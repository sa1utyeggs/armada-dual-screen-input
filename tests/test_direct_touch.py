import unittest

from armada_dual_screen_input.direct_touch import DirectTouchGesture
from armada_dual_screen_input.input_geometry import Rect


class DirectTouchTests(unittest.TestCase):
    def setUp(self):
        self.gesture = DirectTouchGesture(Rect(0, 124, 1240, 956))

    def test_first_finger_immediately_sends_absolute_touch_without_confirmation(self):
        event, = self.gesture.begin(11, 310, 363, 1)
        self.assertEqual((event.kind, event.contact_id, event.position), ('down', 11, (.25, .25)))

    def test_independent_contacts_can_move_and_lift_in_any_order(self):
        self.gesture.begin(1, 248, 315.2, 1)
        self.gesture.begin(2, 992, 888.8, 1)
        move, = self.gesture.move(2, 620, 602, 2)
        self.assertEqual((move.kind, move.contact_id, move.position), ('move', 2, (.5, .5)))
        up, = self.gesture.end(1, 3)
        self.assertEqual(up.contact_id, 1)
        self.assertEqual(self.gesture.contacts, {2: (.5, .5)})
        self.assertEqual(self.gesture.rings, ((.5, .5, True),))
        self.gesture.end(2, 4)
        self.assertFalse(self.gesture.held)
        self.assertEqual(self.gesture.rings, ())

    def test_up_to_ten_contacts_and_excess_contacts_never_join_mid_gesture(self):
        for tid in range(10):
            self.assertEqual(self.gesture.begin(tid, 620, 602, 1)[0].kind, 'down')
        self.assertEqual(self.gesture.begin(10, 620, 602, 1), ())
        self.gesture.end(0, 2)
        self.assertEqual(self.gesture.move(10, 800, 700, 3), ())
        self.gesture.end(10, 4)
        self.assertEqual(self.gesture.begin(11, 620, 602, 5)[0].kind, 'down')

    def test_header_contact_never_turns_into_a_touch_when_dragged_into_area(self):
        self.assertEqual(self.gesture.begin(1, 620, 30, 1), ())
        self.assertEqual(self.gesture.move(1, 620, 602, 2), ())
        self.assertEqual(self.gesture.end(1, 3), ())
        self.assertFalse(self.gesture.contacts)

    def test_active_fingers_are_clamped_at_screen_boundaries(self):
        self.gesture.begin(1, 620, 602, 1)
        event, = self.gesture.move(1, -100, 2000, 2)
        self.assertEqual(event.position, (0., 1.))

    def test_cancel_lifts_all_contacts_once_and_discards_old_updates(self):
        self.gesture.begin(1, 200, 300, 1)
        self.gesture.begin(2, 400, 600, 1)
        self.assertEqual([event.contact_id for event in self.gesture.cancel(2)], [1, 2])
        self.assertEqual(self.gesture.cancel(3), ())
        self.assertEqual(self.gesture.move(1, 600, 700, 4), ())
        self.assertEqual(self.gesture.end(2, 5), ())

    def test_invalid_coordinate_does_not_mutate_current_touch(self):
        self.gesture.begin(1, 620, 602, 1)
        with self.assertRaises(ValueError):
            self.gesture.move(1, float('nan'), 600, 2)
        self.assertEqual(self.gesture.contacts, {1: (.5, .5)})

    def test_still_finger_does_not_emit_redundant_moves(self):
        self.gesture.begin(1, 620, 602, 1)
        self.assertEqual(self.gesture.move(1, 620, 602, 2), ())

    def test_mode_is_absolute_and_does_not_apply_relative_sensitivity(self):
        self.gesture.begin(1, 0, 124, 1)
        event, = self.gesture.move(1, 1240, 1080, 2, motion_interval=.001)
        self.assertEqual(event.position, (1., 1.))

    def test_invalid_capacity_rejected(self):
        for capacity in (0, 11, True, 2.5):
            with self.assertRaises(ValueError):
                DirectTouchGesture(self.gesture.pad, max_contacts=capacity)
