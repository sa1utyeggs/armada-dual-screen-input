"""Mouse-compatible absolute input scoped to one Gamescope EIS socket.

No kernel input devices, physical evdev readers, or global pointer settings.
libei is loaded lazily. All calls belong on the same event-loop thread.
"""
from __future__ import annotations

import ctypes as c
import ctypes.util
from dataclasses import dataclass
import math
import os
from pathlib import Path
import socket
import struct

from gamescope_probe import validate_display
from mirrored_touch import TouchIntent


class InputUnavailable(RuntimeError):
    pass


def same_user_peer_pid(fd: int) -> int:
    """Read credentials from an already-connected Unix socket; send no data."""
    with socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        pid, uid, _ = struct.unpack('3i', connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    if pid <= 0 or uid != os.getuid():
        raise InputUnavailable('graphics socket does not belong to the current user')
    return pid


@dataclass(frozen=True)
class GamescopeTarget:
    runtime: Path
    display_name: str
    display_path: Path
    eis_path: Path
    identity: tuple[int, int, int, int]

    @classmethod
    def resolve(cls, runtime: Path, name: str = 'gamescope-primary') -> GamescopeTarget:
        display = validate_display(runtime, name)
        eis = validate_display(runtime, display.name + '-ei')
        a, b = display.stat(), eis.stat()
        return cls(runtime.resolve(), name, display, eis,
                   (a.st_dev, a.st_ino, b.st_dev, b.st_ino))

    def is_current(self) -> bool:
        try:
            return type(self).resolve(self.runtime, self.display_name) == self
        except (OSError, ValueError):
            return False


def load_libei():
    name = ctypes.util.find_library('ei')
    if not name:
        raise InputUnavailable('libei is unavailable')
    api = c.CDLL(name)
    p, u, i, d = c.c_void_p, c.c_uint32, c.c_int, c.c_double
    signatures = {
        'ei_new_sender': (p, [p]), 'ei_unref': (p, [p]),
        'ei_configure_name': (None, [p, c.c_char_p]),
        'ei_setup_backend_socket': (i, [p, c.c_char_p]),
        'ei_setup_backend_fd': (i, [p, i]),
        'ei_get_fd': (i, [p]), 'ei_dispatch': (None, [p]),
        'ei_get_event': (p, [p]), 'ei_event_unref': (p, [p]),
        'ei_event_get_type': (i, [p]), 'ei_event_get_seat': (p, [p]),
        'ei_event_get_device': (p, [p]),
        'ei_seat_has_capability': (c.c_bool, [p, i]),
        'ei_seat_bind_capabilities': (None, [p]),
        'ei_device_ref': (p, [p]), 'ei_device_unref': (p, [p]),
        'ei_device_has_capability': (c.c_bool, [p, i]),
        'ei_device_get_region': (p, [p, c.c_size_t]),
        'ei_device_start_emulating': (None, [p, u]),
        'ei_device_stop_emulating': (None, [p]),
        'ei_device_pointer_motion_absolute': (None, [p, d, d]),
        'ei_device_button_button': (None, [p, u, c.c_bool]),
        'ei_device_scroll_discrete': (None, [p, c.c_int32, c.c_int32]),
        'ei_device_scroll_cancel': (None, [p, c.c_bool, c.c_bool]),
        'ei_device_frame': (None, [p, c.c_uint64]),
        'ei_now': (c.c_uint64, [p]),
    }
    for axis in ('x', 'y', 'width', 'height'):
        signatures['ei_region_get_' + axis] = (u, [p])
    for symbol, (result, arguments) in signatures.items():
        function = getattr(api, symbol)
        function.restype, function.argtypes = result, arguments
    return api


class LibEIInput:
    REQUIRED = (2, 16, 32)  # absolute pointer, scroll, button
    BTN_LEFT = 0x110

    def __init__(self, target: GamescopeTarget, surface_size: tuple[int, int], *,
                 x_server_pid: int = 0, focus_check=None, api=None) -> None:
        if len(surface_size) != 2 or any(type(n) is not int or not 1 <= n <= 8192
                                         for n in surface_size):
            raise ValueError('verified focused-surface dimensions are required')
        self.target = target
        self.surface_size = surface_size
        self.focus_check = focus_check
        self.api = load_libei() if api is None else api
        self.context = self.api.ei_new_sender(None)
        self.devices: dict[int, dict] = {}
        self.held = False
        self.scrolled = False
        self.emulating = False
        self._active_device = None
        self._wheel_remainder = [0.0, 0.0]
        self._closed = False
        if not self.context:
            raise InputUnavailable('could not create an EI sender')
        try:
            self.api.ei_configure_name(self.context, b'Armada Dual Screen Input')
            if api is None:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(0.2)
                    connection.connect(str(target.eis_path))
                    if x_server_pid <= 0 or same_user_peer_pid(connection.fileno()) != x_server_pid:
                        raise InputUnavailable('upper XWayland and EIS belong to different Gamescopes')
                    connection.setblocking(False)
                    # libei takes ownership of this descriptor. ei_get_fd()
                    # instead exposes its event-loop descriptor, not this socket.
                    result = self.api.ei_setup_backend_fd(self.context, connection.detach())
            else:
                result = self.api.ei_setup_backend_socket(self.context, os.fsencode(target.eis_path))
            if result != 0:
                raise InputUnavailable('could not connect to the selected EIS socket')
        except Exception:
            self.api.ei_unref(self.context)
            self._closed = True
            raise

    @property
    def fd(self) -> int:
        return -1 if self._closed else self.api.ei_get_fd(self.context)

    def _selected(self):
        candidates = [(device, info) for device, info in self.devices.items()
                      if info['resumed'] and info['region'] is not None]
        return candidates[0] if len(candidates) == 1 else None

    @property
    def ready(self) -> bool:
        return not self._closed and self._selected() is not None

    def poll(self) -> None:
        if self._closed or not self.target.is_current():
            raise InputUnavailable('input target changed or disconnected')
        if self.focus_check is not None and not self.focus_check():
            raise InputUnavailable('upper foreground window changed')
        self.api.ei_dispatch(self.context)
        for _ in range(256):
            event = self.api.ei_get_event(self.context)
            if not event:
                if self.emulating and (self._selected() is None
                                       or self._selected()[0] != self._active_device):
                    raise InputUnavailable('active input device is no longer unique')
                return
            try:
                kind = self.api.ei_event_get_type(event)
                if kind == 2:
                    for info in self.devices.values():
                        info['resumed'] = False
                    raise InputUnavailable('EIS disconnected')
                if kind == 3:  # seat added
                    seat = self.api.ei_event_get_seat(event)
                    if all(self.api.ei_seat_has_capability(seat, cap) for cap in self.REQUIRED):
                        self.api.ei_seat_bind_capabilities(
                            seat, *(c.c_int(cap) for cap in self.REQUIRED), None)
                elif kind in (5, 6, 7, 8):
                    device = self.api.ei_event_get_device(event)
                    if kind == 5:
                        region = self.api.ei_device_get_region(device, 0)
                        unique_region = region and not self.api.ei_device_get_region(device, 1)
                        supported = all(self.api.ei_device_has_capability(device, cap)
                                        for cap in self.REQUIRED)
                        rectangle = None
                        if unique_region and supported:
                            rectangle = tuple(getattr(self.api, 'ei_region_get_' + axis)(region)
                                              for axis in ('x', 'y', 'width', 'height'))
                            if min(rectangle[2:]) <= 0:
                                rectangle = None
                        self.devices[device] = {
                            'reference': self.api.ei_device_ref(device),
                            'region': rectangle, 'resumed': False,
                        }
                    elif device in self.devices:
                        if kind in (6, 7) and self.emulating:
                            self.devices[device]['resumed'] = False
                            raise InputUnavailable('active input device was removed or paused')
                        if kind == 6:
                            self.api.ei_device_unref(self.devices.pop(device)['reference'])
                        else:
                            self.devices[device]['resumed'] = kind == 8
            finally:
                self.api.ei_event_unref(event)
        raise InputUnavailable('too many pending EIS lifecycle events')

    def send(self, intent: TouchIntent) -> None:
        self.poll()
        selected = self._selected()
        if selected is None:
            raise InputUnavailable('a unique absolute input device is not ready')
        device, info = selected
        u, v = intent.position
        if not all(math.isfinite(n) and 0 <= n <= 1 for n in (u, v)):
            raise ValueError('input coordinates must be normalized')
        if intent.kind not in ('down', 'move', 'up', 'cancel', 'wheel'):
            raise ValueError('unknown input intent')
        if intent.kind == 'cancel':
            self.release_all()
            return
        if intent.kind == 'down' and self.held:
            raise ValueError('button is already held')
        if intent.kind == 'up' and not self.held:
            return
        if intent.kind == 'wheel' and self.held:
            raise ValueError('cannot scroll during a held drag')
        raw = (intent.wheel[0], -intent.wheel[1])
        if intent.kind == 'wheel' and not all(math.isfinite(n) and abs(n) <= 12000 for n in raw):
            raise ValueError('invalid wheel displacement')
        if not self.emulating:
            self.api.ei_device_start_emulating(device, 1)
            self.emulating = True
            self._active_device = device
        # Gamescope's INT32_MAX EI region is a placeholder, not a normalized
        # coordinate domain. InputEmulation.cpp forwards these values directly
        # to wlserver_mousewarp(), in focused-surface pixels.
        width, height = self.surface_size
        self.api.ei_device_pointer_motion_absolute(device, u * (width - 1),
                                                  v * (height - 1))
        if intent.kind == 'down':
            self.api.ei_device_button_button(device, self.BTN_LEFT, True)
            self.held = True
        elif intent.kind == 'up':
            if self.held:
                self.api.ei_device_button_button(device, self.BTN_LEFT, False)
            self.held = False
        elif intent.kind == 'wheel':
            # Intent Y uses evdev wheel-up-positive; EI Y is down-positive.
            integer = []
            for axis, value in enumerate(raw):
                if value * self._wheel_remainder[axis] < 0:
                    self._wheel_remainder[axis] = 0.0
                self._wheel_remainder[axis] += value
                integer.append(math.trunc(self._wheel_remainder[axis]))
                self._wheel_remainder[axis] -= integer[-1]
            if any(integer):
                self.api.ei_device_scroll_discrete(device, *integer)
                self.scrolled = True
        self.api.ei_device_frame(device, self.api.ei_now(self.context))

    def release_all(self) -> None:
        active = self.devices.get(self._active_device)
        if not self._closed and active and active['resumed'] and self.emulating:
            device = self._active_device
            if self.held:
                self.api.ei_device_button_button(device, self.BTN_LEFT, False)
            if self.scrolled:
                self.api.ei_device_scroll_cancel(device, True, True)
            if self.held or self.scrolled:
                self.api.ei_device_frame(device, self.api.ei_now(self.context))
        self.held = self.scrolled = False
        self._wheel_remainder = [0.0, 0.0]

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.release_all()
            active = self.devices.get(self._active_device)
            if self.emulating and active and active['resumed']:
                self.api.ei_device_stop_emulating(self._active_device)
        finally:
            for info in self.devices.values():
                self.api.ei_device_unref(info['reference'])
            self.devices.clear()
            self.api.ei_unref(self.context)
            self._closed = True
