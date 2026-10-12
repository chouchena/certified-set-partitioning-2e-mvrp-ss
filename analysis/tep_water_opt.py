"""Replace the greedy vessel stage with an EXACT one, on committed transfers. (S1 of the trajectory)

WHAT IS GREEDY TODAY. `tep_chain_own_water.water_tours` walks the transfers in time order and
appends each to the cheapest feasible open tour, else starts a new one. It optimises nothing. It is
the last stage of a strictly sequential pipeline, so it also cannot influence anything upstream.

WHY IT IS WORTH REPLACING AT n30 AND NOT AT n100. Measured against a valid per-tour floor -- the
sum over tours of twice the distance to that tour's furthest satellite, valid under the triangle
inequality -- our water sits at 1.051x at n100 but **1.217x at n30**, max 1.726x. Water is costed at
0.1, so on RC208 that slack is 26.8 units against a 44.3 gap to the predecessors. On RC203, RC206,
RC208, RC201, R206 and C206 the whole water cost EXCEEDS the gap.

WHAT THIS DOES AND DOES NOT TOUCH. Transfers, hubs and transfer TIMES are committed by the street
stage and are left exactly as they are; only the tours over them are re-solved. Hub re-assignment
was tested separately and is settled negative -- re-pricing hubs on the true objective gains
nothing on 26 of 27 n30 cells (d458). So this is "the vessel routing is now exact", NOT "the water
side is now optimised", and it must not be written up as the latter.

THE MODEL. A capacitated minimum-cost path cover over the transfers, with the CDC as depot:
  * an arc a->b exists only where verifier3's C20-WSEQ permits it, u(b) >= u(a) + tau + D(ha,hb);
  * every transfer has exactly one predecessor and one successor (CDC counts as either);
  * cumulative load along a tour is capped at VESSEL_CAPACITY, which is C18-WLOAD;
  * the objective is the real one -- vessel penalty per tour plus travelcostwater x distance.
Time is strictly increasing along any arc, so the arc set is a DAG and subtours are impossible
without a separate elimination constraint.

    python analysis/tep_water_opt.py --size 30
"""
import argparse
import glob
import io
import json
import os
import shutil
import sys
import time

import gurobipy as gp
from gurobipy import GRB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from tep_chain_own_water import objective
from instance_view import VESSEL_CAPACITY
from greedy26 import TOL
from stamp import stamped


def optimal_tours(inst, vi, hub_of, ui, tload, cap=120.0, work=60.0):
    """Exact capacitated path cover over committed transfers. Returns (yij, ntours, cost) or None."""
    D, CDC, tau = inst.D, inst.CDC, float(inst.tau)
    T = list(vi)
    pv, cw = float(inst.penalty_vessels), float(inst.travelcostwater)
    ok = {}
    for a in T:
        for b in T:
            if a == b:
                continue
            if ui[b] + 1e-9 >= ui[a] + tau + D[hub_of[a]][hub_of[b]]:
                ok[(a, b)] = D[hub_of[a]][hub_of[b]]
    m = gp.Model("wateropt"); m.Params.OutputFlag = 0; m.Params.Threads = 1
    m.Params.TimeLimit = cap
    if work:
        m.Params.WorkLimit = float(work)
    e = {k: m.addVar(vtype=GRB.BINARY) for k in ok}
    src = {b: m.addVar(vtype=GRB.BINARY) for b in T}          # CDC -> b
    snk = {a: m.addVar(vtype=GRB.BINARY) for a in T}          # a -> CDC
    L = {c: m.addVar(lb=0.0, ub=float(VESSEL_CAPACITY)) for c in T}
    for c in T:
        m.addConstr(src[c] + gp.quicksum(e[(a, c)] for a in T if (a, c) in e) == 1)
        m.addConstr(snk[c] + gp.quicksum(e[(c, b)] for b in T if (c, b) in e) == 1)
        m.addConstr(L[c] >= float(tload[c]))
    for (a, b) in e:
        m.addConstr(L[b] >= L[a] + float(tload[b]) - float(VESSEL_CAPACITY) * (1 - e[(a, b)]))
    ntours = gp.quicksum(src[b] for b in T)
    m.addConstr(ntours == gp.quicksum(snk[a] for a in T))
    dist = (gp.quicksum(ok[k] * e[k] for k in ok)
            + gp.quicksum(D[CDC][hub_of[b]] * src[b] for b in T)
            + gp.quicksum(D[hub_of[a]][CDC] * snk[a] for a in T))
    m.setObjective(pv * ntours + cw * dist, GRB.MINIMIZE)
    m.optimize()
    if m.SolCount == 0:
        return None
    nxt = {a: b for (a, b) in e if e[(a, b)].X > 0.5}
    yij, seen = [], set()
    for b in T:
        if src[b].X > 0.5:
            cur = b; prev = CDC
            while True:
                yij.append([prev, cur]); seen.add(cur); prev = cur
                if cur in nxt:
                    cur = nxt[cur]
                else:
                    break
            yij.append([prev, CDC])
    if len(seen) != len(T):
        return None                                   # every transfer must be covered
    return yij, int(round(sum(src[b].X for b in T))), float(m.ObjVal)


