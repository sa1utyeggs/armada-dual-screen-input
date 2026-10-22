import ctypes as c
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.canonical_path import canonical_path


class CanonicalPathTests(unittest.TestCase):
    def test_symlinks_and_replacements_are_resolved_afresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'a').mkdir(); (root/'b').mkdir()
            alias = root/'alias'; alias.symlink_to('a')
            self.assertEqual(canonical_path(alias), (root/'a').resolve())
            alias.unlink(); alias.symlink_to('b')
            self.assertEqual(canonical_path(alias), (root/'b').resolve())
            alias.unlink(); alias.symlink_to('missing')
            with self.assertRaises(FileNotFoundError): canonical_path(alias)

    def test_native_result_is_freed_and_undecodable_names_round_trip(self):
        value = c.create_string_buffer(b'/run/user/test-\xff')
        api = SimpleNamespace(realpath=Mock(return_value=c.addressof(value)), free=Mock())
        with patch('armada_dual_screen_input.canonical_path._native_api', return_value=api):
            import os
            self.assertEqual(os.fsencode(canonical_path(Path('/unused'))), value.value)
        api.free.assert_called_once_with(c.addressof(value))

    def test_native_error_and_null_paths_do_not_reuse_prior_success(self):
        api = SimpleNamespace(realpath=Mock(return_value=None), free=Mock())
        with patch('armada_dual_screen_input.canonical_path._native_api', return_value=api), \
             patch('armada_dual_screen_input.canonical_path.c.get_errno', return_value=13):
            with self.assertRaises(PermissionError): canonical_path(Path('/denied'))
            with self.assertRaises(ValueError): canonical_path(Path('/bad\0name'))
        api.free.assert_not_called()
        self.assertEqual(api.realpath.call_count, 1)

    def test_portable_fallback_is_still_strict(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('armada_dual_screen_input.canonical_path._native_api', return_value=None):
            root = Path(directory)
            self.assertEqual(canonical_path(root), root.resolve())
            with self.assertRaises(FileNotFoundError): canonical_path(root/'missing')
