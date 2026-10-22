#!/usr/bin/env python3
"""Detached, ordinary-user driver task; only the fixed bridge gets root."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'src'))
from armada_dual_screen_input.i18n import configure, msg, encode_message
from armada_dual_screen_input.touch_driver import authenticated_action
from armada_dual_screen_input.updates import state_path
from manage import Paths, atomic, command
from release import verify


def write_status(phase, message):
    atomic(state_path().with_name('driver.json'), (json.dumps({
        'schema': 1, 'phase': phase, 'message': str(message),
        'message_i18n': encode_message(message)})+'\n').encode(), 0o600)


def notify(message):
    executable = shutil.which('notify-send')
    if executable:
        try:
            subprocess.run([executable, '--app-name='+str(msg('app.name')),
                            str(msg('driver.tab')), str(message)], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def perform(action, *, paths=None, service=command, operate=authenticated_action, status=write_status):
    if action not in ('apply', 'revert'):
        raise ValueError('Unknown driver action')
    paths = paths or Paths.environment()
    if os.geteuid() == 0 or (paths.root/'current').resolve() != ROOT:
        raise ValueError('Use the managed ordinary-user installation')
    verify(ROOT)
    lock_path = paths.root/'update.lock'
    if lock_path.is_symlink():
        raise ValueError('Unsafe operation lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (paths.root/'current').resolve() != ROOT:
            raise ValueError('Application changed before driver action')
        status('running', msg('driver.starting'))
        active = service(['is-active', '--quiet', 'thor-panel.service'], check=False).returncode == 0
        try:
            if active:
                service(['stop', 'thor-panel.service'])
            result = operate(action)
            status('success', msg('driver.done'))
        except BaseException:
            status('error', msg('driver.operation_failed'))
            raise
        finally:
            if active:
                service(['start', 'thor-panel.service'])
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'revert'))
    parser.add_argument('--ui-language', choices=('en_US', 'zh_CN'), default='en_US')
    args = parser.parse_args(); configure(args.ui_language)
    try:
        perform(args.action)
        notify(msg('driver.done'))
    except Exception:
        write_status('error', msg('driver.operation_failed'))
        notify(msg('driver.operation_failed'))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
