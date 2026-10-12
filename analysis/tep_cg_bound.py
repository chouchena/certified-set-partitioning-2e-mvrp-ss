"""TEP dual leg, piece 2: column generation with a TIME-EXPANDED car flow (FORMULATION_TEP §10,
amendment 1 of 2026-09-23).

Every step below relaxes the joint model (K's constraints as verifier3 checks them), so the
converged LP value is a valid lower bound on the STREET part of the objective,
    penalty_cars * cars + travelcoststreet * street travel;
the water part (vessel penalty + water travel) is bounded separately and added at reporting.

Time is cut into buckets of width DELTA with DELTA * win = tau (U).  s_b = H0 + b * DELTA.
NODES   src (cars leave the depot; N enters), pre(p, b) (car at satellite p waiting for its
        transfer), post(p, b) (car at p after a transfer, free to start a trip), sink.
ARCS    wait pre(p,b)->pre(p,b+1), post(p,b)->post(p,b+1) at 0;
        transfer z(p,b): pre(p,b)->post(p,b+win) at 0 -- the transfer STARTS in bucket b, i.e.
        u in [s_b, s_b+DELTA); allowed only where (13) and (12,g) admit such a u;
        return post(p,b)->sink at c^s * D[p][depot], allowed only if s_b + D[p][depot] <= b_g
        (the last customer of every route carries a transfer, (4), so every route returns from a hub);
        COLUMN (trip r, start L, start bucket b, hub p): from src (L = depot; the car leaves at
        H0, the dominant start) or from post(L, b) (L a satellite, the car leaves at s >= s_b),
        into pre(p, b_arr) with b_arr = floor((earliest arrival at p - H0)/DELTA) computed by
        forward simulation from the start's earliest leave time s_b (arrival is nondecreasing in
        s, so this is the smallest bucket any car starting in bucket b can reach: a relaxation).
ROWS    covering: every customer >= 1 (coefficient = visits, ng columns may repeat a customer);
        balance at every pre/post node and at src (N = columns leaving src);
        booking: for every p and b, sum_{b' in [b, b+win-1]} z(p,b') <= 1 -- valid because (26)
        makes any two transfers at p at least U = win*DELTA apart, so their true start buckets
        differ by >= win and never share a window.  The transfer bucket is the TRUE one because
        the car waits on pre-nodes until it: this is what the first draft got wrong (it hung the
        row on the earliest-arrival bucket, which can cut a feasible timetable).
WINDOWS Table 1's h_i >= a_g + t_gi and h_i <= b_g - t_ig - tau_i - U tighten every customer
        window (K's own bounds), in the pricer and in the simulation.
PRICING the labeling (tep_pricer) with pi and per-customer entry/exit values that underestimate
        every variant's flow-dual terms (entry[c] = min over start nodes of c^s*D[L][c] + mu_start,
        exit[c] = min over pre nodes of c^s*D[c][p] - mu_pre); a trip it returns is then expanded
        to its best feasible variant at the exact reduced cost.  Convergence: the exact pricer
        (not exhausted, not truncated) returns no trip whose best variant has rc < -1e-6.

    python analysis/tep_cg_bound.py R204 [--delta 20] [--ng 10 | --ng 0] [--iters 80] [--build-only]
Gurobi LP at 1 thread (the only solver use); pricing is pure Python.  --ng 0 = elementary.
"""
import argparse
import io
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from analysis.stamp import stamped
from k_comparison import k_proximity
from tep_pricer import Pricer
from precluster_trips import Ctx, prio_st, time_slice


def _work_of(m):
    """Gurobi work units for the optimisation just finished, or 0.0 where unavailable.

    `Work` is deterministic: the same model on the same Gurobi version costs the same work on
    any machine, which wall-clock seconds do not. It is reported per optimisation, not
    cumulatively, so the caller accumulates. Older Gurobi builds do not expose it and return 0.0
    rather than failing -- a run on such a build then writes no clock and is refused at the
    write, which is the correct outcome and not a crash here.
    """
    try:
        return float(m.getAttr("Work"))
    except Exception:
        return 0.0


