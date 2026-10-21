"""Marker restoration uses bounded IPC and never starts an X11 window here."""
import json
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from armada_dual_screen_input.marker_overlay import MarkerOverlay


class MarkerOverlayTests(unittest.TestCase):
    def setUp(self):
        self.peer=None

        def spawn(*args, **kwargs):
            self.peer=socket.fromfd(kwargs['pass_fds'][0],socket.AF_UNIX,socket.SOCK_DGRAM)
            self.peer.setblocking(False)
            return SimpleNamespace(poll=lambda:None,wait=lambda **kwargs:0)

        with patch('armada_dual_screen_input.marker_overlay.subprocess.Popen',side_effect=spawn):
            self.marker=MarkerOverlay(display=':0',server_pid=42)
        self.addCleanup(self.peer.close)
        self.addCleanup(self.marker.wait)
        self.addCleanup(self.marker.close)

    def packets(self):
        result=[]
        while True:
            try: result.append(json.loads(self.peer.recv(4096)))
            except BlockingIOError: return result

    def ready(self):
        self.peer.send(b'{"ready":true,"size":[1920,1080]}')
        self.marker.poll()
        self.packets()

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
        self.peer.send(b'{"ready":true,"size":[1920,1080]}')
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


if __name__=='__main__': unittest.main()
