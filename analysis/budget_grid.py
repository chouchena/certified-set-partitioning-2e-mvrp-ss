"""The grid under the 1500 s cap: what every cell reports when only affordable instruments count.

    python analysis/budget_grid.py                 # all five sizes
    python analysis/budget_grid.py --cap 1500      # the cap is a parameter, not a constant

THE QUESTION THIS ANSWERS, which no existing reader answers. bound_source reports the best valid
bound per cell and charges its wall; it does not ask whether that wall fits a budget. The target
does: "validated bounds over the whole grid, performant against K's derived LBs over K-unproven
cells, at a max of 1500 s measured on 4 cores with no co-tenant". So the reported grid must be
the best bound each cell can BUY inside the cap, not the best bound on disk.

WHY A CO-TENANT WALL IS ADMISSIBLE HERE (d633). The cap is one-sided. A wall measured at 4
threads WITH neighbours is an upper bound on the same run's solo wall, so a recorded wall under
the cap proves the cell affordable; only a wall OVER the cap leaves the question open, and those
cells are listed separately rather than counted as affordable. Cells whose carrier artifact
records no thread count are flagged, because a 1-thread wall bounding a 4-thread wall is a
weaker argument than a tenancy difference.

THE PORTFOLIO, and every member charged. AB4 is deterministic arithmetic on instance data, a
valid bound on its own, median 0.023 s per cell -- it is affordable on every cell and is the
floor nothing can fall below. The TEP instruments are the whole-instance LP (elementary or
ng-class) and, at n100, the easy-reduction subset bound. The reported value is the MAX over the
affordable members, which is valid because the maximum of valid lower bounds is valid.

WHAT IT IS NOT. Not a runtime claim about any individual cell -- those walls are upper bounds,
and the cells over the cap are named, not hidden. Not a comparison with K on speed, which is
settled and refused (CLAUDE.md section 3).
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

AB4_SECONDS = 0.023   # runs/oracle/ab4_grid_rt.json median; charged on every cell


def affordable(cell, size, cap, ab):
    """(value, instrument, secs, class, note) -- the best bound this cell can buy inside `cap`."""
    from bound_certificate import certified, ng_certified
    from best_known import bound_artifacts
    q = ab.get((cell, size))
    water = float(q["water"]) if q else None
    cands = []
    if q and q.get("ab4") is not None:
        cands.append((float(q["ab4"]), "ab4", AB4_SECONDS, "arithmetic", None))
    over = []
    for p, d in bound_artifacts(cell, size):
        b = os.path.basename(p)
        if "_primal" in b or d.get("primal_rounding") or d.get("lp_street") is None:
            continue
        klass = "elementary" if certified(d) else ("ng" if ng_certified(d) else None)
        if klass is None:
            continue
        secs = float(d.get("secs") or 0.0)
        rt = d.get("_rt") or {}
        thr = rt.get("threads") if rt.get("threads") is not None else d.get("threads", (d.get("params") or {}).get("threads"))
        if d.get("drop"):
            v = d.get("lp_composed")
            if v is None:
                continue
            v, inst = float(v), "subset k=%s" % d.get("drop")
        else:
            if water is None:
                continue
            v, inst = float(d["lp_street"]) + water, "tep"
        if secs > cap:
            over.append((v, inst, secs, klass, b))
            continue
        cands.append((v, inst, secs, klass, "threads unrecorded" if thr is None else None))
    if not cands:
        return None, over
    return max(cands, key=lambda t: t[0]), over


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=1500.0)
    ap.add_argument("--sizes", default="10,20,30,50,100")
    a = ap.parse_args()
    from run_full_grid import all_cells
    import kref
    ab = {(q["cell"], q["size"]): q for q in json.load(io.open(
        os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}
    FAM = lambda c: "RC" if c.startswith("RC") else c[0]

    print("THE GRID INSIDE %.0f s PER CELL (every charged member, max over the affordable ones)\n" % a.cap)
    out = {}
    for size in [int(x) for x in a.sizes.split(",")]:
        rows, lost, unpriced = [], [], []
        for c in all_cells():
            best, over = affordable(c, size, a.cap, ab)
            if best is None:
                unpriced.append(c); continue
            v, inst, secs, klass, note = best
            rows.append(dict(cell=c, size=size, value=v, instrument=inst, secs=secs,
                             certificate_class=klass, note=note))
            if over:
                bo = max(over, key=lambda t: t[0])
                if bo[0] > v + 1e-9:
                    lost.append((c, bo[0] - v, bo[2], bo[4]))
        if not rows:
            continue
        tot = sum(r["secs"] for r in rows)
        klas = {}
        for r in rows:
            klas[r["certificate_class"]] = klas.get(r["certificate_class"], 0) + 1
        print("n%-4d %2d cells priced | worst wall %6.0f s | total %7.0f s | classes %s%s"
              % (size, len(rows), max(r["secs"] for r in rows), tot,
                 ", ".join("%s %d" % (k, v) for k, v in sorted(klas.items())),
                 "" if not unpriced else " | NO BOUND: %s" % unpriced))
        if lost:
            print("      cells where a STRONGER bound exists but costs more than the cap:")
            for c, d, s, f in sorted(lost, key=lambda t: -t[1]):
                print("        %-6s would gain %8.2f at %6.0f s  (%s)" % (c, d, s, f))
        try:
            klb = kref.derived_lb(size)
        except Exception:
            klb = None
        if klb:
            for f in ("C", "R", "RC"):
                g = [r["value"] for r in rows if FAM(r["cell"]) == f]
                if g and klb.get(f):
                    print("      %-3s mean %9.2f vs K derived %9.2f  = %.2fx" % (f, sum(g) / len(g), float(klb[f]), (sum(g) / len(g)) / float(klb[f])))
        out["n%d" % size] = rows
    p = os.path.join(ROOT, "logs", "smoke", "budget_grid_cap%d.json" % int(a.cap))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(dict(cap=a.cap, sizes=out,
                   note="values are max over instruments whose RECORDED wall is inside the cap; "
                        "co-tenant walls are upper bounds on solo walls (d633)"),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\nwrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
