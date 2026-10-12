"""Before running any cut: how much can it possibly buy on this cell, and may we waive it? (d580)

THE THEOREM, and it is one line. A cut added to the master IP over a FIXED pool cannot push the
incumbent below that pool's integer optimum. The IP already hands us a valid lower bound on that
optimum -- `ip_bound`, the best bound it held when it stopped. Therefore

    max possible OV improvement from ANY cut, or any extra budget, on this pool
        = (ip_street - ip_bound) / ip_street = the residual MIP gap.

A cell whose IP closed its pool has a residual gap of zero, so **no cut and no budget can improve its
incumbent at all**. The only lever left there is new columns.

WHY THIS ONE IS A BOUND AND THE EARLIER ESTIMATE WAS NOT. `step x car penalty` was an educated guess
at what the integer-car cut would buy on the LP, and measurement refuted it as a bound: the observed
gain exceeded it on 6 of 23 cells, because the master's `src` equality means the LP cannot buy a car
without restructuring chains. The quantity here is different in kind -- it is the IP's own dual bound,
a certified lower bound on the best the pool can do. Nothing added as a row can beat it.

WHAT IT DOES NOT COVER. It bounds improvement WITHIN a pool. A cut that changes which columns get
priced -- i.e. one carried into the dual leg, where it alters the duals and hence the pricing -- can
enlarge the pool and is outside this ceiling. The waiver applies to the primal, frozen-pool use.

    python analysis/tep_cut_waiver.py [--arm ceil|floor] [--threshold 1.0]
"""
import argparse
import collections
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

SIZES = (10, 20, 30, 50, 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("ceil", "floor"), default="ceil",
                    help="ceil is the arm whose output becomes the incumbent (97 per cent re-time rate)")
    ap.add_argument("--threshold", type=float, default=1.0, help="waive a cell whose ceiling is below this, in per cent")
    a = ap.parse_args()
    pat = "tep_cg_bound_*_ip_primal.json" if a.arm == "ceil" else "tep_cg_bound_*_ip.json"
    rows = []
    for p in glob.glob(os.path.join(ROOT, "runs", "oracle", pat)):
        d = json.load(io.open(p, encoding="utf-8"))
        ip = d.get("ip")
        if not isinstance(ip, dict) or ip.get("ip_gap") is None:
            continue
        if (a.arm == "ceil") != bool(d.get("primal_rounding")):
            continue
        cap = 100.0 * float(ip["ip_gap"])
        rows.append(dict(cell=d.get("cell"), size=d.get("size") or 100, cap_pct=cap,
                         street=ip.get("ip_street"), bound=ip.get("ip_bound"), status=ip.get("ip_status"),
                         waive=cap < a.threshold, artifact=os.path.basename(p)))
    by = collections.defaultdict(list)
    for r in rows:
        by[r["size"]].append(r)
    print("CUT WAIVER, %s arm. Ceiling = the residual MIP gap; below %.1f%% the cell is waived.\n" % (a.arm, a.threshold))
    print("%-6s %7s %12s %12s %12s   %s" % ("size", "cells", "closed", "median cap", "worst cap", "worth running"))
    for n in SIZES:
        rs = by.get(n) or []
        if not rs:
            continue
        closed = sum(1 for r in rs if r["cap_pct"] < 1e-9)
        keep = sorted(r["cell"] for r in rs if not r["waive"])
        print("%-6d %7d %12s %11.2f%% %11.2f%%   %s"
              % (n, len(rs), "%d of %d" % (closed, len(rs)), st.median(r["cap_pct"] for r in rs),
                 max(r["cap_pct"] for r in rs),
                 ("%d: %s" % (len(keep), ", ".join(keep[:6]) + (" ..." if len(keep) > 6 else ""))) if keep else "none"))
    keep = [r for r in rows if not r["waive"]]
    print("\n  %d runs examined | %d closed the pool (no cut and no budget can move them) | %d worth running"
          % (len(rows), sum(1 for r in rows if r["cap_pct"] < 1e-9), len(keep)))
    if keep:
        print("  the ceiling over the cells worth running: median %.2f%%, best %.2f%%"
              % (st.median(r["cap_pct"] for r in keep), max(r["cap_pct"] for r in keep)))
    p = os.path.join(ROOT, "runs", "oracle", "tep_cut_waiver_%s.json" % a.arm)
    json.dump(stamped(dict(arm=a.arm, threshold=a.threshold, rows=rows)), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
