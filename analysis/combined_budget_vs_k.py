"""OUR TOTAL per-instance spend -- DUAL + PRIMAL -- against K's single 14,400 s.

THE WORRY, author-raised 2026-09-17, and it is correct:

    "K's RTs are for both LBs and OVs - ours are separated"

`RT_COMPARABILITY.md` section 2.1 states it and I quoted it earlier the same day without following
it through: *"K's 14,400 s buys an exact method producing primal solutions, dual bounds, AND
optimality proofs. Our LB run produces a dual bound only. Same clock, different products."*

Every budget comparison made today compared **our primal run alone** against K's 14,400 s. That
understates our spend, because their one clock also bought the bound we pay for separately. The
honest denominator is **dual + primal**.

WHAT THIS DOES AND DOES NOT CHANGE.
  * It does NOT affect validity: every solution is verifier-checked and every bound is a valid
    relaxation regardless of what they cost.
  * It DOES affect every fairness statement -- the "20% of K's budget" and "38% of K's budget"
    figures in `primal_target.py` are primal-only and therefore too favourable to us.
  * K's 14,400 s ALSO bought optimality proofs on the cells they closed, which we do not produce
    at all. So even dual+primal understates the asymmetry in their favour on those cells.

THE COMPARISON IS STILL NOT LIKE-FOR-LIKE and this file does not pretend otherwise. It reports the
ratio so the exposure is visible and sized, not so it can be argued away.
"""
import collections, glob, json, os, re, statistics as st, sys
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K_BUDGET = 14400.0


def dual_spend():
    out = collections.defaultdict(float)
    for f in glob.glob(os.path.join(ROOT, "crossfeed", "easy_reduction_descend_*_n*.json")):
        m = re.search(r"descend_((?:C|R|RC)\d{3})_n(\d+)\.json$", os.path.basename(f))
        if not m:
            continue
        try:
            recs = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        recs = recs if isinstance(recs, list) else [recs]
        w = sum(r.get("wall", 0) or 0 for r in recs if isinstance(r, dict))
        if w:
            out[(int(m.group(2)), m.group(1))] += w
    return out


def primal_spend():
    """per cell: (aggregate over all runs, worst single run)."""
    agg, worst = collections.defaultdict(float), collections.defaultdict(float)
    for f in glob.glob(os.path.join(ROOT, "runs", "fixopt_*_n*_*.jsonl")):
        m = re.search(r"fixopt_((?:C|R|RC)\d{3})_n(\d+)_", os.path.basename(f))
        if not m:
            continue
        key = (int(m.group(2)), m.group(1))
        try:
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        w = [r.get("wall_s") for r in rows if isinstance(r.get("wall_s"), (int, float))]
        if w:
            agg[key] += max(w)
            worst[key] = max(worst[key], max(w))
    return agg, worst


def main():
    D = dual_spend()
    Pagg, Pworst = primal_spend()
    sizes = sorted({k[0] for k in D} | {k[0] for k in Pagg})

    print("OUR TOTAL PER-INSTANCE SPEND vs K's 14,400 s, which bought their bound AND incumbent")
    print("(unadjusted: our seconds counted as equal to theirs -- RT_COMPARABILITY M3 rejects")
    print(" benchmark normalisation, and the exposure is reported without one)\n")
    print("%-6s %6s | %10s %12s %12s | %11s %11s" %
          ("size", "cells", "dual_s", "primal_1run", "primal_agg",
           "1run+dual", "agg+dual"))
    rows = {}
    for s in sizes:
        cells = sorted({k[1] for k in D if k[0] == s} & {k[1] for k in Pagg if k[0] == s})
        if len(cells) < 3:
            continue
        d = st.median([D[(s, c)] for c in cells])
        p1 = st.median([Pworst[(s, c)] for c in cells])
        pa = st.median([Pagg[(s, c)] for c in cells])
        rows[s] = dict(cells=len(cells), dual=d, primal_1run=p1, primal_agg=pa,
                       one_plus_dual=d + p1, agg_plus_dual=d + pa)
        print("%-6d %6d | %10.0f %12.0f %12.0f | %10.0f%% %10.0f%%" %
              (s, len(cells), d, p1, pa,
               100.0 * (d + p1) / K_BUDGET, 100.0 * (d + pa) / K_BUDGET))

    print("\n  the two right-hand columns are OUR TOTAL as a %% of K's single clock:")
    print("    1run+dual  -- one primal run plus the bound, the fair MEAN comparison")
    print("    agg+dual   -- all primal seeds plus the bound, the fair BEST-OF comparison")
    print("\n  AND IT IS STILL GENEROUS TO US: K's 14,400 s also bought OPTIMALITY PROOFS on the")
    print("  cells they closed (7 of 27 at |C| = 20), which we do not produce at all.")

    json.dump(stamped(dict(k_budget_s=K_BUDGET, sizes={str(k): v for k, v in rows.items()}), __file__),
              open(os.path.join(ROOT, "runs", "combined_budget_vs_k.json"), "w"), indent=1)
    print("\nwrote runs/combined_budget_vs_k.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
