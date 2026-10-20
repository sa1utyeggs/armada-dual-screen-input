"""Pure touch-adapter tests: python3 -m unittest test_toolkit_touch.py."""
import math
from pathlib import Path
import sys
import unittest

from armada_dual_screen_input.toolkit_touch import ToolkitTouch

# The gesture engine imports without opening devices; only a fake bridge is
# constructed below. Include its package directory for debug_codes.
VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "ratatoskr"
sys.path[:0] = [str(VENDOR / "bin"), str(VENDOR)]
from engine import TouchGestureProcessor


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

    def test_new_group_cancels_every_old_contact_before_registering_touch(self):
        self.touch.begin("old-a", 10, 20)
        self.touch.begin("old-b", 30, 40)
        self.clock.value += 1
        self.touch.begin("new", 50, 60, starts_new_group=True)
        self.assertEqual(self.events[2:], [
            ("cancel", 1, 101.0), ("cancel", 2, 101.0),
            ("begin", 3, 50.0, 60.0, 101.0),
        ])
        self.assertEqual([contact.tid for contact in self.touch.active], [3])
        self.assertFalse(self.touch.end("old-a"))
        self.assertFalse(self.touch.update("old-b", 40, 50))

    def test_new_group_reused_sequence_is_cancelled_once_and_gets_fresh_id(self):
        self.touch.begin("reused", 10, 20)
        self.touch.begin("other", 30, 40)
        self.touch.begin("reused", 50, 60, starts_new_group=True)
        self.assertEqual([event[:2] for event in self.events], [
            ("begin", 1), ("begin", 2), ("cancel", 1), ("cancel", 2),
            ("begin", 3),
        ])
        self.assertEqual(len(self.touch.active), 1)
        self.assertTrue(self.touch.end("reused"))
        self.assertEqual(self.events[-1], ("end", 3, 100.0))

    def test_first_group_with_no_old_contacts_does_not_cancel(self):
        self.touch.begin("first", 10, 20, starts_new_group=True)
        self.assertEqual(self.events, [("begin", 1, 10.0, 20.0, 100.0)])

    def test_explicit_adapter_recovery_cancels_without_claiming_a_new_group(self):
        self.touch.begin("old", 10, 20)
        self.clock.value += 5
        self.touch.begin("new", 30, 40, cancel_previous=True)
        self.assertEqual([event[:2] for event in self.events], [
            ("begin", 1), ("cancel", 1), ("begin", 2),
        ])
        self.assertFalse(self.touch.update("old", 40, 50))
        self.assertEqual([c.tid for c in self.touch.active], [2])

    def test_ordinary_second_finger_preserves_long_stationary_or_keyboard_touch(self):
        for first in ("stationary-trackpad", "held-key"):
            with self.subTest(first=first):
                self.setUp()
                self.touch.begin(first, 10, 20, starts_new_group=True)
                self.clock.value += 120
                self.touch.keepalive()
                self.touch.begin("second", 30, 40, starts_new_group=False)
                self.assertEqual([event[0] for event in self.events], ["begin", "begin"])
                self.assertEqual([contact.tid for contact in self.touch.active], [1, 2])
                self.assertEqual(self.touch.active[0].updated_at, 100.0)

    def test_invalid_new_group_begin_does_not_clear_existing_contacts(self):
        self.touch.begin("held", 10, 20)
        self.assertFalse(self.touch.begin(None, 10, 20, starts_new_group=True))
        for x, y in ((math.nan, 20), (10, math.inf), ("bad", 20)):
            with self.assertRaises((ValueError, TypeError)):
                self.touch.begin("invalid", x, y, starts_new_group=True)
        self.assertEqual(self.events, [("begin", 1, 10.0, 20.0, 100.0)])
        self.assertEqual([contact.tid for contact in self.touch.active], [1])
        self.clock.value = math.nan
        with self.assertRaises(ValueError):
            self.touch.begin("invalid-clock", 30, 40, starts_new_group=True)
        self.assertEqual([contact.tid for contact in self.touch.active], [1])

    def test_disabled_new_group_begin_does_not_emit_another_cancel_or_begin(self):
        self.touch.begin("held", 10, 20)
        self.touch.set_enabled(False)
        before = list(self.events)
        self.assertFalse(self.touch.begin("new", 30, 40, starts_new_group=True))
        self.assertEqual(self.events, before)
        self.assertEqual(self.touch.active, ())

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

    def test_real_event_quiet_time_ignores_keepalive_and_preserves_long_hold(self):
        self.assertEqual(self.touch.quiet_for(), math.inf)
        self.touch.begin("held-key", 10, 20)
        self.assertEqual(self.touch.quiet_for(), 0.0)
        for _ in range(120):
            self.clock.value += 1
            self.touch.keepalive()
        self.assertEqual(self.touch.quiet_for(), 120.0)
        self.assertEqual(len(self.touch.active), 1)
        self.assertEqual(self.touch.active[0].updated_at, 100.0)
        self.assertEqual([event[0] for event in self.events], ["begin"])

    def test_update_and_second_finger_end_reset_whole_group_quiet_time(self):
        self.touch.begin("stationary-anchor", 10, 20)
        self.clock.value += 10
        self.touch.begin("scroll-finger", 30, 40)
        self.clock.value += .5
        self.assertEqual(self.touch.quiet_for(), .5)
        self.touch.update("scroll-finger", 30, 50)
        self.assertEqual(self.touch.quiet_for(), 0.0)
        self.clock.value += .5
        self.touch.end("scroll-finger")
        self.assertEqual(self.touch.quiet_for(), 0.0)
        # The anchor has not moved for 11 seconds, but the group just received
        # a real END. It must not look quiet while a second finger is re-landed.
        self.assertEqual(self.touch.active[0].updated_at, 100.0)
        self.clock.value += .25
        self.assertEqual(self.touch.quiet_for(), .25)
        self.touch.begin("scroll-finger-again", 30, 40)
        self.assertEqual(self.touch.quiet_for(), 0.0)
        self.assertTrue(self.touch.owns_sequence("stationary-anchor"))

    def test_cancel_and_nonempty_release_reset_quiet_but_empty_release_does_not(self):
        self.touch.begin("a", 10, 20)
        self.touch.begin("b", 30, 40)
        self.clock.value += 5
        self.touch.cancel("a")
        self.assertEqual(self.touch.quiet_for(), 0.0)
        self.clock.value += 5
        self.touch.release_all()
        self.assertEqual(self.touch.quiet_for(), 0.0)
        self.clock.value += 5
        self.assertEqual(self.touch.release_all(), 0)
        self.assertEqual(self.touch.quiet_for(), 5.0)

    def test_invalid_and_unknown_events_do_not_reset_real_event_quiet_time(self):
        self.touch.begin("held", 10, 20)
        self.clock.value += 5
        self.assertFalse(self.touch.begin(None, 10, 20))
        self.assertFalse(self.touch.update("unknown", 10, 20))
        self.assertFalse(self.touch.end("unknown"))
        self.assertFalse(self.touch.cancel("unknown"))
        self.assertFalse(self.touch.end(None))
        self.assertFalse(self.touch.cancel(None))
        with self.assertRaises(ValueError):
            self.touch.begin("bad", math.nan, 20, starts_new_group=True)
        with self.assertRaises(ValueError):
            self.touch.update("held", 10, math.inf)
        self.assertEqual(self.touch.quiet_for(), 5.0)
        self.assertTrue(self.touch.owns_sequence("held"))

        self.touch.set_enabled(False)
        self.clock.value += 5
        self.assertFalse(self.touch.begin("disabled", 10, 20))
        self.assertEqual(self.touch.quiet_for(), 5.0)

    def test_sequence_ownership_is_read_only_and_tracks_lifecycle(self):
        self.assertFalse(self.touch.owns_sequence(None))
        self.assertFalse(self.touch.owns_sequence("a"))
        self.touch.begin("a", 10, 20)
        self.assertTrue(self.touch.owns_sequence("a"))
        self.clock.value += 5
        self.assertFalse(self.touch.owns_sequence("new"))
        self.assertEqual(self.touch.quiet_for(), 5.0)
        self.touch.begin("a", 30, 40)
        self.assertTrue(self.touch.owns_sequence("a"))
        self.assertEqual(self.touch.quiet_for(), 0.0)
        self.touch.end("a")
        self.assertFalse(self.touch.owns_sequence("a"))
        self.touch.begin("b", 10, 20)
        self.touch.cancel("b")
        self.assertFalse(self.touch.owns_sequence("b"))
        self.touch.begin("c", 10, 20)
        self.touch.release_all()
        self.assertFalse(self.touch.owns_sequence("c"))

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


