"""Pointer regression checks without GTK, evdev, uinput, or device access.

Run with ``python3 -m unittest test_pointer_gestures.py`` from this directory.
All timestamps and touch positions are synthetic; all output stays in memory.
"""
from pathlib import Path
import sys
import unittest


VENDOR = Path(__file__).resolve().parent / "vendor" / "ratatoskr"
sys.path[:0] = [str(VENDOR / "bin"), str(VENDOR)]
import engine as E


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

    def tap_key(self, key, *args):
        self.events.append(("tap_key", key))

    def key(self, key, down):
        self.events.append(("key", key, down))

    def mouse_button(self, button, down):
        self.events.append(("button", button, down))

    @property
    def moves(self):
        return [event for event in self.events if event[0] == "move"]

    @property
    def clicks(self):
        return [event for event in self.events if event[0] == "click"]

    @property
    def total_motion(self):
        return (sum(event[1] for event in self.moves),
                sum(event[2] for event in self.moves))


def fresh():
    bridge = FakeBridge()
    gesture = E.TouchGestureProcessor(bridge, FakeLogger())
    gesture.set_settings(glide=False, sensitivity=1.0)
    return gesture, bridge


class PointerGestureTests(unittest.TestCase):
    def test_repeated_one_pixel_jitter_during_150ms_tap_only_clicks(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        for step in range(1, 15):
            # Repeated sensor noise has a long cumulative path but stays
            # within a single logical pixel of the landing point.
            gesture.touch_move(1, 300 + (1 if step % 2 else -1),
                               300, 100.0 + step * 0.01)
        gesture.touch_up(1, 100.15)
        self.assertEqual(bridge.clicks, [("click", E.BTN_LEFT)])
        self.assertEqual(bridge.moves, [])

    def test_slightly_slower_320ms_tap_still_clicks(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        for step in range(1, 16):
            gesture.touch_move(1, 300 + (1 if step % 2 else -1),
                               300, 100.0 + step * 0.02)
        gesture.touch_up(1, 100.32)
        self.assertEqual(bridge.clicks, [("click", E.BTN_LEFT)])
        self.assertEqual(bridge.moves, [])

    def test_crossing_movement_threshold_then_returning_never_clicks(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_move(1, 330, 300, 100.08)
        gesture.touch_move(1, 300, 300, 100.16)
        gesture.touch_up(1, 100.20)
        self.assertTrue(bridge.moves)
        self.assertEqual(bridge.clicks, [])

    def test_next_tap_does_not_inherit_previous_fractional_motion(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_move(1, 313.25, 300.5, 100.05)
        gesture.touch_up(1, 100.10)
        self.assertTrue(bridge.moves)
        bridge.events.clear()

        gesture.touch_down(2, 500, 500, 101.0)
        # The fractional remainder belongs to the old drag. It must not
        # affect a fresh contact, even before that contact is classified.
        self.assertEqual((gesture.rest_x, gesture.rest_y), (0.0, 0.0))
        gesture.touch_move(2, 500.25, 499.75, 101.04)
        gesture.touch_up(2, 101.12)
        self.assertEqual(bridge.clicks, [("click", E.BTN_LEFT)])
        self.assertEqual(bridge.moves, [])

    def test_stationary_500ms_hold_with_jitter_neither_moves_nor_clicks(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        for step in range(1, 25):
            gesture.touch_move(1, 300 + (1 if step % 2 else -1),
                               300, 100.0 + step * 0.02)
        gesture.touch_up(1, 100.50)
        self.assertEqual(bridge.events, [])

    def test_300px_per_second_motion_is_sampling_rate_independent(self):
        totals = {}
        for rate in (30, 60, 120):
            with self.subTest(rate=rate):
                gesture, bridge = fresh()
                gesture.touch_down(1, 300, 300, 100.0)
                for step in range(1, rate + 1):
                    gesture.touch_move(1, 300 + 300.0 * step / rate,
                                       300, 100.0 + step / rate)
                gesture.touch_up(1, 101.01)
                totals[rate] = bridge.total_motion[0]
                self.assertGreater(totals[rate], 250)
                self.assertEqual(bridge.total_motion[1], 0)
                self.assertEqual(bridge.clicks, [])
        self.assertLessEqual(max(totals.values()) - min(totals.values()), 2,
                             f"Identical motion depends on event rate: {totals}")

    def test_threshold_is_12px_and_only_excess_motion_is_emitted(self):
        gesture, bridge = fresh()
        self.assertEqual(E.TAP_MAX_DISTANCE_PX, 12.0)
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_move(1, 312, 300, 100.04)
        self.assertEqual(bridge.moves, [])
        gesture.touch_move(1, 318, 300, 100.06)
        self.assertGreaterEqual(bridge.total_motion[0], 6)
        self.assertLessEqual(bridge.total_motion[0], 8)
        gesture.touch_up(1, 100.10)
        self.assertEqual(bridge.clicks, [])

    def test_coalesced_first_move_replays_only_excess_past_threshold(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_move(1, 318, 300, 100.06)
        self.assertGreaterEqual(bridge.total_motion[0], 6)
        self.assertLessEqual(bridge.total_motion[0], 8)
        self.assertEqual(bridge.total_motion[1], 0)
        gesture.touch_up(1, 100.10)
        self.assertEqual(bridge.clicks, [])


if __name__ == "__main__":
    unittest.main()
