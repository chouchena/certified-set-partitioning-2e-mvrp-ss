"""B0 — how far does the greedy constructor reach, per size and family?

WHY THIS EXISTS. Until 2026-09-17 the primal had never produced a verified solution at |C| = 100:
coverage was 0 of 27 (`primal-coverage-scoped-to-n20`). A seven-cell probe found that
`ConstructivePrimal(singleton_vessels=True)` verifies on R and RC and fails on C. Seven cells is an
anecdote; this is the grid.

THE SETTING MATTERS AND IS NOT THE DEFAULT. `singleton_vessels=True` gives one CDC->transfer->CDC
vessel trip per transfer -- always CDC-time-window feasible. It is what `fixopt.py:252` and
`bench_primal.py:103` use. The constructor's DEFAULT is False, and testing with the default
produced a false "unschedulable at scale" conclusion that had to be withdrawn.

WHAT THIS IS NOT. A feasibility census, not a performance result. The greedy is roughly 2.4x K's
objective and 3.3x their fleet at |C| = 100. Reaching a size is not competing at it, and no
comparison with K may be drawn from this file.

PROXIMITY comes from `InstanceSpec.for_k_comparison`, so |C| = 100 is built at 0.1 to match K's
Table 6 rather than the 0.0 default.
"""
import argparse, collections, json, os, sys, time, random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from solver.config import InstanceSpec                       # noqa: E402
from solver.problem import SolverProblem                     # noqa: E402
from solver.engines.construct import ConstructivePrimal      # noqa: E402
import analysis.manuscript_numbers as M                      # noqa: E402


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="30,50,100")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs/greedy_coverage.json")
    a = ap.parse_args()

    rows = []
    for size in [int(x) for x in a.sizes.split(",")]:
        cells = sorted(M._cells(size))
        print(f"\n=== |C| = {size} : {len(cells)} cells ===")
        print("%-7s %7s %7s %11s %-8s %s" % ("cell", "nCars", "nVes", "obj", "verify", "violation"))
        for c in cells:
            t0 = time.time()
            rec = dict(cell=c, size=size, fam=fam(c))
            try:
                sp = SolverProblem(InstanceSpec.for_k_comparison(c, size))
                sol = ConstructivePrimal(singleton_vessels=True).construct(sp, random.Random(a.seed))
                if sol is None:
                    rec.update(status="no_solution")
                    print("%-7s %7s %7s %11s %-8s" % (c, "-", "-", "-", "NONE"))
                else:
                    vd = sp.verify(sol)
                    obj = getattr(vd, "recomputed_obj", None)
                    viol = (getattr(vd, "violations", None) or [])
                    rec.update(status="ok" if vd.ok else "failed",
                               nCars=sol.get("nCars"), nVessel=sol.get("nVessel"),
                               transfers=len(sol.get("vi") or []),
                               obj=obj, violation=(str(viol[0])[:70] if viol else None))
                    print("%-7s %7s %7s %11s %-8s %s"
                          % (c, sol.get("nCars"), sol.get("nVessel"),
                             ("%.1f" % obj) if obj else "-",
                             "OK" if vd.ok else "FAILED",
                             (str(viol[0])[:52] if viol else "")))
            except Exception as e:
                rec.update(status="error", violation=str(e)[:120])
                print("%-7s  ERROR %s" % (c, str(e)[:60]))
            rec["wall"] = round(time.time() - t0, 2)
            rows.append(rec)

    print("\n=== COVERAGE: verified feasible, by size and family ===")
    print("%-6s %-4s %8s %8s   %s" % ("size", "fam", "verified", "of", "failure mode"))
    agg = collections.defaultdict(list)
    for r in rows:
        agg[(r["size"], r["fam"])].append(r)
    for k in sorted(agg):
        v = agg[k]
        ok = sum(1 for x in v if x["status"] == "ok")
        modes = {}
        for x in v:
            if x["status"] != "ok" and x.get("violation"):
                tag = x["violation"].split(":")[0]
                modes[tag] = modes.get(tag, 0) + 1
        print("n%-5d %-4s %8d %8d   %s" % (k[0], k[1], ok, len(v), modes or ""))
    for size in sorted({r["size"] for r in rows}):
        v = [r for r in rows if r["size"] == size]
        print("  n%-4d TOTAL verified %d of %d" % (size, sum(1 for x in v if x["status"] == "ok"), len(v)))

    json.dump(stamped(dict(seed=a.seed, singleton_vessels=True, rows=rows), __file__),
              open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("\nwrote %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
