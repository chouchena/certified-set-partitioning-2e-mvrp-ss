"""
S2e close-out — RC203's escape rate at n=38, and what it does to the restart frontier.

Applies validation/PREREG_S2e_pin_escape_rate.md section 3. The new seeds ran at S2's exact
budget so they POOL with the original 18 rather than forming a separate regime.

Pre-registered in advance: this CANNOT certify the k=6 knee (a 0.7pp margin is beyond any
feasible sample). It separates the three regimes that matter, and the rule is to choose k with
margin rather than at the knee.

    python analysis/s2e_close.py
"""
import os, sys, csv, json, math, itertools, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped
import kref

SRC = ["validation/s2_screen.csv", "validation/s2_pilot_RC203.csv",
       "validation/s2_recovered.csv", "validation/s2e_rc203_escape.csv"]
CELL = "RC203"


def wilson(w, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p = w / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def main():
    if not os.path.exists(os.path.join(ROOT, "validation", "s2e_rc203_escape.csv")):
        print("no validation/s2e_rc203_escape.csv -- S2e has not run. NOT a pass.")
        return 1
    vals, new = [], 0
    for f in SRC:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if r.get("cell") != CELL or r.get("variant") != "baseline":
                continue
            v = (r.get("best_obj") or "").strip()
            if v:
                vals.append(float(v))
                new += f.endswith("s2e_rc203_escape.csv")
    bk = kref.table3(20)[CELL]["joint_bk"]
    w = sum(1 for x in vals if x < bk - 1e-9)
    n = len(vals)
    p = w / n if n else 0.0
    lo, hi = wilson(w, n)

    print("=" * 78)
    print(f"S2e CLOSE-OUT — {CELL} escape rate   (K best-known {bk:.1f})")
    print("=" * 78)
    print(f"pooled runs: {n}  (of which {new} new)   escapes: {w}")
    print(f"escape rate p = {p:.4f}   95% Wilson CI [{lo:.3f}, {hi:.3f}]")
    print(f"   was p = 0.111 on 2/18 with CI [0.031, 0.328]\n")

    print(f"{'k':>3}{'P(escape)=1-(1-p)^k':>22}{'CI low':>10}{'CI high':>10}  median flips?")
    for kk in (4, 6, 8, 10, 12):
        P = 1 - (1 - p) ** kk
        Pl, Ph = 1 - (1 - lo) ** kk, 1 - (1 - hi) ** kk
        flip = "yes across CI" if Pl > 0.5 else ("point est only" if P > 0.5 else "no")
        print(f"{kk:>3}{P:>22.3f}{Pl:>10.3f}{Ph:>10.3f}  {flip}")

    print("\n" + "-" * 78)
    if p >= 0.20:
        print(f"REGIME A (p >= 0.20): k = 4 already clears 50% on {CELL}. The restart portfolio")
        print("  story is strong AND cheap; the frontier can be reported at k = 4.")
    elif p <= 0.05:
        print(f"REGIME C (p <= 0.05): no practical k flips {CELL}'s median. The '5/5 cells' row")
        print("  of the restart frontier is WITHDRAWN, and RC203 is reported as a standing")
        print("  failure rather than a cell the portfolio recovers.")
    else:
        kmin = next((kk for kk in range(1, 41) if 1 - (1 - lo) ** kk > 0.5), None)
        print(f"REGIME B (p ~ {p:.2f}): the median flips, but choose k WITH MARGIN, not at the knee.")
        print(f"  Smallest k whose ENTIRE CI clears 50%: {kmin if kmin else '> 40'}")
        print("  Report the frontier with its interval, never as a point estimate.")
    print("\nThis result is specific to RC203 and must not be used as a grid-wide escape rate.")
    json.dump(stamped({"cell": CELL, "n": n, "escapes": w, "p": p, "ci": [lo, hi]}, __file__),
              open(os.path.join(ROOT, "runs", "s2e_final.json"), "w"), indent=1)
    print("-> runs/s2e_final.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
