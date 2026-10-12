"""SELECT the trips and CHAIN them in one model, with the CAR COUNT as the primary objective.

THE AUTHOR'S PROPOSAL, AND WHY THE DIAGNOSIS SAYS IT IS THE RIGHT ONE. Today's pipeline is strictly
sequential: the master IP picks a partition on bucketed street plus a floor-rounded fleet term,
`chain()` is then handed THOSE trips and must use ALL of them, and the water stage runs last on
whatever it is given. So the car count is minimised only WITHIN a partition that was chosen on
street grounds. That is exactly why capping the chaining at two cars on R201 was infeasible six
times over (d461) while the proven LP says two cars is admissible: no partition we generate is
chainable at two, and re-selecting from the same pool cannot help.

Inverting the search means letting the model CHOOSE which trips to use, subject to covering every
customer once, with cars lexicographically first. That is what this does.

WHY THE POOL IS SMALL ON PURPOSE. The union of the floor and ceil partitions is about 30 trips, so
the pairwise chaining variables stay in the thousands and the model solves. Starting there is the
cheap falsifier: if a two-car solution exists among trips we ALREADY hold, the defect is selection
and this fixes it outright. If it does not, the defect is that we never priced the right trips, and
the next move is the pricer -- a much larger piece of work that should not be started on a guess.

THE MODELLING CARE THIS NEEDS. `a[c]` is one variable per customer, shared by every candidate trip
containing c, so an unselected trip's precedence chain would otherwise still bind. Every trip-level
constraint is therefore conditioned on its selection variable, by equality on the degree and hub
rows and by big-M on the timing rows. Constraints that are valid for a customer regardless of which
trip serves it -- the depot-return margin -- stay unconditional, because they are.

    python analysis/tep_select_chain.py R201 RC202 --size 30
"""
import argparse
import io
import json
import os
import sys
import time

import gurobipy as gp
from gurobipy import GRB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity, k_best_incumbent
from tep_force_fleet import build
from stamp import stamped

LAST = {}   # status of the most recent solve, so callers can tell INFEASIBLE from a timeout


