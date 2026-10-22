"""Confirmation, non-blocking launch, retry and detached removal lifetime."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.i18n import active_language, configure, encode_message, msg
from armada_dual_screen_input.uninstall_controller import UninstallController, start_worker


class UninstallControllerTests(unittest.TestCase):
    def setUp(self):
        previous = active_language()
        configure('en_US')
        self.addCleanup(configure, previous)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.work, self.delivery = [], []
        self.launch = Mock()
        self.model = UninstallController(self.root, dispatch=self.delivery.append, changed=Mock(),
            launch=self.launch, background=self.work.append, status_file=self.root/'uninstall.json')
        self.model.managed = True
        self.addCleanup(self.model.close)

    def finish(self):
        self.work.pop(0)()
        self.delivery.pop(0)()

    def test_confirmation_and_cancel_never_launch_or_mutate_installation(self):
        self.model.run()
        self.assertFalse(self.work)
        self.model.request()
        self.assertTrue(self.model.confirming)
        self.model.cancel()
        self.model.run()
        self.launch.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_confirmed_launch_is_async_and_coalesces_repeated_taps(self):
        self.model.request()
        self.model.run()
        self.model.run()
        self.model.request()
        self.assertEqual(len(self.work), 1)
        self.launch.assert_not_called()
        self.assertTrue(self.model.busy)
        self.finish()
        self.launch.assert_called_once_with(self.root)

    def test_failed_launch_allows_new_confirmation_and_retry(self):
        self.launch.side_effect = OSError('no user manager')
        self.model.request(); self.model.run(); self.finish()
        self.assertEqual(self.model.phase, 'error')
        self.assertFalse(self.model.busy)
        self.launch.side_effect = None
        self.model.request(); self.model.run(); self.finish()
        self.assertEqual(self.launch.call_count, 2)

    def test_source_checkout_cannot_request_or_run_uninstall(self):
        self.model.managed = False
        self.model.request(); self.model.run()
        self.assertFalse(self.model.confirming)
        self.assertFalse(self.work)

    def test_closing_panel_does_not_cancel_the_detached_task(self):
        self.model.request(); self.model.run()
        self.model.close(); self.finish()
        self.launch.assert_called_once()
        self.model.changed.assert_called_once()  # Initial starting notification only.

    def test_dead_worker_and_missing_status_exit_busy_state(self):
        self.model.request(); self.model.run(); self.finish()
        data = {'schema': 1, 'phase': 'uninstalling', 'message': 'old language',
                'pid': 123, 'identity': 'boot:1'}
        self.model.status_file.write_text(json.dumps(data))
        with patch('armada_dual_screen_input.uninstall_controller.process_identity', return_value=None):
            self.model.refresh()
        self.assertEqual(self.model.phase, 'error')
        self.assertIn('interrupted', self.model.message)
        self.model.request(); self.model.run(); self.finish()
        self.model.status_file.unlink()
        with patch('armada_dual_screen_input.uninstall_controller.time.time',
                   return_value=self.model._launch_time+21):
            self.model.refresh()
        self.assertFalse(self.model.busy)

    def test_structured_status_translates_after_failure_and_ignores_old_results(self):
        self.model.status_file.write_text(json.dumps({'schema': 1, 'phase': 'success', 'message': 'old'}))
        self.model.refresh()
        self.assertEqual(self.model.phase, 'ready')
        self.model.request(); self.model.run(); self.finish()
        self.model.status_file.write_text(json.dumps({'schema': 1, 'phase': 'error', 'message': 'fallback',
            'message_i18n': encode_message(msg('uninstall.start_failed'))}))
        self.model.refresh()
        self.assertIn('did not start', self.model.message)
        configure('zh_CN')
        self.assertIn('未能启动', self.model.message)

    def test_worker_launch_uses_own_user_unit_without_wait_or_scope(self):
        with patch.dict(os.environ, {'DBUS_SESSION_BUS_ADDRESS':'unix:path=/tmp/lower-private-bus'}), \
             patch('armada_dual_screen_input.uninstall_controller.subprocess.run') as run:
            run.return_value.returncode = 0
            start_worker(self.root)
        command = run.call_args.args[0]
        self.assertIn('--user', command)
        self.assertIn('--unit=thor-panel-uninstall', command)
        self.assertIn('--property=Type=exec', command)
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS', run.call_args.kwargs['env'])
        self.assertIn('--setenv=DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/lower-private-bus', command)
        for forbidden in ('sudo', '--scope', '--wait', 'steam.service', 'gamescope.service'):
            self.assertNotIn(forbidden, command)
        self.assertEqual(command[-2:], ['--ui-language', 'en_US'])
