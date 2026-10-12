"""Per METHOD, before the best-of: what each dual sweep cost and what it was worth.

WHY (author, 2026-09-29): "Do we have per method RT and values before best of?" -- yes. 454 of
543 bound artifacts carry their own `_command`, alongside `lp_street`, `secs`, `delta` and `ng`.
The banked grid is a best-of over several per-size sweeps, so the per-sweep values and walls
survive underneath it and can be read back.

THE NUMBER THAT MATTERS IS THE MARGINAL ONE. A method's win count flatters it: two methods that
agree on a cell both "win" when one would have done. What a portfolio has to justify is the
MARGINAL contribution -- how much the per-cell maximum falls if that method is removed and the
others keep their values. A method with a large win count and zero marginal contribution is
redundant and its wall is waste.

CHARGING. Every method that ran is charged, whether or not it won (d245/d246/d250, and
bound_source: "the reported value could have come from either, so neither is free"). So the
cost column is the method's TOTAL wall over the cells it ran on, not the wall of its wins.

SCOPE. Reads only artifacts that could carry a reported bound: a value present, not ceil-rounded
(a restriction, d414), not a reduced instance (the proof covers block A, not the TEP master on a
subset), and certified either elementary or ng.

    python analysis/lb_method_ablation.py
    python analysis/lb_method_ablation.py --sizes 50
"""
import argparse
import collections
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from best_known import bound_artifacts
from bound_certificate import certified, ng_certified
from stamp import stamped

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])


def method(d):
    """The invocation, normalised: script path and cell name dropped, flags kept and sorted."""
    c = d.get("_command")
    if not c:
        return "(no _command recorded)"
    toks = [x for x in c.split()[1:] if not x.endswith(".py") and x not in CELLS]
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t.startswith("--") and i + 1 < len(toks) and not toks[i + 1].startswith("--"):
            out.append("%s=%s" % (t, toks[i + 1])); i += 2
        else:
            out.append(t); i += 1
    out = [x for x in out if not x.startswith("--size")]
    return " ".join(sorted(out)) or "(defaults)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100])
    a = ap.parse_args()
    rows = []
    for size in a.sizes:
        # per cell: {method: (value, secs)}
        per = {}
        for c in CELLS:
            m = {}
            for q, d in bound_artifacts(c, size):
                if d.get("lp_street") is None or d.get("primal_rounding") or d.get("drop"):
                    continue
                if not (certified(d) or ng_certified(d)):
                    continue
                k = method(d)
                v, s = float(d["lp_street"]), float(d.get("secs") or 0.0)
                if k not in m or v > m[k][0]:
                    m[k] = (v, s)
            if m:
                per[c] = m
        if not per:
            continue
        meths = sorted({k for m in per.values() for k in m})
        print("n%d -- %d cells, %d distinct methods" % (size, len(per), len(meths)))
        print("  %-52s %5s %9s %9s %6s %11s"
              % ("method", "cells", "median_s", "total_h", "wins", "marginal"))
        tab = []
        for k in meths:
            cells = [c for c in per if k in per[c]]
            secs = [per[c][k][1] for c in cells]
            wins = sum(1 for c in cells
                       if per[c][k][0] >= max(v for v, _ in per[c].values()) - 1e-9)
            # marginal: how much the per-cell max falls if this method is removed
            marg = 0.0
            for c in per:
                vals = [v for kk, (v, _) in per[c].items()]
                without = [v for kk, (v, _) in per[c].items() if kk != k]
                if vals and without:
                    marg += max(vals) - max(without)
                elif vals and not without:
                    marg += 0.0        # sole method: removing it loses the cell, not a delta
            tab.append((marg, k, len(cells), statistics.median(secs), sum(secs) / 3600.0, wins))
        for marg, k, n, med, tot, wins in sorted(tab, key=lambda t: -t[0]):
            print("  %-52s %5d %9.0f %9.2f %6d %11.1f" % (k[:52], n, med, tot, wins, marg))
            rows.append(dict(size=size, method=k, cells=n, median_s=med, total_h=tot,
                             wins=wins, marginal=marg))
        tot_h = sum(t[4] for t in tab)
        useful = [t for t in tab if t[0] > 1e-6]
        print("  -> %d of %d methods have ANY marginal contribution; "
              "the rest cost %.2f h of the %.2f h and add nothing\n"
              % (len(useful), len(tab), sum(t[4] for t in tab if t[0] <= 1e-6), tot_h))

    p = os.path.join(ROOT, "runs", "oracle", "lb_method_ablation.json")
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(stamped(dict(rows=rows), "analysis/lb_method_ablation.py",
                          "analysis/best_known.py", "analysis/bound_certificate.py"),
                  f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
    print("wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
