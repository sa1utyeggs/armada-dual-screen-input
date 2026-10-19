"""Keyboard ordering and cancellation checks without GTK or input devices."""
import unittest
from unittest.mock import patch

from keyboard_pulses import KeyboardPulses


class FakeScheduler:
    def __init__(self):
        self.now = 0
        self.next_id = 1
        self.pending = {}
        self.callbacks = {}
        self.cancelled = []

    def schedule(self, delay_ms, callback):
        source = self.next_id
        self.next_id += 1
        self.pending[source] = (self.now + delay_ms, callback)
        self.callbacks[source] = callback
        return source

    def cancel(self, source):
        self.cancelled.append(source)
        self.pending.pop(source, None)

    def run_due(self):
        while self.pending:
            source = min(self.pending, key=lambda s: (self.pending[s][0], s))
            if self.pending[source][0] > self.now:
                break
            _, callback = self.pending.pop(source)
            callback()

    def advance(self, duration_ms):
        end = self.now + duration_ms
        while self.pending:
            deadline = min(item[0] for item in self.pending.values())
            if deadline > end:
                break
            self.now = deadline
            self.run_due()
        self.now = end

    def stall(self, duration_ms):
        """Simulate a busy event loop delivering overdue callbacks together."""
        self.now += duration_ms
        self.run_due()


class KeyboardPulseTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = FakeScheduler()
        self.events = []
        self.keys = KeyboardPulses(
            send_key=lambda code, down: self.events.append((self.scheduler.now, code, down)),
            schedule=self.scheduler.schedule,
            cancel=self.scheduler.cancel,
        )

    def test_tap_is_immediate_and_never_sleeps(self):
        with patch("time.sleep", side_effect=AssertionError("Blocking sleep")):
            self.keys.tap(30)
        self.assertEqual(self.events, [(0, 30, True)])
        self.scheduler.advance(19)
        self.assertEqual(len(self.events), 1)
        self.scheduler.advance(1)
        self.assertEqual(self.events, [(0, 30, True), (20, 30, False)])
        self.assertFalse(self.scheduler.pending)

    def test_fast_same_key_releases_old_press_and_ignores_old_callback(self):
        self.keys.tap(30)
        old_callback = self.scheduler.callbacks[1]
        self.scheduler.advance(5)
        self.keys.tap(30)
        self.assertEqual(self.events, [(0, 30, True), (5, 30, False), (5, 30, True)])
        old_callback()
        self.assertEqual(len(self.events), 3)
        self.scheduler.advance(20)
        self.assertEqual(self.events[-1], (25, 30, False))
        old_callback()
        self.assertEqual(len(self.events), 4)

    def test_different_keys_keep_independent_pending_releases(self):
        self.keys.tap(30)
        self.scheduler.advance(5)
        self.keys.tap(31)
        self.assertEqual(self.events, [(0, 30, True), (5, 31, True)])
        self.scheduler.advance(15)
        self.assertEqual(self.events[-1], (20, 30, False))
        self.scheduler.advance(5)
        self.assertEqual(self.events[-1], (25, 31, False))

    def test_default_repeat_waits_then_preserves_interval(self):
        self.keys.tap(14)
        self.keys.begin_repeat(14)
        self.scheduler.advance(349)
        self.assertEqual(self.events, [(0, 14, True), (20, 14, False)])
        self.scheduler.advance(1)
        self.assertEqual(self.events[-1], (350, 14, True))
        self.scheduler.advance(60)
        self.assertEqual(self.events[-2:], [(370, 14, False), (410, 14, True)])
        self.keys.release()

    def test_late_repeat_does_not_emit_backlog(self):
        self.keys.begin_repeat(14)
        self.scheduler.stall(1000)
        self.assertEqual(self.events, [(1000, 14, True)])
        self.scheduler.advance(59)
        self.assertEqual(self.events, [(1000, 14, True), (1020, 14, False)])
        self.scheduler.advance(1)
        self.assertEqual(self.events[-1], (1060, 14, True))
        self.keys.release()

    def test_stop_repeat_does_not_flush_first_pulse(self):
        self.keys.tap(30)
        self.keys.begin_repeat(30)
        repeat_callback = self.scheduler.callbacks[2]
        self.scheduler.advance(5)
        self.keys.stop_repeat()
        self.assertEqual(self.events, [(0, 30, True)])
        repeat_callback()
        self.scheduler.advance(15)
        self.assertEqual(self.events, [(0, 30, True), (20, 30, False)])
        self.scheduler.advance(1000)
        self.assertEqual(len(self.events), 2)

    def test_new_repeat_invalidates_old_callback_without_cancelling_new_repeat(self):
        self.keys.begin_repeat(30)
        old_callback = self.scheduler.callbacks[1]
        self.keys.begin_repeat(31, delay_ms=150, interval_ms=40)
        old_callback()
        self.assertFalse(self.events)
        self.scheduler.advance(150)
        self.assertEqual(self.events, [(150, 31, True)])
        self.scheduler.advance(40)
        self.assertEqual(self.events[-1], (190, 31, True))
        self.keys.release()

    def test_release_flushes_before_caller_releases_modifier(self):
        self.keys.tap(30)
        self.keys.tap(31)
        self.keys.begin_repeat(31)
        callbacks = list(self.scheduler.callbacks.values())
        self.keys.release()
        self.events.append((0, 42, False))
        self.assertEqual(self.events, [
            (0, 30, True), (0, 31, True),
            (0, 30, False), (0, 31, False), (0, 42, False),
        ])
        for callback in callbacks:
            callback()
        self.scheduler.advance(1000)
        self.assertEqual(len(self.events), 5)
        self.assertFalse(self.scheduler.pending)
        self.keys.tap(32)
        self.assertEqual(self.events[-1], (1000, 32, True))

    def test_close_is_idempotent_and_late_callbacks_cannot_press(self):
        self.keys.tap(30)
        self.keys.begin_repeat(30)
        callbacks = list(self.scheduler.callbacks.values())
        self.keys.close()
        self.keys.close()
        self.keys.tap(31)
        self.keys.begin_repeat(31)
        for callback in callbacks:
            callback()
        self.scheduler.advance(1000)
        self.assertEqual(self.events, [(0, 30, True), (0, 30, False)])
        self.assertFalse(self.scheduler.pending)

    def test_scheduling_failure_releases_key(self):
        def cannot_schedule(delay_ms, callback):
            raise RuntimeError("Scheduler unavailable")

        keys = KeyboardPulses(
            send_key=lambda code, down: self.events.append((0, code, down)),
            schedule=cannot_schedule, cancel=self.scheduler.cancel,
        )
        with self.assertRaisesRegex(RuntimeError, "Scheduler unavailable"):
            keys.tap(30)
        self.assertEqual(self.events, [(0, 30, True), (0, 30, False)])


if __name__ == "__main__":
    unittest.main()
