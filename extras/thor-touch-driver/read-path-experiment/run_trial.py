#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Plan or run a bounded lower-only acquisition comparison, restoring baseline.

Uses the existing verified root-managed component for every module operation.
The caller must stop its input panel and use an owned, input-free test window.
No boot file, additional firmware setting or official service is managed here.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import tempfile
import time

MODES = (1, 6, 33, 1, 33, 6, 1)
PARAMETER = Path('/sys/module/armada_thor_ft5452/parameters/read_chunk')
RESULT = re.compile(r'i2c_result: i2c-\d+ n=(\d+) ret=(-?\d+)')


def input_count(path, now, *, with_ids=False):
    try:
        value = json.loads(path.read_text())
        stamp, count = value['at'], value['contacts']
        if (type(stamp) not in (int, float) or not math.isfinite(stamp)
                or not 0 <= now-stamp <= 1 or type(count) is not int
                or not 0 <= count <= 5):
            return None
        if with_ids:
            ids = value.get('ids')
            if (not isinstance(ids, list) or len(ids) != count
                    or any(type(tid) is not int or tid < 1 for tid in ids)
                    or len(set(ids)) != len(ids)):
                return None
            return value
        return count
    except (OSError, ValueError, TypeError, KeyError):
        return None


def transfer_failed(path, cursor=None):
    cursor = {} if cursor is None else cursor
    try:
        with path.open('rb') as stream:
            offset = cursor.get('offset', 0)
            size = os.fstat(stream.fileno()).st_size
            if size < offset or size-offset > 1024*1024:
                raise RuntimeError('Trace monitor lost its bounded read position')
            stream.seek(offset)
            data = cursor.get('tail', b'')+stream.read(size-offset)
            cursor['offset'] = stream.tell()
        complete, separator, tail = data.rpartition(b'\n')
        cursor['tail'] = tail if separator else data
        return bool(separator and any(int(expected) != int(actual)
                    for expected, actual in RESULT.findall(complete.decode(errors='replace'))))
    except FileNotFoundError:
        return False


def require_primary(state, primary):
    if state is None:
        raise RuntimeError('Diagnostic contact status became stale')
    if primary not in state['ids']:
        raise RuntimeError('Original first-contact identity ended; partial data retained')
    if state['contacts'] not in (1, 2):
        raise RuntimeError('Unexpected extra contact; partial data retained')


def load_control():
    filename = Path('/var/lib/armada-touch-fix-ui/gui_bridge.py')
    spec = importlib.util.spec_from_file_location('existing_driver_bridge', filename)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    metadata, control = bridge.load_component()
    return metadata, control


def status(folder, phase, **values):
    descriptor, temporary = tempfile.mkstemp(prefix='.status-', dir=folder)
    try:
        if 'SUDO_UID' in os.environ:
            os.fchown(descriptor, int(os.environ['SUDO_UID']), -1)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(dict(phase=phase, at=time.monotonic(), **values), stream)
        os.replace(temporary, folder/'status.json')
    finally:
        Path(temporary).unlink(missing_ok=True)



def panel_running(uid):
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid == uid and b'armada_dual_screen_input.panel_app' in (process/'cmdline').read_bytes().split(b'\0'):
                return True
        except OSError:
            continue
    return False


