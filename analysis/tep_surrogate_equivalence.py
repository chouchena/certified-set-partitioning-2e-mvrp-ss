"""Equivalence smoke: surrogate-scored search against the exact-scored one, same cells, seeds and budgets.

PREREG_uniform_pipeline.md S3 (ALNS) and Amendment 2 (refine). The two arms are written by the search
drivers in --no-bank mode under two tags; this reads them and applies the pre-registered kill rule:

    KILL if the median objective of the surrogate arm is worse than the exact arm by > 0.10 percent,
    or the surrogate is worse on more than 6 of 27 cells.

Nothing here is a result about the problem; it is a check of a design (surrogate evaluation with exact
confirmation before acceptance) at a size where the exact search is affordable.

    python analysis/tep_surrogate_equivalence.py --driver alns --exact smoke27_exact --sur smoke27_sur --size 30
"""
import argparse
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", choices=("alns", "refine"), default="alns")
    ap.add_argument("--exact", required=True); ap.add_argument("--sur", required=True)
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--kill-median", type=float, default=0.10); ap.add_argument("--kill-worse", type=int, default=6)
    a = ap.parse_args()
    key = "alns" if a.driver == "alns" else "refined"
    ikey = "incumbent" if a.driver == "alns" else "banked"      # the two drivers name the starting value differently
    E = {r["cell"]: r for r in json.load(io.open(os.path.join(ROOT, "runs", "oracle", "tep_%s_%s_n%d.json" % (a.driver, a.exact, a.size)), encoding="utf-8"))["cells"]}
    S = {r["cell"]: r for r in json.load(io.open(os.path.join(ROOT, "runs", "oracle", "tep_%s_%s_n%d.json" % (a.driver, a.sur, a.size)), encoding="utf-8"))["cells"]}
    cells = sorted(set(E) & set(S))
    rows = []
    print("%s equivalence at n%d, %d cells: exact arm vs surrogate arm (same seeds, same budgets, nothing banked)\n" % (a.driver, a.size, len(cells)))
    print("%-6s %10s %10s %10s %8s | %6s %6s | %8s %8s %6s" % ("cell", "incumbent", "exact", "surrogate", "sur-ex", "ex s", "sur s", "ex gain", "sur gain", "xcall"))
    for c in cells:
        e, s = E[c], S[c]
        ev, sv = float(e[key]), float(s[key]); inc = float(e[ikey])
        d = 100 * (sv / ev - 1)
        rows.append(dict(cell=c, incumbent=inc, exact=ev, surrogate=sv, sur_vs_exact_pct=d, exact_secs=e.get("secs"), sur_secs=s.get("secs"),
                         exact_gain_pct=100 * (ev / inc - 1), sur_gain_pct=100 * (sv / inc - 1), exact_calls=s.get("exact_calls")))
        print("%-6s %10.3f %10.3f %10.3f %+7.3f%% | %6.1f %6.1f | %+7.3f%% %+7.3f%% %6s"
              % (c, inc, ev, sv, d, float(e.get("secs") or 0), float(s.get("secs") or 0), 100 * (ev / inc - 1), 100 * (sv / inc - 1), s.get("exact_calls", "-")))
    d = [r["sur_vs_exact_pct"] for r in rows]
    worse = sum(1 for x in d if x > 1e-9); better = sum(1 for x in d if x < -1e-9); tie = len(d) - worse - better
    med = st.median(d); killed = (med > a.kill_median) or (worse > a.kill_worse)
    tex = sum(float(r["exact_secs"] or 0) for r in rows); tsu = sum(float(r["sur_secs"] or 0) for r in rows)
    print("\n  surrogate vs exact: median %+.3f%%, mean %+.3f%%, worst %+.3f%% | worse on %d, better on %d, tie on %d of %d"
          % (med, st.mean(d), max(d), worse, better, tie, len(d)))
    print("  time: exact arm %.0f s, surrogate arm %.0f s (%.1fx) | exact calls in the surrogate arm: median %s"
          % (tex, tsu, tex / max(tsu, 1e-9), st.median([r["exact_calls"] for r in rows if r["exact_calls"] is not None]) if any(r["exact_calls"] is not None for r in rows) else "-"))
    print("  gains vs incumbent: exact arm median %+.3f%% (improved %d), surrogate arm median %+.3f%% (improved %d)"
          % (st.median(r["exact_gain_pct"] for r in rows), sum(1 for r in rows if r["exact_gain_pct"] < -1e-9),
             st.median(r["sur_gain_pct"] for r in rows), sum(1 for r in rows if r["sur_gain_pct"] < -1e-9)))
    print("  KILL RULE (median > %.2f%% or worse on > %d): %s" % (a.kill_median, a.kill_worse, "KILLED" if killed else "NOT KILLED"))
    out = os.path.join(ROOT, "runs", "oracle", "tep_surrogate_equivalence_%s_n%d.json" % (a.driver, a.size))
    json.dump(stamped(dict(driver=a.driver, size=a.size, exact_tag=a.exact, sur_tag=a.sur, rows=rows, median_pct=med, worse=worse, better=better, killed=killed)),
              io.open(out, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
