"""What a bound must clear at n10/n20/n30, per cell, from K's published per-instance table.
Pure Python, no solver (d421 row 3 calibration).

K publish, per instance and per size up to 30: the Joint model's best-known and its solver gap,
and the LBBD's best-known and its improvement figure. Their implied lower bound is
`joint_bk * (1 - joint_gap/100)` -- the Gurobi convention, confirmed against the paper (d178).
Where the gap is zero the value IS the optimum, and any bound of ours ABOVE it is a validity
breach, not a win.

Per cell this prints: K's incumbent, their implied bound, our current dual-leg bound, the ratio,
and the TARGET a TEP bound must exceed to be a per-cell win. Per size it prints how many cells we
already exceed, which is what the n20 + n30 batch gate should be set against.

    python analysis/k_targets_small.py [--sizes 10,20,30]
"""
import argparse
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import manuscript_numbers as MN
import dual_vs_k as D


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", default="10,20,30"); a = ap.parse_args()
    K = MN._K()
    out = {}
    for size in [int(x) for x in a.sizes.split(",")]:
        per = K["table3"]["per_instance"][str(size)]
        rows = []
        print("\n|C| = %d   (K publish per instance at this size)" % size)
        print("%-6s %9s %9s %9s %9s %8s  %s" % ("cell", "K inc", "K bound", "ours", "ratio", "proven", "target for a TEP win"))
        for c in sorted(per):
            p = per[c]
            kb = p["joint_bk"] * (1 - p["joint_gap"] / 100.0)
            proven = abs(p["joint_gap"]) < 1e-9
            ours = D.lb_frontier(c, size) or D.lb_maxrec(c, size)
            ratio = (ours / kb) if (ours and kb) else None
            tgt = ("must not exceed %.1f (the optimum)" % kb) if proven else ("beat %.1f" % kb)
            rows.append(dict(cell=c, k_inc=p["joint_bk"], k_bound=kb, ours=ours, ratio=ratio, proven=proven,
                             lbbd_bk=p.get("lbbd_bk")))
            print("%-6s %9.1f %9.1f %9s %9s %8s  %s"
                  % (c, p["joint_bk"], kb, ("%.1f" % ours) if ours else "-", ("%.2fx" % ratio) if ratio else "-",
                     "yes" if proven else "no", tgt))
        unpr = [r for r in rows if not r["proven"] and r["ours"]]
        prov = [r for r in rows if r["proven"] and r["ours"]]
        exceed = [r for r in unpr if r["ours"] > r["k_bound"] + 1e-9]
        breach = [r for r in prov if r["ours"] > r["k_bound"] + 1e-6]
        print("  proven by K %d, unproved %d | our leg exceeds K's bound on %d of %d unproved (median ratio %.2fx)"
              % (len(prov), len(unpr), len(exceed), len(unpr), st.median([r["ratio"] for r in unpr]) if unpr else float("nan")))
        print("  on K's proven cells we reach %.0f-%.0f%% of the optimum; validity breaches: %d"
              % (100 * min(r["ratio"] for r in prov), 100 * max(r["ratio"] for r in prov), len(breach)) if prov else "  no proven cells")
        if unpr:
            need = sorted(r["k_bound"] / r["ours"] for r in unpr if r["ours"])
            print("  to win every unproved cell a TEP bound must be, per cell, %.2fx to %.2fx our current leg (median %.2fx)"
                  % (need[0], need[-1], st.median(need)))
        out["n%d" % size] = dict(rows=rows, proven=len(prov), unproved=len(unpr), exceed=len(exceed), breaches=len(breach))
    json.dump(out, io.open(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json"), "w", encoding="utf-8"), indent=1)
    print("\nwrote runs/oracle/k_targets_small.json")


if __name__ == "__main__":
    main()
