#!/usr/bin/env python3
"""Run the independent mirrored-touch prototype in Armada Game Mode.

Dependency paths are explicitly supplied and affect only the child process.
The known upper XWayland display must be selected explicitly for this prototype.
Nothing is installed, enabled at login, or written to the existing panel config.
"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys

from gamescope_probe import probe_display
from session_detect import detect_target_session
from supervisor import child_environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--x-display', required=True)
    parser.add_argument('--upper-display', default='gamescope-primary')
    parser.add_argument('--runtime-root', type=Path,
                        help='private dependency root containing usr/lib64')
    parser.add_argument('--gtk-runtime-root', type=Path,
                        help='optional separate GTK layer-shell dependency root')
    parser.add_argument('--quit-after', type=float, default=0, help='bounded development smoke run')
    parser.add_argument('--proof', type=Path, help='explicit development-only preview PNG')
    parser.add_argument('--fps', type=int, choices=(30, 60), default=60)
    args = parser.parse_args()
    if not sys.platform.startswith('linux') or os.getuid() == 0:
        parser.error('run as the normal handheld Linux user')
    target = detect_target_session(game_only=True)
    if target is None:
        parser.error('no unambiguous Armada Game Mode bottom session')
    result = probe_display(target.runtime_dir, args.upper_display)
    if result.get('status') != 'node_advertised':
        parser.error('upper Gamescope did not advertise a capture node')
    env = child_environment(target)
    if args.runtime_root:
        lib = args.runtime_root.resolve(strict=True) / 'usr/lib64'
        plugin = lib / 'gstreamer-1.0'
        if not (plugin / 'libgstpipewire.so').is_file():
            parser.error('private pipewiresrc plugin is missing')
        env['GST_PLUGIN_PATH'] = str(plugin)
        env['GST_REGISTRY'] = str(args.runtime_root.resolve().parent / 'gst-registry.bin')
    if args.gtk_runtime_root:
        lib = args.gtk_runtime_root.resolve(strict=True) / 'usr/lib64'
        if not (lib / 'libgtk-layer-shell.so.0').is_file():
            parser.error('private GTK layer-shell library is missing')
        env['LD_LIBRARY_PATH'] = str(lib)
        env['GI_TYPELIB_PATH'] = str(lib / 'girepository-1.0')
    base = Path(__file__).resolve().parent
    command = [sys.executable, '-B', str(base / 'mirror_preview.py'),
               '--node', str(result['pipewire_node_id']),
               '--upper-display', args.upper_display, '--x-display', args.x_display,
               '--quit-after', str(args.quit_after), '--fps', str(args.fps)]
    if args.proof:
        command += ['--proof', str(args.proof.resolve())]
    with (target.runtime_dir / 'armada-mirror-preview.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('A mirrored-touch preview is already running')
            return 0
        return subprocess.call(command, cwd=base, env=env)


if __name__ == '__main__':
    raise SystemExit(main())
