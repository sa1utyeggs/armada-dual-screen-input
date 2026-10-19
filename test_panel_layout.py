"""Check compact panel routing without creating a window or input device.

The real adapter needs Linux GTK to import. Reuse the existing keyboard test's
fake app setup through a module alias, without importing or inheriting its test
class into unittest discovery. No GTK loop, Steam connection or uinput runs.
"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


IS_LINUX = sys.platform == "linux"
if IS_LINUX:
    import test_panel_keyboard as keyboard_fixture


@unittest.skipUnless(IS_LINUX, "Real PanelApp routing requires Linux GTK")
class CompactPanelLayoutTests(unittest.TestCase):
    def setUp(self):
        keyboard_fixture.PanelKeyboardTests.setUp(self)
        self.panel = keyboard_fixture.panel_app
        self.app.mode = "split"
        self.app.session_mode = "game"
        self.app.collapsed = False
        self.app.show_debug_hud = False
        self.app.window = SimpleNamespace(get_mapped=Mock(return_value=True))
        self.app.keyboard_guard = Mock()
        self.app.touch = SimpleNamespace(release_all=Mock())
        self.app.gesture.touch_down = Mock()
        self.app.gesture.touch_move = Mock()
        self.app.gesture.touch_up = Mock()
        self.app.gesture.set_settings = Mock()
        self.app.burn_in = SimpleNamespace(notify_mode_change=Mock(), idle_floor=1.0)
        self.app.mirror_cfg = {"mirror_dim": False}
        self.app.gleipnir_cfg = {"gleipnir_ribbon": False}
        self.app.save_config = Mock()
        self.app.update_mode_bounds()
        # Tripwires make an accidental change to this fixture fail before it
        # can create a UI or a kernel input device.
        self.addCleanup(patch.stopall)
        patch.object(self.panel.upstream, "UInputBridge",
                     side_effect=AssertionError("No input devices in tests")).start()
        patch.object(self.panel.Gtk, "Window",
                     side_effect=AssertionError("No GTK windows in tests")).start()

    def test_header_exposes_only_two_modes_and_has_no_overlapping_buttons(self):
        buttons = self.panel.upstream.HEADER_BUTTONS
        names = [name for name, _, _ in buttons]
        self.assertEqual(names[:2], ["trackpad", "split"])
        self.assertTrue({"keyboard", "settings", "hud"}.isdisjoint(names))
        self.assertEqual(len(names), len(set(names)))
        for (_, x, width), (_, next_x, _) in zip(buttons, buttons[1:]):
            # Hit tests include both edges, so a positive gap is required.
            self.assertLess(x + width, next_x)
        for name, x, width in buttons:
            self.assertGreaterEqual(x, 0)
            self.assertGreater(width, 0)
            self.assertLessEqual(x + width, self.panel.SCREEN_WIDTH)
        self.assertEqual(self.app._header_button_look("split")[0], "键鼠")

    def test_header_mode_buttons_route_to_the_two_visible_modes(self):
        with patch.object(self.app, "set_mode") as select:
            for mode in ("trackpad", "split"):
                _, x, width = next(button for button in self.panel.upstream.HEADER_BUTTONS
                                   if button[0] == mode)
                self.app._handle_header_touch(1, x + width / 2, 30, True)
                select.assert_called_with(mode, restart_hint=False)
        self.assertFalse(self.bridge.events)

    def test_status_strip_is_inert_through_move_and_lift_in_both_modes(self):
        for mode in ("trackpad", "split"):
            for y in (80.0, 102.0, 123.999):
                with self.subTest(mode=mode, y=y), patch.object(self.app, "set_mode") as select:
                    self.app.mode = mode
                    self.app._handle_touch_down(17, 620, y, 1.0)
                    self.assertEqual(self.app._touch_owner[17], "status")
                    # A status touch keeps its original ownership even when
                    # dragged over the keyboard or header.
                    self.app._handle_touch_move(17, 620, 700, 1.1)
                    self.app._handle_timed_touch_move(17, 620, 20, 1.2, 0.01)
                    self.app._handle_touch_up(17, 1.3)
                    self.assertNotIn(17, self.app._touch_owner)
                    self.assertEqual(self.app.mode, mode)
                    select.assert_not_called()
        self.app.gesture.touch_down.assert_not_called()
        self.app.gesture.touch_move.assert_not_called()
        self.app.gesture.touch_up.assert_not_called()
        self.app.keyboard_guard.update.assert_not_called()
        self.assertFalse(self.bridge.events)

    def test_compact_header_and_split_boundaries_match_touch_routing(self):
        upstream = self.panel.upstream
        self.assertEqual(upstream.HEADER_BUTTONS_H, 80)
        self.assertEqual(upstream.STATUS_RIBBON_H, 44)
        self.assertEqual(upstream.HEADER_HEIGHT, 124)
        self.assertEqual(upstream.SPLIT_Y, 500)
        for mode in ("trackpad", "split"):
            self.app.mode = mode
            for y, expected in ((79.999, "header"), (80, "ribbon"),
                                (123.999, "ribbon"), (124, "trackpad"),
                                (499.999, "trackpad"),
                                (500, "keyboard" if mode == "split" else "trackpad")):
                with self.subTest(mode=mode, y=y):
                    self.assertEqual(self.app._owner_at(620, y), expected)
        self.app.mode = "split"
        self.app.update_mode_bounds()
        self.assertEqual(self.app.kb_layout.y, 500)
        self.assertEqual(self.app.kb_layout.height, 580)
        self.assertEqual(self.app.kb_layout.rows[0][0].y, 510)

    def test_old_config_modes_load_as_keys_mouse_without_rewriting_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            with patch.object(self.panel.upstream, "CONFIG_PATH", str(config)):
                for old_mode in ("keyboard", "settings", "split", "trackpad"):
                    with self.subTest(mode=old_mode):
                        before = json.dumps({"mode": old_mode, "scroll_speed": 1,
                                             "scroll_scale": 0.25,
                                             "keyboard_repeat_interval_ms": 60}).encode()
                        config.write_bytes(before)
                        self.app.load_config()
                        self.assertEqual(self.app.mode,
                                         "trackpad" if old_mode == "trackpad" else "split")
                        self.assertEqual(self.app.scroll_scale, 0.25)
                        self.assertEqual(self.app.keyboard_cfg["keyboard_repeat_interval_ms"], 60)
                        self.assertEqual(config.read_bytes(), before)

    def test_legacy_mode_calls_normalize_and_guard_tracks_visible_keyboard(self):
        for requested, expected, suppress in (("keyboard", "split", True),
                                               ("settings", "split", True),
                                               ("trackpad", "trackpad", False),
                                               ("split", "split", True)):
            with self.subTest(mode=requested):
                self.app.keyboard_guard.update.reset_mock()
                self.app.set_mode(requested, restart_hint=False)
                self.assertEqual(self.app.mode, expected)
                self.app.keyboard_guard.update.assert_called_once_with(suppress)
        self.assertFalse(self.bridge.events)

    def test_unknown_mode_calls_are_ignored_without_touch_or_guard_changes(self):
        self.app.mode = "trackpad"
        for requested in ("", "unknown", None):
            with self.subTest(mode=requested):
                self.app.set_mode(requested)
                self.assertEqual(self.app.mode, "trackpad")
        self.app.touch.release_all.assert_not_called()
        self.app.save_config.assert_not_called()
        self.app.keyboard_guard.update.assert_not_called()
        self.assertFalse(self.bridge.events)


if __name__ == "__main__":
    unittest.main()
