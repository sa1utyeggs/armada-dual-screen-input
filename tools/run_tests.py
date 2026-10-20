#!/usr/bin/env python3
"""Run isolated tests; never launch the panel or create an input device."""
from pathlib import Path
import os
import subprocess
import sys
import unittest

root = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(root / 'src'), str(root / 'tools')]
suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
result = unittest.TextTestRunner(verbosity=1).run(suite)
node = subprocess.run(['node', '--test', str(root / 'tests/test_steam_keyboard_guard.js')],
                      cwd=root, check=False) if '--with-node' in sys.argv else None
raise SystemExit(0 if result.wasSuccessful() and (node is None or node.returncode == 0) else 1)
