"""Score M6 -- the matched-budget reproduction of K's LBBD -- against its pre-registration.

PREREG: validation/PREREG_M6_matched_budget_reproduction.md

The primary outcome is fixed there and is NOT re-decidable here:

    the mean ratio of OUR bound to the matched-budget reproduced LBBD bound, over the same
    12 cells, and the win count out of 12. Denominator 12, and not to be recomputed over a
    subset chosen after seeing results.

This script therefore hard-codes the denominator and refuses to score a partial set, so that a
crashed or missing cell cannot quietly shrink it into a flattering subset.

THE NUMERATOR IS THE MANUSCRIPT'S ESTIMATOR, NOT A LOCAL ONE. `lb_crossing_samehw.our_bounds`
takes a max over PROVEN records; `lb_estimator.cell_bound(..., reproducible_only=True)` takes a
max over records that were not stopped by the WALL clock, proven or not. Those are different
rules and only the second is what the paper reports. They agree on all 12 n20 cells as of
2026-09-16 -- so this is currently a distinction without a difference -- and the script asserts
that agreement rather than assuming it survives.

WHAT CANNOT BE RECOVERED, stated because the prereg asks for a before/after. Stage 1 of
`rt_fair_pipeline.py` rewrites `runs/lbbd_<cell>_n20_karademir.jsonl` IN PLACE and `runs/` is
gitignored, so the pre-M6 (900 s / 8-thread) per-cell BOUNDS are gone. What survives is:
  * the aggregate, from the claim register `beats-both-k-bounds-v2`: 1.58x vs Joint,
    1.59x vs reproduced LBBD, 11 of 12, sole loss RC201 at 0.99x;
  * the per-cell WORK UNITS, from validation/RT_LEG_DESIGN.md.
So the per-cell change in bound is not measurable and this script does not pretend otherwise --
it reports the per-cell change in work units, which is preserved, and the aggregate change in
bound, which is all the register kept.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from analysis.lb_estimator import cell_bound                 # noqa: E402
from analysis.lb_crossing_samehw import our_bounds           # noqa: E402
from analysis.rt_normalize import repro                      # noqa: E402
from analysis.rt_fair_pipeline import CELLS, k_lbbd_inct     # noqa: E402

# The pre-M6 comparator, preserved only in these two places. See the module docstring.
OLD_AGG = dict(mean_ratio_vs_lbbd=1.59, mean_ratio_vs_joint=1.58, wins=11, n=12,
               sole_loss="RC201", sole_loss_ratio=0.99,
               settings="900 s, 8 threads (CPLEX default = all cores)",
               source="claim register beats-both-k-bounds-v2")
# validation/RT_LEG_DESIGN.md -- master solves under the OLD 900 s / 8-thread comparator.
OLD_MASTERS = {"C203": 3, "C204": 3, "R204": 3, "R208": 3, "R211": 3, "RC202": 3, "RC204": 3,
               "R203": 14, "R207": 51, "RC203": 51, "RC208": 51, "RC201": 100}
NEW_SETTINGS = "1.5 x K own per-cell LBBD IncT (floor 900 s, cap 5400 s), 4 threads"


def our_bound(cell):
    """The manuscript's estimator, with the local one checked against it."""
    p = os.path.join(ROOT, "crossfeed", "easy_reduction_descend_%s_n20.json" % cell)
    if not os.path.exists(p):
        return None, "no descend artifact"
    recs = json.load(open(p, encoding="utf-8"))
    recs = recs if isinstance(recs, list) else [recs]
    cb = cell_bound(recs, reproducible_only=True)
    ob = our_bounds(cell)
    if cb is not None and ob and abs(cb - ob[0]) > 1e-6:
        return cb, "ESTIMATORS DIVERGE: cell_bound=%.3f our_bounds=%.3f" % (cb, ob[0])
    return cb, ""