def run(package, folder, seconds, step_seconds, metadata, control):
    if os.geteuid() != 0:
        raise RuntimeError('Running a trial requires root')
    if not 60 <= seconds <= 300 or not 1 <= step_seconds <= 10:
        raise ValueError('Trial bounds: 60..300 seconds; steps 1..10 seconds')
    if seconds < len(MODES)*step_seconds+15:
        raise ValueError('Trial must allow the complete sequence and restoration')
    if not folder.is_dir() or any((folder/name).exists() for name in ('status.json', 'done', 'register-trace.txt')):
        raise ValueError('Use a fresh, existing diagnostic directory')
    if panel_running(int(os.environ.get('SUDO_UID', os.getuid()))):
        raise RuntimeError('Stop this input panel before the owned-window test')
    store = control.Store()
    class BoundedLinux(control.Linux):
        @staticmethod
        def run(name, *values):
            executable = next((Path(p)/name for p in ('/usr/sbin', '/sbin', '/usr/bin')
                               if (Path(p)/name).is_file()), None)
            if executable is None:
                raise ValueError('Missing module command: '+name)
            return subprocess.check_output([str(executable), *map(str, values)],
                                           text=True, timeout=10).strip()
    system = BoundedLinux()
    baseline = control.Package(control.DATA/'packages'/metadata['module_sha256'])
    baseline.verify(system)
    capture = None
    handlers = {}
    failure = None

    def interrupted(*_):
        raise KeyboardInterrupt

    with store.lock():
        previous = store.read()
        if (previous.get('phase') != 'active' or previous.get('module_sha256') != metadata['module_sha256']
                or system.driver(system.targets()[0]) != control.MODULE):
            raise RuntimeError('The original installed experimental driver must be active')
        controller = control.Controller(system, store)
        try:
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                handlers[sig] = signal.signal(sig, interrupted)
            status(folder, 'loading')
            controller.apply(package)
            if PARAMETER.read_text().strip() != '1':
                raise RuntimeError('Candidate did not start in baseline bytewise mode')
            trace_script = Path(__file__).resolve().parents[1]/'trace_reads.py'
            capture = subprocess.Popen([
                sys.executable, '-I', '-B', str(trace_script), 'collect',
                '--seconds', str(seconds), '--output', str(folder/'register-trace.txt'),
                '--done', str(folder/'done'),
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if not select.select([capture.stdout], [], [], 5)[0]:
                raise RuntimeError('Private trace setup timed out')
            ready = json.loads(capture.stdout.readline())
            if ready.get('ready') is not True:
                raise RuntimeError('Private trace did not become ready')
            status(folder, 'waiting', trace=ready)
            deadline = time.monotonic()+seconds
            settled = started = primary = None
            index = -1
            transfer_cursor = {}
            while time.monotonic() < deadline and not (folder/'cancel').exists():
                now = time.monotonic()
                state = input_count(folder/'input.json', now, with_ids=True)
                count = state['contacts'] if state is not None else None
                if capture.poll() is not None:
                    raise RuntimeError('Private trace ended before the comparison')
                if transfer_failed(folder/'register-trace.txt', transfer_cursor):
                    raise RuntimeError('I2C transfer failed; comparison aborted')
                if started is None:
                    settled = (settled if settled is not None else now) if count == 2 else None
                    if settled is not None and now-settled >= .2:
                        started = now
                        primary = state['ids'][0]
                else:
                    require_primary(state, primary)
                if started is not None:
                    current = int((now-started)//step_seconds)
                    if current >= len(MODES):
                        break
                    if current != index:
                        PARAMETER.write_text(str(MODES[current]))
                        if PARAMETER.read_text().strip() != str(MODES[current]):
                            raise RuntimeError('Read mode did not match the requested value')
                        index = current
                        status(folder, 'sampling', index=index+1, total=len(MODES),
                               chunk=MODES[index], primary=primary,
                               until=started+(index+1)*step_seconds)
                time.sleep(.1)
            else:
                raise RuntimeError('Trial cancelled or timed out')
            PARAMETER.write_text('1')
            status(folder, 'lift')
            release_deadline = min(deadline, time.monotonic()+10)
            while time.monotonic() < release_deadline:
                if input_count(folder/'input.json', time.monotonic()) == 0:
                    break
                time.sleep(.1)
        except BaseException as error:
            failure = type(error).__name__+': '+str(error)
            status(folder, 'aborted', reason=failure)
            raise
        finally:
            for sig in handlers:
                signal.signal(sig, signal.SIG_IGN)
            cleanup_error = None
            try:
                try:
                    if PARAMETER.exists():
                        PARAMETER.write_text('1')
                    (folder/'done').touch()
                    if capture is not None:
                        try:
                            out, err = capture.communicate(timeout=3)
                        except subprocess.TimeoutExpired:
                            capture.terminate()
                            out, err = capture.communicate(timeout=3)
                        (folder/'trace-result.json').write_text(json.dumps(dict(stdout=out, stderr=err, code=capture.returncode)))
                except BaseException as error:
                    cleanup_error = type(error).__name__+': '+str(error)
                finally:
                    # A failed trace shutdown or parameter reset must never
                    # bypass restoration of the original installed module.
                    controller.apply(baseline)
                    if PARAMETER.exists() or store.read().get('module_sha256') != metadata['module_sha256']:
                        raise RuntimeError('Original module identity was not restored')
                    status(folder, 'restored', module_sha256=metadata['module_sha256'],
                           trial_error=failure, cleanup_error=cleanup_error)
                if cleanup_error:
                    raise RuntimeError('Trace cleanup failed after module restoration: '+cleanup_error)

            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--experimental', action='store_true')
    parser.add_argument('--folder', type=Path)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--step-seconds', type=int, default=6)
    args = parser.parse_args()
    metadata, control = load_control()
    package = control.Package(args.package)
    lower, upper = package.verify(control.Linux())
    print(json.dumps(dict(plan=True, package_sha256=package.manifest['sha256'],
                         baseline_sha256=metadata['module_sha256'], lower=str(lower), upper=str(upper),
                         modes=MODES, step_seconds=args.step_seconds, maximum_seconds=args.seconds)), flush=True)
    if args.run:
        if not args.experimental or args.folder is None:
            parser.error('--run needs --experimental and --folder')
        run(package, args.folder, args.seconds, args.step_seconds, metadata, control)


if __name__ == '__main__':
    main()
