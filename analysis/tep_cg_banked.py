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

    python analysis/tep_cg_banked.py R204 [--delta 20] [--ng 10 | --ng 0] [--iters 80]
Gurobi LP at 1 thread (the only solver use); pricing is pure Python.  --ng 0 = elementary.

=============================================================================================
THE BANKED SOLVER, PLUS PROVENANCE AND AN RT TRAJECTORY, AND ONE CORRECTED INSTANCE INPUT.
IT IS NO LONGER AN EXACT REPRODUCTION BELOW |C| = 100, AND THE REASON IS BELOW.
=============================================================================================
Body recovered verbatim from `git show 15f739c:analysis/tep_cg_bound.py` -- the state that
produced the banked corpus (C204 n100 finished 2026-09-23 22:42; the commit is the next
morning, the code having been uncommitted when it ran). `analysis/tep_pricer_banked.py` is
pinned from the same commit, because `analysis/tep_pricer.py` has moved 42 lines since --
`customers`, `no_prune`, `inits`, and a label tuple grown from four elements to five -- and an
exact reproduction cannot rest on the assumption that those are inert at their defaults.

NOT ONE LINE OF THE SOLVING ALGORITHM IS CHANGED. No AB4 floor, no width ladder, no cost gate,
no start-state pricing, no dropped elementary pass, no ceil rounding, no customer subset. Those
all postdate the banked corpus.

BUT THE INSTANCE IS NOT THE ONE THE BANKED CODE BUILT, BELOW |C| = 100. The banked solver
hardcoded satellite proximity 0.1 at BOTH call sites, for every size. K's canonical extraction
(analysis/kref.py, text_facts.proximity) gives table3 0.0 for |C| in {10,20,30}, table4 0.0 for
|C| = 50, table6 0.1 for |C| = 100 -- so 0.1 is correct at n100 ALONE and builds a different
problem instance everywhere else. Measured on C201 n10: proximity 0.0 gives 685 rows, 1100
vars, 58 buckets, 193 seed columns; 0.1 gives 677, 1096, 57, 197.

This file now calls k_proximity(size). At |C| = 100 it therefore still reproduces the banked run
exactly -- verified iteration by iteration on C204 n100, identical LP, cand, checked, added and
labels on all 36 rows. Below |C| = 100 it deliberately does NOT: it solves K's instance instead
of the one the banked code solved. Reproducing a defect that solves the wrong problem is not
useful, and an artifact built at the wrong proximity is not comparable with K's table for that
size. A --proximity override is provided for deliberate like-for-like comparison with a banked
artifact.

The other additions are the two things asked for:

  PROVENANCE.  The original wrote `json.dump(r, ...)` with no stamp at all: no source hashes,
               no code hash, no git sha, no machine, no solver versions. It now goes through
               `analysis.stamp.stamped`, which also refuses to write when a value-determining
               source is uncommitted. Every parameter of the run is recorded in `params`,
               including the ones left at their defaults.

  RT TRAJECTORY.  `events` carries one row per CG iteration with the wall second, the CUMULATIVE
               Gurobi work units and the CUMULATIVE pricer labels -- both monotone by
               construction -- plus the LP as it stood. `improvements` records every rise in the
               LP with its timestamp on all three clocks and the operator that produced it
               (width, pricing stage, iteration). `gates` records every stop decision with its
               inputs and its GO/NO-GO, whether or not it fired.

WHAT THIS REPRODUCES IS NOT A DEFENSIBLE BOUND, AND THE ARTIFACT SAYS SO. This code predates
d436, which measured the pricer it uses against ground truth -- `tep_exact_small`, no pricer,
full enumeration -- and found it REFUTED ON 14 OF 27 CELLS at |C| = 10, over-stating by up to
1.141 per cent WHILE PRINTING PROVEN True. There is no `start_states` switch in this file at
all; the flag did not exist yet. So `valid_bound` is written False on every run and the reason
is recorded. The purpose here is to see what the banked numbers cost and how they moved, not to
produce a bound that can be cited.
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
from tep_pricer_banked import Pricer      # PINNED at 15f739c; see the header
from precluster_trips import Ctx, prio_st, time_slice
from k_comparison import k_proximity
from analysis.stamp import stamped

