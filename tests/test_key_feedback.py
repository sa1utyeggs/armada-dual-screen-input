import unittest
from armada_dual_screen_input.key_feedback import KeyFeedback
from test_keyboard_pulses import FakeScheduler


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.clock=FakeScheduler(); self.changes=[]
        self.feedback=KeyFeedback(self.clock.schedule,self.clock.cancel,
            lambda:self.changes.append(self.clock.now),clock=lambda:self.clock.now/1000)

    def test_short_touch_is_not_erased_before_the_first_paint(self):
        self.feedback.sync(30); self.clock.advance(3); self.feedback.sync(None)
        self.clock.advance(100)
        self.assertEqual(self.feedback.visible,{30})
        self.feedback.painted([30]); self.clock.advance(59)
        self.assertEqual(self.feedback.visible,{30})
        self.clock.advance(1); self.assertFalse(self.feedback.visible)

    def test_long_hold_clears_immediately_when_released(self):
        self.feedback.sync(30); self.feedback.painted([30]); self.clock.advance(500)
        self.assertEqual(self.feedback.visible,{30})
        self.feedback.sync(None); self.assertFalse(self.feedback.visible)

    def test_quick_different_keys_can_each_reach_a_draw(self):
        self.feedback.sync(30); self.feedback.sync(31); self.feedback.sync(None)
        self.assertEqual(self.feedback.visible,{30,31})
        self.feedback.painted([30]); self.clock.advance(60)
        self.assertEqual(self.feedback.visible,{31})
        self.feedback.painted([31]); self.clock.advance(60)
        self.assertFalse(self.feedback.visible)

    def test_old_timer_cannot_clear_a_new_tap_of_the_same_key(self):
        self.feedback.sync(30); self.feedback.painted([30]); self.feedback.sync(None)
        old=self.clock.callbacks[1]
        self.clock.advance(20); self.feedback.sync(30); self.feedback.painted([30])
        old(); self.assertEqual(self.feedback.visible,{30})
        self.feedback.sync(None); self.clock.advance(59)
        self.assertEqual(self.feedback.visible,{30})
        self.clock.advance(1); self.assertFalse(self.feedback.visible)

    def test_clear_and_close_cancel_timers_and_unpainted_feedback(self):
        self.feedback.sync(30); self.feedback.painted([30]); self.feedback.sync(None)
        old=self.clock.callbacks[1]
        self.feedback.sync(31); self.feedback.clear(); old()
        self.assertFalse(self.feedback.visible); self.assertFalse(self.clock.pending)
        self.feedback.close(); self.feedback.sync(32); self.feedback.painted([32])
        self.assertFalse(self.feedback.visible); self.assertFalse(self.clock.pending)
