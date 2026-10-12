"""Friedman + Holm post-hoc across all three S3a arms, with easiness as the control.

WHY THIS EXISTS. `analysis/s3a_significance.py` reports a pairwise Wilcoxon per arm. Demsar
(2006), JMLR 7:1-30 -- the canonical reference for comparing algorithms over a benchmark set,
and already used in this project for the primal -- prescribes Wilcoxon signed-rank for TWO
algorithms but the **Friedman test with post-hoc comparisons when there are MORE than two**.
We have three (easiness, random, reverse) with easiness as the control, so reporting two
separate Wilcoxons inflates the family-wise error rate and a Demsar-literate referee will say so.

OUR DESIGN IS HIERARCHICAL, WHICH IS A DEFENCE -- BUT NOT A SUBSTITUTE. The prereg names
easiness-vs-random as the PRIMARY rule and reverse as a pre-specified QUALIFIER on
interpretation, not a co-primary. Pre-registered hierarchical testing does not require
correction of the primary. That argument is only available because the prereg was written
first. This script supplies the family-wise analysis anyway, as a robustness check, because
it costs nothing and removes the objection entirely.

RANKING CONVENTION. block_relax is a LOWER BOUND, so HIGHER IS BETTER; rank 1 = strongest
bound on that cell. Ties get average ranks.

STATISTICS
  * Friedman chi-square, df = k-1, plus the Iman-Davenport F correction, which Demsar
    recommends as less conservative than the raw chi-square.
  * Post-hoc against the control by the standard rank-difference z, with HOLM's step-down
    correction (more powerful than Bonferroni-Dunn, and also discussed by Demsar).
  * A cross-check of the hand-rolled exact Wilcoxon in s3a_significance.py against scipy.
"""
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lb_estimator, os, math, argparse
import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFORMATIVE = ("C202,C203,C204,C207,R202,R203,R204,R205,R206,R207,R208,R209,R210,R211,"
               "RC202,RC203,RC204,RC205,RC206,RC207,RC208").split(",")
ARMS = ["easiness", "random", "reverse"]
CONTROL = "easiness"


def frontier(path):
    """Delegates. The proved-frontier rule lives in lb_estimator; see
    validation/DECISION_reported_bound_estimator.md and PREREG_S3a Amendment 1."""
    if not os.path.exists(path):
        return None
    return lb_estimator.frontier_bound(json.load(open(path)))


def path_for(arm, cell, size):
    if arm == "easiness":
        return os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{cell}_n{size}.json")
    return os.path.join(ROOT, f"crossfeed/ablation_{arm}_{cell}_n{size}.json")


