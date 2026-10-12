"""P2 on the FULL 20-cell UNPROVED arm at |C| = 20.

P2, as pre-registered in PREREG_gap_decomposition_RQ sec 6:

    "in the UNPROVED arm, the MEDIAN run beats K's BK on more cells than it loses"

It is a per-CELL count, not a per-run rate, and it is deliberately the binding
prediction: "A claim to work where exact methods fail requires reliability, not
a best-of statistic."

Two corrections this project had to make are applied here and were NOT applied
in the original S2 close-out:

  * comparator = min(joint_bk, lbbd_bk), K's BETTER method
    (AUDIT_comparator_asymmetry 2026-09-13; s2_close.py:91 still uses joint_bk
     alone, which is the easier target on 9 of these 20 cells, by up to 84.7)
  * a 0.05 DEADBAND -- K publish to 1 dp, so a "win" of 0.045 is not a win

Sources, both at the SAME budget (400 s wall / 434000 det, baseline variant):
  * the 14 out-of-sample cells from S2g          (6 seeds each)
  * the 6 original cells from the S2 screen      (up to 18 seeds each)

Seed counts differ. For a per-CELL criterion that is correct -- each cell votes
once -- but it is stated, per PREREG_S2g sec 4.2.
"""
import sys, os, csv, json, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis.stamp import stamped
from s2g_status import (parse, median, k_best, DEADBAND,    # noqa: E402
                        UNRESOLVED_LO, UNRESOLVED_HI)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S2_FILES = ("validation/s2_screen.csv", "validation/s2_pilot_RC203.csv",
            "validation/s2_recovered.csv")


def load_s2(variant="baseline"):
    out = {}
    for f in S2_FILES:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if r.get("variant") != variant:
                continue
            v = (r.get("best_obj") or "").strip()
            if not v:
                continue
            out.setdefault(r["cell"], []).append(float(v))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/p2_full_arm.json")
    a = ap.parse_args()

    kref = json.load(open("data/karademir2025/k_reference.json"))
    per = kref["table3"]["per_instance"][str(a.size)]
    unproved = sorted(c for c in per if per[c]["joint_gap"] > 0)

    vals = {c: list(v.values()) for c, v in parse("runs/s2g.log").items()}
    for c, v in load_s2().items():
        vals.setdefault(c, []).extend(v) if c not in vals else None
        if c not in vals or not vals[c]:
            vals[c] = v
        elif len(v) > len(vals[c]):
            vals[c] = v

    print(f"P2 on the UNPROVED arm, |C| = {a.size}: {len(unproved)} cells\n")
    print(f"{'cell':7s} {'seeds':>5s} {'K best':>8s} {'median':>9s} {'delta':>9s} "
          f"{'w/t/l':>8s}  verdict")
    beat = lose = tie = unresolved = missing = 0
    rows = []
    for c in unproved:
        v = vals.get(c) or []
        if not v:
            print(f"{c:7s} {'--':>5s} {'':>8s} {'NO DATA':>9s}"); missing += 1; continue
        kb = k_best(per[c])
        med = median(v)
        d = med - kb
        if d < -DEADBAND:
            vd = "BEAT"
        elif d > DEADBAND:
            vd = "lose"
        else:
            vd = "tie"

        # THE UNRESOLVED OVERLAY, SCOPED TO 6-SEED CELLS. PREREG_S2g section 5 registers two
        # non-parallel bullets: the median scores "their 6 (or 18) runs", while the 2/6-4/6
        # overlay is written only in sixths. Section 4.1 gives its reason -- "on a cell near
        # P(win) = 0.5 SIX seeds cannot resolve the sign at all" -- so it exists because a
        # 6-run median is untrustworthy near 0.5, which an 18-run median is not.
        #
        # This was registered in Amendment 1 of 2026-09-16, AFTER the data, because 18-seed
        # cells did not exist when the rule was written. The rejected alternative is worse in
        # an obvious way: applying the raw counts 2..4 to an 18-seed cell makes RC208 a BEAT
        # at 8/18 while its median, 869.4, is WORSE than K's 858.7.
        #
        # Until 2026-09-16 this script imported four names from s2g_status and none of them was
        # this rule, so the registered overlay was never applied to the data it was registered
        # for. That is the defect this block closes.
        wins = sum(1 for x in v if x < kb - DEADBAND)
        losses = sum(1 for x in v if x > kb + DEADBAND)
        ties = len(v) - wins - losses
        if len(v) == 6 and vd != "tie" and UNRESOLVED_LO <= wins <= UNRESOLVED_HI:
            vd = "UNRESOLVED"

        if vd == "BEAT":
            beat += 1
        elif vd == "lose":
            lose += 1
        elif vd == "tie":
            tie += 1
        else:
            unresolved += 1
        rows.append(dict(cell=c, n=len(v), k_best=kb, median=med, delta=d,
                         win=wins, tie_runs=ties, lose_runs=losses, verdict=vd))
        print(f"{c:7s} {len(v):5d} {kb:8.1f} {med:9.1f} {d:+9.2f} "
              f"{f'{wins}/{ties}/{losses}':>8s}  {vd}")

    n = beat + lose + tie + unresolved
    print(f"\nmedian BEATS K on {beat} cells, TIES on {tie}, LOSES on {lose}, "
          f"UNRESOLVED on {unresolved}  (of {n} with data; {missing} missing)")
    met = beat > lose
    # Section 5: "P2 holds if wins > losses over the RESOLVED cells, and the unresolved count is
    # reported next to it." Printing the unresolved count here is not decoration -- it is the
    # registered form of the verdict.
    print(f"\nP2 = 'median beats K on more cells than it loses, over resolved cells'  ->  "
          f"{'MET' if met else 'NOT MET'}  ({beat} vs {lose}, {unresolved} unresolved)")
    json.dump(stamped(dict(beat=beat, tie=tie, lose=lose, unresolved=unresolved, missing=missing,
                   met=met, rows=rows), __file__), open(a.out, "w"), indent=1)
    print("wrote", a.out)
