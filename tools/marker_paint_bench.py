#!/usr/bin/env python3
"""Offscreen CPU benchmark; no windows, input devices or personal settings.

Requires the Linux Cairo runtime. Compare separate source exports with
--source-root. CPU timings cover only scene preparation/painting, not GTK/GL
submission, compositor GPU work, physical input latency or whole-app usage.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=2000)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 100 or args.rounds < 2:
        parser.error('at least 100 iterations and two rounds are required')
    root=args.source_root.resolve()
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(root/'src'))
    import cairo
    from armada_dual_screen_input.marker_paint import MarkerScene,draw_rings
    canvas=(1920,1080)
    result={}
    for count in (1,2,5):
        rows=[]
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,*canvas)
        scene=MarkerScene(canvas)
        trace=[tuple((.15+i*.14+frame*.00013,.3+i*.06+frame*.00007,True)
                     for i in range(count)) for frame in range(64)]
        def frame(index):
            scene.update(trace[index%len(trace)])
            cr=cairo.Context(surface)
            for rect in scene.take_damage():cr.rectangle(*rect)
            cr.clip();draw_rings(cr,scene.rings,canvas)
        for index in range(1000):frame(index)
        for _ in range(args.rounds):
            start=time.process_time_ns()
            for index in range(args.iterations):frame(index)
            rows.append((time.process_time_ns()-start)/args.iterations/1000)
        result[str(count)]=dict(median_cpu_us_per_frame=statistics.median(rows),samples=rows)
    result=dict(scope='offscreen CPU only',canvas=canvas,iterations=args.iterations,rounds=args.rounds,
                source_sha256=hashlib.sha256((root/'src/armada_dual_screen_input/marker_paint.py').read_bytes()).hexdigest(),
                cases=result)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    main()
