"""
S2 close-out: apply the PRE-REGISTERED winner rule, and nothing else.

The rule (PREREG_ov_freeze_programme.md section 2), fixed before any S2 run:

  * winner = higher POOLED P(win) across the 4 DIAGNOSTIC cells
    (R204, R207, RC202, RC203)
  * the 3 CONTROL cells (C203, RC208, R201) are a VETO, not a vote: if the winner's
    pooled control P(win) drops more than 10 pp against the other variant, it is NOT adopted
  * TIE (|d| < SE_d pooled) -> keep `baseline`, the incumbent configuration.
    Fixed in advance on 2026-09-13 precisely so a marginal result is not argued past,
    as happened at Gate A.

Refuses to decide on partial arms. RC203's diagnostic data comes from the pilot
(validation/s2_pilot_RC203.csv), the other three from the screen.

    python analysis/s2_close.py            # refuses unless every needed arm is complete
    python analysis/s2_close.py --preview  # clearly-labelled partial
"""
import os, sys, csv, glob, json, argparse, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped
import kref

DIAGNOSTIC = ["R204", "R207", "RC202", "RC203"]
CONTROL = ["C203", "RC208", "R201"]
VARIANTS = ["baseline", "captl"]
SEEDS = 18


def load():
    """(cell, variant) -> [objectives]. Screen plus the RC203 pilot."""
    out = {}
    # s2_recovered.csv holds 12 C203 runs whose jsonl was never written; their objectives were
    # re-harvested from the child's own verified stdout (validation/s2_recovered.README.md).
    # The originals in s2_screen.csv have an empty best_obj and are dropped by the guard below,
    # so including both files does not double count.
    for f in ("validation/s2_screen.csv", "validation/s2_pilot_RC203.csv",
              "validation/s2_recovered.csv"):
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p, encoding="utf-8")):
            v = (r.get("best_obj") or "").strip()
            if not v:
                continue
            out.setdefault((r["cell"], r["variant"]), []).append(float(v))
    return out


def pwin(vals, bk, proved=False):
    """Success rate. On a PROVED cell success is matching the optimum within the published
    rounding bound, not beating it -- beating a proven optimum is impossible by construction.

    DISPLAY DEFECT, fixed 2026-09-14: pooled() was corrected to score proved cells on the tie
    criterion but this per-cell function was not, so the table printed R201 as "0%" under a
    column labelled "tie w/ optimum". R201 in fact ties the optimum on 17 of 18 runs. The
    pooled numbers were right throughout; only the per-cell display was wrong."""
    if not vals:
        return None
    if proved:
        return sum(1 for x in vals if abs(x - bk) <= DEADBAND) / len(vals)
    # DEADBAND, not 1e-9: K publish to 1 dp (see k_target).
    return sum(1 for x in vals if x < bk - DEADBAND) / len(vals)


def is_proved(c, k):
    return abs(k[c]["joint_gap"]) < 1e-9


DEADBAND = 0.05          # K publish BK to 1 dp; a "win" below this is not a win


def k_target(c, k):
    """K's BEST incumbent across BOTH their methods.

    COMPARATOR DEFECT, fixed 2026-09-14. This module scored unproved cells against
    `joint_bk` alone -- K's WEAKER method -- contradicting the rule settled in
    AUDIT_comparator_asymmetry on 2026-09-13. joint_bk is the easier target on 9 of the
    20 unproved n20 cells, by up to 84.7 (R211) and 22.9 (RC208), so every banked win
    rate on unproved cells was INFLATED. On proved cells joint_bk == lbbd_bk, so the
    tie criterion is unaffected."""
    r = k[c]
    return min(r["joint_bk"], r.get("lbbd_bk", r["joint_bk"]))