def main(size=20):
    table, cells, dropped = [], [], []
    for c in INFORMATIVE:
        vals = [frontier(path_for(a, c, size)) for a in ARMS]
        if any(v is None for v in vals):
            dropped.append(c); continue
        table.append(vals); cells.append(c)

    N, k = len(table), len(ARMS)
    if N == 0:
        print("no complete cells yet"); return
    complete = (len(dropped) == 0)
    if not complete:
        print(f"!! INTERIM: {N} of {len(INFORMATIVE)} informative cells have all three arms.")
        print(f"   still missing: {dropped}")
        print("   The pre-committed rule is read on the COMPLETE arm. This is a preview.\n")

    X = np.asarray(table, float)
    # rank within each cell; HIGHER block_relax is BETTER -> rank 1 = best, so rank -X
    ranks = np.apply_along_axis(lambda r: stats.rankdata(-r), 1, X)
    Rbar = ranks.mean(axis=0)

    print(f"S3a FRIEDMAN + HOLM   n{size}   cells N = {N}   arms k = {k}")
    print(f"{'cell':8s} " + "".join(f"{a:>11s}" for a in ARMS) + "   ranks")
    for i, c in enumerate(cells):
        print(f"{c:8s} " + "".join(f"{X[i][j]:11.2f}" for j in range(k))
              + "   " + " ".join(f"{ranks[i][j]:.1f}" for j in range(k)))

    print("\naverage ranks (1 = best):")
    for j, a in enumerate(ARMS):
        print(f"    {a:10s} {Rbar[j]:.3f}" + ("   <- CONTROL" if a == CONTROL else ""))

    chi2 = 12.0 * N / (k * (k + 1)) * (np.sum(Rbar ** 2) - k * (k + 1) ** 2 / 4.0)
    p_chi2 = stats.chi2.sf(chi2, k - 1)
    # Iman-Davenport F
    denom = N * (k - 1) - chi2
    if denom > 0:
        F = (N - 1) * chi2 / denom
        df1, df2 = k - 1, (k - 1) * (N - 1)
        p_F = stats.f.sf(F, df1, df2)
    else:
        F, p_F, df1, df2 = float("inf"), 0.0, k - 1, (k - 1) * (N - 1)

    print(f"\nFRIEDMAN  chi2({k-1}) = {chi2:.3f}   p = {p_chi2:.3e}")
    print(f"IMAN-DAVENPORT  F({df1},{df2}) = {F:.3f}   p = {p_F:.3e}"
          f"   <- Demsar's preferred, less conservative")

    se = math.sqrt(k * (k + 1) / (6.0 * N))
    ci = ARMS.index(CONTROL)
    comps = []
    for j, a in enumerate(ARMS):
        if a == CONTROL:
            continue
        z = (Rbar[j] - Rbar[ci]) / se
        comps.append([a, z, 2 * stats.norm.sf(abs(z))])
    comps.sort(key=lambda r: r[2])
    m = len(comps)
    print(f"\nPOST-HOC vs control '{CONTROL}' (Holm step-down, m = {m} comparisons):")
    prev, reject_all, _adj = 0.0, True, []
    for i, (a, z, p) in enumerate(comps):
        adj = min(1.0, max(prev, p * (m - i)))
        prev = adj
        _adj.append(adj)
        rej = adj < 0.05
        reject_all &= rej
        print(f"    {CONTROL} vs {a:9s}  z = {z:+.3f}   raw p = {p:.3e}   "
              f"Holm-adj p = {adj:.3e}   {'REJECT H0' if rej else 'not significant'}")

    print("\nREADING:")
    best = ARMS[int(np.argmin(Rbar))]
    print(f"    best average rank: {best}")
    if p_F < 0.05:
        print("    Friedman rejects 'all three arms equivalent'.")
    else:
        print("    Friedman does NOT reject equivalence -- post-hoc results are not interpretable.")
    print(f"    control beats BOTH other arms after Holm: {reject_all}")

    # cross-check the hand-rolled exact Wilcoxon used in s3a_significance.py
    print("\nCROSS-CHECK of the hand-rolled exact Wilcoxon (s3a_significance.py) vs scipy:")
    for j, a in enumerate(ARMS):
        if a == CONTROL:
            continue
        d = np.log(X[:, j]) - np.log(X[:, ci])       # negative = easiness better
        try:
            r = stats.wilcoxon(d, alternative="less", method="exact")
            how = "exact"
        except Exception:
            r = stats.wilcoxon(d, alternative="less")
            how = "approx"
        print(f"    {CONTROL} vs {a:9s}  scipy W = {r.statistic:.0f}  p = {r.pvalue:.6f}  ({how})")

    if not complete:
        print("\nINTERIM -- not the verdict. Re-run when the reverse arm completes.")

    # Returned for analysis/manuscript_numbers.py -- see the note in s3a_significance.py.
    # One definition, many consumers: the registry must not re-implement the test.
    return dict(N=N, k=k, complete=complete, cells=cells, dropped=dropped,
                avg_rank={a: float(Rbar[j]) for j, a in enumerate(ARMS)},
                chi2=float(chi2), p_chi2=float(p_chi2),
                F=float(F), df1=df1, df2=df2, p_F=float(p_F),
                holm=[dict(arm=a, z=float(z), p_raw=float(pr), p_holm=float(ph),
                           reject=bool(ph < 0.05))
                      for (a, z, pr), ph in zip(comps, _adj)],
                control=CONTROL, best_rank=best, control_beats_all=bool(reject_all))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    a = ap.parse_args()
    main(a.size)
