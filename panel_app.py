#!/usr/bin/env python3
"""Experimental native Wayland adapter; not yet validated on the Thor.

No evdev reads, exclusive digitizer grabs, Decky backend, system-service
changes, cursor environment overrides, or brightness writes are used here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

BASE = Path(__file__).resolve().parent
VENDOR = BASE / "vendor" / "ratatoskr"
sys.path[:0] = [str(VENDOR / "bin"), str(VENDOR)]

os.environ["GDK_BACKEND"] = "wayland"
# The custom Cairo keyboard does not need a shared accessibility bridge.
# Keep this process out of it while isolating the Steam UI hang observed
# during the first hardware test. This is not a proven root-cause fix.
os.environ["NO_AT_BRIDGE"] = "1"
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

import debug_codes

class PanelLogger(debug_codes.DebugLogger):
    def log(self, code, details="") -> None:
        # A normal input app should not persist typed key codes or gestures.
        if not code.name.startswith("STATUS_"):
            super().log(code, details)


debug_codes.DebugLogger = PanelLogger
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "thor-panel"
STATE.mkdir(parents=True, exist_ok=True)
debug_codes.LOG_PATH = str(STATE / "panel.log")

import thor_app as upstream
from engine import SCREEN_HEIGHT, SCREEN_WIDTH
from monitor_select import choose_bottom_monitor, MODE_GAMEMODE, MODE_DESKTOP
from toolkit_touch import ToolkitTouch
from text_render import draw_text
from keyboard_pulses import KeyboardPulses
from scroll_output import ScaledScroll, read_scroll_scale

# Isolate our settings/socket names from a separately installed Ratatoskr.
upstream.CONFIG_PATH = str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "thor-panel/config.json")
upstream.SOCKET_PATH = str(Path(os.environ["XDG_RUNTIME_DIR"]) / "thor-panel-unused.sock")
# Keep a dedicated Close button at the right edge without removing Reset,
# Collapse, or the existing mode controls.
upstream.HEADER_BUTTONS = (
    ("trackpad", 12, 128), ("split", 148, 90), ("keyboard", 246, 122),
    ("settings", 376, 152), ("hud", 536, 64), ("left", 608, 108),
    ("right", 724, 108), ("pen", 840, 148), ("hide", 996, 108),
    ("close", 1112, 116),
)


class PanelApp(upstream.ThorApp):
    def __init__(self, mode: str, monitor) -> None:
        self.session_mode = mode
        self.monitor = monitor
        self.collapsed = False
        super().__init__()
        self.scroll_output = ScaledScroll(self.bridge.emit_scroll, self.scroll_scale)
        self.bridge.emit_scroll = self.scroll_output.scroll
        print(
            f"[scroll] speed={self.gesture.scroll_speed} output_scale={self.scroll_output.scale:g}",
            flush=True,
        )
        # Keep the GTK thread free while a key's 20 ms pulse is held. All
        # keyboard repeat/release work stays on this same event-loop thread.
        self.key_pulses = KeyboardPulses(
            send_key=self.bridge.key,
            schedule=GLib.timeout_add,
            cancel=GLib.source_remove,
        )
        self.bridge.tap_key = self.key_pulses.tap
        # Compositor shutdown/window closure should be retried. Only the
        # explicit Close action returns success and ends the supervisor.
        self.exit_code = 75
        self.window.unfullscreen()
        self.window.set_title("Thor 下屏面板")
        self.window.set_resizable(True)
        self.window.set_default_size(1, 1)
        self.window.set_accept_focus(False)
        self.window.set_focus_on_map(False)
        self.drawing_area.set_can_focus(False)

        # Layer shell selects an actual output and leaves keyboard focus in
        # the game/desktop app receiving our virtual keyboard events.
        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_namespace(self.window, "thor-panel")
        GtkLayerShell.set_monitor(self.window, monitor)
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(self.window, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(self.window, 0)
        if hasattr(GtkLayerShell, "set_respect_close"):
            GtkLayerShell.set_respect_close(self.window, True)
        self._apply_anchors()

        self.touch = ToolkitTouch(
            self._handle_touch_down, self._handle_touch_move,
            self._handle_touch_up, self._cancel_contact,
            on_activity=self._refresh_contact,
            on_timed_update=self._handle_timed_touch_move,
        )
        self.drawing_area.add_events(Gdk.EventMask.TOUCH_MASK)
        self.drawing_area.connect("touch-event", self._on_touch)
        self.drawing_area.connect("size-allocate", self._on_allocate)
        self.window.connect("unmap", self._on_unmap)
        Gdk.Display.get_default().connect("monitor-removed", self._on_monitor_removed)
        Gdk.Display.get_default().get_default_screen().connect("monitors-changed", self._on_monitors_changed)

    def load_config(self) -> None:
        self.mode = "split"
        self.scroll_scale = 1.0
        try:
            cfg = json.loads(Path(upstream.CONFIG_PATH).read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                self.scroll_scale = read_scroll_scale(cfg.get("scroll_scale", 1.0))
                if cfg.get("mode") in ("trackpad", "split", "keyboard", "settings"):
                    self.mode = cfg["mode"]
                self.gesture.set_settings(**cfg)
                upstream.keyboard_settings.apply(self.keyboard_cfg, cfg)
        except (OSError, ValueError, TypeError):
            pass
        # Keep this app free of system-wide pointer and dimming overrides.
        self.pen_mode = "off"
        self.gesture.set_settings(stylus_mode=False)
        self.mirror_cfg["mirror_dim"] = False
        # Keep the panel at the chosen brightness when idle. This only
        # disables Ratatoskr's painted veil; it does not change OS power rules.
        self.burn_in.idle_floor = 1.0
        self.gleipnir_cfg["gleipnir_ribbon"] = False

    def _setup_indicator(self) -> None:
        # Upstream tray actions start/stop official services; they do not apply.
        pass

    def _start_touch_reader(self) -> None:
        raise RuntimeError("Raw digitizer input is disabled in this adapter")

    def _start_ipc_server(self) -> None:
        raise RuntimeError("Decky IPC is disabled in this adapter")

    def start(self) -> None:
        self.stats.start_sampler()
        # Gamescope may swallow clicks/scroll while its pointer is hidden.
        # This only enables the upstream +/-1px wake nudge, not an OS override.
        self.bridge.wake_pointer = self.session_mode == "game"
        self.window.show_all()
        GLib.timeout_add(250, self._keep_contacts_alive)
        GLib.timeout_add_seconds(1, self._on_stats_tick)

    def _on_stats_tick(self) -> bool:
        if self._cleaned:
            return False
        self.drawing_area.queue_draw()
        return True

    def _keep_contacts_alive(self) -> bool:
        if self._cleaned:
            return False
        with self.input_lock:
            self.touch.keepalive()
        return True

    def _refresh_contact(self, tid: int, now: float) -> None:
        contact = self.gesture.active_contacts.get(tid)
        if contact is not None:
            contact["seen_t"] = now

    def _start_key_repeat(self, key) -> None:
        self.key_pulses.begin_repeat(
            key.code, self.keyboard_cfg["keyboard_repeat_delay_ms"],
            self.keyboard_cfg["keyboard_repeat_interval_ms"],
        )

    def _stop_key_repeat(self) -> None:
        if hasattr(self, "key_pulses"):
            self.key_pulses.stop_repeat()

    def _end_key_press(self) -> None:
        if hasattr(self, "key_pulses"):
            # The character must go up before consuming its one-shot modifier.
            self.key_pulses.release()
        super()._end_key_press()

    def _send_keys(self, events) -> None:
        events = list(events)
        if events and hasattr(self, "key_pulses"):
            self.key_pulses.flush_pending()
        super()._send_keys(events)

    def _reset_input(self) -> None:
        self.gesture.glide_stop.set()
        self.gesture.reset_all()
        self._end_key_press()
        self._send_keys(self.mods.release_all())
        self._release_ui_button()
        self.bridge.release_all()
        self._touch_owner.clear()
        self._slider_drag = None
        self.active_key_press = self.active_key_tid = None

    def _cancel_contact(self, tid: int, now: float) -> None:
        # A compositor cancel must not turn into a click on lift.
        self._reset_input()

    def _on_unmap(self, *_) -> None:
        if hasattr(self, "touch"):
            with self.input_lock:
                self.touch.release_all()
                self._reset_input()

    def _on_monitor_removed(self, display, monitor) -> None:
        if monitor == self.monitor:
            self.exit_code = 75  # Supervisor may retry after the session settles.
            self.window.close()

    def _on_monitors_changed(self, screen) -> None:
        if self._cleaned:
            return
        display = screen.get_display()
        names = [screen.get_monitor_plug_name(i) for i in range(display.get_n_monitors())]
        selected = choose_bottom_monitor(names, MODE_GAMEMODE if self.session_mode == "game" else MODE_DESKTOP)
        if selected is None or display.get_monitor(selected) != self.monitor:
            # Do not let KWin silently move this surface to the upper output.
            self.window.hide()
            self.exit_code = 75
            self.window.close()

    def _on_allocate(self, widget, allocation) -> None:
        if allocation.width > 0 and allocation.height > 0:
            with self.input_lock:
                self.touch.set_viewport(allocation.width, allocation.height)

    def _on_touch(self, widget, event) -> bool:
        if self._cleaned:
            return True
        if self.collapsed:
            if event.type == Gdk.EventType.TOUCH_BEGIN:
                self._set_collapsed(False)
            return True
        sequence = event.get_event_sequence()
        with self.input_lock:
            if event.type == Gdk.EventType.TOUCH_BEGIN:
                self.burn_in.record_touch()
                self.touch.begin(sequence, event.x, event.y, source_ms=event.get_time())
            elif event.type == Gdk.EventType.TOUCH_UPDATE:
                self.touch.update(sequence, event.x, event.y, source_ms=event.get_time())
            elif event.type == Gdk.EventType.TOUCH_END:
                self.touch.end(sequence)
            elif event.type == Gdk.EventType.TOUCH_CANCEL:
                self.touch.release_all()
                self._reset_input()
        # Do not forward a touch to the toolkit's emulated pointer handlers.
        return True

    def _handle_timed_touch_move(self, tid, x, y, now, motion_interval) -> None:
        owner = self._touch_owner.get(tid)
        if owner == "trackpad" or (owner is None and self.mode != "settings"):
            self.last_event_time = time.time()
            self.gesture.touch_move(tid, x, y, now, motion_interval=motion_interval)
            if self.show_debug_hud:
                self.drawing_area.queue_draw()
        else:
            self._handle_touch_move(tid, x, y, now)

    def _apply_anchors(self) -> None:
        for edge in (GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT, GtkLayerShell.Edge.BOTTOM):
            GtkLayerShell.set_anchor(self.window, edge, True)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, not self.collapsed)
        self.window.set_size_request(-1, 72 if self.collapsed else -1)
        self.window.resize(1, 1)

    def _set_collapsed(self, collapsed: bool) -> None:
        with self.input_lock:
            self.touch.release_all()
            self._reset_input()
            self.collapsed = collapsed
        self._apply_anchors()
        self.drawing_area.queue_draw()

    def set_mode(self, mode: str, restart_hint: bool = True) -> None:
        if hasattr(self, "touch"):
            self.touch.release_all()
            self._reset_input()
        super().set_mode(mode, restart_hint)

    def _handle_header_touch(self, tid, x, y, down) -> None:
        key = next((k for k, bx, bw in upstream.HEADER_BUTTONS if bx <= x <= bx + bw), None)
        if key == "close":
            with self.input_lock:
                self.touch.set_enabled(False)
                self._reset_input()
            self.exit_code = 0
            self.request_quit()
        elif key == "hide":
            self._set_collapsed(True)
        elif key == "pen":
            self.touch.release_all()
            self._reset_input()
            self.drawing_area.queue_draw()
        else:
            super()._handle_header_touch(tid, x, y, down)

    def _header_button_look(self, key):
        if key == "close":
            return "关闭", True, (0.40, 0.10, 0.12)
        if key == "pen":
            return "释放按键", False, upstream.theme.BTN_ACCENT_DEFAULT
        if key == "hide":
            return "收起", False, upstream.theme.BTN_ACCENT_DEFAULT
        label, active, accent = super()._header_button_look(key)
        label = {"trackpad": "触控板", "split": "分屏", "keyboard": "键盘", "settings": "监控", "left": "左键", "right": "右键"}.get(key, label)
        return label, active, accent

    def _draw_button(self, cr, x, y, w, h, text, active,
                     accent_color=upstream.theme.BTN_ACCENT_DEFAULT) -> None:
        # Keep the upstream border/active-state styling; its Cairo toy text
        # API lacks per-glyph fallback, so draw labels with Pango instead.
        super()._draw_button(cr, x, y, w, h, "", active, accent_color)
        draw_text(cr, text, x + w / 2.0, y + h / 2.0,
                  min(h * 0.40, upstream.BUTTON_TEXT_MAX_PX),
                  bold=True, max_width=w - 16, centered=True)

    def _handle_settings_touch(self, *_) -> None:
        pass  # Monitoring is read-only; Armada keeps hardware controls.

    def _handle_settings_drag(self, *_) -> None:
        pass

    def _draw_quick_settings(self, cr) -> None:
        stats = self.stats.get_stats()
        lines = [
            "Thor 下屏面板 · 独立应用原型",
            "游戏模式" if self.session_mode == "game" else "桌面模式",
            f"CPU: {stats.get('cpu_load', 0)}%  {stats.get('cpu_temp', 0)} °C",
            f"GPU: {stats.get('gpu_mhz', 0)} MHz  {stats.get('gpu_temp', 0)} °C",
            f"RAM: {stats.get('ram_used_gb', 0)} / {stats.get('ram_total_gb', 0)} GB",
            f"电量: {stats.get('bat_cap', 0)}%",
            "收起：显示官方下屏；点击底部条可展开",
        ]
        cr.set_source_rgb(0.8, 0.85, 0.85)
        for index, line in enumerate(lines):
            draw_text(cr, line, 45, upstream.HEADER_HEIGHT + 70 + index * 88,
                      30, max_width=SCREEN_WIDTH - 90)

    def on_draw(self, widget, cr) -> bool:
        allocation = widget.get_allocation()
        if self.collapsed:
            cr.set_source_rgb(0.03, 0.05, 0.05)
            cr.paint()
            cr.set_source_rgb(0.8, 0.9, 0.9)
            draw_text(cr, "Thor 下屏面板 · 点击展开",
                      allocation.width / 2.0, allocation.height / 2.0,
                      min(28, allocation.height * 0.45),
                      max_width=max(1, allocation.width - 40), centered=True)
            return True
        cr.save()
        cr.scale(allocation.width / SCREEN_WIDTH, allocation.height / SCREEN_HEIGHT)
        try:
            return super().on_draw(widget, cr)
        finally:
            cr.restore()

    def cleanup(self) -> None:
        if self._cleaned:
            return
        try:
            if hasattr(self, "touch"):
                self.touch.release_all()
            self._reset_input()
        finally:
            if hasattr(self, "key_pulses"):
                self.key_pulses.close()
            # The parent cleanup only closes this app's resources; our raw
            # fd stays -1, dim mirror never started, and IPC never bound.
            super().cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("game", "desktop"), required=True)
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error("Run the panel as the desktop user, not root")
    if args.mode == "game" and os.environ.get("WAYLAND_DISPLAY") != "armada-plasma-bottom":
        parser.error("Game Mode must use Armada's bottom KWin socket")
    if not GtkLayerShell.is_supported():
        parser.error("This session does not support GTK layer shell")
    display = Gdk.Display.get_default()
    screen = display.get_default_screen()
    names = [screen.get_monitor_plug_name(i) for i in range(display.get_n_monitors())]
    index = choose_bottom_monitor(names, MODE_GAMEMODE if args.mode == "game" else MODE_DESKTOP)
    if index is None:
        print("Cannot identify the bottom output; no window was opened", file=sys.stderr)
        return 75
    if not os.access("/dev/uinput", os.W_OK):
        print("The user cannot write /dev/uinput; no input device was created", file=sys.stderr)
        return 78
    app = PanelApp(args.mode, display.get_monitor(index))
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, app.request_quit, sig)
    try:
        app.start()
        Gtk.main()
        return app.exit_code
    finally:
        app.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
