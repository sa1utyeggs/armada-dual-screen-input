"""Focus-free language UI state and a bounded asynchronous native worker."""
from __future__ import annotations

from .i18n import msg, LocalizedState

import json
import os
from pathlib import Path
import queue
import selectors
import subprocess
import sys
import threading
import time

from .keyboard_xkb import XkbLayout

LANGUAGES = {"en_US": "English · US", "zh_CN": msg('language.chinese_pinyin')}


def read_language(config):
    value = config.get("keyboard_language") if isinstance(config, dict) else None
    return value if isinstance(value, str) and value in LANGUAGES else "en_US"


class KeyboardWorker:
    """All subprocess IO/native waits happen off the GTK thread, with a deadline."""
    def __init__(self, runtime, deliver, dispatch):
        self.runtime, self.deliver, self.dispatch = str(runtime), deliver, dispatch
        self.pending = queue.Queue(maxsize=64)
        self.stopped = threading.Event()
        self.process = None
        self._thread = threading.Thread(target=self._run, name="keyboard-ime", daemon=True)
        self._thread.start()

    def submit(self, request):
        if self.stopped.is_set():
            return False
        try:
            self.pending.put_nowait({**request, "expires": time.monotonic() + .75})
            return True
        except queue.Full:
            self.close()
            return False

    def _read(self, selector, process):
        data = bytearray()
        deadline = time.monotonic() + 3.
        while not self.stopped.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError
            block = os.read(process.stdout.fileno(), 65536)
            if not block:
                raise EOFError
            data.extend(block)
            if len(data) > 65536:
                raise ValueError("Oversized worker reply")
            if data.endswith(b"\n"):
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise ValueError("Invalid worker reply")
                return result
        raise EOFError

    def _notify(self, result):
        def notify():
            if not self.stopped.is_set():
                self.deliver(result)
            return False
        self.dispatch(notify)

    def _run(self):
        process = None
        try:
            if self.stopped.is_set():
                return
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", str(Path(__file__).with_name("keyboard_worker.py")),
                 "--runtime-dir", self.runtime], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                close_fds=True,
            )
            self.process = process
            if self.stopped.is_set():
                return
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                serial = 0
                while not self.stopped.is_set():
                    request = self.pending.get()
                    if request is None:
                        break
                    serial += 1
                    request = {**request, "id": serial}
                    # Initial dictionary loading gets the worker deadline too.
                    encoded = (json.dumps(request, ensure_ascii=False) + "\n").encode()
                    process.stdin.write(encoded)
                    result = self._read(selector, process)
                    if result.get("id") != serial:
                        raise ValueError("Worker replies are out of order")
                    self._notify(result)
        except Exception:
            self._notify({"status": "unavailable"})
        finally:
            if process:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=.3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                for stream in (process.stdin, process.stdout):
                    if stream:
                        stream.close()
            self.process = None

    def close(self):
        self.stopped.set()
        process = self.process
        if process and process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            self.pending.put_nowait(None)
        except queue.Full:
            pass


class KeyboardLanguages(LocalizedState):
    def __init__(self, language, *, mode, runtime, changed, dispatch,
                 forward_key, worker_factory=KeyboardWorker, xkb_factory=XkbLayout):
        self.language = read_language({"keyboard_language": language})
        self.mode, self.runtime = mode, runtime
        self.changed, self.dispatch, self.forward_key = changed, dispatch, forward_key
        self.worker_factory, self.xkb_factory = worker_factory, xkb_factory
        self.worker = self.xkb = None
        self.visible = False
        self.closed = False
        self.ready = False
        self.preedit, self.candidates, self.revision = "", [], 0
        self.page = 0
        self.message = msg('ime.english')
        self._generation = 0

    @property
    def label(self):
        return str(LANGUAGES[self.language])

    def clear(self):
        self.preedit, self.candidates, self.page = "", [], 0

    def stop(self):
        self._generation += 1
        if self.worker:
            self.worker.close()
            self.worker = None
        if self.xkb:
            self.xkb.close()
            self.xkb = None
        self.ready = False
        self.clear()

    def set_language(self, language):
        self.stop()
        self.language = read_language({"keyboard_language": language})
        if self.visible:
            self._start()
        self.changed()

    def sync(self, visible):
        visible = bool(visible)
        if self.closed or visible == self.visible:
            return
        self.visible = visible
        self.stop()
        if visible:
            self._start()
        self.changed()

    def _start(self):
        if self.closed or self.language == "en_US":
            self.message = msg('ime.english')
            return
        if self.mode != "game":
            self.message = msg('ime.game_only')
            return
        self.message = msg('ime.preparing')
        generation = self._generation
        try:
            self.xkb = self.xkb_factory()
            self.worker = self.worker_factory(
                self.runtime,
                lambda result: self._response(generation, result), self.dispatch,
            )
            if not self.worker.submit({"kind": "init"}):
                raise RuntimeError("Worker queue unavailable")
        except Exception:
            self.stop()
            self.message = msg('ime.unavailable')

    def _response(self, generation, result):
        if self.closed or generation != self._generation:
            return
        status = result.get("status")
        if status == "unavailable":
            self.stop()
            self.message = msg('ime.unavailable_retry')
        else:
            self.ready = True
            self.preedit = result.get("preedit", "")
            self.candidates = result.get("candidates", [])
            self.revision = result.get("revision", 0)
            self.page = min(self.page, max(0, (len(self.candidates) - 1) // 6))
            self.message = {
                "focus_changed": msg('ime.focus_changed'),
                "expired": msg('ime.expired'),
                "stale_candidate": msg('ime.stale'),
            }.get(status, msg('ime.help'))
            code = result.get("forward_key")
            if (type(code) is int and code in (1, 15, 103, 108)
                    and 0 <= time.monotonic() - result.get("received_at", 0) <= .2):
                self.forward_key(code)
        self.changed()

    def key(self, code, *, shift=False, caps=False, shortcut=False):
        if self.language != "zh_CN" or shortcut:
            return False
        if not self.ready or self.worker is None:
            # Never leak a user's pending pinyin as English into the target.
            return True
        text = self.xkb.character(code, shift=shift, caps=caps)
        if not self.worker.submit({"kind": "key", "code": code, "text": text, "page": self.page}):
            self.stop()
            self.message = msg('ime.queue_stopped')
            self.changed()
        return True

    def choose(self, index):
        if self.ready and self.worker:
            self.worker.submit({"kind": "choose", "index": index, "revision": self.revision})

    def reset(self):
        self.clear()
        if self.worker:
            self.worker.submit({"kind": "reset"})
        self.changed()

    def turn_page(self, direction):
        self.page = max(0, min(max(0, (len(self.candidates) - 1) // 6), self.page + direction))
        self.changed()

    def close(self):
        self.closed = True
        self.stop()
