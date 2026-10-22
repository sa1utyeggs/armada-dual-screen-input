"""Update a temporary installation through the real transactional installer."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from armada_dual_screen_input.i18n import configure, active_language
from unittest.mock import Mock, patch

import update as worker
from manage import Installer, Paths
from release import PackageError, seal
import test_installation as fixture


class WorkerTests(unittest.TestCase):
    def setUp(self):
        previous = active_language()
        configure("zh_CN")
        self.addCleanup(configure, previous)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.work = Path(temp.name).resolve()
        self.repo = Path(__file__).resolve().parents[1]
        home = self.work / 'home'
        self.paths = Paths(home, home / '.local/share', home / '.config', home / '.local/bin', home / 'Desktop')
        self.services = fixture.Services()
        self.installer = Installer(self.paths, runner=self.services, refresher=Mock(return_value={'warnings': []}))
        self.old = self.bundle('0.1.0')
        self.installer.install(self.old)
        self.current = (self.paths.root / 'current').resolve()
        self.services.calls.clear()
        self.config = self.paths.config / 'thor-panel/config.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_bytes(b'{"mode":"split","scroll_scale":0.001,"future":42}\n')
        self.original = self.config.read_bytes()
        self.status = Mock()
        patcher = patch.object(worker, 'ROOT', self.current)
        patcher.start(); self.addCleanup(patcher.stop)

    def bundle(self, version):
        root = self.work / version
        root.mkdir()
        (root / 'VERSION').write_text(version)
        for name in ('packaging/systemd/thor-panel.service.in', 'packaging/desktop/thor-panel.desktop.in',
                     'assets/icons/armada-dual-screen-input.svg'):
            target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((self.repo / name).read_bytes())
        seal(root, revision='a' * 40)
        return root

    def perform(self, *, version='0.2.0', tag='v0.2.0', prepare=None, runtime=None):
        release = SimpleNamespace(version=version, tag=tag)
        return worker.perform('v0.2.0', fetch=lambda: release,
            prepare=prepare or (lambda *_: self.bundle(version)), installer=self.installer,
            paths=self.paths, status=self.status, check_host=Mock(),
            check_runtime=runtime or (lambda _: {'all': True}))

    def test_success_preserves_config_and_restarts_only_own_active_service(self):
        self.services.active = True
        self.perform()
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual((self.paths.root / 'current/VERSION').read_text(), '0.2.0')
        self.assertEqual((self.paths.root / 'previous').resolve(), self.current)
        self.assertTrue(self.services.active)
        self.assertTrue(all(call[0] not in ('enable', 'disable') for call in self.services.calls))
        self.assertTrue(all('steam' not in str(call) and 'armada' not in str(call) for call in self.services.calls))
        self.assertEqual(self.status.call_args.args[0], 'success')

    def test_download_failure_keeps_files_links_and_service_untouched(self):
        with self.assertRaises(OSError):
            self.perform(prepare=Mock(side_effect=OSError('offline')))
        self.assertEqual((self.paths.root / 'current').resolve(), self.current)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(self.services.calls)

    def test_cache_failure_is_reported_as_successful_update_with_advice(self):
        self.installer.refresher.return_value = {'warnings': ['helper unavailable']}
        self.perform()
        self.assertEqual((self.paths.root / 'current/VERSION').read_text(), '0.2.0')
        self.assertEqual(self.status.call_args.args[0], 'success')
        self.assertIn('桌面缓存刷新未完成', str(self.status.call_args.args[1]))
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_changed_latest_or_wrong_manifest_aborts_before_install(self):
        with self.assertRaisesRegex(worker.UpdateError, '已变化'):
            self.perform(tag='v0.3.0')
        wrong = self.bundle('0.3.0')
        with self.assertRaises(worker.UpdateError):
            self.perform(prepare=lambda *_: wrong)
        self.assertFalse(self.services.calls)

    def test_dependency_failure_does_not_stop_running_panel(self):
        self.services.active = True
        with self.assertRaises(worker.UpdateError):
            self.perform(runtime=lambda _: {'gtk': False})
        self.assertTrue(self.services.active)
        self.assertFalse(self.services.calls)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_installer_error_rolls_back_to_previous_version(self):
        self.services.active = True
        self.services.fail_reload = True
        with self.assertRaises(PackageError):
            self.perform()
        self.assertEqual((self.paths.root / 'current').resolve(), self.current)
        self.assertTrue(self.services.active)
        self.assertEqual(self.config.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
