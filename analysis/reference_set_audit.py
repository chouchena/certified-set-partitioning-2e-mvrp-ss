"""Two questions about the REFERENCE against which our bound is scored. Both raised 2026-09-15.

  Q1  WHICH CELLS belong in a gap-normalised metric?
      On a cell the exact method solves, the published gap is zero, so the reference dual bound
      equals the best-known value. The closed share then takes a ZERO denominator contribution
      and a NEGATIVE numerator one -- a valid dual bound cannot exceed an optimum -- and
      "exceeds the reference" is unachievable BY CONSTRUCTION. Such cells can only depress both
      statistics. They belong in a calibration stratum, not a performance one.

  Q2  WHICH CEILING anchors the gap?
      The exact method's gap is anchored on ITS OWN incumbent: LB = BK x (1 - Gap%/100),
      verified to reproduce their published gaps (register: k-lb-derivation). We inherit that
      anchor. But on many cells a BETTER feasible solution is now known -- some found here --
      so the gap that actually remains open is smaller than the published figures imply.
      Re-anchoring on the tightest known upper bound RAISES our closed share. Whether that is
      legitimate is a framing decision, not an arithmetic one; see the verdict printed below.

PRECISION MATTERS HERE. The reference values are published to one decimal place, so a
difference below 0.05 is indistinguishable from rounding and MUST NOT be counted as an
improvement. Without that guard this script reports us as beating four proven optima, which
would mean either an infeasible solution of ours or a wrong optimum of theirs. It is neither.
"""
import json, csv, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRINT_TOL = 0.05                      # half-width of a value printed to one decimal
PRIMAL = {"fixopt", "joint_milp_cplex", "joint_milp_gurobi", "lbbd"}

K = json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))
AB = {(r["cell"], r["size"]): r.get("ab4")
      for r in json.load(open(os.path.join(ROOT, "runs/ab4_grid_results.json"))).values()}


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def our_lb(cell, size):
    p = os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{cell}_n{size}.json")
    recs = json.load(open(p))
    pr = [x for x in recs if x.get("proven")]
    if pr:
        k = min(x["k"] for x in pr)
        m = [x for x in pr if x["k"] == k][0]["block_relax"]
    else:
        m = max((x.get("block_relax") or 0) for x in recs)
    return max(m, AB.get((cell, size)) or 0)


def our_incumbents(size):
    best = {}
    for r in csv.DictReader(open(os.path.join(ROOT, "runs/summary.csv"), encoding="utf-8")):
        if r.get("size") != str(size) or r.get("engine") not in PRIMAL:
            continue
        if r.get("verified", "").lower() != "true" or r.get("quarantined", "").lower() == "true":
            continue
        try:
            v = float(r["final_incumbent"])
        except (TypeError, ValueError):
            continue
        c = r["instance"]
        if c not in best or v < best[c]:
            best[c] = v
    return best


def q1(size=20):
    per = K["table3"]["per_instance"][str(size)]
    agg = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0, 0,
                                           0.0, 0.0, 0.0, 0, 0])
    for c in sorted(per):
        bk = per[c]["joint_bk"]
        lb = bk * (1 - per[c]["joint_gap"] / 100.0)
        p = our_lb(c, size)
        a = agg[fam(c)]
        a[0] += p; a[1] += lb; a[2] += bk; a[3] += int(p > lb); a[4] += 1
        if per[c]["joint_gap"] > 0:
            a[5] += p; a[6] += lb; a[7] += bk; a[8] += int(p > lb); a[9] += 1
    print(f"\nQ1  PROVEN-CELL CONTAMINATION, |C| = {size}")
    solved = [c for c in per if per[c]["joint_gap"] == 0.0]
    print(f"    solved by the exact method: {len(solved)} of {len(per)}  {sorted(solved)}")
    print(f"    {'fam':>4s} {'ALL CELLS':>26s} {'UNSOLVED ONLY':>26s}")
    for f in ("C", "R", "RC"):
        p, l, b, w, n, p2, l2, b2, w2, n2 = agg[f]
        sa = 100 * (p - l) / (b - l) if b != l else float("nan")
        su = 100 * (p2 - l2) / (b2 - l2) if n2 and b2 != l2 else float("nan")
        print(f"    {f:>4s} {sa:>9.1f}%  exceeds {w:>2d}/{n:<2d} {su:>13.1f}%  "
              f"exceeds {w2:>2d}/{n2:<2d}   ({su - sa:+.1f} pp)")
    return agg


