"""Transient Type B touchscreen for the probe and opt-in native preview.

Creates its own transient uinput device through libevdev. Never opens physical
input devices, changes udev rules, or sends mouse buttons. Callers must verify
the route and foreground target before every contact update.
Releasing uinput contacts is a lift, not a true Wayland touch cancellation.
"""
from __future__ import annotations

import ctypes as c
import ctypes.util
import math
import os
from pathlib import Path


EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, BTN_TOUCH = 0, 0x14a
ABS_X, ABS_Y = 0, 1
ABS_MT_SLOT, ABS_MT_X, ABS_MT_Y, ABS_MT_ID = 0x2f, 0x35, 0x36, 0x39
INPUT_PROP_DIRECT = 1
MAX_COORD = 65535


def screen_to_raw(u: float, v: float, rotation: str) -> tuple[int, int]:
    if not all(math.isfinite(n) and 0 <= n <= 1 for n in (u, v)):
        raise ValueError('normalized screen coordinates are required')
    # Inverse of Gamescope apply_touchscreen_orientation(). These transforms
    # still require a matching-aspect full-frame surface and device validation.
    transforms = {'normal': (u, v), 'right': (v, 1 - u),
                  'inverted': (1 - u, 1 - v), 'left': (1 - v, u)}
    if rotation not in transforms:
        raise ValueError('explicit verified panel rotation is required')
    return tuple(round(value * MAX_COORD) for value in transforms[rotation])


class TouchSequence:
    """Encode a bounded number of independently tracked Type B slots; no I/O."""

    def __init__(self, rotation: str, *, max_contacts=2):
        screen_to_raw(.5, .5, rotation)
        if type(max_contacts) is not int or not 1 <= max_contacts <= 10:
            raise ValueError('invalid native contact capacity')
        self.rotation = rotation
        self.max_contacts = max_contacts
        self.contacts: dict[int, tuple[int, int, int]] = {}
        self.next_tracking = 1

    def down(self, tid: int, u: float, v: float):
        x, y = screen_to_raw(u, v, self.rotation)
        if tid in self.contacts or len(self.contacts) >= self.max_contacts:
            raise ValueError('duplicate or excessive contact')
        slots = {entry[0] for entry in self.contacts.values()}
        slot = next(n for n in range(self.max_contacts) if n not in slots)
        first = not self.contacts
        self.contacts[tid] = (slot, x, y)
        events = [(EV_KEY, BTN_TOUCH, 1)] if first else []
        events += [(EV_ABS, ABS_MT_SLOT, slot),
                   (EV_ABS, ABS_MT_ID, self.next_tracking),
                   (EV_ABS, ABS_MT_X, x), (EV_ABS, ABS_MT_Y, y)]
        self.next_tracking = self.next_tracking % 65535 + 1
        if first:
            events += [(EV_ABS, ABS_X, x), (EV_ABS, ABS_Y, y)]
        return tuple(events + [(EV_SYN, SYN_REPORT, 0)])

    def move(self, tid: int, u: float, v: float):
        x, y = screen_to_raw(u, v, self.rotation)
        if tid not in self.contacts:
            raise ValueError('contact is not active')
        slot, _, _ = self.contacts[tid]
        self.contacts[tid] = (slot, x, y)
        events = [(EV_ABS, ABS_MT_SLOT, slot), (EV_ABS, ABS_MT_X, x), (EV_ABS, ABS_MT_Y, y)]
        if tid == next(iter(self.contacts)):
            events += [(EV_ABS, ABS_X, x), (EV_ABS, ABS_Y, y)]
        return tuple(events + [(EV_SYN, SYN_REPORT, 0)])

    def up(self, tid: int):
        if tid not in self.contacts:
            raise ValueError('contact is not active')
        slot, _, _ = self.contacts.pop(tid)
        events = [(EV_ABS, ABS_MT_SLOT, slot), (EV_ABS, ABS_MT_ID, -1)]
        if not self.contacts:
            events.append((EV_KEY, BTN_TOUCH, 0))
        else:
            _, x, y = next(iter(self.contacts.values()))
            events += [(EV_ABS, ABS_X, x), (EV_ABS, ABS_Y, y)]
        return tuple(events + [(EV_SYN, SYN_REPORT, 0)])

    def release_all(self):
        events = ()
        for tid in tuple(self.contacts):
            events += self.up(tid)
        return events


