"""Opt-in native contact sender for Game Mode; no mouse or wheel conversion.

Native contact intents use a transient touchscreen. No Steam touch-mode
property is changed. The same Gamescope policy as physical upper-screen touch
applies: mode 4 passes native events; mode 1 maps touch to left pointer input.
Pausing lifts contacts; it cannot undo an application action.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import threading
import time

from .gamescope_target import InputUnavailable
from .native_touch import VirtualTouchProbe


def input_owners(node: Path, *, proc_root='/proc') -> set[int]:
    """Check every process, without allocating a Path for every descriptor.

    This retains the full owner-set check, interval, and expiry. Only directory
    iteration changes; no event node is opened or input data read.
    """
    result = set()
    wanted = os.fspath(node)
    with os.scandir(proc_root) as processes:
        for process in processes:
            if not process.name.isdigit():
                continue
            try:
                with os.scandir(process.path+'/fd') as descriptors:
                    for fd in descriptors:
                        try:
                            if os.readlink(fd.path) == wanted:
                                result.add(int(process.name))
                                break
                        except OSError:
                            pass
            except OSError:
                pass
    return result


class TouchRouteWatch:
    """Read-only hotplug/owner checks off the GTK thread; stale checks expire."""

    def __init__(self, node: Path, primary_pid: int):
        self.node, self.primary_pid = node, primary_pid
        info = node.stat()
        if not stat.S_ISCHR(info.st_mode) or primary_pid <= 0:
            raise InputUnavailable('a verified virtual input node and Gamescope are required')
        self.identity = (info.st_dev, info.st_ino, info.st_rdev)
        self._state = (False, 0.0)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name='native-touch-route', daemon=True)

    def start(self):
        self._thread.start()

    def same_node(self):
        try:
            info = self.node.stat()
            return (info.st_dev, info.st_ino, info.st_rdev) == self.identity
        except OSError:
            return False

    def current(self, now):
        valid, checked = self._state
        return (not self._stop.is_set() and valid and 0 <= now - checked <= .75
                and self.same_node())

    def _run(self):
        while not self._stop.is_set():
            try:
                valid = self.same_node() and input_owners(self.node) == {self.primary_pid}
            except OSError:
                valid = False
            self._state = (valid, time.monotonic())
            self._stop.wait(.25)

    def stop(self):
        self._stop.set()
        self._state = (False, 0.0)


class NativeTouchInput:
    def __init__(self, target, expected, *, focus_check):
        if expected.touch_mode not in (1, 4) or expected.server_pid <= 0:
            raise InputUnavailable('upper target touch policy is not supported')
        self.target, self.focus_check = target, focus_check
        self.touch = self.route = None
        self._closed = self._became_ready = False
        self.held = False
        self.active_contacts = set()
        self.native_events_sent = 0
        self.close_error = None
        try:
            # Verified on Thor: a BUS_VIRTUAL device has no physical connector
            # rotation. Coordinates are already in upper output space.
            self.touch = VirtualTouchProbe(rotation='normal', guard=self._guard)
            self.node = self.touch.node
            self.route = TouchRouteWatch(self.node, expected.server_pid)
            self.route.start()
        except Exception as error:
            self.close()
            if isinstance(error, (InputUnavailable, OSError, ValueError)):
                raise
            raise InputUnavailable(str(error)) from error

    def _guard(self):
        return (not self._closed and self.target.is_current() and self.focus_check()
                and self.route is not None and self.route.current(time.monotonic()))

    @property
    def ready(self):
        return self._guard()

    def poll(self):
        if self._closed or not self.target.is_current() or not self.focus_check():
            raise InputUnavailable('native touch target or application touch policy changed')
        if self._became_ready and not self.route.current(time.monotonic()):
            raise InputUnavailable('virtual touchscreen route changed or check expired')
        if self.ready:
            self._became_ready = True

    def send(self, intent):
        self.poll()
        if not self.ready:
            raise InputUnavailable('native touchscreen is not ready')
        try:
            if intent.kind == 'cancel':
                self.release_all()
            elif intent.kind in ('down', 'move', 'up'):
                tid = intent.contact_id
                if intent.kind == 'down' and tid in self.active_contacts:
                    raise ValueError('native contact is already held')
                if intent.kind == 'move' and tid not in self.active_contacts:
                    raise ValueError('native contact is not held')
                if intent.kind == 'up' and tid not in self.active_contacts:
                    return
                self.touch.contact(intent.kind, tid, *intent.position)
                if intent.kind == 'up':
                    self.active_contacts.discard(tid)
                else:
                    self.active_contacts.add(tid)
                self.held = bool(self.active_contacts)
                self.native_events_sent += 1
            else:
                raise ValueError('unknown native touch intent')
        except RuntimeError as error:
            raise InputUnavailable(str(error)) from error

    def release_all(self):
        try:
            if self.touch:
                self.touch.release_all()
        finally:
            self.held = False
            self.active_contacts.clear()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.route:
            self.route.stop()
        try:
            if self.touch:
                self.touch.close()
        except (OSError, RuntimeError) as error:
            self.close_error = str(error)
        finally:
            self.held = False
            self.active_contacts.clear()
