# SPDX-License-Identifier: GPL-2.0-only
"""Read-only Type-B snapshots; no coordinate transformation or motion filter."""
from __future__ import annotations
import math


class LifetimeBudget:
    """A bounded user wait and a separate active window budget."""

    def __init__(self, start, wait_seconds=600, active_seconds=50):
        if not 0 < wait_seconds <= 600 or not 0 < active_seconds <= 50:
            raise ValueError('Waiting/active window bounds are 600/50 seconds')
        self.start = start
        self.wait_seconds, self.active_seconds = wait_seconds, active_seconds
        self.active_started = None

    def start_active(self, now, observed_at=None):
        if self.active_started is not None:
            return True
        observed_at = now if observed_at is None else observed_at
        if not self.start <= observed_at < self.start+self.wait_seconds:
            return False
        self.active_started = now
        return True

    def timeout_reason(self, now):
        if self.active_started is None:
            return 'waiting_timeout' if now >= self.start+self.wait_seconds else None
        return 'active_timeout' if now >= self.active_started+self.active_seconds else None

    def metadata(self):
        return dict(wait_seconds=self.wait_seconds, active_window_seconds=self.active_seconds,
                    wait_started=self.start, wait_deadline=self.start+self.wait_seconds,
                    active_started=self.active_started,
                    active_deadline=self.active_started+self.active_seconds if self.active_started is not None else None)


class SlotState:
    """Keep axis caches across contact lifetimes, just as evdev does."""

    def __init__(self, initial, slot=0):
        self.slots = {int(k): dict(v) for k, v in initial.items()}
        self.slot = slot

    def feed(self, event_type, code, value):
        if event_type == 0 and code == 3:
            raise RuntimeError('SYN_DROPPED')
        if event_type == 3:
            if code == 0x2f:
                self.slot = value
            elif code in (0x39, 0x35, 0x36):
                field = {0x39: 'id', 0x35: 'x', 0x36: 'y'}[code]
                self.slots.setdefault(self.slot, {})[field] = value
        if event_type == 0 and code == 0:
            return {slot: dict(state) for slot, state in self.slots.items()
                    if state.get('id', -1) >= 0}
        return None


