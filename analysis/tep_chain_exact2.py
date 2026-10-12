"""TEP refinement, iteration 2 (d373): chain first with free times and NO booking, then book as
a repair under the chains' precedences, looping on conflicts.

  CHAIN (MILP, Gurobi): the joint model of assemble_precluster.chain minus the same-hub
    separation pairs -- hubs h[r,p], times a/s/u, chaining y/z, vessel-arrival and return bounds,
    objective = cars + street travel. Without the 4 x C(n,2) indicator pairs it is a much
    smaller model; with a work limit it is still not proven, but the bound is the cars' bound.
  BOOK (MILP, tiny): keep the chains; variables u[r] and hubs fixed from CHAIN (or re-chosen);
    constraints: for consecutive trips r -> q in a chain, u_q >= u_r + tau + D[p_r][first_q] +
    (duration of q from its first customer to its hub, at the latest-start timing) ... i.e. the
    chain's own time propagation, plus windows via each trip's [earliest, latest] hub-arrival
    interval, plus same-hub separation (indicators). Objective: total shift from CHAIN's u.
  LOOP: if BOOK is infeasible, the conflicting hub pair (r, q at the same hub with overlapping
    forced windows) is forbidden in CHAIN (h[r,p] + h[q,p] <= 1 for that p, or a no-good on the
    chain arc) and CHAIN re-solves. At most `max_iter` rounds.

Street-level only here (no re-timing / verification): compare with the joint MILP's cars and
street cost at the same work limit.
"""
import io
import json
import os
import sys
import time

import gurobipy as gp
from gurobipy import GRB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from precluster_trips import Ctx, prio_st, time_slice, full_pack
from assemble_precluster import chain as chain_joint


