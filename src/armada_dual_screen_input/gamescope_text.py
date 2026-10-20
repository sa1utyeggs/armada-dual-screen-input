"""Version-bounded Gamescope text adapter for the isolated keyboard worker.

Gamescope's input-method protocol is PRIVATE, not a portable Wayland API.
Keep this dependency separate from layout/IME/UI code. It is never used in
Desktop Mode, never sends pointer input, and never changes Steam services.
Protocol: ValveSoftware/gamescope/protocol/gamescope-input-method.xml.
Only its version-1 text subset is bound; unavailable/unknown routes fail closed.
"""
from __future__ import annotations

import ctypes as c
import ctypes.util
from pathlib import Path

from .gamescope_focus import UpperFocus
from .gamescope_target import GamescopeTarget, InputUnavailable, same_user_peer_pid


class _Interface(c.Structure):
    pass


class _Message(c.Structure):
    _fields_ = [("name", c.c_char_p), ("signature", c.c_char_p),
                ("types", c.POINTER(c.POINTER(_Interface)))]


_Interface._fields_ = [("name", c.c_char_p), ("version", c.c_int),
                      ("method_count", c.c_int), ("methods", c.POINTER(_Message)),
                      ("event_count", c.c_int), ("events", c.POINTER(_Message))]


class GamescopeText:
    def __init__(self, runtime, *, display="gamescope-primary", xdisplay=":0"):
        self.display = self.manager = self.ime = None
        self.upper = None
        self.serial = None
        self.available = True
        self.target = GamescopeTarget.resolve(Path(runtime), display)
        library = ctypes.util.find_library("wayland-client")
        if library is None:
            raise InputUnavailable("System libwayland-client is unavailable")
        self.lib = c.CDLL(library)
        for name, args, result in (
            ("wl_display_connect", [c.c_char_p], c.c_void_p),
            ("wl_display_disconnect", [c.c_void_p], None),
            ("wl_display_get_fd", [c.c_void_p], c.c_int),
            ("wl_display_roundtrip", [c.c_void_p], c.c_int),
            ("wl_proxy_marshal_constructor_versioned",
             [c.c_void_p, c.c_uint32, c.POINTER(_Interface), c.c_uint32], c.c_void_p),
            ("wl_proxy_marshal", [c.c_void_p, c.c_uint32], None),
            ("wl_proxy_add_listener", [c.c_void_p, c.POINTER(c.c_void_p), c.c_void_p], c.c_int),
        ):
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        try:
            self.display = self.lib.wl_display_connect(bytes(self.target.display_path))
            if not self.display:
                raise InputUnavailable("Could not connect to upper Gamescope")
            self.peer_pid = same_user_peer_pid(self.lib.wl_display_get_fd(self.display))
            self.upper = UpperFocus(xdisplay)
            if self.upper.server_pid != self.peer_pid:
                raise InputUnavailable("Text and keyboard focus belong to different compositors")
            self._bind()
        except Exception:
            self.close()
            raise

    def _roundtrip(self):
        if self.lib.wl_display_roundtrip(self.display) < 0:
            raise InputUnavailable("Gamescope text connection was lost")

    def _listen(self, proxy, *callbacks):
        table = (c.c_void_p * len(callbacks))(*(c.cast(cb, c.c_void_p) for cb in callbacks))
        self._keep.extend((table, *callbacks))
        if self.lib.wl_proxy_add_listener(proxy, table, None) != 0:
            raise InputUnavailable("Could not register a text protocol listener")

    def _bind(self):
        self._keep = []
        interface = lambda name: _Interface.in_dll(self.lib, name + "_interface")
        registry_type, seat_type = interface("wl_registry"), interface("wl_seat")
        constructor = self.lib.wl_proxy_marshal_constructor_versioned
        registry = constructor(self.display, 1, c.byref(registry_type), 1, None)
        globals_ = []
        global_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_uint32, c.c_char_p, c.c_uint32)
        remove_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_uint32)

        @global_cb
        def found(_data, _proxy, name, kind, version):
            globals_.append((name, kind.decode("ascii"), version))

        @remove_cb
        def removed(_data, _proxy, name):
            globals_[:] = [item for item in globals_ if item[0] != name]

        self._listen(registry, found, removed)
        self._roundtrip()
        seats = [item for item in globals_ if item[1] == "wl_seat"]
        managers = [item for item in globals_ if item[1] == "gamescope_input_method_manager"]
        if len(seats) != 1 or len(managers) != 1 or managers[0][2] not in (1, 2, 3):
            raise InputUnavailable("Supported Gamescope text protocol/seat is unavailable")
        ime_methods = (_Message * 4)(
            _Message(b"destroy", b"", None), _Message(b"commit", b"u", None),
            _Message(b"set_string", b"s", None), _Message(b"set_action", b"u", None))
        ime_events = (_Message * 2)(_Message(b"unavailable", b"", None),
                                    _Message(b"done", b"u", None))
        ime_type = _Interface(b"gamescope_input_method", 1, 4, ime_methods, 2, ime_events)
        create_types = (c.POINTER(_Interface) * 2)(c.pointer(seat_type), c.pointer(ime_type))
        manager_methods = (_Message * 2)(
            _Message(b"destroy", b"", None), _Message(b"create_input_method", b"on", create_types))
        manager_type = _Interface(b"gamescope_input_method_manager", 1, 2, manager_methods, 0, None)
        self._keep.extend((registry_type, seat_type, ime_methods, ime_events, ime_type,
                           create_types, manager_methods, manager_type))

        def bind(item, descriptor):
            return constructor(registry, 0, c.byref(descriptor), 1,
                               c.c_uint32(item[0]), c.c_char_p(item[1].encode()), c.c_uint32(1), None)

        seat = bind(seats[0], seat_type)
        self.manager = bind(managers[0], manager_type)
        if not seat or not self.manager:
            raise InputUnavailable("Could not bind the Gamescope text interface")
        capabilities_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_uint32)
        name_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_char_p)
        self._listen(seat, capabilities_cb(lambda *_: None), name_cb(lambda *_: None))
        self.ime = constructor(self.manager, 1, c.byref(ime_type), 1, c.c_void_p(seat), None)
        if not self.ime:
            raise InputUnavailable("Could not create the text input route")
        unavailable_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p)
        done_cb = c.CFUNCTYPE(None, c.c_void_p, c.c_void_p, c.c_uint32)

        @unavailable_cb
        def unavailable(*_):
            self.available = False

        @done_cb
        def done(_data, _proxy, serial):
            self.serial = serial

        self._listen(self.ime, unavailable, done)
        self._roundtrip()
        if not self.available or self.serial is None:
            raise InputUnavailable("Gamescope text route is occupied or unavailable")

    def focus(self):
        if not self.target.is_current() or not self.available:
            raise InputUnavailable("Upper Gamescope changed or text route became unavailable")
        snapshot = self.upper.snapshot()
        if not snapshot.input_in_surface or snapshot.input_window in (0, 1):
            raise InputUnavailable("No usable upper text target has focus")
        return snapshot

    def matches(self, expected):
        current = self.focus()
        return (current.same_target(expected)
                and current.input_window == expected.input_window)

    def commit(self, text, expected):
        if not isinstance(text, str) or not text or "\0" in text or len(text.encode()) > 1024:
            raise ValueError("Invalid or oversized text commit")
        self._roundtrip()
        if not self.matches(expected):
            raise InputUnavailable("Upper input target changed")
        self.lib.wl_proxy_marshal(self.ime, 2, c.c_char_p(text.encode("utf-8")))
        self.lib.wl_proxy_marshal(self.ime, 1, c.c_uint32(self.serial))
        self._roundtrip()

    def action(self, action, expected):
        if action not in (1, 2, 3, 4, 5):
            raise ValueError("Unsupported version-1 editing action")
        self._roundtrip()
        if not self.matches(expected):
            raise InputUnavailable("Upper input target changed")
        self.lib.wl_proxy_marshal(self.ime, 3, c.c_uint32(action))
        self.lib.wl_proxy_marshal(self.ime, 1, c.c_uint32(self.serial))
        self._roundtrip()

    def close(self):
        if self.upper is not None:
            self.upper.close()
            self.upper = None
        if self.display:
            self.lib.wl_display_disconnect(self.display)
            self.display = self.manager = self.ime = None
