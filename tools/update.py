#!/usr/bin/env python3
"""Independent per-user update worker; survives a restart of thor-panel.service."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from armada_dual_screen_input.i18n import msg, encode_message
from armada_dual_screen_input.updates import (
    UpdateError, latest_release, newer, prepare_download, process_identity, state_path,
)
from release import PackageError, verify
from manage import Installer, Paths, atomic, host_check, runtime_check


def write_status(phase, message, *, tag='', path=None):
    value = {'schema': 1, 'phase': phase, 'message': str(message), 'message_i18n': encode_message(message), 'tag': tag,
             'pid': os.getpid(), 'identity': process_identity(os.getpid())}
    atomic(path or state_path(), (json.dumps(value, ensure_ascii=False) + '\n').encode(), 0o600)


def perform(tag, *, fetch=latest_release, prepare=prepare_download, installer=None,
            paths=None, status=write_status, check_host=host_check, check_runtime=runtime_check):
    paths = paths or Paths.environment()
    installer = installer or Installer(paths)
    current = paths.root / 'current'
    if current.resolve() != ROOT or not paths.state.is_file():
        raise UpdateError(msg('worker.managed_only'))
    check_host()
    current_manifest = verify(ROOT)
    status('checking', msg('worker.checking'), tag=tag)
    release = fetch()
    if release.tag != tag:
        raise UpdateError(msg('worker.latest_changed'))
    if not newer(release.version, current_manifest['version']):
        status('success', msg('update.current'), tag=tag)
        return
    with tempfile.TemporaryDirectory(prefix='thor-panel-update-') as directory:
        status('downloading', msg('worker.downloading'), tag=tag)
        bundle = prepare(release, Path(directory))
        manifest = verify(bundle)
        if (manifest['version'] != release.version
                or not re.fullmatch(r'[0-9a-f]{40}', manifest.get('source_revision', ''))):
            raise UpdateError(msg('worker.manifest'))
        if not all(value is True for value in check_runtime(bundle).values()):
            raise UpdateError(msg('worker.dependencies'))
        status('installing', msg('worker.installing'), tag=tag)
        # A second updater or manual installer may have changed current during download.
        if current.resolve() != ROOT:
            raise UpdateError(msg('worker.changed'))
        result = installer.install(bundle)
        message = msg('worker.updated_running' if result['started'] else 'worker.updated_next', tag=tag)
        refresh = result.get('desktop_refresh', {})
        if refresh.get('warnings'):
            message = msg('worker.cache_warning', message=message)
        elif refresh.get('mobile_session_active'):
            message = msg('worker.mobile_cache', message=message)
        status('success', message, tag=tag)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-tag', required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise UpdateError(msg('worker.no_sudo'))
    paths = Paths.environment()
    if not paths.root.is_dir() or paths.root.is_symlink():
        raise UpdateError(msg('worker.no_install'))
    # Separate from the installer's transactional lock; covers download as well.
    lock_path = paths.root / 'update.lock'
    if lock_path.is_symlink():
        raise UpdateError(msg('worker.lock'))
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            perform(args.expected_tag, paths=paths)
        except Exception as error:
            if isinstance(error, UpdateError) and error.args:
                message = error.args[0]
            elif isinstance(error, PackageError):
                message = msg('worker.failed_detail', detail=str(error)[:240])
            else:
                message = msg('worker.failed')
            write_status('error', message, tag=args.expected_tag)
            raise SystemExit(1)


if __name__ == '__main__':
    main()