def pooled(data, cells, variant, k, proved_as_tie=True):
    """Pooled success rate over a cell set: successes/runs, not a mean of rates.

    DESIGN FLAW, fixed 2026-09-13. The control set is {C203, RC208, R201} and **R201 is one of
    K's PROVED cells**. On a proved cell "beating K's best-known" is impossible by construction:
    the best attainable outcome is a TIE with the optimum. Counting it as P(win) fed 18
    structural zeros into the pooled control rate, diluting it by a third and shrinking any
    difference between variants toward zero -- so the 10pp veto threshold was really testing
    something closer to 15pp on the cells that could actually move.

    With proved_as_tie, a proved cell scores a success when the run MATCHES the optimum within
    the published rounding bound (0.05, as in s1_validate_primal), which is the right question
    to ask of it. Unproved cells are unchanged."""
    w = n = 0
    for c in cells:
        v = data.get((c, variant), [])
        tgt = k_target(c, k)
        if proved_as_tie and is_proved(c, k):
            w += sum(1 for x in v if abs(x - tgt) <= DEADBAND)
        else:
            w += sum(1 for x in v if x < tgt - DEADBAND)
        n += len(v)
    return (w / n if n else None), w, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    data = load()
    k = kref.table3(20)

    missing = [(c, v, len(data.get((c, v), [])))
               for c in DIAGNOSTIC + CONTROL for v in VARIANTS
               if len(data.get((c, v), [])) < SEEDS]
    print("=" * 78)
    print(f"S2 CLOSE-OUT   diagnostic {DIAGNOSTIC}   control {CONTROL}")
    print("=" * 78)
    if missing:
        print(f"INCOMPLETE arms ({len(missing)}): " +
              ", ".join(f"{c}/{v} {n}/{SEEDS}" for c, v, n in missing))
        if not a.preview:
            print("\nREFUSING to apply the winner rule on partial arms. The rule pools across")
            print("cells, so a short arm silently reweights the pool. Re-run when complete,")
            print("or pass --preview for a clearly-labelled partial.")
            return 1
        print("\n*** PREVIEW ONLY - PARTIAL, NOT A DECISION ***")
    print()

    print(f"{'cell':8}{'arm':10}" + "".join(f"{v:>12}" for v in VARIANTS) + "   K BK   scored on")
    for tag, cells in (("DIAG", DIAGNOSTIC), ("CTRL", CONTROL)):
        for c in cells:
            proved = is_proved(c, k)
            cells_txt = []
            for v in VARIANTS:
                vals = data.get((c, v), [])
                if vals:
                    pct = pwin(vals, k_target(c, k), proved) * 100
                    cells_txt.append(f"{pct:.0f}% ({len(vals)})".rjust(12))
                else:
                    cells_txt.append("--".rjust(12))
            crit = "tie w/ optimum" if proved else "beats K BK"
            print(f"{c:8}{tag:10}" + "".join(cells_txt) + f"   {k_target(c, k):.1f}   {crit}")
    print()

    res = {}
    for tag, cells in (("DIAGNOSTIC", DIAGNOSTIC), ("CONTROL", CONTROL)):
        print(f"POOLED {tag}:")
        for v in VARIANTS:
            p, w, n = pooled(data, cells, v, k)
            res[(tag, v)] = (p, w, n)
            print(f"   {v:10} P(win) {p*100:>5.1f}%   ({w}/{n} runs)" if p is not None
                  else f"   {v:10} no data")
    print()

    pb, wb, nb = res[("DIAGNOSTIC", "baseline")]
    pc, wc, nc = res[("DIAGNOSTIC", "captl")]
    d = pc - pb
    se = (pb * (1 - pb) / nb + pc * (1 - pc) / nc) ** 0.5
    print(f"DIAGNOSTIC d = captl - baseline = {d*100:+.1f}pp,  SE_d = {se*100:.1f}pp,  "
          f"|d|/SE = {abs(d)/se if se else 0:.2f}")

    if abs(d) < se:
        winner = "baseline"
        print(f"\n-> TIE (|d| < SE_d). PRE-REGISTERED RULE: keep the incumbent -> {winner}")
    else:
        winner = "captl" if d > 0 else "baseline"
        print(f"\n-> WINNER on pooled diagnostic P(win): {winner}")

    # The veto blocks adopting a CHALLENGER that wins on diagnostics while breaking the
    # control set. It is one-directional by design: it can never PROMOTE a variant.
    # Applying it symmetrically (as the first implementation did) let the veto override the
    # tie rule and elect the variant the tie rule had just rejected -- the opposite of what
    # "is not adopted" means. Caught by running the preview before the data landed.
    INCUMBENT = "baseline"
    if winner == INCUMBENT:
        print("CONTROL VETO CHECK: not applicable -- the winner IS the incumbent, so there is")
        print("   no adoption to block. The veto is one-directional by construction.")
    else:
        cw = res[("CONTROL", winner)][0]
        co = res[("CONTROL", INCUMBENT)][0]
        if cw is None or co is None:
            print("CONTROL VETO CHECK: cannot evaluate -- missing control data. NOT a pass.")
            winner = INCUMBENT
            print(f"   falling back to the incumbent -> {winner}")
        else:
            drop = (co - cw) * 100
            print(f"CONTROL VETO CHECK: challenger {winner} {cw*100:.1f}% vs incumbent "
                  f"{co*100:.1f}%  -> challenger is {drop:+.1f}pp "
                  f"{'BELOW' if drop > 0 else 'above'}")
            if drop > 10:
                print(f"   *** VETO FIRES (>10pp regression). {winner} is NOT adopted.")
                winner = INCUMBENT
            else:
                print("   no veto (threshold 10pp)")

    print(f"\nS2 WINNER: {winner}")
    print("\nNEXT, per validation/S3_PRELAUNCH_AUDIT.md:")
    print("  Q7 is answerable NOW: if the winner's pooled diagnostic P(win) is comfortably")
    print("  above 50% with no control regression, consider going straight to S4 and treating")
    print("  knob calibration as optional. Otherwise run the Q3 depth/aim probe (~3h) BEFORE")
    print("  the 23h sweep -- the prior 250-300s depth figure and captl's 20s cap contradict.")
    if not missing:
        json.dump(stamped({"winner": winner, "diagnostic": {v: res[("DIAGNOSTIC", v)] for v in VARIANTS},
                   "control": {v: res[("CONTROL", v)] for v in VARIANTS}, "d": d, "se": se}, __file__),
                  open(os.path.join(ROOT, "runs", "s2_final.json"), "w"), indent=1)
        print("\n-> runs/s2_final.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
