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
VENDOR = BASE.parent.parent / "vendor" / "ratatoskr"
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
from .monitor_select import choose_bottom_monitor, MODE_GAMEMODE, MODE_DESKTOP
from .toolkit_touch import ToolkitTouch
from . import steam_style
from . import steam_keys
from .keyboard_pulses import KeyboardPulses
from .keyboard_redraw import KeyboardRedraw, widget_rect
from .paint_damage import clip_regions, intersects
from .static_layer import StaticLayer
from .key_feedback import KeyFeedback
from .keyboard_languages import KeyboardLanguages
from . import keyboard_language_view
from .scroll_output import ScaledScroll, read_scroll_scale
from .steam_keyboard_guard import SteamKeyboardGuard, keyboard_guard_wanted
from .panel_modes import SUPPORTED_MODES, normalize_mode
from .panel_position import PanelPosition, TOUCH_MODES
from . import touchscreen_selector
from .input_settings import read_settings, write_settings, SettingsDraft, NUMBERS, CHOICES
from . import settings_view
from .update_controller import UpdateController

# Isolate our settings/socket names from a separately installed Ratatoskr.
upstream.CONFIG_PATH = str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "thor-panel/config.json")
upstream.SOCKET_PATH = str(Path(os.environ["XDG_RUNTIME_DIR"]) / "thor-panel-unused.sock")
# A single shared table for rendering and hit tests; keyboard bounds stay fixed.
upstream.HEADER_BUTTONS = (
    ("trackpad", 12, 140), ("split", 164, 100), ("position", 276, 168),
    ("preferences", 456, 104), ("left", 572, 100), ("right", 684, 100),
    ("pen", 796, 180), ("hide", 988, 104), ("close", 1104, 124),
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
        self.position = None
        self.preferences = None
        self.updates = None
        self._updates_timer = None
        self.languages = None
        self._language_consumed = set()
        self._last_input_mode = "split"
        self._position_draw_state = None
        self._position_background = StaticLayer()
        self._touch_menu_open = False
        self._discarding_contacts = False
        # Unlike ToolkitTouch, this set survives logical-contact resets when
        # selecting a tab/control. Never mistake the selecting finger for up.
        self._physical_sequences = set()
        self.keyboard_redraw = KeyboardRedraw()
        self.main_loop = None
        super().__init__()
        self.key_feedback = KeyFeedback(GLib.timeout_add, GLib.source_remove,
                                        self._invalidate_keyboard)
        self.position = PanelPosition(sensitivity=self.input_cfg["position_sensitivity"],
                                      touch_mode=self.touch_mode, pad=touchscreen_selector.PAD)
        self._position_revision = self.position.revision
        self.scroll_output = ScaledScroll(self.bridge.emit_scroll, self.scroll_scale)
        self.bridge.emit_scroll = self.scroll_output.scroll
        print(
            f"[scroll] speed={self.gesture.scroll_speed} output_scale={self.scroll_output.scale:g}",
            flush=True,
        )
        # Keep the GTK thread free while a key's 20 ms pulse is held. All
        # keyboard repeat/release work stays on this same event-loop thread.
        self.key_pulses = KeyboardPulses(
            send_key=self._send_key_pulse,
            schedule=GLib.timeout_add,
            cancel=GLib.source_remove,
        )
        self.bridge.tap_key = self.key_pulses.tap
        self.raw_key_pulses = KeyboardPulses(
            send_key=self.bridge.key, schedule=GLib.timeout_add, cancel=GLib.source_remove,
        )
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
        self.languages = KeyboardLanguages(
            self.input_cfg["keyboard_language"], mode=self.session_mode,
            runtime=os.environ["XDG_RUNTIME_DIR"], changed=self._queue_language_draw,
            dispatch=GLib.idle_add, forward_key=self.raw_key_pulses.tap,
        )
        self._install_language_key()
        self.updates = UpdateController(BASE.parent.parent, dispatch=GLib.idle_add,
                                        changed=self._updates_changed)
        self.update_mode_bounds()
        Gdk.Display.get_default().connect("monitor-removed", self._on_monitor_removed)
        Gdk.Display.get_default().get_default_screen().connect("monitors-changed", self._on_monitors_changed)

    def load_config(self) -> None:
        self.mode = "split"
        self.scroll_scale = 1.0
        cfg = {}
        try:
            loaded = json.loads(Path(upstream.CONFIG_PATH).read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg = loaded
        except (OSError, ValueError, TypeError):
            pass
        self.input_cfg = read_settings(cfg)
        self.touch_mode = cfg.get("touch_mode") if cfg.get("touch_mode") in TOUCH_MODES else "position"
        self.scroll_scale = read_scroll_scale(self.input_cfg["scroll_scale"])
        saved_mode = normalize_mode(cfg.get("mode"))
        if saved_mode is not None and saved_mode != "preferences":
            self.mode = saved_mode
        self._last_input_mode = self.mode
        try:
            self.gesture.set_settings(**{**cfg, **self.input_cfg})
        except (ValueError, TypeError, OverflowError):
            self.gesture.set_settings(**self.input_cfg)
        upstream.keyboard_settings.apply(self.keyboard_cfg, self.input_cfg)
        # Keep this app free of system-wide pointer and dimming overrides.
        self.pen_mode = "off"
        self.gesture.set_settings(stylus_mode=False)
        self.mirror_cfg["mirror_dim"] = False
        # Keep the panel at the chosen brightness when idle. This only
        # disables Ratatoskr's painted veil; it does not change OS power rules.
        self.burn_in.idle_floor = 1.0
        self.gleipnir_cfg["gleipnir_ribbon"] = False

    def _current_settings(self):
        return read_settings({**getattr(self, "input_cfg", {}),
                              **self.gesture.get_settings(),
                              **self.keyboard_cfg, "scroll_scale": self.scroll_scale})

    def save_config(self) -> bool:
        try:
            write_settings(upstream.CONFIG_PATH, {
                "mode": self._last_input_mode if self.mode == "preferences" else self.mode,
                "touch_mode": getattr(self, "touch_mode", "position"),
                "debug_hud": self.show_debug_hud, "pen_mode": self.pen_mode,
                **self.gesture.get_settings(), **self.mirror_cfg,
                **self.keyboard_cfg, **self.gleipnir_cfg,
                **getattr(self, "input_cfg", {}), "scroll_scale": self.scroll_scale,
            })
            return True
        except (OSError, ValueError, TypeError):
            print("[settings] Could not save configuration; existing file retained", flush=True)
            return False

    def _save_preferences(self):
        draft = self.preferences
        if draft is None:
            return
        values = read_settings(draft.values)
        try:
            # Persist before applying. Failure must not claim a saved change.
            write_settings(upstream.CONFIG_PATH, values)
        except (OSError, ValueError, TypeError):
            draft.message, draft.error = "保存失败；请检查用户配置文件和目录权限", True
            return
        self.input_cfg = values
        self.gesture.set_settings(**values)
        upstream.keyboard_settings.apply(self.keyboard_cfg, values)
        self.scroll_scale = values["scroll_scale"]
        self.scroll_output.scale = self.scroll_scale
        self.scroll_output.rest_x = self.scroll_output.rest_y = 0.
        if self.position is not None:
            self.position.position_gesture.sensitivity = values["position_sensitivity"]
        if getattr(self, "languages", None) is not None and self.languages.language != values["keyboard_language"]:
            self.languages.set_language(values["keyboard_language"])
        draft.mark_saved()

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
        GLib.timeout_add(16, self._on_position_tick)

    def _position_visible(self) -> bool:
        return (self.session_mode == "game" and self.mode == "position"
                and not self.collapsed and self.window.get_mapped())

    def _stop_position(self) -> None:
        self._touch_menu_open = False
        if getattr(self, "position", None) is not None:
            self.position.stop()
        self._position_draw_state = None

    def _on_position_tick(self) -> bool:
        if self._cleaned:
            return False
        if not self._position_visible() or self.position is None:
            return True
        self.position.tick(contacts_down=(bool(self._physical_sequences)
                                         or getattr(self, '_touch_menu_open', False)))
        if self._position_revision != self.position.revision:
            self._clear_panel_contacts()
            self._position_revision = self.position.revision
        # Contact feedback belongs to the upper marker. Moving or lifting
        # fingers must not invalidate the lower screen's static touch surface.
        state = (self.position.armed, self.position.auto_requested, self.position.message)
        if state != self._position_draw_state:
            self._position_draw_state = state
            self.drawing_area.queue_draw()
        return True

    def _on_map(self, *_) -> None:
        self._sync_keyboard_guard()
        if self._position_visible() and self.position is not None:
            self.position.start()

    def _clear_panel_contacts(self) -> None:
        # Dropping pre-arm fingers must not cancel the newly armed backend.
        self._discarding_contacts = True
        try:
            self.touch.release_all()
            self._reset_input()
        finally:
            self._discarding_contacts = False

    def _on_stats_tick(self) -> bool:
        if self._cleaned:
            return False
        self._sync_keyboard_guard()
        self._queue_stats_draw()
        return True

    def _queue_stats_draw(self):
        recent = time.monotonic()-getattr(self, '_last_keyboard_activity', -float('inf')) < .25
        typing = (self.mode == 'split' and not self.collapsed and not self.ui_hidden
                  and (recent or getattr(self, 'held_key', None) is not None))
        if not typing:
            self.drawing_area.queue_draw()
            return
        # The monitor row changes once per second, not every keycap. Let a
        # quiet status tick perform the full repaint/orbital update instead.
        allocation = self.drawing_area.get_allocation()
        rect = (-5,upstream.HEADER_BUTTONS_H-5,SCREEN_WIDTH+10,upstream.STATUS_RIBBON_H+10)
        self.drawing_area.queue_draw_area(*widget_rect(rect,allocation.width,allocation.height))

    def _sync_keyboard_guard(self, *_) -> None:
        if getattr(self, "keyboard_guard", None) is not None:
            self.keyboard_guard.update(keyboard_guard_wanted(
                self.session_mode, self.mode, self.collapsed, self.window.get_mapped(),
            ))
        if getattr(self, "languages", None) is not None:
            self.languages.sync(self.mode == "split" and not self.collapsed
                                and self.window.get_mapped())

    def _send_key_pulse(self, code, down):
        consumed = self._language_consumed
        if not down and code in consumed:
            consumed.discard(code)
            return
        languages = getattr(self, "languages", None)
        if down and languages is not None and languages.key(
            code, shift=self.mods.active("shift") and not self.mods.locked("shift"),
            caps=self.mods.locked("shift"),
            shortcut=any(self.mods.active(key) for key in ("ctrl", "alt", "super")),
        ):
            consumed.add(code)
            return
        self.bridge.key(code, down)

    def _install_language_key(self):
        for row in self.kb_layout.rows:
            for key in row:
                if key.special == "super":
                    key.label = key.shift_label = "中/EN"
                    key.special = "language"
                    key.is_modifier = key.is_letter = False

    def _keyboard_down(self, tid, x, y):
        key = self.kb_layout.hit_test(x, y)
        if key is not None and key.special == "language":
            self._change_keyboard_language()
            return
        super()._keyboard_down(tid, x, y)

    def _queue_keyboard_draw(self):
        """Invalidate only old/new keycaps when no label or modifier changed."""
        self._last_keyboard_activity = time.monotonic()
        feedback = getattr(self, 'key_feedback', None)
        if feedback is not None:
            feedback.sync(self.active_key_press)
        self._invalidate_keyboard()

    def _visible_key_codes(self):
        feedback = getattr(self, 'key_feedback', None)
        return feedback.visible if feedback is not None else self.active_key_press

    def _invalidate_keyboard(self):
        if getattr(self, '_keyboard_damage_source', None):
            return
        def invalidate():
            self._keyboard_damage_source = None
            if self._cleaned:
                return False
            damage = getattr(self, 'keyboard_redraw', None)
            if (damage is None or self.mode != 'split' or self.ui_hidden
                    or self.collapsed):
                self.drawing_area.queue_draw()
                return False
            regions = damage.regions(self.kb_layout, self._visible_key_codes())
            if regions is None:
                self.drawing_area.queue_draw()
                return False
            allocation = self.drawing_area.get_allocation()
            for rect in regions:
                self.drawing_area.queue_draw_area(*widget_rect(rect,allocation.width,allocation.height))
            return False
        self._keyboard_damage_source = GLib.idle_add(invalidate)

    def _queue_language_draw(self):
        if self._cleaned:
            return
        self._last_keyboard_activity = time.monotonic()
        if self.mode != 'split' or self.collapsed or self.ui_hidden:
            self.drawing_area.queue_draw()
            return
        allocation = self.drawing_area.get_allocation()
        rect = (-5,self._language_top()-5,SCREEN_WIDTH+10,keyboard_language_view.HEIGHT+10)
        self.drawing_area.queue_draw_area(*widget_rect(rect,allocation.width,allocation.height))

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

    def _stalled_trackpad_begin(self, sequence, x, y) -> bool:
        """Recover one quiet leftover scroll contact on a fresh trackpad press.

        The Thor driver can retain an old slot too, so GTK may never report
        an authoritative new group. This deliberately narrow fallback waits
        for three seconds without any real touch event (including a lift).
        It never times out a held keyboard key or a continuing contact.
        """
        if (sequence is None or self.collapsed or self.mode not in ("trackpad", "split")
                or not self.touch.enabled or self.touch.owns_sequence(sequence)):
            return False
        contacts = self.touch.active
        if (len(contacts) != 1 or self.gesture.max_fingers < 2
                or self._touch_owner.get(contacts[0].tid) != "trackpad"
                or self.gesture.is_dragging or self.held_ui_button is not None
                or self.held_key is not None
                or getattr(self.bridge, "held_buttons", ())
                or getattr(self.bridge, "held_keys", ())):
            return False
        try:
            lx, ly = self.touch.to_logical(x, y)
        except (ValueError, TypeError):
            return False
        return self._owner_at(lx, ly) == "trackpad" and self.touch.quiet_for() >= 3.0

    def _start_key_repeat(self, key) -> None:
        if not getattr(self, "input_cfg", {}).get("keyboard_repeat_enabled", True):
            return
        self.key_pulses.begin_repeat(
            key.code, self.keyboard_cfg["keyboard_repeat_delay_ms"],
            self.keyboard_cfg["keyboard_repeat_interval_ms"],
        )

    def _stop_key_repeat(self) -> None:
        if hasattr(self, "key_pulses"):
            self.key_pulses.stop_repeat()

    def _end_key_press(self) -> None:
        before = getattr(self, 'active_key_press', None)
        if hasattr(self, "key_pulses"):
            # The character must go up before consuming its one-shot modifier.
            self.key_pulses.release()
        if hasattr(self, "raw_key_pulses"):
            self.raw_key_pulses.release()
        super()._end_key_press()
        if before is not None:
            self._queue_keyboard_draw()

    def _send_keys(self, events) -> None:
        events = list(events)
        if events and hasattr(self, "key_pulses"):
            self.key_pulses.flush_pending()
        if (getattr(self, "languages", None) is not None
                and any(down and code in (29, 56, 125) for code, down in events)):
            self.languages.reset()
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
        if getattr(self, 'key_feedback', None) is not None:
            self.key_feedback.clear()
        if getattr(self, "preferences", None) is not None:
            self.preferences.drag = None
        if getattr(self, "languages", None) is not None:
            self.languages.reset()

    def _cancel_contact(self, tid: int, now: float) -> None:
        # A compositor cancel must not turn into a click on lift.
        if (getattr(self, "position", None) is not None
                and not getattr(self, "_discarding_contacts", False)):
            self._touch_menu_open = False
            self.position.pause(manual=False)
        self._reset_input()

    def _on_unmap(self, *_) -> None:
        self._stop_position()
        self._physical_sequences.clear()
        if getattr(self, "keyboard_guard", None) is not None:
            self.keyboard_guard.update(False)
        if getattr(self, "languages", None) is not None:
            self.languages.sync(False)
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
                    if self.position is not None:
                        self.position.pause(manual=False)

    def _on_touch(self, widget, event) -> bool:
        if self._cleaned:
            return True
        sequence = event.get_event_sequence()
        initial = (sequence is not None and event.type == Gdk.EventType.TOUCH_BEGIN
                   and event.touch.emulating_pointer)
        if sequence is not None:
            if event.type == Gdk.EventType.TOUCH_BEGIN:
                if initial:
                    self._physical_sequences.clear()
                self._physical_sequences.add(sequence)
            elif event.type in (Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL):
                self._physical_sequences.discard(sequence)
        if self.collapsed:
            if event.type == Gdk.EventType.TOUCH_BEGIN:
                self._set_collapsed(False)
            return True
        with self.input_lock:
            if event.type == Gdk.EventType.TOUCH_BEGIN:
                self.burn_in.record_touch()
                # Read EventTouch's public first-contact field. GTK can copy
                # an event without retaining get_pointer_emulated()'s private
                # flag; on this device that method was false for every BEGIN
                # even while touch.emulating_pointer correctly marked firsts.
                # Only the trusted empty-seat boundary may clear old contacts.
                if initial and self.mode == "position" and self.touch.active:
                    self.position.touch('cancel', 0, time.monotonic())
                    self._clear_panel_contacts()
                recover = not initial and self._stalled_trackpad_begin(sequence, event.x, event.y)
                self.touch.begin(sequence, event.x, event.y,
                                 source_ms=event.get_time(),
                                 starts_new_group=initial, cancel_previous=recover)
                if recover:
                    # A quiet real anchor cannot be distinguished from a
                    # stale driver slot here. Recovery must never make a tap.
                    self.gesture.suppress_taps_for_current_group()
            elif event.type == Gdk.EventType.TOUCH_UPDATE:
                self.touch.update(sequence, event.x, event.y, source_ms=event.get_time())
            elif event.type == Gdk.EventType.TOUCH_END:
                self.touch.end(sequence)
            elif event.type == Gdk.EventType.TOUCH_CANCEL:
                self._touch_menu_open = False
                self.touch.release_all()
                if self.position is not None:
                    self.position.pause(manual=False)
                self._reset_input()
        # Do not forward a touch to the toolkit's emulated pointer handlers.
        return True

    def _handle_timed_touch_move(self, tid, x, y, now, motion_interval) -> None:
        owner = self._touch_owner.get(tid)
        if owner in ("languagebar", "touch_selector"):
            return
        if owner == "preferences" or self.mode == "preferences":
            self._handle_touch_move(tid, x, y, now)
            return
        if self.mode == "position" or owner == "position":
            if owner == "position" and self.position is not None:
                self.position.touch('move', tid, now, x, y, motion_interval=motion_interval)
            return
        if owner == "trackpad" or (owner is None and self.mode != "settings"):
            self.last_event_time = time.time()
            self.gesture.touch_move(tid, x, y, now, motion_interval=motion_interval)
            if self.show_debug_hud:
                self.drawing_area.queue_draw()
        else:
            self._handle_touch_move(tid, x, y, now)

    def _handle_touch_down(self, tid, x, y, now) -> None:
        if self._touch_selector_down(tid, x, y):
            return
        if (getattr(self, "languages", None) is not None and not self.ui_hidden
                and self.mode == "split"
                and keyboard_language_view.visible(self.languages)
                and self._language_top() <= y < self._language_top() + keyboard_language_view.HEIGHT):
            self._touch_owner[tid] = "languagebar"
            self._language_down(x, y)
            return
        # Status is display-only. The vendor ribbon opens its old controls page.
        if not self.ui_hidden and upstream.HEADER_BUTTONS_H <= y < upstream.HEADER_HEIGHT:
            self.last_event_time = time.time()
            self._touch_owner[tid] = "status"
            return
        if self.mode == "preferences" and y >= upstream.HEADER_HEIGHT:
            self._touch_owner[tid] = "preferences"
            self._preferences_down(tid, x, y)
            return
        if self.mode == "position" and y >= upstream.HEADER_HEIGHT:
            self._touch_owner[tid] = "position"
            if self.position is not None:
                self.position.touch('begin', tid, now, x, y)
            return
        super()._handle_touch_down(tid, x, y, now)

    def _handle_touch_move(self, tid, x, y, now) -> None:
        owner = self._touch_owner.get(tid)
        if owner in ("languagebar", "touch_selector"):
            return
        if owner == "preferences" or self.mode == "preferences":
            draft = getattr(self, "preferences", None)
            if owner == "preferences" and draft and draft.drag and draft.drag[0] == tid:
                draft.slide(draft.drag[1], x)
                self.drawing_area.queue_draw()
            return
        if self.mode == "position" or owner == "position":
            if owner == "position" and self.position is not None:
                self.position.touch('move', tid, now, x, y)
            return
        super()._handle_touch_move(tid, x, y, now)

    def _handle_touch_up(self, tid, now) -> None:
        if self._touch_owner.get(tid) in ("languagebar", "touch_selector"):
            self._touch_owner.pop(tid, None)
            return
        if self.mode == "preferences" or self._touch_owner.get(tid) == "preferences":
            self._touch_owner.pop(tid, None)
            draft = getattr(self, "preferences", None)
            if draft and draft.drag and draft.drag[0] == tid:
                draft.drag = None
            return
        if self.mode == "position" or self._touch_owner.get(tid) == "position":
            if self._touch_owner.pop(tid, None) == "position" and self.position is not None:
                self.position.touch('end', tid, now)
            return
        super()._handle_touch_up(tid, now)

    def _apply_anchors(self) -> None:
        for edge in (GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT, GtkLayerShell.Edge.BOTTOM):
            GtkLayerShell.set_anchor(self.window, edge, True)
        GtkLayerShell.set_anchor(self.window, GtkLayerShell.Edge.TOP, not self.collapsed)
        self.window.set_size_request(-1, 72 if self.collapsed else -1)
        self.window.resize(1, 1)

    def _set_collapsed(self, collapsed: bool) -> None:
        self._stop_position()
        with self.input_lock:
            self.touch.release_all()
            self._reset_input()
            self.collapsed = collapsed
        self._apply_anchors()
        self._sync_keyboard_guard()
        if self._position_visible() and self.position is not None:
            self.position.start()
        self.drawing_area.queue_draw()

    def set_mode(self, mode: str, restart_hint: bool = True) -> None:
        # Old settings or callers may still name a removed page.
        mode = normalize_mode(mode)
        if mode not in SUPPORTED_MODES:
            return
        if mode == "position" and self.session_mode != "game":
            return
        if mode == "preferences" and self.mode == "preferences":
            return
        previous_mode = self.mode
        self._stop_position()
        if hasattr(self, "touch"):
            self.touch.release_all()
            self._reset_input()
        if mode == "preferences":
            self._last_input_mode = previous_mode
            self.preferences = SettingsDraft(self._current_settings())
            self.mode = mode
            self.drawing_area.queue_draw()
        elif mode == "position":
            self.mode = mode
            self.save_config()
            if self._position_visible() and self.position is not None:
                self.position.start()
            self.drawing_area.queue_draw()
        else:
            super().set_mode(mode, restart_hint)
        if mode != "preferences":
            self.preferences = None
            self._last_input_mode = mode
        self._sync_keyboard_guard()

    def _preferences_down(self, tid, x, y):
        draft = self.preferences
        if draft is None or draft.drag is not None:
            return
        action, key = draft.hit(x, y)
        if action == "section":
            draft.section = key
            updates = getattr(self, 'updates', None)
            if updates:
                updates.confirming = False
                if key == 'updates':
                    updates.refresh()
                    self._watch_updates()
        elif action == 'check_update':
            if getattr(self, 'updates', None):
                self.updates.check()
        elif action == 'install_update':
            updates = getattr(self, 'updates', None)
            if updates and updates.available and not draft.dirty:
                if updates.confirming:
                    updates.install()
                else:
                    updates.confirming = True
        elif action == 'cancel_update':
            if getattr(self, 'updates', None):
                self.updates.confirming = False
        elif action in ("minus", "plus"):
            spec = NUMBERS[key]
            draft.change(key, draft.values[key] + spec.step * (1 if action == "plus" else -1))
        elif action == "slider":
            draft.drag = tid, key
            draft.slide(key, x)
        elif action == "toggle":
            draft.change(key, not draft.values[key])
        elif action == "choice":
            choices = list(CHOICES[key])
            draft.change(key, choices[(choices.index(draft.values[key]) + 1) % len(choices)])
        elif action == "defaults":
            draft.reset_section()
        elif action == "discard":
            draft.discard()
        elif action == "save":
            self._save_preferences()
        self.drawing_area.queue_draw()

    def _updates_changed(self):
        if (not getattr(self, '_cleaned', False) and self.mode == 'preferences'
                and self.preferences and self.preferences.section == 'updates'):
            self.drawing_area.queue_draw()

    def _watch_updates(self):
        if getattr(self, '_updates_timer', None):
            return
        def poll():
            if (getattr(self, '_cleaned', False) or self.mode != 'preferences'
                    or not self.preferences or self.preferences.section != 'updates'):
                self._updates_timer = None
                return False
            self.updates.refresh()
            self._updates_changed()
            return True
        self._updates_timer = GLib.timeout_add(1000, poll)

    def _handle_header_touch(self, tid, x, y, down) -> None:
        if self._touch_selector_down(tid, x, y):
            return
        key = next((k for k, bx, bw in upstream.HEADER_BUTTONS if bx <= x <= bx + bw), None)
        if key == "close":
            with self.input_lock:
                self.touch.set_enabled(False)
                self._reset_input()
            self.exit_code = 0
            self.request_quit()
        elif key == "hide":
            self._set_collapsed(True)
        elif key in ("position", "preferences"):
            self.set_mode(key, restart_hint=False)
        elif self.mode == "preferences" and key in ("left", "right"):
            # Settings never send clicks into the game or hold a mouse button.
            return
        elif self.mode == "position" and key in ("left", "right", "pen"):
            # Mouse controls are replaced by the dropdown in the touch page.
            if key == 'pen' and self.position is not None:
                if getattr(self, 'touch_mode', 'position') == 'position':
                    self._clear_panel_contacts()
                    self.position.center()
            self.drawing_area.queue_draw()
        elif key == "pen":
            self.touch.release_all()
            self._reset_input()
            self.drawing_area.queue_draw()
        else:
            super()._handle_header_touch(tid, x, y, down)

    def _header_button_look(self, key):
        if key == "preferences":
            return "设置", self.mode == "preferences", upstream.theme.BTN_ACCENT_DEFAULT
        if key == "position":
            return "触屏", self.mode == "position", upstream.theme.BTN_ACCENT_DEFAULT
        if self.mode == "position" and key == "pen":
            return "定位居中", False, upstream.theme.BTN_ACCENT_DEFAULT
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
        regions = clip_regions(cr)
        if intersects(regions, (0, 0, SCREEN_WIDTH, upstream.HEADER_BUTTONS_H)):
            self._draw_header(cr)
        if intersects(regions, (0, upstream.HEADER_BUTTONS_H, SCREEN_WIDTH,
                                upstream.STATUS_RIBBON_H)):
            self._draw_status_ribbon(cr)
        if self.mode in ('trackpad', 'split'):
            bottom = upstream.SPLIT_Y if self.mode == 'split' else SCREEN_HEIGHT
            if intersects(regions, (0, upstream.HEADER_HEIGHT, SCREEN_WIDTH,
                                    bottom-upstream.HEADER_HEIGHT)):
                self._draw_trackpad_surface(cr, upstream.HEADER_HEIGHT,
                                            bottom-upstream.HEADER_HEIGHT)
        if self.mode in ('keyboard', 'split'):
            # The temporary candidate bar can extend above the key area.
            if intersects(regions, (0, self._language_top(), SCREEN_WIDTH,
                                    SCREEN_HEIGHT-self._language_top())):
                self._draw_keyboard(cr)

    def _draw_header(self, cr) -> None:
        buttons = upstream.HEADER_BUTTONS
        if self.mode == 'position':
            hidden = {'left', 'right'}
            if getattr(self, 'touch_mode', 'position') == 'direct':
                hidden.add('pen')
            buttons = tuple(button for button in buttons if button[0] not in hidden)
        steam_style.draw_header(self, cr, buttons,
                                upstream.HEADER_BUTTON_Y, upstream.HEADER_BUTTON_H,
                                SCREEN_WIDTH)
        if self.mode == 'position':
            touchscreen_selector.draw_button(cr, self.touch_mode,
                                             getattr(self, '_touch_menu_open', False))

    def _draw_status_ribbon(self, cr) -> None:
        steam_style.draw_status(self, cr, upstream.HEADER_BUTTONS_H,
                                upstream.STATUS_RIBBON_H, SCREEN_WIDTH)

    def _draw_trackpad_surface(self, cr, y, h) -> None:
        steam_style.draw_trackpad(self, cr, y, h, SCREEN_WIDTH)

    def _draw_keyboard(self, cr) -> None:
        if getattr(self, "languages", None) is not None:
            if (keyboard_language_view.visible(self.languages)
                    and intersects(clip_regions(cr), (0, self._language_top(),
                                                       SCREEN_WIDTH, keyboard_language_view.HEIGHT))):
                keyboard_language_view.draw(cr, self.languages, self._language_top())
        steam_keys.draw_keyboard(self, cr)
        visible = self._visible_key_codes()
        if getattr(self, 'keyboard_redraw', None) is not None:
            self.keyboard_redraw.painted(self.kb_layout, visible, cr)
        feedback = getattr(self, 'key_feedback', None)
        if feedback is not None:
            painted = [key.code for row in self.kb_layout.rows for key in row
                       if key.code in feedback.visible and all(cr.in_clip(x,y)
                           for x in (key.x,key.x+key.w) for y in (key.y,key.y+key.h))]
            feedback.painted(painted)

    def _language_top(self):
        # The split overlay appears only while composing; idle pad/key bounds
        # are exactly the same as before multilingual input was introduced.
        return upstream.SPLIT_Y - keyboard_language_view.HEIGHT

    def _language_down(self, x, y):
        action, value = keyboard_language_view.hit(x, y, self._language_top())
        if action == "candidate":
            self.languages.choose(self.languages.page * 6 + value)
        elif action == "page":
            self.languages.turn_page(value)
        elif action == "cancel":
            self._clear_panel_contacts()
            self.languages.reset()
        self.drawing_area.queue_draw()

    def _change_keyboard_language(self):
        language = "zh_CN" if self.languages.language == "en_US" else "en_US"
        try:
            write_settings(upstream.CONFIG_PATH, {"keyboard_language": language})
        except (OSError, ValueError, TypeError):
            self.languages.message = "语言保存失败，原设置保留"
            self.drawing_area.queue_draw()
            return
        self._clear_panel_contacts()
        self.input_cfg["keyboard_language"] = language
        self.languages.set_language(language)
        self.drawing_area.queue_draw()

    def _handle_settings_touch(self, *_) -> None:
        pass  # Monitoring is read-only; Armada keeps hardware controls.

    def _handle_settings_drag(self, *_) -> None:
        pass

    def _draw_quick_settings(self, cr) -> None:
        steam_style.draw_monitor(self, cr, upstream.HEADER_HEIGHT,
                                 SCREEN_WIDTH, SCREEN_HEIGHT)

    def _paint_orbital_offset(self, cr, now):
        # Partial keycap updates must use the same origin as the surrounding
        # retained pixels. The regular full status repaint advances the orbit.
        left,top,right,bottom = cr.clip_extents()
        if (not hasattr(self, '_paint_origin')
                or (left <= .5 and top <= .5 and right >= SCREEN_WIDTH-.5 and bottom >= SCREEN_HEIGHT-.5)):
            self._paint_origin = self.burn_in.get_orbital_offset(now)
        return self._paint_origin

    def _draw_collapsed(self, cr, width, height) -> None:
        steam_style.draw_collapsed(cr, width, height)

    def on_draw(self, widget, cr) -> bool:
        allocation = widget.get_allocation()
        if self.collapsed:
            self._draw_collapsed(cr, allocation.width, allocation.height)
            return True
        if self.mode == "preferences":
            cr.save()
            cr.scale(allocation.width / SCREEN_WIDTH, allocation.height / SCREEN_HEIGHT)
            self._draw_ui(cr)
            if self.preferences is not None:
                settings_view.draw(cr, self.preferences, getattr(self, 'updates', None))
            cr.restore()
            return True
        if self.mode == "position":
            cr.save()
            cr.scale(allocation.width / SCREEN_WIDTH, allocation.height / SCREEN_HEIGHT)
            self._draw_ui(cr)
            self._draw_position(cr)
            if getattr(self, '_touch_menu_open', False):
                touchscreen_selector.draw_menu(cr, self.touch_mode)
            cr.restore()
            return True
        cr.save()
        cr.scale(allocation.width / SCREEN_WIDTH, allocation.height / SCREEN_HEIGHT)
        try:
            return super().on_draw(widget, cr)
        finally:
            cr.restore()

    def _draw_position(self, cr) -> None:
        position = self.position
        if position is None:
            return
        layer = getattr(self, '_position_background', None)
        if layer is None:
            self._position_background = layer = StaticLayer()
        layer.paint(cr, (position.touch_mode, position.armed, position.message,
                         bool(getattr(self, '_touch_menu_open', False))),
                    SCREEN_WIDTH, SCREEN_HEIGHT, self._draw_position_background)

    def _draw_position_background(self, cr) -> None:
        position = self.position
        # Cache an opaque body so antialiased text is composited exactly once.
        # The header/status remain transparent and keep their independent draws.
        cr.set_source_rgb(*steam_style.BG)
        cr.rectangle(0, upstream.HEADER_HEIGHT, SCREEN_WIDTH,
                     SCREEN_HEIGHT-upstream.HEADER_HEIGHT)
        cr.fill()
        steam_style.rounded(cr, 20, 168, 1200, 882, 12,
                            steam_style.SURFACE, steam_style.BORDER)
        cr.set_source_rgb(*(steam_style.GOOD if position.armed else steam_style.MUTED))
        message = ('请选择触屏模式；收起后自动恢复' if getattr(self, '_touch_menu_open', False)
                   else position.message)
        steam_style.label(cr, message, 20, 150, 24, max_width=1200)
        if position.touch_mode == 'direct':
            cr.set_source_rgb(*steam_style.ACCENT)
            steam_style.label(cr, '直接触屏', 620, 370, 40, centered=True)
            cr.set_source_rgb(*steam_style.FG)
            for text, y in (('下屏落指位置，对应上屏相同位置', 490),
                            ('多根手指独立触摸、移动与抬起', 570),
                            ('上屏圆环标记每一个触点', 650)):
                steam_style.label(cr, text, 620, y, 30, centered=True, max_width=1120)
            cr.set_source_rgb(*steam_style.MUTED)
            steam_style.label(cr, '手势由上屏应用处理 · 不转成滚轮或第二指确认',
                              620, 940, 24, centered=True, max_width=1120)
            return
        cr.set_source_rgb(*steam_style.ACCENT)
        steam_style.label(cr, '只看上屏操作', 620, 370, 40, centered=True)
        cr.set_source_rgb(*steam_style.FG)
        for text, y in (('第一指滑动：移动定位圆环', 490),
                        ('第二指按住：在圆环位置触摸', 570),
                        ('保持第二指，移动第一指：拖动', 650),
                        ('抬起第二指：释放触摸', 730)):
            steam_style.label(cr, text, 620, y, 30, centered=True, max_width=1120)
        cr.set_source_rgb(*steam_style.MUTED)
        steam_style.label(cr, '整个下方区域均可操作 · 不传输上屏画面',
                          620, 940, 25, centered=True, max_width=1120)

    def _touch_selector_down(self, tid, x, y):
        if self.mode != 'position':
            return False
        if getattr(self, '_touch_menu_open', False):
            self._touch_menu_open = False
            selected = touchscreen_selector.hit_option(x, y)
            if selected is not None:
                self._set_touch_mode(selected)
        elif touchscreen_selector.BUTTON.contains(x, y):
            # Release old native touches, but keep automatic enable requested.
            # The open menu also blocks rearming after the selecting finger lifts.
            self.position.pause(manual=False)
            self._clear_panel_contacts()
            self._touch_menu_open = True
        else:
            return False
        self._touch_owner[tid] = 'touch_selector'
        self.drawing_area.queue_draw()
        return True

    def _set_touch_mode(self, mode):
        if mode not in TOUCH_MODES or mode == getattr(self, 'touch_mode', 'position'):
            return
        self._clear_panel_contacts()
        self.position.set_touch_mode(mode)
        self.touch_mode = mode
        self.save_config()
        self._position_draw_state = None

    def cleanup(self) -> None:
        if self._cleaned:
            return
        if getattr(self, 'updates', None):
            self.updates.close()
        if getattr(self, '_updates_timer', None):
            GLib.source_remove(self._updates_timer)
            self._updates_timer = None
        self._stop_position()
        if getattr(self, "languages", None) is not None:
            self.languages.close()
        if getattr(self, "keyboard_guard", None) is not None:
            self.keyboard_guard.stop()
        try:
            if hasattr(self, "touch"):
                self.touch.release_all()
            self._reset_input()
        finally:
            if hasattr(self, "key_pulses"):
                self.key_pulses.close()
            if hasattr(self, "raw_key_pulses"):
                self.raw_key_pulses.close()
            if getattr(self, 'key_feedback', None) is not None:
                self.key_feedback.close()
            # The parent cleanup only closes this app's resources; our raw
            # fd stays -1, dim mirror never started, and IPC never bound.
            super().cleanup()

    def on_destroy(self, *_) -> None:
        self.request_quit()

    def request_quit(self, signum: int = 0) -> bool:
        # Quit this panel's explicit loop without affecting another GTK loop.
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
        if app.position is not None:
            app.position.wait()


if __name__ == "__main__":
    raise SystemExit(main())
