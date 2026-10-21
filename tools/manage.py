#!/usr/bin/env python3
"""Per-user installation, updates and removal. Never manages Armada services."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from release import APP, PackageError, digest, prepare, verify, version
from desktop_cache import refresh_desktop

ROOT = Path(__file__).resolve().parent.parent
UNIT = 'thor-panel.service'  # Preserve existing shortcuts/configuration.


@dataclass
class Paths:
    home: Path
    data: Path
    config: Path
    binary: Path
    desktop: Path

    @classmethod
    def environment(cls):
        home = Path.home()
        desktop = home / 'Desktop'
        if shutil.which('xdg-user-dir'):
            result = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True)
            candidate = Path(result.stdout.strip())
            if result.returncode == 0 and candidate.is_absolute() and candidate != home:
                desktop = candidate
        data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share'))
        config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
        if not all(p.is_absolute() for p in (home, data, config, desktop)):
            raise PackageError('XDG paths must be absolute')
        return cls(home, data, config, home / '.local/bin', desktop)

    @property
    def root(self):
        # Fedora can expose /home through /var/home; normalize the parent while
        # leaving the final component available for explicit symlink checks.
        return self.data.resolve() / 'thor-panel'

    @property
    def state(self):
        return self.root / 'install-state.json'

    def external(self):
        return {
            'unit': self.config / 'systemd/user' / UNIT,
            'application': self.data / 'applications/thor-panel.desktop',
            'icon': self.data / 'icons/hicolor/scalable/apps/armada-dual-screen-input.svg',
            'launcher': self.binary / APP,
            'desktop': self.desktop / '虚拟键鼠.desktop',
        }


def atomic(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def link(path, target):
    temporary = path.with_name('.' + path.name + '.new')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, path)


def command(arguments, *, check=True):
    result = subprocess.run(['systemctl', '--user', *arguments], capture_output=True, text=True, timeout=15)
    if check and result.returncode:
        raise PackageError('User service command failed: ' + ' '.join(arguments) + '\n' + result.stderr.strip())
    return result


def host_check(*, allow_untested=False):
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise PackageError('请在 ArmadaOS 中以普通桌面用户运行，不要使用 sudo。')
    if platform.machine() != 'aarch64':
        raise PackageError('This bundle requires Linux aarch64; no x86/other-architecture runtime is bundled')
    release = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1); release[key] = value.strip('"')
    if release.get('ID') != 'armada':
        raise PackageError('This installer targets ArmadaOS')
    board_file = Path('/sys/firmware/devicetree/base/compatible')
    board = board_file.read_bytes().split(b'\0') if board_file.exists() else []
    if not allow_untested and (b'ayn,thor' not in board or release.get('VERSION_ID') != '44'):
        raise PackageError('Only AYN Thor / Fedora-44-based Armada is tested. Read docs/compatibility.md; explicit --allow-untested is required for other Armada targets.')
    if not os.access('/dev/uinput', os.R_OK | os.W_OK):
        raise PackageError('当前用户不能读写 /dev/uinput；安装器不会更改权限或添加 root 服务。请先检查 Armada 的输入设备权限。')
    command(['show-environment'])  # Captured, never printed/stored.


def runtime_check(root):
    root = Path(root)
    code = '''import ctypes.util, importlib, json
checks={}
try:
 import gi
 for name,version in (('Gtk','3.0'),('Gdk','3.0'),('GtkLayerShell','0.1'),('PangoCairo','1.0')):
  gi.require_version(name,version);importlib.import_module('gi.repository.'+name)
 import cairo
 checks['gtk_cairo_layershell']=True
except (ImportError,ValueError,OSError) as e:checks['gtk_cairo_layershell']=str(e)
try:import websocket;checks['websocket_client']=True
except ImportError as e:checks['websocket_client']=str(e)
for name in ('evdev','xcb'):checks['lib'+name]=bool(ctypes.util.find_library(name))
print(json.dumps(checks))
'''
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    private = root / 'runtime/usr/lib64'
    if private.is_dir():
        env.update(LD_LIBRARY_PATH=str(private), GI_TYPELIB_PATH=str(private / 'girepository-1.0'))
    result = subprocess.run(['/usr/bin/python3', '-B', '-c', code], env=env,
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise PackageError('Dependency probe could not run: ' + result.stderr.strip())
    return json.loads(result.stdout)


class Installer:
    def __init__(self, paths, *, runner=command, refresher=None):
        self.paths, self.runner = paths, runner
        self.refresher = refresher or refresh_desktop

    def refresh(self):
        try:
            return self.refresher(self.paths)
        except Exception:
            # Installation has already committed. Cache helpers cannot roll it back.
            return {'warnings': ['桌面缓存刷新失败；已完成的操作不受影响']}

    def state(self):
        path = self.paths.state
        if path.is_symlink():
            raise PackageError('Install state must not be a symlink')
        if not path.exists():
            return {}
        state = json.loads(path.read_text())
        if state.get('application') != APP or state.get('schema') != 1:
            raise PackageError('Unrecognized install state')
        for identity in state.get('releases', []):
            if not re.fullmatch(r'[A-Za-z0-9.+-]+-[0-9a-f]{16}', identity):
                raise PackageError('Unsafe installed release identity')
        if not set(state.get('files', {})).issubset({str(p) for p in self.paths.external().values()}):
            raise PackageError('Install state lists files outside this application')
        return state

    @contextmanager
    def lock(self):
        root = self.paths.root
        if root.is_symlink():
            raise PackageError('Install root must not be a symlink')
        root.mkdir(parents=True, exist_ok=True)
        if (root / 'installer.lock').is_symlink():
            raise PackageError('Install lock must not be a symlink')
        with (root / 'installer.lock').open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise PackageError('Another installer is running') from error
            yield

    def metadata(self, bundle, *, desktop=True):
        paths = self.paths.external()
        run_path = str(self.paths.root / 'current/tools/run.py')
        if '\n' in run_path or '\r' in run_path:
            raise PackageError('Unsupported newline in installation path')
        quoted = '"' + run_path.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
        unit = (bundle / 'packaging/systemd/thor-panel.service.in').read_text().replace('@RUN@', quoted)
        entry = (bundle / 'packaging/desktop/thor-panel.desktop.in').read_bytes()
        launcher = '#!/bin/sh\nexec /usr/bin/python3 -B ' + shlex.quote(str(self.paths.root / 'current/tools/manage.py')) + ' "$@"\n'
        items = {paths['unit']: (unit.encode(), 0o644), paths['application']: (entry, 0o644),
                 paths['launcher']: (launcher.encode(), 0o755),
                 paths['icon']: ((bundle / 'assets/icons/armada-dual-screen-input.svg').read_bytes(), 0o644)}
        if desktop:
            items[paths['desktop']] = (entry, 0o755)
        return items

    def check_owned(self, files, state):
        known = state.get('files', {})
        for path in files:
            if path.is_symlink():
                raise PackageError('Refusing to overwrite symlink: ' + str(path))
            if not path.exists():
                continue
            if not path.is_file():
                raise PackageError('Not a regular managed file: ' + str(path))
            if str(path) in known and digest(path) == known[str(path)]:
                continue
            # Recognize this project's previous hand-installed launchers only.
            text = path.read_text(errors='replace')
            legacy_unit = (path == self.paths.external()['unit'] and 'ExecStart=' in text
                           and '.local/share/thor-panel/supervisor.py' in text)
            legacy_entry = (path in (self.paths.external()['application'], self.paths.external()['desktop'])
                            and 'Name=虚拟键鼠' in text
                            and 'Exec=/usr/bin/systemctl --user restart thor-panel.service' in text)
            if legacy_unit or legacy_entry:
                continue
            raise PackageError('Existing file is unowned or locally modified; back it up explicitly: ' + str(path))

    def save_state(self, state):
        atomic(self.paths.state, (json.dumps(state, ensure_ascii=False, indent=2) + '\n').encode(), 0o600)

    def install(self, bundle, *, desktop=True):
        bundle = Path(bundle).resolve(); manifest = verify(bundle)
        root = self.paths.root
        with self.lock():
            state = self.state(); items = self.metadata(bundle, desktop=desktop)
            self.check_owned(items, state)
            current = root / 'current'; previous = root / 'previous'
            for pointer in (current, previous):
                if pointer.exists() and not pointer.is_symlink():
                    raise PackageError('Expected an application release symlink: ' + str(pointer))
                if pointer.is_symlink() and not pointer.resolve().is_relative_to(root / 'releases'):
                    raise PackageError('Release symlink leaves this installation')
            identity = manifest['version'] + '-' + manifest['bundle_id']
            releases = root / 'releases'
            if releases.is_symlink():
                raise PackageError('Releases directory must not be a symlink')
            releases.mkdir(exist_ok=True)
            target = releases / identity
            if target.is_symlink():
                raise PackageError('Release directory must not be a symlink')
            created = not target.exists()
            if created:
                with tempfile.TemporaryDirectory(prefix='.staging-', dir=releases) as directory:
                    stage = Path(directory) / 'payload'; stage.mkdir()
                    for name in [*manifest['files'], 'manifest.json']:
                        destination = stage / name; destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(bundle / name, destination)
                    verify(stage); stage.rename(target)
            else:
                verify(target)
            snapshots = {p: (p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else None for p in items}
            old_state = self.paths.state.read_bytes() if self.paths.state.exists() else None
            old_links = {p: os.readlink(p) if p.is_symlink() else None for p in (current, previous)}
            if any(value is not None for value in snapshots.values()):
                backups = root / 'backups'
                if backups.is_symlink(): raise PackageError('Backups directory must not be a symlink')
                backups.mkdir(exist_ok=True)
                backup = Path(tempfile.mkdtemp(prefix='metadata-', dir=backups))
                records = []
                for index, (path, original) in enumerate(snapshots.items()):
                    if original is not None:
                        saved = backup / str(index); saved.write_bytes(original[0]); saved.chmod(0o600)
                        records.append({'path': str(path), 'file': saved.name, 'mode': original[1]})
                atomic(backup / 'index.json', json.dumps({'files': records, 'links': {str(p): v for p, v in old_links.items()}}).encode(), 0o600)
            active = self.runner(['is-active', '--quiet', UNIT], check=False).returncode == 0
            try:
                if active: self.runner(['stop', UNIT])
                if old_links[current] and old_links[current] != 'releases/' + identity:
                    link(previous, old_links[current])
                link(current, 'releases/' + identity)
                for path, (data, mode) in items.items(): atomic(path, data, mode)
                files = dict(state.get('files', {})); files.update({str(p): digest(p) for p in items})
                state = {'schema': 1, 'application': APP, 'version': manifest['version'], 'current': identity,
                         'releases': sorted(set(state.get('releases', [])) | {identity}), 'files': files}
                self.save_state(state)
                self.runner(['daemon-reload'])
                if active: self.runner(['start', UNIT])
            except BaseException:
                for path, original in snapshots.items():
                    if original is None: path.unlink(missing_ok=True)
                    else: atomic(path, *original)
                for path, original in old_links.items():
                    if original is None: path.unlink(missing_ok=True)
                    else: link(path, original)
                if old_state is None: self.paths.state.unlink(missing_ok=True)
                else: atomic(self.paths.state, old_state, 0o600)
                self.runner(['daemon-reload'], check=False)
                if active: self.runner(['start', UNIT], check=False)
                if created: shutil.rmtree(target)
                raise
            return {'installed': manifest['version'], 'root': str(root), 'autostart_changed': False,
                    'started': active, 'configuration_changed': False, 'desktop_refresh': self.refresh()}

    def rollback(self):
        root = self.paths.root
        with self.lock():
            state = self.state(); current, previous = root / 'current', root / 'previous'
            if not state or not current.is_symlink() or not previous.is_symlink():
                raise PackageError('No previous installer-managed version is available')
            before, older = os.readlink(current), os.readlink(previous)
            if not previous.resolve().is_relative_to(root / 'releases') or previous.resolve().name not in state['releases']:
                raise PackageError('Previous release is not managed by this installer')
            manifest = verify(previous.resolve())
            items = self.metadata(previous.resolve(), desktop=str(self.paths.external()['desktop']) in state['files'])
            self.check_owned(items, state)
            snapshots = {p: (p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else None for p in items}
            old_state = self.paths.state.read_bytes()
            active = self.runner(['is-active', '--quiet', UNIT], check=False).returncode == 0
            try:
                if active: self.runner(['stop', UNIT])
                link(current, older); link(previous, before)
                for path, (data, mode) in items.items(): atomic(path, data, mode)
                state.update(version=manifest['version'], current=current.resolve().name)
                state['files'].update({str(p): digest(p) for p in items})
                self.save_state(state)
                self.runner(['daemon-reload'])
                if active: self.runner(['start', UNIT])
            except BaseException:
                link(current, before); link(previous, older)
                for path, original in snapshots.items():
                    if original is None: path.unlink(missing_ok=True)
                    else: atomic(path, *original)
                atomic(self.paths.state, old_state, 0o600)
                self.runner(['daemon-reload'], check=False)
                if active: self.runner(['start', UNIT], check=False)
                raise
            return {'rolled_back_to': manifest['version'], 'configuration_changed': False,
                    'desktop_refresh': self.refresh()}

    def uninstall(self):
        leftovers = []
        with self.lock():
            state = self.state()
            if not state:
                raise PackageError('No installer-managed installation found; legacy/manual files were left untouched')
            unit = self.paths.external()['unit']
            if not unit.exists() or (not unit.is_symlink() and digest(unit) == state['files'].get(str(unit))):
                self.runner(['stop', UNIT])
                self.runner(['disable', UNIT], check=False)
            else:
                raise PackageError('Managed service file changed; inspect it before uninstalling')
            for name, expected in state['files'].items():
                path = Path(name)
                if path.is_symlink() or (path.exists() and (not path.is_file() or digest(path) != expected)):
                    leftovers.append(name); continue
                path.unlink(missing_ok=True)
            for pointer in (self.paths.root / 'current', self.paths.root / 'previous'):
                if pointer.is_symlink() and pointer.resolve().name in state['releases']:
                    pointer.unlink()
            for identity in state['releases']:
                folder = self.paths.root / 'releases' / identity
                if not folder.exists(): continue
                try:
                    if folder.is_symlink(): raise PackageError('Release path is a symlink')
                    verify(folder); shutil.rmtree(folder)
                except (PackageError, OSError, ValueError): leftovers.append(str(folder))
            self.runner(['daemon-reload'])
            if leftovers:
                state['phase'] = 'uninstalled-with-leftovers'; self.save_state(state)
            else:
                self.paths.state.unlink(missing_ok=True)
        return {'uninstalled': True, 'configuration_and_logs_preserved': True, 'leftovers': leftovers,
                'desktop_refresh': self.refresh()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='start', choices=('install', 'uninstall', 'rollback', 'start', 'stop', 'status', 'doctor', 'version'))
    parser.add_argument('--dry-run', action='store_true', help='Read-only installation plan; no download/service/file changes')
    parser.add_argument('--no-desktop', action='store_true')
    parser.add_argument('--runtime-rpm', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--allow-untested', action='store_true')
    args = parser.parse_args(); paths = Paths.environment(); installer = Installer(paths)
    if args.action == 'version': print(version(ROOT)); return
    if args.action == 'doctor':
        print(json.dumps({'platform': sys.platform, 'architecture': platform.machine(), 'uinput_writable': os.access('/dev/uinput', os.R_OK | os.W_OK),
                          'dependencies': runtime_check(ROOT), 'install_root': str(paths.root)}, ensure_ascii=False, indent=2)); return
    if args.action == 'install' and args.dry_run:
        manifest = verify(ROOT) if (ROOT / 'manifest.json').exists() else None
        print(json.dumps({'action': 'install', 'version': version(ROOT), 'bundle_verified': manifest is not None,
                          'root': str(paths.root), 'desktop': None if args.no_desktop else str(paths.external()['desktop']),
                          'autostart': False, 'driver_install': False, 'system_writes': False,
                          'source_runtime_download_needed': manifest is None}, ensure_ascii=False, indent=2)); return
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise PackageError('请在 Linux 中以普通桌面用户运行，不要使用 sudo。')
    if args.action in ('start', 'stop', 'status'):
        arguments = ['restart', UNIT] if args.action == 'start' else [args.action, UNIT, '--no-pager']
        result = command(arguments, check=args.action != 'status')
        print(result.stdout, end=''); return
    if args.action == 'uninstall': print(json.dumps(installer.uninstall(), ensure_ascii=False, indent=2)); return
    host_check(allow_untested=args.allow_untested)
    if args.action == 'rollback': print(json.dumps(installer.rollback(), ensure_ascii=False, indent=2)); return
    with tempfile.TemporaryDirectory(prefix='ads-install-') as temporary:
        bundle = ROOT
        if not (ROOT / 'manifest.json').exists():
            bundle = Path(temporary) / 'bundle'
            prepare(ROOT, bundle, runtime_rpm=args.runtime_rpm,
                    cache=Path(os.environ.get('XDG_CACHE_HOME', paths.home / '.cache')) / APP, offline=args.offline)
        verify(bundle)
        checks = runtime_check(bundle)
        if not all(value is True for value in checks.values()):
            raise PackageError('Missing runtime dependencies (see docs/installation.md): ' + json.dumps(checks))
        print(json.dumps(installer.install(bundle, desktop=not args.no_desktop), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except (PackageError, OSError, ValueError, subprocess.SubprocessError) as error:
        print('armada-dual-screen-input: ' + str(error), file=sys.stderr); raise SystemExit(1)
