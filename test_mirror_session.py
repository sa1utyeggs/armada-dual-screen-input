import unittest

from ei_input import InputUnavailable
from mirror_capture import CapturedFrame
from mirror_geometry import Rect
from mirror_session import MirrorSession


class Sender:
    def __init__(self):
        self.ready = True
        self.lost = False
        self.events = []
        self.releases = 0
        self.closed = False

    def poll(self):
        if self.lost: raise InputUnavailable('target disappeared')

    def send(self, event): self.events.append(event)
    def release_all(self): self.releases += 1
    def close(self): self.closed = True


class MirrorSessionTests(unittest.TestCase):
    def setUp(self):
        self.sender = Sender()
        self.session = MirrorSession(self.sender)
        self.viewport = Rect(0, 0, 100, 100)
        self.frame = CapturedFrame(1, 100, 100, 400, bytearray(40000), 10)

    def prepare(self):
        self.session.update(self.frame, self.viewport, 10, live=True)
        self.assertTrue(self.session.arm(10))

    def test_initial_preview_is_paused_and_cannot_replay_ignored_touches(self):
        self.session.update(self.frame, self.viewport, 10, live=True)
        self.session.touch('begin', 1, 10.01, 50, 50)
        self.session.arm(10.02)
        self.session.touch('end', 1, 10.03)
        self.assertEqual(self.sender.events, [])

    def test_missing_frame_or_unready_input_cannot_arm(self):
        self.assertFalse(self.session.arm(10))
        self.sender.ready = False
        self.session.update(self.frame, self.viewport, 10, live=True)
        self.assertFalse(self.session.arm(10))

    def test_armed_tap_reaches_sender(self):
        self.prepare()
        self.session.touch('begin', 1, 10.01, 50, 50)
        self.session.touch('end', 1, 10.03)
        self.assertEqual([e.kind for e in self.sender.events], ['down', 'up'])

    def test_stale_image_cancels_pending_press_before_timer_can_fire(self):
        self.prepare()
        self.session.touch('begin', 1, 10.01, 50, 50)
        self.session.tick(10.5)
        self.assertFalse(self.session.armed)
        self.assertEqual(self.session.reason, 'stale_frame')
        self.assertEqual(self.sender.events, [])

    def test_static_frame_requires_explicit_source_and_capture_liveness(self):
        self.session.update(self.frame, self.viewport, 12, live=True, cached_frame_current=True)
        self.assertTrue(self.session.arm(12))
        self.session.touch('begin', 1, 12.01, 50, 50)
        self.session.touch('end', 1, 12.03)
        self.assertEqual([e.kind for e in self.sender.events], ['down', 'up'])
        self.session.update(self.frame, self.viewport, 12.1, live=True, cached_frame_current=False)
        self.assertFalse(self.session.armed)

    def test_capture_error_releases_active_drag_immediately(self):
        self.prepare()
        self.session.touch('begin', 1, 10.01, 50, 50)
        self.session.tick(10.08)
        before = self.sender.releases
        self.session.update(self.frame, self.viewport, 10.1, live=False)
        self.assertFalse(self.session.armed)
        self.assertGreater(self.sender.releases, before)
        self.assertEqual([e.kind for e in self.sender.events], ['down'])

    def test_target_loss_closes_backend_and_disarms(self):
        self.prepare()
        self.sender.lost = True
        self.session.tick(10.1)
        self.assertTrue(self.session.failed)
        self.assertTrue(self.sender.closed)
        self.assertFalse(self.session.armed)

    def test_resize_disarms_and_discards_old_finger(self):
        self.prepare()
        self.session.touch('begin', 1, 10.01, 50, 50)
        self.session.update(self.frame, Rect(0, 0, 200, 200), 10.02, live=True)
        self.assertFalse(self.session.armed)
        self.session.arm(10.03)
        self.session.touch('move', 1, 10.04, 100, 100)
        self.session.touch('end', 1, 10.05)
        self.assertEqual(self.sender.events, [])

    def test_two_finger_end_stops_wheel_and_does_not_click(self):
        self.prepare()
        self.session.touch('begin', 1, 10.01, 40, 50)
        self.session.touch('begin', 2, 10.02, 60, 50)
        self.session.touch('move', 1, 10.03, 40, 30)
        before = self.sender.releases
        self.session.touch('end', 1, 10.04)
        self.assertGreater(self.sender.releases, before)
        self.assertEqual([e.kind for e in self.sender.events], ['wheel'])

    def test_new_frames_after_pause_do_not_automatically_rearm(self):
        self.prepare()
        self.session.pause(10.01)
        frame = CapturedFrame(2, 100, 100, 400, bytearray(40000), 11)
        self.session.update(frame, self.viewport, 11, live=True)
        self.assertFalse(self.session.armed)
        self.assertTrue(self.session.arm(11))


if __name__ == '__main__':
    unittest.main()
