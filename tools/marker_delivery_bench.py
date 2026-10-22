#!/usr/bin/env python3
"""Compare real GLib marker IPC delivery, without windows or input output.

The worker is replaced by a local datagram receiver. Results include generator
and receiver CPU and measure callback-to-receive, not physical display latency.
Run with the app's Linux GLib runtime. No installed service is stopped/changed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import socket
import statistics
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'src'))
from armada_dual_screen_input import marker_overlay
from armada_dual_screen_input.gamescope_focus import FocusSnapshot


def distribution(values):
    values = sorted(values)
    if not values:
        return None
    def percentile(q):
        point = (len(values)-1)*q
        lower = int(point)
        return values[lower]+(values[min(lower+1,len(values)-1)]-values[lower])*(point-lower)
    return dict(p50=percentile(.5), p95=percentile(.95), p99=percentile(.99), maximum=values[-1])


def sample(module, interval, seconds, warmup):
    from gi.repository import GLib
    peers = []
    def spawn(*_, **options):
        peer = socket.fromfd(options['pass_fds'][0], socket.AF_UNIX, socket.SOCK_DGRAM)
        peer.setblocking(False)
        peers.append(peer)
        return SimpleNamespace(poll=lambda:None, wait=lambda **_:0)
    target = FocusSnapshot(10,42,42,1920,1080,42,':1',10,True,1)
    with patch.object(module.subprocess, 'Popen', side_effect=spawn):
        marker = module.MarkerOverlay(target=target)
    peer = peers[0]
    loop = GLib.MainLoop()
    sources = []
    issued, ages, gaps = {}, [], []
    received = generated = 0
    last_event = None
    peer.send(b'{"window":200,"ready":true,"size":[1920,1080]}')
    marker.poll()
    while True:
        try: peer.recv(4096)
        except BlockingIOError: break
    start, cpu = time.monotonic(), time.process_time()

    def receive(*_):
        nonlocal received
        for _ in range(64):
            try: payload = json.loads(peer.recv(4096))
            except BlockingIOError: break
            now = time.monotonic()
            if isinstance(payload,list) and len(payload)==3:
                event = issued.get(round(payload[0]*100000))
                if event is not None and event-start >= warmup:
                    received += 1
                    ages.append((now-event)*1000)
        return True

    def update():
        nonlocal generated, last_event
        now = time.monotonic()
        generated += 1
        if last_event is not None and now-start >= warmup:
            gaps.append((now-last_event)*1000)
        last_event = now
        issued[generated] = now
        marker.update((generated/100000, .4), False)
        return True

    def health():
        marker.poll()
        return True

    def heartbeat():
        peer.send(b'{"alive":true}')
        return True

    def finish():
        loop.quit()
        return False

    try:
        sources.append(GLib.io_add_watch(peer.fileno(), GLib.IO_IN, receive))
        sources.append(GLib.timeout_add(16, health))
        sources.append(GLib.timeout_add(400, heartbeat))
        sources.append(GLib.timeout_add(interval, update))
        sources.append(GLib.timeout_add(round((seconds+warmup)*1000), finish))
        loop.run()
        elapsed, cpu = time.monotonic()-start, time.process_time()-cpu
        measured = sum(t-start >= warmup for t in issued.values())
        return dict(callback_interval_ms=interval, elapsed_s=elapsed,
            generated=measured, received=received,
            callback_to_receive_ms=distribution(ages), source_interval_ms=distribution(gaps),
            cpu_ms=cpu*1000, cpu_percent_one_core=100*cpu/elapsed,
            received_per_second=received/seconds)
    finally:
        context = GLib.MainContext.default()
        for source in sources:
            if context.find_source_by_id(source) is not None:
                GLib.source_remove(source)
        marker.close()
        marker.wait()
        peer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=5)
    options = parser.parse_args()
    if not 1 <= options.seconds <= 30:
        parser.error('--seconds must be between 1 and 30')
    spec = importlib.util.spec_from_file_location('armada_dual_screen_input._marker_baseline', options.baseline)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    results = []
    for interval in (17,8):
        for name in ('baseline','candidate','candidate','baseline'):
            result = sample(baseline if name=='baseline' else marker_overlay, interval, options.seconds, .5)
            result['version'] = name
            results.append(result)
            print(json.dumps(result), flush=True)
    summary = []
    for interval in (17,8):
        for name in ('baseline','candidate'):
            phases = [r for r in results if r['version']==name and r['callback_interval_ms']==interval]
            summary.append(dict(version=name, callback_interval_ms=interval,
                mean_phase_p50_ms=statistics.mean(r['callback_to_receive_ms']['p50'] for r in phases),
                mean_phase_p95_ms=statistics.mean(r['callback_to_receive_ms']['p95'] for r in phases),
                mean_phase_p99_ms=statistics.mean(r['callback_to_receive_ms']['p99'] for r in phases),
                mean_cpu_percent_one_core=statistics.mean(r['cpu_percent_one_core'] for r in phases),
                mean_received_per_second=statistics.mean(r['received_per_second'] for r in phases)))
    report=dict(scope='GLib callback to datagram receiver; no window, GPU or input injection; CPU includes test harness',
                phases=results,summary=summary)
    options.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    main()
