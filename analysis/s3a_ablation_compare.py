"""S3a: compare retained-set selection arms against the banked `easiness` baseline.

Implements validation/PREREG_S3a_bound_selection_ablation.md EXACTLY, including Amendment 1.

MEASURES
  primary (pre-committed): the CERTIFIED FRONTIER bound -- block_relax at the SMALLEST k the
      arm proves. block_relax is monotone DECREASING in k, so the smallest certified k gives the
      strongest bound; this is the descent's reported output.
  secondary: MATCHED-k -- block_relax at the smallest k BOTH arms prove, which controls for depth.
  reported alongside: BEST-OF-ALL-RECORDS -- max block_relax over every record, proven or not.
      By Step 0 of the validity proof an unproven record carries a valid dual bound, so this is a
      valid number. It is NOT what the manuscript reports: since 2026-09-16 that is
      `lb_estimator.cell_bound`, the best REPRODUCIBLE record, which additionally excludes
      wall-stopped records (PREREG_n100 Amendment 6). This docstring said otherwise and was
      corrected with the consolidation.

DENOMINATOR. Cells whose baseline descent reaches k=0 are EXCLUDED: at k=0 the drop set is empty,
H is the entire customer set, and every arm returns an identical bound BY CONSTRUCTION. Counting
them as ties would dilute the measured effect toward the null. Their exact agreement is still
reported, as a harness check.
"""
import json, os, sys, glob, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lb_estimator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELLS = ("C201,C202,C203,C204,C205,C206,C207,C208,R201,R202,R203,R204,R205,R206,R207,"
         "R208,R209,R210,R211,RC201,RC202,RC203,RC204,RC205,RC206,RC207,RC208").split(",")
EPS = 1e-6


def load(path):
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path))
    except Exception:
        return None


def summarise(recs):
    if not recs:
        return None
    pr = [r for r in recs if r.get("proven")]
    out = {"n_records": len(recs), "n_proven": len(pr)}
    # THE PROVED FRONTIER, FROM THE ONE DEFINITION. S3a compares retained-set policies, so its
    # measure must be a bound each arm PROVES -- not the best record either arm reached, which
    # would let a lucky truncation decide the comparison. See PREREG_S3a Amendment 1 and
    # validation/DECISION_reported_bound_estimator.md for why these are two quantities.
    kf, _, ok = lb_estimator.frontier(recs)
    if ok:
        out["frontier_k"] = kf
        out["frontier"] = lb_estimator.frontier_bound(recs)
        out["proven_at"] = {r["k"]: r["block_relax"] for r in pr}
    else:
        out["frontier_k"], out["frontier"], out["proven_at"] = None, None, {}
    # `best_any` is REPORTED ALONGSIDE, never compared on: by Step 0 an unproven record carries a
    # valid dual bound, so this is the strongest valid number, but it is not arm-comparable.
    out["best_any"] = lb_estimator.cell_bound(recs, reproducible_only=False)
    return out


def main(arm, size=20):
    rows, missing = [], []
    for c in CELLS:
        base = summarise(load(os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{c}_n{size}.json")))
        armr = summarise(load(os.path.join(ROOT, f"crossfeed/ablation_{arm}_{c}_n{size}.json")))
        if armr is None:
            missing.append(c); continue
        excl = (base and base["frontier_k"] == 0)
        mk = sorted(set(base["proven_at"]) & set(armr["proven_at"])) if (base and armr) else []
        rows.append(dict(cell=c, base=base, arm=armr, excluded=excl,
                         matched_k=(mk[0] if mk else None)))

    print(f"ARM = {arm}   n{size}   cells complete: {len(rows)}/{len(CELLS)}"
          f"   (not yet run: {len(missing)})")
    print(f"{'cell':7s} {'kE':>3s} {'easiness':>9s} {'kA':>3s} {'arm':>9s} {'ratio':>6s} "
          f"{'mk':>3s} {'E@mk':>9s} {'A@mk':>9s}  verdict")

    inf_w = inf_l = inf_t = 0
    ratios, excl_rows = [], []
    for r in rows:
        b, a, c = r["base"], r["arm"], r["cell"]
        if b is None or b["frontier"] is None or a["frontier"] is None:
            print(f"{c:7s}  -- incomplete --"); continue
        ratio = a["frontier"] / b["frontier"]
        mk = r["matched_k"]
        emk = b["proven_at"].get(mk); amk = a["proven_at"].get(mk)
        if r["excluded"]:
            excl_rows.append((c, b["frontier"], a["frontier"]))
            verdict = "excluded (k=0, identical by construction)"
        else:
            if a["frontier"] > b["frontier"] + EPS:
                inf_l += 1; verdict = "ARM BETTER"
            elif a["frontier"] < b["frontier"] - EPS:
                inf_w += 1; verdict = "easiness better"
            else:
                inf_t += 1; verdict = "tie"
            ratios.append(ratio)
        print(f"{c:7s} {str(b['frontier_k']):>3s} {b['frontier']:9.2f} "
              f"{str(a['frontier_k']):>3s} {a['frontier']:9.2f} {ratio:6.3f} "
              f"{str(mk):>3s} {(f'{emk:9.2f}' if emk is not None else '        -')} "
              f"{(f'{amk:9.2f}' if amk is not None else '        -')}  {verdict}")

    n = inf_w + inf_l + inf_t
    # PREREG Amendment 1, pre-committed caveat: exclusion is defined by the BANKED arm's
    # frontier. Where an arm FAILS to reach k=0 on one of those cells, that is a genuine
    # difference in REACH and is reported as such -- it is NOT a harness fault, and it must
    # not be quietly absorbed by the exclusion rule.
    print(f"\n--- EXCLUDED by the baseline reaching k=0: {len(excl_rows)} cells ---")
    same = [e for e in excl_rows if abs(e[1] - e[2]) <= EPS]
    reach = [e for e in excl_rows if abs(e[1] - e[2]) > EPS]
    print(f"    both arms reached k=0, bounds identical: {len(same)}/{len(excl_rows)}"
          f"   <- harness check; the VALUE at k=0 is selection-INDEPENDENT")
    for c, bv, av in reach:
        print(f"    REACH DIFFERENCE {c}: baseline proved k=0 ({bv:.2f}), arm did not "
              f"({av:.2f}). Reported per the pre-committed caveat; NOT a harness fault.")
    print(f"\n--- INFORMATIVE cells: {n} ---")
    if n:
        print(f"    easiness better : {inf_w}  ({100*inf_w/n:.1f}%)")
        print(f"    arm better      : {inf_l}")
        print(f"    tie             : {inf_t}")
        print(f"    mean arm/easiness frontier ratio : {sum(ratios)/len(ratios):.4f}")
        print(f"    PRE-COMMITTED RULE: easiness wins the ablation if it is better on >= 70% "
              f"of informative cells -> currently {100*inf_w/n:.1f}%"
              f" [{'MET' if inf_w/n >= 0.70 else 'NOT MET'}]")
    if missing:
        print(f"\nINTERIM -- {len(missing)} cells not yet run: {missing}")
        print("This is NOT the verdict. The rule is evaluated on the complete 21-cell arm.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["random", "reverse"])
    ap.add_argument("--size", type=int, default=20)
    a = ap.parse_args()
    main(a.arm, a.size)
