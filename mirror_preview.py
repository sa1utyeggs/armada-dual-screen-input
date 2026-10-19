#!/usr/bin/env python3
"""Opt-in Game Mode mirror prototype; independent of the installed panel.

Start with mirror_launch.py. No service, settings or autostart changes. The
preview starts paused, accepts real touchscreen events only, and never takes
keyboard focus. It currently supports matching-aspect XWayland applications.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import os
from pathlib import Path
import signal
import time

from ei_input import GamescopeTarget, InputUnavailable, LibEIInput
from gamescope_focus import FocusWatcher
from mirror_capture import MirrorCapture, SourceMonitor
from mirror_geometry import Rect
from mirror_session import MirrorSession
from toolkit_touch import ToolkitTouch


class PausedSender:
    ready = False
    def poll(self): pass
    def release_all(self): pass
    def close(self): pass


def run(args) -> int:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GtkLayerShell', '0.1')
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
    import cairo

    if (os.getuid() == 0 or os.environ.get('WAYLAND_DISPLAY') != 'armada-plasma-bottom'
            or not GtkLayerShell.is_supported()):
        raise RuntimeError('prototype requires the same-user Game Mode bottom KWin session')
    display = Gdk.Display.get_default()
    if display is None or display.get_n_monitors() != 1:
        raise RuntimeError('the dedicated lower session must expose one unambiguous output')
    target = GamescopeTarget.resolve(Path(os.environ['XDG_RUNTIME_DIR']), args.upper_display)
    loop = GLib.MainLoop()

    class Preview:
        def __init__(self):
            self.started_at, self.started_cpu = time.monotonic(), time.process_time()
            self.closed = False
            self.session = MirrorSession(PausedSender())
            self.capture = MirrorCapture(args.node, fps=args.fps)
            self.source = SourceMonitor(target.runtime, args.upper_display, args.node)
            self.focus = FocusWatcher(args.x_display)
            self.expected_focus = None
            self.pending_until = 0.0
            self.surface = self.surface_frame = None
            self.drawn_sequence = 0
            self.last_status = ''
            self.rate_started, self.rate_sequence, self.rate = time.monotonic(), 0, 0.0
            self.message = '预览已启动；触摸尚未启用'
            self.touch = ToolkitTouch(self.begin, self.move, self.end, self.cancel,
                                      logical_width=1, logical_height=1,
                                      viewport_width=1, viewport_height=1)
            self.window = Gtk.Window(title='同屏触摸 · 实验预览')
            self.window.set_accept_focus(False)
            self.window.set_focus_on_map(False)
            GtkLayerShell.init_for_window(self.window)
            GtkLayerShell.set_namespace(self.window, 'armada-mirror-preview')
            GtkLayerShell.set_monitor(self.window, display.get_monitor(0))
            GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.TOP)
            GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.NONE)
            GtkLayerShell.set_exclusive_zone(self.window, 0)
            for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                         GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(self.window, edge, True)
            if hasattr(GtkLayerShell, 'set_respect_close'):
                GtkLayerShell.set_respect_close(self.window, True)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_border_width(8)
            self.window.add(box)
            heading = Gtk.Label(label='同屏触摸 · 实验预览')
            box.pack_start(heading, False, False, 0)
            buttons = Gtk.Box(spacing=8, homogeneous=True)
            self.enable = Gtk.Button(label='启用触摸')
            release = Gtk.Button(label='释放并暂停')
            close = Gtk.Button(label='关闭预览')
            for button in (self.enable, release, close):
                button.set_can_focus(False)
                button.set_size_request(-1, 42)
                buttons.pack_start(button, True, True, 0)
            box.pack_start(buttons, False, False, 0)
            self.status = Gtk.Label()
            self.status.set_line_wrap(True)
            self.status.set_lines(2)
            self.status.set_size_request(-1, 40)
            box.pack_start(self.status, False, False, 0)
            self.canvas = Gtk.DrawingArea()
            self.canvas.set_can_focus(False)
            self.canvas.set_hexpand(True)
            self.canvas.set_vexpand(True)
            self.canvas.add_events(Gdk.EventMask.TOUCH_MASK)
            self.canvas.connect('draw', self.draw)
            self.canvas.connect('touch-event', self.touch_event)
            self.canvas.connect('size-allocate', self.allocated)
            box.pack_start(self.canvas, True, True, 0)
            hint = Gtk.Label(label='单指点按 / 拖动 · 双指滑动滚轮 · 无惯性')
            box.pack_start(hint, False, False, 0)
            css = Gtk.CssProvider()
            css.load_from_data(b'window { background: #101820; color: #eff5fa; } '
                               b'label, button { font-family: "Noto Sans CJK SC", Sans; font-size: 15px; } '
                               b'button { color: #eff5fa; background: #29404e; border-radius: 8px; }')
            Gtk.StyleContext.add_provider_for_screen(display.get_default_screen(), css, 600)
            self.enable.connect('clicked', self.toggle)
            release.connect('clicked', lambda *_: self.pause('已释放输入；触摸已暂停'))
            close.connect('clicked', self.close)
            self.window.connect('delete-event', lambda *_: (self.close(), True)[1])
            self.window.connect('unmap', lambda *_: self.pause('窗口已隐藏；触摸已暂停'))
            display.connect('monitor-removed', self.close)
            self.focus.start()
            self.source.start()
            self.capture.start()
            self.window.show_all()
            GLib.timeout_add(16, self.tick)
            if args.quit_after:
                GLib.timeout_add(int(args.quit_after * 1000), self.close)
            if args.proof:
                GLib.timeout_add_seconds(3, lambda: (GLib.idle_add(self.proof), False)[1])

        def proof(self):
            if self.closed:
                return False
            self.window.check_resize()
            allocation = self.window.get_allocation()
            image = cairo.ImageSurface(cairo.FORMAT_RGB24, allocation.width, allocation.height)
            self.window.draw(cairo.Context(image))
            image.write_to_png(str(args.proof))
            print(json.dumps({'event': 'preview_layout',
                              'size': [allocation.width, allocation.height],
                              'missing_glyphs': self.status.get_layout().get_unknown_glyphs_count(),
                              'armed': self.session.armed,
                              'capture_status': self.capture.status,
                              'capture_error': self.capture.error,
                              'frame_sequence': self.drawn_sequence,
                              'gesture': self.session.gesture.state if self.session.gesture else 'idle',
                              'contacts': len(self.touch.active),
                              'wheel_notches_sent': getattr(self.session.sender, 'wheel_notches_sent', 0),
                              'delivered': self.session.delivered}), flush=True)
            return False

        def viewport(self):
            a = self.canvas.get_allocation()
            return Rect(0, 0, max(1, a.width), max(1, a.height))

        def allocated(self, _, allocation):
            initial = self.touch.viewport_width == self.touch.viewport_height == 1
            if self.touch.set_viewport(max(1, allocation.width), max(1, allocation.height)):
                if not initial:
                    self.pause('尺寸已变化；请重新启用触摸')
            self.touch.logical_width = max(1, allocation.width)
            self.touch.logical_height = max(1, allocation.height)

        def pause(self, message):
            self.pending_until = 0
            self.session.pause(time.monotonic())
            self.touch.release_all()
            self.message = message

        def toggle(self, *_):
            if self.session.armed or self.pending_until:
                self.pause('触摸已暂停')
                return
            now = time.monotonic()
            state = self.focus.latest()
            frame = self.capture.frames.latest()
            if (frame is None or not (frame.fresh(now) or self.cached_current(now))
                    or not self.capture.source_size
                    or state.snapshot is None or not state.matches(state.snapshot, now)):
                self.message = '正在等待上屏画面与前台窗口'
                return
            if not state.snapshot.compatible(self.capture.source_size):
                self.message = '请关闭 Steam 覆盖菜单；首版需上屏窗口与画面宽高比一致'
                return
            self.pause('正在连接上屏输入…')
            self.session.sender.close()
            self.expected_focus = state.snapshot
            expected = state.snapshot
            try:
                sender = LibEIInput(target, (expected.width, expected.height),
                                    x_server_pid=expected.server_pid,
                                    focus_check=lambda: self.focus.latest().matches(
                                        expected, time.monotonic()))
                self.session = MirrorSession(sender)
                self.session.update(frame, self.viewport(), now, live=True,
                                    cached_frame_current=self.cached_current(now))
                self.pending_until = now + 2
            except (InputUnavailable, OSError, ValueError) as error:
                self.message = '上屏输入不可用；可关闭后重新打开预览'
                print(json.dumps({'event': 'input_error', 'error': str(error)}), flush=True)

        def begin(self, tid, x, y, now):
            self.session.touch('begin', tid, now, x, y)

        def move(self, tid, x, y, now):
            self.session.touch('move', tid, now, x, y)

        def end(self, tid, now):
            self.session.touch('end', tid, now)

        def cancel(self, tid, now):
            self.session.touch('cancel', tid, now)

        def touch_event(self, _, event):
            sequence = event.get_event_sequence()
            if event.type == Gdk.EventType.TOUCH_BEGIN:
                self.touch.begin(sequence, event.x, event.y)
            elif event.type == Gdk.EventType.TOUCH_UPDATE:
                self.touch.update(sequence, event.x, event.y)
            elif event.type == Gdk.EventType.TOUCH_END:
                self.touch.end(sequence)
            elif event.type == Gdk.EventType.TOUCH_CANCEL:
                self.touch.cancel(sequence)
            self.canvas.queue_draw()
            return True

        def tick(self):
            if self.closed:
                return False
            now = time.monotonic()
            frame = self.capture.frames.latest()
            was_armed = self.session.armed
            self.session.update(frame, self.viewport(), now, live=self.capture.status == 'running',
                                cached_frame_current=self.cached_current(now))
            if self.pending_until:
                if self.session.sender.ready:
                    self.touch.release_all()
                if self.session.arm(now):
                    self.pending_until = 0
                    self.message = '触摸已启用；动作作用于上屏'
                    print(json.dumps({'event': 'armed', 'surface_size': [
                        self.expected_focus.width, self.expected_focus.height]}), flush=True)
                elif now >= self.pending_until or self.session.failed:
                    self.pause('连接上屏失败；请重新启用触摸')
            if was_armed and not self.session.armed:
                self.touch.release_all()
                self.message = '画面或前台窗口已变化；请重新启用触摸'
                print(json.dumps({'event': 'input_paused', 'reason': self.session.reason,
                                  'error': self.session.last_error}), flush=True)
            if frame and frame.sequence != self.drawn_sequence:
                self.canvas.queue_draw()
            if now - self.rate_started >= 1:
                sequence = frame.sequence if frame else 0
                self.rate = (sequence - self.rate_sequence) / (now - self.rate_started)
                self.rate_started, self.rate_sequence = now, sequence
            label = '暂停触摸' if self.session.armed else (
                '连接中…' if self.pending_until else '启用触摸')
            if self.enable.get_label() != label:
                self.enable.set_label(label)
            message = self.message
            if self.capture.status == 'starting':
                message = '等待上屏首帧；可用手柄切换一次项目'
            elif self.capture.status == 'error':
                message = '捕获已停止；请关闭后重新打开预览'
            gesture = self.session.gesture.state if self.session.gesture else 'idle'
            activity = {'pending': '等待双指', 'single': '单指拖动',
                        'scroll-pending': '双指就绪', 'scrolling': '双指滚动',
                        'blocked': '请全部抬手'}.get(gesture, '等待触摸')
            if self.session.armed:
                message += ' · ' + activity
            status = (f'{message}\n画面 {self.rate:.0f} 帧/秒 · '
                      f'手指 {len(self.touch.active)} · 滚轮 '
                      f'{getattr(self.session.sender, "wheel_notches_sent", 0)} 格')
            if status != self.last_status:
                self.status.set_text(status)
                self.last_status = status
            return True

        def cached_current(self, now):
            return self.capture.healthy(now) and self.source.current(now)

        def draw(self, _, cr):
            cr.set_source_rgb(0.025, 0.035, 0.045)
            cr.paint()
            frame = self.capture.frames.latest()
            transform = self.session.transform
            if frame is None or transform is None:
                return False
            if self.surface_frame is not frame:
                self.surface = cairo.ImageSurface.create_for_data(
                    frame.data, cairo.FORMAT_RGB24, frame.width, frame.height, frame.stride)
                self.surface_frame = frame
            image = transform.image
            cr.save()
            cr.rectangle(image.x, image.y, image.width, image.height)
            cr.clip()
            cr.translate(image.x, image.y)
            cr.scale(image.width / frame.width, image.height / frame.height)
            cr.set_source_surface(self.surface, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.paint()
            cr.restore()
            if self.session.armed:
                cr.set_source_rgba(0.2, 0.9, 0.9, 0.85)
                cr.set_line_width(2)
                for contact in self.touch.active:
                    cr.arc(contact.x, contact.y, 10, 0, 6.283185307)
                    cr.stroke()
            self.drawn_sequence = frame.sequence
            return False

        def close(self, *_):
            if self.closed:
                return False
            print(json.dumps({'event': 'closing'}), flush=True)
            self.pause('预览已关闭')
            self.session.sender.close()
            self.capture.stop()
            self.source.stop()
            self.focus.stop()
            self.closed = True
            self.window.hide()
            loop.quit()
            print(json.dumps({'event': 'window_closed'}), flush=True)
            return False

    app = Preview()
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    if args.quit_after:
        faulthandler.dump_traceback_later(args.quit_after + 5)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, app.close)
    if args.proof:
        # Development-only snapshots reuse this capture, never attach a second
        # PipeWire consumer. No signal handler is enabled without explicit opt-in.
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2,
                             lambda: (app.proof(), True)[1])
    try:
        loop.run()
    finally:
        app.close()
        app.capture.wait()
        app.source.wait()
        faulthandler.cancel_dump_traceback_later()
        frame = app.capture.frames.latest()
        print(json.dumps({'event': 'closed', 'capture_status': app.capture.status,
                          'capture_error': app.capture.error,
                          'captured_frames': frame.sequence if frame else 0,
                          'latest_age': time.monotonic() - frame.received_at if frame else None,
                          'source_size': app.capture.source_size,
                          'preview_size': [frame.width, frame.height] if frame else None,
                          'duration': time.monotonic() - app.started_at,
                          'cpu_seconds': time.process_time() - app.started_cpu}), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', type=int, required=True)
    parser.add_argument('--upper-display', required=True)
    parser.add_argument('--x-display', required=True)
    parser.add_argument('--fps', type=int, default=60)
    parser.add_argument('--quit-after', type=float, default=0)
    parser.add_argument('--proof', type=Path, help='explicit development-only preview PNG')
    args = parser.parse_args()
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