class Protocol:
    """One short run: three-second baseline, add second, ten-second scan."""

    POINTS = ((950, 300), (950, 900), (950, 300))

    def __init__(self, trace_required=False, post_hold_seconds=0, scan_mode='moving', continuous_secondary=False):
        if post_hold_seconds not in (0, 3):
            raise ValueError('Post-scan hold must be 0 or 3 seconds')
        if scan_mode not in ('moving', 'stationary'):
            raise ValueError('Unknown scan mode')
        if scan_mode == 'stationary' and post_hold_seconds != 3:
            raise ValueError('Stationary control requires a three-second final baseline')
        if continuous_secondary and scan_mode != 'stationary':
            raise ValueError('Continuous-secondary guard is for stationary controls')
        self.phase = 'hold'
        self.primary = None
        self.phase_at = None
        self.trace_required = trace_required
        self.post_hold_seconds = post_hold_seconds
        self.scan_mode = scan_mode
        self.continuous_secondary = continuous_secondary
        self.fixed_secondary = None
        self.point_index = 0
        self.point_started = self.hold_since = None
        self.secondary_ids = set()
        self.reason = None

    def fail(self, reason):
        self.phase, self.reason = 'invalid', reason

    def step(self, now, ids, trace_ready=False, positions=None):
        if self.phase in ('invalid', 'done'):
            return
        if self.phase == 'lift':
            if not ids:
                self.phase = 'done'
            elif now-self.phase_at > 15:
                self.fail('lift_timeout')
            return
        if len(ids) > 2:
            self.fail('extra_contacts')
            return
        if self.primary is not None and self.primary not in ids:
            self.fail('primary_lifted')
            return
        if self.continuous_secondary and self.phase in ('goto_point', 'hold_point'):
            secondary = [i for i in ids if i != self.primary]
            if secondary != [self.fixed_secondary]:
                self.fail('secondary_changed')
                return
        if self.phase == 'hold':
            if len(ids) == 1:
                self.primary, self.phase_at = ids[0], now
                self.phase = 'trace' if self.trace_required else 'baseline'
            elif ids:
                self.fail('second_too_early')
        elif self.phase == 'trace':
            if len(ids) != 1:
                self.fail('second_too_early')
            elif trace_ready:
                self.phase, self.phase_at = 'baseline', now
            elif now-self.phase_at > 15:
                self.fail('trace_timeout')
        elif self.phase == 'baseline':
            if len(ids) != 1:
                self.fail('second_too_early')
            elif now-self.phase_at >= 3:
                self.phase, self.phase_at = 'add', now
        elif self.phase == 'add':
            if len(ids) == 2:
                self.secondary_ids.update(i for i in ids if i != self.primary)
                if self.scan_mode == 'stationary':
                    if self.continuous_secondary:
                        self.fixed_secondary = next(i for i in ids if i != self.primary)
                    self.phase, self.phase_at, self.point_started = 'goto_point', now, now
                    self._stationary_step(now, ids, positions or {})
                else:
                    self.phase, self.phase_at = 'scan', now
            elif now-self.phase_at > 10:
                self.fail('second_timeout')
        elif self.phase == 'scan':
            self.secondary_ids.update(i for i in ids if i != self.primary)
            if now-self.phase_at >= 10:
                self.phase, self.phase_at = ('release_second' if self.post_hold_seconds else 'lift'), now
        elif self.phase == 'release_second':
            if len(ids) == 1:
                self.phase, self.phase_at = 'postbaseline', now
            elif now-self.phase_at > 10:
                self.fail('secondary_lift_timeout')
        elif self.phase == 'postbaseline':
            if len(ids) != 1:
                self.fail('second_returned')
            elif now-self.phase_at >= self.post_hold_seconds:
                self.phase, self.phase_at = 'lift', now
        elif self.phase in ('goto_point', 'hold_point'):
            self.secondary_ids.update(i for i in ids if i != self.primary)
            self._stationary_step(now, ids, positions or {})

    def _stationary_step(self, now, ids, positions):
        elapsed = now-self.point_started
        if elapsed > 9:
            self.fail('position_timeout')
            return
        secondary = [i for i in ids if i != self.primary]
        point = positions.get(secondary[0]) if len(secondary) == 1 else None
        within = (point is not None and len(point) == 2 and all(math.isfinite(v) for v in point)
                  and math.dist(point, self.POINTS[self.point_index]) <= 80)
        if not within:
            self.phase = 'goto_point'
            self.hold_since = None
            if elapsed > 6:
                self.fail('position_timeout')
            return
        if self.hold_since is None:
            if elapsed > 6:
                self.fail('position_timeout')
                return
            self.hold_since, self.phase_at = now, now
            self.phase = 'hold_point'
        if now-self.hold_since >= 3:
            self.hold_since = None
            if self.point_index+1 == len(self.POINTS):
                self.phase, self.phase_at = 'release_second', now
            else:
                self.point_index += 1
                self.phase, self.phase_at, self.point_started = 'goto_point', now, now

    @property
    def capture_should_stop(self):
        return self.phase in ('lift', 'done', 'invalid')

    def remaining(self, now):
        if self.phase == 'goto_point':
            return max(0, math.ceil(6-(now-self.point_started)))
        if self.phase == 'hold_point':
            return max(0, math.ceil(3-(now-self.hold_since)))
        duration = (self.post_hold_seconds if self.phase == 'postbaseline' else
                    3 if self.phase == 'baseline' else 10)
        return max(0, int(duration-(now-self.phase_at)+.999)) if self.phase_at is not None else 0