def chain_free(inst, trips, forbid, work=30.0, cap=120.0, seed=0):
    """assemble_precluster.chain without the booking pairs; `forbid` = set of (r, q, p): r and q
    may not both use hub p."""
    nd, D, tau, depot, CDC = inst.nodes, inst.D, float(inst.tau), inst.depot, inst.CDC
    sats = list(inst.satellites)
    H0, H1 = float(nd[depot].earliest), float(nd[depot].latest)
    pen, tc = float(inst.penalty_cars), float(inst.travelcoststreet)
    R = range(len(trips)); M = (H1 - H0) + max(max(row) for row in D)
    m = gp.Model("chain_free"); m.Params.OutputFlag = 0; m.Params.Threads = 1; m.Params.TimeLimit = cap; m.Params.Seed = seed
    if work: m.Params.WorkLimit = work
    a = {c: m.addVar(lb=float(nd[c].earliest), ub=float(nd[c].latest)) for t in trips for c in t}
    u = {r: m.addVar(lb=H0, ub=H1) for r in R}; s = {r: m.addVar(lb=H0, ub=H1) for r in R}
    h = {(r, p): m.addVar(vtype=GRB.BINARY) for r in R for p in sats}
    y = {(r, q): m.addVar(vtype=GRB.BINARY) for r in R for q in R if r != q}
    yd = {r: m.addVar(vtype=GRB.BINARY) for r in R}; ye = {r: m.addVar(vtype=GRB.BINARY) for r in R}
    z = {(r, q, p): m.addVar(vtype=GRB.BINARY) for (r, q) in y for p in sats}
    for (r, q) in y:
        for p in sats:
            m.addConstr(z[r, q, p] <= y[r, q]); m.addConstr(z[r, q, p] <= h[r, p]); m.addConstr(z[r, q, p] >= y[r, q] + h[r, p] - 1)
    internal = {}
    for r in R:
        cs = trips[r]
        m.addConstr(gp.quicksum(h[r, p] for p in sats) == 1)
        m.addConstr(yd[r] + gp.quicksum(y[q, r] for q in R if q != r) == 1)
        m.addConstr(ye[r] + gp.quicksum(y[r, q] for q in R if q != r) == 1)
        m.addConstr(a[cs[0]] >= s[r] + yd[r] * D[depot][cs[0]] + gp.quicksum(z[q, r, p] * D[p][cs[0]] for q in R if q != r for p in sats))
        tot = 0.0
        for c1, c2 in zip(cs, cs[1:]):
            m.addConstr(a[c2] >= a[c1] + float(nd[c1].service) + D[c1][c2]); tot += D[c1][c2]
        last = cs[-1]
        m.addConstr(u[r] >= a[last] + float(nd[last].service) + gp.quicksum(h[r, p] * D[last][p] for p in sats))
        m.addConstr(u[r] >= H0 + gp.quicksum(h[r, p] * D[CDC][p] for p in sats))
        m.addConstr(u[r] + tau + gp.quicksum(h[r, p] * D[p][depot] for p in sats) <= H1)
        m.addConstr(u[r] + tau + gp.quicksum(h[r, p] * D[p][CDC] for p in sats) <= float(nd[CDC].latest))
        for c in cs:
            m.addConstr(a[c] <= H1 - D[c][depot] - float(nd[c].service) - tau)
        internal[r] = tot
        for q in R:
            if q != r:
                m.addConstr(s[q] >= u[r] + tau - M * (1 - y[r, q]))
    for (r, q, p) in forbid:
        m.addConstr(h[r, p] + h[q, p] <= 1)
    cost = (pen * gp.quicksum(yd[r] for r in R)
            + tc * (gp.quicksum(internal[r] for r in R) + gp.quicksum(h[r, p] * D[trips[r][-1]][p] for r in R for p in sats)
                    + gp.quicksum(yd[r] * D[depot][trips[r][0]] for r in R) + gp.quicksum(z[r, q, p] * D[p][trips[q][0]] for (r, q, p) in z)
                    + gp.quicksum(ye[r] * gp.quicksum(h[r, p] * D[p][depot] for p in sats) for r in R)))
    m.setObjective(cost, GRB.MINIMIZE)
    t0 = time.time(); m.optimize()
    if m.SolCount == 0: return None
    succ = {r: q for (r, q) in y if y[r, q].X > 0.5}
    chains = []
    for r in R:
        if yd[r].X > 0.5:
            ch = [r]
            while ch[-1] in succ: ch.append(succ[ch[-1]])
            chains.append(ch)
    hub = {r: next(p for p in sats if h[r, p].X > 0.5) for r in R}
    return dict(chains=chains, hub=hub, u={r: u[r].X for r in R}, a={c: a[c].X for c in a}, street=m.ObjVal, bound=m.ObjBound, secs=time.time() - t0, status=m.Status)


def book_repair(inst, ctx, trips, res, cap=30.0):
    """Keep chains and hubs; choose u (and the trips' service starts) to satisfy same-hub
    separation with minimum total shift from CHAIN's u. Returns (u, shift) or None."""
    nd, D, tau, depot, CDC = inst.nodes, inst.D, float(inst.tau), inst.depot, inst.CDC
    H0, H1 = float(nd[depot].earliest), float(nd[depot].latest)
    R = range(len(trips)); hub = res["hub"]; M = (H1 - H0) + max(max(row) for row in D)
    m = gp.Model("book"); m.Params.OutputFlag = 0; m.Params.Threads = 1; m.Params.TimeLimit = cap
    a = {c: m.addVar(lb=float(nd[c].earliest), ub=float(nd[c].latest)) for t in trips for c in t}
    u = {r: m.addVar(lb=H0, ub=H1) for r in R}; dev = {r: m.addVar(lb=0.0) for r in R}
    for ch in res["chains"]:
        prev = None
        for r in ch:
            cs = trips[r]
            if prev is None:
                m.addConstr(a[cs[0]] >= H0 + D[depot][cs[0]])
            else:
                m.addConstr(a[cs[0]] >= u[prev] + tau + D[hub[prev]][cs[0]])
            for c1, c2 in zip(cs, cs[1:]):
                m.addConstr(a[c2] >= a[c1] + float(nd[c1].service) + D[c1][c2])
            last = cs[-1]
            m.addConstr(u[r] >= a[last] + float(nd[last].service) + D[last][hub[r]])
            m.addConstr(u[r] >= H0 + D[CDC][hub[r]])
            m.addConstr(u[r] + tau + D[hub[r]][depot] <= H1)
            m.addConstr(u[r] + tau + D[hub[r]][CDC] <= float(nd[CDC].latest))
            for c in cs:
                m.addConstr(a[c] <= H1 - D[c][depot] - float(nd[c].service) - tau)
            m.addConstr(dev[r] >= u[r] - res["u"][r]); m.addConstr(dev[r] >= res["u"][r] - u[r])
            prev = r
    for r in R:
        for q in R:
            if q > r and hub[r] == hub[q]:
                o = m.addVar(vtype=GRB.BINARY)
                m.addConstr(u[q] >= u[r] + tau - M * (1 - o)); m.addConstr(u[r] >= u[q] + tau - M * o)
    m.setObjective(gp.quicksum(dev[r] for r in R), GRB.MINIMIZE)
    m.optimize()
    if m.SolCount == 0:
        return None
    return {r: u[r].X for r in R}, m.ObjVal


