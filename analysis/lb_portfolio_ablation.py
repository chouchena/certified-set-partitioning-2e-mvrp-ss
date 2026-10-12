"""Post-hoc: what the LB and the runtime would have been with each subset of the portfolio.

WHY (author, 2026-09-29): "calculate post-hoc what would have been the LB and RT with AB and
1. without TEP or 2. with only TEP".

FOUR CONFIGURATIONS, each priced at what it would ACTUALLY have cost -- an instrument you do
not run is an instrument you do not charge (d245/d246/d250):

  ab4            the arithmetic bound alone. The free floor: 17 s for the whole grid.
  ab4+descent    "without TEP"  -- drops the column-generation leg entirely.
  ab4+tep        "with only TEP" -- drops the frozen block-A descent.
  all three      what the grid reports today.

POST-HOC MEANS POST-HOC. These are the values the runs already produced, recombined. Dropping
the descent would not have made the TEP runs converge differently, so the LB column is exact;
but a real campaign that had never run the descent might have spent those hours on TEP instead,
and this cannot say what that would have bought. It prices the portfolios, not the alternative
histories.

    python analysis/lb_portfolio_ablation.py
"""
import collections
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

CONFIGS = [("ab4", ("ab4",)),
           ("ab4+descent", ("ab4", "descent")),
           ("ab4+tep", ("ab4", "tep")),
           ("all three", ("ab4", "descent", "tep"))]
VAL = {"ab4": "ab4", "descent": "descent", "tep": "solver"}
SEC = {"ab4": "ab4_s", "descent": "descent_s", "tep": "solver_s"}


def main():
    grid = json.load(io.open(os.path.join(ROOT, "runs", "oracle", "lb_grid.json"),
                             encoding="utf-8"))["rows"]
    base = {(r["cell"], r["size"]): r for r in grid}

    print("PORTFOLIO ABLATION -- LB and runtime for each subset, post-hoc\n")
    print("  %-13s %7s %11s %9s %8s %9s  %s"
          % ("config", "cells", "LB total", "vs all", "RT (h)", "RT saved", "cells where it is the weakest"))
    out, tot_all = [], None
    summary = {}
    for name, members in CONFIGS:
        rows = []
        for k, r in sorted(base.items()):
            live = {m: r.get(VAL[m]) for m in members if r.get(VAL[m]) is not None}
            val = max(live.values()) if live else None
            who = max(live, key=live.get) if live else None
            secs = sum(r.get(SEC[m]) or 0.0 for m in members)
            rows.append(dict(cell=k[0], size=k[1], config=name, value=val, carrier=who,
                             secs=secs, full_value=r.get("reported"),
                             loss=(None if val is None or r.get("reported") is None
                                   else r["reported"] - val)))
        ok = [x for x in rows if x["value"] is not None]
        tot = sum(x["value"] for x in ok)
        rt = sum(x["secs"] for x in rows)
        if name == "all three":
            tot_all = tot
        summary[name] = dict(total=tot, rt=rt, cells=len(ok), rows=rows)
        out += rows

    allrt = summary["all three"]["rt"]
    for name, _m in CONFIGS:
        s = summary[name]
        lost = [x for x in s["rows"] if x["loss"] and x["loss"] > 1e-6]
        print("  %-13s %7d %11.0f %8.2f%% %8.1f %8.1f h  %d"
              % (name, s["cells"], s["total"], 100.0 * s["total"] / tot_all,
                 s["rt"] / 3600.0, (allrt - s["rt"]) / 3600.0, len(lost)))

    print()
    for name, _m in CONFIGS:
        if name == "all three":
            continue
        s = summary[name]
        lost = [x for x in s["rows"] if x["loss"] and x["loss"] > 1e-6]
        print("  %s -- %d of 135 cells weaker than the full portfolio" % (name, len(lost)))
        if lost:
            rel = [100.0 * x["loss"] / x["full_value"] for x in lost]
            bysz = collections.Counter(x["size"] for x in lost)
            print("     loss median %.1f (%.1f%%)  max %.1f (%.1f%%)  by size %s"
                  % (statistics.median([x["loss"] for x in lost]), statistics.median(rel),
                     max(x["loss"] for x in lost), max(rel), dict(sorted(bysz.items()))))
            for x in sorted(lost, key=lambda y: -y["loss"])[:4]:
                print("       %-7s n%-4d %8.1f -> %8.1f (%+.1f)" %
                      (x["cell"], x["size"], x["full_value"], x["value"], -x["loss"]))
        car = collections.Counter(x["carrier"] for x in s["rows"] if x["carrier"])
        print("     carrier: %s" % dict(car))
        print("     LB per dual-hour: %.0f  (all three: %.0f)"
              % (s["total"] / (s["rt"] / 3600.0) if s["rt"] else 0,
                 tot_all / (allrt / 3600.0) if allrt else 0))
        print()

    # per size, the question the primal actually cares about
    print("  BY SIZE -- LB total kept, and hours charged")
    print("    %-6s %13s %13s %13s %13s" % ("size", "ab4", "ab4+descent", "ab4+tep", "all three"))
    for size in (10, 20, 30, 50, 100):
        cells = [k for k in base if k[1] == size]
        line = "    n%-5d" % size
        for name, _m in CONFIGS:
            rr = [x for x in summary[name]["rows"] if x["size"] == size]
            t = sum(x["value"] for x in rr if x["value"] is not None)
            h = sum(x["secs"] for x in rr) / 3600.0
            line += " %8.0f/%3.1fh" % (t, h)
        print(line)

    p = os.path.join(ROOT, "runs", "oracle", "lb_portfolio_ablation.json")
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(stamped(dict(rows=out, configs=[c[0] for c in CONFIGS]),
                          "analysis/lb_portfolio_ablation.py", "analysis/lb_grid.py"),
                  f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
