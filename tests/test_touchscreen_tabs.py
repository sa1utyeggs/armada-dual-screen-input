"""Shared secondary-tab hit regions remain separate from native touch input."""
import unittest

from armada_dual_screen_input import touchscreen_tabs as tabs


class TouchscreenTabGeometryTests(unittest.TestCase):
    def test_tabs_do_not_overlap_and_match_their_labels(self):
        self.assertEqual([(mode, label) for mode, label, _ in tabs.TABS],
                         [('position', '定位'), ('direct', '直接触屏')])
        previous_right = -1
        for mode, _, rect in tabs.TABS:
            self.assertGreater(rect.x, previous_right)
            self.assertGreaterEqual(rect.y, 124)
            self.assertLess(rect.y+rect.height, tabs.CONTENT_TOP)
            self.assertEqual(tabs.hit(rect.x+rect.width/2, rect.y+rect.height/2), mode)
            previous_right = rect.x+rect.width
        self.assertLessEqual(previous_right, 1240)

    def test_tab_gaps_and_native_input_region_do_not_select_a_mode(self):
        for x, y in ((620, 160), (300, 100), (300, 220), (300, 240), (620, 660)):
            self.assertIsNone(tabs.hit(x, y))
        self.assertEqual(tabs.PAD.y, tabs.CONTENT_TOP)
        self.assertEqual(tabs.PAD.y+tabs.PAD.height, 1080)
