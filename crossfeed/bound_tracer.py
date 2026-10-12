"""BoundTracer -- a PURE OBSERVER progress listener for the LB leg.

WHY THIS EXISTS RATHER THAN REUSING StallStopper.
block_a.solve(track_progress=True) installs a StallStopper, which calls self.abort() as soon
as the best bound plateaus. That is a CONTROL device, not an instrument: switching it on to
capture a convergence curve would end solves early and flip `proven` from True to False on
exactly the slow-converging cells the LB leg cares about. Since `proven` gates the descend's
whole control flow, enabling it "just to log" would have silently changed the bounds we report.

So this listener only appends. It never aborts, never sets a deadline, and is attached from the
descend driver with track_progress=False, so no StallStopper is constructed. The bound values
are bit-identical to a run without it.

WHAT IT RECORDS. CPLEX's best_bound at time t is a valid dual bound for z_A(H) at that instant,
so `best_bound(t) + w(full demand)` is a valid lower bound on z_joint* at time t (proof Step 0
in validation/easy_reduction_bound_proof.md). The trace is therefore a genuine ANYTIME LB curve,
which is what makes time-to-beat and time-to-best measurable rather than inferred from wall
totals.

THINNING. Only points where the bound strictly IMPROVES are kept (plus the final point). CPLEX
notifies on every incumbent too, which at 450 s x ~15 solves x 27 cells would bloat the
artifacts for no information: a flat stretch is fully described by its endpoints. The kept
points ARE the "solver improvements" count.
"""
from __future__ import annotations
from docplex.mp.progress import ProgressListener, ProgressClock


class BoundTracer(ProgressListener):
    def __init__(self, offset: float = 0.0, eps: float = 1e-6):
        super().__init__(ProgressClock.BestBound)
        self.offset = offset          # seconds already spent earlier in this cell's descend
        self.eps = eps
        self.points = []              # [(t_local, best_bound)] at strict improvements only
        self._best = None

    def notify_progress(self, pdata):
        bb = pdata.best_bound
        if bb is None:
            return
        if self._best is None or bb > self._best + self.eps:
            self._best = bb
            self.points.append((round(pdata.time, 2), round(bb, 4)))

    # -- read-side helpers -------------------------------------------------
    def curve(self, wlb: float):
        """Anytime block_relax curve in CELL-GLOBAL seconds: [(t, lb_value), ...]."""
        return [(round(self.offset + t, 2), round(bb + wlb, 4)) for (t, bb) in self.points]

    def n_improvements(self):
        return len(self.points)
