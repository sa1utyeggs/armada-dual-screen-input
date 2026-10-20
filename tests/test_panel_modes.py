import unittest

from armada_dual_screen_input.panel_modes import normalize_mode


class SavedModeCompatibilityTests(unittest.TestCase):
    def test_removed_mirror_and_legacy_pages_fall_back_to_keys_mouse(self):
        for mode in ('mirror', 'settings'):
            with self.subTest(mode=mode):
                self.assertEqual(normalize_mode(mode), 'split')

    def test_kept_modes_remain_selectable(self):
        for mode in ('split', 'keyboard', 'trackpad', 'position'):
            with self.subTest(mode=mode):
                self.assertEqual(normalize_mode(mode), mode)

    def test_invalid_saved_values_are_ignored(self):
        for mode in (None, '', 'unknown', [], {}, 3):
            with self.subTest(mode=mode):
                self.assertIsNone(normalize_mode(mode))
