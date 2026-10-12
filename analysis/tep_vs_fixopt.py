"""TEP assembly vs the best pure fixopt artifact per n100 cell (verified rows only, same scan as
bks_n100.py). Classes by source path: fixopt = runs/grid, runs/trial_F5..F7, runs/alloc_abd,
runs/v2batch_R_n100 (the production heuristic and its trial variants); TEP = runs/postpass/
assembled_*, runs/tep, runs/tsc (compose -> chain -> re-time, no polish); TEP+polish = runs/trial_C2
(TEP artifact warm-starting the fixopt stack); postpass = analysis/chain_* (fixopt incumbent
re-chained). Prints per cell and family means.

    python analysis/tep_vs_fixopt.py
"""
import statistics as st
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analysis"))
import bks_n100 as B


def cls(f):
    if "assembled_" in f or "/tep/" in f or "/tsc/" in f:
        return "TEP"
    if "trial_C2" in f:
        return "TEP+polish"
    if "chain_" in f:
        return "postpass"
    return "fixopt"


def main():
    rows = B.scan(False)
    best = {}
    for r in rows:
        k = (r["cell"], cls(r["file"]))
        if k not in best or r["obj"] < best[k]["obj"]:
            best[k] = r
    print("%-6s %9s %9s %9s  %s" % ("cell", "fixopt", "TEP", "TEP+pol", "TEP vs fixopt"))
    wins = n = 0; fam = {}
    for c in B.CELLS:
        fx, tp, hp = best.get((c, "fixopt")), best.get((c, "TEP")), best.get((c, "TEP+polish"))
        d = (100.0 * (tp["obj"] / fx["obj"] - 1)) if (fx and tp) else None
        if d is not None:
            n += 1; wins += d < 0
        f = "RC" if c.startswith("RC") else c[0]
        fam.setdefault(f, []).append((fx["obj"] if fx else None, tp["obj"] if tp else None, hp["obj"] if hp else None))
        print("%-6s %9s %9s %9s  %s" % (c, "%.1f" % fx["obj"] if fx else "-", "%.1f" % tp["obj"] if tp else "-", "%.1f" % hp["obj"] if hp else "-", ("%+.1f%%" % d) if d is not None else "-"))
    print("TEP assembly below the best fixopt run on %d of %d cells" % (wins, n))
    for f, v in fam.items():
        a = [x for x, y, z in v if x]; b = [y for x, y, z in v if y]; h = [z for x, y, z in v if z]
        print("family %-3s best-fixopt mean %8.1f  TEP mean %8.1f (%+.1f%%)%s" % (f, st.mean(a), st.mean(b), 100 * (st.mean(b) / st.mean(a) - 1),
              ("  TEP+polish mean %8.1f (%+.1f%%)" % (st.mean(h), 100 * (st.mean(h) / st.mean(a) - 1))) if h else ""))


if __name__ == "__main__":
    main()
