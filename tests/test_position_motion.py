import unittest

from armada_dual_screen_input.position_motion import PositionMotion


class PositionMotionTests(unittest.TestCase):
    def setUp(self):
        self.m = PositionMotion(956)
        self.m.reset((300, 300))

    def test_normal_motion_is_immediate_without_smoothing(self):
        for x in (310, 330, 360, 410):
            previous = self.m.point
            self.assertEqual(self.m.delta((x, 300), .016), (x-previous[0], 0))

    def test_recorded_large_recontact_never_replays_its_jump(self):
        self.assertIsNone(self.m.delta((835, 300), .293))
        self.assertIsNone(self.m.delta((836, 300), .016))
        self.assertEqual(self.m.delta((840, 300), .016), (4, 0))

    def test_isolated_spike_and_return_do_not_create_an_inverse_jump(self):
        self.assertIsNone(self.m.delta((835, 300), .016))
        self.assertIsNone(self.m.delta((302, 300), .016))
        self.assertEqual(self.m.delta((308, 300), .016), (6, 0))

    def test_repeated_alternating_spikes_cannot_accumulate_motion(self):
        for _ in range(5):
            self.assertIsNone(self.m.delta((835, 300), .016))
            self.assertIsNone(self.m.delta((300, 300), .016))
        self.assertEqual(self.m.delta((305, 300), .016), (5, 0))

    def test_coherent_fast_swipe_continues_without_repaying_ambiguous_first_step(self):
        self.assertIsNone(self.m.delta((520, 300), .016))
        self.assertEqual(self.m.delta((740, 300), .016), (220, 0))
        self.assertEqual(self.m.delta((960, 300), .016), (220, 0))

    def test_previous_speed_does_not_authorize_a_jump_after_a_source_gap(self):
        self.m.delta((400, 300), .016)
        self.m.delta((500, 300), .016)
        self.assertIsNone(self.m.delta((1035, 300), .293))

    def test_reset_drops_old_quarantine_and_unsourced_calls_preserve_legacy_behavior(self):
        self.m.delta((835, 300), .016)
        self.m.reset((10, 10))
        self.assertEqual(self.m.delta((12, 13), .016), (2, 3))
        self.assertEqual(self.m.delta((1000, 1000)), (988, 987))

    def test_bad_timing_is_rejected_before_mutating_motion_state(self):
        for interval in (float('nan'), float('inf'), -1):
            with self.assertRaises(ValueError): self.m.delta((400, 400), interval)
            self.assertEqual(self.m.point, (300, 300))


if __name__ == '__main__': unittest.main()