class Master:
    """ROUNDING DIRECTION IS WHAT MAKES THIS MODEL A BOUND OR A PRIMAL (d414).

    A trip column enters the flow at the bucket of its hub arrival. Rounding that bucket DOWN
    lets a car be ready no later than reality, so the LP is a relaxation and its optimum is a
    valid lower bound -- this is the `primal=False` default and every bound in the ledger.
    Rounding it UP makes the model pessimistic: the bucket's start time is at or after the true
    arrival, the transfer at s_b then ends at s_b + tau at or after the true one, and a trip
    leaving at its bucket start is realisable. Every integer solution of the UP model therefore
    has an exact timetable, and the model is a RESTRICTION: its LP is NOT a bound and must never
    be cited as one. The gap between the two roundings at a given DELTA is the discretisation
    error of the formulation, measurable per cell.
    """

    def __init__(self, inst, delta, threads=1, primal=False, customers=None):
        import gurobipy as gp
        self.gp = gp
        self.inst = inst; nd, D = inst.nodes, inst.D
        self.primal = bool(primal)
        self.D, self.U, self.delta = D, float(inst.tau), float(delta)
        assert abs(self.U / self.delta - round(self.U / self.delta)) < 1e-9, "DELTA must divide tau"
        self.win = int(round(self.U / self.delta))
        # d448: the EASY-REDUCTION mimic needs the master built on a SUBSET of customers.
        # Dropping customers cannot raise the optimum under the triangle inequality, so a
        # bound on the reduced instance is a bound on the full one; the water term is added
        # over the FULL set separately, exactly as the descent leg does.
        self.g, self.d, self.sats = inst.depot, inst.CDC, list(inst.satellites)
        self.C = list(inst.customers) if customers is None else [c for c in inst.customers if c in set(customers)]
        self.H0, self.H1 = float(nd[self.g].earliest), float(nd[self.g].latest)
        self.d0, self.d1 = float(nd[self.d].earliest), float(nd[self.d].latest)
        self.nb = int(math.floor((self.H1 - self.H0) / self.delta)) + 1
        self.pen, self.tc = float(inst.penalty_cars), float(inst.travelcoststreet)
        # Table-1 windows (K's own bounds on h_i)
        self.e = {c: max(float(nd[c].earliest), self.H0 + D[self.g][c]) for c in self.C}
        self.l = {c: min(float(nd[c].latest), self.H1 - D[c][self.g] - float(nd[c].service) - self.U) for c in self.C}
        self.sv = {c: float(nd[c].service) for c in self.C}
        m = self.m = gp.Model("tep_cg"); m.Params.OutputFlag = 0; m.Params.Threads = threads
        self.det_work = 0.0     # cumulative Gurobi work units over every LP solve on this master
        self.cov = {c: m.addConstr(gp.LinExpr() >= 1, name="cov_%d" % c) for c in self.C}
        self.src = m.addConstr(gp.LinExpr() == 0, name="src")
        self.pre = {(p, b): m.addConstr(gp.LinExpr() == 0, name="pre_%d_%d" % (p, b)) for p in self.sats for b in range(self.nb)}
        self.post = {(p, b): m.addConstr(gp.LinExpr() == 0, name="post_%d_%d" % (p, b)) for p in self.sats for b in range(self.nb)}
        self.N = m.addVar(lb=0.0, obj=self.pen, name="N"); m.chgCoeff(self.src, self.N, 1.0)
        self.z = {}
        for p in self.sats:
            lo = self.d0 + D[self.d][p]                                   # (13) lower: u >= a_d + t_dp
            hi = min(self.d1 - self.U - D[p][self.d], self.H1 - self.U - D[p][self.g])   # (13) upper, (12) with j = g
            for b in range(self.nb - 1):
                w = m.addVar(lb=0.0, obj=0.0); m.chgCoeff(self.pre[(p, b)], w, -1.0); m.chgCoeff(self.pre[(p, b + 1)], w, 1.0)
                w = m.addVar(lb=0.0, obj=0.0); m.chgCoeff(self.post[(p, b)], w, -1.0); m.chgCoeff(self.post[(p, b + 1)], w, 1.0)
            for b in range(self.nb):
                sb = self.H0 + b * self.delta
                if sb + D[p][self.g] <= self.H1 + 1e-9:
                    r = m.addVar(lb=0.0, obj=self.tc * D[p][self.g]); m.chgCoeff(self.post[(p, b)], r, -1.0)
                if b + self.win <= self.nb - 1 and sb + self.delta > lo + 1e-9 and sb <= hi + 1e-9:
                    # ub 1: two transfers starting in one bucket would be < DELTA <= U apart, against (26)
                    zz = m.addVar(lb=0.0, ub=1.0, obj=0.0, name="z_%d_%d" % (p, b))
                    m.chgCoeff(self.pre[(p, b)], zz, -1.0); m.chgCoeff(self.post[(p, b + self.win)], zz, 1.0)
                    self.z[(p, b)] = zz
        self.book = {}
        for p in self.sats:
            for b in range(self.nb):
                members = [self.z[(p, b2)] for b2 in range(b, min(self.nb, b + self.win)) if (p, b2) in self.z]
                if len(members) >= 2:
                    self.book[(p, b)] = m.addConstr(gp.quicksum(members) <= 1, name="book_%d_%d" % (p, b))
        self.slack = {c: m.addVar(lb=0.0, obj=1e5, column=gp.Column([1.0], [self.cov[c]])) for c in self.C}
        self.cols = {}; self.col_ba = {}
        m.update()

    def bucket(self, t):
        """Arrival bucket of an absolute time: DOWN for the bound, UP for the primal (see the
        class docstring). Never clamped to the horizon -- a bucket past the last one means the
        variant does not fit and the caller drops it."""
        x = (t - self.H0) / self.delta
        return max(0, int(math.ceil(x - 1e-9)) if self.primal else int(math.floor(x + 1e-9)))

    # ---- trip timing -------------------------------------------------------------------------
    def simulate(self, seq, h_first):
        """Earliest leave time of the last customer when service at the first starts no earlier
        than h_first; None if some window is violated."""
        D, e, l, sv = self.D, self.e, self.l, self.sv
        h = max(h_first, e[seq[0]])
        if h > l[seq[0]] + 1e-9: return None
        for a, c in zip(seq, seq[1:]):
            h = max(h + sv[a] + D[a][c], e[c])
            if h > l[c] + 1e-9: return None
        return h + sv[seq[-1]]

    def variants(self, seq):
        """Every feasible (L, b, p, b_arr) of a trip: depot start once (b=None), satellite starts
        only at the largest bucket reaching each distinct arrival bucket (waiting on post-nodes
        makes the smaller ones redundant)."""
        D, g = self.D, self.g
        out = []
        end = self.simulate(seq, self.H0 + D[g][seq[0]])
        if end is not None:
            for p in self.sats:
                ba = self.bucket(end + D[seq[-1]][p])
                if ba <= self.nb - 1: out.append((g, None, p, ba))
        for L in self.sats:
            seen = {}
            for b in range(self.win, self.nb):
                sb = self.H0 + b * self.delta
                if sb + D[L][seq[0]] > self.l[seq[0]] + 1e-9: break
                end = self.simulate(seq, sb + D[L][seq[0]])
                if end is None: break
                for p in self.sats:
                    ba = self.bucket(end + D[seq[-1]][p])
                    if ba <= self.nb - 1: seen[(p, ba)] = b          # later b overwrites: largest kept
            out.extend((L, b, p, ba) for (p, ba), b in seen.items())
        return out

    def cost(self, seq, L, p):
        D = self.D
        return self.tc * (D[L][seq[0]] + sum(D[a][c] for a, c in zip(seq, seq[1:])) + D[seq[-1]][p])

    def add_column(self, seq, L, b, p, ba):
        key = (tuple(seq), L, b, p)
        if key in self.cols: return False
        gp = self.gp
        coef = {}
        for c in seq: coef[self.cov[c]] = coef.get(self.cov[c], 0.0) + 1.0
        start = self.src if L == self.g else self.post[(L, b)]
        coef[start] = coef.get(start, 0.0) - 1.0
        coef[self.pre[(p, ba)]] = coef.get(self.pre[(p, ba)], 0.0) + 1.0
        cons = list(coef.keys())
        self.cols[key] = self.m.addVar(lb=0.0, obj=self.cost(seq, L, p), column=gp.Column([coef[k] for k in cons], cons))
        self.col_ba[key] = ba
        return True

    def check_rc(self, pi, mu_src, mu_pre, mu_post, n=200):
        """Transcription check: my reduced-cost formula against Gurobi's RC on existing columns
        at the current duals. Returns the largest absolute difference (must be ~0)."""
        worst = 0.0
        for i, (key, var) in enumerate(self.cols.items()):
            if i >= n: break
            seq, L, b, p = key; ba = self.col_ba[key]
            mine = self.cost(list(seq), L, p) - sum(pi[c] for c in seq) + (mu_src if L == self.g else mu_post[(L, b)]) - mu_pre[(p, ba)]
            worst = max(worst, abs(mine - var.RC))
        return worst

    # ---- duals -------------------------------------------------------------------------------
    def solve(self):
        """Optimise the master and charge the deterministic clock. THE ONLY way this model is
        optimised -- every `M.solve()` call site was replaced at once, because a clock that
        misses one site under-reports silently and the artifact still passes the gate."""
        self.m.optimize()
        self.det_work += _work_of(self.m)
        return self.m

    def duals(self):
        pi = {c: self.cov[c].Pi for c in self.C}
        mu_src = self.src.Pi
        mu_pre = {k: v.Pi for k, v in self.pre.items()}
        mu_post = {k: v.Pi for k, v in self.post.items()}
        return pi, mu_src, mu_pre, mu_post

    def pricer_legs(self, mu_src, mu_pre, mu_post):
        """Entry/exit values that underestimate every variant's flow-dual terms, time-aware:
        entry[c] = min over feasible start nodes (depot, or post(L, b) with win <= b <= the last
        bucket from which c is still reachable within its window) of c^s*D[L][c] + mu_start;
        exit_fn(last, t) = min over hubs p of c^s*D[last][p] - max_{b >= ba_min} mu_pre[p, b],
        with ba_min the arrival bucket from the label's earliest completion t (any variant
        completes no earlier, so its arrival bucket is >= ba_min: a valid underestimate);
        exit_[c] = the global per-customer minimum for the completion bound."""
        D, tc, H0, dl = self.D, self.tc, self.H0, self.delta
        nb, win, sats = self.nb, self.win, self.sats
        sufmax = {}
        for p in sats:
            arr = [mu_pre[(p, b)] for b in range(nb)]
            for b in range(nb - 2, -1, -1): arr[b] = max(arr[b], arr[b + 1])
            sufmax[p] = arr
        premin = {}
        for p in sats:
            arr = [float("inf")] * nb
            cur = float("inf")
            for b in range(win, nb):
                cur = min(cur, mu_post[(p, b)]); arr[b] = cur
            premin[p] = arr
        entry = {}
        for c in self.C:
            best = tc * D[self.g][c] + mu_src
            for L in sats:
                bmax = int(math.floor((self.l[c] - D[L][c] - H0) / dl))
                if bmax >= win:
                    best = min(best, tc * D[L][c] + premin[L][min(bmax, nb - 1)])
            entry[c] = best
        exit_ = {c: min(tc * D[c][p] - sufmax[p][0] for p in sats) for c in self.C}

        def exit_fn(last, t):
            best = float("inf")
            for p in sats:
                ba = self.bucket(t + D[last][p])
                if ba <= nb - 1:
                    v = tc * D[last][p] - sufmax[p][ba]
                    if v < best: best = v
            return best
        return entry, exit_, exit_fn

    def start_labels(self, pi, mu_src, mu_post):
        """One initial label per (start node, bucket, first customer), carrying that start's own
        dual, so the pricer's reduced cost is EXACT instead of a minimum over all starts (d437).
        The depot start is a single node at H0; a satellite start at bucket b leaves at s_b."""
        D, tc = self.D, self.tc
        out = {}
        for c in self.C:
            cands = []
            t = max(self.e[c], self.H0 + D[self.g][c])
            if t <= self.l[c] + 1e-9:
                cands.append((tc * D[self.g][c] + mu_src - pi.get(c, 0.0), t + self.sv[c], (self.g, None)))
            for L in self.sats:
                for b in range(self.win, self.nb):
                    sb = self.H0 + b * self.delta
                    if sb + D[L][c] > self.l[c] + 1e-9:
                        break
                    t = max(self.e[c], sb + D[L][c])
                    cands.append((tc * D[L][c] + mu_post[(L, b)] - pi.get(c, 0.0), t + self.sv[c], (L, b)))
            if cands:
                out[c] = cands
        return out

    def variant_from_start(self, seq, tag, pi, mu_src, mu_pre, mu_post):
        """The exact reduced cost and arrival bucket of a column priced from a known start."""
        D = self.D
        L, b = tag
        h_first = self.H0 + D[self.g][seq[0]] if L == self.g else (self.H0 + b * self.delta) + D[L][seq[0]]
        end = self.simulate(seq, h_first)
        if end is None:
            return None
        best = None
        for p in self.sats:
            ba = self.bucket(end + D[seq[-1]][p])
            if ba > self.nb - 1:
                continue
            rc = self.cost(seq, L, p) - sum(pi[c] for c in seq) + (mu_src if L == self.g else mu_post[(L, b)]) - mu_pre[(p, ba)]
            if best is None or rc < best[0]:
                best = (rc, L, b, p, ba)
        return best

    def best_variant(self, seq, pi, mu_src, mu_pre, mu_post):
        base = -sum(pi[c] for c in seq)
        best = None
        for (L, b, p, ba) in self.variants(seq):
            rc = self.cost(seq, L, p) + base + (mu_src if L == self.g else mu_post[(L, b)]) - mu_pre[(p, ba)]
            if best is None or rc < best[0]: best = (rc, L, b, p, ba)
        return best


