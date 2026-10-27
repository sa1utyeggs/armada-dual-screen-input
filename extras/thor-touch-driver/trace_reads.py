#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded, passive FT5452 read tracing in a private tracefs instance.

No I2C transaction, input injection, module operation or global trace setting.
The collector needs root; offline decoding does not. Tracing adds overhead, so
its durations must not be presented as uninstrumented acquisition timings.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import select
import signal
import time

READ = re.compile(r'(\d+\.\d+): regmap_reg_read: (\S+) reg=([0-9a-fA-F]+) val=([0-9a-fA-F]+)')
BULK = re.compile(r'(\d+\.\d+): regmap_bulk_read: (\S+) reg=([0-9a-fA-F]+) val=([0-9a-fA-F \t-]+)$')
START = re.compile(r'(\d+\.\d+): regmap_hw_read_start: \S+ reg=0 count=\d+')
RESULT = re.compile(r'i2c_result: i2c-\d+ n=(\d+) ret=(-?\d+)')
I2C_READ = re.compile(r'(\d+\.\d+): i2c_read: i2c-(\d+) #\d+ a=([0-9a-fA-F]+) f=[0-9a-fA-F]+ l=(\d+)')
# Linux include/trace/events/i2c.h prints write/reply buffers as [%*phD].
# Keep the original text when a trace line or its hexadecimal payload is short.
I2C_MESSAGE = re.compile(r'(\d+\.\d+): i2c_(write|reply): i2c-(\d+) #(\d+) '
                         r'a=([0-9a-fA-F]+) f=([0-9a-fA-F]+) l=(\d+)(?: \[(.*))?$')
I2C_HEX = re.compile(r'(?:[0-9a-fA-F]{2}(?:[-\t ]+[0-9a-fA-F]{2})*)?')


def decode(lines, frame_length=33):
    """Retain broken reads; merge only identical single/bulk trace mirrors."""
    frames, current, results, reads, messages = [], [], [], [], []
    hardware_start = current_start = current_end = current_epoch = None
    epoch = mirrors = 0

    def finish():
        if not current:
            return
        registers = [entry[1] for entry in current]
        ordered = registers == list(range(len(current)))
        begin = current[0][0] if current_start is None else current_start
        frame = dict(start=begin, end=current_end,
                     duration_ms=(current_end-begin)*1000,
                     sequential=ordered, complete=ordered and len(current) == frame_length,
                     registers=registers, bulk_mirrors=mirrors,
                     bytes=[entry[2] for entry in current], contacts=[])
        if ordered and len(current) >= 3:
            values = frame['bytes']
            frame['status_byte'] = values[2]
            frame['reported_contacts'] = values[2] & 15
            for offset in range(3, len(values)-5, 6):
                a, b, c, d, weight, misc = values[offset:offset+6]
                event = a >> 6
                if event != 3:
                    frame['contacts'].append(dict(id=c >> 4, event=event,
                                                  x=((a & 15) << 8) | b,
                                                  y=((c & 15) << 8) | d,
                                                  weight=weight, misc=misc))
        frames.append(frame)

    for line in lines:
        match = START.search(line)
        if match:
            hardware_start = float(match.group(1))
            epoch += 1
        match = READ.search(line)
        bulk = BULK.search(line.rstrip())
        if match or bulk:
            timestamp, name, register, value = (bulk or match).groups()
            timestamp, register = float(timestamp), int(register, 16)
            values = list(bytes.fromhex(value.replace('-', '').replace(' ', '').replace('\t', ''))) if bulk else [int(value, 16)]
            # Some regmap backends emit both per-register and bulk events for
            # the same hardware operation. Do not count that API mirror twice.
            duplicate = (bulk and current_epoch == epoch and current_epoch is not None
                         and register+len(values) <= len(current)
                         and [entry[1] for entry in current[register:register+len(values)]] == list(range(register, register+len(values)))
                         and [entry[2] for entry in current[register:register+len(values)]] == values)
            if duplicate:
                mirrors += 1
                current_end = timestamp
            else:
                if register == 0:
                    finish()
                    current = []
                    current_epoch = epoch if hardware_start is not None else None
                    current_start = hardware_start
                    mirrors = 0
                current.extend((timestamp, register+offset, byte) for offset, byte in enumerate(values))
                current_end = timestamp
        match = RESULT.search(line)
        if match:
            message_count, returned = map(int, match.groups())
            results.append(dict(messages=message_count, returned=returned))
        match = I2C_READ.search(line)
        if match:
            timestamp, bus, address, length = match.groups()
            reads.append(dict(at=float(timestamp), bus=int(bus), address=int(address, 16), length=int(length)))
        match = I2C_MESSAGE.search(line.rstrip())
        if match:
            timestamp, kind, bus, index, address, flags, length, payload = match.groups()
            closed = payload is not None and payload.endswith(']')
            payload = (payload[:-1] if closed else payload) or ''
            valid = I2C_HEX.fullmatch(payload) is not None
            values = list(bytes.fromhex(payload.replace('-', ' '))) if valid else []
            messages.append(dict(at=float(timestamp), kind=kind, bus=int(bus),
                                 message=int(index), address=int(address, 16),
                                 flags=int(flags, 16), length=int(length), bytes=values,
                                 payload=payload,
                                 payload_complete=closed and valid and len(values) == int(length)))
    finish()
    return dict(frames=frames, transfers=results, reads=reads, messages=messages)


