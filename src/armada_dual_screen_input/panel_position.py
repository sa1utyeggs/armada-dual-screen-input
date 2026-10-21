"""Capture-free positioning controller with passive marker and native touch."""
from __future__ import annotations

import os
from pathlib import Path
import time

from .gamescope_target import GamescopeTarget, InputUnavailable
from .gamescope_focus import FocusWatcher
from .marker_overlay import MarkerOverlay
from .input_geometry import Rect
from .native_input import NativeTouchInput
from .position_gesture import PositionGesture
from .direct_touch import DirectTouchGesture, MAX_CONTACTS

TOUCH_MODES = ('position', 'direct')


class PanelPosition:
    pad = Rect(0, 124, 1240, 956)
    hint = '第一指定位 · 第二指按住触摸 · 第一指移动可拖动 · 抬起第二指释放'

    def __init__(self, *, runtime=None, resolve=None, focus_factory=FocusWatcher,
                 marker_factory=MarkerOverlay, native_factory=NativeTouchInput,
                 clock=time.monotonic, sensitivity=2.0, touch_mode='position'):
        if touch_mode not in TOUCH_MODES:
            raise ValueError('unsupported touch mode')
        self.runtime = Path(runtime or os.environ.get('XDG_RUNTIME_DIR', '/nonexistent'))
        self.resolve = resolve or (lambda: GamescopeTarget.resolve(self.runtime))
        self.focus_factory, self.marker_factory = focus_factory, marker_factory
        self.native_factory, self.clock = native_factory, clock
        self.target = self.focus = self.marker = self.sender = self.expected = None
        self.active = self.armed = self.auto_requested = False
        self.message = '触屏尚未打开'
        self.last_error = None
        self.revision = 0
        self.position_gesture = PositionGesture(self.pad, sensitivity=sensitivity)
        self.direct_gesture = DirectTouchGesture(self.pad)
        self.touch_mode = touch_mode
        self.gesture = self.direct_gesture if touch_mode == 'direct' else self.position_gesture
        self._candidate = self._candidate_since = self._clear_since = None
        self._pending_until = self._retry_after = 0.
        self._retired = []
        self.delivered = dict(down=0, move=0, up=0, cancel=0)

    @property
    def enable_label(self):
        return '暂停触摸' if self.armed else '连接中…' if self.auto_requested else '启用触摸'

    def _update_marker(self):
        if not self.marker:
            return
        if self.touch_mode == 'direct':
            self.marker.update_contacts(self.direct_gesture.rings)
        else:
            self.marker.update(self.position_gesture.point, self.position_gesture.held)

    def set_touch_mode(self, mode):
        if mode not in TOUCH_MODES:
            raise ValueError('unsupported touch mode')
        if mode == self.touch_mode:
            return False
        self._close_sender()  # Release every old native contact before changing semantics.
        self.touch_mode = mode
        self.gesture = self.direct_gesture if mode == 'direct' else self.position_gesture
        self.gesture.cancel(self.clock())
        self.auto_requested = self.active
        self._retry_after = 0
        self._update_marker()
        self.message = '模式已切换；抬起所有手指后自动启用'
        return True

    def start(self):
        if self.active:
            return
        self.active, self.auto_requested = True, True
        self._retry_after = 0
        self.message = '正在连接上屏定位标识…'
        try:
            self.target = self.resolve()
            self.focus = self.focus_factory(':0')
            self.focus.start()
        except (OSError, ValueError, InputUnavailable) as error:
            self.last_error = str(error)
            self.message = '无法连接上屏；切换标签后重试'

    def _close_sender(self):
        self.armed, self._pending_until = False, 0
        if self.sender is not None:
            try:
                self.sender.close()
            except (OSError, RuntimeError) as error:
                self.last_error = str(error)
            finally:
                self.sender = None
        self.gesture.cancel(self.clock())
        self._update_marker()
        self._candidate = self._candidate_since = self._clear_since = None
        self.revision += 1

    def pause(self, *, manual=True):
        if manual:
            self.auto_requested = False
        self._close_sender()
        self.message = '触摸已暂停；点击「启用触摸」恢复'

    def stop(self):
        self.pause()
        self.active = False
        if self.focus:
            self.focus.stop()
        if self.marker:
            self.marker.close()
            self._retired.append(self.marker)
        self.target = self.focus = self.marker = self.expected = None

    def wait(self):
        for marker in self._retired:
            marker.wait()
        self._retired.clear()

    def toggle(self):
        if self.auto_requested or self.armed:
            self.pause()
        else:
            self.auto_requested = True
            self._retry_after = 0
            self._candidate = self._candidate_since = self._clear_since = None

    def center(self):
        if self.touch_mode != 'position':
            return
        self._close_sender()
        self.gesture.center(self.clock())
        self._update_marker()
        self.message = '定位已居中；抬手后恢复触摸' if self.auto_requested else '定位已居中；触摸保持暂停'

    def _focus_current(self):
        state = self.focus.latest() if self.focus else None
        now = self.clock()  # Read after the worker snapshot, never before it.
        return bool(state and self.expected and state.matches(self.expected, now)
                    and self.marker and self.marker.current(now))

    def _retry(self, now, error, *, focus_changed=False):
        self.last_error = str(error)
        self._close_sender()
        if self.marker and (not self.marker.current(now) or getattr(self.marker, 'error', None)):
            self.marker.close()
            self._retired.append(self.marker)
            self.marker = None
        # A normal foreground switch only needs the existing stable-target,
        # all-fingers-up and verified-route gates. Keep fault backoff for a
        # lost marker or an actual route/IPC failure.
        self._retry_after = now if focus_changed and self.marker else now+1.5
        self.message = '上屏目标或定位标识变化；抬手后自动恢复' if self.auto_requested else '定位触摸已暂停'

    def touch(self, phase, tid, now, x=0, y=0, *, motion_interval=None):
        if not self.active or not self.armed:
            return
        try:
            if not self._focus_current():
                self._retry(now, InputUnavailable('position target or marker expired'),
                            focus_changed=True)
                return
            events = (self.gesture.begin(tid, x, y, now) if phase == 'begin' else
                      self.gesture.move(tid, x, y, now, motion_interval=motion_interval) if phase == 'move' else
                      self.gesture.end(tid, now) if phase == 'end' else
                      self.gesture.cancel(now))
            for event in events:
                # NativeTouchInput.send checks route, target and readiness for
                # every actual contact. Pure aiming sends no input and does
                # not repeat its filesystem checks on each finger update.
                self.sender.send(event)
                self.delivered[event.kind] += 1
            self._update_marker()
        except (InputUnavailable, OSError, ValueError, RuntimeError) as error:
            self._retry(now, error)

    def tick(self, now=None, *, contacts_down=False):
        if not self.active or self.focus is None or self.target is None:
            return
        # A worker may publish a new snapshot while GTK is ticking.
        requested_now = now
        state = self.focus.latest()
        now = self.clock() if now is None else now
        try:
            if self.sender is None and not self.target.is_current():
                raise InputUnavailable('upper Gamescope instance changed')
            if self.marker:
                self.marker.poll()
            elif now >= self._retry_after and state.snapshot and state.matches(state.snapshot, now):
                self.marker = self.marker_factory(display=':0', server_pid=state.snapshot.server_pid)
                self._update_marker()
            # poll() can receive a heartbeat newer than the pre-poll timestamp.
            # Read the new worker snapshot first, then refresh the clock.
            if requested_now is None:
                state = self.focus.latest()
                now = self.clock()
            if self.armed or self._pending_until:
                if not self._focus_current():
                    self._retry(now, InputUnavailable('upper foreground or marker changed'),
                                focus_changed=True)
                    return
                self.sender.poll()
                if self._pending_until:
                    if contacts_down:
                        self._close_sender()
                        self.message = '请抬起所有手指；随后自动启用'
                    elif self.sender.ready:
                        self.armed, self._pending_until = True, 0
                        self.message = ('直接触屏已启用 · 每根手指独立触摸' if self.touch_mode == 'direct'
                                        else '定位已启用 · 单指定位，第二指确认')
                        if self.touch_mode == 'direct' and self.expected.touch_mode == 1:
                            self.message += ' · 当前应用可能转换为鼠标'
                        self.revision += 1
                    elif now > self._pending_until:
                        raise InputUnavailable('native touch route did not become ready')
                return
            if not self.auto_requested or now < self._retry_after:
                return
            expected = state.snapshot
            if not (self.marker and self.marker.current(now) and expected
                    and state.matches(expected, now)):
                self.message = '正在等待上屏定位标识与前台窗口'
                self._candidate = self._candidate_since = self._clear_since = None
                return
            if expected.touch_mode not in (1, 4) or not expected.compatible(self.marker.size):
                self.message = '当前上屏触摸策略或画面比例暂不支持'
                return
            if self._candidate is None or not self._candidate.same_target(expected):
                self._candidate, self._candidate_since = expected, now
            if contacts_down:
                self._clear_since = None
                self.message = '请抬起所有手指；随后自动启用'
                return
            if self._clear_since is None:
                self._clear_since = now
            if now-self._candidate_since >= .2 and now-self._clear_since >= .08:
                self.expected = expected
                self.marker.restore()
                options = {'max_contacts': MAX_CONTACTS} if self.touch_mode == 'direct' else {}
                self.sender = self.native_factory(self.target, expected, focus_check=self._focus_current,
                                                  **options)
                self._pending_until = now+2
                self.message = '正在确认原生触摸路由…'
        except (InputUnavailable, OSError, ValueError, RuntimeError) as error:
            self._retry(now, error)
