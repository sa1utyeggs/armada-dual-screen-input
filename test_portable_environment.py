"""Keep required GTK runtime local without activating obsolete capture plugins."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import supervisor


class PortableEnvironmentTests(unittest.TestCase):
    def test_leftover_capture_plugin_does_not_activate_or_create_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / 'lib/gstreamer-1.0/libgstpipewire.so'
            plugin.parent.mkdir(parents=True)
            plugin.touch()
            original = {'XDG_CACHE_HOME': str(root / 'cache'), 'WAYLAND_DISPLAY': 'lower'}
            with patch.object(supervisor, 'PORTABLE_LIB', root / 'lib'):
                env = supervisor.portable_environment(original)
            self.assertEqual(env, original)
            self.assertFalse((root / 'cache').exists())

    def test_required_gtk_runtime_is_still_scoped_to_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'libgtk-layer-shell.so.0').touch()
            original = {'WAYLAND_DISPLAY': 'lower'}
            with patch.object(supervisor, 'PORTABLE_LIB', root):
                env = supervisor.portable_environment(original)
            self.assertEqual(original, {'WAYLAND_DISPLAY': 'lower'})
            self.assertEqual(env['LD_LIBRARY_PATH'], str(root))
            self.assertEqual(env['GI_TYPELIB_PATH'], str(root / 'girepository-1.0'))
            self.assertNotIn('GST_PLUGIN_PATH', env)
            self.assertNotIn('GST_REGISTRY', env)
