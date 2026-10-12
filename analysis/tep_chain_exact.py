"""TEP refinement 1 -- the exact chaining layer (d373 design).

The joint chaining MILP (assemble_precluster.chain) decides hubs, transfer times, booking and
car chains together and hits its work limit on every n100 cell with bounds far from the
incumbent. Decoupled:

  A. BOOKING: hub choice h[r,p] and transfer time u[r] only -- vessel-arrival bound, CDC return,
     depot-return margin, same-hub separation >= tau (indicators). Objective: hub-leg travel +
     the waiting the booking forces (u - earliest arrival), so transfers are booked as early as
     the slots allow, which keeps the most chains feasible. Hundreds of binaries, seconds.
  B. CHAINING given (p_r, u_r): a trip's latest start is fixed by u_r (backward pass); the car
     can follow r with q iff u_r + tau + D[p_r][first_q] <= latest_start_q. Min-cost path cover
     on that DAG = one assignment: end-of-r -> start-of-q at the leg cost, end-of-r -> dummy at
     the return leg, dummy -> start-of-q at penalty_cars + depot leg. Hungarian, milliseconds,
     exact for the given booking.

Trip feasibility inside a chain: the car leaves hub p_r at u_r + tau and must reach q's first
customer by q's latest start (q then serves its customers in order, waits where needed, and
reaches p_q by u_q -- the backward pass guarantees it). Same decode/re-timing/verification as
the joint pipeline.

    python analysis/tep_chain_exact.py [cells] [compositions]   # street-level comparison only
"""
import io
import json
import os
import sys
import time

import numpy as np
from scipy.optimize import linear_sum_assignment
import gurobipy as gp
from gurobipy import GRB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from precluster_trips import Ctx, prio_st, time_slice, full_pack
from assemble_precluster import chain as chain_joint


def trip_times(ctx, seq):
    """(earliest start, latest start ignoring the hub, service-start times at earliest start,
    time of arrival at the last customer's END at earliest start)."""
    D, e, l, sv = ctx.D, ctx.e, ctx.l, ctx.sv
    lat = l[seq[-1]]
    for a, b in zip(reversed(seq[:-1]), reversed(seq[1:])):
        lat = min(l[a], lat - sv[a] - D[a][b])
    es = e[seq[0]]
    t = es
    for i, c in enumerate(seq):
        if i:
            t += sv[seq[i - 1]] + D[seq[i - 1]][c]
        t = max(t, e[c])
    end_e = t + sv[seq[-1]]                  # leave the last customer, at the earliest start
    return es, max(lat, es), end_e


def book(inst, ctx, trips, cap=30.0, seed=0):
    nd, D, tau, depot, CDC = inst.nodes, inst.D, float(inst.tau), inst.depot, inst.CDC
    sats = list(inst.satellites)
    H0, H1 = float(nd[depot].earliest), float(nd[depot].latest)
    tc = float(inst.travelcoststreet)
    R = range(len(trips))
    tt = [trip_times(ctx, t) for t in trips]
    M = (H1 - H0) + max(max(row) for row in D)
    m = gp.Model("book"); m.Params.OutputFlag = 0; m.Params.Threads = 1; m.Params.TimeLimit = cap; m.Params.Seed = seed
    h = {(r, p): m.addVar(vtype=GRB.BINARY) for r in R for p in sats}
    u = {r: m.addVar(lb=H0, ub=H1) for r in R}
    wait = {r: m.addVar(lb=0.0) for r in R}
    for r in R:
        es, ls, end_e = tt[r]; last = trips[r][-1]; first = trips[r][0]
        m.addConstr(gp.quicksum(h[r, p] for p in sats) == 1)
        # earliest possible arrival at the chosen hub; the slack above it is waiting
        arr_e = gp.quicksum(h[r, p] * (end_e + D[last][p]) for p in sats)
        m.addConstr(u[r] >= arr_e)
        m.addConstr(wait[r] >= u[r] - arr_e)
        # latest: the trip can start no later than ls, so it reaches the hub no later than ls + (end_e - es) + leg
        m.addConstr(u[r] <= ls + (end_e - es) + gp.quicksum(h[r, p] * D[last][p] for p in sats))
        m.addConstr(u[r] >= H0 + gp.quicksum(h[r, p] * D[CDC][p] for p in sats))
        m.addConstr(u[r] + tau + gp.quicksum(h[r, p] * D[p][depot] for p in sats) <= H1)
        m.addConstr(u[r] + tau + gp.quicksum(h[r, p] * D[p][CDC] for p in sats) <= float(nd[CDC].latest))
        for c in trips[r]:
            pass  # depot-return margin per customer is implied by u <= H1 - tau - D[p][depot] for the last; kept in re-timing
    for r in R:
        for q in R:
            if q > r:
                for p in sats:
                    o = m.addVar(vtype=GRB.BINARY); both = m.addVar(vtype=GRB.BINARY)
                    m.addConstr(both >= h[r, p] + h[q, p] - 1)
                    m.addConstr(u[q] >= u[r] + tau - M * (1 - o) - M * (1 - both))
                    m.addConstr(u[r] >= u[q] + tau - M * o - M * (1 - both))
    m.setObjective(tc * gp.quicksum(h[r, p] * D[trips[r][-1]][p] for r in R for p in sats) + 0.05 * tc * gp.quicksum(wait[r] for r in R), GRB.MINIMIZE)
    t0 = time.time(); m.optimize()
    if m.SolCount == 0:
        return None
    hub = {r: next(p for p in sats if h[r, p].X > 0.5) for r in R}
    return dict(hub=hub, u={r: u[r].X for r in R}, status=m.Status, secs=time.time() - t0, work=m.Work, tt=tt)


