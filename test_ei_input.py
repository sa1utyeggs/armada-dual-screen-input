from collections import deque
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ei_input import GamescopeTarget, InputUnavailable, LibEIInput
from mirrored_touch import TouchIntent


class FakeEI:
    def __init__(self):
        self.queue = deque()
        self.events = {}
        self.calls = []
        self.next_event = 100
        self.capabilities = {1, 2, 16, 32}
        self.regions = {10: (100, 200, 1000, 500)}

    def add(self, kind, device=10):
        self.next_event += 1
        self.events[self.next_event] = (kind, device)
        self.queue.append(self.next_event)

    def ei_new_sender(self, data): return 1
    def ei_setup_backend_socket(self, context, path): return 0
    def ei_get_fd(self, context): return 42
    def ei_dispatch(self, context): pass
    def ei_get_event(self, context): return self.queue.popleft() if self.queue else None
    def ei_event_get_type(self, event): return self.events[event][0]
    def ei_event_get_device(self, event): return self.events[event][1]
    def ei_event_get_seat(self, event): return 20
    def ei_seat_has_capability(self, seat, cap): return cap in self.capabilities
    def ei_device_has_capability(self, device, cap): return cap in self.capabilities
    def ei_device_get_region(self, device, index): return device if index == 0 else None
    def ei_region_get_x(self, region): return self.regions[region][0]
    def ei_region_get_y(self, region): return self.regions[region][1]
    def ei_region_get_width(self, region): return self.regions[region][2]
    def ei_region_get_height(self, region): return self.regions[region][3]
    def ei_now(self, context): return 1000000

    def ei_device_ref(self, device):
        return device

    def __getattr__(self, name):
        if name.startswith('ei_'):
            def record(*args):
                self.calls.append((name, args))
            return record
        raise AttributeError(name)

    def input_calls(self):
        return [(name, args) for name, args in self.calls if name in (
            'ei_device_start_emulating', 'ei_device_pointer_motion_absolute',
            'ei_device_pointer_motion',
            'ei_device_button_button', 'ei_device_scroll_delta', 'ei_device_frame')]


