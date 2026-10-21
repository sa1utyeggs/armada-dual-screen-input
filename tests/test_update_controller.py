"""UI lifecycle and detached startup, with a deterministic fake thread queue."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.update_controller import UpdateController, start_worker
from armada_dual_screen_input.updates import UpdateError, parse_release
from test_updates import release_data


class ControllerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); (self.root / 'VERSION').write_text('0.1.0')
        self.work, self.delivery = [], []
        self.changed = Mock()
        self.fetch = Mock(return_value=parse_release(release_data()))
        self.launch = Mock()
        self.controller = UpdateController(self.root, dispatch=self.delivery.append,
            changed=self.changed, fetch=self.fetch, launch=self.launch, background=self.work.append,
            status_file=self.root / 'status.json')
        self.controller.managed = True

    def finish(self):
        self.work.pop(0)()
        self.delivery.pop(0)()

    def test_check_is_manual_nonblocking_and_coalesces_duplicate_taps(self):
        self.assertFalse(self.work)
        self.controller.check(); self.controller.check()
        self.assertEqual(len(self.work), 1)
        self.fetch.assert_not_called()
        self.work.pop()()
        self.assertEqual(self.controller.phase, 'checking')
        self.delivery.pop()()
        self.assertTrue(self.controller.available)
        self.launch.assert_not_called()

    def test_closing_panel_ignores_late_network_callback(self):
        self.controller.check(); self.controller.close()
        calls = self.changed.call_count
        self.finish()
        self.assertEqual(self.changed.call_count, calls)
        self.launch.assert_not_called()

    def test_error_allows_retry_but_does_not_offer_stale_download(self):
        self.fetch.side_effect = UpdateError('网络不可用')
        self.controller.check(); self.finish()
        self.assertEqual(self.controller.phase, 'error')
        self.assertFalse(self.controller.available)
        self.fetch.side_effect = None
        self.controller.check(); self.finish()
        self.assertTrue(self.controller.available)

    def test_update_launch_runs_outside_the_panel_thread(self):
        self.controller.check(); self.finish()
        self.controller.install(); self.controller.install()
        self.launch.assert_not_called()
        self.assertEqual(len(self.work), 1)
        self.finish()
        self.launch.assert_called_once_with(self.root.resolve(), 'v0.2.0')
        self.controller.close()
        # Close never terminates the independent updater.
        self.assertEqual(self.launch.call_count, 1)

    def test_worker_checking_status_continues_to_poll_and_reports_crash(self):
        path = self.controller.status_file
        data = {'schema': 1, 'phase': 'checking', 'message': '核对中', 'pid': 123, 'identity': 'boot:start'}
        path.write_text(json.dumps(data))
        with patch('armada_dual_screen_input.update_controller.process_identity', return_value='boot:start'):
            self.controller.refresh()
            self.assertTrue(self.controller.busy)
            data.update(phase='downloading', message='下载中'); path.write_text(json.dumps(data))
            self.controller.refresh()
            self.assertEqual(self.controller.phase, 'downloading')
        with patch('armada_dual_screen_input.update_controller.process_identity', return_value=None):
            self.controller.refresh()
            self.assertEqual(self.controller.phase, 'error')
            self.assertIn('中断', self.controller.message)

    def test_source_checkout_cannot_start_install(self):
        self.controller.managed = False
        self.controller.check(); self.finish(); self.controller.install()
        self.assertFalse(self.controller.available)
        self.assertFalse(self.work)

    def test_malformed_worker_status_does_not_leave_starting_stuck_forever(self):
        self.controller.phase = 'starting'
        self.controller._launch_time = 1
        self.controller.status_file.write_text('{"schema":99}')
        with patch('armada_dual_screen_input.update_controller.time.time', return_value=30):
            self.controller.refresh()
        self.assertEqual(self.controller.phase, 'error')
        self.assertFalse(self.controller.busy)

    def test_transient_service_does_not_wait_or_inherit_panel_cgroup(self):
        with patch('armada_dual_screen_input.update_controller.subprocess.run') as run:
            run.return_value.returncode = 0
            start_worker(self.root, 'v0.2.0')
        args = run.call_args.args[0]
        self.assertIn('--user', args)
        self.assertIn('--unit=thor-panel-update', args)
        self.assertIn('--property=Type=exec', args)
        self.assertNotIn('--scope', args)
        self.assertNotIn('--wait', args)
        self.assertNotIn('sudo', args)
        self.assertEqual(args[-2:], ['--expected-tag', 'v0.2.0'])


if __name__ == '__main__':
    unittest.main()
