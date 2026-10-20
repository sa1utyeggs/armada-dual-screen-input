#!/usr/bin/env python3
"""Experimental lower-only driver package tool. Default operations are read-only.

No download, boot-file write, autoload rule, service installation, force-load,
physical input read/grab or upper-device bind is implemented here.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time

MODULE = 'armada_thor_ft5452'
ORIGINAL = 'edt_ft5x06'
PAYLOAD = MODULE + '.ko'
DATA = Path('/var/lib/armada-touch-fix')


class Refused(RuntimeError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise Refused(message)


class Package:
    def __init__(self, directory):
        self.directory = Path(directory).resolve(strict=True)
        self.manifest = json.loads((self.directory / 'manifest.json').read_text())
        m = self.manifest
        require(isinstance(m, dict), 'Manifest must be an object')
        require(m.get('schema') == 1 and m.get('module') == MODULE,
                'Unsupported package format/module')
        require(m.get('payload') == PAYLOAD and m.get('experimental') is True,
                'Only the explicit experimental lower-driver payload is allowed')
        require(isinstance(m.get('sha256'), str)
                and re.fullmatch('[0-9a-f]{64}', m['sha256']) is not None,
                'Invalid payload digest')
        host = m.get('host')
        require(isinstance(host, dict) and all(isinstance(host.get(key), str) for key in
                ('kernel_release', 'architecture', 'kernel_notes_sha256', 'kernel_config_sha256')),
                'Missing host compatibility fields')
        require(isinstance(m.get('vermagic'), str) and bool(m['vermagic'].strip()),
                'Missing module vermagic')
        path = self.directory / PAYLOAD
        require(not path.is_symlink(), 'Payload must not be a symlink')
        require(path.stat().st_size <= 4 * 1024 * 1024, 'Payload is unexpectedly large')
        self.payload = path.read_bytes()
        require(sha(self.payload) == m['sha256'], 'Payload checksum mismatch')
        require(len(self.payload) >= 64 and self.payload[:6] == b'\x7fELF\x02\x01'
                and struct.unpack_from('<H', self.payload, 16)[0] == 1
                and struct.unpack_from('<H', self.payload, 18)[0] == 183,
                'Payload must be a relocatable little-endian ELF64 AArch64 module')

    def verify(self, system):
        actual = system.profile()
        require('ayn,thor' in actual['board_compatible'], 'Not an AYN Thor')
        for key in ('kernel_release', 'architecture', 'kernel_notes_sha256', 'kernel_config_sha256'):
            require(actual[key] == self.manifest['host'][key], 'Host mismatch: ' + key)
        require(not actual['modules_disabled'], 'Kernel module loading has been disabled')
        info = system.module_info(self.directory / PAYLOAD)
        require(info['name'] == MODULE and info['vermagic'] == self.manifest['vermagic'],
                'Unexpected module name/vermagic')
        require(info['vermagic'].split()[0] == actual['kernel_release'], 'Wrong kernel release')
        lower, upper = system.targets()
        require(system.driver(lower) in (ORIGINAL, MODULE), 'Unexpected current lower driver')
        require(system.driver(upper) == ORIGINAL, 'Unexpected upper driver; refusing takeover')
        return lower, upper


class Linux:
    def __init__(self):
        require(sys.platform == 'linux', 'This operation requires Linux')

    def profile(self):
        return {
            'kernel_release': os.uname().release,
            'architecture': os.uname().machine,
            'kernel_notes_sha256': sha(Path('/sys/kernel/notes').read_bytes()),
            'kernel_config_sha256': sha(gzip.decompress(Path('/proc/config.gz').read_bytes())),
            'board_compatible': Path('/sys/firmware/devicetree/base/compatible').read_bytes()
                .rstrip(b'\0').decode().split('\0'),
            'modules_disabled': Path('/proc/sys/kernel/modules_disabled').read_text().strip() != '0',
        }

    def targets(self):
        found = {'bottom_touchscreen': [], 'top_touchscreen': []}
        for path in Path('/sys/bus/i2c/devices').iterdir():
            if not re.fullmatch(r'\d+-0038', path.name):
                continue
            node = path / 'of_node'
            try:
                label = (node / 'label').read_bytes().rstrip(b'\0').decode()
                compatibles = (node / 'compatible').read_bytes().rstrip(b'\0').decode().split('\0')
            except FileNotFoundError:
                continue
            expected = {'bottom_touchscreen': 'focaltech,ft5452',
                        'top_touchscreen': 'focaltech,ft5426'}.get(label)
            if expected and expected in compatibles:
                found[label].append(path.name)
        require(all(len(items) == 1 for items in found.values()), 'Touchscreen targets are ambiguous')
        return found['bottom_touchscreen'][0], found['top_touchscreen'][0]

    def driver(self, device):
        path = Path('/sys/bus/i2c/devices') / device / 'driver'
        return path.resolve().name if path.is_symlink() else None

    def inputs(self, device):
        root = Path('/sys/bus/i2c/devices') / device / 'input'
        return tuple(sorted((str(p.resolve()), (p.parent / 'name').read_text().strip())
                            for p in root.glob('input*/event*')))

    def loaded(self):
        return (Path('/sys/module') / MODULE).is_dir()

    @staticmethod
    def run(name, *args):
        path = next((Path(root) / name for root in ('/usr/sbin', '/sbin', '/usr/bin')
                     if (Path(root) / name).is_file()), None)
        require(path is not None, 'Missing system tool: ' + name)
        return subprocess.check_output([str(path), *map(str, args)], text=True).strip()

    def module_info(self, path):
        return {key: self.run('modinfo', '-F', key, path) for key in ('name', 'vermagic')}

    @staticmethod
    def admin():
        require(os.geteuid() == 0, 'Root is required for driver changes')

    def bind(self, driver, device, action):
        self.admin()
        require(driver in (ORIGINAL, MODULE) and action in ('bind', 'unbind'), 'Invalid operation')
        lower, _ = self.targets()
        require(device == lower, 'Only the verified lower touchscreen may be rebound')
        (Path('/sys/bus/i2c/drivers') / driver / action).write_text(device + '\n')

    def load(self, path):
        self.admin()
        self.run('insmod', path)  # No force/version/signature bypass flags.

    def unload(self, lower):
        self.admin()
        driver = Path('/sys/bus/i2c/drivers') / MODULE
        attached = [p.name for p in driver.iterdir()
                    if re.fullmatch(r'\d+-[0-9a-f]{4}', p.name) and p.is_symlink()] if driver.exists() else []
        require(not attached, 'Refusing unload while any device remains attached')
        self.run('rmmod', MODULE)

    def wait_input(self, driver, lower):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if self.driver(lower) == driver and any(label == 'bottom_touchscreen'
                                                     for _, label in self.inputs(lower)):
                return
            time.sleep(.05)
        raise Refused('Lower touchscreen did not become ready with ' + driver)


class Store:
    def __init__(self):
        Linux.admin()
        self.root = DATA
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.secure(self.root)

    @staticmethod
    def secure(path):
        s = path.lstat()
        require(not stat.S_ISLNK(s.st_mode) and s.st_uid == 0 and not s.st_mode & 0o022,
                'Unsafe root-owned storage path: ' + str(path))

    def read(self):
        path = self.root / 'state.json'
        if not path.exists():
            return {}
        self.secure(path)
        return json.loads(path.read_text())

    def write(self, data):
        fd, temporary = tempfile.mkstemp(prefix='state.', dir=self.root)
        temp = Path(temporary)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(self.root / 'state.json')
        finally:
            temp.unlink(missing_ok=True)

    def save(self, package):
        packages = self.root / 'packages'
        packages.mkdir(mode=0o700, exist_ok=True)
        self.secure(packages)
        directory = packages / package.manifest['sha256']
        directory.mkdir(mode=0o700, exist_ok=True)
        self.secure(directory)
        path = directory / PAYLOAD
        if path.exists() or path.is_symlink():
            self.secure(path)
            require(sha(path.read_bytes()) == package.manifest['sha256'], 'Stored payload changed')
        else:
            with path.open('xb') as stream:
                stream.write(package.payload)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o600)
        manifest = directory / 'manifest.json'
        if not manifest.exists():
            with manifest.open('x') as stream:
                json.dump(package.manifest, stream, indent=2)
        return path

    @contextmanager
    def lock(self):
        import fcntl
        fd = os.open(self.root / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)


class Controller:
    def __init__(self, system, store):
        self.system, self.store = system, store

    def upper_snapshot(self, upper):
        return self.system.driver(upper), self.system.inputs(upper)

    def original(self, lower):
        s = self.system
        current = s.driver(lower)
        require(current in (None, ORIGINAL, MODULE), 'Lower device is owned by another driver')
        if current == MODULE:
            s.bind(MODULE, lower, 'unbind')
        if s.driver(lower) is None:
            s.bind(ORIGINAL, lower, 'bind')
        s.wait_input(ORIGINAL, lower)
        if s.loaded():
            s.unload(lower)

    def apply(self, package):
        s = self.system
        lower, upper = package.verify(s)  # Before storing/loading or unbinding.
        before = self.upper_snapshot(upper)
        old = self.store.read()
        if s.loaded():
            require(old.get('phase') in ('active', 'pending'), 'Unmanaged same-name module is loaded')
        path = self.store.save(package)
        state = {'phase': 'pending', 'module_sha256': package.manifest['sha256'],
                 'previous_sha256': old.get('module_sha256')}
        self.store.write(state)
        try:
            self.original(lower)  # Updates first return to the original driver.
            s.load(path)
            require(s.driver(lower) == ORIGINAL, 'Module unexpectedly took a bound device')
            require(before == self.upper_snapshot(upper), 'Upper device changed after module load')
            s.bind(ORIGINAL, lower, 'unbind')
            s.bind(MODULE, lower, 'bind')
            s.wait_input(MODULE, lower)
            require(before == self.upper_snapshot(upper), 'Upper device changed after takeover')
            state['phase'] = 'active'
            self.store.write(state)
            return state
        except BaseException as error:
            try:
                self.original(lower)
                require(before == self.upper_snapshot(upper), 'Upper device changed during recovery')
                state.update(phase='reverted', error=type(error).__name__)
            except BaseException as recovery:
                state.update(phase='recovery-needed', error=type(error).__name__,
                             recovery_error=type(recovery).__name__)
                self.store.write(state)
                raise Refused('Original driver recovery failed; reboot into the unchanged kernel') from recovery
            self.store.write(state)
            raise

    def revert(self):
        require('ayn,thor' in self.system.profile()['board_compatible'], 'Not an AYN Thor')
        lower, upper = self.system.targets()
        before = self.upper_snapshot(upper)
        self.original(lower)
        require(before == self.upper_snapshot(upper), 'Upper device changed during revert')
        old = self.store.read()
        old['phase'] = 'reverted'
        self.store.write(old)
        return old


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'plan', 'apply', 'trial', 'revert'))
    parser.add_argument('package', nargs='?', type=Path)
    parser.add_argument('--experimental', action='store_true', help='Explicitly allow a driver trial')
    parser.add_argument('--seconds', type=int, default=90, help='Trial duration; automatically reverts')
    args = parser.parse_args()
    require(1 <= args.seconds <= 600, 'Trial duration must be 1–600 seconds')
    system = Linux()
    if args.action == 'status':
        lower, upper = system.targets()
        print(json.dumps({'profile': system.profile(), 'lower_driver': system.driver(lower),
                          'upper_driver': system.driver(upper), 'module_loaded': system.loaded()}, indent=2))
        return
    package = Package(args.package) if args.package else None
    if args.action in ('plan', 'apply', 'trial'):
        require(package is not None, 'Provide an extracted driver package directory')
        lower, upper = package.verify(system)
    if args.action == 'plan':
        print(json.dumps({'compatible': True, 'lower': lower, 'upper': upper,
                          'module_sha256': package.manifest['sha256'],
                          'kernel_or_boot_write': False, 'autoload': False}, indent=2))
        return
    Linux.admin()
    require(args.experimental, 'Driver changes require --experimental')
    store = Store()
    with store.lock():
        controller = Controller(system, store)
        if args.action == 'revert':
            print(json.dumps(controller.revert()))
            return
        if args.action == 'apply':
            print(json.dumps(controller.apply(package)))
            return
        # One foreground process owns the trial and its recovery. No boot rule,
        # detached daemon, timer unit or future script in a user-writable path.
        def interrupted(*_):
            raise KeyboardInterrupt
        signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        previous = {sig: signal.signal(sig, interrupted) for sig in signals}
        changed = False
        try:
            print(json.dumps(controller.apply(package)), flush=True)
            changed = True
            print(f'Experimental trial active; reverting in {args.seconds}s. Ctrl+C reverts now.', flush=True)
            time.sleep(args.seconds)
        finally:
            for sig in signals:
                signal.signal(sig, signal.SIG_IGN)
            try:
                if changed:
                    print(json.dumps(controller.revert()), flush=True)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)


if __name__ == '__main__':
    try:
        main()
    except (Refused, OSError, ValueError, subprocess.CalledProcessError, KeyboardInterrupt) as error:
        print(f'touchfix: {error or type(error).__name__}', file=sys.stderr)
        raise SystemExit(1)