SOURCES = ("analysis/tep_cg_banked.py", "analysis/tep_pricer_banked.py",
           "analysis/precluster_trips.py", "analysis/verifier3.py", "analysis/stamp.py")


def _work_of(m):
    """Gurobi work units for the optimisation just finished, or 0.0 where unavailable.
    Deterministic: the same model on the same Gurobi version costs the same work on any machine,
    which wall seconds do not. Reported per optimisation, so the caller accumulates."""
    try:
        return float(m.getAttr("Work"))
    except Exception:
        return 0.0


class Master:
    def __init__(self, inst, delta, threads=1):
        self.det_work = 0.0      # cumulative Gurobi work units; recording only
        import gurobipy as gp
        self.gp = gp
        self.inst = inst; nd, D = inst.nodes, inst.D
        self.D, self.U, self.delta = D, float(inst.tau), float(delta)
        assert abs(self.U / self.delta - round(self.U / self.delta)) < 1e-9, "DELTA must divide tau"
        self.win = int(round(self.U / self.delta))
        self.g, self.d, self.sats, self.C = inst.depot, inst.CDC, list(inst.satellites), list(inst.customers)
        self.H0, self.H1 = float(nd[self.g].earliest), float(nd[self.g].latest)
        self.d0, self.d1 = float(nd[self.d].earliest), float(nd[self.d].latest)
        self.nb = int(math.floor((self.H1 - self.H0) / self.delta)) + 1
        self.pen, self.tc = float(inst.penalty_cars), float(inst.travelcoststreet)
        # Table-1 windows (K's own bounds on h_i)
        self.e = {c: max(float(nd[c].earliest), self.H0 + D[self.g][c]) for c in self.C}
        self.l = {c: min(float(nd[c].latest), self.H1 - D[c][self.g] - float(nd[c].service) - self.U) for c in self.C}
        self.sv = {c: float(nd[c].service) for c in self.C}
        m = self.m = gp.Model("tep_cg"); m.Params.OutputFlag = 0; m.Params.Threads = threads
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
                ba = int(math.floor((end + D[seq[-1]][p] - self.H0) / self.delta))
                if ba <= self.nb - 1: out.append((g, None, p, ba))
        for L in self.sats:
            seen = {}
            for b in range(self.win, self.nb):
                sb = self.H0 + b * self.delta
                if sb + D[L][seq[0]] > self.l[seq[0]] + 1e-9: break
                end = self.simulate(seq, sb + D[L][seq[0]])
                if end is None: break
                for p in self.sats:
                    ba = int(math.floor((end + D[seq[-1]][p] - self.H0) / self.delta))
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
                ba = int(math.floor((t + D[last][p] - H0) / dl))
                if ba <= nb - 1:
                    v = tc * D[last][p] - sufmax[p][ba]
                    if v < best: best = v
            return best
        return entry, exit_, exit_fn

    def best_variant(self, seq, pi, mu_src, mu_pre, mu_post):
        base = -sum(pi[c] for c in seq)
        best = None
        for (L, b, p, ba) in self.variants(seq):
            rc = self.cost(seq, L, p) + base + (mu_src if L == self.g else mu_post[(L, b)]) - mu_pre[(p, ba)]
            if best is None or rc < best[0]: best = (rc, L, b, p, ba)
        return best


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
    m.Params.Threads = threads; m.Params.TimeLimit = timelimit
    if work: m.Params.WorkLimit = work
    m.Params.MIPGap = 1e-4
    t0 = time.time(); m.optimize(); secs = time.time() - t0
    res = dict(ip_status=int(m.Status), ip_secs=round(secs, 1), ip_threads=threads, ip_timelimit=timelimit)
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
    events = []
    for i in range(len(used)):
        if start[i][0] == M.g: events.append((arr[i][1], 1, "arrive", i))
    for p in M.sats:
        for b in zl[p]: events.append((b, 2, "transfer", p))
        for b, i in deps[p]: events.append((b, 3, "depart", i))
    events.sort(key=lambda e: (e[0], e[1]))
    ok = True; guard = 0
    # arrivals of non-depot trips are emitted when the trip departs (its car is then known)
    while events and guard < 100000:
        guard += 1
        b, _, kind, x = events.pop(0)
        if kind == "arrive":
            p, ba = arr[x]; pending[p].append((ba, car_of_trip[x])); pending[p].sort()
        elif kind == "transfer":
            p = x
            cand = [c for c in pending[p] if c[0] <= b]
            if not cand: ok = False; continue
            c = cand[0]; pending[p].remove(c); avail[p].append((b + M.win, c[1])); avail[p].sort()
        else:
            i = x; p = start[i][0]
            cand = [c for c in avail[p] if c[0] <= b]
            if not cand: ok = False; continue
            c = cand[0]; avail[p].remove(c); car = c[1]
            chains[car].append(i); car_of_trip[i] = car
            events.append((arr[i][1], 1, "arrive", i)); events.sort(key=lambda e: (e[0], e[1]))
    res["decode_ok"] = ok; res["chains"] = chains; res["decoded_cars"] = len(chains)
    res["trips"] = trips; res["hubs"] = [hub[i] for i in range(len(used))]
    if not ok:
        return res
    cand = decode(trips, {"chains": chains, "hub": hub}, depot=M.g)
    out, status, rsecs = retime(cell, cand, cap=retime_cap)
    res["retime_status"] = str(status); res["retime_secs"] = round(rsecs, 1)
    if out is None:
        res["verified"] = False; return res
    run_ = V.verify_solution(M.inst, out, cell=cell, size=size, proximity=0.1, label="tep_master_ip")
    bad = [x for x in run_.findings if x.severity != "TOLERANCE"]
    res["verified"] = (not bad) and (not run_.blocking); res["objVal"] = out["objVal"]; res["nCars"] = out["nCars"]; res["nVessel"] = out["nVessel"]
    res["recomputed"] = run_.objective.get("recomputed"); res["solution"] = out
    return res


