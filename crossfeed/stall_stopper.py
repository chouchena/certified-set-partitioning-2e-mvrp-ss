"""
StallStopper — a docplex progress listener that lets a MIP run as long as
its best bound keeps improving, and aborts once it plateaus.

Answers a concrete question from the block-A dual-bound experiment: was
the |C|=20 hard-cell bound "loose" (structurally weak, more time won't
help) or just "slow to converge" (still climbing, needs more time)? A
fixed time limit can't tell those apart. This can: give it a generous
ceiling (comparable to Karademir's 4 h) but cut it off as soon as the
bound stops moving, and keep the full (time, best_bound, incumbent)
trace so the convergence curve is inspectable afterwards, not just the
final number.

Usage:
    stopper = StallStopper(patience_s=450, min_window_improve=0.01, max_time_s=14400)
    m.add_progress_listener(stopper)
    m.parameters.timelimit = 14400   # the ceiling; stopper cuts in earlier
    sol = m.solve()
    # stopper.trace -> [(t, best_bound, incumbent_or_None), ...]
    # stopper.stopped_reason -> "stalled" | "max_time" | None (hit CPLEX's own limit/proof)

WINDOW criterion (fixed 2026-09-01 from the C203/C204 block-A runs, which
never aborted despite an obvious plateau): the old test asked "did the
bound improve since the last notification" — a steady sub-1%/step crawl
passes it forever. The window test asks "did the bound improve by more
than `min_window_improve` (relative) over the last `patience_s` seconds"
— a crawl fails that.
"""
from __future__ import annotations
from collections import deque
from docplex.mp.progress import ProgressListener, ProgressClock


class StallStopper(ProgressListener):
    def __init__(self, patience_s: float = 450.0, min_window_improve: float = 0.01,
                 max_time_s: float | None = None, warmup_s: float = 120.0):
        super().__init__(ProgressClock.BestBound)
        self.patience_s = patience_s
        self.min_window_improve = min_window_improve
        self.max_time_s = max_time_s
        self.warmup_s = warmup_s          # don't judge a plateau before this
        self.trace = []                   # [(t, best_bound, incumbent_or_None)]
        self.stopped_reason = None
        self._win = deque()               # (t, bb) within the trailing window

    def notify_progress(self, pdata):
        t = pdata.time
        bb = pdata.best_bound
        obj = pdata.current_objective if pdata.has_incumbent else None
        self.trace.append((round(t, 1), bb, obj))

        if self.max_time_s is not None and t >= self.max_time_s:
            self.stopped_reason = "max_time"
            self.abort()
            return

        if bb is None:
            return
        self._win.append((t, bb))
        while self._win and self._win[0][0] < t - self.patience_s:
            self._win.popleft()

        # only judge once we have a full trailing window and past warmup
        if t < self.warmup_s or not self._win or self._win[0][0] > t - self.patience_s + 1:
            return
        bb_then = self._win[0][1]
        rel_gain = (bb - bb_then) / max(1.0, abs(bb_then))
        if rel_gain < self.min_window_improve:
            self.stopped_reason = f"stalled(+{rel_gain:.3%}/{self.patience_s:.0f}s)"
            self.abort()

    def summary(self):
        """Convergence read: bound value at a few checkpoints + verdict."""
        if not self.trace:
            return {"n_points": 0}
        checkpoints = {}
        for target in (60, 300, 600, 900, 1500, 3600, 7200, 14400):
            pts = [bb for (t, bb, _) in self.trace if t <= target and bb is not None]
            if pts:
                checkpoints[f"bound@{target}s"] = round(pts[-1], 2)
        last_t, last_bb, _ = self.trace[-1]
        return {"n_points": len(self.trace), "final_time": round(last_t, 1),
                "final_bound": round(last_bb, 2) if last_bb is not None else None,
                "stopped_reason": self.stopped_reason, "checkpoints": checkpoints}
