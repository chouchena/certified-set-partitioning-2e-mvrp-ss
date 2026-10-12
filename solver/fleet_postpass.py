"""Standalone fleet-reduction post-pass. Applies to ANY valid incumbent. Never damages one.

    from solver.fleet_postpass import apply
    better, report = apply(inst, sol)        # sol unchanged unless a VERIFIED gain is found

INDEPENDENT BY CONSTRUCTION. It takes an instance and a solution dict and returns a solution dict.
It imports no engine, holds no state between calls, and does not care how the incumbent was
produced -- fix-and-optimize, a constructor, or a hand-built solution.

WHAT IT DOES. Tries to empty one vehicle route and place its customers into the slack the other
routes already carry. That is the move first-improvement descent structurally cannot make:
emptying a route is worth penalty_cars (171-224), but every intermediate relocate leaves the route
alive, so each step alone looks like a cost increase. Adding exactly this move to a sequence local
search at n10 moved the mean gap from +63.07 percent to +0.27 percent.

WHY IT PRESERVES THE TIMETABLE INSTEAD OF REBUILDING IT. Measured, and this is the expensive
lesson of 2026-09-22: re-deriving transfer times greedily -- earliest feasible arrival, (26)
resolved by pushing past conflicts -- FAILS ON 26 OF 27 KNOWN-FEASIBLE production route sets, even
when transfer positions AND hubs are preserved. Transfer times are a scheduling decision, not a
derivation. So untouched routes keep every committed (h, u) exactly, and only a route that
actually receives a customer is re-timed, against the bookings the untouched routes already hold.

WHY IT CANNOT DAMAGE A SOLUTION. Every candidate must (a) verify with zero findings above
TOLERANCE and zero blocking, and (b) strictly improve the objective, before it is adopted. The
objective is read from the VERIFIER's own recompute, not from a second implementation that could
disagree. If nothing qualifies, the input is returned unchanged.

WHAT IT REACHES, MEASURED ON 27 n100 CELLS. The cheapest route is fully reinsertable into existing
slack on 6 of 27 (C201, R202, R209, R211, RC202, RC206), one car each. On the other 21 the blocker
is CAPACITY on every cell, not time windows -- consistent with trips already sitting 2 to 10 above
the packing floor with maximum segment load exactly 50. Lifting that needs transfers to be ADDED
to receiving routes, which requires the (26)-aware rescheduler the second paragraph says does not
exist yet. This module deliberately stops at the boundary of what it can verify.

COST. Slack scan under 0.0001 s per cell; one verify 0.0123 s; a whole pass 0.09-0.16 s against a
600-750 s production run, about +0.02 percent runtime.
"""
from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_AN = os.path.join(_ROOT, "analysis")
if _AN not in sys.path:
    sys.path.insert(0, _AN)

from instance_view import LEFV_CAPACITY

TOL = 1e-6


# --------------------------------------------------------------------------- structure
def routes_from_arcs(xij, customers):
    """Per-vehicle customer sequences in visit order."""
    succ = {}
    for a, b in xij:
        succ.setdefault(int(a), []).append(int(b))
    out, used = [], set()
    for start in succ.get(0, []):
        cur, seq, guard = start, [], 0
        while guard < 10000 and cur != 0:
            guard += 1
            if cur in customers:
                seq.append(cur)
            nxt = [x for x in succ.get(cur, []) if (cur, x) not in used]
            if not nxt:
                break
            used.add((cur, nxt[0]))
            cur = nxt[0]
        if seq:
            out.append(seq)
    return out


def _tours(yij, CDC):
    """Vessel tours as lists of transfer tasks, walked from the CDC. Mirrors verifier3."""
    succ = {}
    for a, b in yij:
        a, b = int(a), int(b)
        if a != CDC:
            succ[a] = b
    starts = [int(b) for a, b in yij if int(a) == CDC]
    out = []
    for s in starts:
        cur, tour, guard = s, [], 0
        while cur != CDC and guard < 10000:
            guard += 1
            tour.append(cur)
            if cur not in succ:
                break
            cur = succ[cur]
        if tour:
            out.append(tour)
    return out