def default_delta(inst):
    """THE bucket width every driver must use unless it says otherwise.

    Two runs on different DELTA are different models and their values are not comparable: a finer
    grid rounds less and gives a higher (tighter) bound. Comparing a CG run at tau/3 against an
    exhaustive enumeration at tau produced two false refutations on C201 on 2026-09-25, so the
    default lives here and every driver imports it.
    """
    tau = float(inst.tau)
    return tau if tau <= 60 else tau / 3


def master_ip(M, cell, size, threads=2, timelimit=600.0, work=0.0, retime_cap=240.0):
    """PRICE-AND-BRANCH SMOKE (2026-09-24): solve the converged restricted master as an integer
    program over its priced columns (columns and transfer arcs binary, cars integer; waits and
    returns are forced integral by flow conservation), decode the flow into car chains, re-time
    exactly with the street fixed (assemble_precluster.retime, K's model restricted to the fixed
    street) and verify.  Reports the LP-to-IP gap inside the formulation (how tight TEP's
    relaxation is against integer TEP solutions over the same pool) and the verified objective
    of the pure-TEP integer solution.  The IP is exact within the pool, not for the problem."""
    import gurobipy as gp
    from gurobipy import GRB
    from assemble_precluster import decode, retime
    m = M.m
    for v in M.cols.values(): v.VType = GRB.BINARY
    for v in M.z.values(): v.VType = GRB.BINARY
    M.N.VType = GRB.INTEGER
    for row in M.cov.values(): row.Sense = GRB.EQUAL       # partition in the IP (d412: >= 1 let trips share a customer)
    m.Params.Threads = threads; m.Params.TimeLimit = timelimit
    if work: m.Params.WorkLimit = work
    m.Params.MIPGap = 1e-4
    t0 = time.time(); m.optimize(); secs = time.time() - t0
    M.det_work += _work_of(m)          # the IP runs on the SAME master model; charge its clock too
    res = dict(ip_status=int(m.Status), ip_secs=round(secs, 1), ip_threads=threads,
               ip_timelimit=timelimit, ip_work=round(_work_of(m), 6))
    if m.SolCount == 0:
        res["ip_street"] = None; return res
    res["ip_street"] = m.ObjVal; res["ip_bound"] = m.ObjBound; res["ip_gap"] = m.MIPGap; res["ip_cars"] = M.N.X
    res["slack_used"] = sum(v.X for v in M.slack.values())
    used = [(k, M.col_ba[k]) for k, v in M.cols.items() if v.X > 0.5]
    zs = sorted([(p, b) for (p, b), v in M.z.items() if v.X > 0.5])
    # ---- flow decomposition into car chains (FIFO matching at every satellite) ----
    trips = [list(k[0]) for k, ba in used]
    hub = {i: k[3] for i, (k, ba) in enumerate(used)}
    start = {i: (k[1], k[2]) for i, (k, ba) in enumerate(used)}      # (L, b) with b None from the depot
    arr = {i: (k[3], ba) for i, (k, ba) in enumerate(used)}
    chains = []; car_of_trip = {}
    for i in range(len(used)):
        if start[i][0] == M.g:
            chains.append([i]); car_of_trip[i] = len(chains) - 1
    pending = {p: [] for p in M.sats}          # cars waiting at pre(p): (arrival bucket, car)
    avail = {p: [] for p in M.sats}            # cars ready at post(p): (ready bucket, car)
    zl = {p: sorted(b for (q, b) in zs if q == p) for p in M.sats}
    deps = {p: sorted([(start[i][1], i) for i in range(len(used)) if start[i][0] == p]) for p in M.sats}
    # process buckets in time order so arrivals, transfers and departures interleave correctly
    # Same-bucket order (d412 decoder defect): arrivals (1) before departures (2) before transfers
    # (3). A departure at bucket b never depends on a transfer at b (that car is free only at
    # b + win), but a trip shorter than one bucket arrives at its own departure bucket, and its
    # arrival must be on the queue before the transfers of that bucket are matched.
    events = []
    for i in range(len(used)):
        if start[i][0] == M.g: events.append((arr[i][1], 1, "arrive", i))
    for p in M.sats:
        for b in zl[p]: events.append((b, 3, "transfer", p))
        for b, i in deps[p]: events.append((b, 2, "depart", i))
    events.sort(key=lambda e: (e[0], e[1]))
    ok = True; guard = 0; failures = []
    # arrivals of non-depot trips are emitted when the trip departs (its car is then known)
    while events and guard < 100000:
        guard += 1
        b, _, kind, x = events.pop(0)
        if kind == "arrive":
            p, ba = arr[x]; pending[p].append((ba, car_of_trip[x])); pending[p].sort()
        elif kind == "transfer":
            p = x
            cand = [c for c in pending[p] if c[0] <= b]
            if not cand:
                ok = False; failures.append(dict(kind="transfer", sat=p, bucket=b, pending=list(pending[p]))); continue
            c = cand[0]; pending[p].remove(c); avail[p].append((b + M.win, c[1])); avail[p].sort()
        else:
            i = x; p = start[i][0]
            cand = [c for c in avail[p] if c[0] <= b]
            if not cand:
                ok = False; failures.append(dict(kind="depart", trip=i, sat=p, bucket=b, avail=list(avail[p]))); continue
            c = cand[0]; avail[p].remove(c); car = c[1]
            chains[car].append(i); car_of_trip[i] = car
            events.append((arr[i][1], 1, "arrive", i)); events.sort(key=lambda e: (e[0], e[1]))
    res["decode_ok"] = ok; res["decode_failures"] = failures[:20]; res["chains"] = chains; res["decoded_cars"] = len(chains)
    if failures:
        print("  decode: %d unmatched events, first %s" % (len(failures), failures[0]), flush=True)
    res["trips"] = trips; res["hubs"] = [hub[i] for i in range(len(used))]
    if not ok:
        return res
    # ADMISSIBLE ROUTE (2026-09-28). This called `decode` + `assemble_precluster.retime`, and
    # retime solves K'S JOINT MODEL (build_joint_model). d451 recorded that dependency as
    # REPLACED -- "master IP -> our chaining model -> our tour consolidation -> verifier3, with no
    # predecessor model anywhere" -- but the replacement landed only in tep_chain_own_water and
    # never here, so every master_ip result to date passed through the predecessors' formulation,
    # including the banked `masterip` incumbents and the 2026-09-28 cut trials.
    #
    # The bucket-level decode above produced `chains` for diagnostics; the admissible route does
    # its own continuous-time chaining from the trip partition, so `chains` is no longer the input.
    import time as _t
    _t0 = _t.time()
    from tep_chain_own_water import admissible_solution
    out, _info = admissible_solution(M.inst, trips, cap=retime_cap, work=None)
    res["chain_status"] = _info.get("why"); res["chain_secs"] = round(_t.time() - _t0, 1)
    res["chain_cars"] = _info.get("cars"); res["chain_street"] = _info.get("street")
    res["route"] = "admissible: master IP -> our chaining -> our tour consolidation (no K model)"
    if out is None:
        res["verified"] = False; return res
    run_ = V.verify_solution(M.inst, out, cell=cell, size=size, proximity=k_proximity(size), label="tep_master_ip")
    bad = [x for x in run_.findings if x.severity != "TOLERANCE"]
    res["verified"] = (not bad) and (not run_.blocking); res["objVal"] = out["objVal"]; res["nCars"] = out["nCars"]; res["nVessel"] = out["nVessel"]
    res["recomputed"] = run_.objective.get("recomputed"); res["solution"] = out
    return res


