from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from gamescope_target import InputUnavailable
from gamescope_focus import FocusSnapshot, FocusState
from touch_intent import TouchIntent
from native_input import NativeTouchInput, TouchRouteWatch


class Touch:
    def __init__(self, *, rotation, guard):
        assert rotation == 'normal'
        self.guard, self.node = guard, Path('/unused/event')
        self.events, self.held, self.closed = [], False, False
        self.contacts = set()
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
            mock = patch('native_input.' + symbol, cls)
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
        with patch('native_input.VirtualTouchProbe') as create:
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
        with patch('native_input.VirtualTouchProbe', return_value=touch), \
             patch('native_input.TouchRouteWatch', side_effect=OSError('node gone')):
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