def _splice(yij, c):
    """Remove transfer c from its vessel tour, reconnecting its neighbours (impair30.splice_vessel)."""
    pred = [a for a in yij if int(a[1]) == c]
    succ = [a for a in yij if int(a[0]) == c]
    out = [list(a) for a in yij if int(a[0]) != c and int(a[1]) != c]
    if len(pred) == 1 and len(succ) == 1:
        i, j = int(pred[0][0]), int(succ[0][1])
        if i != j:
            out.append([i, j])
    return out


# --------------------------------------------------------------------------- timing
class _Sched:
    """The incumbent's committed schedule, plus the arithmetic the model defines on it.

    The propagation here was checked against production: it reproduces committed h EXACTLY,
    node for node, including legs departing from a satellite after a transfer.
    """

    def __init__(self, inst, sol):
        self.inst = inst
        self.D, self.nd = inst.D, inst.nodes
        self.tau = float(inst.tau)
        self.depot, self.CDC = inst.depot, inst.CDC
        self.H = {int(k): float(v) for k, v in (sol.get("hi") or {}).items()}
        self.U = {int(k): float(v) for k, v in (sol.get("ui") or {}).items()}
        self.tset = {int(x) for x in (sol.get("vi") or [])}
        self.hub = {int(t): int(h) for t, h in zip(sol.get("vi") or [], sol.get("hubs") or [])}
        self.routes = routes_from_arcs(sol["xij"], set(inst.customers))

    def usable(self):
        if not self.H or not self.U or len(self.routes) < 2:
            return False
        for r in self.routes:
            if not r or r[-1] not in self.tset:
                return False                      # Const4: routes close with a transfer
            if any(c not in self.H for c in r):
                return False
        return all(t in self.U for t in self.tset)

    # -- read-only queries on the committed schedule ------------------------------------
    def slack_from(self, seq, idx):
        """How far nodes from `idx` on can shift before a window or a transfer bound breaks."""
        s = float("inf")
        for k in range(idx, len(seq)):
            c = seq[k]
            s = min(s, float(self.nd[c].latest) - self.H[c])
            if c in self.tset:
                p = self.hub[c]
                s = min(s, (float(self.nd[self.CDC].latest) - self.tau - self.D[p][self.CDC])
                        - self.U[c])
            if s <= TOL:
                return 0.0
        return max(0.0, s)

    def seg_load(self, seq, idx):
        """Demand on the trip containing position `idx` (bounded by transfers)."""
        lo = 0
        for k in range(idx - 1, -1, -1):
            if seq[k] in self.tset:
                lo = k + 1
                break
        hi = len(seq) - 1
        for k in range(idx, len(seq)):
            if seq[k] in self.tset:
                hi = k
                break
        return sum(float(self.nd[seq[k]].demand) for k in range(lo, hi + 1))

    def can_insert(self, seq, cust, pos):
        """(detour, ) if `cust` fits at `pos` within existing capacity and slack, else None."""
        D, nd = self.D, self.nd
        a = seq[pos - 1] if pos > 0 else self.depot
        b = seq[pos] if pos < len(seq) else self.depot
        src = self.hub[a] if (pos > 0 and a in self.tset) else a
        if self.seg_load(seq, pos) + float(nd[cust].demand) > LEFV_CAPACITY + TOL:
            return None
        if pos > 0 and a in self.tset:
            base = self.U[a] + self.tau
        elif pos > 0:
            base = self.H[a] + float(nd[a].service)
        else:
            base = float(nd[self.depot].earliest)
        h = max(float(nd[cust].earliest), base + D[src][cust])
        if h > float(nd[cust].latest) + TOL:
            return None
        ref = self.H[b] if b != self.depot else base + D[src][b]
        push = (h + float(nd[cust].service) + D[cust][b]) - ref
        if push > self.slack_from(seq, pos) + TOL:
            return None
        return D[src][cust] + D[cust][b] - D[src][b]

    # -- write: re-time one route that actually changed ---------------------------------
    def retime(self, seq, booked):
        """Recompute (h, u) for `seq` against `booked`. Returns (H_part, U_part) or None."""
        D, nd, tau = self.D, self.nd, self.tau
        H, U = {}, {}
        prev, ready, from_hub, load = self.depot, float(nd[self.depot].earliest), None, 0.0
        for c in seq:
            src = from_hub if from_hub is not None else prev
            dep = ready + (tau if from_hub is not None
                           else (float(nd[prev].service) if prev != self.depot else 0.0))
            h = max(float(nd[c].earliest), dep + D[src][c])
            if h > float(nd[c].latest) + TOL:
                return None
            if h > float(nd[self.depot].latest) - D[c][self.depot] - float(nd[c].service) - tau + TOL:
                return None
            load += float(nd[c].demand)
            if load > LEFV_CAPACITY + TOL:
                return None
            H[c] = h
            if c in self.tset:
                p = self.hub[c]
                lb = max(h + float(nd[c].service) + D[c][p],
                         float(nd[self.CDC].earliest) + D[self.CDC][p])
                ub = float(nd[self.CDC].latest) - tau - D[p][self.CDC]
                if c == seq[-1]:
                    ub = min(ub, float(nd[self.depot].latest) - tau - D[p][self.depot])
                u = lb
                for b in sorted(booked.get(p, [])):      # (26): step past every conflict
                    if u - tau < b < u + tau:
                        u = b + tau
                if u > ub + TOL:
                    return None
                U[c] = u
                booked.setdefault(p, []).append(u)
                ready, from_hub, load = u, p, 0.0
            else:
                ready, from_hub = h, None
            prev = c
        if seq[-1] not in self.tset:
            return None
        return H, U


