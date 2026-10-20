"""Lease a reversible Steam UI keyboard block while our keyboard is visible.

The GTK thread only updates intent. Local CDP traffic runs in a daemon thread;
the renderer expires the block independently if UI heartbeats or this process
stop. Requires the already-enabled local Steam debugger and websocket-client.
Missing/debugger-incompatible Steam fails open without changing Steam settings.
"""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import urllib.request
import uuid


def keyboard_guard_wanted(session: str, mode: str, collapsed: bool, mapped: bool) -> bool:
    return session == "game" and mode in ("keyboard", "split") and not collapsed and mapped


class SteamKeyboardGuard:
    def __init__(self) -> None:
        self.owner = uuid.uuid4().hex
        self.script = Path(__file__).with_suffix(".js").read_text()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._enabled = False
        self._pulse = 0.0
        self._thread = None
        self._ws = None
        self._target = None
        self._sequence = 0
        self._was_active = False
        self._last_report = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="steam-keyboard-guard", daemon=True)
        self._thread.start()

    def update(self, enabled: bool) -> None:
        with self._lock:
            changed = self._enabled != enabled
            self._enabled = enabled
            self._pulse = time.monotonic()
        if changed:
            self._wake.set()

    def stop(self) -> None:
        self.update(False)
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=0.25)

    def _report(self, message: str) -> None:
        if message != self._last_report:
            print(f"[steam-keyboard] {message}", flush=True)
            self._last_report = message

    def _close_socket(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close(timeout=0)
            except Exception:
                pass
        self._ws = self._target = None

    def _connect(self) -> None:
        import websocket
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:8080/json/list", timeout=0.8) as response:
            targets = json.load(response)
        page = next(p for p in targets if p.get("title") == "SharedJSContext")
        url = page["webSocketDebuggerUrl"]
        if not url.startswith("ws://127.0.0.1:8080/"):
            raise ValueError("Unexpected Steam debugger address")
        if self._target != page["id"] or self._ws is None:
            self._close_socket()
            self._ws = websocket.create_connection(url, timeout=0.8, suppress_origin=True,
                                                   http_no_proxy=["127.0.0.1", "localhost"])
            self._target = page["id"]

    def _command(self, action: str) -> dict:
        if action != "release" or self._ws is None:
            self._connect()
        request = json.dumps({"action": action, "owner": self.owner, "ttlMs": 4000})
        self._sequence += 1
        sequence = self._sequence
        self._ws.send(json.dumps({"id": sequence, "method": "Runtime.evaluate", "params": {
            "expression": f"({self.script})({request})", "returnByValue": True,
        }}))
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            message = json.loads(self._ws.recv())
            if message.get("id") == sequence:
                result = message.get("result", {})
                if "error" in message or "exceptionDetails" in result:
                    raise RuntimeError("Steam keyboard guard evaluation failed")
                return result["result"]["value"]
        raise TimeoutError("Steam keyboard guard reply timed out")

    def _release(self) -> None:
        if self._was_active:
            restored = False
            try:
                self._command("release")
                restored = True
            except Exception:
                pass  # Renderer expiry is the independent fallback.
            self._was_active = False
            self._report("released; Steam keyboard behavior restored" if restored else
                         "heartbeat stopped; Steam will restore by lease expiry")
        self._close_socket()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._wake.clear()
                with self._lock:
                    enabled = self._enabled and time.monotonic() - self._pulse < 2.5
                if enabled:
                    try:
                        # Mark possible ownership even if the reply is lost.
                        self._was_active = True
                        status = self._command("renew")
                        self._report("suppression active" if status.get("active") else
                                     "unavailable; Steam keyboard left enabled")
                    except Exception as error:
                        self._close_socket()
                        self._report(f"connection unavailable ({type(error).__name__}); lease will expire")
                else:
                    self._release()
                self._wake.wait(0.75)
        finally:
            self._release()
