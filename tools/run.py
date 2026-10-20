#!/usr/bin/env python3
"""Launch this source/bundle without pip or global Python path changes."""
from pathlib import Path
import os
import runpy
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src'))
os.environ['PYTHONPATH'] = str(root / 'src')
runpy.run_module('armada_dual_screen_input.supervisor', run_name='__main__')
