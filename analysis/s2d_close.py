"""
S2d close-out — proved-cell fidelity and the pre-registered P1 prediction.

Applies validation/PREREG_S2d_proved_fidelity.md section 4, and nothing else:

  * K proved ALL 27 |C|=10 instances, so there are 27 known correct answers.
  * MATCH = within 0.05 of K's published optimum (they publish one decimal; 0.05 is the
    rounding bound, the same tolerance s1_validate_primal.py uses).
  * P1 PASSES at >= 90% of cells matched.
  * ANY incumbent BELOW a proven optimum is a HARD STOP -- either the primal emits infeasible
    solutions or the instance is not K's.

Reports best-of-seeds AND the per-seed match rate, because the pre-registration recorded that
a pass on best-of-2 must be reported as best-of-2 (adverse audit point 2).

    python analysis/s2d_close.py

Exit 0 pass, 2 fail or hard stop, 1 cannot run.
"""
import os, sys, csv, json, argparse, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped
import kref

CSV = os.path.join(ROOT, "validation", "s2d_proved_n10.csv")
TOL = 0.05
SIZE = 10


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(a.csv):
        print(f"no {os.path.relpath(a.csv, ROOT)} -- S2d has not run. NOT a pass.")
        return 1

    k = kref.table3(SIZE)
    proved = {c: t["joint_bk"] for c, t in k.items() if abs(t["joint_gap"]) < 1e-9}
    runs = collections.defaultdict(list)
    for r in csv.DictReader(open(a.csv, encoding="utf-8")):
        v = (r.get("best_obj") or "").strip()
        if v:
            runs[r["cell"]].append(float(v))

    print("=" * 78)
    print(f"S2d CLOSE-OUT — proved-cell fidelity and P1   (|C|={SIZE}, {len(proved)} proved cells)")
    print("=" * 78)

    missing = [c for c in proved if not runs.get(c)]
    if missing and not a.preview:
        print(f"INCOMPLETE: {len(missing)} of {len(proved)} cells have no data: {sorted(missing)[:8]}")
        print("Re-run when complete, or pass --preview for a clearly-labelled partial.")
        return 1
    if a.preview:
        print("*** PREVIEW — PARTIAL, NOT A DECISION ***\n")

    below, match, miss = [], [], []
    seed_hits = seed_tot = 0
    for c, opt in sorted(proved.items()):
        v = runs.get(c, [])
        if not v:
            continue
        seed_tot += len(v)
        seed_hits += sum(1 for x in v if abs(x - opt) <= TOL)
        b = min(v)
        if b < opt - TOL:
            below.append((c, b, opt))
        elif abs(b - opt) <= TOL:
            match.append((c, b, opt, len(v)))
        else:
            miss.append((c, b, opt, (b - opt) / opt * 100, len(v)))

    n = len(match) + len(miss) + len(below)
    print(f"cells with data: {n} of {len(proved)}   (runs: {seed_tot})\n")

    if below:
        print(f"*** HARD STOP — {len(below)} incumbent(s) BELOW a proven optimum:")
        for c, b, o in below:
            print(f"      {c}: ours {b:.3f} < K optimum {o:.3f}")
        print("    Either the primal emits infeasible solutions or these are not K's instances.")
        print("    Both invalidate the paper in its current form. Investigate before any further run.")
        return 2

    rate = len(match) / n * 100 if n else 0.0
    print(f"MATCHED (best-of-seeds, within {TOL}): {len(match)}/{n}  = {rate:.1f}%")
    if miss:
        print(f"NOT MATCHED: {len(miss)}")
        for c, b, o, d, ns in sorted(miss, key=lambda x: -x[3])[:10]:
            print(f"      {c}: best {b:.2f} vs optimum {o:.2f}  (+{d:.2f}%, {ns} seeds)")
    print(f"\nPER-SEED match rate: {seed_hits}/{seed_tot} = {seed_hits/seed_tot*100 if seed_tot else 0:.1f}%")
    print("  (reported because the pre-registration requires a best-of-k pass to be named as such)")

    print("\n" + "-" * 78)
    verdict = rate >= 90.0
    print(f"P1 ({'>= 90% of proved cells matched'}): {'PASS' if verdict else 'FAIL'}  [{rate:.1f}%]")
    if verdict:
        print("INSTANCE FIDELITY: confirmed at |C|=10. A systematic mismatch with K's instances is")
        print("  ruled out at this size, so the RC208 quarantine cannot rest on 'instance mismatch'")
        print("  as a general claim and must be re-argued on cell-specific grounds or lifted.")
        print("  NOTE: n10 fidelity does not prove n20 fidelity. The builder is shared, so a")
        print("  systematic mismatch would almost certainly show at both -- but RC208 is an n20")
        print("  cell, and stage 2 (the 4 uncovered proved cells at n20) is the direct test.")
    else:
        print("P1 FAILS. Per the pre-registration this is a reliability finding against us and is")
        print("  reported as one. Instance fidelity is UNRESOLVED, not refuted: a search failure")
        print("  and a data mismatch look identical from here. Separating them needs K's exact")
        print("  model on a failing cell (the Gurobi arm, gated in gurobi_validity_check.py).")
    if not verdict:
        return 2
    # DEFECT (found 2026-09-14 by running --preview on 1 cell of data): this wrote
    # runs/s2d_final.json unconditionally, so a clearly-labelled PARTIAL preview produced an
    # artifact named "final" recording cells=1, rate=100%. A later reader cannot tell it was a
    # preview. Same guard s2_close.py already applies: persist only a complete, non-preview run.
    if a.preview or missing:
        print("\nPREVIEW/PARTIAL: runs/s2d_final.json NOT written.")
        return 0
    json.dump(stamped({"size": SIZE, "cells": n, "matched": len(match), "rate": rate,
               "per_seed": [seed_hits, seed_tot], "p1_pass": verdict}, __file__),
              open(os.path.join(ROOT, "runs", "s2d_final.json"), "w"), indent=1)
    print("\n-> runs/s2d_final.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
