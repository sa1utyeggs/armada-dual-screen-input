import unittest

from mirror_geometry import MirrorTransform, Rect
from mirrored_touch import MirroredTouch


class MirroredTouchTests(unittest.TestCase):
    def setUp(self):
        self.transform = MirrorTransform.fit(1920, 1080, Rect(0, 0, 1000, 1000))
        self.touch = MirroredTouch(self.transform)

    def test_quick_tap_produces_one_press_and_release_without_early_click(self):
        self.assertEqual(self.touch.begin(1, 500, 500, 1), ())
        self.assertEqual(self.touch.tick(1.03), ())
        events = self.touch.end(1, 1.04)
        self.assertEqual([e.kind for e in events], ['down', 'up'])
        self.assertEqual(events[0].position, (0.5, 0.5))
        self.assertEqual(self.touch.tick(2), ())

    def test_stationary_long_press_uses_a_deadline_not_a_blocking_sleep(self):
        self.touch.begin(1, 500, 500, 1)
        self.assertAlmostEqual(self.touch.deadline, 1.06)
        self.assertEqual([e.kind for e in self.touch.tick(1.07)], ['down'])
        self.assertIsNone(self.touch.deadline)
        self.assertEqual(self.touch.tick(2), ())
        self.assertEqual([e.kind for e in self.touch.end(1, 3)], ['up'])

    def test_buffered_drag_starts_at_original_position_then_catches_up(self):
        self.touch.begin(1, 500, 500, 1)
        self.assertEqual(self.touch.move(1, 600, 500, 1.02), ())
        events = self.touch.tick(1.07)
        self.assertEqual([e.kind for e in events], ['down', 'move'])
        self.assertEqual(events[0].position, (0.5, 0.5))
        self.assertEqual(events[1].position, (0.6, 0.5))

    def test_quick_drag_released_inside_chord_window_retains_drag_sequence(self):
        self.touch.begin(1, 500, 500, 1)
        self.touch.move(1, 600, 500, 1.02)
        self.assertEqual([e.kind for e in self.touch.end(1, 1.04)],
                         ['down', 'move', 'up'])

    def test_two_fingers_scroll_without_any_click_or_press(self):
        self.touch.begin(1, 450, 500, 1)
        self.assertEqual(self.touch.begin(2, 550, 500, 1.02), ())
        events = self.touch.move(1, 450, 470, 1.03)
        events += self.touch.move(2, 550, 470, 1.04)
        self.assertTrue(events)
        self.assertTrue(all(e.kind == 'wheel' for e in events))
        self.assertTrue(all(e.wheel[1] > 0 for e in events))
        self.assertEqual(events[-1].position, self.transform.to_source(500, 470))

    def test_one_remaining_scroll_finger_never_becomes_a_tap_or_drag(self):
        self.touch.begin(1, 450, 500, 1)
        self.touch.begin(2, 550, 500, 1.01)
        self.touch.move(1, 450, 470, 1.02)
        self.assertEqual(self.touch.end(2, 1.03), ())
        self.assertEqual(self.touch.move(1, 700, 500, 2), ())
        self.assertEqual(self.touch.end(1, 3), ())
        self.assertEqual(self.touch.state, 'idle')

    def test_extra_finger_during_drag_does_not_release_or_start_scroll(self):
        self.touch.begin(1, 500, 500, 1)
        self.touch.tick(1.07)
        self.assertEqual(self.touch.begin(2, 600, 500, 1.08), ())
        self.assertEqual(self.touch.move(2, 700, 500, 1.09), ())
        self.assertEqual([e.kind for e in self.touch.move(1, 520, 500, 1.1)], ['move'])
        self.assertEqual([e.kind for e in self.touch.end(1, 1.2)], ['up'])
        self.assertEqual(self.touch.move(2, 800, 500, 1.3), ())
        self.assertEqual(self.touch.end(2, 1.4), ())

    def test_finger_arriving_after_window_keeps_committed_single_touch(self):
        self.touch.begin(1, 500, 500, 1)
        events = self.touch.begin(2, 600, 500, 1.07)
        self.assertEqual([e.kind for e in events], ['down'])
        self.assertEqual(self.touch.state, 'single')

    def test_third_finger_blocks_scroll_until_every_finger_lifts(self):
        self.touch.begin(1, 450, 500, 1)
        self.touch.begin(2, 550, 500, 1.01)
        self.touch.move(1, 450, 470, 1.02)
        self.assertEqual(self.touch.begin(3, 650, 500, 1.03), ())
        self.assertEqual(self.touch.move(1, 450, 400, 1.04), ())
        for tid in (1, 2, 3):
            self.assertEqual(self.touch.end(tid, 2), ())
        self.assertEqual(self.touch.state, 'idle')

    def test_landing_jitter_below_scroll_threshold_has_no_output(self):
        self.touch.begin(1, 450, 500, 1)
        self.touch.begin(2, 550, 500, 1.01)
        self.assertEqual(self.touch.move(1, 451, 501, 1.02), ())
        self.assertEqual(self.touch.move(2, 551, 501, 1.03), ())
        self.assertEqual(self.touch.end(1, 1.1), ())
        self.assertEqual(self.touch.end(2, 1.2), ())

    def test_scroll_threshold_emits_only_excess_and_retains_fractional_units(self):
        self.touch.begin(1, 450, 500, 1)
        self.touch.begin(2, 550, 500, 1.01)
        events = self.touch.move(1, 450, 490, 1.02)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0].wheel[1], 360 / 562.5)

    def test_horizontal_scroll_is_separate_from_vertical_scroll(self):
        self.touch.begin(1, 450, 500, 1)
        self.touch.begin(2, 550, 500, 1.01)
        event, = self.touch.move(1, 470, 500, 1.02)
        self.assertGreater(event.wheel[0], 0)
        self.assertEqual(event.wheel[1], 0)

    def test_scroll_gain_is_independent_of_panel_resolution(self):
        totals = []
        for scale in (1, 2):
            t = MirroredTouch(MirrorTransform.fit(1920, 1080,
                             Rect(0, 0, 1000 * scale, 1000 * scale)), scroll_threshold=0)
            t.begin(1, 450 * scale, 500 * scale, 1)
            t.begin(2, 550 * scale, 500 * scale, 1.01)
            events = t.move(1, 450 * scale, 470 * scale, 1.02)
            events += t.move(2, 550 * scale, 470 * scale, 1.03)
            totals.append(sum(e.wheel[1] for e in events))
        self.assertAlmostEqual(*totals)

    def test_optional_natural_scrolling_reverses_both_axes(self):
        totals = []
        for natural in (False, True):
            t = MirroredTouch(self.transform, natural_scroll=natural)
            t.begin(1, 450, 500, 1)
            t.begin(2, 550, 500, 1.01)
            event, = t.move(1, 470, 470, 1.02)
            totals.append(event.wheel)
        self.assertAlmostEqual(totals[0][0], -totals[1][0])
        self.assertAlmostEqual(totals[0][1], -totals[1][1])

    def test_initial_touch_in_margin_is_ignored_until_all_contacts_end(self):
        self.touch.begin(1, 500, 0, 1)
        self.touch.begin(2, 500, 500, 1.01)
        self.assertEqual(self.touch.tick(2), ())
        self.assertEqual(self.touch.end(1, 3), ())
        self.assertEqual(self.touch.end(2, 4), ())

    def test_drag_outside_image_clamps_and_can_still_release(self):
        self.touch.begin(1, 500, 500, 1)
        self.touch.tick(1.1)
        event, = self.touch.move(1, -500, -500, 1.2)
        self.assertEqual(event.position, (0, 0))
        event, = self.touch.end(1, 1.3)
        self.assertEqual((event.kind, event.position), ('up', (0, 0)))

    def test_cancel_after_deadline_never_materializes_a_pending_tap(self):
        self.touch.begin(1, 500, 500, 1)
        self.assertEqual(self.touch.cancel(3), ())
        self.assertEqual(self.touch.tick(4), ())
        self.assertEqual(self.touch.end(1, 5), ())

    def test_active_cancel_is_distinct_from_normal_lift(self):
        self.touch.begin(1, 500, 500, 1)
        self.touch.tick(1.1)
        self.assertEqual([e.kind for e in self.touch.cancel(2)], ['cancel'])
        self.assertEqual(self.touch.cancel(3), ())

    def test_resizing_cancels_old_input_before_changing_coordinates(self):
        self.touch.begin(1, 500, 500, 1)
        self.touch.tick(1.1)
        events = self.touch.set_transform(
            MirrorTransform.fit(1280, 800, Rect(0, 0, 800, 600)), 2)
        self.assertEqual([e.kind for e in events], ['cancel'])
        self.assertEqual(self.touch.move(1, 600, 500, 3), ())

    def test_paused_input_stays_silent_and_resume_requires_new_contact(self):
        self.touch.set_enabled(False, 1)
        self.assertEqual(self.touch.begin(1, 500, 500, 2), ())
        self.assertEqual(self.touch.tick(3), ())
        self.touch.set_enabled(True, 4)
        self.assertEqual(self.touch.move(1, 600, 500, 5), ())
        self.assertEqual(self.touch.end(1, 6), ())
        self.touch.begin(2, 500, 500, 7)
        self.assertEqual([e.kind for e in self.touch.end(2, 7.02)], ['down', 'up'])

    def test_invalid_coordinates_do_not_change_pending_gesture(self):
        self.touch.begin(1, 500, 500, 1)
        with self.assertRaises(ValueError):
            self.touch.move(1, float('nan'), 500, 2)
        self.assertEqual(self.touch.state, 'pending')
        with self.assertRaises(ValueError):
            self.touch.begin(1, 500, 500, 2)


if __name__ == '__main__':
    unittest.main()
