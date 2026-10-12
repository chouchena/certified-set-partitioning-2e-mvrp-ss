"""The n30 per-instance table: both legs, per cell, against the better of their two methods (d456).

WHY n30 IS THE BEST COMPARISON WE HAVE. They publish n30 PER INSTANCE -- all 27 cells, a best-known
from each of their two methods, a gap and a time to incumbent. n100 is per family only and n50 is
pooled by water-to-street ratio. So n30 is the largest size where a cell-by-cell claim is possible.

THE COMPARATOR IS THE BETTER OF THEIR TWO METHODS, via `k_comparison.k_best_incumbent`. Using
`k_targets_small.json`'s `k_inc` would compare against their Joint method alone, which their
decomposition beats on 23 of 27 cells at n30 -- by as much as 1047.2 against 843.6 on C203. That
mistake produced a withdrawn claim at n20 (d455) and is not repeated here.

Their per-cell bound is derived as `joint_bk * (1 - joint_gap/100)`, which is what `k_targets_small`
records as `k_bound`. A cell with gap 0 is PROVEN and our solution must not fall below it.

    python analysis/tep_n30_table.py
"""
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from k_comparison import k_best_incumbent
from stamp import stamped

SIZE = 30


def main():
    kt = {r["cell"]: r for r in json.load(io.open(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json"),
                                                 encoding="utf-8"))["n%d" % SIZE]["rows"]}
    ab = {(r["cell"], r["size"]): r for r in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"),
                                                               encoding="utf-8"))["records"]}
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "runs", "postpass", "ownwater_*_n%d.json" % SIZE))):
        c = os.path.basename(f).split("_")[1]
        ours = float(json.load(io.open(f, encoding="utf-8"))["objVal"])
        kb, which = k_best_incumbent(c, SIZE)
        bp = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d.json" % (c, SIZE))
        lb = None
        if os.path.exists(bp):
            d = json.load(io.open(bp, encoding="utf-8"))
            if d.get("proven") and d.get("start_states") and d.get("lp_street") is not None:
                lb = float(d["lp_street"]) + float(ab[(c, SIZE)]["water"])
        rows.append(dict(cell=c, ours=ours, theirs=kb, which=which,
                         proven=bool(kt[c]["proven"]), their_lb=float(kt[c]["k_bound"]), our_lb=lb))
    if not rows:
        print("no n30 solutions yet"); return
    print("n30, per instance. 'theirs' is the BETTER of their two published methods.\n")
    print("%-7s %9s %9s %6s %8s | %9s %9s %7s | %7s %7s"
          % ("cell", "ours", "theirs", "which", "vs them", "our LB", "their LB", "vs them", "our gap", "their gap"))
    below = []; defect = []
    for r in sorted(rows, key=lambda x: (x["ours"] / x["theirs"] - 1) if x["theirs"] else 0):
        d = 100.0 * (r["ours"] / r["theirs"] - 1) if r["theirs"] else None
        if d is not None and d < -0.05 / max(1.0, r["theirs"]) * 100 and r["ours"] < r["theirs"] - 0.05:
            (defect if r["proven"] else below).append(r["cell"])
        og = 100.0 * (1 - r["our_lb"] / r["ours"]) if r["our_lb"] else None
        tg = 100.0 * (1 - r["their_lb"] / r["theirs"]) if r["theirs"] else None
        print("%-7s %9.1f %9.1f %6s %+7.2f%% | %9s %9.1f %6s | %6s %6s"
              % (r["cell"], r["ours"], r["theirs"], r["which"], d,
                 ("%.1f" % r["our_lb"]) if r["our_lb"] else "-", r["their_lb"],
                 ("%.2fx" % (r["our_lb"] / r["their_lb"])) if r["our_lb"] else "-",
                 ("%.1f%%" % og) if og else "-", ("%.1f%%" % tg) if tg else "-"))
    dd = [100.0 * (r["ours"] / r["theirs"] - 1) for r in rows if r["theirs"]]
    print("\n  %d of 27 cells | median %+.2f%%, best %+.2f%%, worst %+.2f%%"
          % (len(rows), st.median(dd), min(dd), max(dd)))
    print("  BELOW their best on %d open cell(s): %s" % (len(below), ", ".join(below) if below else "none"))
    if defect:
        print("  *** BELOW a PROVEN optimum on %s -- a DEFECT, not a win ***" % ", ".join(defect))
    have = [r for r in rows if r["our_lb"]]
    if have:
        rb = sorted(r["our_lb"] / r["their_lb"] for r in have)
        print("  bound: ours above theirs on %d of %d | median %.2fx, max %.2fx"
              % (sum(1 for r in have if r["our_lb"] > r["their_lb"]), len(have), st.median(rb), rb[-1]))
        og = sorted(100.0 * (1 - r["our_lb"] / r["ours"]) for r in have)
        tg = sorted(100.0 * (1 - r["their_lb"] / r["theirs"]) for r in have)
        print("  bracket: ours median %.1f%% against theirs %.1f%%" % (st.median(og), st.median(tg)))
    p = os.path.join(ROOT, "runs", "oracle", "tep_n30_table.json")
    json.dump(stamped(dict(size=SIZE, rows=rows)), io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
