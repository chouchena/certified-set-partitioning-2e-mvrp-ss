"""Does our TOTAL compute per instance exceed K's, after hardware normalisation?

THE CONSTRAINT, author-stated 2026-09-17: "The total RT budget should not exceed K's one AFTER
NORMALIZATION." This is a fairness constraint on the QUALITY comparison, and it is distinct from
the timing question already settled (`we do not race K on speed`). That decision says we never
claim to be FASTER. This says we must not have been GIVEN MORE.

K'S BUDGET. 4 h = 14,400 s per instance, main model; subproblem 50 s (|C| <= 30) / 100 s
(|C| = 100). Hardware: 4x Xeon Gold 5218 @ 2.30 GHz, 4 cores. Source: paper-reference-data.md.

NORMALISATION IS REJECTED BY THIS PROJECT, AND THE FIRST VERSION OF THIS FILE USED IT ANYWAY.
`validation/RT_COMPARABILITY.md` metric M3 -- "normalise by a CPU benchmark" -- is marked
**REJECT: cannot run their hardware; any factor would be invented**, and its section 2 gives FOUR
independent reasons no scalar converts: different deliverable (their 14,400 s buys an exact method
with optimality proofs, ours a dual bound only), different solver (deterministic ticks do not
transfer across Gurobi and CPLEX), different hardware generation, different stopping semantics.
The first version leaned on rt_normalize's prose "roughly twice the clock" as though it were a
measurement. It is not one.

NOR CAN THE MEASUREMENT WE HAVE SUPPLY A FACTOR. M6/M7 ran K's OWN METHOD on our machine -- the one
route that ELIMINATES the hardware term instead of estimating it. We reach a median 0.99 (n20) and
1.03 (n30) of K's published LB using 16% and 32% of their wall budget, converging 0 of 12 at both
sizes. That LOOKS like 3-6x throughput, but it is CONFOUNDED with the bound's own
budget-insensitivity: `budget-sensitivity` shows 94-98% of the terminal bound is already held at
25% of budget. Hardware speed and an early plateau are not separable from this measurement.

SO THE HEADLINE IS FACTOR-FREE: the x1.0 column, our wall seconds counted as equal to theirs with
no adjustment at all. That is the assumption most favourable to US, since a 2024 Core Ultra almost
certainly does more per core than a 2019 Xeon Gold, which would make our spend count for MORE. An
exposure that survives at 1.0x needs no invented number. The other columns show the direction of
travel ONLY and must never be quoted as a normalisation.

THE ACCOUNTING THAT MATTERS IS PER CELL, NOT PER RUN. We report a BEST-OF over many runs per cell
(portfolio, many seeds, bespoke probes). A referee asked "what did it cost to produce that number"
would sum every run on that cell, not quote the cheapest. Reporting per-run budgets while
reporting best-of results is the exposure this checks for.

WHAT THIS DOES NOT COVER. The dual leg (descent/LB campaigns) is budgeted separately and is not
summed here; nor are constructions, which are sub-second. This is the PRIMAL compute only, which
is where the best-of accumulates.
"""
import argparse, collections, glob, json, os, re, statistics as st, sys
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K_LIMIT_S = 14400.0          # 4 h per instance, paper-reference-data.md