# --------------------------------------------------------------------------- the pass
def _assemble(sc, routes, changed_idx, dropped_transfers, base_sol):
    """Build a full candidate solution. Untouched routes keep their committed times."""
    booked = {}
    for i, seq in enumerate(routes):
        if i in changed_idx:
            continue
        for c in seq:
            if c in sc.tset:
                booked.setdefault(sc.hub[c], []).append(sc.U[c])

    H, U = {}, {}
    for i, seq in enumerate(routes):
        if i in changed_idx:
            r = sc.retime(seq, booked)
            if r is None:
                return None
            H.update(r[0])
            U.update(r[1])
        else:
            for c in seq:
                H[c] = sc.H[c]
                if c in sc.tset:
                    U[c] = sc.U[c]

    arcs, transfers, hubs = [], [], []
    for seq in routes:
        prev = sc.depot
        for c in seq:
            arcs.append([prev, c])
            prev = c
        arcs.append([prev, sc.depot])
        for c in seq:
            if c in sc.tset:
                transfers.append(c)
                hubs.append(sc.hub[c])
    if not transfers:
        return None

    yij = [list(a) for a in base_sol.get("yij") or []]
    for c in dropped_transfers:
        yij = _splice(yij, c)
    live = set(transfers) | {sc.CDC}
    yij = [a for a in yij if int(a[0]) in live and int(a[1]) in live]

    # C-DEPOT-TIME: the depot's own time dominates every return
    h0 = float(sc.nd[sc.depot].earliest)
    hub_of = dict(zip(transfers, hubs))
    for seq in routes:
        last = seq[-1]
        h0 = max(h0, U[last] + sc.tau + sc.D[hub_of[last]][sc.depot])
    if h0 > float(sc.nd[sc.depot].latest) + TOL:
        return None
    H[sc.depot] = h0

    return {"xij": arcs, "vi": transfers, "hubs": hubs, "yij": yij,
            "nCars": len(routes), "nVessel": len(_tours(yij, sc.CDC)),
            "hi": {str(k): float(v) for k, v in H.items()},
            "ui": {str(k): float(v) for k, v in U.items()},
            "objVal": base_sol.get("objVal")}


def _clean(run):
    return (not run.blocking) and not any(f.severity != "TOLERANCE" for f in run.findings)