class NewGroupGestureRecoveryTests(unittest.TestCase):
    """Lost-END regressions against the real gesture math, with fake output."""

    def setUp(self):
        self.clock = Clock()
        self.events = []

        class Bridge:
            def emit_mouse_rel(_self, dx, dy):
                self.events.append(("move", dx, dy))

            def emit_scroll(_self, dx, dy):
                self.events.append(("scroll", dx, dy))

            def tap_button(_self, button):
                self.events.append(("click", button))

        class Logger:
            def log(_self, *args):
                pass

        self.gesture = TouchGestureProcessor(Bridge(), Logger())
        self.gesture.set_settings(glide=False)

        def activity(tid, now):
            contact = self.gesture.active_contacts.get(tid)
            if contact is not None:
                contact["seen_t"] = now

        self.touch = ToolkitTouch(
            self.gesture.touch_down, self.gesture.touch_move,
            self.gesture.touch_up, lambda *_: self.gesture.reset_all(),
            on_activity=activity, clock=self.clock,
        )

    def test_lost_scroll_end_recovers_on_authoritative_new_group(self):
        self.touch.begin("a", 300, 300, starts_new_group=True)
        self.touch.begin("lost-end", 400, 300)
        self.clock.value += .02
        self.touch.update("a", 300, 340)
        self.touch.update("lost-end", 400, 340)
        self.touch.end("a")
        for _ in range(120):
            self.clock.value += .25
            self.touch.keepalive()
            self.gesture.expire_stale(self.clock.value)
        self.assertEqual(len(self.gesture.active_contacts), 1)

        # Without a new-group indication, the old behavior remains: a second
        # contact must still scroll instead of interrupting a held finger.
        self.events.clear()
        self.touch.begin("ordinary", 300, 300)
        self.clock.value += .02
        self.touch.update("ordinary", 360, 340)
        self.assertEqual([event[0] for event in self.events], ["scroll"])
        self.touch.end("ordinary")

        self.events.clear()
        self.touch.begin("fresh", 300, 300, starts_new_group=True)
        self.assertEqual(self.events, [])  # cancellation is not a synthetic tap
        self.assertEqual(len(self.touch.active), 1)
        self.assertEqual(len(self.gesture.active_contacts), 1)
        self.clock.value += .02
        self.touch.update("fresh", 360, 340)
        self.assertTrue(any(event[0] == "move" for event in self.events))
        self.assertFalse(any(event[0] in ("click", "scroll") for event in self.events))

    def test_accumulated_ghosts_and_misuse_lock_are_cleared_for_fresh_group(self):
        for index in range(4):
            self.touch.begin(f"ghost-{index}", 300 + index * 30, 300)
        self.assertTrue(self.gesture.misuse_lock)
        self.touch.update("ghost-0", 400, 300)
        self.assertEqual(self.events, [])

        self.touch.begin("fresh", 300, 300, starts_new_group=True)
        self.assertFalse(self.gesture.misuse_lock)
        self.assertEqual(self.gesture.max_fingers, 1)
        self.assertEqual(len(self.gesture.active_contacts), 1)
        self.assertEqual(self.events, [])
        self.clock.value += .02
        self.touch.update("fresh", 360, 300)
        self.assertEqual([event[0] for event in self.events], ["move"])

    def test_reused_ghost_sequence_starts_a_clean_one_finger_gesture(self):
        self.touch.begin("reused", 300, 300)
        self.touch.begin("other-ghost", 400, 300)
        old_ids = {contact.tid for contact in self.touch.active}
        self.touch.begin("reused", 500, 300, starts_new_group=True)
        self.assertFalse(old_ids & set(self.gesture.active_contacts))
        self.clock.value += .02
        self.touch.update("reused", 560, 300)
        self.assertEqual([event[0] for event in self.events], ["move"])


if __name__ == "__main__":
    unittest.main()
