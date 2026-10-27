"""Marker restoration uses bounded IPC and never starts an X11 window here."""
import json
import os
from dataclasses import replace
import socket
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from armada_dual_screen_input.marker_overlay import MarkerOverlay
from armada_dual_screen_input.gamescope_focus import FocusSnapshot
from armada_dual_screen_input.gamescope_target import InputUnavailable
from armada_dual_screen_input.marker_colors import MarkerColors


class Dispatch:
    def __init__(self):
        self.callbacks = {}
        self.next_id = 0

    def add(self, callback):
        self.next_id += 1
        self.callbacks[self.next_id] = callback
        return self.next_id

    def cancel(self, source):
        self.callbacks.pop(source, None)

    def run(self):
        callbacks, self.callbacks = self.callbacks, {}
        for callback in callbacks.values():
            assert callback() is False


class MarkerOverlayTests(unittest.TestCase):
    def setUp(self):
        self.peer=None
        self.parent_environment = dict(os.environ)
        self.expected = FocusSnapshot(10,42,42,1920,1080,42,':1',10,True,1)
        self.dispatch = Dispatch()

        def spawn(*args, **kwargs):
            self.worker_environment = kwargs['env']
            self.worker_arguments = args[0]
            self.peer=socket.fromfd(kwargs['pass_fds'][0],socket.AF_UNIX,socket.SOCK_DGRAM)
            self.peer.setblocking(False)
            return SimpleNamespace(poll=lambda:None,wait=lambda **kwargs:0)

        with patch('armada_dual_screen_input.marker_overlay.subprocess.Popen',side_effect=spawn):
            self.marker=MarkerOverlay(target=self.expected, schedule=self.dispatch.add,
                                      cancel=self.dispatch.cancel)
        self.addCleanup(self.peer.close)
        self.addCleanup(self.marker.wait)
        self.addCleanup(self.marker.close)

    def packets(self):
        result=[]
        while True:
            try: result.append(json.loads(self.peer.recv(4096)))
            except BlockingIOError: return result

    def ready(self):
        self.peer.send(b'{"window":200,"ready":true,"size":[1920,1080]}')
        self.marker.poll()
        self.packets()

    def test_gl_composition_is_scoped_to_marker_child_only(self):
        self.assertEqual(dict(os.environ), self.parent_environment)
        self.assertEqual(self.worker_environment['GDK_GL'], 'always')
        self.assertEqual(self.worker_environment['vblank_mode'], '0')
        self.assertEqual(self.worker_environment['GDK_BACKEND'], 'x11')
        self.assertEqual(self.worker_environment['DISPLAY'], ':1')
        self.assertEqual(self.worker_arguments[self.worker_arguments.index('--frame-rate')+1], 'auto')
        target = self.worker_arguments[self.worker_arguments.index('--target')+1]
        self.assertEqual(json.loads(target)['window'], self.expected.window)
        self.assertEqual(json.loads(target)['app_id'], self.expected.app_id)

    def test_marker_binding_rejects_other_windows_displays_and_apps(self):
        self.assertTrue(self.marker.matches_focus(replace(self.expected,input_window=11)))
        for change in ({'window':20}, {'surface_display':':0'}, {'app_id':769},
                       {'width':1280}, {'height':720}, {'server_pid':43},
                       {'input_in_surface':False}):
            self.assertFalse(self.marker.matches_focus(replace(self.expected,**change)))

    def test_color_configuration_reaches_only_the_marker_child_arguments(self):
        with patch('armada_dual_screen_input.marker_overlay.subprocess.Popen') as spawn:
            spawn.return_value.poll.return_value=None
            marker=MarkerOverlay(target=self.expected,schedule=self.dispatch.add,cancel=self.dispatch.cancel,
                colors=MarkerColors('#FFFFFF','#58e38b'))
            try:
                args=spawn.call_args.args[0]
                self.assertEqual(args[args.index('--idle-color')+1],'#FFFFFF')
                self.assertEqual(args[args.index('--pressed-color')+1],'#58E38B')
                self.assertEqual(dict(os.environ),self.parent_environment)
            finally:
                marker.close();marker.wait()

    def test_position_style_is_worker_configuration_not_per_contact_data(self):
        for style in ('glove', 'pixel_hand', 'reticle'):
            with self.subTest(style=style), \
                 patch('armada_dual_screen_input.marker_overlay.subprocess.Popen') as spawn:
                spawn.return_value.poll.return_value = None
                marker = MarkerOverlay(target=self.expected, schedule=self.dispatch.add,
                                       cancel=self.dispatch.cancel, position_style=style)
                try:
                    args = spawn.call_args.args[0]
                    self.assertEqual(args[args.index('--position-style')+1], style)
                    self.assertEqual(dict(os.environ), self.parent_environment)
                    marker.update((.2, .4), True, motion=self.motion())
                    self.assertEqual(marker.pending['contacts'], ((.2, .4, True),))
                    self.assertNotIn('style', marker.pending)
                    self.assertNotIn('image', marker.pending)
                finally:
                    marker.close(); marker.wait()

    def test_invalid_position_style_is_rejected_before_opening_a_worker(self):
        for style in (None, True, 1, {}, [], 'hand', 'GLOVE'):
            with self.subTest(style=style), \
                 patch('armada_dual_screen_input.marker_overlay.subprocess.Popen') as spawn:
                with self.assertRaises(ValueError):
                    MarkerOverlay(target=self.expected, schedule=self.dispatch.add,
                                  cancel=self.dispatch.cancel, position_style=style)
                spawn.assert_not_called()

    def test_own_window_is_identified_separately_from_the_game(self):
        self.ready()
        self.assertTrue(self.marker.owns_focus(replace(self.expected,window=200)))
        self.assertFalse(self.marker.owns_focus(replace(self.expected,window=200,surface_display=':0')))
        self.assertFalse(self.marker.owns_focus(self.expected))

    def test_ready_without_window_or_replaced_window_is_rejected(self):
        self.peer.send(b'{"ready":true,"size":[1920,1080]}')
        with self.assertRaises(InputUnavailable): self.marker.poll()
        self.ready()
        self.peer.send(b'{"window":201}')
        with self.assertRaises(InputUnavailable): self.marker.poll()

    def test_monitor_refresh_is_reported_and_invalid_values_fail_closed(self):
        self.ready()
        self.peer.send(b'{"alive":true,"refresh_millihz":119930}')
        self.marker.poll()
        self.assertEqual(self.marker.refresh_millihz,119930)
        self.peer.send(b'{"alive":true,"refresh_millihz":true}')
        with self.assertRaises(InputUnavailable):self.marker.poll()

    def test_repeated_restore_requests_coalesce_without_changing_position(self):
        self.ready()
        self.marker.update((.7,.3),False)
        for _ in range(10): self.marker.restore()
        self.marker.poll()
        self.assertEqual(self.packets(),[[.7,.3,False],{'restore':True}])
        self.marker.poll()
        self.assertEqual(self.packets(),[])

    def test_restore_waits_for_worker_readiness(self):
        self.marker.restore()
        self.marker.poll()
        self.assertEqual(self.packets(),[])
        self.peer.send(b'{"window":200,"ready":true,"size":[1920,1080]}')
        self.marker.poll()
        self.assertEqual(self.packets(),[[.5,.5,False],{'restore':True}])

    def test_direct_updates_coalesce_and_empty_payload_clears_contacts(self):
        self.ready()
        self.marker.update_contacts(((.2,.3,True),(.7,.8,True)))
        self.marker.update_contacts(((.4,.3,True),(.6,.8,True)))
        self.marker.poll()
        self.assertEqual(self.packets(),[{'contacts':[[.4,.3,True],[.6,.8,True]]}])
        self.marker.update_contacts(())
        self.marker.poll()
        self.assertEqual(self.packets(),[{'contacts':[]}])

    def test_restore_survives_temporary_ipc_backpressure(self):
        self.ready()
        self.marker.restore()
        original=self.marker.socket
        self.marker.socket=SimpleNamespace(recv=original.recv,
            send=lambda _:(_ for _ in ()).throw(BlockingIOError()))
        try:
            self.marker.poll()
            self.assertTrue(self.marker.restore_pending)
        finally:
            self.marker.socket=original
        self.marker.poll()
        self.assertEqual(self.packets(),[{'restore':True}])

    def test_movement_dispatches_latest_batch_without_waiting_for_health_poll(self):
        self.ready()
        checked_at = self.marker.checked_at
        for n in range(100):
            self.marker.update((n/100, .3), False)
        self.assertEqual(len(self.dispatch.callbacks), 1)
        self.assertEqual(self.packets(), [])
        self.dispatch.run()
        self.assertEqual(self.packets(), [[.99, .3, False]])
        # Sending our own coordinates is not evidence the worker is alive.
        self.assertEqual(self.marker.checked_at, checked_at)
        self.marker.update((.99, .3), False)
        self.assertFalse(self.dispatch.callbacks)

    def test_direct_contacts_dispatch_without_poll_and_keep_release_state(self):
        self.ready()
        self.marker.update_contacts(((.2,.3,True),(.7,.8,True)))
        self.marker.update_contacts(((.4,.3,True),))
        self.dispatch.run()
        self.assertEqual(self.packets(), [{'contacts':[[.4,.3,True]]}])
        self.marker.update_contacts(())
        self.dispatch.run()
        self.assertEqual(self.packets(), [{'contacts':[]}])

    def test_unready_marker_has_no_dispatch_and_first_poll_sends_latest(self):
        self.marker.update((.2,.4), True)
        self.assertFalse(self.dispatch.callbacks)
        self.assertEqual(self.packets(), [])
        self.peer.send(b'{"window":200,"ready":true,"size":[1920,1080]}')
        self.marker.poll()
        self.assertEqual(self.packets(), [[.2,.4,True]])

    def test_poll_fallback_cancels_pending_dispatch_without_duplicate_send(self):
        self.ready()
        self.marker.update((.2,.4), False)
        self.assertEqual(len(self.dispatch.callbacks), 1)
        self.marker.poll()
        self.assertFalse(self.dispatch.callbacks)
        self.assertEqual(self.packets(), [[.2,.4,False]])
        self.dispatch.run()
        self.assertEqual(self.packets(), [])

    def test_backpressure_keeps_latest_without_a_busy_retry_source(self):
        self.ready()
        original = self.marker.socket
        self.marker.socket = SimpleNamespace(recv=original.recv,
            send=lambda _:(_ for _ in ()).throw(BlockingIOError()))
        try:
            self.marker.update((.2,.4), False)
            self.dispatch.run()
            self.assertFalse(self.dispatch.callbacks)
            self.assertEqual(self.marker.sent, (.5,.5,False))
            self.marker.update((.3,.6), False)
            self.dispatch.run()
            self.assertEqual(self.marker.pending, (.3,.6,False))
        finally:
            self.marker.socket = original
        self.marker.poll()
        self.assertEqual(self.packets(), [[.3,.6,False]])

    def test_dispatch_failure_invalidates_health_and_uses_normal_recovery(self):
        self.ready()
        original = self.marker.socket
        self.marker.socket = SimpleNamespace(recv=original.recv,
            send=lambda _:(_ for _ in ()).throw(OSError('peer closed')))
        try:
            self.marker.update((.2,.4), False)
            self.dispatch.run()  # Do not throw through a GTK callback.
            self.assertFalse(self.marker.current(self.marker.checked_at))
            with self.assertRaises(InputUnavailable): self.marker.poll()
            self.marker.update((.3,.6), False)
            self.assertFalse(self.dispatch.callbacks)
        finally:
            self.marker.socket = original

    def test_close_cancels_dispatch_and_late_callback_cannot_send(self):
        self.ready()
        self.marker.update((.2,.4), True)
        callback = next(iter(self.dispatch.callbacks.values()))
        packets = []
        original = self.marker.socket
        self.addCleanup(original.close)
        self.marker.socket = SimpleNamespace(send=lambda data:packets.append(json.loads(data)), close=lambda:None)
        self.marker.close()
        self.assertFalse(self.dispatch.callbacks)
        self.assertEqual(packets, [None])
        self.assertFalse(callback())
        self.marker.update((.3,.6), False)
        self.assertFalse(self.dispatch.callbacks)
        self.assertEqual(packets, [None])

    def test_dispatch_pair_is_required_before_opening_resources(self):
        for options in ({'schedule': self.dispatch.add}, {'cancel': self.dispatch.cancel}):
            with self.assertRaises(ValueError):
                MarkerOverlay(target=self.expected, **options)

    def motion(self, at=10., *, snap=False):
        return dict(ids=(8,),mode='position',active=True,sampled_at=at,snap=snap)

    def test_visual_samples_keep_contact_identity_and_source_time(self):
        self.ready()
        self.marker.update((.2,.4),False,motion=self.motion())
        self.dispatch.run()
        payload=self.packets()[0]
        self.assertEqual(payload['contacts'],[[.2,.4,False]])
        self.assertEqual(payload['motion'],dict(self.motion(),ids=[8]))

    def test_coalesced_lifecycle_barrier_survives_later_moves_and_backpressure(self):
        self.ready()
        self.marker.update((.2,.4),True,motion=self.motion(snap=True))
        self.marker.update((.3,.4),False,motion=self.motion(10.001))
        original=self.marker.socket
        self.marker.socket=SimpleNamespace(recv=original.recv,
            send=lambda _:(_ for _ in ()).throw(BlockingIOError()))
        try:self.dispatch.run()
        finally:self.marker.socket=original
        self.marker.update((.4,.4),False,motion=self.motion(10.002))
        self.dispatch.run()
        payload=self.packets()[0]
        self.assertEqual(payload['contacts'],[[.4,.4,False]])
        self.assertTrue(payload['motion']['snap'])
        self.marker.update((.5,.4),False,motion=self.motion(10.003))
        self.dispatch.run()
        self.assertFalse(self.packets()[0]['motion']['snap'])

    def test_identical_visual_targets_do_not_send_timestamp_only_updates(self):
        self.ready()
        self.marker.update((.2,.4),False,motion=self.motion())
        self.dispatch.run();self.packets()
        for i in range(100):
            self.marker.update((.2,.4),False,motion=self.motion(11+i/1000))
        self.assertFalse(self.dispatch.callbacks)
        self.assertEqual(self.packets(),[])

    def test_bad_visual_metadata_is_rejected_before_queuing(self):
        self.ready()
        with self.assertRaises(ValueError):
            self.marker.update((.2,.4),False,motion=dict(self.motion(),ids=(True,)))
        self.assertFalse(self.dispatch.callbacks)
        self.assertEqual(self.packets(),[])

    def test_motion_geometry_is_still_rejected_before_queuing(self):
        self.ready()
        for point, pressed in (((.2,), False), ((float('nan'), .3), False),
                               ((True, .3), False), ((.2, .3), 1)):
            with self.assertRaises(ValueError):
                self.marker.update(point, pressed, motion=self.motion())
        for contacts in (((.2, 2., True),), ((.2, .3, 1),), ((.2, .3),)):
            with self.assertRaises(ValueError):
                self.marker.update_contacts(contacts, motion=self.motion())
        self.assertFalse(self.dispatch.callbacks)
        self.assertEqual(self.packets(), [])

    def test_mutating_source_lists_after_update_cannot_change_queued_contacts(self):
        self.ready()
        contacts = [[.2, .3, True]]
        motion = dict(self.motion(), ids=[8], mode='direct')
        self.marker.update_contacts(contacts, motion=motion)
        contacts[0][:] = [.9, .9, False]
        motion['ids'][0] = 99
        motion['active'] = False
        self.dispatch.run()
        payload = self.packets()[0]
        self.assertEqual(payload['contacts'], [[.2, .3, True]])
        self.assertEqual(payload['motion']['ids'], [8])
        self.assertTrue(payload['motion']['active'])

    def test_default_glib_dispatch_sends_without_a_health_tick(self):
        try:
            from gi.repository import GLib
        except ImportError:
            self.skipTest('GLib integration requires Linux runtime')
        self.marker._schedule = lambda callback: GLib.idle_add(callback, priority=GLib.PRIORITY_DEFAULT)
        self.marker._cancel = GLib.source_remove
        self.ready()
        self.marker.update((.2,.4), False)
        context = GLib.MainContext.default()
        deadline = time.monotonic()+1
        while self.marker._send_source is not None and time.monotonic() < deadline:
            context.iteration(False)
        self.assertIsNone(self.marker._send_source)
        self.assertEqual(self.packets(), [[.2,.4,False]])


if __name__=='__main__': unittest.main()
