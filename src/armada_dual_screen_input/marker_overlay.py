"""Bounded local IPC to an input-transparent upper-screen marker process.

Separate GDK backends keep the lower Wayland UI and upper XWayland marker
isolated. Updates are latest-state only; GTK never waits for an X server.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

from .gamescope_target import InputUnavailable
from .marker_state import validate_rings
from .marker_sample import sample_payload
from .marker_target import MarkerTarget
from .marker_frames import read_frame_rate
from .marker_colors import DEFAULT_COLORS, MarkerColors


class MarkerOverlay:
    def __init__(self, *, target, schedule=None, cancel=None, frame_rate='auto', colors=DEFAULT_COLORS):
        if read_frame_rate(frame_rate) != frame_rate:
            raise ValueError('unsupported marker frame rate')
        if not isinstance(colors, MarkerColors):
            raise ValueError('validated marker colors are required')
        self.target = MarkerTarget.from_focus(target)
        if (schedule is None) != (cancel is None):
            raise ValueError('marker dispatch needs both schedule and cancel')
        if schedule is None:
            from gi.repository import GLib
            # Dispatch alongside input/IPC rather than waiting for the next
            # 16 ms health tick. A single source merges one event-loop batch.
            schedule = lambda callback: GLib.idle_add(callback, priority=GLib.PRIORITY_DEFAULT)
            cancel = GLib.source_remove
        self._schedule, self._cancel = schedule, cancel
        self._send_source = self._send_error = None
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket, self.process = parent, None
        self.ready = self.closed = False
        self.checked_at = 0.
        self.size = None
        self.error = None
        self.worker_updates = self.worker_draws = 0
        self.refresh_millihz = 0
        self.window = None
        self.pending = (.5, .5, False)
        self.sent = None
        self._snap_pending = False
        self.restore_pending = False
        self._reaper = None
        try:
            # Scope GL composition to our marker. On Thor the default XRender
            # path can block :0 in a GPU fence wait while moving this overlay,
            # delaying independent focus queries enough to expire input.
            # Our demand-driven pacer follows the upper monitor. Disable the
            # marker's extra Mesa swap wait; Gamescope still composes/scans
            # out the result. Never export either setting to the panel/game.
            env = dict(os.environ, GDK_BACKEND='x11', DISPLAY=self.target.surface_display, NO_AT_BRIDGE='1',
                       GDK_GL='always', vblank_mode='0')
            self.process = subprocess.Popen([
                sys.executable, '-B', '-m', 'armada_dual_screen_input.marker_worker',
                '--fd', str(child.fileno()), '--target', self.target.encode(),
                '--frame-rate', frame_rate,
                '--idle-color', colors.idle, '--pressed-color', colors.pressed,
            ], env=env, pass_fds=(child.fileno(),), stdin=subprocess.DEVNULL,
               stdout=subprocess.DEVNULL)
            parent.setblocking(False)
        except Exception:
            parent.close()
            raise
        finally:
            child.close()

    def update(self, point, pressed=False, *, motion=None):
        if motion is not None:
            self._set_pending(sample_payload(((*point, pressed),), motion))
        else:
            if (len(point) != 2 or not all(math.isfinite(n) and 0 <= n <= 1 for n in point)
                    or type(pressed) is not bool):
                raise ValueError('invalid marker state')
            self._set_pending((*point, pressed))

    def update_contacts(self, contacts, *, motion=None):
        self._set_pending(sample_payload(contacts, motion) if motion is not None
                          else {'contacts': validate_rings(contacts)})

    def _set_pending(self, payload):
        if isinstance(payload, dict) and 'motion' in payload:
            self._snap_pending |= payload['motion']['snap']
            payload['motion']['snap'] = self._snap_pending
            if isinstance(self.pending, dict) and 'motion' in self.pending:
                # A new timestamp alone must not wake a settled ring. Keep
                # lifecycle barriers until their latest state is delivered.
                old, new = self.pending['motion'], payload['motion']
                if (not self._snap_pending
                        and old['ids'] == new['ids'] and old['mode'] == new['mode']
                        and old['active'] == new['active'] and old['snap'] == new['snap']
                        and self.pending['contacts'] == payload['contacts']):
                    return
        self.pending = payload
        self._queue_update()

    def _queue_update(self):
        if (not self.closed and self.ready and self._send_error is None
                and self._send_source is None and self.pending != self.sent):
            self._send_source = self._schedule(self._dispatch_update)

    def _send_pending(self):
        if not self.closed and self.ready and self.pending != self.sent:
            try:
                self.socket.send(json.dumps(self.pending).encode())
                self.sent = self.pending
                self._snap_pending = False
            except BlockingIOError:
                pass  # One latest state; a new event or health tick retries.

    def _dispatch_update(self):
        self._send_source = None
        try:
            self._send_pending()
        except (OSError, ValueError, TypeError) as error:
            # A GLib callback cannot raise into PanelPosition's release path.
            # Invalidate readiness and let its normal poll/guard recover.
            self._send_error = error
        return False

    def _cancel_update(self):
        if self._send_source is not None:
            self._cancel(self._send_source)
            self._send_source = None

    def restore(self):
        """Reassert only our passive window once after input focus returns."""
        self.restore_pending = True

    def matches_focus(self, focus):
        return self.target.matches_focus(focus)

    def owns_focus(self, focus):
        return bool(focus and self.window and focus.window == self.window
                    and focus.surface_display == self.target.surface_display)

    def poll(self):
        if self.closed or self.process.poll() is not None:
            raise InputUnavailable('upper marker closed')
        if self._send_error is not None:
            raise InputUnavailable('upper marker IPC unavailable') from self._send_error
        try:
            for _ in range(64):
                try:
                    packet = self.socket.recv(4096)
                except BlockingIOError:
                    break
                state = json.loads(packet)
                if not isinstance(state, dict):
                    raise ValueError('invalid marker reply')
                if 'window' in state:
                    window = state['window']
                    if type(window) is not int or not 1 < window < 2**32 or window == self.target.window:
                        raise ValueError('invalid marker window')
                    if self.window is not None and window != self.window:
                        raise ValueError('marker window changed')
                    self.window = window
                if state.get('error'):
                    self.error = state['error']
                    raise InputUnavailable(self.error)
                if state.get('ready'):
                    if self.window is None:
                        raise ValueError('marker did not identify its own window')
                    width, height = state['size']
                    if not all(type(n) is int and 1 <= n <= 8192 for n in (width, height)):
                        raise ValueError('invalid marker geometry')
                    self.size, self.ready = (width, height), True
                if state.get('alive'):
                    values = (state.get('updates', 0), state.get('draws', 0))
                    if not all(type(n) is int and 0 <= n < 2**63 for n in values):
                        raise ValueError('invalid marker counters')
                    self.worker_updates, self.worker_draws = values
                if 'refresh_millihz' in state:
                    rate = state['refresh_millihz']
                    if type(rate) is not int or not 30000 <= rate <= 240000:
                        raise ValueError('invalid marker monitor refresh')
                    self.refresh_millihz = rate
                self.checked_at = time.monotonic()
            # Readiness and backpressure still have a bounded periodic retry.
            # Cancel an idle send if this tick delivered its latest state.
            self._cancel_update()
            self._send_pending()
            if self.ready and self.restore_pending:
                try:
                    self.socket.send(b'{"restore":true}')
                    self.restore_pending = False
                except BlockingIOError:
                    pass
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise InputUnavailable('upper marker IPC unavailable') from error

    def current(self, now):
        return (not self.closed and self.ready and self._send_error is None and self.process.poll() is None
                and 0 <= now-self.checked_at <= 1.2)

    def close(self):
        if self.closed:
            return
        self.closed, self.ready = True, False
        self._cancel_update()
        try:
            self.socket.send(b'null')
        except OSError:
            pass
        self.socket.close()
        process = self.process
        if process is not None:
            def reap():
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            self._reaper = threading.Thread(target=reap, name='marker-teardown', daemon=True)
            self._reaper.start()

    def wait(self):
        if self._reaper:
            self._reaper.join(timeout=3)

    def reaped(self):
        return (self.closed and (self._reaper is None or not self._reaper.is_alive())
                and (self.process is None or self.process.poll() is not None))
