"""UI lifecycle and detached startup, with a deterministic fake thread queue."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from armada_dual_screen_input.i18n import configure, active_language
from unittest.mock import Mock, patch

from armada_dual_screen_input.update_controller import UpdateController, start_worker
from armada_dual_screen_input.updates import UpdateError, parse_release
from test_updates import public_release_fixture, public_requests, release_data


class ControllerTests(unittest.TestCase):
    def setUp(self):
        previous = active_language()
        configure("zh_CN")
        self.addCleanup(configure, previous)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); (self.root / 'VERSION').write_text('0.1.0')
        self.work, self.delivery = [], []
        self.deadlines = []
        self.changed = Mock()
        self.fetch = Mock(return_value=parse_release(release_data()))
        self.launch = Mock()
        self.controller = UpdateController(self.root, dispatch=self.delivery.append,
            changed=self.changed, fetch=self.fetch, launch=self.launch, background=self.work.append,
            status_file=self.root / 'status.json', deadline=lambda seconds, callback:
                self.deadlines.append(callback) or Mock())
        self.controller.managed = True
        self.addCleanup(self.controller.close)

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

    def test_default_check_uses_shared_public_discovery_without_rest_or_real_network(self):
        from armada_dual_screen_input import installer_release
        selected, _, calls, opener = public_release_fixture()
        discover = installer_release.latest_install_release
        controller = UpdateController(self.root, dispatch=self.delivery.append,
            changed=self.changed, launch=self.launch, background=self.work.append,
            status_file=self.root/'public-status.json', deadline=lambda *_: Mock())
        controller.managed = True
        self.addCleanup(controller.close)
        with patch.object(installer_release, 'latest_install_release',
                          side_effect=lambda **_: discover(opener=opener)) as shared, \
             patch('armada_dual_screen_input.updates.open_url',
                   side_effect=AssertionError('REST discovery forbidden')) as rest, \
             patch('urllib.request.OpenerDirector.open',
                   side_effect=AssertionError('Real network forbidden')):
            controller.check()
            self.finish()
        shared.assert_called_once()
        rest.assert_not_called()
        self.assertEqual(calls, public_requests(selected))
        self.assertEqual(controller.latest, selected)
        self.assertTrue(controller.available)
        self.fetch.assert_not_called()
        self.launch.assert_not_called()

    def test_closing_panel_ignores_late_network_callback(self):
        self.controller.check(); self.controller.close()
        calls = self.changed.call_count
        self.finish()
        self.assertEqual(self.changed.call_count, calls)
        self.launch.assert_not_called()

    def test_slow_dns_cannot_leave_check_busy_or_deliver_stale_results(self):
        self.controller.check()
        self.deadlines.pop(0)()
        self.delivery.pop(0)()
        self.assertEqual(self.controller.phase, 'error')
        self.assertIn('超时', self.controller.message)
        self.assertFalse(self.controller.busy)
        self.finish()  # The old read-only lookup eventually returns.
        self.assertIsNone(self.controller.latest)
        self.controller.check(); self.finish()
        self.assertTrue(self.controller.available)

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

    def test_worker_status_remains_translatable_and_legacy_messages_still_work(self):
        from armada_dual_screen_input.i18n import msg, encode_message
        data = {'schema': 1, 'phase': 'downloading', 'message': 'legacy text',
                'message_i18n': encode_message(msg('worker.downloading')),
                'pid': 123, 'identity': 'boot:start'}
        self.controller.status_file.write_text(json.dumps(data))
        with patch('armada_dual_screen_input.update_controller.process_identity', return_value='boot:start'):
            self.controller.refresh()
        self.assertIn('正在下载', self.controller.message)
        configure('en_US')
        self.assertIn('Downloading', self.controller.message)
        data.pop('message_i18n')
        self.controller.status_file.write_text(json.dumps(data))
        with patch('armada_dual_screen_input.update_controller.process_identity', return_value='boot:start'):
            self.controller.refresh()
        self.assertEqual(self.controller.message, 'legacy text')

    def test_malformed_worker_status_does_not_leave_starting_stuck_forever(self):
        self.controller.phase = 'starting'
        self.controller._launch_time = 1
        self.controller.status_file.write_text('{"schema":99}')
        with patch('armada_dual_screen_input.update_controller.time.time', return_value=30):
            self.controller.refresh()
        self.assertEqual(self.controller.phase, 'error')
        self.assertFalse(self.controller.busy)

    def test_transient_service_does_not_wait_or_inherit_panel_cgroup(self):
        with patch.dict(os.environ, {'DBUS_SESSION_BUS_ADDRESS':'unix:path=/tmp/lower-private-bus'}), \
             patch('armada_dual_screen_input.update_controller.subprocess.run') as run:
            run.return_value.returncode = 0
            start_worker(self.root, 'v0.2.0')
        args = run.call_args.args[0]
        self.assertIn('--user', args)
        self.assertIn('--unit=thor-panel-update', args)
        self.assertIn('--property=Type=exec', args)
        self.assertNotIn('--scope', args)
        self.assertNotIn('--wait', args)
        self.assertNotIn('sudo', args)
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS', run.call_args.kwargs['env'])
        self.assertEqual(args[-2:], ['--expected-tag', 'v0.2.0'])


if __name__ == '__main__':
    unittest.main()
