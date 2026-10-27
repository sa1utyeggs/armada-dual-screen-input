"""Visual trajectories and contact lifecycle, without graphics or input output."""
import math
import unittest

from armada_dual_screen_input.marker_motion import MarkerMotion
from armada_dual_screen_input.marker_sample import decode_sample, sample_payload
from armada_dual_screen_input.marker_frames import MarkerFrames
from test_keyboard_pulses import FakeScheduler


def sample(rings, at, *, ids=None, active=True, mode='position', snap=False):
    if ids is None:
        ids = tuple(range(len(rings)))
    return decode_sample(sample_payload(rings, dict(ids=ids, mode=mode, active=active,
                                                  sampled_at=at, snap=snap)))


class MarkerMotionTests(unittest.TestCase):
    def setUp(self):
        self.motion = MarkerMotion((1920, 1080))
        self.motion.accept(sample(((.3, .5, False),), 1), 1)

    def test_first_sample_and_legacy_samples_are_immediate(self):
        self.assertEqual(self.motion.rings, ((.3, .5, False),))
        self.assertFalse(self.motion.animating)
        self.motion.accept(decode_sample([.4,.6,True]), 2)
        self.assertEqual(self.motion.rings, ((.4,.6,True),))
        self.assertFalse(self.motion.animating)

    def test_movement_generates_bounded_intermediate_positions_then_exactly_settles(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        xs = [self.motion.sample(t)[0][0] for t in (1.017,1.025,1.033,1.041,1.058)]
        self.assertEqual(xs[0],.3)
        self.assertTrue(all(a < b for a,b in zip(xs,xs[1:])),xs)
        self.assertTrue(all(.3 <= x <= .34 for x in xs))
        self.assertEqual(xs[-1],.34)
        self.assertFalse(self.motion.animating)

    def test_advancing_at_different_render_rates_preserves_continuous_time_solution(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        other = MarkerMotion((1920,1080))
        other.accept(sample(((.3,.5,False),),1),1)
        other.accept(sample(((.34,.5,False),),1.017),1.017)
        for now in (1.021,1.025,1.029):
            self.motion.sample(now)
        self.assertAlmostEqual(self.motion.sample(1.033)[0][0], other.sample(1.033)[0][0])

    def test_identical_sample_timestamps_do_not_restart_a_stationary_tail(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        for now in (1.025,1.033,1.041,1.049,1.058):
            self.motion.accept(sample(((.34,.5,False),),now),now)
        self.assertEqual(self.motion.rings,((.34,.5,False),))
        self.assertFalse(self.motion.animating)

    def test_retargeting_advances_old_target_before_using_new_position(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        self.motion.accept(sample(((.38,.5,False),),1.025),1.025)
        expected = .3 + (.34-.3)*(1-math.exp(-.008/.008))
        self.assertAlmostEqual(self.motion.rings[0][0], expected)
        self.assertTrue(expected < self.motion.sample(1.033)[0][0] < .38)

    def test_press_release_and_lift_align_to_confirmed_position(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        self.motion.accept(sample(((.35,.5,True),),1.020),1.020)
        self.assertEqual(self.motion.rings,((.35,.5,True),))
        self.motion.accept(sample(((.36,.5,True),),1.025),1.025)
        self.assertTrue(self.motion.animating)
        self.motion.accept(sample(((.36,.5,False),),1.027),1.027)
        self.assertEqual(self.motion.rings,((.36,.5,False),))
        self.motion.accept(sample(((.37,.5,False),),1.030),1.030)
        self.motion.accept(sample(((.37,.5,False),),1.032,active=False),1.032)
        self.assertEqual(self.motion.rings,((.37,.5,False),))
        self.assertFalse(self.motion.animating)

    def test_source_discontinuity_and_explicit_reset_do_not_animate_old_travel(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        self.motion.accept(sample(((.36,.5,False),),1.020,snap=True),1.020)
        self.assertEqual(self.motion.rings,((.36,.5,False),))
        self.motion.accept(sample(((.38,.5,False),),1.022),1.300)
        self.assertEqual(self.motion.rings,((.38,.5,False),))
        self.assertFalse(self.motion.animating)

    def test_reordered_samples_do_not_move_back_or_restart_animation(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        self.motion.sample(1.025)
        before = self.motion.rings
        self.assertFalse(self.motion.accept(sample(((.1,.5,False),),1.010),1.026))
        self.assertEqual(self.motion.rings,before)
        self.assertEqual(self.motion.sample(1.060),((.34,.5,False),))

    def test_stalled_renderer_finishes_at_latest_target_without_catchup_frames(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        self.assertEqual(self.motion.sample(2),((.34,.5,False),))
        self.assertFalse(self.motion.animating)

    def test_large_discontinuous_jump_is_immediate(self):
        self.motion.accept(sample(((.9,.9,False),),1.017),1.017)
        self.assertEqual(self.motion.rings,((.9,.9,False),))
        self.assertFalse(self.motion.animating)

    def test_multi_touch_identity_survives_reorder_and_never_reuses_removed_finger_path(self):
        first = ((.2,.2,True),(.8,.8,True))
        self.motion.accept(sample(first,1.010,ids=(10,20),mode='direct'),1.010)
        self.motion.accept(sample(((.79,.8,True),(.21,.2,True)),1.017,ids=(20,10),mode='direct'),1.017)
        a,b = self.motion.sample(1.025)
        self.assertTrue(.79 < a[0] < .8)
        self.assertTrue(.2 < b[0] < .21)
        self.motion.accept(sample(((.22,.2,True),),1.027,ids=(10,),mode='direct'),1.027)
        self.assertEqual(len(self.motion.rings),1)
        self.assertLess(self.motion.rings[0][0],.22)
        self.motion.accept(sample(((.7,.7,True),),1.030,ids=(30,),mode='direct'),1.030)
        self.assertEqual(self.motion.rings,((.7,.7,True),))

    def test_empty_contacts_clear_immediately_and_mode_change_starts_without_blending(self):
        self.motion.accept(sample(((.4,.5,True),),1.017,ids=(8,),mode='direct'),1.017)
        self.motion.accept(sample((),1.020,mode='direct',active=False),1.020)
        self.assertFalse(self.motion.rings)
        self.assertFalse(self.motion.animating)
        self.motion.accept(sample(((.5,.5,False),),1.025),1.025)
        self.assertEqual(self.motion.rings,((.5,.5,False),))

    def test_mode_only_change_requests_a_redraw_for_the_same_contact_and_pressed_state(self):
        rings = ((.5, .5, True),)
        for force_snap in (False, True):
            with self.subTest(coalesced_lifecycle_barrier=force_snap):
                motion = MarkerMotion((1920, 1080))
                motion.accept(sample(rings, 1., ids=(8,), mode='position'), 1.)
                # Latest-state batching can discard an intervening empty
                # sample. The surviving direct sample may have exactly the
                # same point, identity and pressure as the positioning sample.
                # Its mode still changes the visible glove into a ring.
                self.assertTrue(motion.accept(sample(rings, 1.01, ids=(8,), mode='direct'),
                                              1.01, force_snap=force_snap))
                self.assertEqual(motion.mode, 'direct')
                self.assertEqual(motion.rings, rings)
                self.assertFalse(motion.animating)
                self.assertFalse(motion.accept(sample(rings, 1.02, ids=(8,), mode='direct'), 1.02))
                self.assertTrue(motion.accept(sample(rings, 1.03, ids=(8,), mode='position'), 1.03))
                self.assertEqual(motion.mode, 'position')
                self.assertEqual(motion.rings, rings)

    def test_coalesced_lifecycle_barrier_overrides_later_movement(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017,force_snap=True)
        self.assertEqual(self.motion.rings,((.34,.5,False),))
        self.assertFalse(self.motion.animating)

    def test_clock_regression_clears_visual_tail(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        self.assertEqual(self.motion.sample(.9),((.34,.5,False),))
        self.assertFalse(self.motion.animating)

    def test_future_timestamp_does_not_freeze_later_genuine_samples(self):
        self.motion.accept(sample(((.34,.5,False),),10000),1.017)
        self.assertFalse(self.motion.animating)
        self.motion.accept(sample(((.35,.5,False),),1.025),1.025)
        self.assertTrue(self.motion.animating)
        self.assertEqual(self.motion.sample(1.080),((.35,.5,False),))

    def test_reversal_stays_inside_confirmed_positions_without_prediction(self):
        self.motion.accept(sample(((.34,.5,False),),1.017),1.017)
        before=self.motion.sample(1.025)[0][0]
        self.motion.accept(sample(((.28,.5,False),),1.026),1.026)
        previous=self.motion.rings[0][0]
        for now in (1.030,1.034,1.042,1.050,1.067):
            x=self.motion.sample(now)[0][0]
            self.assertTrue(.28 <= x <= previous)
            previous=x
        self.assertEqual(previous,.28)

    def test_near_target_stops_at_subpixel_tolerance(self):
        self.motion.accept(sample(((.30001,.5,False),),1.017),1.017)
        self.assertEqual(self.motion.sample(1.018),((.30001,.5,False),))
        self.assertFalse(self.motion.animating)

    def test_sample_validation_rejects_bad_geometry_and_time(self):
        for canvas in ((0,1080),(1920,8193),(True,1080),(1920,)):
            with self.assertRaises(ValueError):MarkerMotion(canvas)
        for now in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):self.motion.sample(now)

    def test_demand_driven_frames_continue_only_until_visual_settles(self):
        loop = FakeScheduler()
        motion = MarkerMotion((1920,1080))
        motion.accept(sample(((.3,.5,False),),0),0)
        painted = []
        def paint():
            painted.append((loop.now,motion.sample(loop.now/1000)))
            if motion.animating:frames.request()
        frames = MarkerFrames(loop.schedule,loop.cancel,paint,self.fail,clock=lambda:loop.now/1000)
        frames.set_refresh(120000)
        loop.advance(17)
        motion.accept(sample(((.34,.5,False),),.017),.017)
        frames.request();loop.advance(100)
        self.assertGreaterEqual(len(painted),4)
        self.assertEqual(painted[-1][1],((.34,.5,False),))
        self.assertFalse(loop.pending)
        count = len(painted);loop.advance(10000)
        self.assertEqual(len(painted),count)


class MarkerSampleTests(unittest.TestCase):
    def test_roundtrip_preserves_ids_time_and_lifecycle(self):
        value=sample(((.2,.3,True),(.7,.8,True)),10,ids=(12,42),mode='direct',snap=True)
        self.assertEqual(value.ids,(12,42))
        self.assertEqual(value.sampled_at,10)
        self.assertTrue(value.snap)

    def test_metadata_rejects_missing_ids_duplicates_and_invalid_values(self):
        good=dict(ids=(1,),mode='position',active=True,sampled_at=10,snap=False)
        for change in ({'ids':()}, {'ids':(True,)}, {'ids':(-1,)}, {'ids':(2**63,)},
                       {'mode':'bad'}, {'active':1}, {'snap':1}, {'sampled_at':float('nan')},
                       {'sampled_at':-1}, {'sampled_at':True}, {'extra':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                sample_payload(((.2,.3,False),),dict(good,**change))
        with self.assertRaises(ValueError):
            sample(((.2,.3,True),(.7,.8,True)),10,ids=(1,1),mode='direct')
        with self.assertRaises(ValueError):sample((),10,active=True,mode='direct')
        with self.assertRaises(ValueError):sample(((.2,.3,True),),10,active=False,mode='direct')


if __name__ == '__main__':unittest.main()
