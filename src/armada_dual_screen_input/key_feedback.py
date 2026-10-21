"""Minimum visible key feedback, independent of logical key ownership/output."""
from __future__ import annotations

import math
import time


class KeyFeedback:
    def __init__(self, schedule, cancel, changed, *, clock=time.monotonic, minimum_ms=60):
        self.schedule, self.cancel, self.changed = schedule, cancel, changed
        self.clock, self.minimum = clock, minimum_ms/1000
        self.active = None
        self.records = {}
        self.closed = False

    @property
    def visible(self):
        return frozenset(self.records)

    def _arm(self, code, record):
        if record['held'] or record['painted'] is None or record['source'] is not None:
            return
        delay = max(0, math.ceil((record['painted']+self.minimum-self.clock())*1000))
        if delay == 0:
            self.records.pop(code,None)
            self.changed()
            return
        def finish():
            if not self.closed and self.records.get(code) is record and not record['held']:
                self.records.pop(code,None)
                self.changed()
            return False
        record['source'] = self.schedule(delay,finish)

    def sync(self, active):
        if self.closed or active == self.active:
            return
        previous, self.active = self.active, active
        old = self.records.get(previous)
        if old is not None:
            old['held'] = False
            self._arm(previous,old)
        if active is not None:
            stale = self.records.get(active)
            if stale is not None and stale['source'] is not None:
                self.cancel(stale['source'])
            self.records[active] = dict(held=True,painted=None,source=None)
        self.changed()

    def painted(self, codes):
        if self.closed:
            return
        for code in codes:
            record = self.records.get(code)
            if record is not None and record['painted'] is None:
                record['painted'] = self.clock()
                self._arm(code,record)

    def clear(self):
        for record in self.records.values():
            if record['source'] is not None:
                self.cancel(record['source'])
        changed = bool(self.records)
        self.records.clear(); self.active = None
        if changed and not self.closed:
            self.changed()

    def close(self):
        self.closed = True
        self.clear()
