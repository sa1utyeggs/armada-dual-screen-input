"""Non-blocking keyboard taps for one event-loop thread.

``schedule(ms, callback)`` must schedule a deferred, one-shot callback and
return a handle accepted by ``cancel(handle)``. Callbacks return ``False`` so
GLib.timeout_add can be passed directly. No worker thread sleeps or sends
events after a key's owner has cancelled it.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class KeyboardPulses:
    def __init__(
        self,
        send_key: Callable[[int, bool], None],
        schedule: Callable[[int, Callable[[], bool]], Any],
        cancel: Callable[[Any], Any],
    ) -> None:
        self._send_key = send_key
        self._schedule = schedule
        self._cancel = cancel
        self._pending: dict[int, tuple[object, Any]] = {}
        self._repeat_token: object | None = None
        self._repeat_source: Any = None
        self._closed = False

    def tap(self, code: int, delay_s: float = 0.02) -> None:
        """Press now and release later; consecutive taps always have an up edge."""
        if self._closed:
            return
        self._flush(code)
        token = object()
        self._send_key(code, True)

        def finish() -> bool:
            pending = self._pending.get(code)
            if pending is not None and pending[0] is token:
                del self._pending[code]
                self._send_key(code, False)
            return False

        try:
            source = self._schedule(max(0, round(delay_s * 1000)), finish)
        except Exception:
            # A scheduling failure must not leave the key physically held.
            self._send_key(code, False)
            raise
        self._pending[code] = (token, source)

    def begin_repeat(self, code: int, delay_ms: int = 350, interval_ms: int = 60) -> None:
        """Repeat after the initial delay; the caller sends the first tap."""
        self.stop_repeat()
        if self._closed:
            return
        token = object()
        self._repeat_token = token
        interval_ms = max(1, round(interval_ms))

        def repeat() -> bool:
            if self._closed or self._repeat_token is not token:
                return False
            self._repeat_source = None
            self.tap(code)
            if not self._closed and self._repeat_token is token:
                # Schedule relative to delivery, never catch up missed repeats.
                self._repeat_source = self._schedule(interval_ms, repeat)
            return False

        self._repeat_source = self._schedule(max(0, round(delay_ms)), repeat)

    def stop_repeat(self) -> None:
        """Stop future repeats without shortening an outstanding tap."""
        self._repeat_token = None
        source, self._repeat_source = self._repeat_source, None
        if source is not None:
            self._cancel(source)

    def _flush(self, code: int) -> None:
        pending = self._pending.pop(code, None)
        if pending is not None:
            # Invalidate before cancellation: even a late callback is harmless.
            try:
                self._cancel(pending[1])
            finally:
                self._send_key(code, False)

    def release(self) -> None:
        """Stop repeats and release every pending key before modifier release."""
        self.stop_repeat()
        self.flush_pending()

    def flush_pending(self) -> None:
        """Finish short taps before a modifier changes, keeping repeat intent."""
        for code in list(self._pending):
            self._flush(code)

    def close(self) -> None:
        """Release everything and permanently reject new key-down events."""
        self._closed = True
        self.release()