def conflicts(inst, trips, res):
    """Same-hub pairs whose forced hub-arrival windows cannot be tau apart -- the no-goods."""
    tau = float(inst.tau); hub = res["hub"]; out = set()
    # crude: pairs at the same hub with |u_r - u_q| < tau in CHAIN's solution
    R = range(len(trips))
    for r in R:
        for q in R:
            if q > r and hub[r] == hub[q] and abs(res["u"][r] - res["u"][q]) < tau - 1e-6:
                out.add((r, q, hub[r]))
    return out


def chain_exact2(inst, ctx, trips, work=30.0, max_iter=6):
    forbid = set(); hist = []
    for it in range(max_iter):
        res = chain_free(inst, trips, forbid, work=work)
        if res is None: return None, hist
        rep = book_repair(inst, ctx, trips, res)
        hist.append(dict(it=it, cars=res["cars"] if "cars" in res else len(res["chains"]), street=res["street"], bound=res["bound"], secs=round(res["secs"], 1), booked=rep is not None, shift=(rep[1] if rep else None), forbid=len(forbid)))
        if rep is not None:
            res["u"] = rep[0]; res["cars"] = len(res["chains"]); return res, hist
        new = conflicts(inst, trips, res)
        if not new - forbid:
            return None, hist
        forbid |= new
    return None, hist


def main():
    cells = sys.argv[1].split(",") if len(sys.argv) > 1 else ["R204", "RC204", "C204"]
    comps = sys.argv[2].split(",") if len(sys.argv) > 2 else ["prio", "ts"]
    F = {"prio": prio_st, "ts": time_slice, "fp": full_pack}
    print("TEP exact chaining, iteration 2: chain free of booking -> book repair -> no-good loop; vs joint (work 30)\n")
    for cell in cells:
        inst = V.load_instance(cell, 100, 0.1); ctx = Ctx(inst)
        for name in comps:
            trips = F[name](ctx)
            t0 = time.time(); j = chain_joint(inst, trips, cap=120.0, work=30.0); js = time.time() - t0
            t0 = time.time(); x, hist = chain_exact2(inst, ctx, trips); xs = time.time() - t0
            print("  %-5s %-4s %2d trips | joint: %d cars, street %.1f (bound %.1f, %.0fs) | iter2: %s cars, street %s (%.0fs, %d rounds%s)" % (
                cell, name, len(trips), j["cars"], j["street"], j["bound"], js,
                x["cars"] if x else "-", ("%.1f" % x["street"]) if x else "-", xs, len(hist), (", shift %.0f" % hist[-1]["shift"]) if hist and hist[-1]["shift"] is not None else ""), flush=True)
            for hrow in hist: print("        ", hrow)


if __name__ == "__main__":
    main()
