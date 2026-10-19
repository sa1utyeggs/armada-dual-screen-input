"""Read Gamescope's upper XWayland focus without changing it.

XCB returns errors on a lost X server instead of Xlib's process-wide exit.
Only local display names supplied by the launcher are accepted. No window
titles, process command lines, typed input or image content are recorded.
"""
from __future__ import annotations

import ctypes as c
import ctypes.util
from dataclasses import dataclass
import re
import threading
import time

from ei_input import InputUnavailable, same_user_peer_pid


@dataclass(frozen=True)
class FocusSnapshot:
    window: int
    app_id: int
    graphics_app_id: int
    width: int
    height: int
    server_pid: int = 0
    surface_display: str = ''
    input_window: int = 0
    input_in_surface: bool = True

    def compatible(self, source_size: tuple[int, int]) -> bool:
        # The first prototype supports a full-frame, matching-aspect surface.
        # Letterboxing/cropping/zoom require the compositor's actual transform.
        w, h = source_size
        return (self.window > 0 and self.app_id == self.graphics_app_id and self.input_in_surface
                and 0 < self.width <= 8192 and 0 < self.height <= 8192
                and w > 0 and h > 0
                and abs(self.width / self.height - w / h) / (w / h) < 0.005)


class Cookie(c.Structure):
    _fields_ = [('sequence', c.c_uint)]


class Iterator(c.Structure):
    _fields_ = [('data', c.c_void_p), ('rem', c.c_int), ('index', c.c_int)]


class Geometry(c.Structure):
    _fields_ = [('response_type', c.c_uint8), ('depth', c.c_uint8),
               ('sequence', c.c_uint16), ('length', c.c_uint32),
               ('root', c.c_uint32), ('x', c.c_int16), ('y', c.c_int16),
               ('width', c.c_uint16), ('height', c.c_uint16),
               ('border_width', c.c_uint16)]


