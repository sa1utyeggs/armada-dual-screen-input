"""Cache refresh targets private Plasma buses and cannot fail an installation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from desktop_cache import plasma_sessions, refresh_desktop
from manage import Paths


class DesktopCacheTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(); self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.proc = self.work / 'proc'; self.proc.mkdir()
        home = self.work / 'home with spaces'
        self.paths = Paths(home, home / '.local/share', home / '.config', home / '.local/bin', home / 'Desktop')
        (self.paths.data / 'icons/hicolor/scalable/apps').mkdir(parents=True)

    def process(self, pid='123', name='plasmashell', bus='unix:path=/tmp/private-plasma-bus'):
        root = self.proc / pid; root.mkdir()
        (root / 'comm').write_text(name + '\n')
        (root / 'cmdline').write_bytes(b'plasmashell\0-p\0org.kde.plasma.mobileshell\0')
        (root / 'environ').write_bytes(('DBUS_SESSION_BUS_ADDRESS=' + bus + '\0LANG=zh_CN.UTF-8\0TOKEN=do-not-copy\0').encode())
        return root

    def test_discovers_private_same_user_bus_without_copying_secrets(self):
        self.process()
        self.process(pid='124', name='steam')
        self.process(pid='125', bus='tcp:host=example.invalid')
        (self.proc / '126').mkdir()  # Process disappearing during discovery.
        sessions = plasma_sessions(self.proc)
        self.assertEqual(sessions, [({'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/private-plasma-bus',
                                     'LANG': 'zh_CN.UTF-8'}, True)])
        self.assertEqual(plasma_sessions(self.proc, uid=os.getuid() + 1), [])

    def test_private_session_gets_menu_and_icon_notifications_without_restart(self):
        sessions = [({'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/private-bus', 'LANG': 'zh_CN.UTF-8'}, True)]
        with patch('desktop_cache.sys.platform', 'linux'), \
             patch('desktop_cache.plasma_sessions', return_value=sessions), \
             patch('desktop_cache.shutil.which', side_effect=lambda name: '/usr/bin/' + name), \
             patch('desktop_cache.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            result = refresh_desktop(self.paths)
        calls = run.call_args_list
        self.assertEqual([Path(c.args[0][0]).name for c in calls],
                         ['gtk-update-icon-cache', 'kbuildsycoca6', 'gdbus'])
        self.assertIn(str(self.paths.data / 'icons/hicolor'), calls[0].args[0])
        self.assertEqual(calls[1].kwargs['env']['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=/tmp/private-bus')
        self.assertEqual(calls[1].kwargs['env']['LANG'], 'zh_CN.UTF-8')
        self.assertIn('unix:path=/tmp/private-bus', calls[2].args[0])
        self.assertEqual(result['sessions_notified'], 1)
        self.assertTrue(result['mobile_session_active'])
        self.assertEqual(result['warnings'], [])
        self.assertTrue(all(c.kwargs['timeout'] <= 5 for c in calls))
        self.assertFalse(any('systemctl' in str(c.args[0]) or 'refreshCurrentShell' in str(c.args[0]) for c in calls))

    def test_missing_failed_and_timed_out_helpers_are_warnings(self):
        for failure in ('missing', 'failed', 'timeout'):
            with self.subTest(failure=failure), patch('desktop_cache.sys.platform', 'linux'), \
                 patch('desktop_cache.plasma_sessions', return_value=[]), \
                 patch('desktop_cache.shutil.which', return_value=None if failure == 'missing' else '/usr/bin/helper'), \
                 patch('desktop_cache.subprocess.run', return_value=SimpleNamespace(returncode=1),
                       side_effect=subprocess.TimeoutExpired('helper', 5) if failure == 'timeout' else None):
                result = refresh_desktop(self.paths)
                self.assertTrue(result['warnings'])
                self.assertEqual(result['sessions_notified'], 0)

    def test_headless_install_rebuilds_disk_cache_without_gui_or_bus_changes(self):
        with patch('desktop_cache.sys.platform', 'linux'), \
             patch('desktop_cache.plasma_sessions', return_value=[]), \
             patch('desktop_cache.shutil.which', side_effect=lambda name: '/usr/bin/' + name), \
             patch('desktop_cache.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            result = refresh_desktop(self.paths)
        self.assertEqual([Path(c.args[0][0]).name for c in run.call_args_list],
                         ['gtk-update-icon-cache', 'kbuildsycoca6'])
        self.assertFalse(result['mobile_session_active'])


if __name__ == '__main__':
    unittest.main()
