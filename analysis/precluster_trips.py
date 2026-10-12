"""Spatiotemporal, customer-prioritised pre-clustering into trips, scored at the TRIP level
against the incumbent's own trips (author: 'spatiotemporal heuristic customer prioritized
pre-clustering trip-wise'). Thread-free.

Heuristic PRIO-ST: customers are taken in priority order (tightest window first, ties by fewest
compatible neighbours); each seeds a trip that is extended by the cheapest spatiotemporal
neighbour -- cost = travel + waiting if arriving before the window, infeasible if after it --
inserted at the best position, while load <= Q and the exact 4-customer TSPTW keeps the trip
feasible; the trip ends at the nearest satellite to its last customer. A variant TIME-SLICE
composes trips inside each satellite region from customers with adjacent window midpoints.

Scoring, identical for both sides: a trip's intrinsic waiting is the waiting at its LATEST
feasible start (order fixed), its travel is first customer -> ... -> last -> hub, its busy time
is travel + service + waiting + tau at the hub. Sums per cell against the incumbent's trips
(same customers, so travel and busy time are comparable; the start-location leg is excluded on
both sides).
"""
import io
import itertools
import json
import math
import os
import statistics as st
import sys

ROOT = r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from solver.fleet_postpass import routes_from_arcs

S = os.path.dirname(os.path.abspath(__file__))
Q, CLOSE, MAXLEN = 50.0, 10.0, 4
CELLS = [f + str(i) for f in ("C20", "R20", "RC20") for i in range(1, 9)] + ["R209", "R210", "R211"]


class Ctx:
    def __init__(self, inst):
        self.inst = inst
        nd = inst.nodes
        self.D, self.tau = inst.D, float(inst.tau)
        self.e = {c: float(nd[c].earliest) for c in inst.customers}
        self.l = {c: float(nd[c].latest) for c in inst.customers}
        self.sv = {c: float(nd[c].service) for c in inst.customers}
        self.dem = {c: float(nd[c].demand) for c in inst.customers}
        self.hub_of = {c: min(inst.satellites, key=lambda s: inst.D[c][s]) for c in inst.customers}

    def latest_start_eval(self, seq):
        """Order fixed: latest feasible start time before the first customer, then waiting,
        travel, busy time at that start. None if infeasible."""
        D, e, l, sv = self.D, self.e, self.l, self.sv
        # latest start: propagate backwards
        lat = l[seq[-1]]
        for a, b in zip(reversed(seq[:-1]), reversed(seq[1:])):
            lat = min(l[a], lat - sv[a] - D[a][b])
        if lat < e[seq[0]] - 1e-9:
            # can still be feasible if earliest start forces waiting somewhere; check forward from e[first]
            t0 = e[seq[0]]
        else:
            t0 = lat
        t, wait, travel = t0, 0.0, 0.0
        for i, c in enumerate(seq):
            if i:
                t += sv[seq[i - 1]] + D[seq[i - 1]][c]; travel += D[seq[i - 1]][c]
            if t < e[c]:
                wait += e[c] - t; t = e[c]
            if t > l[c] + 1e-9:
                return None
        hub = self.hub_of[seq[-1]]
        travel += D[seq[-1]][hub]
        busy = (t + sv[seq[-1]] + D[seq[-1]][hub] + self.tau) - t0
        return dict(wait=wait, travel=travel, busy=busy, start=t0)

    def best_order(self, cs):
        best = None
        for perm in itertools.permutations(cs):
            r = self.latest_start_eval(list(perm))
            if r is None: continue
            key = (r["busy"], r["travel"])
            if best is None or key < best[0]:
                best = (key, list(perm), r)
        return best


def prio_st(ctx, close=CLOSE, rng=None, jitter=30.0):
    """rng: a seeded random.Random for the five-seed design -- adds uniform jitter (0..jitter time
    units) to the window-width priority; None reproduces the deterministic order."""
    C = list(ctx.inst.customers)
    D, e, l, sv, dem = ctx.D, ctx.e, ctx.l, ctx.sv, ctx.dem
    deg = {i: sum(1 for j in C if j != i and D[i][j] <= close and ((e[i] + sv[i] + D[i][j] <= l[j]) or (e[j] + sv[j] + D[j][i] <= l[i]))) for i in C}
    jit = {c: (rng.uniform(0.0, jitter) if rng else 0.0) for c in C}
    order = sorted(C, key=lambda c: (l[c] - e[c] + jit[c], deg[c]))
    unassigned = set(C)
    trips = []
    for seed in order:
        if seed not in unassigned: continue
        unassigned.discard(seed)
        cur = [seed]; load = dem[seed]
        while len(cur) < MAXLEN:
            cands = []
            for j in unassigned:
                if load + dem[j] > Q: continue
                if min(D[c][j] for c in cur) > 2 * close: continue
                b = ctx.best_order(cur + [j])
                if b is None: continue
                cands.append((b[0], j, b[1]))
            if not cands: break
            cands.sort()
            _, j, seq = cands[0]
            cur = seq; load += dem[j]; unassigned.discard(j)
        trips.append(cur)
    return trips


def time_slice(ctx, rng=None, jitter=30.0):
    C = list(ctx.inst.customers)
    e, l, dem = ctx.e, ctx.l, ctx.dem
    jit = {c: (rng.uniform(0.0, jitter) if rng else 0.0) for c in C}
    trips = []
    for p in ctx.inst.satellites:
        cs = sorted([c for c in C if ctx.hub_of[c] == p], key=lambda c: (e[c] + l[c]) / 2 + jit[c])
        cur, load = [], 0.0
        for c in cs:
            if cur and (load + dem[c] > Q or len(cur) == MAXLEN or ctx.best_order(cur + [c]) is None):
                trips.append(ctx.best_order(cur)[1]); cur, load = [], 0.0
            cur.append(c); load += dem[c]
        if cur:
            trips.append(ctx.best_order(cur)[1])
    return trips


