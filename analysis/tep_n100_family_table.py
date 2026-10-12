"""The n100 headline: both legs, per family, against the predecessors' published figures (d453).

WHY PER FAMILY. They publish n100 in Table 6 per family, not per instance, so a family mean is the
only like-for-like comparison at this size. A per-cell figure against a family mean is the weaker
comparison this project already agreed to at d347 and is not used here.

BOTH LEGS ARE OURS. The primal is master IP -> our chaining model -> our vessel-tour consolidation,
with no predecessor model (d451). The dual is the easy-reduction idea mimicked over our master:
prove a reduced customer set, add the full-set water term (d448). The descent leg and the relaxed
exact model are both excluded because they are built on their compact model.

WHAT IS AND IS NOT A COMPARISON:
  * our incumbent mean vs their incumbent mean -- like for like, this is the primal claim
  * our bound mean vs their bound mean -- like for like, this is the dual claim
  * our GAP vs their GAP -- the bracket comparison, and the one a referee will look at
  * a cell with no solution of ours is EXCLUDED from our mean and the exclusion is printed. A mean
    over a favourable subset is not a family mean.

    python analysis/tep_n100_family_table.py
"""
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import kref
from stamp import stamped
from bound_certificate import certified, bound_class   # d519 certificate; bound_class adds the ng class (2026-09-27)

FAM = lambda c: "RC" if c.startswith("RC") else c[0]
CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])


def our_primal():
    """Best VERIFIED primal per cell over every production configuration dir (2026-09-27: was the floor artifact only,
    which would have kept the ceil sweep gains out of the headline table)."""
    out = {}
    for sub in ("", "ceil", "selchain", "forced", "refine", "alns", "masterip"):
        for f in glob.glob(os.path.join(ROOT, "runs", "postpass", sub, "ownwater_*_n100.json")):
            c = os.path.basename(f).split("_")[1]; v = float(json.load(io.open(f, encoding="utf-8"))["objVal"])
            out[c] = v if c not in out else min(out[c], v)
    return out


def our_bound():
    """The max over every VALID bound for a cell, with the certificate class of the winner.

    TWO SOURCES, TWO CLASSES (2026-09-27). Until today this read only the subset instrument, whose
    elementary pass converges because the customer set is reduced, and the whole-instance runs were
    discarded because their elementary pass exhausted its label cap. But those runs carry a second,
    weaker certificate: the ng-route class converged at full length on the true duals with no
    candidate below the cut, which makes their LP the optimum over a class that CONTAINS the
    elementary routes, hence a valid lower bound (`bound_certificate.ng_certified`). On the 18 cells
    where both exist the whole-instance ng bound is the higher one, by 125 to 418 cost units, and the
    dual side takes the max of valid bounds (settled 2026-09-13).

    Returns {cell: (value, class, source)}.
    """
    best = {}

    def offer(c, v, klass, src):
        if v is None:
            return
        if c not in best or float(v) > best[c][0]:
            best[c] = (float(v), klass, src)

    for f in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_*_n100_k*.json")):
        d = json.load(io.open(f, encoding="utf-8"))
        k = bound_class(d)
        if k:
            offer(d["cell"], d.get("lp_composed"), k, os.path.basename(f))
    for f in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_*.json")):
        d = json.load(io.open(f, encoding="utf-8"))
        if (d.get("size") or 100) != 100:
            continue
        k = bound_class(d)
        if k:
            offer(d["cell"], d.get("composed") if d.get("composed") is not None else d.get("lp_composed"),
                  k, os.path.basename(f))
    return best


def main():
    P, B = our_primal(), our_bound()
    klb = kref.derived_lb(100)
    rows = []
    print("n100, per family. Their incumbent is the LBBD column of Table 6; their bound is derived")
    print("from that and their published gap.\n")
    print("%-4s %5s | %10s %10s %8s | %10s %10s %8s | %8s %8s"
          % ("fam", "cells", "our inc", "their inc", "vs them", "our LB", "their LB", "vs them", "our gap", "their gap"))
    for f in ("C", "R", "RC"):
        cells = [c for c in CELLS if FAM(c) == f]
        t = kref.table6(f)
        k_inc = float(t["lbbd"]["zIP"]); k_lb = float(klb[f])
        havep = [c for c in cells if c in P]
        haveb = [c for c in cells if c in B]
        oi = st.mean(P[c] for c in havep) if havep else None
        ob = st.mean(B[c][0] for c in haveb) if haveb else None
        klass = sorted({B[c][1] for c in haveb})
        og = (100.0 * (1 - ob / oi)) if (oi and ob) else None
        kg = 100.0 * (1 - k_lb / k_inc)
        print("%-4s %2d/%2d | %10s %10.1f %8s | %10s %10.1f %8s | %8s %8.1f%%"
              % (f, len(havep), len(cells),
                 ("%.1f" % oi) if oi else "-", k_inc,
                 ("%+.1f%%" % (100.0 * (oi / k_inc - 1))) if oi else "-",
                 ("%.1f" % ob) if ob else "-", k_lb,
                 ("%.2fx" % (ob / k_lb)) if ob else "-",
                 ("%.1f%%" % og) if og else "-", kg))
        rows.append(dict(family=f, cells_primal=len(havep), cells_bound=len(haveb), n=len(cells),
                         our_inc=oi, their_inc=k_inc, our_lb=ob, their_lb=k_lb,
                         our_gap=og, their_gap=kg, bound_classes=klass,
                         bound_sources={c: B[c][2] for c in haveb},
                         missing_primal=[c for c in cells if c not in P]))
    miss = sorted(set(c for r in rows for c in r["missing_primal"]))
    if miss:
        print("\n  EXCLUDED from the primal means (no solution of ours yet): %s" % ", ".join(miss))
        print("  The means above are therefore over a SUBSET and are provisional until it is complete.")
    else:
        print("\n  all 27 cells present in both legs")
    p = os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json")
    json.dump(stamped(dict(rows=rows)), io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
