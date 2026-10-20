from dataclasses import replace
from types import SimpleNamespace
import unittest

from ei_input import InputUnavailable
from gamescope_focus import FocusSnapshot, FocusState
from panel_position import PanelPosition


class Marker:
    size = (1920, 1080)
    def __init__(self, **kwargs): self.valid=True; self.closed=False; self.updates=[]
    def current(self, now): return self.valid and not self.closed
    def update(self, point, pressed=False): self.updates.append((point, pressed))
    def poll(self):
        if self.closed: raise InputUnavailable('marker gone')
    def close(self): self.closed=True
    def wait(self): pass


class Sender:
    ready=True
    def __init__(self, *args, focus_check): self.events=[]; self.closed=False; self.focus_check=focus_check
    def poll(self):
        if not self.focus_check(): raise InputUnavailable('target changed')
    def send(self, event): self.poll(); self.events.append(event)
    def close(self): self.closed=True


class PanelPositionTests(unittest.TestCase):
    def setUp(self):
        self.now=10.
        self.snapshot=FocusSnapshot(10,769,769,1920,1080,42,':0',10,True,4)
        self.focus=SimpleNamespace(start=lambda:None, stop=lambda:None,
            latest=lambda:FocusState(self.snapshot, self.now))
        self.target=SimpleNamespace(is_current=lambda:True)
        self.p=PanelPosition(resolve=lambda:self.target, focus_factory=lambda _:self.focus,
            marker_factory=Marker, native_factory=Sender, clock=lambda:self.now)
        self.p.start()
        self.addCleanup(self.p.stop)

    def tick(self, elapsed=0, contacts=False):
        self.now+=elapsed
        self.p.tick(contacts_down=contacts)

    def arm(self):
        self.tick(); self.tick(.25); self.tick(.01)
        self.assertTrue(self.p.armed)

    def test_only_lifted_stable_target_arms_without_any_capture_dependency(self):
        self.tick(contacts=True); self.tick(.5, contacts=True)
        self.assertFalse(self.p.armed)
        self.tick(); self.tick(.09); self.tick(.01)
        self.assertTrue(self.p.armed)
        self.assertFalse(hasattr(self.p, 'capture'))

    def test_new_finger_during_pending_route_cancels_and_waits_for_lift(self):
        self.tick(); self.tick(.25)
        old=self.p.sender
        self.tick(.01, contacts=True)
        self.assertTrue(old.closed)
        self.assertFalse(self.p.armed)

    def test_aim_only_never_sends_input_and_confirm_sends_native_drag(self):
        self.arm()
        sender=self.p.sender
        self.p.touch('begin',1,self.now,300,300)
        self.p.touch('move',1,self.now,400,300)
        self.assertEqual(sender.events,[])
        self.p.touch('begin',2,self.now,1000,1000)
        self.p.touch('move',1,self.now,500,300)
        self.p.touch('end',2,self.now)
        self.assertEqual([e.kind for e in sender.events],['down','move','up'])
        self.assertEqual(sender.events[-1].position,self.p.gesture.point)

    def test_target_change_or_expired_marker_releases_and_requires_new_contacts(self):
        self.arm()
        self.p.touch('begin',1,self.now,300,300)
        self.p.touch('begin',2,self.now,600,600)
        old=self.p.sender
        self.snapshot=replace(self.snapshot,window=22,input_window=22)
        self.tick(.01)
        self.assertTrue(old.closed)
        self.assertFalse(self.p.armed)
        self.assertFalse(self.p.gesture.contacts)
        self.tick(2); self.tick(.25); self.tick(.01)
        self.assertTrue(self.p.armed)
        old=self.p.sender
        self.p.marker.valid=False
        self.tick(.01)
        self.assertTrue(old.closed)
        self.assertFalse(self.p.armed)

    def test_verified_child_change_preserves_a_held_native_contact(self):
        self.arm()
        self.p.touch('begin',1,self.now,300,300)
        self.p.touch('begin',2,self.now,600,600)
        old=self.p.sender
        self.snapshot=replace(self.snapshot,input_window=11)
        self.tick(.01)
        self.assertIs(self.p.sender,old)
        self.assertTrue(self.p.gesture.held)

    def test_manual_pause_stays_paused_and_stop_removes_marker(self):
        self.arm()
        self.p.toggle();self.tick(3)
        self.assertFalse(self.p.armed)
        self.assertFalse(self.p.auto_requested)
        marker=self.p.marker
        self.p.stop()
        self.assertTrue(marker.closed)

    def test_center_releases_sender_without_enabling_a_manually_paused_mode(self):
        self.arm(); old=self.p.sender
        self.p.center()
        self.assertTrue(old.closed)
        self.assertEqual(self.p.gesture.point,(.5,.5))
        self.p.pause();self.p.center();self.tick(5)
        self.assertFalse(self.p.armed)


if __name__ == '__main__': unittest.main()