class EIInputTests(unittest.TestCase):
    def setUp(self):
        self.current = True
        self.target = SimpleNamespace(eis_path=Path('/unused/socket'),
                                      is_current=lambda: self.current)
        self.api = FakeEI()
        self.sender = LibEIInput(self.target, (1920, 1080), api=self.api)
        self.addCleanup(self.sender.close)

    def ready(self):
        for kind in (1, 3, 5, 8): self.api.add(kind)
        self.sender.poll()

    def test_setup_and_capability_handshake_send_no_input(self):
        self.assertFalse(self.sender.ready)
        self.ready()
        self.assertTrue(self.sender.ready)
        self.assertEqual(self.api.input_calls(), [])

    def test_native_backend_rejects_different_compositor_before_fd_handoff(self):
        with patch('ei_input.load_libei', return_value=self.api), \
                patch('ei_input.socket.socket'), \
                patch('ei_input.same_user_peer_pid', return_value=123):
            with self.assertRaises(InputUnavailable):
                LibEIInput(self.target, (1920, 1080), x_server_pid=456)
        self.assertFalse(any(name == 'ei_setup_backend_fd' for name, _ in self.api.calls))
        self.assertEqual(self.api.input_calls(), [])

    def test_gamescope_uses_surface_pixels_instead_of_placeholder_region(self):
        self.ready()
        self.sender.send(TouchIntent('move', (1, 0.5)))
        call = next(args for name, args in self.api.calls
                    if name == 'ei_device_pointer_motion_absolute')
        self.assertEqual(call, (10, 1919, 539.5))

    def test_foreground_change_prevents_new_input_but_close_releases_old_button(self):
        self.ready()
        self.sender.send(TouchIntent('down', (0.5, 0.5)))
        self.sender.focus_check = lambda: False
        count = len(self.api.input_calls())
        with self.assertRaises(InputUnavailable):
            self.sender.send(TouchIntent('move', (0.1, 0.1)))
        self.assertEqual(len(self.api.input_calls()), count)
        self.sender.close()
        buttons = [args for name, args in self.api.calls if name == 'ei_device_button_button']
        self.assertEqual(buttons[-1], (10, 0x110, False))

    def test_ambiguous_device_releases_original_button_on_close(self):
        self.ready()
        self.sender.send(TouchIntent('down', (0.5, 0.5)))
        self.api.regions[11] = (0, 0, 1000, 1000)
        self.api.add(5, 11)
        self.api.add(8, 11)
        with self.assertRaises(InputUnavailable): self.sender.poll()
        self.sender.close()
        buttons = [args for name, args in self.api.calls if name == 'ei_device_button_button']
        self.assertEqual(buttons[-1], (10, 0x110, False))

    def test_press_move_release_have_separate_frames_and_balanced_buttons(self):
        self.ready()
        for kind in ('down', 'move', 'up'):
            self.sender.send(TouchIntent(kind, (0.5, 0.5)))
        calls = self.api.input_calls()
        buttons = [args[-1] for name, args in calls if name == 'ei_device_button_button']
        self.assertEqual(buttons, [True, False])
        self.assertEqual(sum(name == 'ei_device_frame' for name, _ in calls), 3)
        self.assertFalse(self.sender.held)

    def test_tiny_wheel_travel_is_preserved_as_continuous_notch_fractions(self):
        self.ready()
        for _ in range(3): self.sender.send(TouchIntent('wheel', (0.5, 0.5), (0.4, 0.4)))
        wheels = [args for name, args in self.api.calls if name == 'ei_device_scroll_delta']
        self.assertEqual(len(wheels), 3)
        self.assertAlmostEqual(sum(args[1] for args in wheels), 1.2 / 120)
        self.assertAlmostEqual(sum(args[2] for args in wheels), -1.2 / 120)
        self.assertFalse(any(name == 'ei_device_scroll_discrete' for name, _ in self.api.calls))

    def test_reversing_continuous_wheel_does_not_retain_old_direction_travel(self):
        self.ready()
        for delta in (0.4, 0.4, -0.6, -0.6):
            self.sender.send(TouchIntent('wheel', (0.5, 0.5), (delta, 0)))
        wheels = [args for name, args in self.api.calls if name == 'ei_device_scroll_delta']
        self.assertEqual([args[1] for args in wheels], [delta / 120 for delta in (0.4, 0.4, -0.6, -0.6)])

    def test_scroll_wakes_hidden_pointer_once_then_restores_exact_centroid(self):
        self.ready()
        self.sender.send(TouchIntent('wheel', (0.5, 0.5), (0, -12)))
        self.sender.send(TouchIntent('wheel', (0.5, 0.5), (0, -12)))
        motions = [args for name, args in self.api.calls if name == 'ei_device_pointer_motion']
        self.assertEqual(motions, [(10, 1.0, 0.0), (10, -1.0, 0.0)])
        calls = self.api.input_calls()
        absolute = next(i for i, (name, _) in enumerate(calls)
                        if name == 'ei_device_pointer_motion_absolute')
        wheel = next(i for i, (name, _) in enumerate(calls) if name == 'ei_device_scroll_delta')
        self.assertLess(absolute, wheel)
        self.assertEqual(calls[absolute][1], (10, 959.5, 539.5))
        self.sender.release_all()
        self.api.calls.clear()
        self.sender.send(TouchIntent('wheel', (0.5, 0.5), (0, -12)))
        self.assertEqual(sum(name == 'ei_device_pointer_motion' for name, _ in self.api.calls), 2)

    def test_invalid_intent_cannot_move_or_press_the_pointer(self):
        self.ready()
        for intent in (TouchIntent('move', (2, 0)), TouchIntent('other', (0, 0)),
                       TouchIntent('wheel', (0.5, 0.5), (float('nan'), 0))):
            with self.assertRaises(ValueError): self.sender.send(intent)
        self.assertEqual(self.api.input_calls(), [])

    def test_target_change_prevents_further_input(self):
        self.ready()
        self.current = False
        with self.assertRaises(InputUnavailable):
            self.sender.send(TouchIntent('down', (0.5, 0.5)))
        self.assertEqual(self.api.input_calls(), [])

    def test_pause_closes_without_sending_events_to_the_paused_device(self):
        self.ready()
        self.sender.send(TouchIntent('down', (0.5, 0.5)))
        self.api.add(7)
        with self.assertRaises(InputUnavailable): self.sender.poll()
        self.assertFalse(self.sender.ready)
        count = len(self.api.input_calls())
        self.sender.close()
        self.assertEqual(len(self.api.input_calls()), count)

    def test_missing_capability_and_ambiguous_devices_cannot_be_selected(self):
        self.api.capabilities.remove(16)
        self.ready()
        self.assertFalse(self.sender.ready)
        self.api.capabilities.add(16)
        self.api.add(6)
        self.sender.poll()
        for device in (10, 11):
            self.api.regions[device] = (0, 0, 1000, 1000)
            self.api.add(5, device)
            self.api.add(8, device)
        self.sender.poll()
        self.assertFalse(self.sender.ready)

    def test_close_releases_held_button_before_stopping_emulation(self):
        self.ready()
        self.sender.send(TouchIntent('down', (0.5, 0.5)))
        self.api.calls.clear()
        self.sender.close()
        names = [name for name, _ in self.api.calls]
        self.assertLess(names.index('ei_device_button_button'), names.index('ei_device_stop_emulating'))
        self.assertEqual(self.api.calls[0][1][-1], False)
        self.assertEqual(names[-1], 'ei_unref')
        count = len(self.api.calls)
        self.sender.close()
        self.assertEqual(len(self.api.calls), count)

    def test_scroll_and_duplicate_press_during_drag_are_rejected(self):
        self.ready()
        self.sender.send(TouchIntent('down', (0.5, 0.5)))
        count = len(self.api.input_calls())
        for intent in (TouchIntent('down', (0.5, 0.5)),
                       TouchIntent('wheel', (0.5, 0.5), (1, 1))):
            with self.assertRaises(ValueError): self.sender.send(intent)
        self.assertEqual(len(self.api.input_calls()), count)


class TargetIdentityTests(unittest.TestCase):
    def test_primary_alias_retarget_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory).resolve()
            sockets = []
            try:
                for name in ('first', 'first-ei', 'second', 'second-ei'):
                    sock = socket.socket(socket.AF_UNIX)
                    sock.bind(str(runtime / name))
                    sockets.append(sock)
                alias = runtime / 'gamescope-primary'
                alias.symlink_to('first')
                target = GamescopeTarget.resolve(runtime)
                self.assertTrue(target.is_current())
                alias.unlink()
                alias.symlink_to('second')
                self.assertFalse(target.is_current())
            finally:
                for sock in sockets: sock.close()


if __name__ == '__main__':
    unittest.main()
