"""Forced-diversity primal selection: generate structurally distinct partitions, rank them exactly.

THE DEFECT THIS FIXES. The master ranks trip partitions by a bucketed street cost with a
floor-rounded fleet term and NO WATER, and the production route takes its argmin on trust. On R211
at n30 that ranking was nearly orthogonal to the truth: candidates 1.4 percent apart in proxy value
were 19 percent apart in realised objective, and the winner used 2 cars where the proxy pick used 3
(the floor-rounded fleet term under-prices a car). Re-ranking recovered 19.19 percent and took the
cell from +25.02 to +1.02 percent against the better of the predecessors' two published methods.

WHY A SOLUTION POOL IS NOT ENOUGH. Gurobi returned 12 pooled solutions on that cell of which only 3
were distinct partitions, so the proxy trivially picked the best of a near-duplicate set and the
pool test concluded the ranking was fine. It was not. Diversity has to be FORCED: solve, forbid
that exact column set with a no-good cut, solve again.

NO REGRESSION IS STRUCTURAL. The driver keeps the banked solution unless a candidate is strictly
better AND passes verifier3. The table cannot get worse; a regression would be a coding defect.

DETERMINISM. The banked n30 batch used a WALL-CLOCK cap on the integer stage, which violates the
deterministic-budget rule. Here the IP rounds use Gurobi WorkLimit (deterministic work units), the
chaining keeps its deterministic work limit, and column generation runs with NO wall at all -- at
n30 it exhausts, and the driver asserts the artifact came back `proven`. A cell that does not is
recorded non-deterministic and excluded from the gate arithmetic rather than silently kept.

The pre-run audit, with the sample and gates fixed before any data, is
`validation/runaudits/TEP_forced_diversity.md`.

    python analysis/tep_diverse_primal.py R204 --size 30 --rounds 8
"""
import argparse
import io
import json
import os
import shutil
import sys
import time
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity, k_best_incumbent
import tep_cg_bound as T
from tep_pool_search import realise
from stamp import stamped

GRB_OPTIMAL = 2


def banked_path(cell, size):
    return os.path.join(ROOT, "runs", "postpass", "ownwater_%s_n%d.json" % (cell, size))