def per_cell_totals():
    per, runs = collections.defaultdict(float), collections.Counter()
    for f in glob.glob(os.path.join(ROOT, "runs", "fixopt_*_n*_*.jsonl")):
        m = re.search(r"fixopt_((?:C|R|RC)\d{3})_n(\d+)_", os.path.basename(f))
        if not m:
            continue
        cell, size = m.group(1), int(m.group(2))
        try:
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        w = [r.get("wall_s") for r in rows if isinstance(r.get("wall_s"), (int, float))]
        if not w:
            continue
        per[(size, cell)] += max(w)          # this run's own wall
        runs[(size, cell)] += 1
    return per, runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factors", default="1.0,1.5,2.0,2.5",
                    help="candidate hardware factors: how many K-seconds one of our seconds buys")
    a = ap.parse_args()
    factors = [float(x) for x in a.factors.split(",")]

    per, runs = per_cell_totals()
    sizes = sorted({k[0] for k in per})

    print("PRIMAL compute already spent PER CELL (sum of wall over every run on that cell)")
    print("%-6s %7s %11s %11s %11s %11s" %
          ("size", "cells", "median_s", "p90_s", "max_s", "med runs"))
    tots = {}
    for sz in sizes:
        v = sorted(per[k] for k in per if k[0] == sz)
        r = sorted(runs[k] for k in runs if k[0] == sz)
        if len(v) < 3:
            continue
        tots[sz] = v
        print("%-6d %7d %11.0f %11.0f %11.0f %11d" %
              (sz, len(v), st.median(v), v[int(0.9 * len(v))], max(v), st.median(r)))

    print("\nK's budget: %.0f s per instance on 4x Xeon Gold 5218 @2.30GHz, 4 cores." % K_LIMIT_S)
    print("HEADLINE IS THE x1.0 COLUMN -- our wall seconds counted as equal to theirs, with NO")
    print("normalisation. RT_COMPARABILITY.md M3 rejects benchmark normalisation outright (\"any")
    print("factor would be invented\"), and M6/M7 cannot supply one either: hardware throughput is")
    print("confounded with the bound's own early plateau. Columns right of x1.0 show the direction")
    print("of travel ONLY and must not be quoted as a normalisation.\n")

    print("%-6s %12s | %s" % ("size", "our median_s",
                              " ".join("%14s" % ("x%.1f -> %% of K" % f) for f in factors)))
    verdicts = {}
    for sz in sizes:
        if sz not in tots:
            continue
        med = st.median(tots[sz])
        cells = []
        over = []
        for f in factors:
            pct = 100.0 * (med * f) / K_LIMIT_S
            cells.append("%13.0f%%" % pct)
            over.append(pct > 100.0)
        verdicts[sz] = over
        print("%-6d %12.0f | %s" % (sz, med, " ".join("%14s" % c for c in cells)))

    print("\n%-6s %12s | %s" % ("size", "our p90_s",
                                " ".join("%14s" % ("x%.1f -> %% of K" % f) for f in factors)))
    for sz in sizes:
        if sz not in tots:
            continue
        p90 = tots[sz][int(0.9 * len(tots[sz]))]
        print("%-6d %12.0f | %s" % (sz, p90,
              " ".join("%13.0f%%" % (100.0 * (p90 * f) / K_LIMIT_S) for f in factors)))

    print("\nVERDICT by size (median cell), across the plausible factor range:")
    any_over = False
    for sz in sizes:
        if sz not in verdicts:
            continue
        o = verdicts[sz]
        if all(o):
            print("  n%-4d OVER K's budget at EVERY factor tested -- a real fairness exposure" % sz)
            any_over = True
        elif any(o):
            print("  n%-4d over at some factors only -- the conclusion DEPENDS on a number"
                  " rt_normalize calls the weakest evidence available" % sz)
            any_over = True
        else:
            print("  n%-4d within K's budget at every factor tested" % sz)
    if not any_over:
        print("\n  No size exceeds K's normalised budget on the median cell.")
    print("\n  READ ONLY THE x1.0 COLUMN AS A RESULT. Everything right of it rests on a factor that")
    print("  RT_COMPARABILITY.md M3 rejects as invented, and that the M6/M7 measurement cannot")
    print("  supply because hardware throughput is confounded with the bound's early plateau.")

    out = {}
    for sz in sizes:
        if sz not in tots:
            continue
        v = tots[sz]
        p90 = v[int(0.9 * len(v))]
        out[str(sz)] = dict(cells=len(v), median_s=round(st.median(v), 1),
                            p90_s=round(p90, 1), max_s=round(max(v), 1),
                            pct_of_K_unadjusted=round(100.0 * st.median(v) / K_LIMIT_S, 1),
                            p90_pct_of_K_unadjusted=round(100.0 * p90 / K_LIMIT_S, 1))
    json.dump(stamped(dict(k_limit_s=K_LIMIT_S,
                   headline="x1.0 ONLY -- RT_COMPARABILITY M3 rejects benchmark normalisation",
                   sizes=out), __file__),
              open(os.path.join(ROOT, "runs", "rt_budget_fairness.json"), "w"), indent=1)
    print("\nwrote runs/rt_budget_fairness.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
