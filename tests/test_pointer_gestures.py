"""Pointer regression checks without GTK, evdev, uinput, or device access.

Run with ``python3 -m unittest test_pointer_gestures.py`` from this directory.
All timestamps and touch positions are synthetic; all output stays in memory.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "ratatoskr"
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

    def test_scroll_to_one_finger_tiny_motion_does_not_replay_scroll(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_down(2, 500, 300, 100.01)
        gesture.touch_move(1, 300, 400, 100.10)
        gesture.touch_move(2, 500, 400, 100.11)
        self.assertTrue(any(event[0] == "scroll" for event in bridge.events))
        gesture.touch_up(2, 100.12)
        bridge.events.clear()

        gesture.touch_move(1, 300, 401, 100.13)
        gesture.touch_up(1, 100.14)
        self.assertEqual(bridge.events, [])

    def test_pointer_move_then_second_finger_never_becomes_a_right_tap(self):
        for first_lift in (1, 2):
            with self.subTest(first_lift=first_lift):
                gesture, bridge = fresh()
                gesture.touch_down(1, 300, 300, 100.0)
                gesture.touch_move(1, 318, 300, 100.05)
                self.assertTrue(gesture.pointer_active)
                gesture.touch_down(2, 500, 300, 100.06)
                gesture.touch_up(first_lift, 100.10)
                self.assertTrue(gesture.pointer_active)
                remaining = 3 - first_lift
                x = 318 if remaining == 1 else 500
                bridge.events.clear()
                gesture.touch_move(remaining, x + 30, 300, 100.12)
                self.assertEqual(bridge.moves, [])
                gesture.touch_up(remaining, 100.15)
                self.assertEqual(bridge.clicks, [])

    def test_scroll_to_one_finger_waits_for_all_lifts_without_click_or_glide(self):
        gesture, bridge = fresh()
        gesture.set_settings(glide=True)
        glides = []
        gesture._start_glide = lambda vx, vy: glides.append((vx, vy))
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_down(2, 500, 300, 100.01)
        gesture.touch_move(1, 300, 400, 100.10)
        gesture.touch_move(2, 500, 400, 100.11)
        # Fractional output and velocity may also belong to the earlier
        # single-finger leg; neither should survive this transition.
        gesture.rest_x, gesture.rest_y = 0.75, -0.75
        gesture.vel_x, gesture.vel_y = 2000, -2000
        gesture.touch_up(2, 100.12)
        self.assertEqual((gesture.rest_x, gesture.rest_y), (0.0, 0.0))
        self.assertEqual((gesture.vel_x, gesture.vel_y), (0.0, 0.0))
        self.assertEqual(gesture.max_fingers, 2)
        bridge.events.clear()

        gesture.touch_move(1, 300, 418, 100.16)
        self.assertEqual(bridge.events, [])
        gesture.touch_move(1, 300, 448, 100.18)
        self.assertEqual(bridge.events, [])
        self.assertEqual((gesture.vel_x, gesture.vel_y), (0.0, 0.0))
        self.assertEqual((gesture.rest_x, gesture.rest_y), (0.0, 0.0))
        gesture.touch_up(1, 100.19)
        self.assertEqual(bridge.clicks, [])
        self.assertEqual(glides, [])

    def test_repeated_scroll_with_staggered_lifts_never_drifts_pointer(self):
        gesture, bridge = fresh()
        gesture.set_settings(glide=True, sensitivity=1.5, scroll_speed=1)
        glides = []
        gesture._start_glide = lambda vx, vy: glides.append((vx, vy))
        for cycle in range(40):
            with self.subTest(cycle=cycle):
                first, second = cycle * 2 + 1, cycle * 2 + 2
                now = 100.0 + cycle * 0.5
                gesture.touch_down(first, 300, 400, now)
                gesture.touch_down(second, 500, 400, now + 0.01)
                gesture.touch_move(first, 300, 350, now + 0.08)
                gesture.touch_move(second, 500, 350, now + 0.09)
                lifted, remaining = ((first, second) if cycle % 2
                                     else (second, first))
                gesture.touch_up(lifted, now + 0.10)
                x = 300 if remaining == first else 500
                gesture.touch_move(remaining, x, 330, now + 0.14)
                gesture.touch_up(remaining, now + 0.16)
                self.assertEqual(bridge.moves, [])
                self.assertEqual(bridge.clicks, [])
                self.assertFalse(gesture.active_contacts)
        self.assertEqual(sum(event[0] == "scroll" for event in bridge.events), 80)
        self.assertEqual(glides, [])

    def test_trailing_finger_movement_rejects_false_two_finger_tap(self):
        for dx, dy in ((0, -40), (0, 40), (-40, 0), (40, 0)):
            for first_lift in (1, 2):
                with self.subTest(dx=dx, dy=dy, first_lift=first_lift):
                    gesture, bridge = fresh()
                    gesture.touch_down(1, 300, 300, 100.0)
                    gesture.touch_down(2, 500, 300, 100.01)
                    gesture.touch_up(first_lift, 100.05)
                    remaining = 3 - first_lift
                    x = 300 if remaining == 1 else 500
                    gesture.touch_move(remaining, x + dx, 300 + dy, 100.10)
                    gesture.touch_up(remaining, 100.15)
                    self.assertEqual(bridge.events, [])

    def test_second_finger_rejoining_continues_scroll_without_pointer_motion(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_down(2, 500, 300, 100.01)
        gesture.touch_move(1, 300, 350, 100.05)
        gesture.touch_up(2, 100.08)
        gesture.touch_move(1, 300, 400, 100.10)
        gesture.touch_down(3, 500, 400, 100.12)
        gesture.touch_move(3, 500, 450, 100.15)
        gesture.touch_up(1, 100.18)
        gesture.touch_move(3, 500, 490, 100.20)
        gesture.touch_up(3, 100.22)
        self.assertEqual(sum(event[0] == "scroll" for event in bridge.events), 2)
        self.assertEqual(bridge.moves, [])
        self.assertEqual(bridge.clicks, [])

    def test_fresh_pointer_moves_after_all_scroll_contacts_lift(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_down(2, 500, 300, 100.01)
        gesture.touch_move(1, 300, 350, 100.05)
        gesture.touch_up(1, 100.08)
        gesture.touch_move(2, 500, 400, 100.10)
        gesture.touch_up(2, 100.12)
        bridge.events.clear()
        gesture.touch_down(3, 300, 300, 100.15)
        gesture.touch_move(3, 350, 300, 100.20)
        self.assertTrue(bridge.moves)
        self.assertGreater(bridge.total_motion[0], 0)
        self.assertEqual(bridge.total_motion[1], 0)
        gesture.touch_up(3, 100.22)
        self.assertEqual(bridge.clicks, [])

    def test_fresh_finger_after_scroll_and_all_lifts_is_normal_tap(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_down(2, 500, 300, 100.01)
        gesture.touch_move(1, 300, 400, 100.10)
        gesture.touch_move(2, 500, 400, 100.11)
        gesture.touch_up(2, 100.12)
        gesture.touch_up(1, 100.13)
        self.assertEqual(bridge.clicks, [])
        self.assertEqual(gesture.active_contacts, {})
        bridge.events.clear()

        gesture.touch_down(3, 600, 600, 100.20)
        gesture.touch_up(3, 100.30)
        self.assertEqual(bridge.events, [("click", E.BTN_LEFT)])

    def test_two_finger_tap_still_right_clicks_after_first_lift(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.touch_down(2, 500, 300, 100.02)
        gesture.touch_up(2, 100.08)
        gesture.touch_up(1, 100.10)
        self.assertEqual(bridge.events, [("click", E.BTN_RIGHT)])

    def test_recovery_group_suppresses_taps_including_later_added_fingers(self):
        for fingers in (1, 2, 3):
            with self.subTest(fingers=fingers):
                gesture, bridge = fresh()
                gesture.set_settings(three_finger_middle_click=True)
                settings = gesture.get_settings()
                gesture.touch_down(1, 300, 300, 100.0)
                gesture.suppress_taps_for_current_group()
                for tid in range(2, fingers + 1):
                    gesture.touch_down(tid, 300 + tid * 100, 300, 100.02)
                for tid in range(fingers, 0, -1):
                    gesture.touch_up(tid, 100.10)
                self.assertEqual(bridge.events, [])
                self.assertEqual(gesture.get_settings(), settings)
                # A genuinely new group can tap normally after every lift.
                gesture.touch_down(4, 300, 300, 100.15)
                gesture.touch_up(4, 100.25)
                self.assertEqual(bridge.events, [("click", E.BTN_LEFT)])

    def test_recovery_group_still_allows_pointer_motion_and_scroll(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.suppress_taps_for_current_group()
        gesture.touch_move(1, 350, 300, 100.05)
        self.assertTrue(bridge.moves)
        bridge.events.clear()
        gesture.touch_down(2, 500, 300, 100.06)
        gesture.touch_move(2, 500, 350, 100.10)
        self.assertTrue(any(event[0] == "scroll" for event in bridge.events))
        self.assertEqual(bridge.moves, [])
        gesture.touch_up(2, 100.12)
        gesture.touch_up(1, 100.14)
        self.assertEqual(bridge.clicks, [])

    def test_reset_clears_recovery_suppression_for_the_next_group(self):
        gesture, bridge = fresh()
        gesture.touch_down(1, 300, 300, 100.0)
        gesture.suppress_taps_for_current_group()
        gesture.reset_all()
        self.assertFalse(gesture._suppress_group_taps)
        gesture.touch_down(2, 300, 300, 100.05)
        gesture.touch_up(2, 100.15)
        self.assertEqual(bridge.events, [("click", E.BTN_LEFT)])

    def test_recovery_cancels_long_press_and_late_callback_cannot_cross_groups(self):
        timers = []

        class ManualTimer:
            def __init__(self, delay, callback, args=()):
                self.callback = callback
                self.args = args
                self.alive = False
                self.cancelled = False
                timers.append(self)

            def start(self):
                self.alive = True

            def is_alive(self):
                return self.alive

            def cancel(self):
                self.cancelled = True
                self.alive = False

            def fire_even_if_cancelled(self):
                # Timer.cancel cannot stop an already-dispatched callback.
                self.callback(*self.args)

        gesture, bridge = fresh()
        gesture.set_settings(long_press_right_click=True)
        with patch.object(E.threading, "Timer", ManualTimer):
            gesture.touch_down(1, 300, 300, 100.0)
            old_timer = timers[-1]
            gesture.suppress_taps_for_current_group()
            self.assertTrue(old_timer.cancelled)
            self.assertIsNone(gesture.long_press_timer)
            old_timer.fire_even_if_cancelled()
            self.assertFalse(gesture.long_press_triggered)
            self.assertEqual(bridge.events, [])
            gesture.touch_up(1, 100.10)
            self.assertEqual(bridge.events, [])

            gesture.touch_down(2, 300, 300, 100.15)
            new_timer = timers[-1]
            self.assertIsNot(new_timer, old_timer)
            old_timer.fire_even_if_cancelled()
            self.assertEqual(bridge.events, [])
            self.assertFalse(gesture.long_press_triggered)
            new_timer.fire_even_if_cancelled()
            self.assertEqual(bridge.events, [("click", E.BTN_RIGHT)])
            self.assertTrue(gesture.long_press_triggered)
            gesture.touch_up(2, 100.70)
            self.assertEqual(bridge.events, [("click", E.BTN_RIGHT)])


if __name__ == "__main__":
    unittest.main()
