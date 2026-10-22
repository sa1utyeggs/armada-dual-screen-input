"""Real panel routing with simulated GTK/input objects; never opens a window."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.input_settings import DEFAULTS, SettingsDraft
from armada_dual_screen_input.scroll_output import ScaledScroll

IS_LINUX = sys.platform == "linux"
if IS_LINUX:
    import test_panel_keyboard as fixture


@unittest.skipUnless(IS_LINUX, "Real PanelApp preferences require Linux GTK")
class PanelPreferencesTests(unittest.TestCase):
    def setUp(self):
        fixture.PanelKeyboardTests.setUp(self)
        self.panel = fixture.panel_app
        self.app.mode = "split"
        self.app.session_mode = "game"
        self.app.collapsed = False
        self.app.preferences = None
        self.app.input_cfg = dict(DEFAULTS)
        self.app.scroll_scale = .25
        self.app._last_input_mode = "split"
        self.app.gesture = self.panel.upstream.TouchGestureProcessor(self.bridge, Mock())
        self.app.scroll_output = ScaledScroll(Mock(), self.app.scroll_scale)
        self.app.keyboard_guard = Mock()
        self.app.window = SimpleNamespace(get_mapped=lambda: True)
        self.app.touch = SimpleNamespace(release_all=Mock())
        self.app.drawing_area.queue_draw = Mock()
        self.app.show_debug_hud = False
        self.app.mirror_cfg = {"mirror_dim": False}
        self.app.gleipnir_cfg = {"gleipnir_ribbon": False}
        self.app.pen_mode = "off"
        self.app.burn_in = SimpleNamespace(notify_mode_change=Mock())
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Path(temp.name) / "config.json"
        patch.object(self.panel.upstream, "CONFIG_PATH", str(self.config)).start()
        patch.object(self.panel.upstream, "UInputBridge", side_effect=AssertionError("No uinput in tests")).start()
        patch.object(self.panel.Gtk, "Window", side_effect=AssertionError("No window in tests")).start()

    def enter(self):
        self.app.set_mode("preferences")

    def test_enter_settings_releases_held_keys_and_native_steam_guard(self):
        self.app._keyboard_down(1, self.app.kb_layout.rows[1][1].x + 1,
                                 self.app.kb_layout.rows[1][1].y + 1)
        self.enter()
        self.assertEqual(self.app.mode, "preferences")
        self.assertFalse(self.bridge.held_keys)
        self.assertFalse(self.scheduler.pending)
        self.app.keyboard_guard.update.assert_called_with(False)
        self.assertFalse(self.config.exists())

    def test_settings_header_never_sends_or_holds_game_mouse_buttons(self):
        self.enter()
        for key in ("left", "right"):
            _, x, width = next(b for b in self.panel.upstream.HEADER_BUTTONS if b[0] == key)
            self.app._handle_touch_down(10, x + width / 2, 30, 1.)
            self.app._handle_touch_up(10, 1.1)
        self.assertIsNone(self.app.held_ui_button)
        self.assertFalse(self.bridge.events)

    def test_header_settings_button_opens_the_preferences_page(self):
        _, x, width = next(b for b in self.panel.upstream.HEADER_BUTTONS if b[0] == "preferences")
        self.app._handle_touch_down(10, x + width / 2, 30, 1.)
        self.app._handle_touch_up(10, 1.1)
        self.assertEqual(self.app.mode, "preferences")
        self.assertFalse(self.bridge.events)

    def test_setting_drag_has_one_owner_and_cannot_move_the_upper_pointer(self):
        self.enter()
        with patch.object(self.app.gesture, "touch_move") as move:
            self.app._handle_touch_down(1, 800, 350, 1.)
            self.app._handle_touch_down(2, 1000, 350, 1.1)
            value = self.app.preferences.values["sensitivity"]
            self.app._handle_timed_touch_move(2, 640, 350, 1.2, .01)
            self.assertEqual(self.app.preferences.values["sensitivity"], value)
            self.app._handle_timed_touch_move(1, 968, 350, 1.3, .01)
            self.assertEqual(self.app.preferences.values["sensitivity"], 5.)
            self.app._handle_touch_up(2, 1.4)
            self.assertEqual(self.app.preferences.drag[0], 1)
            self.app._handle_touch_up(1, 1.5)
            self.assertIsNone(self.app.preferences.drag)
            move.assert_not_called()
        self.assertFalse(self.bridge.events)
        self.assertFalse(self.config.exists())

    def test_save_changes_runtime_and_survives_reload_and_later_mode_save(self):
        self.config.write_text(json.dumps({"mode": "position", "future": 42, "scroll_scale": .25}))
        self.enter()
        draft = self.app.preferences
        for key, value in (("sensitivity", 2.3), ("position_sensitivity", 3.),
                           ("marker_frame_rate", "30"),
                           ("scroll_scale", .1), ("keyboard_repeat_enabled", False),
                           ("keyboard_repeat_delay_ms", 500)):
            draft.change(key, value)
        self.app.position = SimpleNamespace(position_gesture=SimpleNamespace(sensitivity=2.), stop=Mock())
        self.app._save_preferences()
        self.assertEqual(self.app.gesture.sensitivity, 2.3)
        self.assertEqual(self.app.position.position_gesture.sensitivity, 3.)
        self.assertEqual(self.app.position.frame_rate, '30')
        self.assertEqual(self.app.scroll_output.scale, .1)
        self.assertFalse(draft.dirty)
        self.app.set_mode("trackpad")
        self.app.load_config()
        self.assertEqual(self.app.input_cfg["position_sensitivity"], 3.)
        self.assertEqual(self.app.input_cfg["marker_frame_rate"], '30')
        self.assertEqual(self.app.scroll_scale, .1)
        self.assertFalse(self.app.input_cfg["keyboard_repeat_enabled"])
        self.assertEqual(self.app.keyboard_cfg["keyboard_repeat_delay_ms"], 500)
        self.assertEqual(json.loads(self.config.read_text())["future"], 42)
        self.assertEqual(json.loads(self.config.read_text())["mode"], "trackpad")

    def test_save_failure_keeps_runtime_and_draft_for_retry(self):
        self.enter()
        self.app.preferences.change("sensitivity", 3.)
        with patch.object(self.panel, "write_settings", side_effect=PermissionError):
            self.app._save_preferences()
        self.assertEqual(self.app.gesture.sensitivity, 1.5)
        self.assertTrue(self.app.preferences.error)
        self.assertTrue(self.app.preferences.dirty)
        self.app._save_preferences()
        self.assertFalse(self.app.preferences.error)

    def test_leaving_preferences_discards_draft_and_releases_slider(self):
        self.enter()
        self.app.preferences.change("sensitivity", 4.)
        self.app.set_mode("split")
        self.assertIsNone(self.app.preferences)
        self.assertEqual(self.app.gesture.sensitivity, 1.5)
        self.enter()
        self.assertEqual(self.app.preferences.values["sensitivity"], 1.5)
        self.assertEqual(json.loads(self.config.read_text())["mode"], "split")

    def test_repeat_can_be_disabled_without_losing_the_initial_key_tap(self):
        self.app.input_cfg["keyboard_repeat_enabled"] = False
        key = self.app.kb_layout.rows[1][1]
        self.app._keyboard_down(1, key.x + 1, key.y + 1)
        self.scheduler.advance(1000)
        self.assertEqual(self.bridge.events, [(0, key.code, True), (20, key.code, False)])
        self.assertFalse(self.bridge.held_keys)

    def test_opening_settings_twice_keeps_unsaved_draft(self):
        self.enter()
        self.app.preferences.change("sensitivity", 3.)
        self.enter()
        self.assertTrue(self.app.preferences.dirty)
        self.assertEqual(self.app.preferences.values["sensitivity"], 3.)

    def test_update_buttons_need_confirmation_and_never_send_game_input(self):
        self.enter()
        self.app.updates = SimpleNamespace(available=True, confirming=False,
            refresh=Mock(), check=Mock(), install=Mock())
        self.app._watch_updates = Mock()
        self.app._preferences_down(1, 700, 250)
        self.assertEqual(self.app.preferences.section, 'updates')
        self.app._preferences_down(1, 200, 800)
        self.app.updates.check.assert_called_once()
        self.app._preferences_down(1, 900, 800)
        self.app.updates.install.assert_not_called()
        self.assertTrue(self.app.updates.confirming)
        self.app._preferences_down(1, 900, 880)
        self.assertFalse(self.app.updates.confirming)
        self.app._preferences_down(1, 900, 800)
        self.app._preferences_down(1, 900, 800)
        self.app.updates.install.assert_called_once()
        self.assertFalse(self.bridge.events)
        self.assertFalse(self.config.exists())

    def test_unsaved_settings_block_install_without_saving_or_discarding(self):
        self.enter()
        self.app.preferences.change('sensitivity', 3.)
        self.app.preferences.section = 'updates'
        self.app.updates = SimpleNamespace(available=True, confirming=True, install=Mock())
        self.app._preferences_down(1, 900, 800)
        self.app.updates.install.assert_not_called()
        self.assertTrue(self.app.preferences.dirty)
        self.assertFalse(self.config.exists())


if __name__ == "__main__":
    unittest.main()
