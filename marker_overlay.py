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

from gamescope_target import InputUnavailable


class MarkerOverlay:
    def __init__(self, *, display, server_pid):
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket, self.process = parent, None
        self.ready = self.closed = False
        self.checked_at = 0.
        self.size = None
        self.error = None
        self.worker_updates = self.worker_draws = 0
        self.pending = (.5, .5, False)
        self.sent = None
        self._reaper = None
        try:
            env = dict(os.environ, GDK_BACKEND='x11', DISPLAY=display, NO_AT_BRIDGE='1')
            self.process = subprocess.Popen([
                sys.executable, '-B', str(Path(__file__).with_name('marker_worker.py')),
                '--fd', str(child.fileno()), '--display', display,
                '--server-pid', str(server_pid),
            ], env=env, pass_fds=(child.fileno(),), stdin=subprocess.DEVNULL,
               stdout=subprocess.DEVNULL)
            parent.setblocking(False)
        except Exception:
            parent.close()
            raise
        finally:
            child.close()

    def update(self, point, pressed=False):
        if (len(point) != 2 or not all(math.isfinite(n) and 0 <= n <= 1 for n in point)
                or type(pressed) is not bool):
            raise ValueError('invalid marker state')
        self.pending = (*point, pressed)

    def poll(self):
        if self.closed or self.process.poll() is not None:
            raise InputUnavailable('upper marker closed')
        try:
            for _ in range(64):
                try:
                    packet = self.socket.recv(4096)
                except BlockingIOError:
                    break
                state = json.loads(packet)
                if not isinstance(state, dict):
                    raise ValueError('invalid marker reply')
                if state.get('error'):
                    self.error = state['error']
                    raise InputUnavailable(self.error)
                if state.get('ready'):
                    width, height = state['size']
                    if not all(type(n) is int and 1 <= n <= 8192 for n in (width, height)):
                        raise ValueError('invalid marker geometry')
                    self.size, self.ready = (width, height), True
                if state.get('alive'):
                    values = (state.get('updates', 0), state.get('draws', 0))
                    if not all(type(n) is int and 0 <= n < 2**63 for n in values):
                        raise ValueError('invalid marker counters')
                    self.worker_updates, self.worker_draws = values
                self.checked_at = time.monotonic()
            if self.ready and self.pending != self.sent:
                try:
                    self.socket.send(json.dumps(self.pending).encode())
                    self.sent = self.pending
                except BlockingIOError:
                    pass  # Keep the newest unsent state, never a motion queue.
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise InputUnavailable('upper marker IPC unavailable') from error

    def current(self, now):
        return (not self.closed and self.ready and self.process.poll() is None
                and 0 <= now-self.checked_at <= 1.2)

    def close(self):
        if self.closed:
            return
        self.closed, self.ready = True, False
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
