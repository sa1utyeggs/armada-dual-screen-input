import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from armada_dual_screen_input.gamescope_target import GamescopeTarget
from armada_dual_screen_input.canonical_path import canonical_path


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


class TargetValidationTests(unittest.TestCase):
    """Exercise fresh identity checks using real temporary Unix sockets."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='adt-')
        self.addCleanup(self.directory.cleanup)
        self.parent = Path(self.directory.name).resolve()
        self.runtime = self.parent/'run'
        self.runtime.mkdir()
        self.open_socket('a')
        self.open_socket('a-ei')
        self.alias = self.runtime/'gamescope-primary'
        self.alias.symlink_to('a')
        self.target = GamescopeTarget.resolve(self.runtime)
        self.assertTrue(self.target.is_current())

    def open_socket(self, name, directory=None):
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        sock.bind(str((directory or self.runtime)/name))

    def test_direct_socket_and_canonical_runtime_alias_remain_accepted(self):
        target = GamescopeTarget.resolve(self.runtime, 'a')
        self.assertTrue(target.is_current())
        alias = self.parent/'alias'
        alias.symlink_to('run', target_is_directory=True)
        self.assertEqual(GamescopeTarget.resolve(alias, 'a'), target)

    def test_equivalent_local_alias_is_valid_but_each_retarget_is_rechecked(self):
        self.alias.unlink()
        self.assertFalse(self.target.is_current())
        self.alias.symlink_to('./a')
        self.assertTrue(self.target.is_current())
        self.open_socket('b')
        self.open_socket('b-ei')
        self.alias.unlink()
        self.alias.symlink_to('b')
        self.assertFalse(self.target.is_current())

    def test_either_socket_replacement_is_detected_at_the_same_path(self):
        for name in ('a', 'a-ei'):
            with self.subTest(name=name):
                path = self.runtime/name
                saved = self.runtime/'saved'
                path.rename(saved)  # Keep the old inode present during replacement.
                self.open_socket(name)
                self.assertFalse(self.target.is_current())
                path.unlink()
                saved.rename(path)
                self.assertTrue(self.target.is_current())

    def test_endpoint_replaced_during_partner_lookup_uses_fresh_identity(self):
        original = canonical_path
        replaced = False
        def resolve(path, *args, **kwargs):
            nonlocal replaced
            result = original(path, *args, **kwargs)
            if path == self.runtime/'a-ei' and not replaced:
                replaced = True
                (self.runtime/'a').rename(self.runtime/'saved')
                self.open_socket('a')
            return result
        with patch('armada_dual_screen_input.gamescope_probe.canonical_path', resolve):
            self.assertFalse(self.target.is_current())
        self.assertTrue(replaced)

    def test_missing_or_regular_file_endpoint_cannot_reuse_old_validation(self):
        for name in ('a', 'a-ei'):
            with self.subTest(name=name):
                path = self.runtime/name
                saved = self.runtime/'saved'
                path.rename(saved)
                self.assertFalse(self.target.is_current())
                path.write_text('not a socket')
                self.assertFalse(self.target.is_current())
                path.unlink()
                saved.rename(path)
                self.assertTrue(self.target.is_current())

    def test_either_endpoint_alias_cannot_escape_runtime(self):
        outside = self.parent/'other'
        outside.mkdir()
        self.open_socket('a', outside)
        self.open_socket('a-ei', outside)
        for name in ('a', 'a-ei'):
            with self.subTest(name=name):
                path = self.runtime/name
                saved = self.runtime/'saved'
                path.rename(saved)
                path.symlink_to(outside/name)
                self.assertFalse(self.target.is_current())
                path.unlink()
                saved.rename(path)
                self.assertTrue(self.target.is_current())

    def test_canonical_runtime_retarget_is_detected_even_for_original_sockets(self):
        previous = self.parent/'previous'
        self.runtime.rename(previous)
        self.runtime.symlink_to(previous, target_is_directory=True)
        self.assertFalse(self.target.is_current())

    def test_runtime_must_still_be_a_directory(self):
        self.runtime.rename(self.parent/'previous')
        self.runtime.write_text('not a directory')
        self.assertFalse(self.target.is_current())

    def test_current_owner_is_checked_for_runtime_and_both_endpoints(self):
        original = Path.stat
        for changed in (self.runtime, self.runtime/'a', self.runtime/'a-ei'):
            with self.subTest(changed=changed.name):
                def stat(path, *args, **kwargs):
                    info = original(path, *args, **kwargs)
                    if path == changed:
                        fields = list(info)
                        fields[4] = info.st_uid+1
                        return os.stat_result(fields)
                    return info
                with patch.object(Path, 'stat', stat):
                    self.assertFalse(self.target.is_current())
                self.assertTrue(self.target.is_current())

    def test_failed_metadata_read_does_not_reuse_previous_success(self):
        original = Path.stat
        for changed in (self.runtime, self.runtime/'a', self.runtime/'a-ei'):
            with self.subTest(changed=changed.name):
                def stat(path, *args, **kwargs):
                    if path == changed:
                        raise PermissionError('metadata unavailable')
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'stat', stat):
                    self.assertFalse(self.target.is_current())
                self.assertTrue(self.target.is_current())
