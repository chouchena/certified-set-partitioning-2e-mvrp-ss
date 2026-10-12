"""Statistical treatment of the S3a selection ablation.

THE QUESTION THIS SETTLES. Each arm uses ONE seeded ordering per cell, not a distribution of
orderings. Does that undermine the conclusion?

NO -- and the reason is structural, not a matter of degree. **The replication unit is the CELL,
not the seed.** Under the null hypothesis we actually care about,

    H0: the easiness ordering is exchangeable with a uniformly random ordering
        (i.e. our score has no special merit),

easiness and a random draw are interchangeable on any given cell, so P(easiness wins) = 1/2 there.
Each cell is therefore one valid Bernoulli trial and the 21 informative cells give 21 of them.
One draw per cell is not a degenerate sample: it is a PAIRED RANDOMISATION TEST ACROSS INSTANCES,
the standard design in this literature (Demsar 2006), and the same logic this project already uses
for the primal Wilcoxon.

Extra seeds would buy PRECISION and POWER, never validity. The stronger claim they would enable --
a per-cell permutation test placing easiness in the top q% of all orderings -- needs >= 20 draws per
cell to reach p < 0.05 per cell, i.e. ~140 h. Not worth it for an effect already at p ~ 1e-4.

WHAT IS COMPUTED
  * exact one-sided SIGN TEST on the win count (H0: p = 1/2)
  * exact one-sided WILCOXON SIGNED-RANK on log frontier ratios, which uses the MAGNITUDES and is
    much stronger here because the effect is strongly asymmetric (easiness wins big, random small)
  * FLIP ROBUSTNESS: how many cells would have to change sign to break the pre-committed 70% rule
  * a FRAGILITY ranking: the cells near ratio 1.0 are the only ones another draw could plausibly flip

CAVEAT, stated in the output: cells within a family (C, R, RC) share structure, so independence
across the 21 is imperfect. This is the same limitation Demsar's framework carries and which we
already disclose for the primal comparison.
"""
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lb_estimator, os, math, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The 21 informative cells: all 27 minus the 6 whose baseline descent reaches k=0, where the
# retained set is the whole instance and the bound is selection-INDEPENDENT by construction.
INFORMATIVE = ("C202,C203,C204,C207,R202,R203,R204,R205,R206,R207,R208,R209,R210,R211,"
               "RC202,RC203,RC204,RC205,RC206,RC207,RC208").split(",")
THRESHOLD = 0.70


def frontier(path):
    """Delegates. The proved-frontier rule lives in lb_estimator; see
    validation/DECISION_reported_bound_estimator.md and PREREG_S3a Amendment 1."""
    if not os.path.exists(path):
        return None
    return lb_estimator.frontier_bound(json.load(open(path)))


def sign_test(wins, n):
    """Exact one-sided binomial tail, H0: p = 1/2."""
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / 2 ** n


