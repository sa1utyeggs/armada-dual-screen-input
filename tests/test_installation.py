"""Transactional filesystem/service checks using temporary homes and fake systemd."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from manage import Installer, Paths
from release import PackageError, archive, prepare, seal, verify


class Services:
    def __init__(self): self.active=False; self.calls=[]; self.fail_reload=False
    def __call__(self, arguments, *, check=True):
        self.calls.append(arguments)
        if arguments[0]=='is-active': return SimpleNamespace(returncode=0 if self.active else 3)
        if arguments[0]=='daemon-reload' and self.fail_reload:
            self.fail_reload=False
            if check: raise PackageError('simulated daemon reload failure')
        if arguments[0]=='stop': self.active=False
        if arguments[0]=='start': self.active=True
        return SimpleNamespace(returncode=0)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.work=tempfile.TemporaryDirectory();self.addCleanup(self.work.cleanup)
        self.work=Path(self.work.name);home=self.work/'home with spaces'
        self.paths=Paths(home,home/'.local/share',home/'.config',home/'.local/bin',home/'Desktop')
        self.services=Services();self.refresher=Mock(return_value={'warnings': []})
        self.installer=Installer(self.paths,runner=self.services,refresher=self.refresher)
        self.repo=Path(__file__).resolve().parents[1]

    def bundle(self, version='0.1.0-preview.1', content='first'):
        root=self.work/('bundle-'+version);root.mkdir()
        (root/'VERSION').write_text(version+'\n')
        for name in ('packaging/systemd/thor-panel.service.in','packaging/desktop/thor-panel.desktop.in','assets/icons/armada-dual-screen-input.svg'):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((self.repo/name).read_bytes())
        (root/'code.py').write_text(content)
        seal(root);return root

    def test_fresh_install_does_not_start_enable_or_write_configuration(self):
        config=self.paths.config/'thor-panel/config.json';config.parent.mkdir(parents=True);config.write_text('{"scroll_scale":0.25}')
        bundle=self.bundle();result=self.installer.install(bundle)
        self.assertFalse(result['started'])
        self.assertEqual(config.read_text(),'{"scroll_scale":0.25}')
        self.assertFalse(any(c[0] in ('start','restart','enable','disable') for c in self.services.calls))
        self.assertTrue((self.paths.root/'current').is_symlink())
        self.assertTrue(self.paths.external()['desktop'].is_file())
        self.assertIn('home with spaces',self.paths.external()['unit'].read_text())
        self.assertIn('current/tools/run.py" --run',self.paths.external()['unit'].read_text())

    def test_active_upgrade_restarts_only_own_service_and_rollback_restores_previous_code(self):
        self.installer.install(self.bundle())
        self.services.active=True
        self.installer.install(self.bundle('0.2.0','second'))
        self.assertEqual((self.paths.root/'current/code.py').read_text(),'second')
        self.installer.rollback()
        self.assertEqual((self.paths.root/'current/code.py').read_text(),'first')
        self.assertTrue(self.services.active)
        self.assertTrue(all('armada-bottom' not in str(c) and 'gamescope' not in str(c) for c in self.services.calls))

    def test_cache_refresh_runs_after_committed_install_rollback_and_removal(self):
        def refreshed(paths):
            self.assertEqual(paths,self.paths)
            if paths.state.exists():
                self.assertEqual(json.loads(paths.state.read_text())['version'],
                                 (paths.root/'current/VERSION').read_text().strip())
            return {'warnings': []}
        self.refresher.side_effect=refreshed
        self.installer.install(self.bundle())
        self.installer.install(self.bundle('0.2.0'))
        self.installer.rollback()
        self.installer.uninstall()
        self.assertEqual(self.refresher.call_count,4)

    def test_cache_failure_does_not_undo_successful_install(self):
        self.refresher.side_effect=OSError('cache unavailable')
        result=self.installer.install(self.bundle())
        self.assertTrue(result['desktop_refresh']['warnings'])
        self.assertTrue(self.paths.state.is_file())
        self.assertEqual((self.paths.root/'current/code.py').read_text(),'first')

    def test_rollback_restores_previous_icon_and_managed_metadata(self):
        first=self.bundle();first_icon=(first/'assets/icons/armada-dual-screen-input.svg').read_bytes()
        self.installer.install(first)
        second=self.bundle('0.2.0')
        icon=second/'assets/icons/armada-dual-screen-input.svg'
        icon.write_bytes(first_icon+b'\n<!-- updated icon -->\n');seal(second)
        self.installer.install(second)
        self.assertNotEqual(self.paths.external()['icon'].read_bytes(),first_icon)
        self.installer.rollback()
        self.assertEqual(self.paths.external()['icon'].read_bytes(),first_icon)
        state=json.loads(self.paths.state.read_text())
        import hashlib
        self.assertEqual(state['files'][str(self.paths.external()['icon'])],hashlib.sha256(first_icon).hexdigest())

    def test_failed_upgrade_restores_files_link_state_and_running_status(self):
        self.installer.install(self.bundle());self.services.active=True
        before={key:path.read_bytes() for key,path in self.paths.external().items()}
        state=self.paths.state.read_bytes();link=os.readlink(self.paths.root/'current')
        self.services.fail_reload=True
        with self.assertRaises(PackageError):self.installer.install(self.bundle('0.2.0','second'))
        self.assertEqual(state,self.paths.state.read_bytes())
        self.assertEqual(link,os.readlink(self.paths.root/'current'))
        self.assertEqual(before,{key:path.read_bytes() for key,path in self.paths.external().items()})
        self.assertTrue(self.services.active)

    def test_tampered_bundle_is_rejected_before_any_service_action(self):
        bundle=self.bundle();(bundle/'code.py').write_text('changed')
        with self.assertRaises(PackageError):self.installer.install(bundle)
        self.assertEqual(self.services.calls,[])
        self.refresher.assert_not_called()
        self.assertFalse(self.paths.root.exists())

    def test_unrelated_desktop_file_is_not_overwritten(self):
        path=self.paths.external()['desktop'];path.parent.mkdir(parents=True);path.write_text('my unrelated shortcut')
        with self.assertRaises(PackageError):self.installer.install(self.bundle())
        self.assertEqual(path.read_text(),'my unrelated shortcut')
        self.assertEqual(self.services.calls,[])

    def test_legacy_metadata_is_recognized_and_backed_up_without_removing_old_source(self):
        unit=self.paths.external()['unit'];unit.parent.mkdir(parents=True)
        unit.write_text('[Service]\nExecStart=/usr/bin/python3 "%h/.local/share/thor-panel/supervisor.py" --run\n')
        legacy=self.paths.root/'supervisor.py';legacy.parent.mkdir(parents=True);legacy.write_text('old code')
        self.installer.install(self.bundle())
        self.assertEqual(legacy.read_text(),'old code')
        self.assertTrue(list((self.paths.root/'backups').glob('*/index.json')))

    def test_release_directory_symlink_is_rejected(self):
        self.paths.root.mkdir(parents=True);outside=self.work/'outside';outside.mkdir()
        (self.paths.root/'releases').symlink_to(outside)
        with self.assertRaises(PackageError):self.installer.install(self.bundle())
        self.assertEqual(list(outside.iterdir()),[])

    def test_uninstall_preserves_config_logs_unrelated_and_modified_files(self):
        self.installer.install(self.bundle());self.services.active=True
        config=self.paths.config/'thor-panel/config.json';config.parent.mkdir(parents=True);config.write_text('settings')
        log=self.paths.home/'.local/state/thor-panel/panel.log';log.parent.mkdir(parents=True);log.write_text('log')
        shortcut=self.paths.external()['desktop'];shortcut.write_text('edited shortcut')
        unrelated=self.paths.root/'personal-note.txt';unrelated.write_text('keep')
        result=self.installer.uninstall()
        self.assertIn(str(shortcut),result['leftovers'])
        self.assertEqual(shortcut.read_text(),'edited shortcut')
        self.assertEqual(config.read_text(),'settings');self.assertEqual(log.read_text(),'log')
        self.assertEqual(unrelated.read_text(),'keep')
        self.assertFalse(self.paths.external()['unit'].exists());self.assertFalse(self.services.active)

    def test_uninstall_refuses_changed_service_before_stopping_it(self):
        self.installer.install(self.bundle());self.services.calls.clear()
        self.paths.external()['unit'].write_text('unrelated service')
        with self.assertRaises(PackageError):self.installer.uninstall()
        self.assertEqual(self.services.calls,[])

    def test_failed_stop_aborts_uninstall_before_removing_files(self):
        self.installer.install(self.bundle())
        def fail(arguments,check=True):
            if arguments[0]=='stop':raise PackageError('service manager unavailable')
            return self.services(arguments,check=check)
        self.installer.runner=fail
        with self.assertRaises(PackageError):self.installer.uninstall()
        self.assertTrue(self.paths.external()['unit'].exists())
        self.assertTrue((self.paths.root/'current/code.py').exists())
        self.assertTrue(self.paths.state.exists())

    def test_failed_rollback_state_write_restores_original_links_and_state(self):
        self.installer.install(self.bundle());self.installer.install(self.bundle('0.2.0','second'))
        self.services.active=True
        before=self.paths.state.read_bytes()
        metadata={name:path.read_bytes() for name,path in self.paths.external().items()}
        with patch.object(self.installer,'save_state',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.installer.rollback()
        self.assertEqual(self.paths.state.read_bytes(),before)
        self.assertEqual((self.paths.root/'current/code.py').read_text(),'second')
        self.assertTrue(self.services.active)
        self.assertEqual(metadata,{name:path.read_bytes() for name,path in self.paths.external().items()})

    def test_manifest_traversal_unlisted_file_and_symlink_are_rejected(self):
        bundle=self.bundle();data=json.loads((bundle/'manifest.json').read_text())
        data['files']['../outside']='0'*64;(bundle/'manifest.json').write_text(json.dumps(data))
        with self.assertRaises(PackageError):verify(bundle)
        seal(bundle);(bundle/'unlisted.py').write_text('extra')
        with self.assertRaises(PackageError):verify(bundle)
        (bundle/'unlisted.py').unlink();(bundle/'link').symlink_to(bundle/'code.py')
        with self.assertRaises(PackageError):verify(bundle)

    def test_archives_are_reproducible_and_exclude_absolute_paths(self):
        bundle=self.bundle();a=self.work/'a.tar.gz';b=self.work/'b.tar.gz'
        archive(bundle,a);archive(bundle,b)
        self.assertEqual(a.read_bytes(),b.read_bytes())
        import tarfile
        with tarfile.open(a) as reader:
            self.assertTrue(all(not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in reader.getmembers()))

    def test_source_release_whitelist_does_not_copy_configuration_logs_or_driver_experiments(self):
        import shutil
        from release import ROOT_FILES,TOOLS,DOCS,TREES
        source=self.work/'source';source.mkdir()
        for name in ROOT_FILES:shutil.copyfile(self.repo/name,source/name)
        for tree in (*TREES,'tools','docs'):
            shutil.copytree(self.repo/tree,source/tree,ignore=shutil.ignore_patterns('__pycache__'))
        (source/'src/private-config.json').write_text('private')
        (source/'src/ui.log').write_text('private log')
        (source/'extras').mkdir();(source/'extras/driver.ko').write_bytes(b'not an app payload')
        for name in ('markers/glove-v1/idle.png', 'markers/glove/reference.png',
                     'markers/pixel_hand/reference.png', 'markers/paw/idle.png', 'private-preview.png'):
            draft=source/'assets'/name;draft.parent.mkdir(parents=True,exist_ok=True)
            draft.write_bytes(b'not a runtime asset')
        for state in ('idle', 'pressed'):
            marker=source/'assets/markers/pixel_hand'/f'{state}.png'
            marker.parent.mkdir(parents=True,exist_ok=True)
            marker.write_bytes(b'pixel-hand runtime fixture')
        icon=source/'assets/icons/extra.png';icon.write_bytes(b'additional application icon')
        target=self.work/'prepared'
        with patch('release.runtime_package',return_value=(self.work/'unused.rpm',{})),patch('release.extract_runtime'):
            manifest=prepare(source,target)
        self.assertNotIn('src/private-config.json',manifest['files'])
        self.assertNotIn('src/ui.log',manifest['files'])
        self.assertFalse(any(p.startswith('extras/') for p in manifest['files']))
        self.assertIn('vendor/ratatoskr/LICENSE',manifest['files'])
        self.assertIn('src/armada_dual_screen_input/i18n.py', manifest['files'])
        self.assertIn('src/armada_dual_screen_input/ui_catalogs.py', manifest['files'])
        self.assertIn('docs/i18n.md', manifest['files'])
        self.assertIn('tools/uninstall.py', manifest['files'])
        self.assertEqual({name for name in manifest['files'] if name.startswith('assets/markers/')},
                         {'assets/markers/glove/idle.png', 'assets/markers/glove/pressed.png',
                          'assets/markers/pixel_hand/idle.png', 'assets/markers/pixel_hand/pressed.png'})
        self.assertIn('assets/icons/extra.png', manifest['files'])
        self.assertNotIn('assets/private-preview.png', manifest['files'])

    def test_dry_run_writes_no_home_files_or_services(self):
        env=dict(os.environ,HOME=str(self.paths.home),XDG_DATA_HOME=str(self.paths.data),XDG_CONFIG_HOME=str(self.paths.config),PYTHONDONTWRITEBYTECODE='1')
        result=subprocess.run([sys.executable,'-B',str(self.repo/'tools/manage.py'),'install','--dry-run'],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(json.loads(result.stdout)['autostart'])
        self.assertFalse(self.paths.home.exists())


if __name__=='__main__':unittest.main()
