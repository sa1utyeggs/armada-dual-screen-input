from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.gamescope_target import InputUnavailable
from armada_dual_screen_input.gamescope_focus import FocusSnapshot, FocusState
from armada_dual_screen_input.touch_intent import TouchIntent
from armada_dual_screen_input.native_input import NativeTouchInput, TouchRouteWatch
from armada_dual_screen_input.native_touch import (VirtualTouchProbe, TouchSequence,
    ABS_MT_ID, BTN_TOUCH, EV_ABS, EV_KEY, EV_SYN, SYN_REPORT)


class Touch:
    def __init__(self, *, rotation, guard, max_contacts=2):
        assert rotation == 'normal'
        self.guard, self.node = guard, Path('/unused/event')
        self.events, self.held, self.closed = [], False, False
        self.contacts = set()
        self.max_contacts = max_contacts
    def contact(self, phase, tid, u, v):
        if not self.guard(): raise RuntimeError('guard changed')
        self.events.append(phase)
        if phase == 'up': self.contacts.discard(tid)
        else: self.contacts.add(tid)
        self.held = bool(self.contacts)
    def release_all(self):
        self.events.extend('up' for _ in self.contacts)
        self.contacts.clear()
        self.held = False
    def close(self):
        self.release_all()
        self.closed = True


class Route:
    def __init__(self, *args): self.valid, self.stopped = True, False
    def start(self): pass
    def current(self, now): return self.valid and not self.stopped
    def stop(self): self.stopped = True