def apply(inst, sol, verify=None, cell=None, size=None, proximity=None, max_victims=None):
    """Try to remove one or more vehicles. Returns (solution, report).

    The returned solution is `sol` itself unless a candidate both VERIFIED clean and strictly
    improved the objective, so this is safe to run over any banked incumbent.
    """
    t0 = time.time()
    rep = {"removed": 0, "tried": 0, "verified": 0, "rejected": {},
           "obj_before": None, "obj_after": None, "delta": 0.0, "rt_s": 0.0,
           "cars_before": None, "cars_after": None, "status": "unchanged"}

    if verify is None:
        import verifier3 as _V
        def verify(s):
            return _V.verify_solution(inst, s, cell=cell, size=size,
                                      proximity=proximity, label="postpass")

    def rej(k):
        rep["rejected"][k] = rep["rejected"].get(k, 0) + 1

    run0 = verify(sol)
    if not _clean(run0):
        rep["status"] = "input did not verify clean; refusing to modify"
        rep["rt_s"] = round(time.time() - t0, 4)
        return sol, rep
    base = float(run0.objective.get("recomputed", sol.get("objVal")))
    rep["obj_before"] = rep["obj_after"] = base

    best = sol
    sc = _Sched(inst, sol)
    if not sc.usable():
        rep["status"] = "incumbent carries no usable committed timetable"
        rep["rt_s"] = round(time.time() - t0, 4)
        return sol, rep
    rep["cars_before"] = rep["cars_after"] = len(sc.routes)

    progress = True
    while progress and len(sc.routes) > 1:
        progress = False
        order = sorted(range(len(sc.routes)), key=lambda i: len(sc.routes[i]))
        if max_victims:
            order = order[:max_victims]
        for vic in order:
            rep["tried"] += 1
            # A failed attempt must leave the schedule exactly as it found it, or the next
            # victim is judged against times that belong to an abandoned candidate.
            snapH, snapU = dict(sc.H), dict(sc.U)
            others = [list(r) for i, r in enumerate(sc.routes) if i != vic]
            changed, ok = set(), True
            # Insertions are committed ONE AT A TIME and the receiving route is RE-TIMED after
            # each, so the next candidate is judged against the slack that actually remains.
            # Judging every customer against the original schedule is optimistic: the first
            # insertion consumes slack the second one then assumes is still there.
            for cust in sc.routes[vic]:
                cands = []
                for bi in range(len(others)):
                    for pos in range(len(others[bi]) + 1):
                        d = sc.can_insert(others[bi], cust, pos)
                        if d is not None:
                            cands.append((d, bi, pos))
                if not cands:
                    rej("no feasible insertion (capacity or slack)")
                    ok = False
                    break
                cands.sort()
                placed = False
                for _d, bi, pos in cands[:6]:
                    trial = others[bi][:pos] + [cust] + others[bi][pos:]
                    booked = {}
                    for j, seq in enumerate(others):
                        if j == bi:
                            continue
                        for c in seq:
                            if c in sc.tset:
                                booked.setdefault(sc.hub[c], []).append(sc.U[c])
                    r = sc.retime(trial, booked)
                    if r is None:
                        continue
                    others[bi] = trial
                    changed.add(bi)
                    sc.H.update(r[0])
                    sc.U.update(r[1])
                    placed = True
                    break
                if not placed:
                    rej("re-timing after insertion failed")
                    ok = False
                    break
            if not ok:
                sc.H, sc.U = snapH, snapU
                continue
            dropped = [c for c in sc.routes[vic] if c in sc.tset]
            cand = _assemble(sc, others, changed, dropped, best)
            if cand is None:
                rej("assembling the candidate failed")
                sc.H, sc.U = snapH, snapU
                continue
            run = verify(cand)
            if not _clean(run):
                rej("candidate did not verify")
                sc.H, sc.U = snapH, snapU
                continue
            rep["verified"] += 1
            obj = float(run.objective.get("recomputed"))
            if obj >= base - 1e-7:
                rej("verified but not an improvement")
                sc.H, sc.U = snapH, snapU
                continue
            cand["objVal"] = obj
            best, base = cand, obj
            rep["removed"] += 1
            rep["obj_after"] = obj
            rep["cars_after"] = cand["nCars"]
            rep["status"] = "improved"
            sc = _Sched(inst, cand)
            progress = True
            break

    rep["delta"] = round(rep["obj_after"] - rep["obj_before"], 4)
    rep["rt_s"] = round(time.time() - t0, 4)
    return best, rep