def select_chain(inst, trips, cap=900.0, work=None, max_cars=None, min_cars=False, seed=0, prune_at=None):
    """Joint trip selection + chaining. Returns a chain()-shaped dict over the SELECTED trips."""
    nd, D, tau, depot, CDC = inst.nodes, inst.D, float(inst.tau), inst.depot, inst.CDC
    sats = list(inst.satellites)
    H0, H1 = float(nd[depot].earliest), float(nd[depot].latest)
    pen, tc = float(inst.penalty_cars), float(inst.travelcoststreet)
    R = range(len(trips))
    BIG = (H1 - H0) + max(max(row) for row in D)
    m = gp.Model("selchain"); m.Params.OutputFlag = 0; m.Params.Threads = 1
    m.Params.TimeLimit = cap; m.Params.Seed = int(seed)
    if work:
        m.Params.WorkLimit = float(work)

    x = {r: m.addVar(vtype=GRB.BINARY) for r in R}
    cust = sorted({c for t in trips for c in t})
    for c in cust:                                   # exact cover
        m.addConstr(gp.quicksum(x[r] for r in R if c in trips[r]) == 1)

    a = {c: m.addVar(lb=float(nd[c].earliest), ub=float(nd[c].latest)) for c in cust}
    u = {r: m.addVar(lb=H0, ub=H1) for r in R}
    s = {r: m.addVar(lb=H0, ub=H1) for r in R}
    h = {(r, p): m.addVar(vtype=GRB.BINARY) for r in R for p in sats}
    y = {(r, q): m.addVar(vtype=GRB.BINARY) for r in R for q in R if r != q}
    yd = {r: m.addVar(vtype=GRB.BINARY) for r in R}
    ye = {r: m.addVar(vtype=GRB.BINARY) for r in R}
    z = {(r, q, p): m.addVar(vtype=GRB.BINARY) for (r, q) in y for p in sats}
    for (r, q) in y:
        m.addConstr(y[r, q] <= x[r]); m.addConstr(y[r, q] <= x[q])
        for p in sats:
            m.addConstr(z[r, q, p] <= y[r, q]); m.addConstr(z[r, q, p] <= h[r, p])
            m.addConstr(z[r, q, p] >= y[r, q] + h[r, p] - 1)

    internal = {}
    for r in R:
        cs = trips[r]
        m.addConstr(gp.quicksum(h[r, p] for p in sats) == x[r])
        m.addConstr(yd[r] + gp.quicksum(y[q, r] for q in R if q != r) == x[r])
        m.addConstr(ye[r] + gp.quicksum(y[r, q] for q in R if q != r) == x[r])
        m.addConstr(a[cs[0]] >= s[r] + yd[r] * D[depot][cs[0]]
                    + gp.quicksum(z[q, r, p] * D[p][cs[0]] for q in R if q != r for p in sats)
                    - BIG * (1 - x[r]))
        tot = 0.0
        for c1, c2 in zip(cs, cs[1:]):
            m.addConstr(a[c2] >= a[c1] + float(nd[c1].service) + D[c1][c2] - BIG * (1 - x[r]))
            tot += D[c1][c2]
        last = cs[-1]
        m.addConstr(u[r] >= a[last] + float(nd[last].service)
                    + gp.quicksum(h[r, p] * D[last][p] for p in sats) - BIG * (1 - x[r]))
        m.addConstr(u[r] >= H0 + gp.quicksum(h[r, p] * D[CDC][p] for p in sats))
        m.addConstr(u[r] + tau + gp.quicksum(h[r, p] * D[p][depot] for p in sats) <= H1 + BIG * (1 - x[r]))
        m.addConstr(u[r] + tau + gp.quicksum(h[r, p] * D[p][CDC] for p in sats)
                    <= float(nd[CDC].latest) + BIG * (1 - x[r]))
        internal[r] = tot
        for q in R:
            if q != r:
                m.addConstr(s[q] >= u[r] + tau - BIG * (1 - y[r, q]))
    for c in cust:                                   # valid whichever trip serves c
        m.addConstr(a[c] <= H1 - D[c][depot] - float(nd[c].service) - tau)
    for r in R:                                      # tau-spacing when two trips share a hub
        for q in R:
            if q > r:
                for p in sats:
                    o = m.addVar(vtype=GRB.BINARY); both = m.addVar(vtype=GRB.BINARY)
                    m.addConstr(both <= h[r, p]); m.addConstr(both <= h[q, p])
                    m.addConstr(both >= h[r, p] + h[q, p] - 1)
                    m.addConstr(u[q] >= u[r] + tau - BIG * (1 - o) - BIG * (1 - both))
                    m.addConstr(u[r] >= u[q] + tau - BIG * o - BIG * (1 - both))

    cars = gp.quicksum(yd[r] for r in R)
    street = (gp.quicksum(internal[r] * x[r] for r in R)
              + gp.quicksum(h[r, p] * D[trips[r][-1]][p] for r in R for p in sats)
              + gp.quicksum(yd[r] * D[depot][trips[r][0]] for r in R)
              + gp.quicksum(z[r, q, p] * D[p][trips[q][0]] for (r, q, p) in z)
              + gp.quicksum(ye[r] * gp.quicksum(h[r, p] * D[p][depot] for p in sats) for r in R))
    if max_cars is not None:
        m.addConstr(cars <= int(max_cars))
    t0 = time.time()
    if prune_at is not None:
        # LP-pruning guard (PREREG_uniform_pipeline S4): the relaxation of the cost objective over THIS pool is a valid
        # lower bound on the street+fleet cost of any selection from it. If it already reaches prune_at (banked total
        # minus a valid water floor), no selection can beat the incumbent and the MIP is skipped -- a proof, not a heuristic.
        m.setObjective(pen * cars + tc * street, GRB.MINIMIZE); m.update()
        rel = m.relax(); rel.Params.OutputFlag = 0; rel.Params.Threads = 1; rel.optimize()
        lp = float(rel.ObjVal) if rel.Status == GRB.OPTIMAL else None
        LAST["lp_relax"] = lp; LAST["prune_at"] = float(prune_at); LAST["lp_secs"] = round(time.time() - t0, 2)
        if lp is not None and (prune_at == float("inf") or lp >= float(prune_at) - 1e-6):   # inf = lp-only check mode: always return here
            LAST["status"] = "pruned"
            return dict(pruned=True, lp=lp, prune_at=float(prune_at), secs=time.time() - t0)
    if min_cars:
        # PHASE 1: the inversion -- cars are the objective, not a penalty term.
        m.setObjective(cars, GRB.MINIMIZE); m.optimize()
        LAST['phase1_status'] = m.Status; LAST['phase1_bound'] = m.ObjBound
        if m.SolCount == 0:
            return None
        k = int(round(m.ObjVal))
        m.addConstr(cars <= k)                       # PHASE 2: street, at the proven fleet
        m.setObjective(pen * cars + tc * street, GRB.MINIMIZE)
        if work:
            m.Params.WorkLimit = float(work)
        m.Params.TimeLimit = max(1.0, cap - (time.time() - t0))
        m.optimize()
    else:
        m.setObjective(pen * cars + tc * street, GRB.MINIMIZE); m.optimize()
    LAST['status'] = m.Status; LAST['bound'] = m.ObjBound; LAST['work'] = m.Work
    if m.SolCount == 0:
        return None
    sel = [r for r in R for _ in (0,) if x[r].X > 0.5]
    idx = {r: i for i, r in enumerate(sel)}
    succ = {r: q for (r, q) in y if y[r, q].X > 0.5}
    chains = []
    for r in sel:
        if yd[r].X > 0.5:
            ch = [r]
            while ch[-1] in succ:
                ch.append(succ[ch[-1]])
            chains.append([idx[t] for t in ch])
    sub = [trips[r] for r in sel]
    return dict(trips=sub, cars=len(chains), street=m.ObjVal, secs=time.time() - t0,
                chains=chains, hub={idx[r]: next(p for p in sats if h[r, p].X > 0.5) for r in sel},
                status=m.Status, a={c: a[c].X for c in cust},
                s={idx[r]: s[r].X for r in sel}, u={idx[r]: u[r].X for r in sel},
                gurobi=dict(status=m.Status, obj=m.ObjVal, bound=m.ObjBound, work_used=m.Work,
                            nodes=m.NodeCount, secs=time.time() - t0, threads=1, seed=seed,
                            time_limit=cap, work_limit=work))


