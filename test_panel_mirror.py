"""Lifecycle checks with fake capture, focus and input; no GUI or input device."""
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock

from gamescope_focus import FocusSnapshot, FocusState
from mirror_capture import CapturedFrame, FrameStore
from panel_mirror import PanelMirror


class PanelMirrorTests(unittest.TestCase):
    def setUp(self):
        self.now = time.monotonic()
        self.frame = CapturedFrame(1, 16, 9, 64, bytearray(64 * 9), self.now)
        self.capture = Mock(status='running', source_size=(16, 9), frames=FrameStore())
        self.capture.frames.publish(self.frame)
        self.capture.wait.return_value = True
        self.capture.healthy.return_value = True
        self.source = Mock()
        self.source.current.return_value = True
        self.snapshot = FocusSnapshot(1, 769, 769, 1600, 900, 123,
                                      ':0', 1, True, 4)
        self.focus = Mock()
        self.focus.latest.side_effect = lambda: FocusState(self.snapshot, self.now)
        self.sender = Mock(ready=True)
        self.native_factory = Mock(return_value=self.sender)
        self.mouse_factory = Mock(return_value=self.sender)
        self.target = SimpleNamespace(display_name='gamescope-primary')
        self.discovered = threading.Event()

        def discover():
            self.discovered.set()
            return self.target, 42
        self.panel = PanelMirror(runtime='/run/user/1000', discover=discover,
            capture_factory=Mock(return_value=self.capture),
            source_factory=Mock(return_value=self.source),
            focus_factory=Mock(return_value=self.focus),
            native_factory=self.native_factory, mouse_factory=self.mouse_factory)
        self.addCleanup(self.panel.stop)

    def enter(self):
        self.panel.start()
        self.assertTrue(self.discovered.wait(1))
        # Discovery publishes just after setting the event.
        deadline = time.monotonic() + 1
        while self.panel.capture is None and time.monotonic() < deadline:
            self.panel.tick(self.now)
            time.sleep(0.001)
        self.assertIs(self.panel.capture, self.capture)

    def arm(self):
        self.enter()
        self.advance(0.25)
        self.advance(0.1)
        self.assertTrue(self.panel.armed)

    def advance(self, seconds, *, contacts_down=False):
        self.now += seconds
        self.panel.tick(self.now, contacts_down=contacts_down)

    def test_entering_mirror_waits_for_stable_focus_then_automatically_enables(self):
        self.panel.tick(self.now)
        self.panel.capture_factory.assert_not_called()
        self.enter()
        self.capture.start.assert_called_once()
        self.assertFalse(self.panel.armed)
        self.native_factory.assert_not_called()
        self.assertTrue(self.panel.auto_requested)
        self.advance(0.25)
        self.advance(0.1)
        self.assertTrue(self.panel.armed)

    def test_default_native_drag_and_no_dual_finger_wheel(self):
        self.arm()
        self.panel.touch('begin', 11, self.now, 500, 500)
        self.panel.touch('begin', 12, self.now, 600, 500)
        self.panel.touch('move', 11, self.now, 520, 530)
        self.panel.touch('move', 12, self.now, 620, 530)
        self.panel.touch('end', 11, self.now)
        self.panel.touch('end', 12, self.now)
        intents = [c.args[0] for c in self.sender.send.call_args_list]
        self.assertEqual([i.kind for i in intents], ['down', 'down', 'move', 'move', 'up', 'up'])
        self.assertEqual({i.contact_id for i in intents}, {11, 12})
        self.mouse_factory.assert_not_called()

    def test_leaving_during_held_contact_releases_and_stops_every_worker(self):
        self.arm()
        self.panel.touch('begin', 7, self.now, 500, 500)
        self.panel.stop()
        self.sender.release_all.assert_called()
        self.sender.close.assert_called_once()
        self.capture.stop.assert_called_once()
        self.source.stop.assert_called_once()
        self.focus.stop.assert_called_once()
        self.assertFalse(self.panel.armed)
        self.assertIsNone(self.panel.frame)

    def test_focus_loss_between_touches_closes_device_immediately(self):
        self.arm()
        self.sender.poll.side_effect = OSError('focus lost')
        self.panel.touch('begin', 7, self.now, 500, 500)
        self.assertFalse(self.panel.armed)
        self.sender.close.assert_called()

    def test_input_mode_switch_automatically_connects_after_fingers_lift(self):
        self.arm()
        self.panel.set_input_mode('mouse')
        self.assertFalse(self.panel.armed)
        self.sender.close.assert_called_once()
        self.advance(0.1, contacts_down=True)
        self.mouse_factory.assert_not_called()
        self.advance(0.25)
        self.advance(0.1)
        self.advance(0.1)
        self.mouse_factory.assert_called_once()
        self.assertTrue(self.panel.armed)

    def test_stop_before_discovery_finishes_does_not_start_late_capture(self):
        gate = threading.Event()
        self.panel.discover = lambda: (gate.wait(1), None)
        self.panel.start()
        self.panel.stop()
        gate.set()
        self.panel.tick(self.now)
        self.panel.capture_factory.assert_not_called()

    def test_dead_pipeline_and_stale_frame_release_input(self):
        self.arm()
        self.capture.status = 'error'
        self.panel.tick(self.now + 1)
        self.assertFalse(self.panel.armed)
        self.sender.close.assert_called()

    def test_reenter_cannot_create_second_consumer_while_prior_stop_hangs(self):
        self.enter()
        self.capture.wait.return_value = False
        self.panel.stop()
        self.discovered.clear()
        self.panel.start()
        deadline = time.monotonic() + 1
        while self.panel.last_error is None and time.monotonic() < deadline:
            self.panel.tick(self.now)
            time.sleep(0.001)
        self.assertIn('still stopping', self.panel.last_error)
        self.panel.capture_factory.assert_called_once()
        self.assertFalse(self.discovered.is_set())

    def test_tab_selecting_finger_blocks_device_creation_until_real_lift(self):
        self.enter()
        self.advance(1, contacts_down=True)
        self.advance(2, contacts_down=True)
        self.native_factory.assert_not_called()
        self.assertIn('抬起', self.panel.message)
        self.advance(0.1)
        self.advance(0.1)
        self.advance(0.1)
        self.assertTrue(self.panel.armed)
        self.sender.send.assert_not_called()

    def test_finger_arriving_during_connection_prevents_arm_without_retry_churn(self):
        self.enter()
        self.sender.ready = False
        self.advance(0.25)
        self.native_factory.assert_called_once()
        self.sender.ready = True
        self.advance(3, contacts_down=True)
        self.assertFalse(self.panel.armed)
        self.native_factory.assert_called_once()
        self.advance(0.1)
        self.advance(0.1)
        self.assertTrue(self.panel.armed)

    def test_manual_pause_stays_paused_until_user_resumes(self):
        self.arm()
        self.panel.toggle(self.now)
        self.advance(10)
        self.assertFalse(self.panel.armed)
        self.assertFalse(self.panel.auto_requested)
        self.native_factory.assert_called_once()
        self.panel.toggle(self.now)
        self.advance(0.1)
        self.advance(0.25)
        self.advance(0.1)
        self.assertTrue(self.panel.armed)

    def test_switching_input_style_while_manually_paused_does_not_resume(self):
        self.arm()
        self.panel.pause()
        self.panel.set_input_mode('mouse')
        self.advance(5)
        self.mouse_factory.assert_not_called()
        self.assertFalse(self.panel.auto_requested)

    def test_unstable_focus_restarts_settle_delay(self):
        from dataclasses import replace
        self.enter()
        self.advance(0.1)
        self.snapshot = replace(self.snapshot, window=2, input_window=2)
        self.advance(0.15)
        self.native_factory.assert_not_called()
        self.advance(0.1)
        self.native_factory.assert_not_called()
        self.advance(0.15)
        self.advance(0.1)
        self.assertTrue(self.panel.armed)
        self.assertEqual(self.native_factory.call_args.args[1], self.snapshot)

    def test_failed_connection_retries_with_backoff(self):
        self.native_factory.side_effect = OSError('temporarily unavailable')
        self.enter()
        self.advance(0.25)
        self.assertEqual(self.native_factory.call_count, 1)
        for _ in range(10):
            self.advance(0.1)
        self.assertEqual(self.native_factory.call_count, 1)
        self.advance(0.6)
        self.advance(0.25)
        self.assertEqual(self.native_factory.call_count, 2)
        self.assertTrue(self.panel.auto_requested)

    def test_focus_loss_releases_then_recovers_without_replaying_old_finger(self):
        self.arm()
        self.panel.touch('begin', 7, self.now, 500, 500)
        self.sender.poll.side_effect = OSError('focus changed')
        self.panel.touch('move', 7, self.now, 550, 500)
        self.assertFalse(self.panel.armed)
        self.sender.poll.side_effect = None
        self.advance(2, contacts_down=True)
        self.assertFalse(self.panel.armed)
        self.advance(0.1)
        self.advance(0.1)
        self.advance(0.1)
        self.advance(0.1)
        self.assertTrue(self.panel.armed)
        self.sender.send.reset_mock()
        self.panel.touch('move', 7, self.now, 600, 600)
        self.panel.touch('end', 7, self.now)
        self.sender.send.assert_not_called()

    def test_child_focus_changes_do_not_restart_settle_timer_or_native_connection(self):
        from dataclasses import replace
        self.enter()
        self.advance(0.1)
        self.snapshot = replace(self.snapshot, input_window=2)
        self.advance(0.15)
        self.advance(0.1)
        self.assertTrue(self.panel.armed)
        self.panel.touch('begin', 7, self.now, 500, 500)
        self.snapshot = replace(self.snapshot, input_window=3)
        self.advance(0.02, contacts_down=True)
        self.panel.touch('move', 7, self.now, 600, 500)
        self.panel.touch('end', 7, self.now)
        self.assertTrue(self.panel.armed)
        self.native_factory.assert_called_once()
        self.sender.close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