def collect(output, seconds, done):
    if os.geteuid() != 0:
        raise RuntimeError('Collection requires root; offline decoding does not')
    if not 1 <= seconds <= 600:
        raise ValueError('Capture duration must be 1..600 seconds')
    if 'ayn,thor' not in Path('/sys/firmware/devicetree/base/compatible').read_bytes().decode().split('\0'):
        raise RuntimeError('This collector is restricted to AYN Thor')
    targets = []
    for target in Path('/sys/bus/i2c/devices').glob('*-0038'):
        node = target/'of_node'
        try:
            compatible = (node/'compatible').read_bytes().split(b'\0')
            if b'focaltech,ft5452' in compatible and (node/'label').read_bytes().rstrip(b'\0') == b'bottom_touchscreen':
                targets.append(target)
        except OSError:
            continue
    if len(targets) != 1:
        raise RuntimeError('Cannot identify the unique lower FT5452')
    target = targets[0]
    bus = int(target.name.split('-')[0])
    root = Path('/sys/kernel/tracing')
    instance = root/'instances'/f'thor-touch-reads-{os.getpid()}'
    stopped = False
    previous_handlers = {}
    pipe = None
    stream = None
    created = False
    written = 0

    def stop(*_):
        nonlocal stopped
        stopped = True

    try:
        # Exclusive, non-symlink output creation; never overwrite an existing file.
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        if 'SUDO_UID' in os.environ:
            os.fchown(descriptor, int(os.environ['SUDO_UID']), -1)
        stream = os.fdopen(descriptor, 'wb', buffering=0)
        instance.mkdir()
        created = True
        (instance/'tracing_on').write_text('0')
        (instance/'buffer_size_kb').write_text('1024')
        (instance/'trace_clock').write_text('mono')
        for event in ('regmap_reg_read', 'regmap_bulk_read', 'regmap_hw_read_start', 'regmap_hw_read_done'):
            folder = instance/'events/regmap'/event
            (folder/'filter').write_text(f'name == "{target.name}"')
            (folder/'enable').write_text('1')
        result = instance/'events/i2c/i2c_result'
        (result/'filter').write_text(f'adapter_nr == {bus}')
        (result/'enable').write_text('1')
        for event in ('i2c_read', 'i2c_write', 'i2c_reply'):
            message = instance/'events/i2c'/event
            (message/'filter').write_text(f'adapter_nr == {bus} && addr == 56')
            (message/'enable').write_text('1')
        metadata = dict(device=target.name, driver=(target/'driver').resolve().name,
                        instance=str(instance), seconds=seconds, monotonic=time.monotonic(),
                        wall_time=time.time(), bytewise=(target/'of_node/no-regmap-bulk-read').exists())
        stream.write(('# '+json.dumps(metadata)+'\n').encode())
        pipe = os.open(instance/'trace_pipe', os.O_RDONLY | os.O_NONBLOCK)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous_handlers[sig] = signal.signal(sig, stop)
        (instance/'tracing_on').write_text('1')
        print(json.dumps(dict(ready=True, **metadata)), flush=True)
        deadline = time.monotonic()+seconds
        while not stopped and time.monotonic() < deadline and not (done and done.exists()):
            if not select.select([pipe], [], [], .1)[0]:
                continue
            data = os.read(pipe, 65536)
            written += len(data)
            stream.write(data)
            if written >= 32*1024*1024:
                raise RuntimeError('Capture stopped at 32 MiB bound')
        (instance/'tracing_on').write_text('0')
        while select.select([pipe], [], [], 0)[0]:
            data = os.read(pipe, 65536)
            if not data:
                break
            stream.write(data)
        stats = {}
        for cpu in (instance/'per_cpu').glob('cpu*/stats'):
            stats[cpu.parent.name] = cpu.read_text()
        stream.write(('# '+json.dumps(dict(ended=True, bytes=written, stats=stats))+'\n').encode())
    finally:
        if created:
            (instance/'tracing_on').write_text('0')
            (instance/'events/enable').write_text('0')
        if pipe is not None:
            os.close(pipe)
        if stream is not None:
            stream.close()
        if created:
            instance.rmdir()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    print(json.dumps(dict(closed=True, bytes=written, instance_removed=not instance.exists())), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    capture = commands.add_parser('collect')
    capture.add_argument('--output', required=True, type=Path)
    capture.add_argument('--seconds', type=int, default=180)
    capture.add_argument('--done', type=Path)
    analyze = commands.add_parser('decode')
    analyze.add_argument('input', type=Path)
    args = parser.parse_args()
    if args.command == 'collect':
        collect(args.output, args.seconds, args.done)
    else:
        print(json.dumps(decode(args.input.read_text().splitlines())))


if __name__ == '__main__':
    main()