def wide_pool(cell, size, prox, limit=70, primal=False):
    """S4: widen the pool with columns the LP likes, not only the two IP partitions.

    The IP partitions are ~30 trips and the select+chain model proved 3 cars minimal over them on
    RC202 (d461, and the S2 sweep). That is a statement about the POOL. The master holds thousands
    of priced columns; the ones with positive LP value are the fractional optimum's own support and
    are the natural next tier. Capped at `limit` because the chaining variables are pairwise.
    """
    import tep_cg_bound as T
    import verifier3 as _V
    inst = _V.load_instance(cell, size, prox)
    r = T.run(cell, T.default_delta(inst), 400, ["prio", "ts"], 10, 1000, False, 3_000_000,
              size=size, start_states=True, proximity=prox, return_master=True, max_secs=420.0,
              primal=primal)
    M = r["master"]
    vals = []
    for k, v in M.cols.items():
        try:
            xv = float(v.X)
        except Exception:
            continue
        if xv > 1e-6:
            vals.append((xv, list(k[0])))
    vals.sort(key=lambda t: -t[0])
    return [t for _, t in vals[:limit]]



def pool_master_lp(inst, pool):
    """A VALID lower bound over the pool that is cheap: the floor-bucketed TEP master restricted to the pool trips,
    every (start, hub, bucket) variant of each. Floor bucketing relaxes continuous time (d414) and the master keeps
    the fleet term continuous, so no selection+chaining over this pool can cost less. ~1-3k columns, sub-second.
    The big-M relaxation of the select+chain model itself is useless for this (RC201 n20: 148.8 against a banked 992.0)."""
    import tep_cg_bound as T
    M = T.Master(inst, T.default_delta(inst), primal=False)
    for seq in pool:
        for (L, b, p, ba) in M.variants(list(seq)):
            M.add_column(list(seq), L, b, p, ba)
    M.m.update(); M.m.optimize()
    if M.m.Status != 2:
        return None
    if any(v.X > 1e-9 for v in M.slack.values()):      # a customer no pool variant can cover: not a bound on anything
        return None
    return float(M.m.ObjVal)

