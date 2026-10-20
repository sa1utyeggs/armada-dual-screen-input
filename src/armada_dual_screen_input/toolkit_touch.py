"""Translate toolkit touch sequences to Ratatoskr's logical touch handlers.

This module never reads evdev, grabs a digitizer, or accepts mouse events.  Call
it only from a toolkit's actual TOUCH_BEGIN/UPDATE/END/CANCEL handler, using the
event's sequence object as the key.  A ``None`` sequence is deliberately ignored
so an emulated pointer event cannot feed virtual mouse output back into input.

Coordinates must be in DrawingArea allocation units, not raw device pixels.
Render the UI with the same allocation-to-logical scaling.  The toolkit already
accounts for panel rotation and display scale; do not apply raw_to_screen().

All gesture lifetime timestamps use one injected monotonic clock. Do not mix
them with raw-frame or wall-clock timestamps. Optional GDK source times supply
only per-contact motion intervals, never absolute gesture times. Call keepalive() periodically and before
gesture expiry; on_activity should refresh ONLY the engine contact's seen_t.
Stationary toolkit contacts remain valid until END/CANCEL, not until an evdev
silence timeout. A trusted toolkit first-contact indication may mark a new
group, cancelling contacts whose END/CANCEL was not delivered to this adapter.
Do not infer that indication from elapsed time or a previously unseen sequence.
Cancel all contacts on unmap, session exit, or mode handoff.

Callbacks run synchronously on the caller's thread; use the GTK main thread or
the application's input lock.  Cancellation is distinct from an ordinary lift:
on_cancel must discard gestures and release held output without producing a tap.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Hashable


@dataclass(frozen=True)
class Contact:
    tid: int
    x: float
    y: float
    started_at: float
    updated_at: float
    source_ms: int | None = None
    motion_interval: float | None = None


class ToolkitTouch:
    """Map stable toolkit sequence keys to increasing, never-reused touch IDs."""

    def __init__(
        self,
        on_begin: Callable[[int, float, float, float], None],
        on_update: Callable[[int, float, float, float], None],
        on_end: Callable[[int, float], None],
        on_cancel: Callable[[int, float], None],
        *,
        on_activity: Callable[[int, float], None] | None = None,
        on_timed_update: Callable[[int, float, float, float, float | None], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        logical_width: float = 1240,
        logical_height: float = 1080,
        viewport_width: float = 1240,
        viewport_height: float = 1080,
    ) -> None:
        self.logical_width = self._dimension(logical_width)
        self.logical_height = self._dimension(logical_height)
        self.viewport_width = self._dimension(viewport_width)
        self.viewport_height = self._dimension(viewport_height)
        self._on_begin = on_begin
        self._on_update = on_update
        self._on_end = on_end
        self._on_cancel = on_cancel
        self._on_activity = on_activity
        self._on_timed_update = on_timed_update
        self._clock = clock
        self._last_time = -math.inf
        self._last_event_time: float | None = None
        self._next_tid = 1
        self._contacts: dict[Hashable, Contact] = {}
        self.enabled = True

    @staticmethod
    def _dimension(value: float) -> float:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("touch dimensions must be finite and positive")
        return value

    def _now(self) -> float:
        value = float(self._clock())
        if not math.isfinite(value):
            raise ValueError("touch clock must return a finite number")
        self._last_time = max(value, self._last_time)
        return self._last_time

    def to_logical(self, x: float, y: float) -> tuple[float, float]:
        x, y = float(x), float(y)
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("touch coordinates must be finite")
        return (
            min(max(x * self.logical_width / self.viewport_width, 0.0), self.logical_width - 1.0),
            min(max(y * self.logical_height / self.viewport_height, 0.0), self.logical_height - 1.0),
        )

    @property
    def active(self) -> tuple[Contact, ...]:
        """An immutable snapshot, in contact-begin order."""
        return tuple(self._contacts.values())

    def owns_sequence(self, sequence: Hashable | None) -> bool:
        """Whether this exact toolkit sequence is already registered."""
        return sequence is not None and sequence in self._contacts

    def quiet_for(self) -> float:
        """Seconds since an accepted real event or contact cancellation.

        Keepalive never changes this baseline. Before the first accepted event
        the result is infinity. This observation does not expire any contacts.
        """
        now = self._now()
        if self._last_event_time is None:
            return math.inf
        return max(0.0, now - self._last_event_time)

    def _refresh_activity(self, now: float) -> None:
        if self._on_activity is not None:
            for contact in tuple(self._contacts.values()):
                self._on_activity(contact.tid, now)

    def keepalive(self) -> int:
        """Keep stationary contacts alive without generating moves or output."""
        self._refresh_activity(self._now())
        return len(self._contacts)

    def begin(
        self, sequence: Hashable | None, x: float, y: float, *,
        source_ms: int | None = None, starts_new_group: bool = False,
        cancel_previous: bool = False,
    ) -> bool:
        """Register a touch, optionally reconciling a trusted new-group boundary.

        ``starts_new_group`` means the toolkit knows that its previous group
        ended. It must not be set for ordinary second fingers or inferred from
        a quiet contact: a real finger may stay stationary indefinitely. The
        boundary repairs a missed application END, not a contact still held by
        the kernel/compositor, which cannot report a fresh group in that case.

        ``cancel_previous`` is a separate explicit adapter recovery decision.
        It cancels old state without asserting that the toolkit saw all lifts.
        """
        if sequence is None or not self.enabled:
            return False
        x, y = self.to_logical(x, y)
        now = self._now()
        if (starts_new_group or cancel_previous) and self._contacts:
            # Cancel, never lift: ghost fingers must not produce a late tap.
            # Clear all old sequences before reusing even the same boxed key.
            self.release_all()
            now = self._now()
        self._refresh_activity(now)
        previous = self._contacts.pop(sequence, None)
        if previous is not None:
            self._last_event_time = now
            self._on_cancel(previous.tid, now)
        contact = Contact(self._next_tid, x, y, now, now, source_ms)
        self._next_tid += 1
        self._contacts[sequence] = contact
        self._last_event_time = now
        self._on_begin(contact.tid, x, y, now)
        return True

    def update(self, sequence: Hashable | None, x: float, y: float, *, source_ms: int | None = None) -> bool:
        contact = self._contacts.get(sequence)
        if contact is None or not self.enabled:
            return False
        x, y = self.to_logical(x, y)
        now = self._now()
        self._refresh_activity(now)
        # Source time is used only for motion physics. Contact lifetime and
        # click timing stay on the injected monotonic clock above. A delayed
        # batch of callbacks must not look like a sudden burst of finger speed.
        interval = None
        if source_ms is not None:
            interval = 0.0  # no reliable velocity until two source times exist
            if contact.source_ms is not None:
                delta = (source_ms - contact.source_ms) % (2 ** 32)
                if 0 < delta <= 500:
                    interval = delta / 1000.0
                elif delta == 0:
                    interval = contact.motion_interval or 0.0
        self._contacts[sequence] = Contact(contact.tid, x, y, contact.started_at, now, source_ms, interval)
        self._last_event_time = now
        if self._on_timed_update is not None:
            self._on_timed_update(contact.tid, x, y, now, interval)
        else:
            self._on_update(contact.tid, x, y, now)
        return True

    def end(self, sequence: Hashable | None) -> bool:
        if sequence not in self._contacts:
            return False
        now = self._now()
        self._refresh_activity(now)
        contact = self._contacts.pop(sequence)
        self._last_event_time = now
        self._on_end(contact.tid, now)
        return True

    def cancel(self, sequence: Hashable | None) -> bool:
        if sequence not in self._contacts:
            return False
        now = self._now()
        self._refresh_activity(now)
        contact = self._contacts.pop(sequence)
        self._last_event_time = now
        self._on_cancel(contact.tid, now)
        return True

    def release_all(self) -> int:
        """Cancel every contact, even if one cleanup callback raises an error."""
        if not self._contacts:
            return 0
        now = self._now()
        contacts = self.active
        self._contacts.clear()
        self._last_event_time = now
        first_error: Exception | None = None
        for contact in contacts:
            try:
                self._on_cancel(contact.tid, now)
            except Exception as err:
                if first_error is None:
                    first_error = err
        if first_error is not None:
            raise first_error
        return len(contacts)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        if not self.enabled:
            self.release_all()

    def set_viewport(self, width: float, height: float) -> bool:
        """Cancel a gesture before resizing, avoiding an artificial pointer jump."""
        width, height = self._dimension(width), self._dimension(height)
        if (width, height) == (self.viewport_width, self.viewport_height):
            return False
        self.release_all()
        self.viewport_width, self.viewport_height = width, height
        return True
