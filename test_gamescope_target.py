from pathlib import Path
import socket
import tempfile
import unittest

from gamescope_target import GamescopeTarget


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
