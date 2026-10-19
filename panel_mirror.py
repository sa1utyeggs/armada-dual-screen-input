"""Mirrored input lifecycle for the normal panel; no GTK or hardware on import.

Only the mirror page starts capture. Discovery and capture teardown never block
GTK. Input always starts paused and is destroyed on a mode/visibility handoff.
"""
from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, SimpleQueue
import threading
import time

from ei_input import GamescopeTarget, InputUnavailable, LibEIInput
from gamescope_focus import FocusWatcher
from gamescope_probe import probe_display
from mirror_capture import MirrorCapture, SourceMonitor
from mirror_geometry import Rect
from mirror_session import MirrorSession
from mirrored_touch import MirroredTouch
from native_gesture import NativeMirroredTouch
from native_input import NativeTouchInput


class PausedSender:
    ready = False
    def poll(self): pass
    def release_all(self): pass
    def close(self): pass


class PanelMirror:
    # Same logical coordinates as the panel's ToolkitTouch/Cairo canvas.
    viewport = Rect(12, 190, 1216, 820)

    def __init__(self, *, runtime=None, discover=None, capture_factory=MirrorCapture,
                 source_factory=SourceMonitor, focus_factory=FocusWatcher,
                 native_factory=NativeTouchInput, mouse_factory=LibEIInput):
        self.runtime = Path(runtime or os.environ.get('XDG_RUNTIME_DIR', '/nonexistent'))
        self.discover = discover or self._discover
        self.capture_factory, self.source_factory = capture_factory, source_factory
        self.focus_factory = focus_factory
        self.native_factory, self.mouse_factory = native_factory, mouse_factory
        self.active = False
        self.input_mode = 'native'
        self.session = MirrorSession(PausedSender())
        self.capture = self.source = self.focus = self.target = None
        self.expected = None
        self.pending_until = 0.0
        self.message = '同屏触摸尚未打开'
        self.last_error = None
        self._frame_seen = False
        self._bootstrap_result = SimpleQueue()
        self._retired = []
        self.revision = 0

    def _discover(self):
        target = GamescopeTarget.resolve(self.runtime)
        result = probe_display(self.runtime, target.display_name, timeout=1.0)
        if result.get('status') != 'node_advertised':
            raise InputUnavailable('upper Gamescope has no capture node')
        return target, result['pipewire_node_id']

    def start(self):
        if self.active:
            return
        self.active = True
        self.message, self.last_error = '正在连接上屏画面…', None
        self._frame_seen = False
        self.session = MirrorSession(PausedSender())
        # Wait for any prior pipeline off GTK; never attach overlapping capture
        # consumers when the user switches tabs rapidly.
        self._retired = [capture for capture in self._retired if not capture.wait(0)]
        retired, result = tuple(self._retired), SimpleQueue()
        self._bootstrap_result = result

        def prepare():
            try:
                if any(not capture.wait(2.0) for capture in retired):
                    raise InputUnavailable('previous capture is still stopping')
                result.put((self.discover(), None))
            except Exception as error:
                result.put((None, str(error)))
        threading.Thread(target=prepare, name='mirror-discovery', daemon=True).start()

    @property
    def armed(self):
        return self.active and self.session.armed

    @property
    def frame(self):
        return self.capture.frames.latest() if self.capture else None

    def cached_current(self, now):
        return bool(self.capture and self.source and self.capture.healthy(now)
                    and self.source.current(now))

    def pause(self, message='触摸已暂停；请抬手后重新启用'):
        self.pending_until = 0
        self.session.pause(time.monotonic())
        self.session.sender.close()
        self.message = message
        self.revision += 1

    def stop(self):
        self.pause()
        self.active = False
        capture, source, focus = self.capture, self.source, self.focus
        self.capture = self.source = self.focus = self.target = None
        self.expected = None
        self.session = MirrorSession(PausedSender())
        if focus:
            focus.stop()
        if source:
            source.stop()
        if capture:
            capture.stop()
            self._retired.append(capture)

            def reap():
                if capture.wait():
                    capture.frames.clear()
                if source:
                    source.wait()
            threading.Thread(target=reap, name='mirror-teardown', daemon=True).start()

    def wait(self):
        """Final process teardown only; tab/visibility changes never wait."""
        for capture in self._retired:
            if capture.wait():
                capture.frames.clear()

    def set_input_mode(self, mode):
        if mode not in ('native', 'mouse'):
            return
        self.pause('输入方式已切换；请重新启用触摸')
        self.input_mode = mode
        self.session = MirrorSession(PausedSender())

    def toggle(self, now=None):
        now = time.monotonic() if now is None else now
        if self.armed or self.pending_until:
            self.pause()
            return
        if not (self.active and self.capture and self.focus and self.target):
            self.message = '正在等待上屏画面；可切换标签后重试'
            return
        state, frame = self.focus.latest(), self.frame
        if (frame is None or not (frame.fresh(now) or self.cached_current(now))
                or not self.capture.source_size or state.snapshot is None
                or not state.matches(state.snapshot, now)):
            self.message = '正在等待上屏画面与前台窗口'
            return
        expected = state.snapshot
        if not expected.compatible(self.capture.source_size):
            self.message = '请关闭上屏覆盖菜单；当前需窗口与画面宽高比一致'
            return
        if self.input_mode == 'native' and expected.touch_mode not in (1, 4):
            self.message = '当前触屏模式不支持；可切换为鼠标兼容'
            return
        self.pause('正在连接上屏输入…')
        self.expected = expected
        try:
            focus_check = lambda: self.focus is not None and self.focus.latest().matches(
                expected, time.monotonic())
            if self.input_mode == 'native':
                sender = self.native_factory(self.target, expected, focus_check=focus_check)
            else:
                sender = self.mouse_factory(self.target, (expected.width, expected.height),
                                           x_server_pid=expected.server_pid,
                                           focus_check=focus_check)
            self.session = MirrorSession(sender, gesture_factory=(NativeMirroredTouch
                if self.input_mode == 'native' else MirroredTouch))
            self.session.update(frame, self.viewport, now, live=True,
                                cached_frame_current=self.cached_current(now))
            self.pending_until = now + 2
        except (InputUnavailable, OSError, ValueError) as error:
            self.last_error = str(error)
            self.pause('上屏输入不可用；可切换标签后重试')

    def touch(self, phase, tid, now, x=0, y=0):
        was_armed = self.armed
        self.session.touch(phase, tid, now, x, y)
        if was_armed and not self.armed:
            self.pause('画面或前台窗口已变化；请重新启用触摸')

    def tick(self, now=None):
        if not self.active:
            return
        now = time.monotonic() if now is None else now
        if self.capture is None:
            try:
                result, error = self._bootstrap_result.get_nowait()
            except Empty:
                return
            if error:
                self.last_error = error
                self.message = '无法连接上屏画面；切换标签后重试'
                return
            try:
                self.target, node = result
                self.capture = self.capture_factory(node, fps=60)
                self.source = self.source_factory(self.runtime, self.target.display_name, node)
                # :0 is Armada's primary control XWayland. UpperFocus verifies
                # its peer PID against Gamescope before enabling any input.
                self.focus = self.focus_factory(':0')
                self.focus.start()
                self.source.start()
                self.capture.start()
                self.message = '镜像已连接；点击「启用触摸」开始操作'
            except Exception as error:
                self.last_error = str(error)
                self.stop()
                self.message = '上屏捕获不可用；切换标签后重试'
                return
        was_armed = self.armed
        self.session.update(self.frame, self.viewport, now,
                            live=self.capture.status == 'running',
                            cached_frame_current=self.cached_current(now))
        if self.pending_until:
            if self.session.arm(now):
                self.pending_until = 0
                self.message = ('触摸已启用；沿用上屏应用的触屏设置' if
                                self.input_mode == 'native' else '鼠标兼容已启用；双指滑动滚动')
                self.revision += 1  # Discard fingers placed before arming.
            elif now >= self.pending_until or self.session.failed:
                self.pause('连接失败；请重新启用触摸')
        if was_armed and not self.armed:
            self.pause('画面或前台窗口已变化；请重新启用触摸')
        if self.capture.status == 'starting':
            self.message = '等待上屏首帧；可用手柄切换一次项目'
        elif self.capture.status == 'running' and self.frame is not None and not self._frame_seen:
            self._frame_seen = True
            if not self.armed and not self.pending_until:
                self.message = '镜像已连接；点击「启用触摸」开始操作'
        elif self.capture.status == 'error':
            self.last_error = self.capture.error
            if self.armed or self.pending_until:
                self.pause()
            self.message = '画面捕获已停止；切换标签后重试'

    @property
    def enable_label(self):
        return '暂停触摸' if self.armed else '连接中…' if self.pending_until else '启用触摸'

    @property
    def hint(self):
        return ('单指点按 / 滑动 / 拖动 · 多指沿用上屏设置 · 释放等同抬手' if
                self.input_mode == 'native' else '单指左键点按 / 拖动 · 双指滚轮 · 无惯性')