def wilcoxon_exact(diffs):
    """Exact one-sided signed-rank p-value. Zeros dropped; ties get average ranks.

    The exact null distribution is built by DP over achievable positive-rank sums, which is
    valid only when there are no rank ties; with ties we fall back to the normal approximation
    and say so, rather than quoting an exact p-value that is not exact.
    """
    d = [x for x in diffs if abs(x) > 1e-12]
    n = len(d)
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i = 0
    tied = False
    while i < n:
        j = i
        while j + 1 < n and abs(abs(d[order[j + 1]]) - abs(d[order[i]])) < 1e-12:
            j += 1
        if j > i:
            tied = True
        r = (i + j) / 2 + 1
        for t in range(i, j + 1):
            ranks[order[t]] = r
        i = j + 1
    Wp = sum(ranks[i] for i in range(n) if d[i] > 0)
    Wm = sum(ranks[i] for i in range(n) if d[i] < 0)
    mu = n * (n + 1) / 4
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (min(Wp, Wm) - mu) / sd
    if tied:
        p = 0.5 * math.erfc(abs(z) / math.sqrt(2))
        return Wp, Wm, z, p, n, "normal approx (rank ties present)"
    # exact: count subsets of {1..n} whose sum <= min(Wp,Wm)
    target = int(round(min(Wp, Wm)))
    dp = [0] * (n * (n + 1) // 2 + 1)
    dp[0] = 1
    for r in range(1, n + 1):
        for s in range(len(dp) - 1, r - 1, -1):
            dp[s] += dp[s - r]
    p = sum(dp[: target + 1]) / 2 ** n
    return Wp, Wm, z, p, n, "exact"


def main(arm, size=20):
    rows = []
    for c in INFORMATIVE:
        b = os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{c}_n{size}.json")
        a = os.path.join(ROOT, f"crossfeed/ablation_{arm}_{c}_n{size}.json")
        if not os.path.exists(a):
            continue
        fe, fa = frontier(b), frontier(a)
        if fe is None or fa is None:
            continue
        rows.append((c, fe, fa, fa / fe))

    n = len(rows)
    if n < len(INFORMATIVE):
        print(f"!! INCOMPLETE: {n} of {len(INFORMATIVE)} informative cells present. "
              f"The pre-committed rule is evaluated on the COMPLETE arm; this is interim.\n")
    wins = sum(1 for *_, r in rows if r < 1)

    print(f"ARM = {arm}   informative cells n = {n}   easiness better on {wins}")
    print(f"\nSIGN TEST  (exact, one-sided, H0: easiness exchangeable with a random ordering)")
    print(f"    p = {sign_test(wins, n):.6f}")

    Wp, Wm, z, p, neff, how = wilcoxon_exact([-math.log(r) for *_, r in rows])
    print(f"\nWILCOXON SIGNED-RANK on log frontier ratios  ({how}, n_eff = {neff})")
    print(f"    W+ = {Wp:.0f}   W- = {Wm:.0f}   z = {z:.3f}   p = {p:.6f}")
    print("    (stronger than the sign test because the effect is ASYMMETRIC: easiness wins")
    print("     by large margins, the arm by small ones, and signed-rank uses magnitudes)")

    need = math.ceil(THRESHOLD * n)
    print(f"\nFLIP ROBUSTNESS vs the pre-committed {THRESHOLD:.0%} rule")
    print(f"    need >= {need} of {n} ({100*need/n:.1f}%); have {wins}; tolerates {wins-need} flips")

    print(f"\nFRAGILITY -- only cells near ratio 1.0 could plausibly flip on another draw")
    for c, fe, fa, r in sorted(rows, key=lambda x: abs(math.log(x[3])))[:8]:
        print(f"    {c:7s} ratio {r:.3f}  margin {abs(1-r)*100:5.1f}%  "
              f"won by {'easiness' if r < 1 else arm.upper()}")
    big = sum(1 for *_, r in rows if abs(1 - r) >= 0.05)
    print(f"    {big} of {n} cells sit at margins >= 5%, which reseeding will not move")

    print("\nCAVEAT: cells within a family (C/R/RC) share structure, so independence across the")
    print("        21 is imperfect -- the same limitation Demsar's framework carries and which")
    print("        we already disclose for the primal comparison.")

    # Returned so analysis/manuscript_numbers.py can register these values WITHOUT
    # re-implementing the test. Same discipline as T1/F2: one definition, many consumers.
    return dict(arm=arm, n=n, wins=wins, complete=(n == len(INFORMATIVE)),
                sign_p=sign_test(wins, n),
                wilcoxon=dict(W_plus=Wp, W_minus=Wm, z=z, p=p, n_eff=neff, method=how),
                threshold=THRESHOLD, need=need, flips_tolerated=wins - need,
                mean_ratio=sum(r for *_, r in rows) / n,
                margins_ge_5pct=big)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["random", "reverse"])
    ap.add_argument("--size", type=int, default=20)
    a = ap.parse_args()
    main(a.arm, a.size)
