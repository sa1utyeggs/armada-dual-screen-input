"""Real panel language-bar routing with fake devices and a fake IME worker."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.input_settings import DEFAULTS
from armada_dual_screen_input.keyboard_languages import KeyboardLanguages
from armada_dual_screen_input.keyboard_pulses import KeyboardPulses
from test_keyboard_languages import FakeWorker, FakeXkb

IS_LINUX = sys.platform == "linux"
if IS_LINUX:
    import test_panel_keyboard as fixture


@unittest.skipUnless(IS_LINUX, "Real PanelApp language routing requires Linux GTK")
class PanelLanguageTests(unittest.TestCase):
    def setUp(self):
        fixture.PanelKeyboardTests.setUp(self)
        self.app.session_mode = "game"
        self.app.mode = "split"
        self.app.collapsed = False
        self.app.preferences = None
        self.app.input_cfg = dict(DEFAULTS)
        self.app._language_consumed = set()
        self.app.key_pulses._send_key = self.app._send_key_pulse
        self.app.raw_key_pulses = KeyboardPulses(self.bridge.key, self.scheduler.schedule,
                                                self.scheduler.cancel)
        self.addCleanup(self.app.raw_key_pulses.close)
        self.app.languages = KeyboardLanguages(
            "en_US", mode="game", runtime="/own/runtime", changed=lambda: None,
            dispatch=lambda cb: cb(), forward_key=self.app.raw_key_pulses.tap,
            worker_factory=FakeWorker, xkb_factory=FakeXkb,
        )
        self.addCleanup(self.app.languages.close)
        self.app.languages.sync(True)
        self.app._install_language_key()
        self.app.touch = SimpleNamespace(release_all=Mock())
        self.app.window = SimpleNamespace(get_mapped=lambda: True)
        self.app.keyboard_guard = None
        self.app.update_mode_bounds()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Path(directory.name) / "config.json"
        self.config.write_text(json.dumps({"sensitivity": 1.5, "future": 42}))
        patch.object(fixture.panel_app.upstream, "CONFIG_PATH", str(self.config)).start()

    down = lambda self, label, tid: fixture.PanelKeyboardTests.down(self, label, tid)
    up = lambda self, tid: fixture.PanelKeyboardTests.up(self, tid)

    def test_english_pulses_remain_on_existing_route(self):
        code = self.down("a", 1)
        self.scheduler.advance(20)
        self.up(1)
        self.assertEqual(self.bridge.events, [(0, code, True), (20, code, False)])

    def test_language_switch_saves_only_owned_field_and_releases_held_modifier(self):
        self.down("Shift", 1)
        self.up(1)
        self.down("中/EN", 2)
        self.assertEqual(self.app.languages.language, "zh_CN")
        self.assertFalse(self.bridge.held_keys)
        self.assertFalse(self.app.mods.active("shift"))
        self.assertFalse(any(code == 125 for _, code, _ in self.bridge.events))
        self.assertEqual(json.loads(self.config.read_text()),
                         {"sensitivity": 1.5, "future": 42, "keyboard_language": "zh_CN"})

    def test_chinese_key_pulses_never_emit_english_down_or_up(self):
        self.app.languages.set_language("zh_CN")
        self.app.languages.worker.deliver({"status": "ready", "preedit": "", "candidates": [], "revision": 0})
        self.down("a", 1)
        self.scheduler.advance(20)
        self.up(1)
        self.assertFalse(self.bridge.events)
        self.assertFalse(self.app._language_consumed)
        self.assertEqual(self.app.languages.worker.requests[-1]["kind"], "key")

    def test_language_strip_is_above_key_geometry_and_does_not_send_pointer_moves(self):
        self.assertGreater(self.app.kb_layout.y, self.app._language_top())
        self.app.languages.language = "zh_CN"
        self.app.languages.ready = True
        self.app.languages.preedit = "ni"
        self.app._handle_touch_down(1, 500, self.app._language_top() + 30, 1.)
        self.assertEqual(self.app._touch_owner[1], "languagebar")
        with patch.object(self.app, "_handle_touch_move") as move:
            self.app._handle_timed_touch_move(1, 500, 900, 1.1, .01)
            move.assert_not_called()
        self.app._handle_touch_up(1, 1.2)
        self.assertFalse(self.bridge.events)

    def test_failed_language_save_retains_current_language_and_configuration(self):
        with patch.object(fixture.panel_app, "write_settings", side_effect=PermissionError):
            self.down("中/EN", 2)
        self.assertEqual(self.app.languages.language, "en_US")
        self.assertNotIn("keyboard_language", json.loads(self.config.read_text()))

    def test_split_preserves_original_key_bounds_and_moves_strip_into_trackpad(self):
        self.app.mode = "split"
        self.app.update_mode_bounds()
        original = fixture.KeyboardLayout(0, 500, 1240, 580)
        self.assertEqual(self.app.kb_layout.y, original.y)
        self.assertEqual(self.app.kb_layout.height, original.height)
        self.assertEqual(self.app.kb_layout.rows[0][0].h, original.rows[0][0].h)
        self.assertEqual(self.app._language_top() + 88, self.app.kb_layout.y)

    def test_keys_mouse_header_does_not_enable_an_expanded_keyboard(self):
        self.app.mode = "split"
        self.app.update_mode_bounds()
        _, x, width = next(item for item in fixture.panel_app.upstream.HEADER_BUTTONS if item[0] == "split")
        with patch.object(self.app, "save_config", return_value=True):
            self.app._handle_header_touch(1, x + width / 2, 30, True)
            self.assertEqual(self.app.mode, "split")
            self.assertEqual(self.app.kb_layout.y, 500)
        self.assertFalse(self.bridge.held_keys)

    def test_idle_split_pad_keeps_its_full_original_surface(self):
        self.app.mode = "split"
        with patch.object(fixture.panel_app.steam_style, "draw_trackpad") as draw:
            self.app._draw_trackpad_surface(None, 124, 376)
            draw.assert_called_once_with(self.app, None, 124, 376, 1240)


if __name__ == "__main__":
    unittest.main()
