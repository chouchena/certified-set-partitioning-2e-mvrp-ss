"""AB4 over the whole grid, with its runtime charged: value, RT and provenance per cell.

WHY (author, 2026-09-28): "run the AB4 over all grid and record RT, provenance and value so we
can use it to use the max formula and deduct and add its RT to the total LB RT (solver + AB4)".

THE RULE THIS SERVES. Our reported bound is `max(solver, AB4)` -- SKELETON's portfolio rule,
now also in TEP_FORMULATION section 5. And d245/d246/d250: EVERY bound instrument whose value is
reported is charged to the cell's runtime envelope. So if AB4 can carry a cell, AB4's seconds are
part of the LB leg and come out of the primal's 5760 - LB_wall. This script produces the numbers
that make both of those auditable per cell.

DESIGN, declared before the run.
  SCOPE      135 cells: 27 x {10, 20, 30, 50, 100}. Proximity from k_comparison.k_proximity,
             so n100 is 0.1 and the rest 0.0 -- the same convention ab_grid_build's COMBOS uses.
  VALUE      crossfeed.fullset_bound on a freshly built instance. Deterministic arithmetic: no
             solver, no seed (ab_grid_build's own words). The three components are recorded
             separately because ab4 = fleet_term + travel_term + water and the water half is what
             the composed bound consumes.
  RT         wall, split into build() and fullset_bound() so that the part attributable to the
             BOUND is separable from instance construction. Both are reported; the charged
             figure is the total, because neither happens without the other.
  FIDELITY   every value is diffed against runs/ab_grid_provenanced.json. AB4 is deterministic,
             so a mismatch means the stored numbers came from code we no longer have -- the
             same test ab_grid_build --verify exists to run. A mismatch is reported, never
             silently accepted.
  ENVELOPE   for each cell: the LB wall as it stands (run_full_grid.lb_cell_seconds, the descent
             leg's recorded wall), that wall PLUS AB4, and the primal envelope before and after.
             This is the "deduct and add" the author asked for, per cell rather than in aggregate.
  MAX        where a certified composed bound exists, the carrier is recorded. The composed value
             is read through bound_source, the single authority, NOT re-derived here.

WHAT THIS IS NOT. It does not change any bound. It measures one and records what charging it
would cost. Nothing here writes to the bound corpus.

    python analysis/ab4_grid_rt.py                 # all 135
    python analysis/ab4_grid_rt.py --sizes 10 20   # a subset
"""
import argparse
import io
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
from build_instance import build
from crossfeed.fullset_bound import fullset_bound
from k_comparison import k_proximity
from stamp import stamped
import bound_source as BS


def retained_depth(cell, size):
    """|H|, the deepest retained set the descent reached on this cell.

    FINDING_n50_crossover: correlation(|H|/|C|, AB/MILP) = -0.688 over 22 cells, and every AB
    win sits at depth <= 16 of 50. So depth is the measured INSTANCE-LEVEL driver of whether
    AB carries a cell -- it belongs beside the value, or the carrier is only observed and never
    predicted. Read from the descent's own artifacts, the same source fig_crossover uses.
    """
    import glob as _g
    depth = 0
    for pat in ("easy_reduction_descend_%s_n%d.json" % (cell, size),
                "easy_reduction_descend_%s_n%d_*.json" % (cell, size)):
        for f in _g.glob(os.path.join(ROOT, "crossfeed", pat)):
            try:
                recs = json.load(io.open(f, encoding="utf-8"))
            except Exception:
                continue
            for r in (recs if isinstance(recs, list) else [recs]):
                depth = max(depth, r.get("nH") or 0)
    return depth or None

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
# The files that actually determine an AB number, named by ab_grid_build as AB_HASH_FILES. A
# change to any of them changes the bound, so all of them belong in this artifact's provenance.
AB_SOURCES = ("crossfeed/fullset_bound.py", "crossfeed/check_cuts.py",
              "crossfeed/blockA_cpsat.py", "build_instance.py",
              "analysis/ab4_grid_rt.py")