def score(ctx, trips):
    tot = dict(trips=len(trips), wait=0.0, travel=0.0, busy=0.0, infeasible=0)
    for seq in trips:
        r = ctx.latest_start_eval(seq)
        if r is None:
            tot["infeasible"] += 1; continue
        tot["wait"] += r["wait"]; tot["travel"] += r["travel"]; tot["busy"] += r["busy"]
    return tot


def incumbent_trips(ctx, sol):
    tset = {int(x) for x in sol["vi"]}
    hub = {int(t): int(h) for t, h in zip(sol["vi"], sol["hubs"])}
    trips, cur = [], []
    for r in routes_from_arcs(sol["xij"], set(ctx.inst.customers)):
        for c in r:
            cur.append(c)
            if c in tset:
                trips.append(list(cur)); cur = []
    # score with the incumbent's own hubs
    saved = dict(ctx.hub_of)
    for t in trips:
        ctx.hub_of[t[-1]] = hub[t[-1]]
    sc = score(ctx, trips)
    ctx.hub_of = saved
    return trips, sc


def main():
    cells = sys.argv[1].split(",") if len(sys.argv) > 1 else CELLS
    print("PRE-CLUSTERING TRIP-WISE vs THE INCUMBENT'S TRIPS (trip level: intrinsic waiting at latest start, travel to hub, busy time)\n")
    print("  %-6s | %5s %7s %7s %7s | %5s %7s %7s %7s %4s | %5s %7s %7s %7s %4s" % (
        "cell", "incT", "wait", "travel", "busy", "prioT", "wait", "travel", "busy", "inf", "tsT", "wait", "travel", "busy", "inf"))
    rows = []
    for cell in cells:
        inst = V.load_instance(cell, 100, 0.1); ctx = Ctx(inst)
        sol = json.load(io.open(os.path.join(ROOT, "runs", "grid", "g_%s_n100_p0.1_s0.json" % cell), encoding="utf-8"))
        _, inc = incumbent_trips(ctx, sol)
        pr = score(ctx, prio_st(ctx)); ts = score(ctx, time_slice(ctx))
        rows.append(dict(cell=cell, inc=inc, prio=pr, ts=ts))
        print("  %-6s | %5d %7.0f %7.0f %7.0f | %5d %7.0f %7.0f %7.0f %4d | %5d %7.0f %7.0f %7.0f %4d" % (
            cell, inc["trips"], inc["wait"], inc["travel"], inc["busy"], pr["trips"], pr["wait"], pr["travel"], pr["busy"], pr["infeasible"],
            ts["trips"], ts["wait"], ts["travel"], ts["busy"], ts["infeasible"]), flush=True)
    def summ(key):
        d_busy = [100 * (r[key]["busy"] - r["inc"]["busy"]) / r["inc"]["busy"] for r in rows]
        d_trav = [100 * (r[key]["travel"] - r["inc"]["travel"]) / r["inc"]["travel"] for r in rows]
        d_wait = [100 * (r[key]["wait"] - r["inc"]["wait"]) / max(1, r["inc"]["wait"]) for r in rows]
        d_trip = [r[key]["trips"] - r["inc"]["trips"] for r in rows]
        return ("busy %+.1f%% median (better on %d/%d) | travel %+.1f%% | waiting %+.1f%% | trips %+.1f | infeasible trips total %d"
                % (st.median(d_busy), sum(1 for x in d_busy if x < 0), len(rows), st.median(d_trav), st.median(d_wait), st.mean(d_trip), sum(r[key]["infeasible"] for r in rows)))
    print("\n  PRIO-ST vs incumbent:    " + summ("prio"))
    print("  TIME-SLICE vs incumbent: " + summ("ts"))
    print("\n  busy time is the fleet driver (sum of trip durations over the horizon); travel is the objective driver.")
    json.dump(rows, io.open(os.path.join(S, "precluster_trips.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()


def full_pack(ctx, close=CLOSE, maxlen=5, rng=None, jitter=30.0):
    """FULL-PACK (d354): fill-first composition -- largest feasible load first, then busy, then
    travel; up to 5 customers so capacity, not the length cap, ends a trip. Reaches the capacity
    minimum of transfers on every C cell at the price of waiting."""
    C = list(ctx.inst.customers)
    D, e, l, dem = ctx.D, ctx.e, ctx.l, ctx.dem
    jit = {c: (rng.uniform(0.0, jitter) if rng else 0.0) for c in C}
    order = sorted(C, key=lambda c: (l[c] - e[c] + jit[c], -dem[c]))
    un = set(C)
    trips = []
    for seed in order:
        if seed not in un:
            continue
        un.discard(seed)
        cur, load = [seed], dem[seed]
        while len(cur) < maxlen:
            best = None
            for j in un:
                if load + dem[j] > Q or min(D[c][j] for c in cur) > 2 * close:
                    continue
                b = ctx.best_order(cur + [j])
                if b is None:
                    continue
                key = (-dem[j], b[0][0], b[0][1])
                if best is None or key < best[0]:
                    best = (key, j, b[1])
            if best is None:
                break
            _, j, seq = best
            cur, load = seq, load + dem[j]
            un.discard(j)
        trips.append(cur)
    return trips