def main():
    inct = k_lbbd_inct()
    rows, notes = [], []
    for c in CELLS:
        r = repro(c)
        ours, note = our_bound(c)
        if note:
            notes.append("%s: %s" % (c, note))
        ki = inct.get(c)
        bud = min(5400.0, max(900.0, (ki or 900.0) * 1.5))
        theirs = r.get("bound") if r else None
        ratio = (ours / theirs) if (ours and theirs) else None
        rows.append(dict(cell=c, k_inct=ki, budget_s=bud, ours=ours, theirs=theirs,
                         ratio=ratio, win=(ratio > 1.0) if ratio else None,
                         masters=(r or {}).get("masters"), cuts=(r or {}).get("cuts"),
                         iters=(r or {}).get("iters"), status=(r or {}).get("status"),
                         old_masters=OLD_MASTERS.get(c)))

    print("=== M6 -- matched-budget reproduction of K LBBD, scored against PREREG ===")
    print("    old comparator: %s" % OLD_AGG["settings"])
    print("    new comparator: %s" % NEW_SETTINGS)
    print("")
    print("%-7s%9s%9s%11s%11s%8s%5s%16s%10s" %
          ("cell", "K IncT", "budget", "OUR bound", "repro LB", "ratio", "win",
           "masters o->n", "status"))
    for d in rows:
        print("%-7s%9s%9s%11s%11s%8s%5s%16s%10s" % (
            d["cell"],
            "%.0f" % d["k_inct"] if d["k_inct"] else "-",
            "%.0f" % d["budget_s"],
            "%.2f" % d["ours"] if d["ours"] else "MISSING",
            "%.2f" % d["theirs"] if d["theirs"] else "MISSING",
            "%.3f" % d["ratio"] if d["ratio"] else "-",
            ("Y" if d["win"] else "n") if d["win"] is not None else "?",
            "%s -> %s" % (d["old_masters"], d["masters"]),
            str(d["status"] or "-")[:10]))

    scored = [d for d in rows if d["ratio"] is not None]
    print("")
    if len(scored) != len(CELLS):
        print("!! REFUSING TO SCORE: %d of %d cells produced a ratio." % (len(scored), len(CELLS)))
        print("   The prereg fixes the denominator at %d. Scoring the subset would be" % len(CELLS))
        print("   exactly the selection it forbids. Missing: %s"
              % ", ".join(d["cell"] for d in rows if d["ratio"] is None))
        for n in notes:
            print("   " + n)
        return 1

    mean_ratio = sum(d["ratio"] for d in scored) / len(CELLS)
    wins = sum(1 for d in scored if d["win"])
    print("PRIMARY OUTCOME (denominator fixed at %d by the prereg):" % len(CELLS))
    print("  mean ratio, ours / matched-budget reproduced LBBD : %.3f   (was %.2f)"
          % (mean_ratio, OLD_AGG["mean_ratio_vs_lbbd"]))
    print("  wins                                              : %d of %d   (was %d of %d)"
          % (wins, len(CELLS), OLD_AGG["wins"], OLD_AGG["n"]))
    losses = [d for d in scored if not d["win"]]
    print("  losses: %s" % (", ".join("%s %.3fx" % (d["cell"], d["ratio"]) for d in losses)
                            if losses else "none"))
    print("")

    print("PREREG SECTION 4 -- applied, not re-decided:")
    if mean_ratio < 1.0:
        print("  * mean ratio < 1.0 -> the standing claim is RETRACTED, naming M6 as cause.")
    else:
        print("  * mean ratio >= 1.0 -> the claim survives; its VALUE is superseded by M6.")
    if wins < 7:
        print("  * wins < 7 of 12 -> the '11 of 12' phrasing is WITHDRAWN, replaced by %d of 12."
              % wins)
    else:
        print("  * wins >= 7 of 12 -> phrasing updated to the measured %d of 12." % wins)
    print("  * the fairer comparator SUPERSEDES the unfair one in all cases; the 900 s")
    print("    reproduction is not retained on the grounds that it was measured first.")
    print("  * this remains OUR re-implementation on OUR hardware. rt_normalize.py caution")
    print("    that it is not K method on our machine survives M6 in full.")

    out = dict(prereg="validation/PREREG_M6_matched_budget_reproduction.md",
               new_settings=NEW_SETTINGS, old=OLD_AGG,
               mean_ratio=mean_ratio, wins=wins, n=len(CELLS), rows=rows, notes=notes)
    p = os.path.join(ROOT, "runs", "m6_score.json")
    json.dump(stamped(out, __file__), open(p, "w", encoding="utf-8"), indent=1)
    print("")
    print("wrote runs/m6_score.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
