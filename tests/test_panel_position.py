from dataclasses import replace
from types import SimpleNamespace
import unittest

from armada_dual_screen_input.gamescope_target import InputUnavailable
from armada_dual_screen_input.gamescope_focus import FocusSnapshot, FocusState
from armada_dual_screen_input.panel_position import PanelPosition
from armada_dual_screen_input.marker_target import MarkerTarget
from armada_dual_screen_input.touchscreen_selector import PAD
from armada_dual_screen_input.marker_colors import DEFAULT_COLORS, MarkerColors


class Marker:
    size = (1920, 1080)
    refresh_millihz = 119930
    def __init__(self, *, target, frame_rate='auto', colors=DEFAULT_COLORS):
        self.frame_rate = frame_rate
        self.colors = colors
        self.target=MarkerTarget.from_focus(target)
        self.window=999
        self.valid=True; self.closed=False; self.updates=[]; self.restores=0; self.motion=[]
    def matches_focus(self, focus): return self.target.matches_focus(focus)
    def current(self, now): return self.valid and not self.closed
    def update(self, point, pressed=False, *, motion=None):
        self.updates.append((point, pressed)); self.motion.append(motion)
    def update_contacts(self, contacts, *, motion=None):
        self.updates.append(tuple(contacts)); self.motion.append(motion)
    def poll(self):
        if self.closed: raise InputUnavailable('marker gone')
    def restore(self): self.restores+=1
    def close(self): self.closed=True
    def wait(self): pass
    def reaped(self): return self.closed