def run_cell(cell, size, rounds, work_ip, work_chain, cap_chain, verbose=True):
    prox = k_proximity(size)
    inst = V.load_instance(cell, size, prox)
    # d475: the incumbent is the MIN over every production dir (d469 class), and this driver banks to
    # its OWN dir instead of overwriting the floor artifact -- which would have contaminated the
    # floor-only record tep_n30_table.py keeps.
    cands = []
    for sub in ("", "ceil", "selchain", "forced", "diverse", "refine", "alns", "masterip"):
        q = os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, size))
        if os.path.exists(q):
            cands.append((float(json.load(io.open(q, encoding="utf-8"))["objVal"]), q))
    if not cands:
        return dict(cell=cell, size=size, skipped="no banked solution to improve on")
    base, bp = min(cands)
    banked = json.load(io.open(bp, encoding="utf-8"))
    kb, which = k_best_incumbent(cell, size)
    if verbose:
        print("%s n%d: banked %.3f (%d cars, %d vessels) | their best %s"
              % (cell, size, base, banked["nCars"], banked["nVessel"],
                 ("%.1f (%s)" % (kb, which)) if kb else "not published at this size"), flush=True)

    # Column generation with NO wall: at n30 it exhausts, so the stage is deterministic.
    t0 = time.time()
    r = T.run(cell, T.default_delta(inst), 400, ["prio", "ts"], 10, 1000, False, 3_000_000,
              size=size, start_states=True, proximity=prox, return_master=True, max_secs=0.0)
    cg_s = time.time() - t0
    if not r.get("proven"):
        return dict(cell=cell, size=size, nondeterministic="column generation did not prove; "
                    "its stopping point is not reproducible and the cell is excluded", cg_secs=cg_s)
    M = r["master"]
    import gurobipy as gp
    from gurobipy import GRB
    for v in M.cols.values(): v.VType = GRB.BINARY
    for v in M.z.values(): v.VType = GRB.BINARY
    M.N.VType = GRB.INTEGER
    for row in M.cov.values(): row.Sense = GRB.EQUAL
    M.m.Params.Threads = 1
    M.m.Params.PoolSearchMode = 0
    M.m.Params.PoolSolutions = 1
    M.m.Params.WorkLimit = work_ip          # DETERMINISTIC, not TimeLimit
    M.m.Params.TimeLimit = gp.GRB.INFINITY

    ncust = len(list(inst.customers))
    cands, work_used = [], 0.0
    t1 = time.time()
    for rnd in range(rounds):
        M.m.optimize()
        work_used += float(M.m.Work)
        if M.m.SolCount == 0:
            if verbose:
                print("    round %d: no further partition (status %s)" % (rnd, M.m.Status), flush=True)
            break
        used = [k for k, v in M.cols.items() if v.X > 0.5]
        trips = [list(k[0]) for k in used]
        cov = [c for t in trips for c in t]
        proxy = float(M.m.ObjVal)
        rec = dict(i=rnd, proxy=proxy, trips=len(trips), obj=None, why=None)
        if len(set(cov)) == ncust and len(cov) == len(set(cov)):
            sol = realise(inst, trips, cap_chain, work_chain, incumbent=base)   # d477 prune
            if sol is None:
                rec["why"] = "did not realise"
            else:
                rec.update(obj=float(sol["objVal"]), cars=int(sol["nCars"]), vessels=int(sol["nVessel"]))
                rec["_sol"] = sol
        else:
            rec["why"] = "not a partition"
        cands.append(rec)
        if verbose:
            print("    round %-2d proxy %9.1f -> %s" % (rnd, proxy,
                  ("real %9.3f  %d cars %d vessels" % (rec["obj"], rec["cars"], rec["vessels"]))
                  if rec.get("obj") else rec["why"]), flush=True)
        M.m.addConstr(gp.quicksum(M.cols[k] for k in used) <= len(used) - 1, name="nogood_%d" % rnd)
        M.m.update()
    ip_s = time.time() - t1

    ok = [c for c in cands if c.get("obj") is not None]
    out = dict(cell=cell, size=size, rounds=rounds, banked=base, their_best=kb, their_method=which,
               distinct=len(cands), realised=len(ok), cg_secs=round(cg_s), ip_secs=round(ip_s),
               work_ip=round(work_used, 1), work_limit_per_round=work_ip,
               candidates=[{k: v for k, v in c.items() if k != "_sol"} for c in cands],
               round0=(ok[0]["obj"] if ok and ok[0]["i"] == 0 else None))
    if not ok:
        out["result"] = "nothing realised"
        if verbose:
            print("    nothing realised -- banked value stands", flush=True)
        return out
    best = min(ok, key=lambda c: c["obj"])
    out.update(best_obj=best["obj"], best_round=best["i"], best_cars=best["cars"],
               best_vessels=best["vessels"])

    if best["obj"] >= base - 1e-6:
        out["result"] = "no improvement"
        if verbose:
            print("  -> best candidate %.3f does NOT beat banked %.3f; banked stands"
                  % (best["obj"], base), flush=True)
        return out

    sol = best["_sol"]
    run = V.verify_solution(inst, sol, cell=cell, size=size, proximity=prox, label="diverse_primal")
    bad = [x for x in run.findings if x.severity != "TOLERANCE"]
    if bad or run.blocking:
        out["result"] = "improvement REJECTED by verifier3"
        out["findings"] = [str(x.cls) for x in bad[:5]]
        if verbose:
            print("  -> %.3f beats banked but FAILS verifier3 (%s); banked stands"
                  % (best["obj"], ", ".join(out["findings"])), flush=True)
        return out

    dst_dir = os.path.join(ROOT, "runs", "postpass", "diverse")
    if not os.path.isdir(dst_dir):
        os.makedirs(dst_dir)
    dst = os.path.join(dst_dir, "ownwater_%s_n%d.json" % (cell, size))
    if os.path.exists(dst):
        keep = os.path.join(dst_dir, "superseded")
        if not os.path.isdir(keep):
            os.makedirs(keep)
        shutil.copy2(dst, os.path.join(keep, "ownwater_%s_n%d_%d.json" % (cell, size, int(time.time()))))
    sol["size"] = size; sol["_proximity"] = prox; sol["_verified"] = True
    sol["selection"] = "forced-diversity, exact water"; sol["superseded_objVal"] = base
    sol["superseded_from"] = os.path.relpath(bp, ROOT)
    json.dump(stamped(sol, "analysis/tep_diverse_primal.py", "analysis/assemble_precluster.py"),
              io.open(dst, "w", encoding="utf-8"), indent=1, default=str)
    out.update(result="IMPROVED", gain_pct=100.0 * (1 - best["obj"] / base),
               vs_their_best_before=100.0 * (base / kb - 1) if kb else None,
               vs_their_best_after=100.0 * (best["obj"] / kb - 1) if kb else None,
               cars_before=int(banked["nCars"]), cars_after=int(best["cars"]))
    if verbose:
        print("  -> IMPROVED %.3f to %.3f (%.2f%%) | cars %d -> %d | vs their best %+.2f%% -> %+.2f%%"
              % (base, best["obj"], out["gain_pct"], banked["nCars"], best["cars"],
                 out["vs_their_best_before"], out["vs_their_best_after"]), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="+")
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--work-ip", type=float, default=30.0, help="Gurobi WorkLimit per IP round (deterministic)")
    ap.add_argument("--work-chain", type=float, default=60.0)
    ap.add_argument("--cap-chain", type=float, default=600.0, help="wall safety on chaining; must not bind")
    ap.add_argument("--tag", default="sample")
    a = ap.parse_args()
    res = []
    for c in a.cells:
        t0 = time.time()
        try:
            r = run_cell(c, a.size, a.rounds, a.work_ip, a.work_chain, a.cap_chain)
        except Exception as e:                                  # one bad cell must not lose the batch
            r = dict(cell=c, size=a.size, error="%s: %s" % (type(e).__name__, e))
            print("  %s FAILED: %s" % (c, r["error"]), flush=True)
        r["wall_secs"] = round(time.time() - t0)
        res.append(r)
        p = os.path.join(ROOT, "runs", "oracle", "tep_diverse_primal_%s_n%d.json" % (a.tag, a.size))
        json.dump(stamped(dict(size=a.size, rounds=a.rounds, tag=a.tag, cells=res)),
                  io.open(p, "w", encoding="utf-8"), indent=1, default=str)

    imp = [r for r in res if r.get("result") == "IMPROVED"]
    nd = [r for r in res if r.get("nondeterministic")]
    err = [r for r in res if r.get("error")]
    print("\n  %d cell(s): %d improved, %d no improvement, %d non-deterministic, %d error"
          % (len(res), len(imp), len(res) - len(imp) - len(nd) - len(err), len(nd), len(err)))
    for r in imp:
        print("    %-7s %9.3f -> %9.3f  %+6.2f%%   cars %d -> %d   vs their best %+.2f%% -> %+.2f%%"
              % (r["cell"], r["banked"], r["best_obj"], -r["gain_pct"], r["cars_before"],
                 r["cars_after"], r["vs_their_best_before"], r["vs_their_best_after"]))
    car = [r for r in imp if r["cars_after"] != r["cars_before"]]
    print("    winner differs from the banked solution in CAR COUNT on %d of %d improvements"
          % (len(car), len(imp)))
    # ATTRIBUTION. A gain already present at round 0 is NOT diversity -- it is the deterministic
    # WorkLimit solving an integer stage the production route under-budgeted. Only a gain at a
    # later round is the no-good cuts doing work. Reported split because the cheaper fix wins.
    r0 = [r for r in imp if r.get("best_round") == 0]
    dv = [r for r in imp if r.get("best_round", 0) > 0]
    print("    ATTRIBUTION: %d of %d improvements are already at ROUND 0 (better IP solve, not diversity);"
          % (len(r0), len(imp)))
    print("                 %d need a no-good cut. Extra gain from diversity beyond round 0:" % len(dv))
    for r in dv:
        if r.get("round0"):
            print("                   %-7s round0 %9.3f -> best %9.3f  (%+.2f%% further)"
                  % (r["cell"], r["round0"], r["best_obj"], 100.0 * (r["best_obj"] / r["round0"] - 1)))
    for r in res:
        if r.get("result") == "no improvement" and r.get("round0") and r["round0"] < r["banked"]:
            print("    NOTE %s: round 0 (%.3f) beats banked (%.3f) but was rejected -- check the gate"
                  % (r["cell"], r["round0"], r["banked"]))
    w = [r.get("wall_secs", 0) for r in res]
    print("    wall per cell: median %d s, max %d s (envelope is 5760 our-seconds for LB + primal)"
          % (st.median(w), max(w)))
    print("  wrote runs/oracle/tep_diverse_primal_%s_n%d.json" % (a.tag, a.size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
