import math
import unittest

from mirror_geometry import MirrorTransform, Rect


class MirrorGeometryTests(unittest.TestCase):
    def test_fit_keeps_aspect_ratio_and_centers_with_toolbar_offset(self):
        transform = MirrorTransform.fit(1920, 1080, Rect(0, 80, 1240, 1000))
        self.assertAlmostEqual(transform.image.width, 1240)
        self.assertAlmostEqual(transform.image.height, 697.5)
        self.assertEqual(transform.to_source(620, 580), (0.5, 0.5))

    def test_rotated_round_trip_includes_all_corners_and_off_center_points(self):
        for rotation in (0, 90, 180, 270):
            transform = MirrorTransform.fit(2560, 1600, Rect(11, 70, 900, 800), rotation)
            for u, v in ((0, 0), (1, 0), (0, 1), (1, 1), (0.2, 0.7)):
                with self.subTest(rotation=rotation, point=(u, v)):
                    mapped = transform.to_source(*transform.to_view(u, v), clamp=True)
                    self.assertAlmostEqual(mapped[0], u)
                    self.assertAlmostEqual(mapped[1], v)

    def test_clockwise_rotation_has_the_expected_orientation(self):
        transform = MirrorTransform.fit(1920, 1080, Rect(0, 0, 1080, 1920), 90)
        self.assertEqual(transform.to_source(0, 0), (0, 1))
        self.assertEqual(transform.to_source(1080, 0), (0, 0))

    def test_initial_margin_touch_is_rejected_but_drag_can_clamp_at_edge(self):
        transform = MirrorTransform.fit(1920, 1080, Rect(0, 0, 1000, 1000))
        self.assertIsNone(transform.to_source(500, 0))
        self.assertEqual(transform.to_source(-50, -50, clamp=True), (0, 0))
        self.assertEqual(transform.to_source(2000, 2000, clamp=True), (1, 1))

    def test_source_pixel_edges_never_exceed_the_last_pixel(self):
        transform = MirrorTransform.fit(1920, 1080, Rect(0, 0, 1000, 1000))
        self.assertEqual(transform.to_pixel(0, 0), (0, 0))
        self.assertEqual(transform.to_pixel(1, 1), (1919, 1079))

    def test_invalid_geometry_is_rejected_before_mapping(self):
        for width, height in ((0, 1), (1, -1), (True, 1), (1.5, 2)):
            with self.assertRaises(ValueError):
                MirrorTransform.fit(width, height, Rect(0, 0, 100, 100))
        for rotation in (45, 360, True):
            with self.assertRaises(ValueError):
                MirrorTransform.fit(100, 100, Rect(0, 0, 100, 100), rotation)
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                Rect(value, 0, 100, 100)
        with self.assertRaises(ValueError):
            Rect(0, 0, 0, 100)


if __name__ == '__main__':
    unittest.main()
