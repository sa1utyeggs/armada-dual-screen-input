"""Preference validation, persistence failures and touch editing without input."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from armada_dual_screen_input.input_settings import (
    DEFAULTS, NUMBERS, SECTIONS, SettingsDraft, read_settings, write_settings,
)


class InputSettingsTests(unittest.TestCase):
    def test_missing_values_keep_existing_behavior_defaults(self):
        self.assertEqual(read_settings({}), DEFAULTS)
        self.assertEqual(DEFAULTS["sensitivity"], 1.5)
        self.assertEqual(DEFAULTS["position_sensitivity"], 2.)
        self.assertTrue(DEFAULTS["keyboard_repeat_enabled"])

    def test_invalid_and_nonfinite_numbers_never_reach_input(self):
        for key, spec in NUMBERS.items():
            for value in (None, {}, [], True, "bad", float("nan"), float("inf")):
                with self.subTest(key=key, value=value):
                    self.assertEqual(read_settings({key: value})[key], spec.default)
            self.assertEqual(read_settings({key: -999})[key],
                             spec.default if key == "scroll_scale" else spec.low)
            self.assertEqual(read_settings({key: 99999})[key], spec.high)

    def test_booleans_are_strict_and_unknown_config_is_not_an_input_option(self):
        for key in ("glide", "tap_to_click", "keyboard_repeat_enabled"):
            self.assertFalse(read_settings({key: False})[key])
            self.assertTrue(read_settings({key: "false"})[key])
        self.assertNotIn("unrelated", read_settings({"unrelated": 1}))

    def test_small_legacy_wheel_scale_survives_editing_another_preference(self):
        draft = SettingsDraft({"scroll_scale": .001})
        draft.change("sensitivity", 2.)
        self.assertEqual(read_settings(draft.values)["scroll_scale"], .001)

    def test_opening_and_editing_draft_does_not_change_saved_values(self):
        draft = SettingsDraft({"scroll_scale": .25})
        draft.change("sensitivity", 2.3)
        draft.change("keyboard_repeat_enabled", False)
        self.assertTrue(draft.dirty)
        self.assertEqual(draft.saved["sensitivity"], 1.5)
        draft.discard()
        self.assertFalse(draft.dirty)
        self.assertEqual(draft.values["scroll_scale"], .25)

    def test_restoring_defaults_only_changes_selected_section(self):
        draft = SettingsDraft({"sensitivity": 2.3, "position_sensitivity": 3.,
                               "keyboard_repeat_interval_ms": 80})
        draft.section = "mouse"
        draft.reset_section()
        self.assertEqual(draft.values["sensitivity"], 1.5)
        self.assertEqual(draft.values["position_sensitivity"], 3.)
        self.assertEqual(draft.values["keyboard_repeat_interval_ms"], 80)
        self.assertTrue(draft.dirty)

    def test_slider_clamps_to_range_and_stepper_values_do_not_accumulate_noise(self):
        draft = SettingsDraft({})
        for key, spec in NUMBERS.items():
            draft.slide(key, -1)
            self.assertEqual(draft.values[key], spec.low)
            draft.slide(key, 2000)
            self.assertLessEqual(draft.values[key], spec.high)
        for _ in range(7):
            draft.change("sensitivity", draft.values["sensitivity"] - .1)
        self.assertEqual(draft.values["sensitivity"], 4.3)

    def test_controls_have_separate_hit_regions_and_all_fit_lower_screen(self):
        draft = SettingsDraft({})
        for section in SECTIONS:
            draft.section = section
            for key, top in draft.rows():
                self.assertGreaterEqual(top, 300)
                self.assertLess(top + 88, 934)
                expected = "slider" if key in NUMBERS else "toggle"
                self.assertEqual(draft.hit(800 if key in NUMBERS else 1000, top + 50),
                                 (expected, key))
            self.assertEqual(draft.hit(1100, 1020), ("save", None))
            self.assertEqual(draft.hit(30, 120), (None, None))

    def test_save_merges_unknown_fields_and_preserves_previous_input_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thor-panel/config.json"
            write_settings(path, {"mode": "position", "future": {"keep": True}, "scroll_scale": .25})
            write_settings(path, {"sensitivity": 2.3, "keyboard_repeat_enabled": False})
            result = json.loads(path.read_text())
            self.assertEqual(result["future"], {"keep": True})
            self.assertEqual(result["mode"], "position")
            self.assertEqual(result["scroll_scale"], .25)
            self.assertEqual(result["sensitivity"], 2.3)
            self.assertFalse(result["keyboard_repeat_enabled"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_atomic_replace_keeps_old_bytes_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = b'{"keep":true}\n'
            path.write_bytes(original)
            with patch("armada_dual_screen_input.input_settings.os.replace", side_effect=OSError("full")):
                with self.assertRaises(OSError):
                    write_settings(path, {"sensitivity": 2.})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_malformed_existing_config_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for original in (b'{broken', b'[]', b'null'):
                path.write_bytes(original)
                with self.assertRaises(ValueError):
                    write_settings(path, DEFAULTS)
                self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
