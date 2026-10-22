#!/usr/bin/env python3
"""Remove only this user installation, surviving its own service/file removal."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from armada_dual_screen_input.i18n import configure, encode_message, msg
from armada_dual_screen_input.uninstall_controller import status_path
from armada_dual_screen_input.updates import process_identity
from manage import Installer, Paths, atomic
from release import PackageError, verify


def write_status(phase, message, *, result=None, path=None):
    value = {'schema': 1, 'phase': phase, 'message': str(message),
             'message_i18n': encode_message(message), 'pid': os.getpid(),
             'identity': process_identity(os.getpid()), 'result': result}
    atomic(path or status_path(), (json.dumps(value, ensure_ascii=False) + '\n').encode(), 0o600)


def notify(message, *, runner=subprocess.run):
    executable = shutil.which('notify-send')
    if executable:
        try:
            runner([executable, '--app-name=' + str(msg('app.name')),
                    str(msg('uninstall.title')), str(message)], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass  # The durable result remains in uninstall.json without a notification daemon.


def perform(*, paths=None, installer=None, status=write_status, notification=notify):
    paths = paths or Paths.environment()
    installer = installer or Installer(paths)
    if paths.root.is_symlink() or (paths.root / 'current').resolve() != ROOT or not paths.state.is_file():
        raise PackageError(str(msg('uninstall.managed_only')))
    verify(ROOT)
    # Coordinate with the updater's whole download/install lifetime, then let
    # Installer.uninstall acquire its normal transactional installer lock.
    lock_path = paths.root / 'update.lock'
    if lock_path.is_symlink():
        raise PackageError(str(msg('uninstall.lock_invalid')))
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PackageError(str(msg('uninstall.update_busy'))) from error
        # A manual install may have changed current before the lock was acquired.
        if (paths.root / 'current').resolve() != ROOT:
            raise PackageError(str(msg('uninstall.managed_only')))
        status('uninstalling', msg('uninstall.running'))
        result = installer.uninstall()
        message = msg('uninstall.leftovers' if result['leftovers'] else 'uninstall.success')
        status('success', message, result=result)
        notification(message)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ui-language', choices=('en_US', 'zh_CN'), default='en_US')
    args = parser.parse_args()
    configure(args.ui_language)
    try:
        if sys.platform != 'linux' or os.geteuid() == 0:
            raise PackageError(str(msg('uninstall.no_sudo')))
        perform()
    except Exception as error:
        message = msg('uninstall.failed', detail=str(error)[:240])
        write_status('error', message)
        notify(message)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