class Sender:
    ready=True
    def __init__(self, *args, focus_check, max_contacts=2):
        self.events=[]; self.closed=False; self.focus_check=focus_check; self.max_contacts=max_contacts
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

    def test_selected_frame_rate_reaches_marker_without_changing_native_input(self):
        self.p.frame_rate='30'
        self.arm()
        self.assertEqual(self.p.marker.frame_rate,'30')
        self.assertEqual(self.p.monitor_millihz,119930)
        self.assertFalse(self.p.sender.events)
        self.p.stop()
        self.assertEqual(self.p.monitor_millihz,119930)

    def test_saved_colors_reach_recreated_marker_in_both_modes_without_input(self):
        self.p.marker_colors = MarkerColors('#FFFFFF', '#58E38B')
        for mode in ('position', 'direct'):
            self.p.set_touch_mode(mode)
            self.arm()
            self.assertEqual(self.p.marker.colors, self.p.marker_colors)
            self.assertFalse(self.p.sender.events)
            self.p.stop()
            self.p.start()

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
        self.p.touch('move',1,self.now,424,395.6)
        self.assertEqual(sender.events,[])
        self.assertAlmostEqual(self.p.gesture.point[0],.7)
        self.assertAlmostEqual(self.p.gesture.point[1],.7)
        self.p.touch('begin',2,self.now,1000,1000)
        self.p.touch('move',1,self.now,548,491.2)
        self.p.touch('end',2,self.now)
        self.assertEqual([e.kind for e in sender.events],['down','move','up'])
        self.assertEqual(sender.events[-1].position,self.p.gesture.point)
        self.assertAlmostEqual(sender.events[-1].position[0],.9)
        self.assertAlmostEqual(sender.events[-1].position[1],.9)

    def test_visual_motion_is_separate_and_native_down_move_up_remain_immediate(self):
        self.arm()
        self.p.touch('begin',11,self.now,300,300)
        self.assertTrue(self.p.marker.motion[-1]['snap'])
        self.assertEqual(self.p.marker.motion[-1]['ids'],(11,))
        self.p.touch('move',11,self.now,310,300)
        self.assertFalse(self.p.marker.motion[-1]['snap'])
        self.assertTrue(self.p.marker.motion[-1]['active'])
        self.assertEqual(self.p.sender.events,[])
        self.p.touch('begin',22,self.now,600,600)
        self.assertEqual([e.kind for e in self.p.sender.events],['down'])
        self.assertEqual(self.p.sender.events[-1].position,self.p.gesture.point)
        self.assertTrue(self.p.marker.motion[-1]['snap'])
        self.p.touch('move',11,self.now,320,300)
        self.assertEqual([e.kind for e in self.p.sender.events],['down','move'])
        self.assertEqual(self.p.sender.events[-1].position,self.p.gesture.point)
        self.assertFalse(self.p.marker.motion[-1]['snap'])
        self.p.touch('end',22,self.now)
        self.assertEqual([e.kind for e in self.p.sender.events],['down','move','up'])
        self.assertTrue(self.p.marker.motion[-1]['snap'])
        self.p.touch('end',11,self.now)
        self.assertFalse(self.p.marker.motion[-1]['active'])
        self.assertTrue(self.p.marker.motion[-1]['snap'])

    def test_direct_visual_contacts_keep_native_ids_and_clear_on_cancel(self):
        self.p.set_touch_mode('direct')
        self.arm()
        self.p.touch('begin',11,self.now,300,300)
        self.p.touch('begin',22,self.now,600,600)
        self.assertEqual(self.p.marker.motion[-1]['ids'],(11,22))
        self.p.touch('move',22,self.now,620,600)
        self.assertFalse(self.p.marker.motion[-1]['snap'])
        self.assertEqual(self.p.sender.events[-1].contact_id,22)
        self.p.touch('end',11,self.now)
        self.assertEqual(self.p.marker.motion[-1]['ids'],(22,))
        self.assertTrue(self.p.marker.motion[-1]['snap'])
        self.p.touch('cancel',22,self.now)
        self.assertEqual(self.p.marker.updates[-1],())
        self.assertEqual(self.p.marker.motion[-1]['ids'],())
        self.assertFalse(self.p.marker.motion[-1]['active'])
        self.assertEqual([e.kind for e in self.p.sender.events],['down','down','move','up','up'])

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

    def test_foreground_return_skips_fault_backoff_but_waits_for_stable_focus(self):
        self.arm()
        self.p.touch('begin',1,self.now,300,300)
        self.p.touch('begin',2,self.now,600,600)
        old=self.p.sender
        self.snapshot=replace(self.snapshot,window=22,input_window=22)
        self.tick(.01)
        lost_at=self.now
        self.assertTrue(old.closed)
        self.assertFalse(self.p.gesture.contacts)
        self.tick(.01);self.tick(.18)
        self.assertIsNone(self.p.sender)
        self.tick(.03);self.tick(.01)
        self.assertTrue(self.p.armed)
        self.assertLess(self.now-lost_at,.35)
        self.assertEqual(self.p.sender.events,[])
        self.assertFalse(self.p.gesture.held)

    def test_lost_marker_still_uses_fault_backoff(self):
        self.arm()
        old=self.p.marker
        old.valid=False
        self.tick(.01)
        self.assertTrue(old.closed)
        self.tick(1)
        self.assertIsNone(self.p.marker)
        self.assertIsNone(self.p.sender)
        self.tick(.51);self.tick(.25);self.tick(.01)
        self.assertTrue(self.p.armed)

    def test_foreground_change_retires_decoration_and_rebinds_after_stability(self):
        self.arm()
        marker=self.p.marker
        self.snapshot=replace(self.snapshot,window=22,input_window=22,app_id=42,
                              graphics_app_id=42,surface_display=':1')
        self.tick(.01)
        self.assertTrue(marker.closed)
        self.assertIsNone(self.p.marker)
        self.assertFalse(self.p.armed)
        self.tick(.01);self.tick(.21);self.tick(.01)
        self.assertTrue(self.p.armed)
        self.assertTrue(self.p.marker.matches_focus(self.snapshot))
        self.assertEqual(self.p.sender.events,[])

    def test_own_decoration_focus_is_not_adopted_as_an_application(self):
        self.arm()
        self.snapshot=replace(self.snapshot,window=self.p.marker.window,input_window=999)
        self.tick(.01)
        self.assertFalse(self.p.armed)
        self.assertIsNone(self.p.marker)
        self.tick(.01)
        self.assertIsNone(self.p.marker)
        self.assertIsNone(self.p.sender)

    def test_completed_retired_markers_do_not_accumulate_across_window_switches(self):
        self.arm()
        for window in range(20,30):
            self.snapshot=replace(self.snapshot,window=window,input_window=window)
            self.tick(.01)
            self.assertLessEqual(len(self.p._retired),1)
            self.tick(.01);self.tick(.21);self.tick(.01)
            self.assertTrue(self.p.armed)
            self.assertEqual(self.p._retired,[])

    def test_route_failure_with_healthy_marker_still_uses_fault_backoff(self):
        self.arm()
        marker=self.p.marker
        old=self.p.sender
        def fail(): raise InputUnavailable('virtual touchscreen route changed')
        old.poll=fail
        self.tick(.01)
        self.assertTrue(old.closed)
        self.tick(1)
        self.assertIs(self.p.marker,marker)
        self.assertIsNone(self.p.sender)
        self.tick(.51);self.tick(.25);self.tick(.01)
        self.assertTrue(self.p.armed)

    def test_quick_access_return_restores_marker_once_after_lift_and_stable_focus(self):
        self.arm()
        marker=self.p.marker
        self.assertEqual(marker.restores,1)
        self.p.touch('begin',1,self.now,300,300)
        self.p.touch('begin',2,self.now,600,600)
        old=self.p.sender
        game=replace(self.snapshot,app_id=42,graphics_app_id=42,surface_display=':1')
        self.snapshot=replace(game,app_id=769)
        self.tick(.01)
        self.assertTrue(old.closed)
        self.assertIsNone(self.p.marker)
        self.assertTrue(marker.closed)
        self.tick(2)
        self.assertFalse(self.p.armed)
        self.assertEqual(marker.restores,1)
        self.snapshot=game
        self.tick(.25,contacts=True)
        self.assertFalse(self.p.armed)
        self.assertEqual(marker.restores,1)
        self.tick();self.tick(.21);self.tick(.01)
        self.assertTrue(self.p.armed)
        current_marker = self.p.marker
        self.assertIsNot(current_marker, marker)
        self.assertEqual(current_marker.restores,1)
        self.assertTrue(current_marker.matches_focus(game))
        self.assertFalse(self.p.gesture.held)
        for _ in range(5): self.tick(.1)
        self.assertEqual(current_marker.restores,1)

    def test_new_aim_after_first_finger_lifts_does_not_require_orphan_end(self):
        self.arm()
        for phase,tid,x,y in [('begin',1,300,300),('begin',2,600,600),
                              ('end',1,0,0),('begin',3,300,300),('move',3,424,300)]:
            self.p.touch(phase,tid,self.now,x,y)
        self.assertTrue(self.p.armed)
        self.assertAlmostEqual(self.p.gesture.point[0],.7)
        self.assertEqual([e.kind for e in self.p.sender.events],['down','up'])

    def test_manual_pause_stays_paused_and_stop_removes_marker(self):
        self.arm()
        self.p.toggle();self.tick(3)
        self.assertFalse(self.p.armed)
        self.assertFalse(self.p.auto_requested)
        marker=self.p.marker
        self.p.stop()
        self.assertTrue(marker.closed)

    def test_switching_to_direct_releases_old_contact_and_waits_for_all_lifts(self):
        self.arm()
        self.p.touch('begin', 1, self.now, 300, 300)
        self.p.touch('begin', 2, self.now, 600, 600)
        old = self.p.sender
        self.p.set_touch_mode('direct')
        self.assertTrue(old.closed)
        self.assertFalse(self.p.armed)
        self.assertTrue(self.p.auto_requested)
        self.tick(.5, contacts=True)
        self.assertIsNone(self.p.sender)
        self.tick(); self.tick(.25); self.tick(.01)
        self.assertTrue(self.p.armed)
        self.assertEqual(self.p.sender.max_contacts, 10)
        self.assertEqual(self.p.sender.events, [])

    def test_direct_mode_sends_independent_contacts_and_markers(self):
        self.p.set_touch_mode('direct')
        self.arm()
        self.p.touch('begin', 1, self.now, 310, 363)
        self.p.touch('begin', 2, self.now, 930, 841)
        self.p.touch('move', 2, self.now, 620, 602)
        self.p.touch('end', 1, self.now)
        self.assertEqual([(e.kind, e.contact_id) for e in self.p.sender.events],
                         [('down', 1), ('down', 2), ('move', 2), ('up', 1)])
        self.assertEqual(self.p.marker.updates[-1], ((.5, .5, True),))
        self.p.touch('end', 2, self.now)
        self.assertEqual(self.p.marker.updates[-1], ())

    def test_header_is_excluded_but_dropdown_needs_no_extra_native_input_row(self):
        panel = PanelPosition(pad=PAD)
        self.addCleanup(panel.stop)
        self.assertEqual(panel.position_gesture.pad, PAD)
        self.assertEqual(panel.direct_gesture.pad, PAD)
        for mode in ('position', 'direct'):
            panel.set_touch_mode(mode)
            self.assertEqual(panel.gesture.begin(1, 310, 30, self.now), ())
            self.assertEqual(panel.gesture.move(1, 620, 660, self.now), ())
            panel.gesture.end(1, self.now)
        down, = panel.direct_gesture.begin(2, 310, 363, self.now)
        self.assertEqual(down.position, (.25, .25))
        move, = panel.direct_gesture.move(2, 1240, 1080, self.now)
        self.assertEqual(move.position, (1., 1.))

    def test_direct_target_change_releases_every_contact_and_clears_rings(self):
        self.p.set_touch_mode('direct'); self.arm()
        self.p.touch('begin', 1, self.now, 310, 363)
        self.p.touch('begin', 2, self.now, 930, 841)
        old = self.p.sender
        marker = self.p.marker
        self.snapshot=replace(self.snapshot, window=22, input_window=22)
        self.tick(.01)
        self.assertTrue(old.closed)
        self.assertFalse(self.p.direct_gesture.contacts)
        self.assertEqual(marker.updates[-1], ())
        self.assertTrue(marker.closed)

    def test_return_to_position_keeps_previous_aim_without_reusing_old_touch(self):
        self.p.position_gesture.point = (.2, .8)
        self.p.set_touch_mode('direct'); self.arm()
        self.p.touch('begin', 1, self.now, 310, 363)
        old = self.p.sender
        self.p.set_touch_mode('position')
        self.assertTrue(old.closed)
        self.assertEqual(self.p.gesture.point, (.2, .8))
        self.assertFalse(self.p.gesture.contacts)
        self.assertTrue(self.p.auto_requested)

    def test_center_releases_sender_without_enabling_a_manually_paused_mode(self):
        self.arm(); old=self.p.sender
        self.p.center()
        self.assertTrue(old.closed)
        self.assertEqual(self.p.gesture.point,(.5,.5))
        self.p.pause();self.p.center();self.tick(5)
        self.assertFalse(self.p.armed)


if __name__ == '__main__': unittest.main()