def cover(inst, ctx, trips, bk):
    """Exact min-cost path cover given the booking: one assignment."""
    D, tau, depot = inst.D, float(inst.tau), inst.depot
    pen, tc = float(inst.penalty_cars), float(inst.travelcoststreet)
    n = len(trips); INF = 1e9
    hub, u, tt = bk["hub"], bk["u"], bk["tt"]
    # latest start of each trip so that it reaches its booked hub by u: ls_hub = min(ls, u - (end_e - es) - leg)
    ls_hub = {r: min(tt[r][1], u[r] - (tt[r][2] - tt[r][0]) - D[trips[r][-1]][hub[r]]) for r in range(n)}
    C = np.full((2 * n, 2 * n), INF)
    for r in range(n):
        for q in range(n):
            if r != q and u[r] + tau + D[hub[r]][trips[q][0]] <= ls_hub[q] + 1e-9:
                C[r, q] = tc * D[hub[r]][trips[q][0]]
        C[r, n + r] = tc * D[hub[r]][depot]                       # end of r -> return to depot (dummy col)
        C[n + r, r] = pen + tc * D[depot][trips[r][0]]            # new car -> start of r (dummy row)
    for i in range(n):
        for j in range(n):
            C[n + i, n + j] = 0.0                                  # dummy -> dummy
    rows, cols = linear_sum_assignment(C)
    total = float(C[rows, cols].sum())
    succ = {}
    starts = []
    for r, c in zip(rows, cols):
        if r < n and c < n: succ[r] = c
        if r >= n and c < n: starts.append(c)
    chains = []
    for s in starts:
        ch = [s]
        while ch[-1] in succ: ch.append(succ[ch[-1]])
        chains.append(ch)
    internal = sum(tc * (sum(D[a][b] for a, b in zip(t, t[1:])) + D[t[-1]][hub[i]]) for i, t in enumerate(trips))
    return dict(chains=chains, cars=len(chains), street=total + internal, hub=hub, u=u)


def chain_exact(inst, ctx, trips, seed=0):
    bk = book(inst, ctx, trips, seed=seed)
    if bk is None:
        return None
    cv = cover(inst, ctx, trips, bk)
    cv.update(book_status=bk["status"], book_secs=bk["secs"], book_work=bk["work"])
    return cv


def main():
    cells = sys.argv[1].split(",") if len(sys.argv) > 1 else ["R204", "RC204", "C204"]
    comps = sys.argv[2].split(",") if len(sys.argv) > 2 else ["prio", "ts"]
    F = {"prio": prio_st, "ts": time_slice, "fp": full_pack}
    print("TEP exact chaining (booking MILP + assignment path cover) vs the joint chaining MILP (work limit 30), street level\n")
    print("  %-5s %-4s %5s | %6s %9s %6s | %6s %9s %7s %7s" % ("cell", "comp", "trips", "jCars", "jStreet", "jSecs", "xCars", "xStreet", "bookS", "status"))
    for cell in cells:
        inst = V.load_instance(cell, 100, 0.1); ctx = Ctx(inst)
        for name in comps:
            trips = F[name](ctx)
            t0 = time.time(); j = chain_joint(inst, trips, cap=120.0, work=30.0); js = time.time() - t0
            x = chain_exact(inst, ctx, trips)
            print("  %-5s %-4s %5d | %6s %9s %6.0f | %6s %9s %7.1f %7s" % (
                cell, name, len(trips), j["cars"] if j else "-", ("%.1f" % j["street"]) if j else "-", js,
                x["cars"] if x else "-", ("%.1f" % x["street"]) if x else "-", x["book_secs"] if x else 0, x["book_status"] if x else "-"), flush=True)


if __name__ == "__main__":
    main()
