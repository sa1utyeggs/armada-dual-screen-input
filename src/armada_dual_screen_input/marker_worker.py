#!/usr/bin/env python3
"""Passive marker worker with an optional native EGL submission path.

Both backends own an input-transparent same-app decoration only. If native
setup is unavailable, fall back before publishing/mapping a window or using
IPC; errors after activation fail closed instead of switching a live target.
"""
from __future__ import annotations

import argparse
import json
import socket

from .marker_colors import DEFAULT_COLORS, MarkerColors, parse_color


def run(fd, target, frame_rate='auto', *, colors=DEFAULT_COLORS):
    from .marker_native_worker import NativeUnavailable, run as native_run
    try:
        return native_run(fd, target, frame_rate, colors=colors)
    except NativeUnavailable:
        from .marker_gtk_worker import run as gtk_run
        return gtk_run(fd, target, frame_rate, colors=colors)


if __name__ == '__main__':
    from .marker_target import MarkerTarget
    from .marker_frames import FRAME_RATES
    parser = argparse.ArgumentParser()
    parser.add_argument('--fd', type=int, required=True)
    parser.add_argument('--target', type=MarkerTarget.decode, required=True)
    parser.add_argument('--frame-rate', choices=FRAME_RATES, default='auto')
    parser.add_argument('--idle-color', type=parse_color, default=DEFAULT_COLORS.idle)
    parser.add_argument('--pressed-color', type=parse_color, default=DEFAULT_COLORS.pressed)
    args = parser.parse_args()
    try:
        run(args.fd, args.target, args.frame_rate,
            colors=MarkerColors(args.idle_color, args.pressed_color))
    except Exception as error:
        try:
            socket.socket(fileno=args.fd).send(json.dumps({'error': str(error)}).encode())
        except OSError:
            pass
        raise SystemExit(1)
