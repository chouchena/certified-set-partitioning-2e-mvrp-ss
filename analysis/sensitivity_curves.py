#!/usr/bin/env python
"""The two sensitivity curves the paper owes a referee, both from banked data. No solver.

paper/SKELETON.md Part 7b lists eight sensitivity rows. Every one was marked "HAVE", which in
that file means only that artifacts exist -- not that anything is computed, quotable or written
up. Two of those rows carry a real result and neither had generating code until now:

  S-B2  THE ESCALATION BUDGET, marked "NOT RUN -- BLOCKING for any escalated result".
        It is no longer blocking. PREREG_n100 Amendment 4 established that every descent record
        carries `lb_curve`, a list of (elapsed, bound) pairs offset onto a per-cell timeline, and
        that the bound held at any T not exceeding the run's length is recoverable as the running
        maximum over points with elapsed <= T. That value is not an approximation of what a
        T-second run would have produced -- it IS what a T-second run would have produced, because
        every recorded value is a valid dual bound (L-step0) and the estimator is a max.
        Coverage is complete: 108 cells, 887 records, 217214 curve points, zero records without a
        curve. The skeleton's caveat -- "budget REDUCTIONS are replayable, INCREASES are not" --
        no longer bites, because the increases were run in the n100 equalisation.

  S-H   WLS, K's water:street cost ratio. K devote section 5.3 and a third of their Table 4 to
        it, and every MILP run we hold fixes 1:10. The arithmetic-bound sweep exists
        (runs/ab_wls_sweep.json, 540 evaluations) and had no registry entry and no finding.

WHICH ESTIMATOR THE BUDGET CURVE USES, and why it matters here specifically. Curve points are
taken from REPRODUCIBLE records only (limit_hit != "wall"), so the curve's terminal value equals
`lb_estimator.cell_bound` exactly. Mixing in wall-stopped records would make the curve end
somewhere the paper does not report. See validation/DECISION_reported_bound_estimator.md.

Usage:
    python analysis/sensitivity_curves.py            # both curves
    python analysis/sensitivity_curves.py --check    # exit 1 if a curve contradicts the estimator
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))

import lb_estimator  # noqa: E402

SIZES = (20, 30, 50, 100)
FRACTIONS = (0.25, 0.50, 0.75, 1.00)


def _cells(size):
    rx = re.compile(r"^easy_reduction_descend_([A-Z]+\d+)_n%d\.json$" % size)
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "crossfeed", "easy_reduction_descend_*.json"))):
        m = rx.match(os.path.basename(f))
        if m:
            out.append((m.group(1), f))
    return out


def cell_curve(records):
    """Pooled (elapsed, bound) over REPRODUCIBLE records, on the cell's own timeline.

    `t_start` is the cumulative wall at which the record began, and `lb_curve` is already offset
    onto that timeline by BoundTracer(offset=cumulative_wall) -- verified by checking that the
    final point of each record matches its block_relax.
    """
    pts = []
    for r in records:
        if not lb_estimator.is_reproducible(r):
            continue
        pts.extend((float(e), float(v)) for e, v in (r.get("lb_curve") or []))
    pts.sort()
    return pts


def bound_at(pts, T):
    best = None
    for e, v in pts:
        if e > T:
            break
        if best is None or v > best:
            best = v
    return best


def budget_curve():
    """For each size: the bound held at 25/50/75/100% of the cell's own realised budget,
    as a share of its terminal bound. A flat row means extra compute buys nothing."""
    out = {}
    for size in SIZES:
        rows = []
        for cell, path in _cells(size):
            recs = json.load(open(path))
            pts = cell_curve(recs)
            if not pts:
                continue
            total = max(e for e, _ in pts)
            term = bound_at(pts, total)
            if not term:
                continue
            # UNDEFINED IS NOT ZERO. A cell whose only reproducible record starts late has NO
            # reproducible bound before that point -- R205/n100 is the case: its k=67 and k=68
            # records are wall-stopped and excluded, and the surviving k=69 record does not begin
            # until t = 1806 of a 2696 s cell, so nothing exists at 25% or 50%.
            #
            # Scoring that as 0.0 would be a silent fabrication AND would drag the n100 row down
            # (0.9326/0.9449 became 0.9690/0.9820 once it was removed). `None` here, excluded from
            # the mean, and the count of undefined cells is printed beside the row.
            shares = []
            for f in FRACTIONS:
                b = bound_at(pts, total * f)
                shares.append((b / term) if b else None)
            rows.append((cell, total, term, shares))
        if rows:
            out[size] = rows
    return out


def wls_curve():
    """Our arithmetic bound as a share of K's best-known, by cost scenario.

    THE COMPARATOR IS min(Joint, LBBD), the registered rule -- not `joint` alone, which is what
    the by-family entries used and which understates our share unevenly across sizes.
    K publish all four WLS ratios only at sizes 10, 20 and 50 (table4).
    """
    import manuscript_numbers as M
    K = M._K()
    sw = json.load(open(os.path.join(ROOT, "runs/ab_wls_sweep.json")))

    def kbk(size, wls):
        r = {x["method"]: x["bk"] for x in K["table4"]
             if x["size"] == size and x["wls"] == wls}
        return min(r.values()) if r else None

    out = {}
    for wls in ("1:10", "1:5", "1:1", "10:1"):
        v = [x for x in sw.values() if x["size"] in (10, 20, 50) and x["wls"] == wls]
        out[wls] = {
            "share": st.mean(x["ab4"] / kbk(x["size"], wls) for x in v),
            "street_share": st.mean(x["travel"] / x["ab4"] for x in v),
            "n": len(v),
        }
    return out, sw


def invariance(sw):
    """Which bound components does WLS scale? The mechanism, checked arithmetically."""
    import collections
    out = {}
    for comp in ("travel", "water", "fleet", "penCars", "ab4"):
        g = collections.defaultdict(list)
        for k, v in sw.items():
            c, s, w = k.split("|")
            g[(c, s)].append(v[comp])
        out[comp] = max(max(v) - min(v) for v in g.values() if len(v) == 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    failures = []

    print("=" * 76)
    print("S-B2 / S-C  BUDGET CURVE -- bound at a fraction of the cell's own realised budget,")
    print("            as a share of its terminal bound. Reproducible records only.")
    print("=" * 76)
    bc = budget_curve()
    print("  %-6s %-6s %s  undefined" % ("size", "cells",
                                         "  ".join("%5.0f%%" % (f * 100) for f in FRACTIONS)))
    for size, rows in bc.items():
        means, undef = [], 0
        for i in range(len(FRACTIONS)):
            vals = [r[3][i] for r in rows if r[3][i] is not None]
            means.append(st.mean(vals) if vals else float("nan"))
            undef = max(undef, len(rows) - len(vals))
        print("  n%-5d %-6d %s  %d" % (size, len(rows),
                                       "  ".join("%6.4f" % m for m in means), undef))
    print()
    print("  worst DEFINED cell at 50%% of budget (where extra compute bought the most):")
    for size, rows in bc.items():
        d = [r for r in rows if r[3][1] is not None]
        if not d:
            continue
        w = min(d, key=lambda r: r[3][1])
        print("    n%-5d %-7s %.4f of terminal at half budget" % (size, w[0], w[3][1]))
    und = [(size, r[0]) for size, rows in bc.items() for r in rows if any(x is None for x in r[3])]
    if und:
        print("  undefined (no reproducible record that early): %s"
              % ", ".join("%s/n%d" % (c, s) for s, c in und))

    # THE CURVE MUST END WHERE THE REPORTED ESTIMATOR SAYS IT ENDS -- to the precision the two
    # can actually share, which is not exact equality, for two measured reasons:
    #
    #   * `block_relax` is stored ROUNDED TO 2 DECIMALS while `lb_curve` keeps full precision,
    #     so a curve point legitimately sits a few thousandths ABOVE its own record
    #     (C201/n50 k=0: curve 1633.1144, record 1633.11);
    #   * the tracer samples periodically and the final `block_relax` is read at termination,
    #     after the last sample, so the curve can also fall slightly SHORT. Measured worst case
    #     across all 108 cells: 0.0237% (C206/n20).
    #
    # 0.1% is therefore a tolerance the data can meet with room to spare, while a genuine defect
    # -- wrong records pooled, a broken `t_start` offset, a curve from another cell -- would be
    # orders of magnitude larger. Gating at 1e-6 flagged 45 of 108 cells and told us nothing.
    TOL = 1e-3
    for size, rows in bc.items():
        for cell, _total, term, _sh in rows:
            recs = json.load(open(os.path.join(
                ROOT, "crossfeed", "easy_reduction_descend_%s_n%d.json" % (cell, size))))
            cb = lb_estimator.cell_bound(recs, reproducible_only=True)
            if cb is None or abs(cb - term) / cb > TOL:
                failures.append(("curve-vs-estimator", cell, size, term, cb))

    print()
    print("=" * 76)
    print("S-H  WLS COST SCENARIO -- our arithmetic bound against K's best-known")
    print("     comparator min(Joint, LBBD); K publish all four ratios at n10/n20/n50 only")
    print("=" * 76)
    wc, sw = wls_curve()
    print("  %-8s %-14s %-16s %s" % ("wls", "street/bound", "bound / K best", "n"))
    for wls, d in wc.items():
        print("  %-8s %-14.3f %-16.3f %d" % (wls, d["street_share"], d["share"], d["n"]))
    print()
    inv = invariance(sw)
    print("  MECHANISM -- max spread of each component within a cell across the four ratios:")
    for comp, spread in inv.items():
        print("    %-8s %12.2f %s" % (comp, spread, "<-- INVARIANT" if spread < 1e-6 else ""))
    print()
    print("  Street travel is the ONLY component WLS does not scale, and it is where the bound's")
    print("  slack lives. As WLS rises that fixed term becomes a vanishing share of the objective")
    print("  and the bound approaches tight. This is arithmetic, not a fitted trend.")
    if inv["travel"] >= 1e-6:
        failures.append(("travel-not-invariant", inv["travel"]))

    if args.check:
        if failures:
            print("\nFAIL:")
            for f in failures:
                print("  ", f)
            return 1
        print("\nOK: every cell's curve terminates at the reported estimator, and street travel "
              "is invariant across all four cost scenarios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
