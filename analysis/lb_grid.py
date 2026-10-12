"""THE LOWER-BOUND GRID: every cell, every instrument, its value, its runtime and its provenance.

WHY (author, 2026-09-29): "produce a performant LB grid (vs banked previous results and RTs) and
commit it with full values, AB4/solver/max, RTs and provenance".

THREE INDEPENDENT INSTRUMENTS, and the reported bound is the max of whichever are available:

  descent   the frozen block-A leg. Validity is a PROOF (validation/easy_reduction_bound_proof.md
            steps 1-2, extended by step 0 to any valid dual bound of the same problem).
  solver    the TEP column-generation composed bound, LP street + AB water, reportable ONLY
            behind an elementary certificate (d427/d519: an unconverged master's LP is an upper
            bound on the relaxation, not a lower bound on the problem).
  ab4       the closed-form arithmetic bound. Deterministic arithmetic on instance data: no
            solver, no seed, and NO certificate needed -- which is why it still carries a cell
            whose pricing never converged.

max(a, b, c) of valid lower bounds is a valid lower bound. SKELETON states the portfolio rule;
TEP_FORMULATION section 5 now states the AB4 half of it too.

EVERY INSTRUMENT IS CHARGED (d245/d246/d250). The reported value could have come from any of
them, so none is free: the charged figure is the sum of the walls of the instruments that ran,
and the primal's envelope is 5760 - that sum.

WHAT THIS FILE DOES NOT DO. It does not compute a bound. Every value comes from an existing
authority -- bound_source for descent/solver/ab4 and their maximum, best_known for the banked
comparison -- so that this grid cannot disagree with the rest of the repo. A second copy of a
lookup is the defect analysis/single_authority.py exists to stop.

    python analysis/lb_grid.py
    python analysis/lb_grid.py --sizes 30 50
"""
import argparse
import collections
import io
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
import bound_source as BS
from best_known import best_bound, best_solution
from stamp import stamped

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
SOURCES = ("analysis/lb_grid.py", "analysis/bound_source.py", "analysis/best_known.py",
           "analysis/bound_certificate.py", "crossfeed/fullset_bound.py",
           "analysis/run_full_grid.py")


