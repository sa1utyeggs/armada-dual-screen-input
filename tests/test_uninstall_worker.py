"""Uninstall a temporary home only; no real service or personal file changes."""
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import uninstall as worker
from manage import Installer, Paths
from release import PackageError, seal
import test_installation as fixture


class UninstallWorkerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name).resolve()
        home = self.work/'home'
        self.paths = Paths(home, home/'.local/share', home/'.config', home/'.local/bin', home/'Desktop')
        self.services = fixture.Services()
        self.installer = Installer(self.paths, runner=self.services, refresher=Mock(return_value={'warnings': []}))
        source = self.work/'bundle'; source.mkdir()
        repo = Path(__file__).resolve().parents[1]
        (source/'VERSION').write_text('0.1.3')
        for name in ('packaging/systemd/thor-panel.service.in', 'packaging/desktop/thor-panel.desktop.in',
                     'assets/icons/armada-dual-screen-input.svg'):
            path = source/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((repo/name).read_bytes())
        seal(source, revision='a'*40)
        self.installer.install(source)
        self.current = (self.paths.root/'current').resolve()
        patcher = patch.object(worker, 'ROOT', self.current)
        patcher.start(); self.addCleanup(patcher.stop)
        self.config = self.paths.config/'thor-panel/config.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_bytes(b'{"keyboard_language":"zh_CN","future":42}\n')
        self.original = self.config.read_bytes()
        self.log = self.work/'state/uninstall.json'
        self.notify = Mock()
        self.services.calls.clear()

    def perform(self):
        return worker.perform(paths=self.paths, installer=self.installer, notification=self.notify,
            status=lambda phase, message, **kwargs: worker.write_status(phase, message, path=self.log, **kwargs))

    def test_removal_finishes_after_deleting_bundle_and_keeps_config_and_record(self):
        self.services.active = True
        result = self.perform()
        self.assertTrue(result['uninstalled'])
        self.assertFalse(self.current.exists())
        self.assertFalse((self.paths.root/'current').exists())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(json.loads(self.log.read_text())['phase'], 'success')
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)
        self.notify.assert_called_once()
        self.assertFalse(self.services.active)
        self.assertTrue(all(call[-1] == 'thor-panel.service' or call[0] == 'daemon-reload'
                            for call in self.services.calls))

    def test_modified_shortcut_is_kept_and_reported_as_leftover(self):
        shortcut = self.paths.external()['desktop']
        shortcut.write_text('user changed shortcut')
        result = self.perform()
        self.assertIn(str(shortcut), result['leftovers'])
        self.assertEqual(shortcut.read_text(), 'user changed shortcut')
        self.assertEqual(json.loads(self.log.read_text())['result']['leftovers'], result['leftovers'])

    def test_update_in_progress_blocks_removal_before_any_service_operation(self):
        with (self.paths.root/'update.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(PackageError):
                self.perform()
        self.assertTrue(self.current.exists())
        self.assertFalse(self.services.calls)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_changed_current_or_service_refuses_removal(self):
        with patch.object(worker, 'ROOT', self.work/'other'):
            with self.assertRaises(PackageError):
                self.perform()
        self.assertFalse(self.services.calls)
        self.paths.external()['unit'].write_text('locally modified')
        with self.assertRaises(PackageError):
            self.perform()
        self.assertTrue(self.current.exists())
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_absent_notification_support_does_not_invalidate_result(self):
        with patch.object(worker.shutil, 'which', return_value=None):
            run = Mock()
            worker.notify('removed', runner=run)
        run.assert_not_called()
        with patch.object(worker.shutil, 'which', return_value='/usr/bin/notify-send'):
            worker.notify('removed', runner=Mock(side_effect=OSError('no notification bus')))

    def test_entrypoint_records_failure_and_notifies_without_hiding_the_error(self):
        with patch.object(worker.sys, 'argv', ['uninstall.py']), \
             patch.object(worker.sys, 'platform', 'linux'), \
             patch.object(worker.os, 'geteuid', return_value=1000), \
             patch.object(worker, 'perform', side_effect=PackageError('modified service')), \
             patch.object(worker, 'write_status') as status, \
             patch.object(worker, 'notify') as notification:
            with self.assertRaises(SystemExit) as stopped:
                worker.main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(status.call_args.args[0], 'error')
        self.assertIn('modified service', str(status.call_args.args[1]))
        notification.assert_called_once()
