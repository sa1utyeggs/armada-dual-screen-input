"""Persistent, isolated system-pinyin and Gamescope text helper.

Pipe contents are transient typed input: never log or persist them. Native
libraries may print diagnostics, so keep protocol output on a separate fd and
discard their stdout/stderr. Each command has an expiry; nothing is replayed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "armada_dual_screen_input"

from .keyboard_composition import Composition
from .pinyin_engine import PinyinEngine
from .gamescope_text import GamescopeText


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    def terminate(_signal, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    if sys.platform == "linux":
        # Do not retain a native worker if the panel crashes or is killed.
        import ctypes as c
        parent = os.getppid()
        libc = c.CDLL(None)
        libc.prctl.argtypes = [c.c_int, c.c_ulong, c.c_ulong, c.c_ulong, c.c_ulong]
        libc.prctl.restype = c.c_int
        if parent <= 1 or libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() != parent:
            return 1
    output = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    with open(os.devnull, "wb") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    engine = transport = None
    composition = None
    try:
        for raw in sys.stdin:
            request = None
            try:
                if len(raw) > 8192:
                    raise ValueError("Oversized request")
                request = json.loads(raw)
                if not isinstance(request, dict) or type(request.get("id")) is not int:
                    raise ValueError("Invalid request")
                if request.get("kind") == "init":
                    if composition is not None:
                        raise ValueError("Already initialized")
                    engine = PinyinEngine()
                    transport = GamescopeText(args.runtime_dir)
                    composition = Composition(engine, transport)
                    result = composition.state()
                elif composition is None:
                    raise ValueError("Worker is not initialized")
                elif time.monotonic() > request.get("expires", 0):
                    composition.reset()
                    result = composition.state("expired")
                else:
                    result = composition.handle(request)
                result.update(id=request["id"], received_at=time.monotonic())
            except Exception:
                if composition:
                    composition.reset()
                result = {"id": request.get("id", -1) if isinstance(request, dict) else -1,
                          "status": "unavailable"}
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            output.flush()
    finally:
        if transport:
            transport.close()
        if engine:
            engine.close()
        output.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
