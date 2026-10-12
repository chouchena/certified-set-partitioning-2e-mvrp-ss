import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
"""G-a -- the estimator v6's CM1 MANDATED and no layer implemented.

v6, CM1: "K publish to one decimal, so the resolution is theirs: +/-0.05. An n10 route carries ~12
arcs and a 0.005 rounding slip per arc shifts z by ~0.06 -- right at that tolerance. So a per-cell
test cannot rule out the very class of distance error AM1 raised. Instead collect the signed
residuals `ours - K`. Rounding noise is SYMMETRIC about zero; a systematic rebuild error is BIASED.
Report mean, sign balance and spread -- NOT a pass count."

L1b reports a pass count. oracle_L3.py reports a pass count. Both were written after v6 said not to.

AND THE DENOMINATOR IS NOT WHAT v6 ASSUMED. v6 says "twenty-seven signed residuals detect a bias
far below the per-cell tolerance". They are not 27 independent residuals. Solomon's n10 instances
within a family share coordinates and demands and differ only in their time windows, and at n10
many of them have the SAME optimum: C201/C205/C206/C207 all return 365.489, R206/R207/R208 all
327.558. A distance-rebuild error moves identical instances identically, so repeated optima carry
one piece of evidence between them, not one each.

So this reports BOTH: the naive per-cell statistic, and the statistic over DISTINCT optima, which
is the honest denominator. Where they disagree, the distinct-optima figure is the one that may be
quoted.

    python analysis/oracle_residuals.py
"""
import json
import math
import os
import sys
from math import comb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "runs", "oracle")


def stats(res):
    n = len(res)
    if n < 2:
        return dict(n=n, mean=None, sd=None, neg=None, t=None, sign_p=None)
    mean = sum(res) / n
    sd = (sum((v - mean) ** 2 for v in res) / (n - 1)) ** 0.5
    neg = sum(1 for v in res if v < 0)
    t = None if sd == 0 else mean / (sd / math.sqrt(n))
    k = min(neg, n - neg)
    sign_p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
    return dict(n=n, mean=mean, sd=sd, neg=neg, pos=n - neg, t=t, sign_p=sign_p,
                lo=min(res), hi=max(res))


def show(label, s):
    if s["n"] < 2:
        print("   %-22s n=%d -- too few to estimate" % (label, s["n"]))
        return
    print("   %-22s n=%2d   mean %+.5f   sd %.5f   %2d neg / %2d pos   t %+.3f   sign p %.4f"
          % (label, s["n"], s["mean"], s["sd"], s["neg"], s["pos"],
             s["t"] if s["t"] is not None else float("nan"), s["sign_p"]))


def collapse(rows, keyfn, resfn):
    """One residual per DISTINCT optimum: repeated optima are one piece of evidence."""
    uniq = {}
    for r in rows:
        uniq.setdefault(keyfn(r), resfn(r))
    return list(uniq.values())


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("G-a -- SIGNED RESIDUAL DISTRIBUTION, the estimator v6's CM1 required.")
    print("       Rounding noise is symmetric about zero; a rebuild error is biased.")
    print()

    pools, out = [], {}

    l1b = os.path.join(OUT, "L1b.json")
    if os.path.exists(l1b):
        rows = [r for r in json.load(open(l1b, encoding="utf-8")) if r.get("proven")]
        if rows:
            print("L1b -- n10, K's Table 3")
            per_cell = [r["residual"] for r in rows]
            distinct = collapse(rows, lambda r: round(r["ours"], 3), lambda r: r["residual"])
            show("per cell", stats(per_cell))
            show("distinct optima", stats(distinct))
            npass = sum(1 for r in rows if r.get("rounds_to_k"))
            print("   pass count (what was reported before): %d/%d round to K"
                  % (npass, len(rows)))
            print("   repeated optima collapsed: %d cells -> %d distinct"
                  % (len(per_cell), len(distinct)))
            pools += distinct
            out["L1b"] = dict(per_cell=stats(per_cell), distinct=stats(distinct),
                              pass_count=npass, cells=len(rows))
            print()

    l3 = os.path.join(OUT, "L3.jsonl")
    if os.path.exists(l3):
        rows = []
        for line in open(l3, encoding="utf-8"):
            r = json.loads(line)
            if r.get("vac_proven") and r.get("vac_delta") is not None:
                rows.append(r)
        if rows:
            print("L3 -- n20/n30, K's Table 3, K's own vacuous arm")
            per_cell = [r["vac_delta"] for r in rows]
            distinct = collapse(rows, lambda r: round(r["vac_obj"], 3),
                                lambda r: r["vac_delta"])
            show("per cell", stats(per_cell))
            show("distinct optima", stats(distinct))
            print("   repeated optima collapsed: %d cells -> %d distinct"
                  % (len(per_cell), len(distinct)))
            pools += distinct
            out["L3"] = dict(per_cell=stats(per_cell), distinct=stats(distinct),
                             cells=len(rows))
            print()

    if len(pools) >= 2:
        s = stats(pools)
        print("POOLED across layers, distinct optima only")
        show("pooled", s)
        out["pooled"] = s
        print()
        biased = (s["t"] is not None and abs(s["t"]) > 2.06) or s["sign_p"] < 0.05
        print("   VERDICT: %s" % ("BIAS DETECTED -- the residuals are not centred on zero, which "
                                  "is a rebuild finding, not rounding" if biased else
                                  "NO BIAS DETECTED. The residuals are consistent with K's own "
                                  "one-decimal rounding."))
        print()
        print("   WHAT THIS DOES NOT SAY. 'No bias detected' at n=%d is not 'no bias'. The"
              % s["n"])
        print("   detectable effect at this sample is roughly sd/sqrt(n) x 2 = %+.4f; an error"
              % (2 * s["sd"] / math.sqrt(s["n"])))
        print("   smaller than that passes. And every residual comes through ONE rebuild code")
        print("   path, so a defect that shifts every instance equally shifts the mean and the")
        print("   spread together and is invisible to a symmetry test.")
        print()
        print("   CORRECTION TO v6. CM1 claims 'twenty-seven signed residuals'. The independent")
        print("   count is %d, because repeated optima carry one piece of evidence between them."
              % out.get("L1b", {}).get("distinct", {}).get("n", 0))

    json.dump(stamped(out, __file__), open(os.path.join(OUT, "residuals.json"), "w"),
              indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
