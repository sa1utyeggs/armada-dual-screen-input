"""Marker pacing without sleeps, graphics libraries or application input."""
import unittest

from armada_dual_screen_input.marker_frames import MarkerFrames
from test_keyboard_pulses import FakeScheduler


class MarkerFrameTests(unittest.TestCase):
    def setUp(self):
        self.loop = FakeScheduler()
        self.paints, self.errors = [], []
        self.frames = MarkerFrames(self.loop.schedule, self.loop.cancel,
            lambda:self.paints.append(self.loop.now), self.errors.append,
            clock=lambda:self.loop.now/1000)

    def test_dirty_batch_is_single_frame_and_idle_has_no_timer(self):
        for _ in range(100):self.frames.request()
        self.assertEqual(len(self.loop.pending),1)
        self.loop.advance(0)
        self.assertEqual(self.paints,[0])
        self.assertFalse(self.loop.pending)
        self.loop.advance(5000)
        self.assertEqual(self.paints,[0])

    def test_fractional_upper_refresh_is_not_rounded_to_a_fixed_9ms(self):
        self.frames.set_refresh(119930)
        for _ in range(1000):
            self.frames.request()
            self.loop.advance(1)
        self.loop.advance(20)
        self.assertTrue(119 <= len(self.paints) <= 122,self.paints)
        gaps={b-a for a,b in zip(self.paints,self.paints[1:])}
        self.assertEqual(gaps,{8,9})
        self.assertFalse(self.loop.pending)

    def test_refresh_drop_reschedules_pending_work(self):
        self.frames.set_refresh(120000)
        self.frames.request();self.loop.advance(0)
        self.loop.advance(1);self.frames.request()
        self.frames.set_refresh(60000)
        self.loop.advance(15)
        self.assertEqual(self.paints,[0])
        self.loop.advance(1)
        self.assertEqual(self.paints,[0,17])

    def test_refresh_increase_can_advance_a_pending_frame(self):
        self.frames.request();self.loop.advance(0)
        self.loop.advance(1);self.frames.request()
        self.frames.set_refresh(120000)
        self.loop.advance(8)
        self.assertEqual(self.paints,[0,9])

    def test_unknown_or_invalid_refresh_uses_bounded_default(self):
        for value in (None,0,True,-1,float('nan'),29999,240001):
            self.frames.set_refresh(120000)
            self.frames.set_refresh(value)
            self.assertEqual(self.frames.refresh_millihz,60000)
        for value in (30000,144000,240000):
            self.frames.set_refresh(value)
            self.assertEqual(self.frames.refresh_millihz,value)

    def test_user_caps_follow_monitor_and_do_not_queue_excess_frames(self):
        for choice, monitor, expected in (('auto',119930,120),('120',119930,120),
                ('60',119930,60),('30',119930,30),('120',60000,60),('auto',144000,144)):
            with self.subTest(choice=choice,monitor=monitor):
                loop=FakeScheduler(); paints=[]
                frames=MarkerFrames(loop.schedule,loop.cancel,lambda:paints.append(loop.now),
                    self.errors.append,clock=lambda:loop.now/1000,frame_rate=choice)
                frames.set_refresh(monitor)
                for _ in range(1000):frames.request();loop.advance(1)
                self.assertLessEqual(abs(len(paints)-expected),1)
                loop.advance(40)
                self.assertFalse(loop.pending)
                count=len(paints);loop.advance(1000)
                self.assertEqual(len(paints),count)

    def test_invalid_frame_rate_is_rejected_before_scheduling(self):
        for choice in (120,True,None,'240','bad',{}):
            with self.assertRaises(ValueError):
                MarkerFrames(self.loop.schedule,self.loop.cancel,lambda:None,
                             self.errors.append,frame_rate=choice)
        self.assertFalse(self.loop.pending)

    def test_stall_skips_old_slots_without_a_catchup_burst(self):
        self.frames.set_refresh(120000)
        self.frames.request();self.loop.advance(0)
        self.loop.advance(1);self.frames.request()
        self.loop.stall(100)
        self.assertEqual(self.paints,[0,101])
        self.frames.request()
        self.loop.advance(7)
        self.assertEqual(self.paints,[0,101])
        self.loop.advance(2)
        self.assertEqual(len(self.paints),3)

    def test_presentation_wait_consumes_budget_without_an_extra_frame_delay(self):
        self.frames.set_refresh(120000)
        def paint():
            self.paints.append(self.loop.now)
            self.loop.now+=20
        self.frames.paint=paint
        self.frames.request();self.loop.run_due()
        self.assertEqual(self.paints,[0])
        self.assertFalse(self.loop.pending)
        self.frames.request()
        self.loop.run_due()
        self.assertEqual(self.paints,[0,20])
        self.assertFalse(self.loop.pending)

    def test_reentrant_request_keeps_one_future_frame(self):
        self.frames.set_refresh(120000)
        def paint():
            self.paints.append(self.loop.now)
            if len(self.paints)==1:self.frames.request()
        self.frames.paint=paint
        self.frames.request();self.loop.advance(0)
        self.assertEqual(self.paints,[0])
        self.assertEqual(len(self.loop.pending),1)
        self.loop.advance(9)
        self.assertEqual(self.paints,[0,9])
        self.assertFalse(self.loop.pending)

    def test_error_closes_dispatch_and_reports_failure_once(self):
        self.frames.paint=lambda:(_ for _ in ()).throw(RuntimeError('lost drawable'))
        self.frames.request();self.loop.advance(0)
        self.assertTrue(self.frames.closed)
        self.assertEqual(len(self.errors),1)
        self.frames.request();self.loop.advance(100)
        self.assertFalse(self.loop.pending)

    def test_close_cancels_pending_frame_and_late_dispatch_is_harmless(self):
        self.frames.request()
        late=next(iter(self.loop.pending.values()))[1]
        self.frames.close()
        self.assertFalse(late())
        self.frames.request();self.frames.set_refresh(120000)
        self.loop.advance(100)
        self.assertFalse(self.paints)
        self.assertFalse(self.loop.pending)


if __name__=='__main__':unittest.main()
