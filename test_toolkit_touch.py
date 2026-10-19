"""Pure touch-adapter tests: python3 -m unittest test_toolkit_touch.py."""
import math
import unittest

from toolkit_touch import ToolkitTouch


class Clock:
    value = 100.0

    def __call__(self):
        return self.value


class ToolkitTouchTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events = []
        self.activity = []
        self.touch = ToolkitTouch(
            lambda *args: self.events.append(("begin", *args)),
            lambda *args: self.events.append(("update", *args)),
            lambda *args: self.events.append(("end", *args)),
            lambda *args: self.events.append(("cancel", *args)),
            on_activity=lambda *args: self.activity.append(args),
            clock=self.clock,
        )

    def test_sequence_lifecycle_and_ids_are_never_reused(self):
        self.assertTrue(self.touch.begin("finger", 100, 200))
        self.clock.value += 0.1
        self.assertTrue(self.touch.update("finger", 200, 300))
        self.clock.value += 0.1
        self.assertTrue(self.touch.end("finger"))
        self.touch.begin("finger", 300, 400)
        self.assertEqual([event[1] for event in self.events], [1, 1, 1, 2])
        self.assertEqual(self.events[0], ("begin", 1, 100.0, 200.0, 100.0))
        self.assertEqual(self.touch.active[0].tid, 2)

    def test_contacts_keep_independent_ids_until_their_own_end(self):
        a, b = object(), object()
        self.touch.begin(a, 1, 2)
        self.touch.begin(b, 3, 4)
        self.touch.end(a)
        self.touch.update(b, 5, 6)
        self.assertEqual(self.touch.active[0].tid, 2)
        self.assertEqual(self.events[-1], ("update", 2, 5.0, 6.0, 100.0))

    def test_missing_sequences_cannot_become_mouse_feedback(self):
        self.assertFalse(self.touch.begin(None, 10, 20))
        self.assertFalse(self.touch.update(None, 10, 20))
        self.assertFalse(self.touch.end(None))
        self.assertFalse(self.touch.cancel(None))
        self.assertFalse(self.touch.update("unknown", 10, 20))
        self.assertFalse(self.touch.end("unknown"))
        self.assertFalse(self.touch.cancel("unknown"))
        self.assertEqual(self.events, [])

    def test_duplicate_begin_cancels_previous_contact(self):
        self.touch.begin("a", 10, 20)
        self.touch.begin("a", 30, 40)
        self.assertEqual(self.events[1], ("cancel", 1, 100.0))
        self.assertEqual(self.events[2], ("begin", 2, 30.0, 40.0, 100.0))
        self.assertEqual(len(self.touch.active), 1)

    def test_cancel_never_dispatches_a_normal_end_or_synthetic_tap(self):
        self.touch.begin("a", 10, 20)
        self.touch.cancel("a")
        self.assertEqual([event[0] for event in self.events], ["begin", "cancel"])
        self.assertEqual(self.touch.active, ())

    def test_viewport_coordinates_scale_and_clamp_without_raw_rotation(self):
        self.touch.set_viewport(620, 540)
        self.assertEqual(self.touch.to_logical(310, 270), (620.0, 540.0))
        self.assertEqual(self.touch.to_logical(-10, -20), (0.0, 0.0))
        self.assertEqual(self.touch.to_logical(620, 540), (1239.0, 1079.0))
        self.assertEqual(self.touch.to_logical(5000, 5000), (1239.0, 1079.0))

    def test_resize_cancels_before_coordinate_transform_changes(self):
        self.touch.begin("a", 10, 20)
        self.assertTrue(self.touch.set_viewport(620, 540))
        self.assertEqual(self.events[-1][0], "cancel")
        self.assertFalse(self.touch.update("a", 10, 20))
        self.touch.begin("b", 10, 20)
        self.assertEqual(self.events[-1], ("begin", 2, 20.0, 40.0, 100.0))
        self.assertFalse(self.touch.set_viewport(620, 540))
        self.assertEqual(len(self.touch.active), 1)

    def test_invalid_geometry_does_not_cancel_existing_gesture(self):
        self.touch.begin("a", 10, 20)
        for width, height in [(0, 10), (10, -1), (math.nan, 10), (10, math.inf)]:
            with self.assertRaises(ValueError):
                self.touch.set_viewport(width, height)
        self.assertEqual(len(self.touch.active), 1)
        self.assertEqual(self.touch.viewport_width, 1240)
        for x, y in [(math.nan, 10), (10, math.inf)]:
            with self.assertRaises(ValueError):
                self.touch.update("a", x, y)
        self.assertEqual(self.events, [("begin", 1, 10.0, 20.0, 100.0)])

    def test_keepalive_preserves_stationary_contacts_without_motion(self):
        self.touch.begin("a", 10, 20)
        self.clock.value += 10
        self.assertEqual(self.touch.keepalive(), 1)
        self.assertEqual(self.activity, [(1, 110.0)])
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.touch.active[0].updated_at, 100)
        self.touch.begin("b", 30, 40)
        self.assertEqual(self.activity[-1], (1, 110.0))

    def test_stationary_contact_refresh_precedes_second_begin(self):
        seen = {}
        expired = []
        clock = Clock()

        def down(tid, _x, _y, now):
            expired.extend(t for t, last in seen.items() if now - last > 1.5)
            seen[tid] = now

        touch = ToolkitTouch(
            down, lambda *_: None, lambda *_: None, lambda *_: None,
            on_activity=lambda tid, now: seen.__setitem__(tid, now), clock=clock,
        )
        touch.begin("stationary", 1, 2)
        clock.value += 20
        touch.begin("new", 3, 4)
        self.assertEqual(expired, [])
        self.assertEqual(seen, {1: 120.0, 2: 120.0})

    def test_release_all_and_disable_cancel_every_contact(self):
        self.touch.begin("a", 10, 20)
        self.touch.begin("b", 30, 40)
        self.touch.set_enabled(False)
        self.assertEqual([event[0] for event in self.events], ["begin", "begin", "cancel", "cancel"])
        self.assertEqual(self.touch.release_all(), 0)
        self.assertFalse(self.touch.begin("c", 10, 20))
        self.touch.set_enabled(True)
        self.touch.begin("c", 10, 20)
        self.assertEqual(self.touch.active[0].tid, 3)

    def test_release_all_finishes_other_cleanup_after_callback_failure(self):
        cancelled = []

        def cancel(tid, _now):
            cancelled.append(tid)
            if tid == 1:
                raise RuntimeError("first cleanup failed")

        touch = ToolkitTouch(lambda *_: None, lambda *_: None, lambda *_: None, cancel)
        touch.begin("a", 1, 2)
        touch.begin("b", 3, 4)
        with self.assertRaisesRegex(RuntimeError, "first cleanup failed"):
            touch.release_all()
        self.assertEqual(cancelled, [1, 2])
        self.assertEqual(touch.active, ())

    def test_timestamp_domain_is_monotonic_and_ignores_clock_regression(self):
        self.touch.begin("a", 1, 2)
        self.clock.value = 50
        self.touch.update("a", 3, 4)
        self.clock.value = 101
        self.touch.end("a")
        self.assertEqual([event[-1] for event in self.events], [100, 100, 101])


if __name__ == "__main__":
    unittest.main()