def run(cell, delta, iters, seed_cols, ng, per_iter, build_only, label_cap, size=100, check_cap=20000, smooth=0.5, stall=15, max_secs=0.0, check_secs=60.0, ip=None, det_budget=0, proximity=None):
    # FIX 2. `t0` below is set AFTER the master and pricer are built, and it is what max_secs is
    # measured against. It is NOT moved -- moving it would change when the wall fires, which is
    # the algorithm. `t_origin` is a SECOND clock, started here, used only to timestamp phases.
    # On C204 n100 the build was about 100 s and appeared in no record at all.
    t_origin = time.time(); phases = []

    def phase(name, **kw):
        phases.append(dict(phase=name, t=round(time.time() - t_origin, 3), **kw))

    phase("start")
    # K'S PROXIMITY FOR THE SIZE, not a hardcoded 0.1. The banked solver wrote 0.1 at both call
    # sites for EVERY size. K's canonical extraction (analysis/kref.py, text_facts.proximity)
    # gives table3 0.0 for |C| in {10,20,30}, table4 0.0 for |C| = 50 and table6 0.1 for
    # |C| = 100 -- so the hardcoded value is correct at n100 alone and builds a DIFFERENT
    # PROBLEM INSTANCE at every other size. Measured on C201 n10: proximity 0.0 gives 685 rows,
    # 1100 vars, 58 buckets and 193 seed columns; 0.1 gives 677, 1096, 57 and 197. Not the same
    # instance, so a bound built at 0.1 is not comparable with K's table for that size.
    #
    # THIS BREAKS THE REPRODUCTION AT n10..n50 DELIBERATELY. Reproducing a defect that solves
    # the wrong instance is not useful; at n100 the two agree because 0.1 is correct there.
    prox = k_proximity(size) if proximity is None else float(proximity)
    inst = V.load_instance(cell, size, prox); ctx = Ctx(inst)
    phase("instance_loaded", tau=float(inst.tau), customers=len(list(inst.customers)))
    M = Master(inst, delta); pr = Pricer(inst, scale=M.tc, table1=True, ng=(ng or None))
    phase("master_and_pricer_built", rows=M.m.NumConstrs, vars=M.m.NumVars,
          buckets=M.nb, z_arcs=len(M.z), booking_rows=len(M.book))
    n0 = 0
    for name in seed_cols:
        trips = prio_st(ctx) if name == "prio" else time_slice(ctx)
        for seq in trips:
            for (L, b, p, ba) in M.variants(list(seq)):
                n0 += M.add_column(list(seq), L, b, p, ba)
    M.m.update()
    phase("seed_columns_added", seed_cols=list(seed_cols), columns=n0)
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

    def price_with(duals_p, duals_true, stage_len):
        mu_src_p, pi_p, mu_pre_p, mu_post_p = duals_p
        entry, exit_, exit_fn = M.pricer_legs(mu_src_p, mu_pre_p, mu_post_p)
        found, nlab, exhausted = pr.price(pi_p, maxlen=stage_len, keep=10 ** 9, rc_cut=-1e-6, entry=entry, exit=exit_, exit_fn=exit_fn, label_cap=label_cap)
        mu_src_t, pi_t, mu_pre_t, mu_post_t = duals_true
        added = 0; best_rc = 0.0; checked = 0; t_chk = time.time()
        for rc0, cost, seq in found:
            # the pricer's order is by an UNDERESTIMATE, so exact negatives can sit deep in the
            # list; keep checking until per_iter negatives are added, or the check has run for
            # check_secs AND at least check_cap candidates were seen with something added.
            # With nothing added the check runs to the end (that is what a proof needs).
            if added >= per_iter:
                per_iter_hit[0] += 1
                break
            # FIX 5 (edit 1 of 2). WAS:
            #     if added > 0 and checked >= check_cap and time.time() - t_chk > check_secs
            # A wall test INSIDE the candidate scan made column SELECTION machine-dependent: a
            # slower host truncates earlier and admits a different column set, so the run is not
            # reproducible even when it converges.
            #
            # THE TRUNCATION IS DROPPED RATHER THAN RE-CUT, and the direction matters. Deleting
            # only the wall term leaves `added > 0 and checked >= check_cap`, which fires
            # WHENEVER the original would AND also whenever the wall had not yet elapsed -- i.e.
            # it scans STRICTLY FEWER candidates than the code being reproduced. Scanning to the
            # end is the only deterministic choice that is never less thorough than the original:
            # it can admit more columns, never fewer, and the original's own comment says the
            # full scan "is what a proof needs".
            #
            # THE COST IS REAL AND IS NOT HIDDEN. `found` reaches hundreds of thousands of
            # candidates on the large cells and each one costs a best_variant call, so an
            # iteration can be far slower than under the banked code. That is the price of
            # deterministic column selection; `checked` is on every event row so it can be
            # measured rather than guessed.
            pass
            var = M.best_variant(list(seq), pi_t, mu_src_t, mu_pre_t, mu_post_t); checked += 1
            if var and var[0] < -1e-6:
                best_rc = min(best_rc, var[0])
                if added < per_iter: added += M.add_column(list(seq), var[1], var[2], var[3], var[4])
        return found, nlab, exhausted, added, best_rc, checked

    stages = [5, 7, None]; stage = 0; center = None
    hist = []; t0 = time.time(); proven = False; status = "iters"; flat = 0; last_val = None
    phase("cg_loop_start", build_s=round(t0 - t_origin, 3))
    events, gates, improvements, descent = [], [], [], []
    labels_cum = [0]; last_lp = [None]
    # counted inside price_with (a closure), read by the gate rows after each iteration
    scan_trunc = [0]; per_iter_hit = [0]

    def gate(name, fired, decision, **kw):
        """Every stop decision, fired or not, with its inputs and its GO/NO-GO. The original
        recorded none of these: a gate that permitted work left no trace, so its silence could
        not be told from its never having been reached."""
        gates.append(dict(gate=name, t=round(time.time() - t0, 2), it=kw.pop("it", None),
                          fired=bool(fired), decision=decision, **kw))

    bound_by = ["converged"]
    for it in range(iters):
        scan_trunc[0] = 0; per_iter_hit[0] = 0
        # FIX 5 (edit 2 of 2). A DETERMINISTIC stop, checked before the wall. Pricer labels
        # reproduce; wall seconds are this host on this day. The wall is retained as a backstop
        # and a run it stops is flagged reproducible=false rather than reported as if it were.
        det_over = bool(det_budget and labels_cum[0] > det_budget)
        gate("G_det_budget", det_over, "NO-GO" if det_over else "GO", it=it,
             labels=int(labels_cum[0]), det_budget=int(det_budget))
        if det_over:
            status = "det_budget"; bound_by[0] = "det"; break
        over = bool(max_secs and time.time() - t0 > max_secs)
        gate("G_max_secs", over, "NO-GO" if over else "GO", it=it,
             elapsed_s=round(time.time() - t0, 2), max_secs=max_secs)
        if over:
            status = "max_secs"; bound_by[0] = "wall"; break
        M.m.optimize(); M.det_work += _work_of(M.m); val = M.m.ObjVal
        pi, mu_src, mu_pre, mu_post = M.duals()
        duals_true = (mu_src, pi, mu_pre, mu_post)
        if it < 3:
            print("  rc transcription check (my formula vs Gurobi RC, 200 columns): max |diff| %.6f" % M.check_rc(pi, mu_src, mu_pre, mu_post), flush=True)
        t1 = time.time()
        smoothed = center is not None and smooth > 0
        duals_p = blend(center, duals_true, smooth) if smoothed else duals_true
        found, nlab, exhausted, added, best_rc, checked = price_with(duals_p, duals_true, stages[stage])
        mis = False
        if added == 0 and smoothed and not exhausted:
            mis = True
            found, nlab, exhausted, added, best_rc, checked = price_with(duals_true, duals_true, stages[stage])
        center = duals_p if (added > 0 and not mis) else duals_true
        t_price = time.time() - t1
        slack_use = sum(v.X for v in M.slack.values())
        labels_cum[0] += int(nlab)
        hist.append(dict(it=it, stage=stages[stage], lp=round(val, 2), cols=len(M.cols), cand=len(found), checked=checked, added=added, best_rc=round(best_rc, 2), labels=nlab, exhausted=exhausted, mispriced=mis, slack=round(slack_use, 3), N=round(M.N.X, 3), price_s=round(t_price), secs=round(time.time() - t0)))
        # RT TRAJECTORY. `labels` here is CUMULATIVE, unlike hist's per-iteration `labels`;
        # `work` is cumulative by construction. Both monotone, so either can anchor a post-hoc
        # truncation of this run to any runtime. Wall alone cannot: it is this host on this day.
        events.append(dict(t=round(time.time() - t0, 2), it=it, stage=stages[stage],
                           lp=round(val, 6), work=round(M.det_work, 6),
                           labels=int(labels_cum[0]), cols=len(M.cols), added=added,
                           exhausted=bool(exhausted), mispriced=bool(mis),
                           slack=round(slack_use, 6)))
        # THE LP DESCENDS; IT DOES NOT IMPROVE. In column generation the restricted master's
        # optimum falls toward the converged value from above, so no mid-run iterate is a lower
        # bound and there is no sequence of improving LB values to record. The fit-or-drop rule:
        # only the CONVERGED value is reportable. `descent` therefore logs each fall as progress
        # toward a bound, explicitly not as a bound; the single entry in `improvements` is
        # written at convergence, below, and is the only moment an LB value exists at all.
        if last_lp[0] is None or val < last_lp[0] - 1e-9:
            descent.append(dict(t=round(time.time() - t0, 2), it=it,
                                work=round(M.det_work, 6), labels=int(labels_cum[0]),
                                lp_from=(None if last_lp[0] is None else round(last_lp[0], 6)),
                                lp_to=round(val, 6),
                                drop=(None if last_lp[0] is None else round(last_lp[0] - val, 6)),
                                operator="tep:d%g:stage%s" % (delta, stages[stage]),
                                delta=delta, stage=stages[stage], is_bound=False,
                                note="CG iterate, descending from above; NOT a bound until the "
                                     "exact pass converges"))
            last_lp[0] = val
        print("  it %2d  len %-4s LP %9.2f  N %5.2f  cols %6d  cand %7d  chk %6d  +%4d  best rc %9.2f  labels %8d%s%s  slack %.3f  price %4.0fs  %5.0fs"
              % (it, stages[stage] or "all", val, M.N.X, len(M.cols), len(found), checked, added, best_rc, nlab, " EXHAUSTED" if exhausted else "", " misprice" if mis else "", slack_use, t_price, time.time() - t0), flush=True)
        gate("G_scan_truncated", bool(scan_trunc[0]), "NO-GO" if scan_trunc[0] else "GO", it=it,
             checked=checked, check_cap=check_cap, cand=len(found),
             note="candidate scan cut on check_cap; deterministic since 1.3")
        gate("G_per_iter_cap", bool(per_iter_hit[0]), "NO-GO" if per_iter_hit[0] else "GO", it=it,
             added=added, per_iter=per_iter)
        gate("G_misprice_retry", bool(mis), "NO-GO" if mis else "GO", it=it,
             smooth=smooth, note="smoothed pass added nothing; re-priced on the true duals")
        gate("G_exhausted", bool(exhausted), "NO-GO" if exhausted else "GO", it=it,
             labels=int(nlab), label_cap=label_cap)
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
            if added == 0:
                proven = slack_use < 1e-6; status = "proven" if proven else "slack"
                gate("G_converged", True, "GO" if proven else "NO-GO", it=it,
                     added=added, slack=round(slack_use, 9), cand=len(found),
                     note="exact stage added nothing; proven iff no covering slack")
                if proven:
                    # THE ONLY MOMENT AN LB VALUE EXISTS. Everything before this is a descending
                    # iterate and is not a bound (fit-or-drop).
                    improvements.append(dict(t=round(time.time() - t0, 2), it=it,
                                             work=round(M.det_work, 6),
                                             labels=int(labels_cum[0]),
                                             lb_from=None, lb_to=round(val, 6), gain=None,
                                             operator="tep:d%g:exact" % delta, delta=delta,
                                             stage=None, certified=True,
                                             note="exact pass converged with no slack; this is "
                                                  "the first and only reportable LB of the run"))
                break
            stalled = bool(stall and flat >= stall)
            gate("G_stalled", stalled, "NO-GO" if stalled else "GO", it=it,
                 flat=flat, stall=stall)
            if stalled:
                status = "stalled"; break
            stage = 0; flat = 0
        else:
            # FIX 3. The stage-escalation gate: it decides whether the EXACT pricer is ever
            # reached, and so whether a certificate is possible at all. Previously unrecorded.
            esc = bool(added == 0 or best_rc > tol_h or flat >= 5)
            gate("G_stage_escalation", esc, "ESCALATE" if esc else "HOLD", it=it,
                 stage_from=stages[stage], stage_to=(stages[stage + 1] if esc and stage + 1 < len(stages) else stages[stage]),
                 added=added, best_rc=round(best_rc, 6), tol_h=round(tol_h, 6), flat=flat,
                 note="heuristic stage yields to the next when it adds nothing, cannot move the "
                      "LP, or the LP has been flat for 5 iterations")
            if esc:
                stage += 1; flat = 0
    M.m.optimize(); val = M.m.ObjVal
    r = dict(cell=cell, size=size, delta=delta, ng=ng, lp_street=val, N=M.N.X, cols=len(M.cols), iters=len(hist), proven=proven, status=status, secs=round(time.time() - t0), hist=hist)
    # ---- RT TRAJECTORY ----------------------------------------------------------------------
    r["events"] = events
    r["descent"] = descent
    r["improvements"] = improvements
    r["gates"] = gates
    r["det_ticks"] = dict(gurobi_work=round(M.det_work, 6), pricer_labels=int(labels_cum[0]),
                          cg_iters=len(hist))
    # ---- EVERY PARAMETER, including the ones left at a default --------------------------------
    r["params"] = dict(iters_cap=int(iters), seed_cols=list(seed_cols), per_iter=int(per_iter),
                       label_cap=int(label_cap), check_cap=int(check_cap), smooth=float(smooth),
                       stall=int(stall), max_secs=float(max_secs), build_only=bool(build_only),
                       size=int(size), delta=float(delta), ng=ng, threads=1,
                       stages=[5, 7, None],
                       # FIX 4. check_secs gated the candidate scan and was not recorded; it is
                       # INERT since 1.3 (the wall term was removed from that test) and both
                       # facts are on the page.
                       check_secs=float(check_secs), check_secs_active=False,
                       det_budget=int(det_budget),
                       # FIX 4. proximity is HARDCODED 0.1 for every size in this solver
                       # (lines 363 and 556). k_comparison.k_proximity(20) is 0.0, so any run
                       # of this file below |C| = 100 is built at the wrong proximity. That is
                       # the banked behaviour, reproduced faithfully, and now visible.
                       proximity=float(prox), proximity_source=(
                           "k_comparison.k_proximity(size), from K's text_facts.proximity"
                           if proximity is None else "--proximity override"),
                       proximity_hardcoded=False)
    r["phases"] = phases
    r["bound_by"] = bound_by[0]
    r["reproducible"] = (bound_by[0] != "wall")
    r["smooth"] = float(smooth)
    # ---- WHY THIS IS NOT A CITABLE BOUND, on the artifact rather than in a README --------------
    # This solver predates d436, which measured its pricer against ground truth
    # (tep_exact_small: no pricer, full enumeration) and found it REFUTED ON 14 OF 27 CELLS at
    # |C| = 10, over-stating by up to 1.141 per cent WHILE PRINTING PROVEN True. There is no
    # start-state switch in this file; it did not exist yet. `proven` is the pricer's own word.
    r["valid_bound"] = False
    r["valid_bound_why"] = ("reproduction of the pre-d436 solver: no start-state pricing, which "
                            "d436 refuted on 14 of 27 cells at |C|=10 while it printed PROVEN "
                            "True. Recorded for comparison with the banked corpus, not citable.")
    r["reproduces"] = "git 15f739c analysis/tep_cg_bound.py + tep_pricer.py, verbatim"
    if ip:
        phase("master_ip_start", columns=len(M.cols))
        print("  master IP over %d columns (threads %d, cap %.0f s) ..." % (len(M.cols), ip["threads"], ip["timelimit"]), flush=True)
        r["ip"] = master_ip(M, cell, size, threads=ip["threads"], timelimit=ip["timelimit"], work=ip.get("work", 0.0))
        q = r["ip"]
        if q.get("ip_street") is not None:
            print("  IP street %.1f vs LP %.1f -> integrality gap within the pool %.1f%% | cars %.0f (decoded %s, ok %s) | re-time %s -> %s"
                  % (q["ip_street"], val, 100.0 * (q["ip_street"] / val - 1), q["ip_cars"], q.get("decoded_cars"), q.get("decode_ok"), q.get("retime_status"),
                     ("obj %.1f cars %d vessels %d verifier3 %s" % (q["objVal"], q["nCars"], q["nVessel"], "PASS" if q.get("verified") else "FAIL")) if q.get("objVal") else "no solution"), flush=True)
        else:
            print("  IP: no solution within the cap", flush=True)
        phase("master_ip_done", ip_status=(q or {}).get("ip_status"),
              ip_secs=(q or {}).get("ip_secs"), ip_street=(q or {}).get("ip_street"),
              retime_status=(q or {}).get("retime_status"), verified=(q or {}).get("verified"))
    phase("run_end", status=status, proven=bool(proven), iters=len(hist))
    r["phases"] = phases
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
    ap.add_argument("--proximity", type=float, default=None,
                    help="omit for K's proximity for the size (0.0 up to n50, 0.1 at n100). The banked "
                         "solver hardcoded 0.1 everywhere, which is the wrong instance below n100.")
    ap.add_argument("--allow-wall-stop", action="store_true",
                    help="GAP C: bank a wall-stopped run as a DIAGNOSTIC. Without it such a run is refused.")
    ap.add_argument("--det-budget", type=int, default=0, help="FIX 5: deterministic stop in pricer labels; 0 = off, wall decides and the run is flagged irreproducible")
    a = ap.parse_args()
    prox_main = k_proximity(a.size) if a.proximity is None else a.proximity
    inst = V.load_instance(a.cell, a.size, prox_main)
    default_delta = float(inst.tau) if float(inst.tau) <= 60 else float(inst.tau) / 3
    delta = a.delta or default_delta
    # A DISTINCT FILENAME. tep_cg_bound.py names its output from cell/size/delta alone, so
    # running this under the original scheme would OVERWRITE the banked artifact it is meant to
    # be compared against.
    out_name = "tep_cg_banked_%s%s%s.json" % (a.cell, "" if a.size == 100 else "_n%d" % a.size, "" if abs(delta - default_delta) < 1e-9 else "_d%d" % int(round(delta)))
    print("TEP CG bound -- %s n%d, DELTA %.0f (tau %.0f), ng %s, seed columns %s -> runs/oracle/%s" % (a.cell, a.size, delta, inst.tau, a.ng or "elementary", a.seed_cols, out_name), flush=True)
    r = run(a.cell, delta, a.iters, a.seed_cols.split(","), a.ng, a.per_iter, a.build_only, a.label_cap, size=a.size, check_cap=a.check_cap, smooth=a.smooth, stall=a.stall, max_secs=a.max_secs,
            ip=(dict(threads=a.ip_threads, timelimit=a.ip_time, work=a.ip_work) if a.ip else None), det_budget=a.det_budget,
            proximity=prox_main)
    if a.ip:
        out_name = out_name.replace(".json", "_ip.json")
    if a.build_only:
        print("  build-only: OK"); return
    ab = {(q["cell"], q["size"]): q for q in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}[(a.cell, a.size)]
    ab_street = float(ab["fleet_term"]) + float(ab["travel_term"])
    print("\n  LP street part %.1f (N %.2f cars, %d columns, %d iterations, %.0fs)  PROVEN %s" % (r["lp_street"], r["N"], r["cols"], r["iters"], r["secs"], r["proven"]))
    print("  AB4 street part (fleet_term + travel_term) %.1f -> street bound x%.3f; AB4 total %.1f with water %.1f -> composed %.1f"
          % (ab_street, r["lp_street"] / ab_street, float(ab["ab4"]), float(ab["water"]), r["lp_street"] + float(ab["water"])))
    print("  VALID only if PROVEN True (exact pricer converged, no covering slack).")
    r["ab_street"] = ab_street; r["ab4"] = float(ab["ab4"]); r["water_ab"] = float(ab["water"]); r["composed"] = r["lp_street"] + float(ab["water"])
    r["_command"] = " ".join(sys.argv); r["_finished"] = time.strftime("%Y-%m-%d %H:%M")
    # PROVENANCE. The original wrote a bare json.dump with no stamp of any kind. `stamped` adds
    # per-source sha256, source_hash, code_hash, git sha and dirty set, machine, python, solver
    # versions -- and REFUSES to write at all when a value-determining source is uncommitted.
    # GAP C. Flagging a wall-decided run is not enforcing determinism -- 1.3 recorded
    # `reproducible: false` and wrote the artifact anyway, so nothing stopped the old way of
    # running it. An artifact whose TRAJECTORY was chosen by the wall clock cannot be reproduced
    # on another machine, and by this project's own standard it is not written. --allow-wall-stop
    # exists for diagnosis and stamps the artifact as diagnostic so it can never be mistaken for
    # a result.
    if r.get("bound_by") == "wall" and not a.allow_wall_stop:
        raise SystemExit(os.linesep.join([
            "REFUSING TO WRITE %s: the run was stopped by the WALL (max_secs %.0f s), so its"
            % (out_name, float(a.max_secs)),
            "trajectory -- how many iterations ran, which columns entered -- is this machine on",
            "this day and does not reproduce. Give it a deterministic budget (--det-budget, in",
            "pricer labels; this run reached %d) or pass --allow-wall-stop to bank it as a"
            % int(r["det_ticks"]["pricer_labels"]),
            "DIAGNOSTIC. There is no silent third option."]))
    r["diagnostic_only"] = bool(r.get("bound_by") == "wall")
    out = os.path.join(ROOT, "runs", "oracle", out_name)
    d = stamped(r, *SOURCES, det=r["det_ticks"], wall=r["secs"])
    tmp = out + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, out)


if __name__ == "__main__":
    main()