def run_one(path, size, cap, work):
    cell = os.path.basename(path).split("_")[1]
    prox = k_proximity(size)
    inst = V.load_instance(cell, size, prox)
    sol = json.load(io.open(path, encoding="utf-8"))
    hub_of = {int(x): int(h) for x, h in zip(sol["vi"], sol["hubs"])}
    ui = {int(k): float(v) for k, v in sol["ui"].items()}
    vi = [int(x) for x in sol["vi"]]
    nd = inst.nodes
    # trip loads, reconstructed from the street walk exactly as water_floor_check does
    dep = inst.depot
    nxt, starts = {}, []
    for a, b in sol["xij"]:
        a, b = int(a), int(b)
        if a == dep:
            starts.append(b)
        else:
            nxt[a] = b
    ts, tload = set(vi), {}
    for s0 in starts:
        cur, acc = s0, 0.0
        while cur is not None and cur != dep:
            acc += float(nd[cur].demand)
            if cur in ts:
                tload[cur] = acc; acc = 0.0
            cur = nxt.get(cur)
    if any(c not in tload for c in vi):
        return dict(cell=cell, skipped="street walk did not reach every transfer")
    if any(c not in ui for c in vi):
        return dict(cell=cell, skipped="no committed transfer time for some transfer")
    before = float(sol["objVal"])
    t0 = time.time()
    r = optimal_tours(inst, vi, hub_of, ui, tload, cap=cap, work=work)
    if r is None:
        return dict(cell=cell, skipped="no feasible cover found in budget")
    yij, nves, _ = r
    new = dict(sol); new["yij"] = yij; new["nVessel"] = nves
    new["objVal"] = objective(inst, new, hub_of)
    rec = dict(cell=cell, before=before, after=float(new["objVal"]),
               vessels_before=int(sol["nVessel"]), vessels_after=nves, secs=round(time.time() - t0, 1))
    if new["objVal"] >= before - 1e-6:
        rec["result"] = "no improvement"
        return rec
    run = V.verify_solution(inst, new, cell=cell, size=size, proximity=prox, label="water_opt")
    bad = [x for x in run.findings if x.severity != "TOLERANCE"]
    if bad or run.blocking:
        rec["result"] = "REJECTED by verifier3"; rec["findings"] = [str(x.cls) for x in bad[:4]]
        return rec
    keep = os.path.join(os.path.dirname(path), "superseded_wateropt")
    if not os.path.isdir(keep):
        os.makedirs(keep)
    shutil.copy2(path, os.path.join(keep, os.path.basename(path)))
    new["water_stage"] = "exact path cover"; new["superseded_objVal"] = before
    json.dump(stamped(new, "analysis/tep_water_opt.py"), io.open(path, "w", encoding="utf-8"),
              indent=1, default=str)
    rec["result"] = "IMPROVED"; rec["gain"] = before - float(new["objVal"])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--cap", type=float, default=120.0); ap.add_argument("--work", type=float, default=60.0)
    a = ap.parse_args()
    pats = [os.path.join(ROOT, "runs", "postpass", "ownwater_*_n%d.json" % a.size),
            os.path.join(ROOT, "runs", "postpass", "ceil", "ownwater_*_n%d.json" % a.size),
            os.path.join(ROOT, "runs", "postpass", "selchain", "ownwater_*_n%d.json" % a.size)]
    files = sorted(f for p in pats for f in glob.glob(p))
    print("Exact vessel routing on %d banked n%d solution(s). Street, hubs and transfer times are"
          % (len(files), a.size))
    print("committed and untouched; only the tours over them are re-solved.\n")
    print("%-7s %-9s %10s %10s %8s %7s %6s" % ("cell", "source", "before", "after", "gain", "vessels", "s"))
    rows = []
    for f in files:
        src = "ceil" if os.sep + "ceil" + os.sep in f else ("selchain" if "selchain" in f else "floor")
        r = run_one(f, a.size, a.cap, a.work); r["source"] = src
        rows.append(r)
        if r.get("skipped"):
            print("%-7s %-9s %s" % (r["cell"], src, r["skipped"])); continue
        print("%-7s %-9s %10.3f %10.3f %8s %3d->%-3d %6.1f"
              % (r["cell"], src, r["before"], r["after"],
                 ("%.3f" % r["gain"]) if r.get("gain") else ("-" if r["result"] != "IMPROVED" else "0"),
                 r["vessels_before"], r["vessels_after"], r["secs"]))
    imp = [r for r in rows if r.get("result") == "IMPROVED"]
    rej = [r for r in rows if r.get("result") == "REJECTED by verifier3"]
    print("\n  %d artifact(s): %d improved, %d unchanged, %d rejected by verifier3, %d skipped"
          % (len(rows), len(imp), sum(1 for r in rows if r.get("result") == "no improvement"),
             len(rej), sum(1 for r in rows if r.get("skipped"))))
    if imp:
        import statistics as st
        g = sorted(r["gain"] for r in imp)
        print("    gain: median %.2f, best %.2f, total %.1f | vessels dropped on %d"
              % (st.median(g), g[-1], sum(g), sum(1 for r in imp if r["vessels_after"] < r["vessels_before"])))
    for r in rej:
        print("    REJECTED %s: %s" % (r["cell"], ", ".join(r.get("findings", []))))
    json.dump(stamped(dict(size=a.size, rows=rows)),
              io.open(os.path.join(ROOT, "runs", "oracle", "tep_water_opt_n%d.json" % a.size), "w",
                      encoding="utf-8"), indent=1, default=str)
    print("  wrote runs/oracle/tep_water_opt_n%d.json" % a.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