def cell_budget(size, cell):
    """K's cap on our machine: K_CAP / HW factor. NOT run_full_grid.envelope.

    envelope() returns K_CAP/factor MINUS lb_cell_seconds, i.e. the budget with the dual leg
    ALREADY deducted. This grid then charges descent_s, which IS lb_cell_seconds -- so using
    envelope() here deducts the dual leg twice. It did, and it inflated "cells over budget"
    from 2 to 11 (R208 n50 read -4203.7 s remaining when the truth is -2719.9). The project has
    hit this exact error before: "THE EARLIER RUNTIME-HEADROOM FIGURES DOUBLE-DEDUCTED THE LB
    LEG". The full cap is the right starting point when the charge is itemised from zero.
    """
    try:
        import run_full_grid as G
        return float(G.K_CAP_THEIR_SECONDS) / float(G.HW_FACTOR_ENVELOPE)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100])
    ap.add_argument("--allow-suspended", action="store_true",
                    help="also report the TEP bound at n100, where it is suspended by claim "
                         "tep-cg-bounds-suspended-pending-proof. OFF by default on purpose.")
    a = ap.parse_args()

    print("LOWER-BOUND GRID -- descent / solver(TEP) / AB4, their max, runtimes and provenance\n")
    print("  %-7s %-5s %10s %10s %10s %11s %-8s %9s %9s  %s"
          % ("cell", "size", "descent", "solver", "ab4", "REPORTED", "carrier",
             "charged", "envelope", "vs banked"))
    rows = []
    for size in a.sizes:
        for cell in CELLS:
            t0 = time.time()
            r = BS.bound_for(cell, size, source="best", allow_suspended=a.allow_suspended)
            comp, ab4_half, tep_rep = BS.tep_bound_parts(cell, size,
                                                         allow_suspended=a.allow_suspended)
            _tv, tep_secs, tep_why = BS.tep_bound(cell, size, allow_suspended=a.allow_suspended)
            _dv, desc_secs = BS.descent_bound(cell, size)
            env0 = cell_budget(size, cell)
            bb = best_bound(cell, size)
            bs = best_solution(cell, size)
            rec = dict(
                cell=cell, size=size,
                descent=r.get("descent_value"), solver=r.get("tep_value"), ab4=r.get("ab4_value"),
                reported=r.get("value"), carrier=r.get("winner"),
                solver_composed=comp, solver_why=tep_why,
                descent_s=desc_secs, solver_s=tep_secs, ab4_s=BS._ab4_seconds(cell, size),
                charged_s=r.get("charged"),
                budget_s=env0, envelope_before_s=env0,
                envelope_after_s=(None if env0 is None or r.get("charged") is None
                                  else round(env0 - r["charged"], 1)),
                banked_bound=(bb[0] if bb else None),
                banked_class=(bb[1] if bb else None),
                banked_artifact=(bb[2] if bb else None),
                ov=(float(bs[0]) if bs else None),
                lookup_s=round(time.time() - t0, 3))
            # the two checks that matter, run on every row rather than asserted once
            rec["valid_vs_ov"] = (None if rec["reported"] is None or rec["ov"] is None
                                  else rec["reported"] <= rec["ov"] + 1e-6)
            rec["delta_vs_banked"] = (None if rec["reported"] is None or rec["banked_bound"] is None
                                      else rec["reported"] - rec["banked_bound"])
            rec["gap_pct"] = (None if not rec["reported"] or not rec["ov"]
                              else 100.0 * (rec["ov"] - rec["reported"]) / rec["reported"])
            print("  %-7s n%-4d %10s %10s %10s %11s %-8s %9s %9s  %s"
                  % (cell, size,
                     "%.1f" % rec["descent"] if rec["descent"] else "-",
                     "%.1f" % rec["solver"] if rec["solver"] else "-",
                     "%.1f" % rec["ab4"] if rec["ab4"] else "-",
                     "%.1f" % rec["reported"] if rec["reported"] else "NONE",
                     rec["carrier"] or "-",
                     "%.0f" % rec["charged_s"] if rec["charged_s"] else "-",
                     "%.0f" % rec["envelope_after_s"] if rec["envelope_after_s"] else "-",
                     ("%+.1f" % rec["delta_vs_banked"]) if rec["delta_vs_banked"] else "same"),
                  flush=True)
            rows.append(rec)

    ok = [r for r in rows if r["reported"] is not None]
    print("\n  cells %d | with a bound %d | without %d" % (len(rows), len(ok), len(rows) - len(ok)))
    bad = [r for r in ok if r["valid_vs_ov"] is False]
    print("  SOUNDNESS: bounds exceeding a verified incumbent: %d%s"
          % (len(bad), "" if not bad else "  *** " + ", ".join(
              "%s n%d" % (r["cell"], r["size"]) for r in bad[:6])))
    car = collections.Counter(r["carrier"] for r in ok)
    print("  carrier: %s" % dict(car))
    for s in a.sizes:
        g = [r for r in ok if r["size"] == s]
        if not g:
            continue
        c = collections.Counter(r["carrier"] for r in g)
        ch = [r["charged_s"] for r in g if r["charged_s"]]
        print("    n%-5d %-46s charged median %7.0f s  max %7.0f s"
              % (s, str(dict(c)), statistics.median(ch) if ch else 0, max(ch) if ch else 0))
    imp = [r for r in ok if r["delta_vs_banked"] and r["delta_vs_banked"] > 1e-6]
    reg = [r for r in ok if r["delta_vs_banked"] and r["delta_vs_banked"] < -1e-6]
    print("  VS BANKED: higher on %d, lower on %d, unchanged on %d"
          % (len(imp), len(reg), len(ok) - len(imp) - len(reg)))
    if imp:
        print("    gains: median +%.1f  max +%.1f"
              % (statistics.median([r["delta_vs_banked"] for r in imp]),
                 max(r["delta_vs_banked"] for r in imp)))
    if reg:
        print("    REGRESSIONS (must be explained, not averaged away):")
        for r in sorted(reg, key=lambda x: x["delta_vs_banked"])[:8]:
            print("      %-7s n%-4d reported %.1f against banked %.1f (%+.1f) banked from %s"
                  % (r["cell"], r["size"], r["reported"], r["banked_bound"],
                     r["delta_vs_banked"], os.path.basename(str(r["banked_artifact"]))))
    gaps = [r["gap_pct"] for r in ok if r["gap_pct"] is not None]
    if gaps:
        print("  gap to the verified incumbent, (OV-LB)/LB: median %.2f%%  best %.2f%%"
              % (statistics.median(gaps), min(gaps)))

    p = os.path.join(ROOT, "runs", "oracle", "lb_grid.json")
    # THE DETERMINISTIC CLOCK for a pure lookup. This grid runs no solver: it reads banked
    # artifacts and takes a max. Its own cost is fixed by how much it read, so that is the
    # clock. The SOLVER seconds it reports per row are the runtimes of the artifacts it read,
    # each of which carries its own det_ticks -- this row's clock is not a substitute for them.
    d = stamped(dict(rows=rows, sizes=a.sizes, allow_suspended=bool(a.allow_suspended),
                     instruments=["descent", "solver", "ab4"]), *SOURCES,
                det=dict(lookup_only=1, rows=len(rows), sizes=list(a.sizes),
                         basis="reads banked artifacts and takes a max; runs no solver"))
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