def q2(size=20):
    per = K["table3"]["per_instance"][str(size)]
    best = our_incumbents(size)
    un = [c for c in sorted(per) if per[c]["joint_gap"] > 0]

    print(f"\nQ2  CEILING SENSITIVITY, |C| = {size}   (unsolved cells only, n = {len(un)})")
    # Soundness check FIRST: appearing to beat a proven optimum means something is wrong.
    bad = []
    for c in sorted(per):
        if per[c]["joint_gap"] != 0.0 or c not in best:
            continue
        d = best[c] - per[c]["joint_bk"]
        if d < -PRINT_TOL:
            bad.append((c, per[c]["joint_bk"], best[c], d))
    if bad:
        print("    !! SOUNDNESS FAILURE -- our incumbent is below a PROVEN optimum by more")
        print("       than print precision. Either our solution is infeasible or the published")
        print("       optimum is wrong. Do not proceed until this is resolved.")
        for c, bk, v, d in bad:
            print(f"       {c}: published {bk:.1f}, ours {v:.6f}, {d:+.6f}")
        return None
    print(f"    soundness: no incumbent beats a proven optimum beyond +-{PRINT_TOL} print "
          f"precision  [OK]")

    strict = [c for c in un if c in best and best[c] < per[c]["joint_bk"] - PRINT_TOL]
    print(f"    we hold a strictly better incumbent on {len(strict)} of {len(un)} unsolved cells")

    agg = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    for c in un:
        bk = per[c]["joint_bk"]
        lb = bk * (1 - per[c]["joint_gap"] / 100.0)
        a = agg[fam(c)]
        a[0] += our_lb(c, size) - lb
        a[1] += bk - lb
        a[2] += min(bk, best.get(c, bk)) - lb
        a[3] += 1
    print(f"    closed share = sum(our LB - ref LB) / sum(CEILING - ref LB)")
    print(f"    {'fam':>4s} {'n':>3s} {'ceiling = published BK':>24s} "
          f"{'ceiling = best UB known':>25s}")
    tot = [0.0, 0.0, 0.0, 0]
    for f in ("C", "R", "RC"):
        num, dp, dn, n = agg[f]
        for i, v in enumerate((num, dp, dn, n)):
            tot[i] += v
        print(f"    {f:>4s} {int(n):>3d} {100*num/dp:>23.1f}% {100*num/dn:>24.1f}%"
              f"   ({100*num/dn - 100*num/dp:+.1f} pp)")
    print(f"    {'all':>4s} {int(tot[3]):>3d} {100*tot[0]/tot[1]:>23.1f}% "
          f"{100*tot[0]/tot[2]:>24.1f}%   ({100*tot[0]/tot[2] - 100*tot[0]/tot[1]:+.1f} pp)")
    return dict(published=100 * tot[0] / tot[1], best_known=100 * tot[0] / tot[2],
                n=int(tot[3]), n_better=len(strict))


if __name__ == "__main__":
    print("REFERENCE-SET AUDIT")
    for s in (20, 30):
        q1(s)
    q2(20)
    print("""
VERDICT AS ADOPTED 2026-09-15

  Q1  ADOPT the stratification. Solved cells move to their own category and are reported
      there as CALIBRATION (our bound as a share of the known optimum), never deleted. This
      is a correction, not a new convention: |C| = 10 was already omitted on exactly this
      argument, and it was simply never generalised to the 7 solved cells at |C| = 20.

  Q2  DO NOT re-anchor the headline. Report it as a clearly labelled secondary.
      Re-anchoring on the tightest known upper bound raises the |C| = 20 closed share from
      64.2% to 70.2%, and every reason it is tempting is a reason to distrust it:
        * it makes a DUAL-bound statistic depend on our PRIMAL work. The number would rise
          when our heuristic improves, so it would stop measuring the bound.
        * it is not reproducible from the predecessors' paper alone. A reader can recompute
          64.2% from their Table 3; 70.2% needs our artifacts.
        * our best incumbents are best-of-N over as many as 46 runs, a basis already ruled
          inadmissible against their single run (register: ov-median-vs-bestof-gap).
          Feeding it into the denominator would import that problem into a dual result that
          is currently clean.
        * it moves the reference in our own favour by 6 points, in a continuation paper whose
          referees may be the predecessors.
      The honest version is a statement about the STATE OF KNOWLEDGE, not about our credit:
      "less of the published gap remains genuinely open than those figures imply, because
      better feasible solutions are now known." That belongs in the text and costs nothing.""")
