"""Click installer checks use fixture releases, temporary homes and fake services."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import click_install as gui
from build_click_installer import NAME, build, launcher
from armada_dual_screen_input.i18n import active_language, configure, msg
from armada_dual_screen_input.updates import UpdateError, parse_release, prepare_download
from release import PackageError, archive, seal
from test_updates import release_data

ROOT = Path(__file__).resolve().parents[1]


def launcher_contents(desktop):
    command = shlex.split(next(line[5:] for line in desktop.splitlines() if line.startswith('Exec=')))
    encoded = command[-1].split("b64decode('", 1)[1].split("'", 1)[0]
    code = base64.b64decode(encoded).decode()
    payload_text = code.split("b64decode('", 1)[1].split("'", 1)[0]
    payload = base64.b64decode(payload_text)
    with zipfile.ZipFile(io.BytesIO(payload)) as zipped:
        files = {name: zipped.read(name) for name in zipped.namelist()}
    return (files, command[:-1], code.replace(payload_text, '<payload>'),
            command[-1].replace(encoded, '<helper>'))


class ClickInstallTests(unittest.TestCase):
    def setUp(self):
        previous = active_language()
        configure('en_US')
        self.addCleanup(configure, previous)

    def test_review_then_install_pins_release_and_blocks_duplicate_actions(self):
        release = SimpleNamespace(tag='v0.2.0')
        fetch, host, install = Mock(return_value=release), Mock(), Mock(return_value={})
        session = gui.InstallSession(fetch=fetch, check_host=host, install=install)
        jobs = []
        self.assertFalse(session.start('install', launch=jobs.append))
        self.assertTrue(session.start('check', launch=jobs.append))
        self.assertFalse(session.start('check', launch=jobs.append))
        self.assertFalse(session.start('install', launch=jobs.append))

        jobs.pop()()
        host.assert_called_once_with()
        self.assertEqual(session.phase, 'ready')
        install.assert_not_called()
        self.assertIn('v0.2.0', session.message)
        self.assertTrue(session.start('install', launch=jobs.append))
        self.assertFalse(session.start('install', launch=jobs.append))
        jobs.pop()()
        self.assertIs(install.call_args.args[0], release)
        fetch.assert_called_once_with()
        self.assertEqual(session.phase, 'success')
        self.assertFalse(session.start('install', launch=jobs.append))

    def test_initial_window_uses_smallest_logical_workarea_with_decoration_space(self):
        monitors = [SimpleNamespace(get_workarea=lambda: SimpleNamespace(width=443, height=386)),
                    SimpleNamespace(get_workarea=lambda: SimpleNamespace(width=1422, height=800))]
        display = SimpleNamespace(get_n_monitors=lambda: len(monitors), get_monitor=lambda i: monitors[i])
        width, height = gui.window_size(display)
        self.assertLess(width, 443)
        self.assertLess(height + 40, 386)
        self.assertEqual((width, height), gui.window_size(display, (443, 386)))
        self.assertEqual(gui.window_size(display, (1422, 800)), (540, 440))

    def test_unsupported_host_stops_before_network_and_retry_rechecks(self):
        host = Mock(side_effect=[PackageError('Unsupported device'), None])
        fetch = Mock(return_value=SimpleNamespace(tag='v0.2.0'))
        session = gui.InstallSession(check_host=host, fetch=fetch)
        session.start('check', launch=lambda job: job())
        self.assertEqual(session.phase, 'error')
        self.assertIn('Unsupported', str(session.details))
        fetch.assert_not_called()
        session.start('check', launch=lambda job: job())
        self.assertEqual(session.phase, 'ready')
        self.assertEqual(session.details, '')
        self.assertEqual(host.call_count, 2)

    def test_error_identity_and_success_cache_notice_follow_language_switch(self):
        session = gui.InstallSession(check_host=lambda: None,
                                     fetch=Mock(side_effect=UpdateError(msg('update.network'))))
        session.start('check', launch=lambda job: job())
        english = session.message, str(session.details)
        configure('zh_CN')
        self.assertNotEqual(english, (session.message, str(session.details)))
        session.fetch = lambda: SimpleNamespace(tag='v0.2.0')
        session.install = lambda *a, **kw: {'desktop_refresh': {'warnings': ['fixture']}}
        session.start('check', launch=lambda job: job())
        session.start('install', launch=lambda job: job())
        self.assertEqual(session.phase, 'success')
        self.assertEqual(session.message_key, 'installer.success_refresh')

    def fixture_release(self, work, *, revision='a' * 40, tamper=False, version='0.2.0'):
        tree = work / 'armada-dual-screen-input-0.2.0-aarch64'
        tree.mkdir()
        (tree / 'VERSION').write_text(version + '\n')
        (tree / 'tools').mkdir()
        (tree / 'tools/manage.py').write_text('# Fixture; never executed\n')
        seal(tree, revision=revision)
        if tamper:
            (tree / 'tools/manage.py').write_text('# Tampered\n')
        packed = work / 'package.tar.gz'
        archive(tree, packed)
        binary = packed.read_bytes()
        data = release_data()
        filename = data['assets'][0]['name']
        checksums = (hashlib.sha256(binary).hexdigest() + '  ' + filename + '\n').encode()
        for asset, body in zip(data['assets'], (binary, checksums)):
            asset.update(size=len(body), digest='sha256:' + hashlib.sha256(body).hexdigest())
        release = parse_release(data)
        bodies = {release.archive_url: binary, release.checksum_url: checksums}
        return release, bodies

    def test_verified_download_installs_offline_without_token_and_cleans_temporary_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            release, bodies = self.fixture_release(Path(directory))
            roots, phases = [], []
            def prepare(release, work):
                roots.append(work)
                return prepare_download(release, work, opener=lambda url: io.BytesIO(bodies[url]))
            def run(command, **kwargs):
                self.assertEqual(command[:5], ['/usr/bin/python3', '-E', '-s', '-B', str(kwargs['cwd'] / 'tools/manage.py')])
                self.assertEqual(command[5:], ['install', '--offline'])
                for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'PYTHONPATH', 'PYTHONHOME'):
                    self.assertNotIn(name, kwargs['env'])
                self.assertTrue((kwargs['cwd'] / 'manifest.json').is_file())
                return SimpleNamespace(returncode=0, stdout='{"started": false}')
            with patch.dict(gui.os.environ, {'GH_TOKEN': 'fixture', 'GITHUB_TOKEN': 'fixture',
                                            'PYTHONPATH': '/fixture', 'PYTHONHOME': '/fixture'}):
                result = gui.install_release(release, status=phases.append, prepare=prepare,
                                             run=run, check_host=lambda: None)
            self.assertFalse(result['started'])
            self.assertEqual(phases, ['installer.downloading', 'installer.verifying', 'installer.installing'])
            self.assertTrue(all(not path.exists() for path in roots))

    def test_invalid_download_manifest_version_or_revision_never_runs_installer(self):
        for options in ({'tamper': True}, {'version': '0.1.0'}, {'revision': 'a'*40+'-dirty'}, {'corrupt': True}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                args = {k: v for k, v in options.items() if k != 'corrupt'}
                release, bodies = self.fixture_release(Path(directory), **args)
                if options.get('corrupt'):
                    bodies[release.archive_url] += b'tampered'
                run = Mock()
                roots = []
                def prepare(release, work):
                    roots.append(work)
                    return prepare_download(release, work, opener=lambda url: io.BytesIO(bodies[url]))
                with self.assertRaises((UpdateError, PackageError)):
                    gui.install_release(release, status=lambda key: None, prepare=prepare,
                                        check_host=lambda: None, run=run)
                run.assert_not_called()
                self.assertTrue(all(not path.exists() for path in roots))

    def test_install_failure_cleans_download_and_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            release, bodies = self.fixture_release(Path(directory))
            roots = []
            def prepare(release, work):
                roots.append(work)
                return prepare_download(release, work, opener=lambda url: io.BytesIO(bodies[url]))
            with self.assertRaisesRegex(PackageError, 'fixture failure'):
                gui.install_release(release, status=lambda key: None, prepare=prepare, check_host=lambda: None,
                    run=lambda *a, **kw: SimpleNamespace(returncode=1, stderr='fixture failure', stdout=''))
            self.assertTrue(all(not path.exists() for path in roots))

    def test_launcher_is_reproducible_self_contained_and_runs_outside_checkout(self):
        desktop = launcher(ROOT)
        self.assertEqual(desktop, launcher(ROOT))
        tracked = (ROOT / NAME).read_text()
        # zlib versions can encode the same source differently across Mac/Linux.
        self.assertEqual(launcher_contents(tracked), launcher_contents(desktop),
                         'Regenerate the homepage launcher with --output .')
        self.assertEqual([line for line in tracked.splitlines() if not line.startswith('Exec=')],
                         [line for line in desktop.splitlines() if not line.startswith('Exec=')])
        self.assertIn('Terminal=false', desktop)
        command = shlex.split(next(line[5:] for line in desktop.splitlines() if line.startswith('Exec=')))
        self.assertNotIn('%', command[-1])
        # Inspect the actual embedded payload without executing any of its code.
        names = launcher_contents(desktop)[0]
        self.assertIn('LICENSE', names)
        self.assertIn('armada_dual_screen_input/ui_catalogs.py', names)
        self.assertFalse(any(name.startswith(('extras/', 'vendor/', 'runtime/', '.git/')) for name in names))
        with tempfile.TemporaryDirectory(prefix='launcher test ') as directory:
            target = build(ROOT, directory)
            self.assertEqual(target.name, NAME)
            # Download directories may contain unrelated Python files. They
            # must not shadow stdlib modules before the embedded helper starts.
            (Path(directory) / 'base64.py').write_text('raise RuntimeError("cwd module was imported")\n')
            # System Python is the target path; use the test runtime on Mac.
            command[0] = sys.executable
            result = subprocess.run([*command, '--help'], cwd=directory, capture_output=True, text=True,
                                    env=dict(gui.os.environ, TMPDIR=directory))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--preview', result.stdout)
            self.assertEqual(list(Path(directory).glob('ads-click-helper-*')), [])


@unittest.skipUnless(sys.platform == 'linux', 'Installer layout needs Linux GTK and a display')
class ClickInstallerLayoutTests(unittest.TestCase):
    def test_both_languages_and_states_fit_own_offscreen_window(self):
        if not gui.os.environ.get('DISPLAY'):
            self.skipTest('No display; run under xvfb-run for installer layout checks')
        # PanelApp forces Wayland at import. GTK window checks need a fresh
        # interpreter so they neither inherit nor modify the panel's backend.
        code = ('import sys,unittest;sys.path[:0]=["src","tools","tests"];'
                'from test_click_install import render_layouts;render_layouts(unittest.TestCase())')
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                env=dict(gui.os.environ, GDK_BACKEND='x11'), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


def render_layouts(case):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    case.assertTrue(Gtk.init_check(None)[0], 'Could not initialize Xvfb GTK display')
    for language, available in ((language, size) for language in ('en_US', 'zh_CN')
                                for size in ((1024, 768), (443, 386))):
        for phase in ('ready', 'installing', 'success', 'error'):
            with case.subTest(language=language, phase=phase, available=available):
                configure(language)
                session = gui.InstallSession()
                session.phase = phase
                session.message = msg({'ready': 'installer.ready', 'installing': 'installer.installing',
                    'success': 'installer.success', 'error': 'installer.failed'}[phase], **(
                        {'tag': 'v123.456.789'} if phase in ('ready', 'success') else {}))
                session.details = msg('update.network') if phase == 'error' else ''
                window = gui.create_window(session, Gtk, GLib, offscreen=True, available_size=available)
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                width, height = window.initial_size
                case.assertLessEqual(window.get_allocated_width(), width)
                case.assertLessEqual(window.get_allocated_height(), height)
                for label in (window.title_label, window.scope, window.status):
                    layout = label.get_layout()
                    case.assertEqual(layout.get_unknown_glyphs_count(), 0)
                    case.assertLessEqual(layout.get_pixel_size()[0], label.get_allocated_width())
                    case.assertLessEqual(layout.get_pixel_size()[1], label.get_allocated_height())
                case.assertEqual(window.close_button.get_sensitive(), not session.busy)
                case.assertEqual(window.action.get_visible(), phase != 'success')
                for control in (window.languages, window.close_button, window.action):
                    if not control.get_visible():
                        continue
                    x, y = control.translate_coordinates(window, 0, 0)
                    case.assertGreaterEqual(x, 0)
                    case.assertGreaterEqual(y, 0)
                    case.assertLessEqual(x + control.get_allocated_width(), width)
                    case.assertLessEqual(y + control.get_allocated_height(), height)
                window.destroy()


if __name__ == '__main__':
    unittest.main()