def banked():
    p = os.path.join(ROOT, "runs", "ab_grid_provenanced.json")
    try:
        return {(r["cell"], r["size"]): r
                for r in json.load(io.open(p, encoding="utf-8"))["records"]}
    except Exception:
        return {}


def lb_wall(cell, size):
    """The dual leg's recorded wall on this cell, in our seconds.

    The signature is lb_cell_seconds(cell, SIZE). The first version of this helper called it
    with the cell alone, raised TypeError into a bare `except`, and silently recorded None on
    all 135 cells -- which is exactly the "solver + AB4" total the run was asked to produce.
    A swallowed exception that yields a plausible-looking None is worse than a crash.
    """
    from run_full_grid import lb_cell_seconds
    v = lb_cell_seconds(cell, size)
    return None if v is None else float(v)


def envelope(size, cell):
    try:
        import run_full_grid as G
        e = G.envelope(size, G.HW_FACTOR_ENVELOPE, cell)
        return float(e) if e else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100])
    ap.add_argument("--cells", nargs="*", default=CELLS)
    a = ap.parse_args()

    bank = banked()
    print("AB4 OVER THE GRID -- value, runtime and provenance, with the RT charged\n")
    print("  %-7s %-5s %11s %10s %10s %10s %8s %8s  %s"
          % ("cell", "size", "ab4", "fleet", "travel", "water", "build_s", "bound_s", "vs banked"))
    rows, mismatches = [], []
    for size in a.sizes:
        prox = k_proximity(size)
        for cell in a.cells:
            rec = dict(cell=cell, size=size, proximity=prox)
            try:
                t0 = time.time()
                p = build(cell, size, wls=0.1, tau="formula", proximity=prox, time_limit=60)
                t1 = time.time()
                b, parts = fullset_bound(p)
                t2 = time.time()
                rec.update(ab4=float(b), fleet_term=float(parts["fleet_term"]),
                           travel_term=float(parts["travel_term"]), water=float(parts["water"]),
                           V_LB=parts.get("V_LB"), which=parts.get("dist_winner"),
                           build_s=round(t1 - t0, 3), bound_s=round(t2 - t1, 3),
                           total_s=round(t2 - t0, 3))
                # fidelity: AB4 is deterministic, so this must reproduce exactly
                ref = bank.get((cell, size))
                if ref is not None:
                    d = abs(float(ref["ab4"]) - rec["ab4"])
                    rec["banked_ab4"] = float(ref["ab4"]); rec["banked_delta"] = d
                    rec["reproduces"] = d < 1e-6
                    if not rec["reproduces"]:
                        mismatches.append((cell, size, float(ref["ab4"]), rec["ab4"]))
                else:
                    rec["reproduces"] = None
                # the decomposition the composed bound relies on
                rec["decomposes"] = abs((rec["fleet_term"] + rec["travel_term"] + rec["water"])
                                        - rec["ab4"]) < 1e-6
            except Exception as e:
                rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:90])
            # RT accounting: what charging AB4 costs this cell
            w = lb_wall(cell, size)
            env0 = envelope(size, cell)
            rec["lb_wall_s"] = w
            rec["lb_wall_with_ab4_s"] = None if w is None else round(w + (rec.get("total_s") or 0.0), 3)
            rec["envelope_before_s"] = env0
            rec["envelope_after_s"] = (None if env0 is None
                                       else round(env0 - (rec.get("total_s") or 0.0), 3))
            # WHICH INSTRUMENT CARRIES THE CELL, decided against the COMPOSED half and not
            # against the reported max. tep_bound now returns max(composed, ab4), so comparing
            # ab4 to it can never elect ab4 -- the first run of this script reported
            # "carrier: ab4 0 of 126" for exactly that reason. tep_bound_parts hands back both
            # halves from the one authority, so nothing is re-derived here.
            try:
                comp, _ab4_rep, reported = BS.tep_bound_parts(cell, size, allow_suspended=True)
            except Exception:
                comp = reported = None
            rec["nH"] = retained_depth(cell, size)
            rec["nH_frac"] = (None if not rec["nH"] else round(rec["nH"] / float(size), 4))
            rec["composed_via_bound_source"] = comp
            rec["reported_via_bound_source"] = reported
            rec["carrier"] = (None if comp is None or rec.get("ab4") is None
                              else ("ab4" if rec["ab4"] > comp + 1e-9 else "solver"))
            print("  %-7s n%-4d %11s %10s %10s %10s %8s %8s  %s"
                  % (cell, size,
                     "%.3f" % rec["ab4"] if rec.get("ab4") is not None else "ERR",
                     "%.2f" % rec["fleet_term"] if rec.get("fleet_term") is not None else "-",
                     "%.2f" % rec["travel_term"] if rec.get("travel_term") is not None else "-",
                     "%.2f" % rec["water"] if rec.get("water") is not None else "-",
                     rec.get("build_s"), rec.get("bound_s"),
                     "exact" if rec.get("reproduces") else
                     ("MISMATCH" if rec.get("reproduces") is False else "not banked")),
                  flush=True)
            rows.append(rec)

    ok = [r for r in rows if r.get("ab4") is not None]
    tot = [r["total_s"] for r in ok]
    print("\n  cells %d | errors %d" % (len(rows), len(rows) - len(ok)))
    if tot:
        print("  AB4 runtime per cell: median %.3f s, mean %.3f s, max %.3f s, TOTAL %.1f s"
              % (statistics.median(tot), statistics.mean(tot), max(tot), sum(tot)))
    rep = [r for r in ok if r.get("reproduces") is not None]
    print("  fidelity against the banked grid: %d of %d reproduce exactly"
          % (sum(1 for r in rep if r["reproduces"]), len(rep)))
    if mismatches:
        print("  *** MISMATCHES -- the banked numbers did NOT come from this code:")
        for c, s, a_, b_ in mismatches[:10]:
            print("      %-7s n%-4d banked %.6f  recomputed %.6f" % (c, s, a_, b_))
    print("  decomposition ab4 = fleet + travel + water holds on %d of %d"
          % (sum(1 for r in ok if r.get("decomposes")), len(ok)))
    car = [r for r in ok if r.get("carrier")]
    print("  carrier where a certified composed bound exists: ab4 %d, solver %d (of %d)"
          % (sum(1 for r in car if r["carrier"] == "ab4"),
             sum(1 for r in car if r["carrier"] == "solver"), len(car)))
    dep = [r for r in ok if r.get("carrier") and r.get("nH_frac")]
    if dep:
        w = [r["nH_frac"] for r in dep if r["carrier"] == "ab4"]
        l = [r["nH_frac"] for r in dep if r["carrier"] == "solver"]
        if w and l:
            print("  retained-set depth |H|/|C|: where AB4 carries, median %.3f (n=%d); "
                  "where the solver carries, median %.3f (n=%d)"
                  % (statistics.median(w), len(w), statistics.median(l), len(l)))
        elif w or l:
            print("  retained-set depth recorded on %d cells; only one carrier present" % len(dep))
    envd = [r for r in ok if r.get("envelope_before_s") and r.get("envelope_after_s")]
    if envd:
        sh = [100.0 * r["total_s"] / r["envelope_before_s"] for r in envd]
        print("  ENVELOPE COST of charging AB4: median %.4f%% of the cell envelope, max %.4f%%"
              % (statistics.median(sh), max(sh)))

    p = os.path.join(ROOT, "runs", "oracle", "ab4_grid_rt.json")
    # THE DETERMINISTIC CLOCK for a routine that does no search. AB4 is closed-form arithmetic
    # over the instance: no solver, no seed, no branching on data. Its work is therefore a
    # function of the instance DIMENSIONS alone, which is why the dimensions are the clock here
    # rather than a tick count. Stated plainly instead of dressed up as one: there is nothing to
    # count that is not already determined by (cells, sizes). What reproduces is the whole row.
    d = stamped(dict(rows=rows, sizes=a.sizes, cells=a.cells,
                     note="AB4 is deterministic arithmetic: no solver, no seed dependence"),
                *AB_SOURCES,
                det=dict(closed_form=1, cells=len(a.cells), sizes=list(a.sizes),
                         rows=len(rows),
                         basis="no search: work is fixed by the instance dimensions"))
    if not d.get("sources"):
        raise RuntimeError("refusing to write with an empty sources map")
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
