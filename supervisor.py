#!/usr/bin/env python3
"""Follow Armada's existing graphics sessions, without managing compositors.

This is an experimental per-user supervisor, not an installation script.
It is safe to run --probe over SSH; --run creates this app's uinput devices
and shows its native GUI only after discovering an unambiguous session.
"""
from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from session_detect import detect_target_session

BASE = Path(__file__).resolve().parent
PORTABLE_LIB = BASE / "runtime/usr/lib64"


def portable_environment(env: dict[str, str]) -> dict[str, str]:
    env = dict(env)
    if (PORTABLE_LIB / "libgtk-layer-shell.so.0").exists():
        env["LD_LIBRARY_PATH"] = str(PORTABLE_LIB)
        env["GI_TYPELIB_PATH"] = str(PORTABLE_LIB / "girepository-1.0")
    return env


def probe(include_desktop: bool = False) -> dict:
    result = {"linux": sys.platform.startswith("linux"), "uinput_writable": os.access("/dev/uinput", os.W_OK)}
    target = detect_target_session(game_only=not include_desktop)
    result["session"] = None if target is None else {
        "mode": target.mode, "wayland_display": target.wayland_display,
        "source_pids": target.source_pids,
    }
    try:
        gi = importlib.import_module("gi")
        for namespace, version in (("Gtk", "3.0"), ("Gdk", "3.0"), ("GtkLayerShell", "0.1")):
            gi.require_version(namespace, version)
            importlib.import_module(f"gi.repository.{namespace}")
        importlib.import_module("cairo")
        result["python_gui_dependencies"] = True
    except (ImportError, ValueError) as error:
        result["python_gui_dependencies"] = False
        result["dependency_error"] = str(error)
    return result


def child_environment(target) -> dict[str, str]:
    # Never carry a previous graphics session, preload, or authentication token
    # from the SSH/systemd environment into the new GUI process.
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONUNBUFFERED": "1"}
    env.update(target.environment)
    env["GDK_BACKEND"] = "wayland"
    env["NO_AT_BRIDGE"] = "1"
    return portable_environment(env)


def target_key(target):
    if target is None:
        return None
    try:
        socket_info = (target.runtime_dir / target.wayland_display).stat()
    except OSError:
        return None
    return (target.mode, str(target.runtime_dir), target.wayland_display,
            target.source_pids, socket_info.st_dev, socket_info.st_ino,
            tuple(sorted(target.environment.items())))


def stop_child(child) -> int | None:
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)
    return child.poll() if child is not None else None


def run(include_desktop: bool = False) -> int:
    if not sys.platform.startswith("linux") or os.getuid() == 0:
        print("Run as the handheld's normal Linux desktop user", file=sys.stderr)
        return 78
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    if not runtime.is_dir() or runtime.stat().st_uid != os.getuid():
        print("Missing same-user XDG_RUNTIME_DIR", file=sys.stderr)
        return 78
    with (runtime / "thor-panel-supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Thor panel supervisor is already running")
            return 0
        child = None
        current = None
        stopping = False
        retry_after = 0.0

        def request_stop(signum, frame):
            nonlocal stopping
            stopping = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, request_stop)
        try:
            while not stopping:
                target = detect_target_session(runtime_dir=runtime, game_only=not include_desktop)
                wanted = target_key(target)
                if wanted != current:
                    stopped_code = stop_child(child)
                    if stopped_code in (0, 78):
                        # Preserve an explicit Close even if it coincides
                        # with the graphics session changing.
                        return stopped_code
                    child = None
                    current = wanted
                    retry_after = 0.0
                if child is not None and child.poll() is not None:
                    code = child.returncode
                    child = None
                    if code == 0:
                        # The GUI's Exit button stops this app, not Armada.
                        return 0
                    if code == 78:
                        return code  # Missing permissions need explicit repair.
                    retry_after = time.monotonic() + 10
                    print(f"Panel exited ({code}); waiting before retry", flush=True)
                if target is not None and current is not None and child is None and time.monotonic() >= retry_after:
                    print(f"Starting panel in {target.mode} session", flush=True)
                    child = subprocess.Popen(
                        [sys.executable, str(BASE / "panel_app.py"), "--mode", target.mode],
                        env=child_environment(target), cwd=BASE,
                    )
                time.sleep(2)
        finally:
            stop_child(child)
    return 0


def main() -> int:
    # The dynamic loader reads LD_LIBRARY_PATH at process startup. Re-exec
    # once rather than editing the system loader or the user's global env.
    prepared = portable_environment(dict(os.environ))
    if any(os.environ.get(key) != prepared.get(key) for key in ("LD_LIBRARY_PATH", "GI_TYPELIB_PATH")):
        os.execve(sys.executable, [sys.executable, *sys.argv], prepared)
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--probe", action="store_true", help="Read-only checks; creates no input devices")
    action.add_argument("--run", action="store_true", help="Run the experimental GUI for the current session")
    parser.add_argument("--include-desktop", action="store_true", help="Experimental, unvalidated Desktop support; disabled by default")
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(args.include_desktop), ensure_ascii=False, indent=2))
        return 0
    return run(args.include_desktop)


if __name__ == "__main__":
    raise SystemExit(main())
