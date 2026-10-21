"""Dropdown geometry keeps the native input area at its original height."""
import unittest

from armada_dual_screen_input import touchscreen_selector as selector


class TouchscreenSelectorGeometryTests(unittest.TestCase):
    def test_button_fits_existing_header_and_options_have_separate_hits(self):
        self.assertGreaterEqual(selector.BUTTON.x, 572)
        self.assertLessEqual(selector.BUTTON.x+selector.BUTTON.width, 784)
        self.assertGreaterEqual(selector.BUTTON.y, 0)
        self.assertLess(selector.BUTTON.y+selector.BUTTON.height, 80)
        self.assertEqual([(mode, label) for mode, label, _ in selector.OPTIONS],
                         [('position', '定位'), ('direct', '直接触屏')])
        previous_bottom = selector.MENU.y
        for mode, _, rect in selector.OPTIONS:
            self.assertGreater(rect.y, previous_bottom)
            self.assertEqual(selector.hit_option(rect.x+rect.width/2,
                                                 rect.y+rect.height/2), mode)
            previous_bottom = rect.y+rect.height
        self.assertLess(previous_bottom, selector.MENU.y+selector.MENU.height)

    def test_dropdown_needs_no_extra_reserved_height(self):
        for x, y in ((620, 30), (620, 152), (300, 150), (620, 660)):
            self.assertIsNone(selector.hit_option(x, y))
        self.assertEqual(selector.PAD.y, 124)
        self.assertEqual(selector.PAD.height, 956)
        self.assertEqual(selector.PAD.y+selector.PAD.height, 1080)
