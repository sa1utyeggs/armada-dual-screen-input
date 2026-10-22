#!/usr/bin/env python3
"""Deterministic visual replay; no devices, windows, GPU or native input.

These are model/trajectory metrics, never measured touch-to-display latency.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
from armada_dual_screen_input.marker_motion import MarkerMotion
from armada_dual_screen_input.marker_sample import decode_sample, sample_payload

CANVAS = (1920, 1080)
SPEED = 600.


def point(name, at):
    if name == 'straight':
        return (.2+SPEED*min(at, 1.)/(CANVAS[0]-1), .5)
    if name == 'stop':
        return (.2+SPEED*min(at, .6)/(CANVAS[0]-1), .5)
    if name == 'reverse':
        distance = min(at, 1.-at)
        return (.2+SPEED*distance/(CANVAS[0]-1), .5)
    angle = at*math.tau*.75
    return (.5+120*math.cos(angle)/(CANVAS[0]-1), .5+120*math.sin(angle)/(CANVAS[1]-1))


def distance(a, b):
    return math.hypot((a[0]-b[0])*(CANVAS[0]-1), (a[1]-b[1])*(CANVAS[1]-1))


def distribution(values):
    values = sorted(values)
    return {key:values[round((len(values)-1)*q)] if values else None
            for key,q in (('p50',.5),('p95',.95),('p99',.99),('maximum',1))}


def replay(name, render_hz, source_hz):
    motion = MarkerMotion(CANVAS)
    events = [(n/source_hz, 0) for n in range(math.floor(source_hz)+1)]
    events += [(n/render_hz, 1) for n in range(math.floor(1.15*render_hz)+1)]
    events.sort()
    latest = previous = None
    records = []
    draws = baseline_draws = 0
    previous_baseline = None
    for at, kind in events:
        if kind == 0:
            latest = (*point(name,at), False)
            message = sample_payload((latest,),dict(ids=(0,),mode='position',active=True,
                                                    sampled_at=at,snap=False))
            motion.accept(decode_sample(message),at)
            continue
        ring = motion.sample(at)[0]
        if previous != ring:
            draws += 1
        if previous_baseline != latest:
            baseline_draws += 1
        if .15 <= at <= .95:
            records.append(dict(at=at,visual=ring,baseline=latest,
                                visual_offset_px=distance(ring,latest)))
        previous, previous_baseline = ring, latest
    steady = name == 'straight'
    steps = [distance(a['visual'],b['visual']) for a,b in zip(records,records[1:])]
    base_steps = [distance(a['baseline'],b['baseline']) for a,b in zip(records,records[1:])]
    def cv(values):
        return statistics.pstdev(values)/statistics.mean(values) if statistics.mean(values) else 0.
    span = records[-1]['at']-records[0]['at']
    return dict(trajectory=name,render_hz=render_hz,source_hz=source_hz,
                baseline_position_changes=baseline_draws,smoothed_position_changes=draws,
                steady_position_changes_per_second=dict(
                    baseline=sum(a['baseline']!=b['baseline'] for a,b in zip(records,records[1:]))/span,
                    smoothed=sum(a['visual']!=b['visual'] for a,b in zip(records,records[1:]))/span) if steady else None,
                visual_offset_from_confirmed_px=distribution([r['visual_offset_px'] for r in records]),
                straight_step_coefficient_of_variation=dict(baseline=cv(base_steps),smoothed=cv(steps)) if steady else None,
                mean_extra_visual_lag_equivalent_ms=statistics.mean(r['visual_offset_px'] for r in records)/SPEED*1000 if steady else None,
                settled_at_end=not motion.animating,final_position_exact=motion.rings==(latest,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    report = dict(scope='Deterministic continuous-time model replay only; excludes event delivery, GPU/compositor and scanout; no physical latency claim',
                  time_constant_ms=MarkerMotion.TIME_CONSTANT*1000,
                  settle_timeout_ms=MarkerMotion.SETTLE_AFTER*1000,
                  phases=[replay(name,hz,57.7144) for hz in (120,60,30)
                          for name in ('straight','stop','reverse','circle')])
    if args.output:
        args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
