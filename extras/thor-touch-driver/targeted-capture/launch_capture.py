#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded root launcher for passive trace coordination only.

No module, service, input or controller-register operation. The collector uses
its own temporary tracefs instance and restores only that instance on exit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time

FRESH = ('capture-request', 'capture.done', 'done', 'cancel', 'trace-ready',
         'trace-failed', 'trace-result.json', 'register-trace.txt')


def validate_folder(folder, uid):
    """Require the operator's real directory, not a root-writable symlink."""
    if not folder.is_absolute():
        raise ValueError('Use an absolute fresh diagnostic directory')
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid:
        raise ValueError('Diagnostic directory must be owned by SUDO_UID and not be a symlink')
    for name in FRESH:
        if os.path.lexists(folder/name):
            raise ValueError('Diagnostic directory contains an old marker or trace: '+name)


def write_json(folder, name, value, uid):
    """Exclusive non-symlink output, readable by the operator after sudo."""
    descriptor = os.open(folder/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    try:
        os.fchown(descriptor, uid, -1)
        with os.fdopen(descriptor, 'w') as stream:
            descriptor = None
            json.dump(value, stream)
            stream.write('\n')
    finally:
        if descriptor is not None:
            os.close(descriptor)


def regular_marker(folder, name):
    try:
        info = (folder/name).lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Diagnostic marker must be a regular non-symlink file: '+name)
    return True


def start_capture(folder, seconds):
    script = Path(__file__).resolve().parents[1]/'trace_reads.py'
    return subprocess.Popen([
        sys.executable, '-I', '-B', str(script), 'collect', '--seconds', str(seconds),
        '--output', str(folder/'register-trace.txt'), '--done', str(folder/'capture.done'),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)


def stop_capture(process):
    """Allow the collector's finally block to remove its own trace instance."""
    if process is None or process.poll() is not None:
        return False
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
    return True


def run(folder, *, wait_seconds=600, capture_seconds=30, startup_seconds=5,
        capture_factory=start_capture):
    if os.geteuid() != 0:
        raise RuntimeError('This passive collector launcher requires sudo')
    try:
        uid = int(os.environ['SUDO_UID'])
    except (KeyError, ValueError) as error:
        raise RuntimeError('Run through sudo so SUDO_UID identifies the operator') from error
    if uid <= 0:
        raise RuntimeError('The diagnostic directory must belong to a non-root operator')
    if not 0 < wait_seconds <= 600 or not 0 < capture_seconds <= 30 or not 0 < startup_seconds <= 5:
        raise ValueError('Wait/capture/startup bounds are 600/30/5 seconds')
    validate_folder(folder, uid)
    start = time.monotonic()
    result = dict(outcome='failed', ready=None, closed=None, error=None, returncode=None,
                  stdout='', stderr='', terminated=False, uid=uid,
                  budgets=dict(wait_seconds=wait_seconds, capture_seconds=capture_seconds,
                               startup_seconds=startup_seconds, capture_exit_grace_seconds=5))
    process, stopped = None, False
    handlers, buffers, pending = {}, {}, b''

    def interrupt(*_):
        nonlocal stopped
        stopped = True

    def read_available(timeout):
        nonlocal pending
        if not buffers:
            return []
        lines = []
        for descriptor in select.select(list(buffers), [], [], timeout)[0]:
            data = os.read(descriptor, 4096)
            if not data:
                del buffers[descriptor]
                continue
            key = 'stdout' if descriptor == process.stdout.fileno() else 'stderr'
            result[key] += data.decode('utf-8', errors='replace')
            if len(result['stdout'])+len(result['stderr']) > 65536:
                raise RuntimeError('Collector status output exceeded 64 KiB bound')
            if key == 'stdout':
                pending += data
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    lines.append(line)
        return lines

    def handle_status(lines):
        for line in lines:
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError) as error:
                raise RuntimeError('Collector emitted invalid status JSON') from error
            if result['ready'] is None:
                if not isinstance(value, dict) or value.get('ready') is not True:
                    raise RuntimeError('Collector did not report successful trace setup')
                result['ready'] = value
                write_json(folder, 'trace-ready', dict(at=time.monotonic(), trace=value,
                                                       budgets=result['budgets']), uid)
            elif isinstance(value, dict) and value.get('closed') is True:
                result['closed'] = value
            else:
                raise RuntimeError('Collector emitted unexpected status JSON')

    def drain_status():
        deadline = time.monotonic()+.2
        while buffers and time.monotonic() < deadline:
            handle_status(read_available(.01))

    try:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, interrupt)
        deadline = start+wait_seconds
        while True:
            if stopped or regular_marker(folder, 'cancel'):
                raise RuntimeError('Passive launcher interrupted or cancelled before trace setup')
            if regular_marker(folder, 'capture.done') or regular_marker(folder, 'done'):
                result['outcome'] = 'cancelled'
                return result
            if regular_marker(folder, 'capture-request'):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Timed out waiting for the first-contact capture request')
            time.sleep(.05)

        result['request_wait_elapsed'] = time.monotonic()-start
        process = capture_factory(folder, capture_seconds)
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
            buffers[stream.fileno()] = stream
        capture_start = time.monotonic()
        startup_deadline = capture_start+startup_seconds
        capture_deadline = capture_start+capture_seconds+5
        while True:
            if stopped or regular_marker(folder, 'cancel'):
                raise RuntimeError('Passive capture interrupted or cancelled')
            handle_status(read_available(.05))
            now = time.monotonic()
            if result['ready'] is None and now >= startup_deadline:
                raise RuntimeError('Passive trace setup timed out')
            code = process.poll()
            if code is not None:
                # Drain status bytes after exit, retaining errors for diagnosis.
                drain_status()
                result['returncode'] = code
                if code != 0:
                    raise RuntimeError('Passive collector failed with exit code '+str(code))
                if result['ready'] is None:
                    raise RuntimeError('Passive collector exited before trace setup')
                if not result['closed'] or result['closed'].get('instance_removed') is not True:
                    raise RuntimeError('Collector did not confirm removal of its private trace instance')
                if not regular_marker(folder, 'capture.done'):
                    raise RuntimeError('Passive collector ended before the diagnostic scan finished')
                result['outcome'] = 'completed'
                return result
            if now >= capture_deadline:
                raise RuntimeError('Passive collector did not exit within its bounded duration')
    except BaseException as error:
        result['error'] = type(error).__name__+': '+str(error)
        result['outcome'] = 'failed'
        try:
            write_json(folder, 'trace-failed', dict(at=time.monotonic(), error=result['error']), uid)
        except OSError as marker_error:
            result['marker_error'] = repr(marker_error)
        return result
    finally:
        try:
            try:
                result['terminated'] = stop_capture(process)
                if process is not None:
                    result['returncode'] = process.poll()
                    drain_status()
            except BaseException as cleanup_error:
                result['cleanup_error'] = repr(cleanup_error)
                result['outcome'] = 'failed'
                if not os.path.lexists(folder/'trace-failed'):
                    write_json(folder, 'trace-failed', dict(at=time.monotonic(), error=result['cleanup_error']), uid)
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    stream.close()
            result['elapsed'] = time.monotonic()-start
            write_json(folder, 'trace-result.json', result, uid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--wait-seconds', type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.wait_seconds <= 600:
        parser.error('Waiting budget must be 1..600 seconds')
    result = run(args.folder, wait_seconds=args.wait_seconds)
    print(json.dumps(result), flush=True)
    return 0 if result['outcome'] in ('completed', 'cancelled') else 1


if __name__ == '__main__':
    raise SystemExit(main())
