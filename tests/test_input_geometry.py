import math
import unittest

from armada_dual_screen_input.input_geometry import Rect


class OperationAreaTests(unittest.TestCase):
    def test_bounds_include_edges_but_not_header_or_outside(self):
        pad = Rect(0, 124, 1240, 956)
        self.assertTrue(pad.contains(0, 124))
        self.assertTrue(pad.contains(1240, 1080))
        self.assertFalse(pad.contains(0, 123))
        self.assertFalse(pad.contains(1241, 124))

    def test_invalid_or_nonfinite_geometry_is_rejected(self):
        for values in ((0, 0, 0, 1), (0, 0, 1, -1), (math.nan, 0, 1, 1), (0, 0, math.inf, 1)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Rect(*values)
        with self.assertRaises(ValueError):
            Rect(0, 0, 1, 1).contains(math.nan, 0)