def run(cell, delta, iters, seed_cols, ng, per_iter, build_only, label_cap, size=100, check_cap=20000, smooth=0.5, stall=15, max_secs=0.0, check_secs=60.0, ip=None, int_cars=False, primal=False, proximity=None, proof_audit=False, certify=False, farley_on=False, start_states=False, return_master=False, customers=None,
        elem_pass=False, census=False, threads=4, det_budget=0, fast_pricer=False,
        harvest_cb=None, harvest_lb0=0.0, harvest_soft_secs=0.0, harvest_throttle=10.0, harvest_runaway=0.0):
    prox = k_proximity(size) if proximity is None else float(proximity)
    inst = V.load_instance(cell, size, prox); ctx = Ctx(inst)
    M = Master(inst, delta, threads=threads, primal=primal, customers=customers)
    _PC = Pricer
    if fast_pricer:
        from tep_pricer_njit import FastPricer as _PC   # d655: numba pricer, bit-exact drop-in
    pr = _PC(inst, scale=M.tc, table1=True, ng=(ng or None), customers=customers)
    # d427: ng dominance can hide a variant-feasible elementary column behind a cheaper label
    # whose completions the master rejects, so an ng pass finding nothing is NOT a proof of the
    # master's optimality. ng still drives the iterations (it is far cheaper); the PROOF is an
    # elementary pass, and the loop only stops when THAT finds nothing.
    pr_exact = pr if not ng else _PC(inst, scale=M.tc, table1=True, ng=None, customers=customers)
    n0 = 0
    keepset = set(M.C)
    for name in seed_cols:
        trips = prio_st(ctx) if name == "prio" else time_slice(ctx)
        if customers is not None:
            # the composition heuristics run on the FULL instance, so on a reduced master their
            # trips carry customers the master has no rows for. Project each trip onto the kept
            # set and drop the empties; the ORDER within a trip is preserved (d448).
            trips = [t2 for t2 in ([c2 for c2 in t if c2 in keepset] for t in trips) if t2]
        for seq in trips:
            for (L, b, p, ba) in M.variants(list(seq)):
                n0 += M.add_column(list(seq), L, b, p, ba)
    M.m.update()
    print("  master: %d rows, %d vars; %d seed columns from %s; z arcs %d, booking rows %d; buckets %d x DELTA %.0f"
          % (M.m.NumConstrs, M.m.NumVars, n0, ",".join(seed_cols), len(M.z), len(M.book), M.nb, M.delta), flush=True)
    if build_only:
        return dict(cell=cell, delta=delta, build_only=True, rows=M.m.NumConstrs, vars=M.m.NumVars, seed_cols=n0)
    # Heuristic-then-exact pricing: cheap length-capped passes add columns; only the uncapped pass
    # can prove optimality.  A pass that adds nothing escalates; an exact pass that adds columns
    # drops back to the cheap stage.  Candidates are checked at their exact reduced cost in pricer
    # order, at most check_cap of them unless none is negative (then all, for the proof).
    # Dual smoothing (Wentges): price with alpha * center + (1 - alpha) * current duals; the ADD
    # decision and the PROOF always use the true duals (exact reduced cost), so validity is
    # untouched; a mis-price (nothing negative under smoothed duals) re-prices with the true ones.
    def blend(a, b, w):
        return (w * a[0] + (1 - w) * b[0], {k: w * a[1][k] + (1 - w) * b[1][k] for k in b[1]},
                {k: w * a[2][k] + (1 - w) * b[2][k] for k in b[2]}, {k: w * a[3][k] + (1 - w) * b[3][k] for k in b[3]})

    def price_with(duals_p, duals_true, stage_len, pricer=None):
        pricer = pricer or pr
        mu_src_p, pi_p, mu_pre_p, mu_post_p = duals_p
        entry, exit_, exit_fn = M.pricer_legs(mu_src_p, mu_pre_p, mu_post_p)
        inits = M.start_labels(pi_p, mu_src_p, mu_post_p) if start_states else None
        found, nlab, exhausted = pricer.price(pi_p, maxlen=stage_len, keep=10 ** 9, rc_cut=-1e-6, entry=entry, exit=exit_, exit_fn=exit_fn, label_cap=label_cap, inits=inits)
        mu_src_t, pi_t, mu_pre_t, mu_post_t = duals_true
        added = 0; best_rc = 0.0; checked = 0; t_chk = time.time()
        for rc0, cost, seq, tag in found:
            # the pricer's order is by an UNDERESTIMATE, so exact negatives can sit deep in the
            # list; keep checking until per_iter negatives are added, or the check has run for
            # check_secs AND at least check_cap candidates were seen with something added.
            # With nothing added the check runs to the end (that is what a proof needs).
            if added >= per_iter: break
            if added > 0 and checked >= check_cap and time.time() - t_chk > check_secs: break
            # With start-state pricing the column's start is known and its reduced cost is exactly
            # what the pricer computed -- but the SAME customer sequence may price out from a
            # different start, and taking only the pricer's start left negative columns behind on
            # 5 of 27 cells at n10 (arbiter panel, d437). So take the better of the two: the exact
            # start-state variant, and the best variant over all starts. Neither alone is a
            # stopping test; the minimum of both is the one the certificate needs.
            var = M.best_variant(list(seq), pi_t, mu_src_t, mu_pre_t, mu_post_t)
            if start_states and tag:
                vs = M.variant_from_start(list(seq), tag, pi_t, mu_src_t, mu_pre_t, mu_post_t)
                if vs is not None and (var is None or vs[0] < var[0]):
                    var = vs
            checked += 1
            if var and var[0] < -1e-6:
                best_rc = min(best_rc, var[0])
                if added < per_iter: added += M.add_column(list(seq), var[1], var[2], var[3], var[4])
        return found, nlab, exhausted, added, best_rc, checked

    def _lagr(exact_diag=True):
        """The d430/d626 Lagrangian bound z_RMP + |C| * rc_min at the CURRENT master duals (re-
        solving first). VALID iff start_states is on and the no-prune pricer did not exhaust.
        `exact_diag` adds the exact-rc diagnostic loop (the end-of-run certificate wants it; the
        per-iteration harvest leaves it off because it is O(candidates) and the bound needs only
        rc0_min). Side-effect-free on the master except the solve: it finds columns, never adds."""
        M.solve()
        pi, mu_src, mu_pre, mu_post = M.duals()
        entry, exit_, exit_fn = M.pricer_legs(mu_src, mu_pre, mu_post)
        inits = M.start_labels(pi, mu_src, mu_post) if start_states else None
        t1 = time.time()
        found, nlab, exh = pr.price(pi, keep=10 ** 9, rc_cut=1e18, entry=entry, exit=exit_,
                                    exit_fn=exit_fn, label_cap=label_cap, no_prune=True, inits=inits)
        rc0_min = found[0][0] if found else 0.0
        rc_exact_min = 0.0
        if exact_diag:
            for rc0, cost, seq, tag in found:
                var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
                if start_states and tag:
                    vs = M.variant_from_start(list(seq), tag, pi, mu_src, mu_pre, mu_post)
                    if vs is not None and (var is None or vs[0] < var[0]):
                        var = vs
                if var is not None:
                    rc_exact_min = min(rc_exact_min, var[0])
        kappa = len(M.C)
        valid = (not exh) and bool(start_states)
        return dict(z_rmp=M.m.ObjVal, rc0_min=rc0_min, rc_exact_min=rc_exact_min,
                    residual_slack=rc_exact_min - rc0_min, kappa=kappa,
                    bound=M.m.ObjVal + kappa * min(0.0, rc0_min),
                    penalty=kappa * min(0.0, rc0_min), exhausted=exh, valid=valid,
                    conditions=dict(no_prune=True, start_states=bool(start_states),
                                    not_exhausted=(not exh), candidates=len(found), labels=nlab),
                    why_invalid=(None if valid else
                                 ("pricer exhausted its label cap, so the minimum was not found"
                                  if exh else "start-state pricing off: the entry leg only "
                                              "underestimates and d430's slack applies")),
                    secs=round(time.time() - t1, 1))

    hist = []; t0 = time.time(); state = {"center": None, "harvest_lb": harvest_lb0, "harvest_next_t": 0.0}

    def cg_loop(iters, tag=""):
        """Price to proof (or to a cap) over the current master; returns (LP value, proven, status).

        TWO BUDGETS, AND ONLY ONE OF THEM MAY DECIDE THE RESULT. `det_budget` counts pricer
        labels, which are deterministic: the same instance and the same code generate the same
        count on any machine. `max_secs` counts wall seconds, which are this host on this day.

        CLAUDE.md section 2: deterministic tick budgets, not wall-clock, wherever a result must
        reproduce. A run whose TRAJECTORY was chosen by the wall clock is not reproducible --
        a faster machine takes more iterations and returns a different bound. So the wall cap
        is retained only as a safety backstop, and if it is what stopped the run, the result is
        stamped `bound_by = "wall"` and `reproducible = False`, which the caller must surface
        rather than bury.
        """
        stages = [5, 7, None]; stage = 0; proven = False; status = "iters"; flat = 0; last_val = None
        for it in range(iters):
            if det_budget and sum(int(h.get("labels") or 0) for h in hist) > det_budget:
                status = "det_budget"; state["bound_by"] = "det"; break
            if max_secs and time.time() - t0 > max_secs:
                status = "max_secs"; state["bound_by"] = "wall"; break
            M.solve(); val = M.m.ObjVal
            pi, mu_src, mu_pre, mu_post = M.duals()
            duals_true = (mu_src, pi, mu_pre, mu_post)
            if it < 3 and not tag:
                print("  rc transcription check (my formula vs Gurobi RC, 200 columns): max |diff| %.6f" % M.check_rc(pi, mu_src, mu_pre, mu_post), flush=True)
            t1 = time.time()
            center = state["center"]
            smoothed = center is not None and smooth > 0
            duals_p = blend(center, duals_true, smooth) if smoothed else duals_true
            found, nlab, exhausted, added, best_rc, checked = price_with(duals_p, duals_true, stages[stage])
            mis = False
            if added == 0 and smoothed and not exhausted:
                mis = True
                found, nlab, exhausted, added, best_rc, checked = price_with(duals_true, duals_true, stages[stage])
            state["center"] = duals_p if (added > 0 and not mis) else duals_true
            t_price = time.time() - t1
            slack_use = sum(v.X for v in M.slack.values())
            hist.append(dict(it=it, tag=tag, stage=stages[stage], lp=round(val, 2), cols=len(M.cols), cand=len(found), checked=checked, added=added, best_rc=round(best_rc, 2), labels=nlab, exhausted=exhausted, mispriced=mis, slack=round(slack_use, 3), N=round(M.N.X, 3), price_s=round(t_price, 2), secs=round(time.time() - t0, 2), work=round(M.det_work, 6)))
            print("  it %2d%s len %-4s LP %9.2f  N %5.2f  cols %6d  cand %7d  chk %6d  +%4d  best rc %9.2f  labels %8d%s%s  slack %.3f  price %4.0fs  %5.0fs"
                  % (it, tag, stages[stage] or "all", val, M.N.X, len(M.cols), len(found), checked, added, best_rc, nlab, " EXHAUSTED" if exhausted else "", " misprice" if mis else "", slack_use, t_price, time.time() - t0), flush=True)
            # LAGRANGIAN HARVEST (off unless harvest_cb set). The free ceiling z_RMP + |C|*best_rc
            # is an UPPER bound on the valid bound (rc_min <= best_rc, the main loop searches a
            # subset), so when it does not clear the running best LB the no-prune pricing provably
            # cannot improve and is skipped. We pay for _lagr only when the ceiling clears best_lb
            # ("then and if"), throttled to ~1/throttle of wall. bound VALIDITY is independent of
            # the ceiling -- it is _lagr's own (start_states and not exhausted). STOP RULE: soft
            # target at harvest_soft_secs, but defer the stop to the next banked valid LB (or stop
            # at once if the ceiling can no longer clear best_lb); runaway guard is a hard backstop.
            if harvest_cb is not None:
                kappa_h = len(M.C)
                ceiling = val + kappa_h * min(0.0, best_rc)
                rec = dict(it=it, tag=tag, t=round(time.time() - t0, 3), work=round(M.det_work, 6),
                           z_rmp=round(val, 6), best_rc=round(best_rc, 6), ceiling=round(ceiling, 6),
                           best_lb=round(state["harvest_lb"], 6), fired=False)
                banked = False
                if ceiling > state["harvest_lb"] + 1e-6 and (time.time() - t0) >= state["harvest_next_t"]:
                    lg = _lagr(exact_diag=False)
                    rec.update(fired=True, bound=round(lg["bound"], 6), rc0_min=round(lg["rc0_min"], 6),
                               valid=bool(lg["valid"]), exhausted=bool(lg["exhausted"]), lagr_secs=lg["secs"])
                    if lg["valid"] and lg["bound"] > state["harvest_lb"] + 1e-6:
                        state["harvest_lb"] = lg["bound"]; banked = True; rec["banked"] = True
                    state["harvest_next_t"] = (time.time() - t0) + harvest_throttle * max(lg["secs"], 0.1)
                harvest_cb(rec)
                if harvest_soft_secs and (time.time() - t0) > harvest_soft_secs:
                    if harvest_runaway and (time.time() - t0) > harvest_runaway:
                        status = "harvest_runaway"; state["bound_by"] = "wall"; break
                    if banked:
                        status = "harvest_next_lb"; state["bound_by"] = "wall"; break
                    if ceiling <= state["harvest_lb"] + 1e-6:
                        status = "harvest_softcap"; state["bound_by"] = "wall"; break
            if exhausted:
                status = "exhausted"; break
            # LP flat = unchanged to 1e-4 relative; heuristic stages escalate when they add nothing,
            # when their best column could not move the LP (|rc| < 1e-4 |LP|), or when the LP has
            # been flat for 5 iterations (the tailing seen on R204 d10, 19:02: one column per
            # iteration at rc -0.1 with the LP frozen). Only the exact stage can prove or stall.
            flat = flat + 1 if (last_val is not None and abs(val - last_val) < 1e-4 * max(1.0, abs(val))) else 0
            last_val = val
            tol_h = -1e-4 * max(1.0, abs(val))
            if stages[stage] is None:
                if added == 0 and not elem_pass:
                    # THE IN-RUN ELEMENTARY PASS IS DROPPED (d596, author: 'Drop it'). Decided
                    # and documented on 2026-09-29; ed87a90 changed only the ledger and the
                    # trajectory document, so the branch below stayed live until d602 caught it.
                    #
                    # THE EVIDENCE: across ALL 508 ELEM rows in the banked grid it found a
                    # column 0 times, moved the LP 0 times (max |LP(elem) - LP(ng)| = 0.000000)
                    # and refuted an ng certificate 0 times, while costing 8.66 h on the 71
                    # passes that FAIL (max 5,770 s).
                    #
                    # THE CERTIFICATE IS NOW ng, AND THE TEST IS cand == 0, NOT added == 0.
                    # Those differ and the difference is load-bearing: R211 at |C| = 100
                    # recorded added 0 with cand 114,207 -- every column it found was already in
                    # the master -- and the elementary pass then found five at rc -4.46. Read
                    # through `added` alone that run would have been certified and its bound
                    # would have been wrong. ng_certified() applies the same test to the row.
                    state["lp_ng"] = val          # d594: free ordering check on every cell
                    if len(found) == 0:
                        proven = slack_use < 1e-6
                        status = "proven_ng" if proven else "slack"
                    else:
                        proven = False
                        status = "ng_cand_nonzero"
                    break
                if added == 0:
                    # the ng pass is silent: now ask the exact (elementary) pricer (d427)
                    ef, nl_e, exh_e, add_e, rc_e, chk_e = price_with(duals_true, duals_true, None, pricer=pr_exact)
                    hist.append(dict(it=it, tag=" ELEM", stage=None, lp=round(val, 2), cols=len(M.cols), cand=len(ef),
                                     checked=chk_e, added=add_e, best_rc=round(rc_e, 4), labels=nl_e, exhausted=exh_e,
                                     slack=round(slack_use, 3), N=round(M.N.X, 3),
                                     secs=round(time.time() - t0, 2), work=round(M.det_work, 6)))
                    print("  it %2d ELEM len all  LP %9.2f  cand %7d  chk %6d  +%4d  best rc %9.4f  labels %8d%s  %5.0fs"
                          % (it, val, len(ef), chk_e, add_e, rc_e, nl_e, " EXHAUSTED" if exh_e else "", time.time() - t0), flush=True)
                    if exh_e:
                        status = "elem_exhausted"; break        # no proof: the exact pass could not finish
                    if add_e == 0:
                        proven = slack_use < 1e-6; status = "proven" if proven else "slack"
                        break
                    stage = 0; flat = 0; state["center"] = duals_true
                    continue
                if stall and flat >= stall:
                    status = "stalled"; break
                stage = 0; flat = 0
            elif added == 0 or best_rc > tol_h or flat >= 5:
                stage += 1; flat = 0
        M.solve()
        return M.m.ObjVal, proven, status

    val, proven, status = cg_loop(iters)
    # INTEGER-CAR CUTS (2026-09-24, author: 'smoke it'): the proven LP's car count N_LP is a lower
    # bound on the cars of every feasible solution, and cars are integer, so N >= ceil(N_LP) is
    # valid. Add it, re-price to proof (the cut changes the duals, new columns may price out),
    # repeat while the proven N_LP keeps crossing an integer. Each accepted bound is proven.
    cuts = []
    if int_cars and proven:
        lp0 = val
        while True:
            n = M.N.X; c = int(math.ceil(n - 1e-6))
            if c - n < 1e-6 or (cuts and c <= cuts[-1]["cut"]):
                break
            M.m.addConstr(M.N >= c, name="intcars_%d" % c)
            print("  integer-car cut: N >= %d (proven LP N %.3f, LP %.2f) -> re-pricing to proof" % (c, n, val), flush=True)
            cuts.append(dict(cut=c, lp_before=val, N_before=n))
            val, proven, status = cg_loop(iters, tag=" c%d" % c)
            cuts[-1].update(lp_after=val, N_after=M.N.X, proven=proven, status=status)
            if not proven:
                break
        if cuts:
            print("  integer-car cuts: LP %.2f -> %.2f (%+.2f%%), N %.3f -> %.3f, last cut N >= %d, proven %s"
                  % (lp0, val, 100.0 * (val / lp0 - 1), cuts[0]["N_before"], M.N.X, cuts[-1]["cut"], proven), flush=True)
    # END-OF-RUN HARVEST (off unless harvest_cb set): one forced valid harvest at the final master
    # state, BYPASSING the throttle, so the converged/best bound is always banked even when the
    # throttle suppressed the last in-loop fire. A hard-killed run never reaches here -- but it also
    # never converged, and its best valid point was already banked in-loop before the kill.
    if harvest_cb is not None:
        _lg = _lagr(exact_diag=False)
        _ceil = _lg["z_rmp"] + len(M.C) * min(0.0, _lg["rc0_min"])
        _rec = dict(it=-1, tag="final", t=round(time.time() - t0, 3), work=round(M.det_work, 6),
                    z_rmp=round(_lg["z_rmp"], 6), best_rc=None, ceiling=round(_ceil, 6),
                    best_lb=round(state["harvest_lb"], 6), fired=True, bound=round(_lg["bound"], 6),
                    rc0_min=round(_lg["rc0_min"], 6), valid=bool(_lg["valid"]),
                    exhausted=bool(_lg["exhausted"]), lagr_secs=_lg["secs"])
        if _lg["valid"] and _lg["bound"] > state["harvest_lb"] + 1e-6:
            state["harvest_lb"] = _lg["bound"]; _rec["banked"] = True
        harvest_cb(_rec)
    # PROOF AUDIT (d427): the whole bound rests on "the pricer found nothing, therefore nothing
    # exists". R211 contradicts that (a cut LOWERED a proven optimum), so this re-prices at the
    # converged duals with the completion-bound prune OFF and, optionally, elementary labeling,
    # and reports the most negative EXACT reduced cost any variant reaches. Anything below -1e-6
    # means the proof was false and names the mechanism.
    # FARLEY BOUND (d433, corrected in d436): scale ONLY THE COVERING DUALS by lambda. The first
    # version scaled every dual and returned lambda = 0 on both cells tried, because the master
    # holds ZERO-COST variables -- the wait arcs -- whose dual feasibility needs the scaled dual
    # term to be <= 0, so any numerically positive term forces lambda to zero. Scaling only the
    # covering duals avoids that entirely: the wait, return, transfer and car variables have no
    # entry in a covering row, so their reduced costs are untouched and stay feasible, while a
    # trip column's reduced cost RISES as lambda falls (pi >= 0 on a >= row), so every column
    # already in the master stays feasible too and only the unseen universe needs checking.
    # Bound (weak duality) = lambda * sum(covering duals) + sum(booking duals).
    farley = None
    if farley_on:
        M.solve(); z_rmp = M.m.ObjVal
        pi, mu_src, mu_pre, mu_post = M.duals()
        pi_sum = sum(pi.values())
        book_sum = sum(c.Pi for c in M.book.values())

        def bound_at(lam):
            return lam * pi_sum + book_sum

        def universe_ok(lam):
            e, x_, xf = M.pricer_legs(mu_src, mu_pre, mu_post)          # flow duals UNSCALED
            f, nl, exh = pr.price({c: lam * pi[c] for c in pi}, keep=1, rc_cut=-1e-9,
                                  entry=e, exit=x_, exit_fn=xf, label_cap=label_cap)
            return (not f), (f[0][0] if f else 0.0), exh

        lo, hi, passes = 0.0, 1.0, 1
        ok_hi, rc_hi, exh = universe_ok(hi)
        if ok_hi:
            lam = hi
        else:
            for _ in range(7):
                mid = 0.5 * (lo + hi)
                ok, _rc, _e = universe_ok(mid); passes += 1
                if ok: lo = mid
                else: hi = mid
            lam = lo
        farley = dict(z_rmp=z_rmp, pi_sum=pi_sum, book_sum=book_sum, lam=lam, bound=bound_at(lam),
                      rc_at_one=rc_hi, pricing_passes=passes, exhausted=bool(exh), scaled="covering duals only")
        print("  Farley (covering duals only): z_RMP %.2f = pi_sum %.2f + booking %.2f | rc at lambda=1 %.3f | lambda %.4f -> VALID bound %.2f (%.1f%% of z_RMP), %d passes"
              % (z_rmp, pi_sum, book_sum, rc_hi, lam, farley["bound"], 100.0 * farley["bound"] / z_rmp if z_rmp else 0.0, passes), flush=True)

    # LAGRANGIAN CERTIFICATE (d430): a bound that needs no convergence claim. For duals pi the
    # weak-duality bound is z_RMP + kappa * rc_min, where kappa bounds the number of TRIP columns
    # in any solution (each trip serves at least one customer, so kappa = |C|) and rc_min is the
    # least reduced cost in the universe. We need only an UNDERESTIMATE of rc_min, and the ng
    # pricer supplies one whatever its dominance hides: dominance preserves the minimum of its own
    # universe, and the entry/exit terms underestimate every variant, so min(found.rc) <= rc_min.
    # Valid whether or not the run converged; its tightness is kappa * |rc0_min|.
    lagr = None
    if certify:
        lagr = _lagr(exact_diag=True)
        print("  Lagrangian certificate: z_RMP %.2f, pricer rc_min %.4f (exact best %.4f, residual "
              "slack %.4f), kappa %d -> bound %.2f (%.1f%% below the RMP value)  %s"
              % (lagr["z_rmp"], lagr["rc0_min"], lagr["rc_exact_min"], lagr["residual_slack"],
                 lagr["kappa"], lagr["bound"],
                 100.0 * (1 - lagr["bound"] / lagr["z_rmp"]) if lagr["z_rmp"] else 0.0,
                 "VALID" if lagr["valid"] else "NOT VALID: " + lagr["why_invalid"]), flush=True)
    audit = None
    if proof_audit:
        M.solve()
        pi, mu_src, mu_pre, mu_post = M.duals()
        entry, exit_, exit_fn = M.pricer_legs(mu_src, mu_pre, mu_post)
        audit = {}
        # d449: the audit built its pricers WITHOUT the customer subset, so on a reduced master
        # it priced over customers the master has no rows for and died on the first lookup. This
        # is the FOURTH place the full customer set leaked into a reduced run; the others were the
        # seed columns, the elementary proving pricer, and the arbiter's exact LP.
        for tag, pricer in (("ng_noprune", Pricer(inst, scale=M.tc, table1=True, ng=(ng or None), customers=customers)),
                            ("elementary_noprune", Pricer(inst, scale=M.tc, table1=True, ng=None, customers=customers))):
            t1 = time.time()
            found, nlab, exh = pricer.price(pi, keep=10 ** 9, rc_cut=-1e-6, entry=entry, exit=exit_,
                                            exit_fn=exit_fn, label_cap=label_cap, no_prune=True)
            worst = 0.0; worst_seq = None; neg = 0
            for rc0, cost, seq, tag in found:
                var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
                if var and var[0] < -1e-6:
                    neg += 1
                    if var[0] < worst:
                        worst, worst_seq = var[0], list(seq)
            # DSSR premise (d431): how many DISTINCT customers actually repeat in the priced
            # paths? That set is what decremental state space relaxation would have to force
            # elementary, and its size decides whether the build converges in a few rounds.
            rep_cust, rep_paths = set(), 0
            for rc0, cost, seq, tag in found:
                if len(set(seq)) < len(seq):
                    rep_paths += 1
                    seen = set()
                    for c in seq:
                        if c in seen:
                            rep_cust.add(c)
                        seen.add(c)
            audit[tag] = dict(candidates=len(found), labels=nlab, exhausted=exh, negatives=neg,
                              worst_rc=worst, worst_seq=worst_seq, secs=round(time.time() - t1, 1),
                              paths_with_repeats=rep_paths, distinct_repeating_customers=len(rep_cust),
                              repeating_customers=sorted(rep_cust)[:40], n_customers=len(M.C))
            top = found[:50]
            top_cust, top_paths = set(), 0
            for rc0, cost, seq, tag in top:
                if len(set(seq)) < len(seq):
                    top_paths += 1
                    seen = set()
                    for c in seq:
                        if c in seen: top_cust.add(c)
                        seen.add(c)
            audit[tag]["top50_paths_with_repeats"] = top_paths
            audit[tag]["top50_distinct_repeating"] = len(top_cust)
            print("    [%s] non-elementary paths %d of %d; distinct customers that repeat: %d of %d | TOP 50 by reduced cost: %d non-elementary, %d distinct repeating (this is the set DSSR would force)"
                  % (tag, rep_paths, len(found), len(rep_cust), len(M.C), top_paths, len(top_cust)), flush=True)
            print("  proof audit [%s]: %d candidates, %d with EXACT rc < -1e-6, worst %.4f%s (%.0f s%s)"
                  % (tag, len(found), neg, worst, (" seq %s" % worst_seq) if worst_seq else "", audit[tag]["secs"],
                     ", LABEL CAP HIT" if exh else ""), flush=True)
        audit["duals_sample"] = dict(pi_min=min(pi.values()), pi_max=max(pi.values()),
                                     mu_src=mu_src, mu_pre_max=max(mu_pre.values()), mu_post_max=max(mu_post.values()))
    # ---- d437 column census -------------------------------------------------------------
    # variants() keeps only the LARGEST satellite bucket per arrival bucket, on the argument that
    # post-nodes carry free wait arcs so the smaller ones are redundant.  start_labels() makes no
    # such cut.  If start-state pricing adds columns variants() would never offer, the two runs
    # are solving DIFFERENT LPs and their values are not comparable.  If it adds none, they are
    # the same LP and one of the two convergence certificates is false.
    # d502 (2026-09-26): the census and the split are a diagnostic of CONVERGENCE certificates and have no wall of
    # their own; on an unproven stop they recompute variants() per column twice and re-solve the master twice.
    # C204 n20 d5 hit its 900 s wall at 906 s and then ran 20 more minutes here over 93,331 columns. Skip when unproven.
    if start_states and proven and census:
        out_u = 0; in_u = 0; ex = []
        for key in list(M.cols.keys()):
            seq, L, bb, pp = key
            legal = set(M.variants(list(seq)))
            tup = (L, bb, pp, M.col_ba[key])
            if tup in legal:
                in_u += 1
            else:
                out_u += 1
                if len(ex) < 5:
                    same = sorted(w for w in legal if w[0] == L and w[2] == pp)
                    ex.append((list(seq), L, bb, pp, M.col_ba[key], same[:3]))
        print("  d437 column census: %d of %d priced columns lie OUTSIDE variants(); %d inside"
              % (out_u, out_u + in_u, in_u), flush=True)
        for e in ex:
            print("     outside: seq %s start (%s,%s) hub %s ba %s | variants same (L,hub): %s" % tuple(e), flush=True)
        # Split the difference against the old enumerator: forbid every outside column and
        # re-solve.  If the value is unchanged, the outside columns are redundant (as the
        # post-layer wait arcs predict) and the whole drop comes from columns INSIDE the old
        # universe that the old pricer never found -- which is d427, with a measured size.
        if out_u:
            keep = []
            for key in list(M.cols.keys()):
                seq, L, bb, pp = key
                if (L, bb, pp, M.col_ba[key]) not in set(M.variants(list(seq))):
                    v = M.cols[key]; keep.append((v, v.UB)); v.UB = 0.0
            M.solve()
            val_inside = M.m.ObjVal if M.m.Status == 2 else None
            for v, ub in keep:
                v.UB = ub
            M.solve()
            r_inside = val_inside
            print("  d437 split: LP over INSIDE-only columns %s ; LP over all %s ; back to %s"
                  % (("%.4f" % r_inside) if r_inside is not None else "infeasible",
                     "%.4f" % val, "%.4f" % M.m.ObjVal), flush=True)

    r = dict(cell=cell, size=size, proximity=prox, delta=delta, ng=ng, start_states=bool(start_states), lp_street=val, primal_rounding=bool(primal), valid_bound=(bool(proven) and not primal and bool(start_states)), N=M.N.X, cols=len(M.cols), iters=len(hist), proven=proven, status=status, secs=round(time.time() - t0), hist=hist, int_car_cuts=cuts, proof_audit=audit, lagrangian=lagr, farley=farley)
    # THE DETERMINISTIC CLOCK (CLAUDE.md section 1, adopted 2026-09-29). Two costs in two units,
    # recorded side by side and never summed: Gurobi work units on the master LP, and labels
    # generated by the pricer, which is pure Python and where most of the wall time goes. Both
    # reproduce on any machine; `secs` does not. Without this the artifact is refused at the
    # write, which is the whole point.
    # d594: the LP at ng convergence, beside the final LP. Free, and it makes every cell a
    # test of LP(ng) <= LP(elementary) wherever both are ever recorded on the same model.
    r["lp_at_ng_convergence"] = state.get("lp_ng")
    r["elem_pass"] = bool(elem_pass)
    # RT COMPARABILITY (author, 2026-09-29): every published result runs SOLO with 4 cores
    # available and the other 4 free. Recorded per artifact because a runtime claim that
    # cannot name its execution conditions is not comparable with K's 4 Xeon Gold 5218.
    # NOTE what 4 threads actually buys: the LP is 0.25 to 2.69 per cent of the wall on the
    # four smoke cells (gurobi_work 3.9 to 39.7 units against 1,026 to 1,565 s). The pricer
    # is pure single-threaded Python and is the other 97 to 99.75 per cent, so real
    # utilisation is about one core. Our runtime is therefore CONSERVATIVE against theirs.
    r["threads"] = int(threads)
    # EVERY PARAMETER THAT DETERMINED THIS VALUE, including the ones left at a default and the
    # ones a caller passed positionally. An audit on 2026-09-29 found ~20 unrecorded, of which
    # `smooth` is the sharpest: it changes the pricing trajectory AND bound_certificate.ng_certified
    # branches on it via (d or {}).get("smooth", 0.5) -- so the certificate rule was being decided
    # against an assumed value rather than a recorded one.
    r["params"] = dict(iters_cap=int(iters), seed_cols=list(seed_cols), per_iter=int(per_iter),
                       label_cap=int(label_cap), check_cap=int(check_cap), smooth=float(smooth),
                       stall=int(stall), check_secs=float(check_secs), max_secs=float(max_secs),
                       det_budget=int(det_budget), build_only=bool(build_only),
                       int_cars=bool(int_cars), primal=bool(primal), proof_audit=bool(proof_audit),
                       certify=bool(certify), farley_on=bool(farley_on), census=bool(census),
                       customers=(None if customers is None else len(customers)))
    r["smooth"] = float(smooth)            # ng_certified reads this; it must not be a default
    # WHICH CLOCK STOPPED THE RUN. A wall-bound run did not reproduce and must say so.
    r["bound_by"] = state.get("bound_by", "converged")
    r["reproducible"] = (state.get("bound_by") != "wall")
    # CERTIFICATE EVIDENCE, so the verdict can be RE-CHECKED rather than trusted.
    # bound_certificate.py's own contract: "A bound may be cited only if the artifact itself
    # shows how it was proven." It reads these fields off the last non-ELEM hist row.
    _ng = [h for h in hist if not str(h.get("tag", "")).strip().upper().startswith("ELEM")]
    if _ng:
        _l = _ng[-1]
        r["cert_evidence"] = dict(stage=_l.get("stage"), exhausted=bool(_l.get("exhausted")),
                                  cand=_l.get("cand"), added=_l.get("added"),
                                  mispriced=bool(_l.get("mispriced")), slack=_l.get("slack"),
                                  best_rc=_l.get("best_rc"), it=_l.get("it"), proven=bool(proven))
    r["det_ticks"] = dict(gurobi_work=round(M.det_work, 6),
                          pricer_labels=int(sum(int(h.get("labels") or 0) for h in hist)),
                          cg_iters=len(hist))
    if return_master:
        r["master"] = M
    if ip:
        print("  master IP over %d columns (threads %d, cap %.0f s) ..." % (len(M.cols), ip["threads"], ip["timelimit"]), flush=True)
        r["ip"] = master_ip(M, cell, size, threads=ip["threads"], timelimit=ip["timelimit"], work=ip.get("work", 0.0))
        # the IP is solved over the SAME master, so it inherits any integer-car cuts added
        # above (valid for every feasible solution, so they prune the IP as well)
        r["ip"]["cuts_in_master"] = [c["cut"] for c in cuts]
        q = r["ip"]
        if q.get("ip_street") is not None:
            print("  IP street %.1f vs LP %.1f -> integrality gap within the pool %.1f%% | cars %.0f (decoded %s, ok %s) | re-time %s -> %s"
                  % (q["ip_street"], val, 100.0 * (q["ip_street"] / val - 1), q["ip_cars"], q.get("decoded_cars"), q.get("decode_ok"), q.get("retime_status"),
                     ("obj %.1f cars %d vessels %d verifier3 %s" % (q["objVal"], q["nCars"], q["nVessel"], "PASS" if q.get("verified") else "FAIL")) if q.get("objVal") else "no solution"), flush=True)
        else:
            print("  IP: no solution within the cap", flush=True)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--delta", type=float, default=None); ap.add_argument("--iters", type=int, default=80)
    ap.add_argument("--seed-cols", default="prio,ts"); ap.add_argument("--ng", type=int, default=10); ap.add_argument("--per-iter", type=int, default=1000)
    ap.add_argument("--label-cap", type=int, default=3_000_000); ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--size", type=int, default=100); ap.add_argument("--check-cap", type=int, default=20000); ap.add_argument("--smooth", type=float, default=0.5)
    ap.add_argument("--stall", type=int, default=15, help="stop unproven if the LP value is unchanged this many iterations while columns are still added")
    ap.add_argument("--max-secs", type=float, default=0.0, help="stop unproven after this wall time (0 = none)")
    ap.add_argument("--ip", action="store_true", help="price-and-branch smoke: solve the converged master as an IP, decode, re-time, verify")
    ap.add_argument("--ip-threads", type=int, default=2); ap.add_argument("--ip-time", type=float, default=600.0); ap.add_argument("--ip-work", type=float, default=0.0)
    ap.add_argument("--int-cars", action="store_true", help="after the proof, add N >= ceil(N_LP) and re-prove, repeatedly (valid cuts)")
    # START-STATE PRICING IS NOW THE DEFAULT, and `valid_bound` requires it (2026-09-29).
    #
    # d436 measured the alternative against ground truth -- tep_exact_small.py, which uses no
    # pricer and enumerates every feasible elementary trip: the original pricer is REFUTED ON
    # 14 OF 27 CELLS at |C| = 10, over-stating by up to 1.141 per cent (RC205 287.6350 against
    # 284.3912) WHILE PRINTING PROVEN True. Start-state pricing was refuted on 0 of 27.
    #
    # It was nonetheless an opt-in flag whose default was the refuted configuration, and on
    # 2026-09-29 that trap fired twice in one hour: a CLI run of C201 n10 and the first draft of
    # analysis/lb_solver.py both used the default and both printed PROVEN. The solver's second
    # smoke cell returned C202 n20 at 621.305 against a banked 619.740 -- same delta, same ng,
    # same certificate class -- which is not a gain but an invalid bound, caught only because
    # two sound certificates over the same column space must agree.
    #
    # A default that is known to be refuted is a trap, not a default. `--no-start-states` keeps
    # the old behaviour for deliberate comparisons; it now writes valid_bound False.
    ap.add_argument("--start-states", dest="start_states", action="store_true", default=True,
                    help="price from real (start node, bucket) labels so the reduced cost is exact (d436). ON by default.")
    ap.add_argument("--census", action="store_true",
                    help="post-proof d437 column census and LP split. A DIAGNOSTIC: it recomputes "
                         "variants() for every column twice and re-solves the whole LP twice, with no "
                         "wall of its own (d498: 20 minutes past a fired 900 s wall). Off by default.")
    ap.add_argument("--elem-pass", action="store_true",
                    help="run the in-run elementary proving pass. DROPPED from production by d596 "
                         "(0 of 508 rows ever fired, 8.66 h wasted on the 71 that failed); kept for "
                         "the out-of-RT arbiter, which must re-price with the completion-bound prune OFF.")
    ap.add_argument("--no-start-states", dest="start_states", action="store_false",
                    help="the pre-d436 pricer, REFUTED on 14 of 27 cells. Writes valid_bound False.")
    ap.add_argument("--farley", action="store_true", help="scale the duals until nothing prices out; lambda * z_RMP is a valid bound with no convergence claim (d433)")
    ap.add_argument("--certify", action="store_true", help="report the Lagrangian bound z_RMP + |C| * rc_min, valid with or without convergence (d430)")
    ap.add_argument("--proof-audit", action="store_true", help="after the proof, re-price unpruned (ng and elementary) at the converged duals and report the worst exact reduced cost")
    ap.add_argument("--primal-round", action="store_true", help="ceil the arrival buckets: a RESTRICTION whose integer solutions are timeable; its LP is NOT a bound (d414)")
    ap.add_argument("--proximity", type=float, default=None, help="omit for K's proximity for the size (0.0 up to n50, 0.1 at n100)")
    ap.add_argument("--force-intcars-n100", action="store_true", help="run --int-cars at n100 anyway; it cannot fire until G4 is fixed")
    a = ap.parse_args()
    if a.int_cars and a.size == 100 and not a.force_intcars_n100:
        # G4 (2026-09-27). The cut is gated on `int_cars and proven`, and `proven` is the ELEMENTARY
        # certificate, which no |C| = 100 cell has ever obtained: the elementary pass exhausts its
        # label cap on all 27. So an n100 --int-cars run re-derives the ng bound it already had and
        # fires nothing -- measured at 640 to 2483 seconds a cell before this refusal existed. It is
        # refused rather than merely skipped upstream so that a queue built elsewhere cannot spend a
        # night on it. Lift the refusal by fixing the gate to accept an ng-converged LP, which is
        # valid for the same reason the elementary one is: the ng master is a relaxation, so its car
        # count bounds the integer optimum's from below.
        sys.exit("refused (G4): --int-cars at --size 100 cannot fire, because the cut is conditioned on the "
                 "elementary certificate and no n100 cell has one. Use --force-intcars-n100 to run it anyway.")
    if a.int_cars and a.primal_round:
        sys.exit("refused (d420): --int-cars adds N >= ceil(N_LP), valid only because the LP is a "
                 "RELAXATION whose car count bounds every feasible solution from below. Under "
                 "--primal-round the model is a restriction: its LP value is not a bound, N_LP "
                 "bounds nothing, and the cut could exclude the restriction own optimum.")
    inst = V.load_instance(a.cell, a.size, k_proximity(a.size) if a.proximity is None else a.proximity)
    dd = default_delta(inst)
    delta = a.delta or dd
    out_name = "tep_cg_bound_%s%s%s.json" % (a.cell, "" if a.size == 100 else "_n%d" % a.size, "" if abs(delta - dd) < 1e-9 else "_d%d" % int(round(delta)))
    if a.ip:
        out_name = out_name.replace(".json", "_ip.json")
    if a.int_cars:
        out_name = out_name.replace(".json", "_intcars.json")
    if a.primal_round:
        out_name = out_name.replace(".json", "_primal.json")
    if a.proximity is not None and abs(a.proximity - k_proximity(a.size)) > 1e-9:
        out_name = out_name.replace(".json", "_p%s.json" % ("%g" % a.proximity).replace(".", ""))
    print("TEP CG bound -- %s n%d, DELTA %.0f (tau %.0f), ng %s, seed columns %s -> runs/oracle/%s" % (a.cell, a.size, delta, inst.tau, a.ng or "elementary", a.seed_cols, out_name), flush=True)
    r = run(a.cell, delta, a.iters, a.seed_cols.split(","), a.ng, a.per_iter, a.build_only, a.label_cap, size=a.size, check_cap=a.check_cap, smooth=a.smooth, stall=a.stall, max_secs=a.max_secs,
            ip=(dict(threads=a.ip_threads, timelimit=a.ip_time, work=a.ip_work) if a.ip else None), int_cars=a.int_cars, primal=a.primal_round, proximity=a.proximity, proof_audit=a.proof_audit, certify=a.certify, farley_on=a.farley, start_states=a.start_states, elem_pass=a.elem_pass, census=a.census)
    if a.build_only:
        print("  build-only: OK"); return
    ab = {(q["cell"], q["size"]): q for q in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}[(a.cell, a.size)]
    ab_street = float(ab["fleet_term"]) + float(ab["travel_term"])
    print("\n  LP street part %.1f (N %.2f cars, %d columns, %d iterations, %.0fs)  PROVEN %s" % (r["lp_street"], r["N"], r["cols"], r["iters"], r["secs"], r["proven"]))
    print("  AB4 street part (fleet_term + travel_term) %.1f -> street bound x%.3f; AB4 total %.1f with water %.1f -> composed %.1f"
          % (ab_street, r["lp_street"] / ab_street, float(ab["ab4"]), float(ab["water"]), r["lp_street"] + float(ab["water"])))
    print("  VALID only if PROVEN True (exact pricer converged, no covering slack)." if not a.primal_round else
          "  PRIMAL ROUNDING (ceil): this model is a RESTRICTION -- the LP value is NOT a lower bound and must never be cited as one (d414).")
    r["ab_street"] = ab_street; r["ab4"] = float(ab["ab4"]); r["water_ab"] = float(ab["water"])
    # `composed` keeps its meaning -- LP street + AB water -- but the REPORTED bound is the
    # max of that and AB4's own total, per SKELETON's portfolio rule. AB4 wins on 7 of 135
    # certified cells, all |C| = 10, by up to +69.8. Both fields are recorded so a reader can
    # see which carried the cell.
    r["composed"] = r["lp_street"] + float(ab["water"])
    r["lb_reported"] = max(r["composed"], r["ab4"])
    r["lb_carrier"] = "composed" if r["composed"] >= r["ab4"] else "ab4"
    r["_command"] = " ".join(sys.argv); r["_finished"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(stamped(r, "analysis/tep_cg_bound.py", "analysis/tep_pricer.py", "analysis/precluster_trips.py",
                      det=r.get("det_ticks"), wall=r.get("secs")),
              io.open(os.path.join(ROOT, "runs", "oracle", out_name), "w", encoding="utf-8"), indent=1, default=str)


if __name__ == "__main__":
    main()
