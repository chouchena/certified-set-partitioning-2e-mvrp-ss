"""Cap the fleet in the MASTER, not just the chaining, and re-partition. (d461)

THE CHAIN OF ELIMINATION THAT LEADS HERE. After ceil rounding (d460), 25 of 27 n30 cells carry the
right car count. Two do not: R201 (gap 1.13 cars) and RC202 (0.91), which are also the two worst
cells at +15.81 and +14.44 percent. `tep_force_fleet.py` then capped the CHAINING at two cars on
every partition we hold, floor and ceil, and every one was INFEASIBLE. So the chaining is not
failing to find a two-car schedule; the partitions it is handed cannot support one.

AND TWO CARS IS NOT RULED OUT. The proven floor-rounded LP is a relaxation, so ceil(N_LP) is a hard
lower bound on the car count of any feasible solution. It is 2 on both cells while we use 3. On
C203, R208 and RC207 it EQUALS what we use, which is why those cells are left alone -- their fleet
is provably optimal and their residual gap is street routing.

SO THE PARTITION IS THE PROBLEM, and this caps N in the master itself, forcing it to select a
different partition, then caps the chaining to match. Rounds of no-good cuts follow, because the
first partition meeting N <= k need not be chainable at k -- the bucketed car count undercounts
what continuous timing needs, which is the whole reason ceil rounding exists.

Everything produced here is an ordinary feasible solution of our own formulation, verified by
verifier3, and banked separately under runs/postpass/forced/. Capping N is a RESTRICTION of the
search, so it can only fail to find a solution, never produce an invalid one.

    python analysis/tep_master_fleet_cap.py R201 RC202 --size 30 --cap-cars 2 --rounds 6
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity, k_best_incumbent
import tep_cg_bound as T
from assemble_precluster import chain
from tep_force_fleet import build
from stamp import stamped


def banked_best(cell, size):
    v = None
    for p in (os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, size))
              for sub in ("", "ceil", "selchain", "forced", "refine", "alns")):  # d469/d475: every production dir
        if os.path.exists(p):
            x = float(json.load(io.open(p, encoding="utf-8"))["objVal"])
            v = x if v is None else min(v, x)
    return v


def cap_solve(inst, cell, size, prox, cap_cars, rounds=6, work_ip=60.0, work_chain=300.0,
              cap_chain=600.0, ng=10, budget_s=None, cg_secs=90.0, kb=None, log=print):
    """Cap N <= cap_cars in the master, re-partition over `rounds` with no-good cuts, chain, and
    VERIFY each candidate with verifier3; return the best verified (objVal, solution, tag, round) or
    None. No I/O and no banking, so tep_solve can call this as stage 13 (d685). Capping N is a
    RESTRICTION of our own formulation -- it can only fail to find a solution, never produce an
    invalid one (d461) -- and every returned solution is verifier3-clean. main() calls this too.

    `ng` is the ng-route neighbourhood size of the re-partition CG. A WIDER ng generates the diverse
    columns a low-car partition needs: at ng=10 the master held no chainable 2-car partition for
    RC202 n30, at ng=25 it does (d690). Because this runs ONLY on basin cells (the caller fires it
    when cars > cap) and the result is accept-if-verified-better gated, the wider ng is basin-scoped
    and cannot regress a non-basin or an already-good cell."""
    import gurobipy as gp
    from gurobipy import GRB
    best = None
    _t0 = time.time()                      # d691: hard wall backstop so a fruitless cap search aborts
    ncust = len(list(inst.customers))      #       fast instead of hanging (R204/R207/R211 n30 cap=1 ran 700s+)
    for tag, pr in (("floor", False), ("ceil", True)):
        if budget_s is not None and time.time() - _t0 > budget_s:
            log("        fleet-cap budget %.0fs exhausted before %s tag" % (budget_s, tag)); break
        r = T.run(cell, T.default_delta(inst), 400, ["prio", "ts"], ng, 1000, False, 3_000_000,
                  size=size, start_states=True, proximity=prox, return_master=True,
                  max_secs=cg_secs, primal=pr)      # d691: wall-bound the re-partition CG (was 0.0=uncapped)
        M = r["master"]
        for v in M.cols.values(): v.VType = GRB.BINARY
        for v in M.z.values(): v.VType = GRB.BINARY
        M.N.VType = GRB.INTEGER
        for row in M.cov.values(): row.Sense = GRB.EQUAL
        M.m.Params.Threads = 1
        M.m.Params.PoolSearchMode = 0
        M.m.Params.PoolSolutions = 1
        M.m.Params.WorkLimit = work_ip
        M.m.Params.TimeLimit = GRB.INFINITY
        M.m.addConstr(M.N <= cap_cars, name="fleet_cap")     # the restriction
        M.m.update()
        log("  %-5s master converged (proven %s); solving with N <= %d"
            % (tag, r.get("proven"), cap_cars))
        for rnd in range(rounds):
            if budget_s is not None and time.time() - _t0 > budget_s:
                log("        fleet-cap budget %.0fs exhausted at %s round %d" % (budget_s, tag, rnd)); break
            M.m.optimize()
            if M.m.SolCount == 0:
                log("        round %d: no partition with N <= %d (status %s)"
                    % (rnd, cap_cars, M.m.Status)); break
            used = [k for k, v in M.cols.items() if v.X > 0.5]
            trips = [list(k[0]) for k in used]
            cov = [c for t in trips for c in t]
            if len(set(cov)) != ncust or len(cov) != len(set(cov)):
                log("        round %d: not a partition" % rnd)
            else:
                t0 = time.time()
                res = chain(inst, trips, cap=cap_chain, work=work_chain, max_cars=cap_cars)
                if res is None:
                    log("        round %-2d %2d trips: chaining INFEASIBLE at %d cars (%.0fs)"
                        % (rnd, len(trips), cap_cars, time.time() - t0))
                else:
                    s = build(inst, trips, res)
                    if s is None:
                        log("        round %-2d %2d trips: %d cars but NOT TIMEABLE"
                            % (rnd, len(trips), res["cars"]))
                    else:
                        run = V.verify_solution(inst, s, cell=cell, size=size, proximity=prox,
                                                label="master_fleet_cap")
                        bad = [x for x in run.findings if x.severity != "TOLERANCE"]
                        ok = (not bad) and (not run.blocking)
                        log("        round %-2d %2d trips: %d cars, obj %.3f | verifier3 %s | vs theirs %s"
                            % (rnd, len(trips), s["nCars"], s["objVal"], "PASS" if ok else "FAIL",
                               ("%+.2f%%" % (100.0 * (s["objVal"] / kb - 1))) if kb else "not published"))
                        if ok and (best is None or s["objVal"] < best[0]):
                            best = (s["objVal"], s, tag, rnd)
            M.m.addConstr(gp.quicksum(M.cols[k] for k in used) <= len(used) - 1, name="ng_%d" % rnd)
            M.m.update()
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="+"); ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--cap-cars", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--work-ip", type=float, default=60.0)
    ap.add_argument("--work-chain", type=float, default=300.0)
    ap.add_argument("--cap-chain", type=float, default=600.0)
    a = ap.parse_args()
    prox = k_proximity(a.size)
    out = []
    for cell in a.cells:
        t_cell = time.time()          # d552: per-cell clock, so the artifact can carry its own seconds
        inst = V.load_instance(cell, a.size, prox)
        kb, which = k_best_incumbent(cell, a.size)
        base = banked_best(cell, a.size)
        # K PUBLISH NO PER-CELL INCUMBENT AT |C| = 50 OR 100, so kb is None there and "%.1f" raised
        # TypeError before any work was done. That crash stopped the whole campaign at step S3b on its
        # first cell (2026-09-27, 1 second in) -- the same class of defect as the n50/n100 divide in
        # tep_n30_best_of.py earlier the same day: a print that assumes a comparator which does not exist.
        print("\n%s n%d: banked %.3f | their best %s | capping N <= %d"
              % (cell, a.size, base, ("%.1f (%s)" % (kb, which)) if kb else "not published at this size",
                 a.cap_cars), flush=True)
        best = cap_solve(inst, cell, a.size, prox, a.cap_cars, a.rounds, a.work_ip, a.work_chain,
                         a.cap_chain, kb=kb)
        if best is not None and best[0] < base - 1e-6:
            v, s, tag, rnd = best
            dst = os.path.join(ROOT, "runs", "postpass", "forced")
            if not os.path.isdir(dst):
                os.makedirs(dst)
            s["size"] = a.size; s["_proximity"] = prox; s["_verified"] = True
            s["selection"] = "master-fleet-cap(%s, N<=%d, round %d)" % (tag, a.cap_cars, rnd)
            s["superseded_objVal"] = base
            s["secs"] = round(time.time() - t_cell, 1)          # d552: the stage recorded no seconds at all
            s["stage_detail"] = dict(cap_cars=a.cap_cars, source=tag, round=rnd, rounds_allowed=a.rounds,
                                     cars_after=s.get("nCars"))
            json.dump(stamped(s, "analysis/tep_master_fleet_cap.py", "analysis/assemble_precluster.py"),
                      io.open(os.path.join(dst, "ownwater_%s_n%d.json" % (cell, a.size)), "w", encoding="utf-8"),
                      indent=1, default=str)
            print("  => IMPROVED %.3f to %.3f%s"
                  % (base, v, (" | %+.2f%% vs their best (was %+.2f%%)"
                               % (100.0 * (v / kb - 1), 100.0 * (base / kb - 1))) if kb
                     else " | they publish no per-cell value at this size"), flush=True)
            out.append(dict(cell=cell, improved=True, obj=v, banked=base, theirs=kb, src=tag))
        else:
            print("  => no verified partition at N <= %d beats %.3f" % (a.cap_cars, base), flush=True)
            out.append(dict(cell=cell, improved=False, banked=base, theirs=kb))
    json.dump(stamped(dict(size=a.size, cap_cars=a.cap_cars, cells=out)),
              io.open(os.path.join(ROOT, "runs", "oracle", "tep_master_fleet_cap_n%d.json" % a.size), "w",
                      encoding="utf-8"), indent=1, default=str)
    print("\n  wrote runs/oracle/tep_master_fleet_cap_n%d.json" % a.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