class UpperFocus:
    """One worker-thread connection. Never call X reply waits on the GTK thread."""

    PROPERTIES = ('GAMESCOPE_FOCUSED_WINDOW', 'GAMESCOPE_FOCUSED_APP',
                  'GAMESCOPE_FOCUSED_APP_GFX')

    DISPLAY_PROPERTIES = ('GAMESCOPE_FOCUS_DISPLAY', 'GAMESCOPE_MOUSE_FOCUS_DISPLAY')

    def __init__(self, display: str, *, _controller=None) -> None:
        if not re.fullmatch(r':[0-9]+(?:\.[0-9]+)?', display):
            raise ValueError('an explicit local upper XWayland display is required')
        name = ctypes.util.find_library('xcb')
        if not name:
            raise InputUnavailable('libxcb is unavailable')
        self.api = c.CDLL(name)
        self.display = display
        self.surface_connection = None
        self.libc = c.CDLL(None)
        self.libc.free.argtypes = [c.c_void_p]
        p, u = c.c_void_p, c.c_uint32
        signatures = {
            'xcb_connect': (p, [c.c_char_p, c.POINTER(c.c_int)]),
            'xcb_disconnect': (None, [p]), 'xcb_connection_has_error': (c.c_int, [p]),
            'xcb_get_setup': (p, [p]), 'xcb_setup_roots_iterator': (Iterator, [p]),
            'xcb_get_file_descriptor': (c.c_int, [p]),
            'xcb_screen_next': (None, [c.POINTER(Iterator)]),
            'xcb_intern_atom': (Cookie, [p, c.c_uint8, c.c_uint16, c.c_char_p]),
            'xcb_intern_atom_reply': (p, [p, Cookie, c.POINTER(p)]),
            'xcb_get_property': (Cookie, [p, c.c_uint8, u, u, u, u, u]),
            'xcb_get_property_reply': (p, [p, Cookie, c.POINTER(p)]),
            'xcb_get_property_value': (p, [p]),
            'xcb_get_property_value_length': (c.c_int, [p]),
            'xcb_get_geometry': (Cookie, [p, u]),
            'xcb_get_geometry_reply': (p, [p, Cookie, c.POINTER(p)]),
            'xcb_get_input_focus': (Cookie, [p]),
            'xcb_get_input_focus_reply': (p, [p, Cookie, c.POINTER(p)]),
            'xcb_query_tree': (Cookie, [p, u]),
            'xcb_query_tree_reply': (p, [p, Cookie, c.POINTER(p)]),
        }
        for symbol, (result, arguments) in signatures.items():
            function = getattr(self.api, symbol)
            function.restype, function.argtypes = result, arguments
        screen = c.c_int()
        self.connection = self.api.xcb_connect(display.encode(), c.byref(screen))
        try:
            if self.api.xcb_connection_has_error(self.connection):
                raise InputUnavailable('upper XWayland display cannot be opened')
            self.server_pid = same_user_peer_pid(self.api.xcb_get_file_descriptor(self.connection))
            if _controller is not None and self.server_pid != _controller.server_pid:
                raise InputUnavailable('focused XWayland belongs to a different Gamescope')
            it = self.api.xcb_setup_roots_iterator(self.api.xcb_get_setup(self.connection))
            for _ in range(screen.value):
                self.api.xcb_screen_next(c.byref(it))
            if it.rem < 1:
                raise InputUnavailable('upper XWayland screen is unavailable')
            self.root = c.c_uint32.from_address(it.data).value
            self.atoms = {}
            for name in (() if _controller else self.PROPERTIES + self.DISPLAY_PROPERTIES):
                encoded = name.encode()
                cookie = self.api.xcb_intern_atom(self.connection, True, len(encoded), encoded)
                reply = self._reply('xcb_intern_atom_reply', cookie)
                try:
                    atom = c.c_uint32.from_address(reply + 8).value
                    if not atom:
                        raise InputUnavailable('selected display is not a Gamescope root')
                    self.atoms[name] = atom
                finally:
                    self.libc.free(reply)
        except Exception:
            self.close()
            raise

    def _reply(self, name, cookie):
        error = c.c_void_p()
        reply = getattr(self.api, name)(self.connection, cookie, c.byref(error))
        if error or not reply:
            self.libc.free(error)
            self.libc.free(reply)
            raise InputUnavailable('upper focus query failed or disconnected')
        return reply

    def snapshot(self) -> FocusSnapshot:
        if not self.connection or self.api.xcb_connection_has_error(self.connection):
            raise InputUnavailable('upper XWayland disconnected')
        # Queue all requests before awaiting the first reply.
        cookies = [self.api.xcb_get_property(self.connection, False, self.root,
                                           self.atoms[name], 0, 0, 1)
                   for name in self.PROPERTIES]
        values = []
        for cookie in cookies:
            reply = self._reply('xcb_get_property_reply', cookie)
            try:
                fmt = c.c_uint8.from_address(reply + 1).value
                if fmt != 32 or self.api.xcb_get_property_value_length(reply) != 4:
                    raise InputUnavailable('Gamescope focus property is unavailable')
                values.append(c.c_uint32.from_address(
                    self.api.xcb_get_property_value(reply)).value)
            finally:
                self.libc.free(reply)
        surface_display = self._display_property('GAMESCOPE_FOCUS_DISPLAY')
        if self._display_property('GAMESCOPE_MOUSE_FOCUS_DISPLAY') != surface_display:
            raise InputUnavailable('visible and mouse-focus XWayland displays differ')
        surface = self
        if surface_display != self.display:
            if self.surface_connection is None or self.surface_connection.display != surface_display:
                if self.surface_connection:
                    self.surface_connection.close()
                self.surface_connection = UpperFocus(surface_display, _controller=self)
            surface = self.surface_connection
        cookie = surface.api.xcb_get_geometry(surface.connection, values[0])
        reply = surface._reply('xcb_get_geometry_reply', cookie)
        try:
            geometry = Geometry.from_address(reply)
            width, height = geometry.width, geometry.height
        finally:
            self.libc.free(reply)
        input_window, input_in_surface = surface._input_focus(values[0])
        return FocusSnapshot(*values, width, height, self.server_pid, surface_display,
                             input_window, input_in_surface)

    def _display_property(self, name: str) -> str:
        cookie = self.api.xcb_get_property(self.connection, False, self.root,
                                           self.atoms[name], 0, 0, 16)
        reply = self._reply('xcb_get_property_reply', cookie)
        try:
            length = self.api.xcb_get_property_value_length(reply)
            if not 0 < length <= 64:
                raise InputUnavailable('focused XWayland display is unavailable')
            # Gamescope publishes a C string through a CARDINAL property;
            # trailing values past its NUL are not part of the display name.
            raw = c.string_at(self.api.xcb_get_property_value(reply), length).split(b'\0', 1)[0]
            value = raw.decode('ascii')
            if not re.fullmatch(r':[0-9]+(?:\.[0-9]+)?', value):
                raise InputUnavailable('focused display is not a local XWayland server')
            return value
        finally:
            self.libc.free(reply)

    def _input_focus(self, surface: int) -> tuple[int, bool]:
        cookie = self.api.xcb_get_input_focus(self.connection)
        reply = self._reply('xcb_get_input_focus_reply', cookie)
        try:
            original = c.c_uint32.from_address(reply + 8).value
        finally:
            self.libc.free(reply)
        window = original
        for _ in range(32):
            if window == surface:
                return original, True
            if window in (0, 1, self.root):
                break
            cookie = self.api.xcb_query_tree(self.connection, window)
            reply = self._reply('xcb_query_tree_reply', cookie)
            try:
                window = c.c_uint32.from_address(reply + 12).value
            finally:
                self.libc.free(reply)
        return original, False

    def close(self) -> None:
        if self.surface_connection:
            self.surface_connection.close()
            self.surface_connection = None
        if self.connection:
            self.api.xcb_disconnect(self.connection)
            self.connection = None


@dataclass(frozen=True)
class FocusState:
    snapshot: FocusSnapshot | None
    received_at: float
    error: str | None = None

    def matches(self, expected: FocusSnapshot, now: float) -> bool:
        return (self.error is None and self.snapshot == expected
                and 0 <= now - self.received_at <= 0.2)


class FocusWatcher:
    """Only the latest focus state crosses to GTK; stalled queries expire."""

    def __init__(self, display: str) -> None:
        self.display = display
        self._state = FocusState(None, 0, 'waiting for upper focus')
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name='upper-focus', daemon=True)

    def start(self) -> None:
        self._thread.start()

    def latest(self) -> FocusState:
        with self._lock:
            return self._state

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        focus = None
        try:
            focus = UpperFocus(self.display)
            while not self._stop.is_set():
                try:
                    state = FocusState(focus.snapshot(), time.monotonic())
                except InputUnavailable as error:
                    state = FocusState(None, time.monotonic(), str(error))
                with self._lock:
                    self._state = state
                self._stop.wait(1 / 60)
        except (InputUnavailable, OSError, ValueError) as error:
            with self._lock:
                self._state = FocusState(None, time.monotonic(), str(error))
        finally:
            if focus is not None:
                focus.close()