def pool_for(cell, size):
    """Candidate trips: the union of the floor and ceil master-IP partitions, de-duplicated."""
    seen, pool, src = set(), [], {}
    for tag, suf in (("floor", ""), ("ceil", "_primal")):
        p = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s_ip%s.json"
                         % (cell, "" if size == 100 else "_n%d" % size, suf))
        if not os.path.exists(p):
            continue
        for t in json.load(io.open(p, encoding="utf-8"))["ip"]["trips"]:
            k = tuple(t)
            if k not in seen:
                seen.add(k); pool.append(list(t)); src[k] = tag
    return pool, src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="+"); ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--cap", type=float, default=900.0); ap.add_argument("--work", type=float, default=600.0)
    ap.add_argument("--max-cars", type=int, default=0,
                    help="HARD fleet cap as a constraint instead of the lexicographic car objective. The "
                         "RC202 proof run (2026-09-26) found a 2-car solution this way at 1307 s where "
                         "phase-1 car minimisation had returned 3 at its 901 s cap: same pool, same model, "
                         "a constraint prunes where an objective only guides.")
    ap.add_argument("--wide", type=int, default=0,
                    help="S4: add up to N LP-positive master columns to the pool (0 = IP partitions only)")
    ap.add_argument("--prune", action="store_true", help="LP-pruning guard: skip the MIP when the pool relaxation + water floor >= banked (PREREG_uniform_pipeline S4)")
    ap.add_argument("--lp-only", action="store_true", help="report the pool LP bound against banked and stop (guard check, no MIP)")
    ap.add_argument("--prune-master", action="store_true", help="guard by the pool-restricted floor-bucketed MASTER LP (valid, cheap) instead of the model relaxation")
    a = ap.parse_args()
    prox = k_proximity(a.size)
    out = []
    for cell in a.cells:
        inst = V.load_instance(cell, a.size, prox)
        kb, which = k_best_incumbent(cell, a.size)
        # d469: the incumbent is the MIN over EVERY production dir. Reading only floor+ceil let a
        # 1 s smoke "improve" R201 to 1209.6 against a stale 1212.1 while the forced artifact sat at
        # 1066.3 -- and would let a re-run overwrite a BETTER selchain artifact with a worse one.
        banked, src_path, cars_banked = None, None, None
        for sub in ("", "ceil", "selchain", "forced", "refine", "alns"):
            bp = os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, a.size))
            if os.path.exists(bp):
                bd = json.load(io.open(bp, encoding="utf-8"))
                v = float(bd["objVal"])
                if banked is None or v < banked:
                    banked = v
                    src_path = os.path.relpath(bp, ROOT)
                    cars_banked = int(bd["nCars"]) if bd.get("nCars") is not None else None
        pool, src = pool_for(cell, a.size)
        if a.wide:
            seen = {tuple(t) for t in pool}
            for pr in (False, True):
                for t in wide_pool(cell, a.size, prox, limit=a.wide, primal=pr):
                    if tuple(t) not in seen:
                        seen.add(tuple(t)); pool.append(t); src[tuple(t)] = "lp"
        ncust = len(list(inst.customers))
        cov = sorted({c for t in pool for c in t})
        print("\n%s n%d: pool %d trips (%d from floor, %d new from ceil), covering %d of %d customers"
              % (cell, a.size, len(pool), sum(1 for v in src.values() if v == "floor"),
                 sum(1 for v in src.values() if v == "ceil"), len(cov), ncust), flush=True)
        if len(cov) != ncust:
            print("  pool does not cover every customer -- cannot be a partition source")
            out.append(dict(cell=cell, pool=len(pool), failed="pool does not cover every customer", banked=banked, theirs=kb)); continue
        print("  banked %.3f | their best %s" % (banked, ("%.1f" % kb) if kb else "n/a"), flush=True)
        t0 = time.time()
        prune_at = None
        if a.prune or a.lp_only or a.prune_master:
            ab = {(r["cell"], r["size"]): r for r in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}
            water_lb = float(ab[(cell, a.size)]["water"])          # instance-level water floor, valid for any solution (the bound composition uses it)
            prune_at = float("inf") if a.lp_only else banked - water_lb
        if a.prune_master:
            t1 = time.time(); lpm = pool_master_lp(inst, pool)
            room = None if lpm is None else banked - lpm - water_lb
            verdict = "SKIP" if (lpm is not None and room <= 1e-6) else "RUN"
            print("  pool MASTER LP (floor buckets, valid over the pool) %s (%.1fs) | water floor %.3f | banked %.3f | room %s | guard: %s"
                  % (("%.3f" % lpm) if lpm is not None else "none", time.time() - t1, water_lb, banked,
                     ("%.3f = %.2f%%" % (room, 100 * room / banked)) if room is not None else "n/a", verdict), flush=True)
            if a.lp_only or verdict == "SKIP":
                out.append(dict(cell=cell, pool=len(pool), master_lp=lpm, water_lb=water_lb, banked=banked, theirs=kb, room=room,
                                verdict=verdict, guard="master", lp_only=a.lp_only, secs=round(time.time() - t0, 1))); continue
            prune_at = None                                  # the master guard replaces the relaxation guard
        if a.max_cars:
            res = select_chain(inst, pool, cap=a.cap, work=a.work, max_cars=a.max_cars, min_cars=False, prune_at=prune_at)
        else:
            res = select_chain(inst, pool, cap=a.cap, work=a.work, min_cars=True, prune_at=prune_at)
        if res is not None and res.get("pruned"):
            lp = res["lp"]; wl = water_lb
            verdict = "SKIP (LP + water floor %.3f >= banked %.3f)" % (lp + wl, banked) if lp + wl >= banked - 1e-6 else "RUN (LP + water floor %.3f < banked %.3f, room %.3f = %.2f%%)" % (lp + wl, banked, banked - lp - wl, 100 * (banked - lp - wl) / banked)
            print("  pool LP relaxation %.3f (%.1fs) | water floor %.3f | guard verdict: %s" % (lp, LAST.get("lp_secs", 0), wl, verdict), flush=True)
            out.append(dict(cell=cell, pool=len(pool), lp_relax=lp, water_lb=wl, banked=banked, theirs=kb, pruned=(not a.lp_only), lp_only=a.lp_only,
                            verdict=verdict.split(" ")[0], secs=round(time.time() - t0, 1))); continue
        if res is None:
            # d471: RC205 hit this branch and left NO row -- a failure must be a record, not an absence
            print("  joint select+chain: INFEASIBLE or no solution in budget")
            out.append(dict(cell=cell, pool=len(pool), failed="no solution in budget", banked=banked, theirs=kb,
                            gurobi_status=LAST.get("status"), phase1_status=LAST.get("phase1_status"),
                            secs=round(time.time() - t0))); continue
        sol = build(inst, res["trips"], res, incumbent=banked)   # d477 prune
        if sol is None:
            print("  selected %d trips, %d cars -- NOT TIMEABLE through the water stage"
                  % (len(res["trips"]), res["cars"]))
            out.append(dict(cell=cell, pool=len(pool), failed="not timeable through water", cars=res["cars"],
                            banked=banked, theirs=kb, secs=round(time.time() - t0))); continue
        run = V.verify_solution(inst, sol, cell=cell, size=a.size, proximity=prox, label="select_chain")
        bad = [x for x in run.findings if x.severity != "TOLERANCE"]
        ok = (not bad) and (not run.blocking)
        print("  selected %d of %d trips | %d CARS | obj %.3f | verifier3 %s | %.0fs"
              % (len(res["trips"]), len(pool), res["cars"], sol["objVal"],
                 "PASS" if ok else "FAIL(%s)" % (bad[0].cls if bad else "blocking"), time.time() - t0), flush=True)
        # d468: the Gurobi status that says WHICH limit stopped the solve (work = deterministic,
        # time = co-tenancy-sensitive) lived only in-process and was lost on RC202. Persist it.
        rec = dict(cell=cell, pool=len(pool), selected=len(res["trips"]), cars=res["cars"],
                   obj=float(sol["objVal"]), verified=ok, banked=banked, theirs=kb,
                   secs=round(time.time() - t0),
                   gurobi_status=LAST.get("status"), phase1_status=LAST.get("phase1_status"),
                   work_used=LAST.get("work"), bound=LAST.get("bound"))
        sol["gurobi_status"] = LAST.get("status"); sol["work_used"] = LAST.get("work")
        if ok and kb:
            print("     vs banked %+.2f%% | vs their best %+.2f%% (was %+.2f%%)"
                  % (100.0 * (sol["objVal"] / banked - 1), 100.0 * (sol["objVal"] / kb - 1),
                     100.0 * (banked / kb - 1)), flush=True)
            rec["vs_theirs"] = 100.0 * (sol["objVal"] / kb - 1)
        if ok and sol["objVal"] < banked - 1e-6:
            dst = os.path.join(ROOT, "runs", "postpass", "selchain")
            if not os.path.isdir(dst):
                os.makedirs(dst)
            sol["size"] = a.size; sol["_proximity"] = prox; sol["_verified"] = True
            sol["selection"] = "joint select+chain, cars first"; sol["superseded_objVal"] = banked
            sol["secs"] = round(time.time() - t0, 1)
            # d552: the stage had no lineage and no operator detail, so the ledger could not say what it
            # improved on or how. src names the artifact that held the value it beat.
            sol["superseded_from"] = src_path
            sol["stage_detail"] = dict(pool=len(pool), wide=a.wide, cap=a.cap, work=a.work,
                                       cars_before=cars_banked, cars_after=sol.get("nCars"))
            json.dump(stamped(sol, "analysis/tep_select_chain.py"),
                      io.open(os.path.join(dst, "ownwater_%s_n%d.json" % (cell, a.size)), "w",
                              encoding="utf-8"), indent=1, default=str)
            print("     IMPROVED -- banked under runs/postpass/selchain/", flush=True)
            rec["improved"] = True
        out.append(rec)
    json.dump(stamped(dict(size=a.size, cells=out)),
              io.open(os.path.join(ROOT, "runs", "oracle", "tep_select_chain_n%d.json" % a.size), "w",
                      encoding="utf-8"), indent=1, default=str)
    print("\n  wrote runs/oracle/tep_select_chain_n%d.json" % a.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
