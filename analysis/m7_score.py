"""Score M7 -- the matched-budget LBBD reproduction at |C| = 30 -- against its pre-registration.

PREREG: validation/PREREG_M7_n30_matched_budget.md

The primary outcome is fixed there and is NOT re-decidable here. It is a RATIO OF TWO MEANS
over the same 12 cells, denominator 12:

    R_lbbd  = mean( our bound / matched-budget reproduced LBBD bound )
    R_joint = mean( our bound / K's PUBLISHED Joint dual bound )
    REFUTED if  R_lbbd / R_joint < 0.85.

The claim under test is `beats-both-k-bounds-v3`: that our margin does not depend on which of
K's two bounds it is measured against. A collapse in R_lbbd/R_joint is what would show it does.

NUMERATOR IS THE MANUSCRIPT'S ESTIMATOR, NOT A LOCAL ONE -- `lb_estimator.cell_bound(...,
reproducible_only=True)`, the same call `m6_score.py` makes, so the n20 and n30 arms are
commensurable. `lb_crossing_samehw.our_bounds` uses a different rule (max over PROVEN records);
this script asserts the two agree rather than assuming it, exactly as M6 does.

THE n20 SIDE IS RECOMPUTED HERE, not quoted. The prereg cites "1.586 / 1.58 = 1.004" from the
register. Recomputing both sizes through identical code is what makes the pair PAIRED; quoting
a remembered figure would compare this script's estimator against a previous one's.

SIZE BUG THIS SCRIPT EXISTS DOWNSTREAM OF. `rt_fair_pipeline.py` stage 4 called
`rt_normalize.py` with no --size, and `rt_normalize`, `lb_coverage.k_paper_lb` and
`lb_crossing_samehw.our_bounds` were each hardcoded to 20. The M7 run therefore emitted a
complete, internally consistent |C| = 20 report under an n30 heading. The 12 n30 artifacts
were never affected. All four sites now carry the size; see runs/m7_n30_report_corrected.txt.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from analysis.lb_estimator import cell_bound                 # noqa: E402
from analysis.lb_crossing_samehw import our_bounds           # noqa: E402
from analysis.lb_coverage import k_paper_lb                  # noqa: E402
from analysis.rt_normalize import repro                      # noqa: E402
from analysis.rt_fair_pipeline import CELLS, k_lbbd_inct     # noqa: E402

THRESHOLD = 0.85          # prereg section 3. A choice, recorded there as one.


def our_bound(cell, size):
    """The manuscript's estimator, with the local one checked against it."""
    p = os.path.join(ROOT, "crossfeed", "easy_reduction_descend_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        p = os.path.join(ROOT, "crossfeed", "easy_reduction_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return None, "no descend artifact at n%d" % size
    recs = json.load(open(p, encoding="utf-8"))
    recs = recs if isinstance(recs, list) else [recs]
    cb = cell_bound(recs, reproducible_only=True)
    ob = our_bounds(cell, size)
    if cb is not None and ob and abs(cb - ob[0]) > 1e-6:
        return cb, "ESTIMATORS DIVERGE: cell_bound=%.3f our_bounds=%.3f" % (cb, ob[0])
    return cb, ""


def arm(size):
    """Returns (rows, notes). One row per cell; ratio is None if anything is missing."""
    KJ = k_paper_lb(size)
    # BUDGET, not wall. "At the cap" must mean the budget RULE hit 5400 s, which is a statement
    # about how much time the comparator was allowed. Wall >= 5400 is a different thing and
    # counts overrun as capping: R208 got a 5298 s budget and ran 5411 s, so a wall-based count
    # says 6 of 12 where the truth is 5.
    inct = k_lbbd_inct(size)
    rows, notes = [], []
    for c in CELLS:
        bud = min(5400.0, max(900.0, (inct.get(c) or 900.0) * 1.5))
        r = repro(c, size)
        ours, note = our_bound(c, size)
        if note:
            notes.append("n%d %s: %s" % (size, c, note))
        lb = r.get("bound") if r else None
        kj = KJ.get(c)
        rows.append(dict(cell=c, ours=ours, lbbd=lb, joint=kj, budget_s=bud,
                         r_lbbd=(ours / lb) if (ours and lb) else None,
                         r_joint=(ours / kj) if (ours and kj) else None,
                         status=(r or {}).get("status"), wall=(r or {}).get("wall"),
                         masters=(r or {}).get("masters")))
    return rows, notes


def score(rows, size):
    ok = [d for d in rows if d["r_lbbd"] is not None and d["r_joint"] is not None]
    if len(ok) != len(CELLS):
        return None, [d["cell"] for d in rows if d["r_lbbd"] is None or d["r_joint"] is None]
    R_lbbd = sum(d["r_lbbd"] for d in ok) / len(CELLS)
    R_joint = sum(d["r_joint"] for d in ok) / len(CELLS)
    return dict(size=size, R_lbbd=R_lbbd, R_joint=R_joint, ratio=R_lbbd / R_joint,
                wins_lbbd=sum(1 for d in ok if d["r_lbbd"] > 1.0),
                wins_joint=sum(1 for d in ok if d["r_joint"] > 1.0),
                converged=sum(1 for d in ok
                              if str(d["status"] or "").startswith("optimal")
                              or str(d["status"] or "") == "converged")), []


def main():
    out = {}
    for size in (20, 30):
        rows, notes = arm(size)
        s, missing = score(rows, size)
        out[size] = dict(rows=rows, notes=notes, score=s, missing=missing)

    print("=== M7 -- matched-budget LBBD reproduction at |C| = 30, scored against PREREG ===")
    print("    validation/PREREG_M7_n30_matched_budget.md")
    print("    budget: 1.5 x K's own per-cell LBBD IncT (floor 900 s, cap 5400 s), 4 threads")
    print("")
    print("%-7s %10s %10s %10s %8s %8s %11s %7s" %
          ("cell", "OUR bound", "repro LBBD", "K Joint LB", "r_lbbd", "r_joint", "status", "wall_s"))
    for d in out[30]["rows"]:
        print("%-7s %10s %10s %10s %8s %8s %11s %7s" % (
            d["cell"],
            "%.2f" % d["ours"] if d["ours"] else "MISSING",
            "%.2f" % d["lbbd"] if d["lbbd"] else "MISSING",
            "%.2f" % d["joint"] if d["joint"] else "MISSING",
            "%.3f" % d["r_lbbd"] if d["r_lbbd"] else "-",
            "%.3f" % d["r_joint"] if d["r_joint"] else "-",
            str(d["status"] or "-")[:11],
            "%.0f" % d["wall"] if d["wall"] else "-"))

    for size in (20, 30):
        if out[size]["score"] is None:
            print("")
            print("!! n%d: REFUSING TO SCORE -- missing %s" % (size, ", ".join(out[size]["missing"])))
            print("   The prereg fixes the denominator at %d and forbids substituting a subset."
                  % len(CELLS))
            for n in out[size]["notes"]:
                print("   " + n)
            return 1

    a, b = out[20]["score"], out[30]["score"]
    print("")
    print("PRIMARY OUTCOME (denominator fixed at %d by the prereg):" % len(CELLS))
    print("%-8s %10s %10s %15s %14s %14s" %
          ("|C|", "R_lbbd", "R_joint", "R_lbbd/R_joint", "wins vs LBBD", "wins vs Joint"))
    for s in (a, b):
        print("%-8d %10.3f %10.3f %15.3f %14s %14s" %
              (s["size"], s["R_lbbd"], s["R_joint"], s["ratio"],
               "%d of %d" % (s["wins_lbbd"], len(CELLS)),
               "%d of %d" % (s["wins_joint"], len(CELLS))))
    print("")
    print("  threshold: REFUTED if R_lbbd / R_joint < %.2f at |C| = 30." % THRESHOLD)
    print("  measured : %.3f" % b["ratio"])
    print("")
    print("PREREG SECTION 4 -- applied, not re-decided:")
    if b["ratio"] < THRESHOLD:
        print("  * %.3f < %.2f -> `beats-both-k-bounds-v3` is RETRACTED, naming M7."
              % (b["ratio"], THRESHOLD))
        print("    The manuscript's dual-results subsection is rewritten to report the collapse.")
    else:
        print("  * %.3f >= %.2f -> the falsifier DID NOT REFUTE the claim at |C| = 30."
              % (b["ratio"], THRESHOLD))
        print("    Write this as NOT REFUTED. Never as confirmed or validated -- a falsification")
        print("    test can only refute (CLAUDE.md section 2).")
    print("  * 12 of 27 cells at |C| = 30. Every figure carries that denominator, never 'the grid'.")
    print("  * converged %d of 12: a time-limited reproduction is a WEAK comparator and the"
          % b["converged"])
    print("    rt_normalize.py caution survives M7 in full.")
    print("  * RC201 stays in the denominator (prereg section 4).")

    p = os.path.join(ROOT, "runs", "m7_score.json")
    json.dump(stamped(dict(prereg="validation/PREREG_M7_n30_matched_budget.md",
                   threshold=THRESHOLD, n20=a, n30=b,
                   rows_n30=out[30]["rows"], rows_n20=out[20]["rows"],
                   notes=out[20]["notes"] + out[30]["notes"]), __file__),
              open(p, "w", encoding="utf-8"), indent=1)
    print("")
    print("wrote runs/m7_score.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