class AbsInfo(c.Structure):
    _fields_ = [(field, c.c_int32) for field in
                ('value', 'minimum', 'maximum', 'fuzz', 'flat', 'resolution')]


class VirtualTouchProbe:
    """Creation sends no contacts. Destroying this object removes its device."""

    def __init__(self, *, rotation: str, guard, max_contacts=2):
        if not callable(guard):
            raise ValueError('an explicit route and foreground guard is required')
        self.sequence = TouchSequence(rotation, max_contacts=max_contacts)
        self.guard = guard
        self.device = self.uinput = None
        name = ctypes.util.find_library('evdev')
        if not name:
            raise RuntimeError('libevdev is unavailable')
        self.api = c.CDLL(name)
        p, u = c.c_void_p, c.c_uint
        signatures = {
            'libevdev_new': (p, []), 'libevdev_free': (None, [p]),
            'libevdev_set_name': (None, [p, c.c_char_p]),
            'libevdev_set_phys': (None, [p, c.c_char_p]),
            'libevdev_set_id_bustype': (None, [p, c.c_int]),
            'libevdev_enable_property': (c.c_int, [p, u]),
            'libevdev_enable_event_type': (c.c_int, [p, u]),
            'libevdev_enable_event_code': (c.c_int, [p, u, u, p]),
            'libevdev_uinput_create_from_device': (c.c_int, [p, c.c_int, c.POINTER(p)]),
            'libevdev_uinput_destroy': (None, [p]),
            'libevdev_uinput_get_devnode': (c.c_char_p, [p]),
            'libevdev_uinput_write_event': (c.c_int, [p, u, u, c.c_int]),
        }
        for symbol, (result, arguments) in signatures.items():
            function = getattr(self.api, symbol)
            function.restype, function.argtypes = result, arguments
        try:
            self.device = self.api.libevdev_new()
            if not self.device:
                raise RuntimeError('cannot allocate libevdev device')
            self.api.libevdev_set_name(self.device, f'Armada native touch probe {os.getpid()}'.encode())
            self.api.libevdev_set_phys(self.device, b'armada-dual-screen-input/probe')
            self.api.libevdev_set_id_bustype(self.device, 6)  # BUS_VIRTUAL
            self._check(self.api.libevdev_enable_property(self.device, INPUT_PROP_DIRECT))
            for kind in (EV_KEY, EV_ABS):
                self._check(self.api.libevdev_enable_event_type(self.device, kind))
            self._check(self.api.libevdev_enable_event_code(self.device, EV_KEY, BTN_TOUCH, None))
            for axis in (ABS_X, ABS_Y, ABS_MT_SLOT, ABS_MT_X, ABS_MT_Y, ABS_MT_ID):
                maximum = self.sequence.max_contacts-1 if axis == ABS_MT_SLOT else MAX_COORD
                info = AbsInfo(0, 0, maximum, 0, 0, 0)
                self._check(self.api.libevdev_enable_event_code(
                    self.device, EV_ABS, axis, c.byref(info)))
            ui = c.c_void_p()
            self._check(self.api.libevdev_uinput_create_from_device(self.device, -2, c.byref(ui)))
            self.uinput = ui.value
            node = self.api.libevdev_uinput_get_devnode(self.uinput)
            if not node:
                raise RuntimeError('created touchscreen has no event node')
            self.node = Path(os.fsdecode(node))
        except Exception:
            self.close()
            raise

    @staticmethod
    def _check(result):
        if result < 0:
            raise OSError(-result, os.strerror(-result))

    def _write(self, events):
        if self.uinput is None:
            raise RuntimeError('touchscreen is closed')
        for event in events:
            self._check(self.api.libevdev_uinput_write_event(self.uinput, *event))

    def contact(self, phase: str, tid: int, u: float = 0, v: float = 0):
        if not self.guard():
            self.release_all()
            raise RuntimeError('touch route or own test window changed')
        if phase not in ('down', 'move', 'up'):
            raise ValueError('unknown native touch phase')
        events = (self.sequence.up(tid) if phase == 'up' else
                  getattr(self.sequence, phase)(tid, u, v))
        try:
            self._write(events)
        except Exception:
            self.close()
            raise

    def release_all(self):
        if self.uinput is not None:
            self._write(self.sequence.release_all())

    def close(self):
        try:
            self.release_all()
        finally:
            if self.uinput is not None:
                self.api.libevdev_uinput_destroy(self.uinput)
                self.uinput = None
            if self.device is not None:
                self.api.libevdev_free(self.device)
                self.device = None
