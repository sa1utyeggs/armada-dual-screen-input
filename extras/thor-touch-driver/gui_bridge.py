#!/usr/bin/env python3
"""Optional root-owned driver bridge; no application bundle or boot integration.

Installed separately. Public status needs no root. Only apply/revert require
administrator authentication, and neither accepts a module path from the GUI.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys

ROOT = Path('/var/lib/armada-touch-fix-ui')
DATA = Path('/var/lib/armada-touch-fix')


def secure(path, directory=False):
    info = path.lstat()
    if (info.st_uid != 0 or info.st_mode & 0o022 or
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError('Unsafe driver component: ' + str(path))


def load_component(root=ROOT):
    for directory in (root.parent.parent, root.parent, root):
        secure(directory, True)
    for name in ('component.json', 'gui_bridge.py', 'touchfix.py'):
        secure(root / name)
    if (root/'component.json').stat().st_size > 16384:
        raise ValueError('Oversized driver component metadata')
    metadata = json.loads((root/'component.json').read_text())
    if metadata.get('schema') != 1 or metadata.get('component') != 'armada-thor-touch-fix-ui':
        raise ValueError('Unknown driver component')
    for name in ('gui_bridge.py', 'touchfix.py'):
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != metadata['files'][name]:
            raise ValueError('Driver component checksum mismatch')
    if not re.fullmatch('[0-9a-f]{64}', metadata.get('module_sha256', '')):
        raise ValueError('Invalid module identity')
    host = metadata.get('host')
    if (not isinstance(host, dict) or set(host) != {'kernel_release', 'architecture',
            'kernel_notes_sha256', 'kernel_config_sha256'} or
            any(not isinstance(value, str) or not value for value in host.values())):
        raise ValueError('Invalid kernel compatibility metadata')
    spec = importlib.util.spec_from_file_location('thor_driver_control', root/'touchfix.py')
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    return metadata, control


def status(metadata, system):
    profile = system.profile()
    lower, upper = system.targets()
    compatible = ('ayn,thor' in profile['board_compatible'] and
                  all(profile.get(k) == v for k, v in metadata['host'].items()) and
                  not profile['modules_disabled'] and
                  system.driver(lower) in ('edt_ft5x06', 'armada_thor_ft5452') and
                  system.driver(upper) == 'edt_ft5x06')
    return {'schema': 1, 'component': True, 'compatible': compatible,
            'active': system.driver(lower) == 'armada_thor_ft5452',
            'kernel': profile['kernel_release'], 'lower_driver': system.driver(lower),
            'upper_driver': system.driver(upper), 'autoload': False}


def perform(action, metadata, control, system=None):
    if action not in ('status', 'apply', 'revert'):
        raise ValueError('Unknown driver action')
    system = system or control.Linux()
    if action == 'status':
        return status(metadata, system)
    control.Linux.admin()
    if action == 'apply':
        package = control.Package(DATA/'packages'/metadata['module_sha256'])
        if package.manifest['sha256'] != metadata['module_sha256']:
            raise ValueError('Wrong fixed driver package')
        package.verify(system)  # Full fingerprints and payload checks before writes.
    else:
        package = None
    store = control.Store()
    with store.lock():
        controller = control.Controller(system, store)
        if action == 'apply':
            previous = store.read()
            if (system.loaded() and system.driver(system.targets()[0]) == control.MODULE
                    and previous.get('module_sha256') == metadata['module_sha256']):
                return status(metadata, system)  # Already active: no needless rebind.
            controller.apply(package)
        elif action == 'revert':
            controller.revert()
        else:
            raise ValueError('Unknown driver action')
    return status(metadata, system)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'apply', 'revert'))
    args = parser.parse_args()
    try:
        metadata, control = load_component()
        # Ordinary command stalls are bounded in the privileged process, which
        # owns and can terminate its modinfo/insmod/rmmod children. A hung or
        # panicking kernel still requires reboot into the unchanged kernel.
        class BoundedLinux(control.Linux):
            @staticmethod
            def run(name, *values):
                executable = next((Path(p)/name for p in ('/usr/sbin', '/sbin', '/usr/bin')
                                   if (Path(p)/name).is_file()), None)
                if executable is None:
                    raise ValueError('Missing module command')
                return subprocess.check_output([str(executable), *map(str, values)],
                                               text=True, timeout=10).strip()
        def interrupted(*_):
            raise KeyboardInterrupt
        if args.action != 'status':
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                signal.signal(sig, interrupted)
        print(json.dumps(perform(args.action, metadata, control, BoundedLinux())), flush=True)
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({'schema': 1, 'error': str(error)[:240] or 'Interrupted'}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
