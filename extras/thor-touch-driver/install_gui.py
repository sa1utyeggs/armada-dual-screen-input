#!/usr/bin/env python3
"""Explicit one-time optional GUI-component installation; never loads a driver."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

BASE = Path(__file__).resolve().parent
ROOT = Path('/var/lib/armada-touch-fix-ui')


def install(package_directory, *, root=ROOT):
    if os.geteuid() != 0:
        raise ValueError('Run this optional component installer with sudo')
    spec = importlib.util.spec_from_file_location('driver_gui_bridge', BASE/'gui_bridge.py')
    bridge = importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge)
    spec = importlib.util.spec_from_file_location('driver_package_control', BASE/'touchfix.py')
    control = importlib.util.module_from_spec(spec); spec.loader.exec_module(control)
    package = control.Package(package_directory)
    package.verify(control.Linux())
    # Persist the already verified module separately from app releases.
    store = control.Store()
    with store.lock():
        store.save(package)
        for directory in (root.parent.parent, root.parent):
            bridge.secure(directory, True)
        existed = root.exists() or root.is_symlink()
        if existed:
            bridge.load_component(root)  # Refuse an unowned/modified installation.
        else:
            root.mkdir(mode=0o755)
        bridge.secure(root, True)
        files = {name: (BASE/name).read_bytes() for name in ('gui_bridge.py', 'touchfix.py')}
        metadata = {'schema': 1, 'component': 'armada-thor-touch-fix-ui',
                    'module_sha256': package.manifest['sha256'], 'host': package.manifest['host'],
                    'autoload': False, 'files': {n: hashlib.sha256(b).hexdigest() for n,b in files.items()}}
        files['component.json'] = (json.dumps(metadata, indent=2)+'\n').encode()
        original = {name: (root/name).read_bytes() if (root/name).exists() else None for name in files}
        def write(name, data):
            fd, temporary = tempfile.mkstemp(prefix='.install-', dir=root)
            try:
                with os.fdopen(fd, 'wb') as out:
                    out.write(data); out.flush(); os.fsync(out.fileno())
                os.chmod(temporary, 0o644)
                os.replace(temporary, root/name)
            finally:
                Path(temporary).unlink(missing_ok=True)
        try:
            for name,data in files.items():
                write(name, data)
            bridge.load_component(root)
        except BaseException:
            for name,data in original.items():
                if data is None:
                    (root/name).unlink(missing_ok=True)
                else:
                    write(name, data)
            if not existed:
                root.rmdir()
            raise
    return {'installed': str(root), 'driver_changed': False, 'autoload': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.package)))