# --------------------------------------------------------------------------- thin-trip pass
def _trips_of(sc, routes):
    """(route_index, customers, load) for every trip, in visit order."""
    out = []
    for ri, seq in enumerate(routes):
        cur = []
        for c in seq:
            cur.append(c)
            if c in sc.tset:
                out.append((ri, list(cur), sum(float(sc.nd[x].demand) for x in cur)))
                cur = []
        if cur:
            out.append((ri, list(cur), sum(float(sc.nd[x].demand) for x in cur)))
    return out


def _assemble_explicit(sc, routes, tset, hub, changed, base_sol):
    """_assemble with the transfer set passed in, because retiring a trip removes the
    transfer marker from the customer that carried it."""
    booked = {}
    for i, seq in enumerate(routes):
        if i in changed:
            continue
        for c in seq:
            if c in tset:
                booked.setdefault(hub[c], []).append(sc.U[c])
    sv_t, sv_h = sc.tset, sc.hub
    sc.tset, sc.hub = tset, hub
    try:
        H, U = {}, {}
        for i, seq in enumerate(routes):
            if i in changed:
                r = sc.retime(seq, booked)
                if r is None:
                    return None
                H.update(r[0])
                U.update(r[1])
            else:
                for c in seq:
                    H[c] = sc.H[c]
                    if c in tset:
                        U[c] = sc.U[c]
        arcs, transfers, hubs = [], [], []
        for seq in routes:
            prev = sc.depot
            for c in seq:
                arcs.append([prev, c])
                prev = c
            arcs.append([prev, sc.depot])
            for c in seq:
                if c in tset:
                    transfers.append(c)
                    hubs.append(hub[c])
        if not transfers:
            return None
        yij = [list(a) for a in base_sol.get("yij") or []]
        for c in set(sv_t) - set(transfers):
            yij = _splice(yij, c)
        live = set(transfers) | {sc.CDC}
        yij = [a for a in yij if int(a[0]) in live and int(a[1]) in live]
        h0 = float(sc.nd[sc.depot].earliest)
        hub_of = dict(zip(transfers, hubs))
        for seq in routes:
            last = seq[-1]
            if last not in U:
                return None
            h0 = max(h0, U[last] + sc.tau + sc.D[hub_of[last]][sc.depot])
        if h0 > float(sc.nd[sc.depot].latest) + TOL:
            return None
        H[sc.depot] = h0
        return {"xij": arcs, "vi": transfers, "hubs": hubs, "yij": yij,
                "nCars": len(routes), "nVessel": len(_tours(yij, sc.CDC)),
                "hi": {str(k): float(v) for k, v in H.items()},
                "ui": {str(k): float(v) for k, v in U.items()},
                "objVal": base_sol.get("objVal")}
    finally:
        sc.tset, sc.hub = sv_t, sv_h