class NativeInputTests(unittest.TestCase):
    def setUp(self):
        for symbol, cls in [('VirtualTouchProbe', Touch), ('TouchRouteWatch', Route)]:
            mock = patch('armada_dual_screen_input.native_input.' + symbol, cls)
            mock.start(); self.addCleanup(mock.stop)
        self.current = self.focused = True
        self.target = SimpleNamespace(is_current=lambda: self.current)
        self.expected = FocusSnapshot(10, 769, 769, 1920, 1080, 42, ':0', 10, True, 4)
        self.sender = NativeTouchInput(self.target, self.expected, focus_check=lambda: self.focused)
        self.addCleanup(self.sender.close)

    def test_creation_sends_no_input_and_waits_for_verified_route(self):
        self.assertEqual(self.sender.touch.events, [])
        self.sender.route.valid = False
        self.sender.poll()
        self.assertFalse(self.sender.ready)
        with self.assertRaises(InputUnavailable): self.sender.send(TouchIntent('down', (.5, .5)))
        self.assertEqual(self.sender.touch.events, [])

    def test_contact_sequence_uses_native_device(self):
        for kind in ('down', 'move', 'up'):
            self.sender.send(TouchIntent(kind, (.5, .5)))
        self.assertEqual(self.sender.touch.events, ['down', 'move', 'up'])
        self.assertEqual(self.sender.native_events_sent, 3)

    def test_wheel_is_never_emulated_in_native_mode(self):
        event = TouchIntent('wheel', (.5, .5), (0, 120))
        with self.assertRaises(ValueError): self.sender.send(event)
        self.assertEqual(self.sender.touch.events, [])

    def test_target_change_prevents_further_contact_and_close_lifts_once(self):
        self.sender.send(TouchIntent('down', (.5, .5)))
        self.focused = False
        with self.assertRaises(InputUnavailable): self.sender.send(TouchIntent('move', (.6, .6)))
        self.sender.close(); self.sender.close()
        self.assertEqual(self.sender.touch.events, ['down', 'up'])
        self.assertTrue(self.sender.route.stopped)

    def test_native_drag_survives_verified_child_change_but_not_new_surface(self):
        current = self.expected
        self.sender.focus_check = lambda: FocusState(current, 10).matches(self.expected, 10.1)
        self.sender.send(TouchIntent('down', (.4, .4)))
        current = replace(current, input_window=11)
        self.sender.send(TouchIntent('move', (.5, .5)))
        self.assertEqual(self.sender.touch.events, ['down', 'move'])
        current = replace(current, window=20)
        with self.assertRaises(InputUnavailable):
            self.sender.send(TouchIntent('move', (.6, .6)))
        self.sender.close()
        self.assertEqual(self.sender.touch.events, ['down', 'move', 'up'])

    def test_route_loss_after_ready_disables_input(self):
        self.sender.poll()
        self.sender.route.valid = False
        with self.assertRaises(InputUnavailable): self.sender.poll()
        self.assertEqual(self.sender.touch.events, [])

    def test_unsupported_touch_mode_is_rejected_before_device_creation(self):
        with patch('armada_dual_screen_input.native_input.VirtualTouchProbe') as create:
            with self.assertRaises(InputUnavailable):
                NativeTouchInput(self.target, replace(self.expected, touch_mode=0), focus_check=lambda: True)
            create.assert_not_called()

    def test_application_pointer_policy_is_respected_without_setting_override(self):
        sender = NativeTouchInput(self.target, replace(self.expected, touch_mode=1), focus_check=lambda: True)
        try:
            sender.send(TouchIntent('down', (.5, .5)))
            self.assertEqual(sender.touch.events, ['down'])
        finally:
            sender.close()

    def test_initialization_error_cleans_owned_device(self):
        touch = Touch(rotation='normal', guard=lambda: True)
        with patch('armada_dual_screen_input.native_input.VirtualTouchProbe', return_value=touch), \
             patch('armada_dual_screen_input.native_input.TouchRouteWatch', side_effect=OSError('node gone')):
            with self.assertRaises(OSError):
                NativeTouchInput(self.target, self.expected, focus_check=lambda: True)
        self.assertTrue(touch.closed)

    def test_close_error_still_stops_route_and_does_not_break_gui_cleanup(self):
        def broken_close(): raise OSError('touch device disappeared')
        self.sender.touch.close = broken_close
        self.sender.close()
        self.assertTrue(self.sender.route.stopped)
        self.assertIn('disappeared', self.sender.close_error)





    def test_route_checks_expire_and_stop_immediately(self):
        route = object.__new__(TouchRouteWatch)
        route._stop = threading.Event()
        route._state = (True, 10)
        route.same_node = lambda: True
        self.assertTrue(route.current(10.5))
        self.assertFalse(route.current(10.8))
        route.stop()
        self.assertFalse(route.current(10.1))

    def test_two_native_contacts_are_released_independently(self):
        self.sender.send(TouchIntent('down', (.4, .5), contact_id=1))
        self.sender.send(TouchIntent('down', (.6, .5), contact_id=2))
        self.sender.send(TouchIntent('move', (.4, .1), contact_id=1))
        self.sender.send(TouchIntent('up', (.4, .1), contact_id=1))
        self.assertEqual(self.sender.touch.events, ['down', 'down', 'move', 'up'])
        self.assertEqual(self.sender.active_contacts, {2})
        self.sender.send(TouchIntent('cancel', (.5, .5)))
        self.assertEqual(self.sender.touch.events, ['down', 'down', 'move', 'up', 'up'])
        self.assertFalse(self.sender.held)
        self.assertFalse(self.sender.active_contacts)

    def test_explicit_multitouch_capacity_reaches_native_device(self):
        sender = NativeTouchInput(self.target, self.expected, focus_check=lambda: True, max_contacts=10)
        try:
            self.assertEqual(sender.touch.max_contacts, 10)
            for tid in range(10):
                sender.send(TouchIntent('down', (.5, .5), contact_id=tid))
            self.assertEqual(len(sender.active_contacts), 10)
            sender.release_all()
            self.assertFalse(sender.active_contacts)
        finally:
            sender.close()

    def test_one_full_guard_per_contact_and_no_readiness_reuse(self):
        self.target.is_current = Mock(return_value=True)
        self.sender.focus_check = Mock(return_value=True)
        self.sender.route.current = Mock(return_value=True)
        for kind in ('down', 'move', 'up'):
            self.sender.send(TouchIntent(kind, (.4, .5)))
        for check in (self.target.is_current, self.sender.focus_check,
                      self.sender.route.current):
            self.assertEqual(check.call_count, 3)
        self.assertTrue(self.sender._became_ready)
        self.assertFalse(self.sender.active_contacts)

    def test_poll_checks_each_condition_once_and_ready_stays_fresh(self):
        self.target.is_current = Mock(return_value=True)
        self.sender.focus_check = Mock(return_value=True)
        self.sender.route.current = Mock(return_value=True)
        self.sender.poll()
        for check in (self.target.is_current, self.sender.focus_check,
                      self.sender.route.current):
            self.assertEqual(check.call_count, 1)
        self.sender.route.current.return_value = False
        self.assertFalse(self.sender.ready)
        with self.assertRaises(InputUnavailable):
            self.sender.poll()

    def test_target_focus_or_route_lost_after_poll_blocks_move_and_lifts(self):
        for failure in ('target', 'focus', 'route'):
            with self.subTest(failure=failure):
                self.current = self.focused = self.sender.route.valid = True
                self.sender.send(TouchIntent('down', (.4, .5)))
                self.sender.poll()
                self.current = failure != 'target'
                self.focused = failure != 'focus'
                self.sender.route.valid = failure != 'route'
                count = len(self.sender.touch.events)
                with self.assertRaises(InputUnavailable):
                    self.sender.send(TouchIntent('move', (.6, .5)))
                self.assertEqual(self.sender.touch.events[count:], ['up'])
                self.assertFalse(self.sender.held)
                self.assertFalse(self.sender.active_contacts)

    def test_cancel_lifts_contacts_even_when_target_is_unavailable(self):
        for tid in (1, 2):
            self.sender.send(TouchIntent('down', (.4, .5), contact_id=tid))
        self.current = self.focused = self.sender.route.valid = False
        self.sender.send(TouchIntent('cancel', (.5, .5)))
        self.assertEqual(self.sender.touch.events, ['down', 'down', 'up', 'up'])
        self.assertFalse(self.sender.held)
        self.assertFalse(self.sender.active_contacts)

    def test_closed_sender_rejects_contacts_and_unknown_up_writes_nothing(self):
        self.sender.send(TouchIntent('up', (.4, .5), contact_id=999))
        self.assertEqual(self.sender.touch.events, [])
        self.sender.close()
        with self.assertRaises(InputUnavailable):
            self.sender.send(TouchIntent('down', (.4, .5)))
        self.assertEqual(self.sender.touch.events, [])

    def real_encoder(self):
        # Exercise the actual final guard and Type B encoding, replacing only
        # the kernel write. Never construct a uinput device or load libevdev.
        probe = object.__new__(VirtualTouchProbe)
        probe.sequence = TouchSequence('normal', max_contacts=5)
        probe.guard = self.sender._guard
        probe.uinput = 1
        writes = []
        probe._write = lambda events: writes.extend(events)
        probe.close = probe.release_all
        self.sender.touch = probe
        return writes

    def test_real_encoder_keeps_five_independent_reports_and_one_guard_each(self):
        writes = self.real_encoder()
        for tid in range(5):
            self.sender.send(TouchIntent('down', (.1+tid*.1, .3), contact_id=tid))
        writes.clear()
        self.target.is_current = Mock(return_value=True)
        for tid in range(5):
            self.sender.send(TouchIntent('move', (.1+tid*.1, .4), contact_id=tid))
        self.assertEqual(self.target.is_current.call_count, 5)
        self.assertEqual(sum(e == (EV_SYN, SYN_REPORT, 0) for e in writes), 5)
        self.assertEqual(len(self.sender.touch.sequence.contacts), 5)

    def test_real_encoder_final_guard_denies_late_change_and_releases_once(self):
        writes = self.real_encoder()
        self.sender.send(TouchIntent('down', (.4, .5)))
        self.sender.poll()
        writes.clear()
        self.focused = False
        with self.assertRaises(InputUnavailable):
            self.sender.send(TouchIntent('move', (.6, .5)))
        self.assertEqual(sum(e == (EV_ABS, ABS_MT_ID, -1) for e in writes), 1)
        self.assertEqual(sum(e == (EV_KEY, BTN_TOUCH, 0) for e in writes), 1)
        self.assertFalse(self.sender.touch.sequence.contacts)
        self.assertFalse(self.sender.active_contacts)
