#!/usr/bin/env python3
"""Native Wayland input panel for Armada's dedicated lower session.

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
import steam_style
import steam_keys
from keyboard_pulses import KeyboardPulses
from scroll_output import ScaledScroll, read_scroll_scale
from steam_keyboard_guard import SteamKeyboardGuard, keyboard_guard_wanted
from panel_mirror import PanelMirror

# Isolate our settings/socket names from a separately installed Ratatoskr.
upstream.CONFIG_PATH = str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "thor-panel/config.json")
upstream.SOCKET_PATH = str(Path(os.environ["XDG_RUNTIME_DIR"]) / "thor-panel-unused.sock")
# A single shared table for rendering and hit tests; keyboard bounds stay fixed.
upstream.HEADER_BUTTONS = (
    ("trackpad", 12, 140), ("split", 160, 110), ("mirror", 278, 170),
    ("left", 470, 150), ("right", 628, 132), ("pen", 768, 180),
    ("hide", 956, 128), ("close", 1092, 136),
)
# Reclaim one status row for the trackpad; keep the keyboard bounds unchanged.
upstream.STATUS_RIBBON_H = 44.0
upstream.HEADER_HEIGHT = upstream.HEADER_BUTTONS_H + upstream.STATUS_RIBBON_H


class PanelApp(upstream.ThorApp):
    def __init__(self, mode: str, monitor) -> None:
        self.session_mode = mode
        self.monitor = monitor
        self.collapsed = False
        self.keyboard_guard = None
        self.mirror = None
        self._mirror_discarding = False
        self._mirror_surface = self._mirror_surface_frame = None
        self._mirror_draw_state = None
        self.main_loop = None
        super().__init__()
        self.mirror = PanelMirror()
        self._mirror_revision = self.mirror.revision
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
        self.window.set_title("虚拟键鼠")
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
        self.window.connect("map", self._on_map)
        if self.session_mode == "game":
            self.keyboard_guard = SteamKeyboardGuard()
        Gdk.Display.get_default().connect("monitor-removed", self._on_monitor_removed)
        Gdk.Display.get_default().get_default_screen().connect("monitors-changed", self._on_monitors_changed)

    def load_config(self) -> None:
        self.mode = "split"
        self.scroll_scale = 1.0
        try:
            cfg = json.loads(Path(upstream.CONFIG_PATH).read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                self.scroll_scale = read_scroll_scale(cfg.get("scroll_scale", 1.0))
                if cfg.get("mode") in ("trackpad", "split", "mirror"):
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
        if getattr(self, "keyboard_guard", None) is not None:
            self.keyboard_guard.start()
        self.stats.start_sampler()
        # Gamescope may swallow clicks/scroll while its pointer is hidden.
        # This only enables the upstream +/-1px wake nudge, not an OS override.
        self.bridge.wake_pointer = self.session_mode == "game"
        self.window.show_all()
        GLib.timeout_add(250, self._keep_contacts_alive)
        GLib.timeout_add_seconds(1, self._on_stats_tick)
        GLib.timeout_add(16, self._on_mirror_tick)

    def _mirror_visible(self) -> bool:
        return (self.session_mode == "game" and self.mode == "mirror"
                and not self.collapsed and self.window.get_mapped())

    def _on_map(self, *_) -> None:
        self._sync_keyboard_guard()
        if self._mirror_visible() and self.mirror is not None:
            self.mirror.start()

    def _clear_panel_contacts(self) -> None:
        # Dropping pre-arm fingers must not cancel the newly armed backend.
        self._mirror_discarding = True
        try:
            self.touch.release_all()
            self._reset_input()
        finally:
            self._mirror_discarding = False

    def _stop_mirror(self) -> None:
        if getattr(self, "mirror", None) is not None:
            self.mirror.stop()
        self._mirror_surface = self._mirror_surface_frame = None
        self._mirror_draw_state = None

    def _on_mirror_tick(self) -> bool:
        if self._cleaned:
            return False
        if not self._mirror_visible() or self.mirror is None:
            return True
        self.mirror.tick()
        if self._mirror_revision != self.mirror.revision:
            self._clear_panel_contacts()
            self._mirror_revision = self.mirror.revision
        frame = self.mirror.frame
        state = (frame.sequence if frame else None, self.mirror.armed,
                 bool(self.mirror.pending_until), self.mirror.message, self.mirror.input_mode)
        if state != self._mirror_draw_state:
            self._mirror_draw_state = state
            self.drawing_area.queue_draw()
        return True

    def _on_stats_tick(self) -> bool:
        if self._cleaned:
            return False
        self._sync_keyboard_guard()
        self.drawing_area.queue_draw()
        return True

    def _sync_keyboard_guard(self, *_) -> None:
        if getattr(self, "keyboard_guard", None) is not None:
            self.keyboard_guard.update(keyboard_guard_wanted(
                self.session_mode, self.mode, self.collapsed, self.window.get_mapped(),
            ))

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
        if (getattr(self, "mirror", None) is not None
                and not getattr(self, "_mirror_discarding", False)):
            self.mirror.pause()
        self._reset_input()

    def _on_unmap(self, *_) -> None:
        self._stop_mirror()
        if getattr(self, "keyboard_guard", None) is not None:
            self.keyboard_guard.update(False)
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
                if self.touch.set_viewport(allocation.width, allocation.height):
                    if self.mirror is not None:
                        self.mirror.pause('窗口尺寸已变化；请重新启用触摸')

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
                if self.mirror is not None:
                    self.mirror.pause()
                self._reset_input()
        # Do not forward a touch to the toolkit's emulated pointer handlers.
        return True

    def _handle_timed_touch_move(self, tid, x, y, now, motion_interval) -> None:
        owner = self._touch_owner.get(tid)
        if self.mode == "mirror" or owner == "mirror":
            self._handle_touch_move(tid, x, y, now)
            return
        if owner == "trackpad" or (owner is None and self.mode != "settings"):
            self.last_event_time = time.time()
            self.gesture.touch_move(tid, x, y, now, motion_interval=motion_interval)
            if self.show_debug_hud:
                self.drawing_area.queue_draw()
        else:
            self._handle_touch_move(tid, x, y, now)

    def _handle_touch_down(self, tid, x, y, now) -> None:
        # Status is display-only. The vendor ribbon opens its old controls page.
        if not self.ui_hidden and upstream.HEADER_BUTTONS_H <= y < upstream.HEADER_HEIGHT:
            self.last_event_time = time.time()
            self._touch_owner[tid] = "status"
            return
        if self.mode == "mirror" and y >= upstream.HEADER_HEIGHT:
            self._touch_owner[tid] = "mirror"
            if self.mirror is not None:
                self.mirror.touch('begin', tid, now, x, y)
            return
        super()._handle_touch_down(tid, x, y, now)

    def _handle_touch_move(self, tid, x, y, now) -> None:
        owner = self._touch_owner.get(tid)
        if self.mode == "mirror" or owner == "mirror":
            if owner == "mirror" and self.mirror is not None:
                self.mirror.touch('move', tid, now, x, y)
            return
        super()._handle_touch_move(tid, x, y, now)

    def _handle_touch_up(self, tid, now) -> None:
        if self.mode == "mirror" or self._touch_owner.get(tid) == "mirror":
            if self._touch_owner.pop(tid, None) == "mirror" and self.mirror is not None:
                self.mirror.touch('end', tid, now)
            return
        super()._handle_touch_up(tid, now)

    def _apply_anchors(self) -> None:
        for edge in (GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT, GtkLayerShell.Edge.BOTTOM):
            GtkLayerShell.set_anchor(self.window, edge, True)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, not self.collapsed)
        self.window.set_size_request(-1, 72 if self.collapsed else -1)
        self.window.resize(1, 1)

    def _set_collapsed(self, collapsed: bool) -> None:
        self._stop_mirror()
        with self.input_lock:
            self.touch.release_all()
            self._reset_input()
            self.collapsed = collapsed
        self._apply_anchors()
        self._sync_keyboard_guard()
        if self._mirror_visible() and self.mirror is not None:
            self.mirror.start()
        self.drawing_area.queue_draw()

    def set_mode(self, mode: str, restart_hint: bool = True) -> None:
        # Old settings or callers may still name a removed page.
        if mode in ("keyboard", "settings"):
            mode = "split"
        elif mode not in ("trackpad", "split", "mirror"):
            return
        if mode == "mirror" and self.session_mode != "game":
            return
        self._stop_mirror()
        if hasattr(self, "touch"):
            self.touch.release_all()
            self._reset_input()
        if mode == "mirror":
            self.mode = mode
            self.save_config()
            if self._mirror_visible() and self.mirror is not None:
                self.mirror.start()
            self.drawing_area.queue_draw()
        else:
            super().set_mode(mode, restart_hint)
        self._sync_keyboard_guard()

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
        elif key == "mirror":
            self.set_mode("mirror", restart_hint=False)
        elif self.mode == "mirror" and key in ("left", "right", "pen"):
            self._clear_panel_contacts()
            if self.mirror is not None:
                if key == "left":
                    self.mirror.toggle()
                elif key == "right":
                    self.mirror.set_input_mode('mouse' if self.mirror.input_mode == 'native' else 'native')
                else:
                    self.mirror.pause()
            self.drawing_area.queue_draw()
        elif key == "pen":
            self.touch.release_all()
            self._reset_input()
            self.drawing_area.queue_draw()
        else:
            super()._handle_header_touch(tid, x, y, down)

    def _header_button_look(self, key):
        if key == "mirror":
            return "同屏触摸", self.mode == "mirror", upstream.theme.BTN_ACCENT_DEFAULT
        if self.mode == "mirror" and key in ("left", "right", "pen"):
            mirror = getattr(self, "mirror", None)
            label = {"left": mirror.enable_label if mirror else "启用触摸",
                     "right": "原生触摸" if mirror is None or mirror.input_mode == 'native' else "鼠标兼容",
                     "pen": "释放触点"}[key]
            return label, bool(key == "left" and mirror and mirror.armed), upstream.theme.BTN_ACCENT_DEFAULT
        if key == "close":
            return "关闭", True, (0.40, 0.10, 0.12)
        if key == "pen":
            return "释放按键", False, upstream.theme.BTN_ACCENT_DEFAULT
        if key == "hide":
            return "收起", False, upstream.theme.BTN_ACCENT_DEFAULT
        label, active, accent = super()._header_button_look(key)
        label = {"trackpad": "触控板", "split": "键鼠", "left": "左键", "right": "右键"}.get(key, label)
        return label, active, accent

    def _draw_button(self, cr, x, y, w, h, text, active,
                     accent_color=upstream.theme.BTN_ACCENT_DEFAULT) -> None:
        steam_style.button(cr, x, y, w, h, text, active)

    def _draw_ui(self, cr) -> None:
        cr.set_source_rgb(*steam_style.BG)
        cr.paint()
        super()._draw_ui(cr)

    def _draw_header(self, cr) -> None:
        steam_style.draw_header(self, cr, upstream.HEADER_BUTTONS,
                                upstream.HEADER_BUTTON_Y, upstream.HEADER_BUTTON_H,
                                SCREEN_WIDTH)

    def _draw_status_ribbon(self, cr) -> None:
        steam_style.draw_status(self, cr, upstream.HEADER_BUTTONS_H,
                                upstream.STATUS_RIBBON_H, SCREEN_WIDTH)

    def _draw_trackpad_surface(self, cr, y, h) -> None:
        steam_style.draw_trackpad(self, cr, y, h, SCREEN_WIDTH)

    def _draw_keyboard(self, cr) -> None:
        steam_keys.draw_keyboard(self, cr)

    def _handle_settings_touch(self, *_) -> None:
        pass  # Monitoring is read-only; Armada keeps hardware controls.

    def _handle_settings_drag(self, *_) -> None:
        pass

    def _draw_quick_settings(self, cr) -> None:
        steam_style.draw_monitor(self, cr, upstream.HEADER_HEIGHT,
                                 SCREEN_WIDTH, SCREEN_HEIGHT)

    def _draw_collapsed(self, cr, width, height) -> None:
        steam_style.draw_collapsed(cr, width, height)

    def on_draw(self, widget, cr) -> bool:
        allocation = widget.get_allocation()
        if self.collapsed:
            self._draw_collapsed(cr, allocation.width, allocation.height)
            return True
        cr.save()
        cr.scale(allocation.width / SCREEN_WIDTH, allocation.height / SCREEN_HEIGHT)
        try:
            if self.mode == "mirror":
                # Absolute touch and its displayed image must share the same
                # geometry; skip the vendor's orbital UI-only micro-shift.
                self._draw_ui(cr)
                self._draw_mirror(cr)
                return True
            return super().on_draw(widget, cr)
        finally:
            cr.restore()

    def _draw_mirror(self, cr) -> None:
        import cairo
        mirror = self.mirror
        if mirror is None:
            return
        viewport = mirror.viewport
        steam_style.rounded(cr, viewport.x, viewport.y, viewport.width, viewport.height,
                            8, (0.025, 0.035, 0.045), steam_style.BORDER)
        frame, transform = mirror.frame, mirror.session.transform
        if frame is not None and transform is not None:
            if self._mirror_surface_frame is not frame:
                self._mirror_surface = cairo.ImageSurface.create_for_data(
                    frame.data, cairo.FORMAT_RGB24, frame.width, frame.height, frame.stride)
                self._mirror_surface_frame = frame
            image = transform.image
            cr.save()
            cr.rectangle(image.x, image.y, image.width, image.height)
            cr.clip()
            cr.translate(image.x, image.y)
            cr.scale(image.width / frame.width, image.height / frame.height)
            cr.set_source_surface(self._mirror_surface, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_BILINEAR)
            cr.paint()
            cr.restore()
        cr.set_source_rgb(*(steam_style.GOOD if mirror.armed else steam_style.MUTED))
        steam_style.label(cr, mirror.message, 20, 145, 25, max_width=1200)
        cr.set_source_rgb(*steam_style.MUTED)
        steam_style.label(cr, mirror.hint, SCREEN_WIDTH / 2, 1045, 23,
                          centered=True, max_width=1200)

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._stop_mirror()
        if getattr(self, "keyboard_guard", None) is not None:
            self.keyboard_guard.stop()
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

    def on_destroy(self, *_) -> None:
        self.request_quit()

    def request_quit(self, signum: int = 0) -> bool:
        # Own the loop explicitly: capture libraries may also use GLib and
        # must not affect which nested Gtk.main() level receives a quit.
        if getattr(self, "main_loop", None) is not None:
            self.main_loop.quit()
        return False


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
    app.main_loop = GLib.MainLoop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, app.request_quit, sig)
    try:
        app.start()
        app.main_loop.run()
        return app.exit_code
    finally:
        app.cleanup()
        if app.mirror is not None:
            app.mirror.wait()


if __name__ == "__main__":
    raise SystemExit(main())