def spread_thin_trips(inst, sol, verify=None, cell=None, size=None, proximity=None,
                      max_passes=12):
    """Retire the EMPTIEST trip by spreading its customers, repeatedly.

    WHY THIS SUCCEEDS WHERE ROUTE ELIMINATION DOES NOT. A route needs every one of its customers
    rehomed at once and succeeds on 0 of 197 banked incumbents. The emptiest trip carries a median
    10 units -- one or two customers -- so it needs one or two insertions. Measured on the 27 n100
    production cells, the emptiest trip is fully redistributable on 16 of them.

    WHAT IT IS WORTH. Retiring a trip removes its transfer: the satellite detour it was paying
    (median 8.25, up to 105) plus a vessel task. It retires a CAR only when the trip was its
    route's last, which on those 27 cells it never was. So this is a travel move, not a fleet move,
    and it must not be reported as one.

    Verify-gated exactly as `apply`: nothing is adopted without zero findings above TOLERANCE and a
    strictly better objective taken from the verifier's own recompute.
    """
    t0 = time.time()
    rep = {"trips_removed": 0, "cars_removed": 0, "obj_before": None, "obj_after": None,
           "delta": 0.0, "rt_s": 0.0, "passes": 0, "rejected": {}, "status": "unchanged"}
    if verify is None:
        import verifier3 as _V

        def verify(s):
            return _V.verify_solution(inst, s, cell=cell, size=size,
                                      proximity=proximity, label="thintrip")

    def rej(k):
        rep["rejected"][k] = rep["rejected"].get(k, 0) + 1

    run0 = verify(sol)
    if not _clean(run0):
        rep["status"] = "input did not verify clean; refusing to modify"
        rep["rt_s"] = round(time.time() - t0, 4)
        return sol, rep
    base = float(run0.objective.get("recomputed", sol.get("objVal")))
    rep["obj_before"] = rep["obj_after"] = base
    best, cars0 = sol, None

    for _ in range(max_passes):
        rep["passes"] += 1
        sc = _Sched(inst, best)
        if not sc.usable():
            break
        if cars0 is None:
            cars0 = len(sc.routes)
        trips = _trips_of(sc, sc.routes)
        if len(trips) < 2:
            break
        done = False
        for ri, tcust, _load in sorted(trips, key=lambda t: t[2]):
            victim = set(tcust)
            others = [list(r) for r in sc.routes]
            others[ri] = [c for c in others[ri] if c not in victim]
            tset = set(sc.tset) - victim
            hub = {k: v for k, v in sc.hub.items() if k in tset}
            if not tset:
                continue
            snapH, snapU = dict(sc.H), dict(sc.U)
            changed, ok = {ri}, True
            for cust in tcust:
                cands = []
                for bi in range(len(others)):
                    if not others[bi]:
                        continue
                    for pos in range(len(others[bi]) + 1):
                        dd = sc.can_insert(others[bi], cust, pos)
                        if dd is not None:
                            cands.append((dd, bi, pos))
                cands.sort()
                placed = False
                for _dd, bi, pos in cands[:6]:
                    trial = others[bi][:pos] + [cust] + others[bi][pos:]
                    booked = {}
                    for j, seq in enumerate(others):
                        if j == bi:
                            continue
                        for c in seq:
                            if c in tset:
                                booked.setdefault(hub[c], []).append(sc.U[c])
                    sv_t, sv_h = sc.tset, sc.hub
                    sc.tset, sc.hub = tset, hub
                    try:
                        r = sc.retime(trial, booked)
                    finally:
                        sc.tset, sc.hub = sv_t, sv_h
                    if r is None:
                        continue
                    others[bi] = trial
                    changed.add(bi)
                    sc.H.update(r[0])
                    sc.U.update(r[1])
                    placed = True
                    break
                if not placed:
                    rej("no feasible insertion for a displaced customer")
                    ok = False
                    break
            if not ok:
                sc.H, sc.U = snapH, snapU
                continue
            others = [r for r in others if r]
            cand = _assemble_explicit(sc, others, tset, hub, set(range(len(others))), best)
            if cand is None:
                rej("assembly or re-timing failed")
                sc.H, sc.U = snapH, snapU
                continue
            run = verify(cand)
            if not _clean(run):
                rej("candidate did not verify")
                sc.H, sc.U = snapH, snapU
                continue
            obj = float(run.objective.get("recomputed"))
            if obj >= base - 1e-7:
                rej("verified but not an improvement")
                sc.H, sc.U = snapH, snapU
                continue
            cand["objVal"] = obj
            best, base = cand, obj
            rep["trips_removed"] += 1
            rep["obj_after"] = obj
            rep["status"] = "improved"
            done = True
            break
        if not done:
            break

    if cars0 is not None:
        rep["cars_removed"] = cars0 - int(best.get("nCars", cars0))
    rep["delta"] = round(rep["obj_after"] - rep["obj_before"], 4)
    rep["rt_s"] = round(time.time() - t0, 4)
    return best, rep
