"""Private capture dependencies must not leak into the caller's environment."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import supervisor


class MirrorEnvironmentTests(unittest.TestCase):
    def test_plugin_is_child_only_and_registry_is_in_user_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / 'lib/gstreamer-1.0/libgstpipewire.so'
            plugin.parent.mkdir(parents=True)
            plugin.touch()
            original = {'XDG_CACHE_HOME': str(root / 'cache'), 'WAYLAND_DISPLAY': 'lower'}
            with patch.object(supervisor, 'PORTABLE_LIB', root / 'lib'):
                env = supervisor.portable_environment(original)
            self.assertNotIn('GST_PLUGIN_PATH', original)
            self.assertNotIn('GST_REGISTRY', original)
            self.assertEqual(env['GST_PLUGIN_PATH'], str(plugin.parent))
            self.assertEqual(Path(env['GST_REGISTRY']).parent, root / 'cache/thor-panel')
            self.assertNotIn('LD_LIBRARY_PATH', env)
            self.assertEqual(env['WAYLAND_DISPLAY'], 'lower')

    def test_absent_plugin_does_not_create_cache_or_change_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {'XDG_CACHE_HOME': str(root / 'cache')}
            with patch.object(supervisor, 'PORTABLE_LIB', root / 'missing'):
                self.assertEqual(supervisor.portable_environment(original), original)
            self.assertFalse((root / 'cache').exists())


if __name__ == '__main__':
    unittest.main()
