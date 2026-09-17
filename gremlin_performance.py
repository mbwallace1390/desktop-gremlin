"""Rolling frame measurements and decorative quality control; no simulation state."""
from collections import deque
import math


class PerformanceMonitor:
    def __init__(self):
        self.samples = deque(maxlen=240)
        self.detail = 1.0
        self.overloaded = 0.0
        self.headroom = 0.0
        self.dropped_seconds = 0.0

    def record(self, interval, update_ms, draw_ms, steps, dropped, period,
               automatic=True, active=True):
        values = (interval, update_ms, draw_ms, dropped, period)
        if not all(math.isfinite(v) and v >= 0 for v in values) or period <= 0:
            return
        self.samples.append((interval, update_ms, draw_ms, steps))
        self.dropped_seconds += dropped
        if not automatic:
            self.detail = 1.0
            self.overloaded = self.headroom = 0.0
            return
        if not active:
            self.overloaded = self.headroom = 0.0
            return
        # Only sustained pressure changes detail. Sleeping or pausing cannot
        # masquerade as spare rendering capacity or a performance regression.
        cost = update_ms + draw_ms
        elapsed = min(interval, .25)
        if cost > period * 850 or interval > period * 1.35:
            self.overloaded += elapsed
            self.headroom = 0.0
            if self.overloaded >= 1.5:
                self.detail = max(.25, self.detail - .15)
                self.overloaded = 0.0
        elif cost < period * 550 and interval < period * 1.15:
            self.headroom += elapsed
            self.overloaded = 0.0
            if self.headroom >= 6.0:
                self.detail = min(1.0, self.detail + .1)
                self.headroom = 0.0
        else:
            self.overloaded = self.headroom = 0.0

    def snapshot(self):
        rows = list(self.samples)
        if not rows:
            return dict(fps=0.0, update_ms=0.0, draw_ms=0.0, p95_ms=0.0, frame_p95_ms=0.0,
                        steps=0.0, detail=self.detail, dropped=self.dropped_seconds)
        intervals = sorted(r[0] for r in rows if r[0] > 0)
        costs = sorted(r[1] + r[2] for r in rows)
        n = len(rows)
        return dict(fps=len(intervals) / sum(intervals) if intervals else 0.0,
                    update_ms=sum(r[1] for r in rows) / n,
                    draw_ms=sum(r[2] for r in rows) / n,
                    p95_ms=costs[max(0, math.ceil(n * .95) - 1)],
                    frame_p95_ms=(intervals[math.ceil(len(intervals) * .95) - 1] * 1000
                                  if intervals else 0.0),
                    steps=sum(r[3] for r in rows) / n, detail=self.detail,
                    dropped=self.dropped_seconds)
