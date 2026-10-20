import unittest

from mirror_geometry import Rect
from position_gesture import PositionGesture


class PositionGestureTests(unittest.TestCase):
    def setUp(self):
        self.g = PositionGesture(Rect(0, 124, 1240, 956))

    def test_aiming_emits_no_app_input_and_retouch_does_not_jump(self):
        self.assertEqual(self.g.begin(1, 600, 600, 1), ())
        self.assertEqual(self.g.move(1, 724, 695.6, 2), ())
        self.assertAlmostEqual(self.g.point[0], .6)
        self.assertAlmostEqual(self.g.point[1], .6)
        self.assertEqual(self.g.end(1, 3), ())
        self.assertEqual(self.g.begin(2, 10, 130, 4), ())
        self.assertAlmostEqual(self.g.point[0], .6)

    def test_confirm_anywhere_targets_marker_and_its_motion_is_ignored(self):
        self.g.begin(1, 20, 200, 1)
        event, = self.g.begin(2, 1200, 1050, 2)
        self.assertEqual((event.kind, event.position), ('down', (.5, .5)))
        self.assertEqual(self.g.move(2, 10, 200, 3), ())
        self.assertEqual(self.g.point, (.5, .5))
        event, = self.g.end(2, 4)
        self.assertEqual(event.kind, 'up')
        self.assertEqual(self.g.move(1, 30, 200, 5), ())
        self.assertFalse(self.g.held)
        self.assertEqual(self.g.begin(3, 300, 200, 6)[0].kind, 'down')

    def test_held_confirm_and_aim_motion_produce_one_native_drag(self):
        events = list(self.g.begin(1, 300, 300, 1))
        events += self.g.begin(2, 1000, 1000, 2)
        events += self.g.move(1, 424, 300, 3)
        events += self.g.end(2, 4)
        self.assertEqual([e.kind for e in events], ['down', 'move', 'up'])
        self.assertEqual({e.contact_id for e in events}, {0})
        self.assertAlmostEqual(events[-1].position[0], .6)

    def test_aim_lifting_first_releases_without_promoting_orphan_confirm(self):
        self.g.begin(1, 300, 300, 1)
        self.g.begin(2, 1000, 1000, 2)
        self.assertEqual(self.g.end(1, 3)[0].kind, 'up')
        self.assertEqual(self.g.move(2, 900, 900, 4), ())
        self.assertEqual(self.g.begin(3, 400, 400, 5), ())
        self.assertEqual(self.g.point, (.5, .5))
        self.assertEqual(self.g.aim, 3)
        self.assertIsNone(self.g.confirm)
        self.g.end(2, 6)
        self.assertFalse(self.g.blocked)
        self.g.end(3, 7)
        self.assertFalse(self.g.blocked)

    def test_missing_orphan_end_does_not_block_new_aim_or_reuse_old_confirmation(self):
        self.g.begin(1,300,300,1)
        self.g.begin(2,600,600,2)
        self.assertEqual(self.g.end(1,3)[0].kind,'up')
        # No END for contact 2. A brand-new finger may position, without input.
        self.assertEqual(self.g.begin(3,300,300,4),())
        self.assertEqual(self.g.move(3,424,300,5),())
        self.assertAlmostEqual(self.g.point[0],.6)
        self.assertFalse(self.g.held)
        self.assertEqual(self.g.move(2,900,900,6),())
        # Only another NEW begin can confirm; the old end cannot release it.
        self.assertEqual(self.g.begin(4,1000,1000,7)[0].kind,'down')
        self.assertEqual(self.g.end(2,8),())
        self.assertTrue(self.g.held)
        self.assertEqual(self.g.move(3,548,300,9)[0].kind,'move')
        self.assertEqual(self.g.end(4,10)[0].kind,'up')

    def test_multiple_orphans_never_become_the_new_aim_or_confirm(self):
        self.g.begin(1,300,300,1)
        self.g.begin(2,600,600,2)
        self.g.begin(3,900,900,3)
        self.g.end(1,4)
        self.assertEqual(self.g.begin(4,400,400,5),())
        self.assertEqual(self.g.move(4,524,400,6),())
        self.assertEqual(self.g.move(2,700,700,7),())
        self.assertEqual(self.g.move(3,800,800,8),())
        self.assertFalse(self.g.held)

    def test_third_finger_does_not_move_or_release_owned_contact(self):
        self.g.begin(1, 300, 300, 1)
        self.g.begin(2, 600, 600, 2)
        self.assertEqual(self.g.begin(3, 900, 900, 3), ())
        self.assertEqual(self.g.move(3, 200, 200, 4), ())
        self.assertEqual(self.g.end(3, 5), ())
        self.assertTrue(self.g.held)

    def test_edges_are_clamped_and_reverse_motion_recovers_immediately(self):
        self.g.begin(1, 0, 124, 1)
        self.g.move(1, 5000, 5000, 2)
        self.assertEqual(self.g.point, (1., 1.))
        self.g.move(1, 4876, 4904.4, 3)
        self.assertAlmostEqual(self.g.point[0], .9)
        self.assertAlmostEqual(self.g.point[1], .9)

    def test_cancel_and_center_release_without_late_lift_click(self):
        self.g.begin(1, 300, 300, 1)
        self.g.begin(2, 600, 600, 2)
        self.assertEqual(self.g.center(3)[0].kind, 'cancel')
        self.assertEqual(self.g.end(2, 4), ())
        self.assertEqual(self.g.point, (.5, .5))
        self.assertFalse(self.g.held)

    def test_single_finger_jump_is_quarantined_without_creating_touch(self):
        self.g.begin(1, 300, 300, 1)
        for x, interval in ((835, .293), (836, .016)):
            self.assertEqual(self.g.move(1, x, 300, 2, motion_interval=interval), ())
            self.assertEqual(self.g.point, (.5, .5))
        self.g.move(1, 840, 300, 3, motion_interval=.016)
        self.assertAlmostEqual(self.g.point[0], .5+4/1240)
        self.assertFalse(self.g.held)

    def test_spike_during_native_hold_keeps_the_same_contact_and_releases_normally(self):
        self.g.begin(1, 300, 300, 1)
        down, = self.g.begin(2, 1000, 1000, 2)
        self.assertEqual(self.g.move(1, 835, 300, 3, motion_interval=.016), ())
        self.assertEqual(self.g.move(1, 302, 300, 4, motion_interval=.016), ())
        self.assertTrue(self.g.held)
        moved, = self.g.move(1, 310, 300, 5, motion_interval=.016)
        up, = self.g.end(2, 6)
        self.assertEqual([down.kind, moved.kind, up.kind], ['down', 'move', 'up'])
        self.assertEqual({down.contact_id, moved.contact_id, up.contact_id}, {0})

    def test_lift_during_quarantine_cannot_affect_the_next_aim(self):
        self.g.begin(1, 300, 300, 1)
        self.g.move(1, 835, 300, 2, motion_interval=.016)
        self.g.end(1, 3)
        self.g.begin(2, 100, 100, 4)
        self.g.move(2, 110, 100, 5, motion_interval=.016)
        self.assertAlmostEqual(self.g.point[0], .5+10/1240)


if __name__ == '__main__': unittest.main()
