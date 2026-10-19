"""Source-time motion checks with synthetic clocks and an in-memory mouse.

Run ``python3 -m unittest test_source_timing.py``. No GTK or input device is used.
Source milliseconds affect motion physics only; gesture lifetime stays monotonic.
"""
import math
from pathlib import Path
import sys
import unittest

from toolkit_touch import ToolkitTouch


VENDOR = Path(__file__).resolve().parent / "vendor" / "ratatoskr"
sys.path[:0] = [str(VENDOR / "bin"), str(VENDOR)]
import engine as E


class Clock:
    value = 100.0

    def __call__(self):
        return self.value


class FakeLogger:
    def log(self, *args):
        pass


class FakeBridge:
    def __init__(self):
        self.events = []

    def emit_mouse_rel(self, dx, dy):
        self.events.append(("move", dx, dy))

    def emit_scroll(self, dx, dy):
        self.events.append(("scroll", dx, dy))

    def tap_button(self, button, *args):
        self.events.append(("click", button))

    @property
    def total_x(self):
        return sum(event[1] for event in self.events if event[0] == "move")


class SourceTimingTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events = []
        self.activity = []
        self.touch = ToolkitTouch(
            lambda *args: self.events.append(("begin", *args)),
            lambda *args: self.events.append(("legacy_update", *args)),
            lambda *args: self.events.append(("end", *args)),
            lambda *args: self.events.append(("cancel", *args)),
            on_activity=lambda *args: self.activity.append(args),
            on_timed_update=lambda *args: self.events.append(("update", *args)),
            clock=self.clock,
        )

    def last_interval(self):
        return [event for event in self.events if event[0] == "update"][-1][-1]

    def test_unsigned_32bit_wrap_keeps_correct_interval(self):
        self.touch.begin("a", 300, 300, source_ms=0xFFFFFFF0)
        self.clock.value = 100.30
        self.touch.update("a", 301, 300, source_ms=4)
        self.assertAlmostEqual(self.last_interval(), 0.020)
        self.assertEqual(self.touch.active[0].updated_at, 100.30)
        self.assertEqual(self.events[-1][-2], 100.30)

    def test_duplicate_source_time_reuses_only_previous_valid_interval(self):
        self.touch.begin("a", 300, 300, source_ms=1000)
        self.touch.update("a", 301, 300, source_ms=1000)
        self.assertEqual(self.last_interval(), 0.0)
        self.touch.update("a", 302, 300, source_ms=1020)
        self.assertAlmostEqual(self.last_interval(), 0.020)
        for position in (303, 304, 305):
            self.clock.value += 0.0001
            self.touch.update("a", position, 300, source_ms=1020)
            self.assertAlmostEqual(self.last_interval(), 0.020)

    def test_backwards_source_time_rebaselines_without_high_velocity(self):
        self.touch.begin("a", 300, 300, source_ms=1000)
        self.touch.update("a", 310, 300, source_ms=1020)
        self.touch.update("a", 320, 300, source_ms=1010)
        self.assertEqual(self.last_interval(), 0.0)
        self.touch.update("a", 321, 300, source_ms=1010)
        self.assertEqual(self.last_interval(), 0.0)
        self.touch.update("a", 322, 300, source_ms=1030)
        self.assertAlmostEqual(self.last_interval(), 0.020)

    def test_cancel_forgets_interval_and_reused_sequence_starts_fresh(self):
        self.touch.begin("a", 300, 300, source_ms=1000)
        self.touch.update("a", 310, 300, source_ms=1020)
        old_tid = self.touch.active[0].tid
        self.touch.cancel("a")
        self.assertEqual(self.touch.active, ())
        self.assertFalse(self.touch.update("a", 320, 300, source_ms=1040))
        self.touch.begin("a", 300, 300, source_ms=2000)
        self.assertGreater(self.touch.active[0].tid, old_tid)
        self.touch.update("a", 301, 300, source_ms=2000)
        self.assertEqual(self.last_interval(), 0.0)

    def test_resize_forgets_source_state_before_new_scaled_contact(self):
        self.touch.begin("a", 300, 300, source_ms=1000)
        self.touch.update("a", 310, 300, source_ms=1020)
        self.assertTrue(self.touch.set_viewport(620, 540))
        self.assertEqual(self.touch.active, ())
        self.assertFalse(self.touch.update("a", 320, 300, source_ms=1040))
        self.touch.begin("a", 150, 150, source_ms=3000)
        self.touch.update("a", 151, 150, source_ms=3000)
        self.assertEqual(self.last_interval(), 0.0)

    def test_different_sequences_keep_independent_source_baselines(self):
        self.touch.begin("a", 300, 300, source_ms=1000)
        self.touch.update("a", 301, 300, source_ms=1020)
        self.touch.begin("b", 500, 300, source_ms=2000)
        self.touch.update("b", 501, 300, source_ms=2050)
        self.assertAlmostEqual(self.last_interval(), 0.050)
        self.touch.update("a", 302, 300, source_ms=1040)
        self.assertAlmostEqual(self.last_interval(), 0.020)
        self.touch.end("b")
        self.touch.begin("c", 600, 300, source_ms=3000)
        self.touch.update("c", 601, 300, source_ms=3000)
        self.assertEqual(self.last_interval(), 0.0)

    def test_missing_source_uses_legacy_motion_interval_fallback(self):
        self.touch.begin("a", 300, 300)
        self.clock.value = 100.06
        self.touch.update("a", 318, 300)
        self.assertIsNone(self.last_interval())
        self.touch.update("a", 320, 300, source_ms=1000)
        self.assertEqual(self.last_interval(), 0.0)
        self.touch.update("a", 322, 300, source_ms=1020)
        self.assertAlmostEqual(self.last_interval(), 0.020)
        self.touch.update("a", 324, 300)
        self.assertIsNone(self.last_interval())

        clock, gesture, bridge, touch = integrated_touch()
        touch.begin("a", 300, 300)
        clock.value = 100.06
        touch.update("a", 318, 300)
        self.assertGreater(bridge.total_x, 0)
        self.assertAlmostEqual(gesture.vel_x, 110.0, places=6)

    def test_no_timed_callback_retains_original_update_contract(self):
        events = []
        touch = ToolkitTouch(lambda *args: None,
                             lambda *args: events.append(args),
                             lambda *args: None, lambda *args: None,
                             clock=self.clock)
        touch.begin("a", 300, 300, source_ms=1000)
        self.clock.value = 100.02
        touch.update("a", 302, 300, source_ms=1020)
        self.assertEqual(events, [(1, 302.0, 300.0, 100.02)])

    def test_source_discontinuity_never_changes_tap_or_liveness_clock(self):
        clock, gesture, bridge, touch = integrated_touch()
        touch.begin("a", 300, 300, source_ms=0xFFFFFF00)
        clock.value = 100.10
        touch.update("a", 301, 300, source_ms=900000)
        self.assertEqual(gesture.start_time, 100.0)
        self.assertEqual(gesture.active_contacts[1]["seen_t"], 100.10)
        clock.value = 100.15
        touch.end("a")
        self.assertEqual(bridge.events, [("click", E.BTN_LEFT)])

    def test_half_second_source_pause_does_not_look_like_dispatch_burst(self):
        clock, gesture, bridge, touch = integrated_touch()
        touch.begin("a", 300, 300, source_ms=1000)
        clock.value = 100.02
        touch.update("a", 330, 300, source_ms=1020)
        before = bridge.total_x
        # Source motion resumes after 500 ms, while callbacks are delivered
        # only 100 us apart. Velocity must use source time, not that burst.
        clock.value = 100.0201
        touch.update("a", 360, 300, source_ms=1520)
        self.assertLessEqual(bridge.total_x - before, 31)
        self.assertLess(gesture.vel_x, 100)

    def test_source_pause_over_500ms_suppresses_gain_and_glide_velocity(self):
        clock, gesture, bridge, touch = integrated_touch()
        touch.begin("a", 300, 300, source_ms=1000)
        clock.value = 100.02
        touch.update("a", 330, 300, source_ms=1020)
        before = bridge.total_x
        clock.value = 100.0201
        touch.update("a", 360, 300, source_ms=1620)
        self.assertEqual(bridge.total_x - before, 30)
        self.assertEqual((gesture.vel_x, gesture.vel_y), (0.0, 0.0))
        self.assertEqual(gesture.vel_time, clock.value)

    def test_regular_and_four_event_bursts_keep_motion_and_velocity_equal(self):
        outputs = []
        for batched in (False, True):
            clock, gesture, bridge, touch = integrated_touch()
            touch.begin("a", 300, 300, source_ms=1000)
            for step in range(1, 121):
                clock.value = (100.0 + math.ceil(step / 4) / 30
                               + ((step - 1) % 4) * 0.0001
                               if batched else 100.0 + step / 120)
                touch.update("a", 300 + 2.5 * step, 300,
                             source_ms=1000 + round(step * 1000 / 120))
            outputs.append((bridge.total_x, gesture.vel_x, gesture.vel_y))
        self.assertLessEqual(abs(outputs[0][0] - outputs[1][0]), 2, outputs)
        self.assertAlmostEqual(outputs[0][1], outputs[1][1], places=6)
        self.assertEqual((outputs[0][2], outputs[1][2]), (0.0, 0.0))


def integrated_touch():
    clock = Clock()
    bridge = FakeBridge()
    gesture = E.TouchGestureProcessor(bridge, FakeLogger())
    gesture.set_settings(glide=False, sensitivity=1.0)

    def activity(tid, now):
        contact = gesture.active_contacts.get(tid)
        if contact is not None:
            contact["seen_t"] = now

    touch = ToolkitTouch(
        gesture.touch_down, gesture.touch_move, gesture.touch_up,
        lambda *args: gesture.reset_all(), clock=clock,
        on_activity=activity,
        on_timed_update=lambda tid, x, y, now, interval:
            gesture.touch_move(tid, x, y, now, motion_interval=interval),
    )
    return clock, gesture, bridge, touch


if __name__ == "__main__":
    unittest.main()
