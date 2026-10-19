import json
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gamescope_probe import probe_display, validate_display


class GamescopeProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime = Path(self.directory.name).resolve()
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        self.socket.bind(str(self.runtime / 'primary'))

    def test_explicit_same_user_socket_and_local_alias_are_accepted(self):
        (self.runtime / 'alias').symlink_to('primary')
        self.assertEqual(validate_display(self.runtime, 'alias'), self.runtime / 'primary')

    def test_socket_alias_cannot_escape_the_selected_runtime(self):
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / 'alias').symlink_to(self.runtime / 'primary')
            with self.assertRaises(ValueError):
                validate_display(Path(other), 'alias')

    def test_regular_files_and_guessed_paths_are_rejected(self):
        (self.runtime / 'file').write_text('not a socket')
        for name in ('file', '../primary', '/tmp/primary', '.', '', 'a\0b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_display(self.runtime, name)

    def test_runtime_of_a_different_user_is_rejected(self):
        with patch('gamescope_probe.os.getuid', return_value=self.runtime.stat().st_uid + 1):
            with self.assertRaises(ValueError):
                validate_display(self.runtime, 'primary')

    def test_unsupported_host_never_starts_a_native_process(self):
        with patch('gamescope_probe.sys.platform', 'darwin'), \
             patch('gamescope_probe.subprocess.run') as run:
            self.assertEqual(probe_display(self.runtime, 'primary')['status'],
                             'unsupported_platform')
            run.assert_not_called()

    def test_native_probe_is_time_bounded_and_explicitly_targeted(self):
        response = {'status': 'node_advertised', 'capture_tested': False, 'input_tested': False}
        with patch('gamescope_probe.sys.platform', 'linux'), \
             patch('gamescope_probe.subprocess.run', return_value=SimpleNamespace(
                 returncode=0, stdout=json.dumps(response))) as run:
            self.assertEqual(probe_display(self.runtime, 'primary'), response)
            args, kwargs = run.call_args
            self.assertEqual(args[0][-1], 'primary')
            self.assertIn('-I', args[0])
            self.assertEqual(kwargs['timeout'], 3.0)

    def test_unresponsive_native_probe_returns_timeout(self):
        with patch('gamescope_probe.sys.platform', 'linux'), \
             patch('gamescope_probe.subprocess.run', side_effect=subprocess.TimeoutExpired('probe', 3)):
            self.assertEqual(probe_display(self.runtime, 'primary'), {'status': 'timeout'})

    def test_worker_crash_does_not_crash_the_caller(self):
        with patch('gamescope_probe.sys.platform', 'linux'), \
             patch('gamescope_probe.subprocess.run', return_value=SimpleNamespace(returncode=-11)):
            self.assertEqual(probe_display(self.runtime, 'primary'),
                             {'status': 'probe_failed', 'returncode': -11})

    def test_malformed_native_result_is_rejected(self):
        for output in ('not json', '[]'):
            with self.subTest(output=output), patch('gamescope_probe.sys.platform', 'linux'), \
                 patch('gamescope_probe.subprocess.run', return_value=SimpleNamespace(
                     returncode=0, stdout=output)):
                self.assertEqual(probe_display(self.runtime, 'primary'), {'status': 'probe_failed'})

    def test_invalid_timeout_cannot_start_an_unbounded_probe(self):
        with patch('gamescope_probe.sys.platform', 'linux'):
            for timeout in (0, -1, 31, float('nan')):
                with self.assertRaises(ValueError):
                    probe_display(self.runtime, 'primary', timeout=timeout)


if __name__ == '__main__':
    unittest.main()
