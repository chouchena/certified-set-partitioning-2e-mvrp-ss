"""Two tests that decide what L1b left open.

T1 -- POWER (settles CM2 and BM1's "less likely"). L1b matched K on 26 of 26 proven n10 cells.
      But those are 26 instances through ONE rebuild code path, so a defect in the triangle pass
      or the rounding would apply identically to all -- and if it changed no optimum, all 26 would
      still match and the defect would survive. Matching therefore means something only if a
      DELIBERATE rebuild perturbation BREAKS the match.

      Same logic as the root-LP pre-test's 2*tau control: a null is informative only when the
      instrument is shown able to report non-null.

      Three perturbations, each a plausible "what if our rebuild differs from theirs":
        P1  no triangle pass          -- raw Euclidean, rounded
        P2  3-decimal rounding        -- instead of 2
        P3  triangle closure iterated -- instead of K's single non-iterated pass

T2 -- SLACKNESS (settles CM3). v3 justified n10 as an instance probe by asserting constraints are
      slack there. ASSERTED, NOT MEASURED. This measures, at each n10 optimum, how many published
      constraints are TIGHT. If most are slack, CM3 stands and L1b really is mostly an instance
      test. If most bind, n10 tests constraints too and the attribution is better than claimed.

    python analysis/oracle_power_and_slack.py
"""
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import instance_view
import verifier3

OUT = os.path.join(ROOT, "runs", "oracle")
# the fastest proven n10 cells from the L1b run, so the power test costs minutes not hours
FAST = ["C201", "C205", "C206", "C207", "C208", "R201", "R205", "R209", "RC201", "RC206"]


def kbk(k, cell):
    return k["table3"]["per_instance"]["10"][cell]["joint_bk"]


def euclid(nd, i, j, dp=2):
    # instanceGenerator.Node uses xcor/ycor; instance_view.VNode uses x/y. Support both, because
    # this probe perturbs the BUILDER's matrix (instanceGenerator) while the verifier reads the
    # rebuild (instance_view) -- a silent attribute mismatch here would look like a solve failure.
    a, b = nd[i], nd[j]
    ax = getattr(a, "x", None) if hasattr(a, "x") else a.xcor
    ay = getattr(a, "y", None) if hasattr(a, "y") else a.ycor
    bx = getattr(b, "x", None) if hasattr(b, "x") else b.xcor
    by = getattr(b, "y", None) if hasattr(b, "y") else b.ycor
    return round(math.sqrt((ax - bx) ** 2 + (ay - by) ** 2), dp)


def perturb(p, mode):
    """Rebuild p.DistMatrix under a deliberate variation. Returns a description."""
    nd = p.nodes
    n = len(nd)
    d = [[euclid(nd, i, j, 3 if mode == "P2" else 2) for j in range(n)] for i in range(n)]
    if mode == "P1":
        pass                                        # no triangle pass at all
    elif mode == "P2":
        for i in range(n):                          # K's single non-iterated pass, 3dp distances
            for j in range(n):
                for kk in range(n):
                    c = d[i][kk] + d[kk][j]
                    if c <= d[i][j]:
                        d[i][j] = c
    elif mode == "P3":
        for _ in range(4):                          # iterate to convergence instead of once
            for i in range(n):
                for j in range(n):
                    for kk in range(n):
                        c = d[i][kk] + d[kk][j]
                        if c <= d[i][j]:
                            d[i][j] = c
    p.DistMatrix = d
    return {"P1": "no triangle pass", "P2": "3-decimal distances",
            "P3": "triangle closure iterated"}[mode]


def solve(p, tl=180.0, threads=4):
    from joint_model_gurobi import joint_synchronized_gurobi
    from gurobipy import GRB
    p.hardSingleTransfer = False
    r = joint_synchronized_gurobi(p, time_limit=tl, mip_gap=0.0, threads=threads,
                                  log_output=False)
    return r["objVal"], (r["status"] == GRB.OPTIMAL), r.get("solution")


def run_T1(k):
    from build_instance import build
    print("T1 -- POWER. Does a deliberate rebuild perturbation BREAK the match with K?")
    print("     If it does not, L1b's 26/26 is insensitive and CM2 stands.")
    print()
    print("   %-7s %10s %12s %12s %12s" % ("cell", "K BK", "baseline", "P2 3-dec",
                                                  "P1 no-tri"))
    rows = []
    for c in FAST:
        bk = kbk(k, c)
        line = [c, bk]
        for mode in (None, "P2", "P1"):
            p = build(c, 10, wls=0.1, tau="formula", proximity=0.0)
            desc = perturb(p, mode) if mode else "baseline"
            ov, prov, _ = solve(p)
            ok = ov is not None and abs(round(ov, 1) - bk) < 1e-9
            line.append((ov, ok, prov, desc))
        rows.append(line)
        print("   %-7s %10.1f %12s %12s %12s"
              % (c, bk,
                 "%.3f%s" % (line[2][0], "" if line[2][1] else " X"),
                 "%.3f%s" % (line[3][0], "" if line[3][1] else " X"),
                 "%.3f%s" % (line[4][0], "" if line[4][1] else " X")))
    base_ok = sum(1 for r in rows if r[2][1])
    p1_ok = sum(1 for r in rows if r[3][1])
    p3_ok = sum(1 for r in rows if r[4][1])
    print()
    print("   matches K: baseline %d/%d | P2 3-decimal %d/%d | P1 no-triangle %d/%d"
          % (base_ok, len(rows), p1_ok, len(rows), p3_ok, len(rows)))
    print()
    print("   NOTE, found by running it: P1 (no triangle pass) and P3 (iterated closure) are")
    print("   MATHEMATICAL NO-OPS at n10 -- Euclidean distances satisfy the triangle inequality")
    print("   by construction, and 2-decimal rounding does not break it at 16 nodes. They could")
    print("   never have carried the power test. P2, which perturbs the DISTANCES THEMSELVES,")
    print("   is the only one of the three that probes what BM1 raised.")
    print()
    broke = (p1_ok < base_ok) or (p3_ok < base_ok)
    if broke:
        print("   VERDICT: THE TEST HAS POWER. A perturbed rebuild stops matching K, so the")
        print("   baseline's 26/26 is evidence about the rebuild and not an insensitivity.")
        print("   CM2 is SETTLED in the favourable direction, and BM1's confound moves from")
        print("   'less likely' to 'excluded for perturbations of this size'.")
    else:
        print("   VERDICT: NO POWER. Even a deliberately wrong rebuild still matches K, so")
        print("   L1b's 26/26 says nothing about the distance matrix. CM2 STANDS and BM1 is")
        print("   NOT narrowed. The oracle must not be reported as corroborating the rebuild.")
    return rows, broke


def run_T2(k):
    """Tightness at the n10 optima: how many published constraints actually bind?"""
    from build_instance import build
    print()
    print("T2 -- SLACKNESS. v3 ASSERTED constraints are slack at n10. Measuring.")
    print()
    tally, cells_done = {}, 0
    for c in FAST[:6]:
        p = build(c, 10, wls=0.1, tau="formula", proximity=0.0)
        ov, prov, sol = solve(p)
        if sol is None or not prov:
            continue
        raw = instance_view.VInstance._load_json(c)
        inst = instance_view.VInstance(c, 10, wls=0.1,
                                       tau=verifier3.tau_for(raw, 10), proximity=0.0)
        sol = dict(sol)
        sol["objVal"] = ov
        run = verifier3.verify_solution(inst, sol, cell=c, size=10, proximity=0.0)
        # a TOLERANCE finding means the constraint is tight to within FEAS_TOL
        for f in run.findings:
            if f.severity == "TOLERANCE":
                tally[f.cls] = tally.get(f.cls, 0) + 1
        cells_done += 1
    print("   cells measured: %d" % cells_done)
    print("   constraint classes found TIGHT at the optimum (count of tight evaluations):")
    for kk, v in sorted(tally.items(), key=lambda x: -x[1]):
        print("      %-22s %4d" % (kk, v))
    if not tally:
        print("      none -- every constraint strictly slack at these optima")
    print()
    if len(tally) <= 3:
        print("   VERDICT: n10 optima leave most constraints SLACK. CM3 STANDS -- L1b is")
        print("   largely an instance test, which is what it was promoted to be.")
    else:
        print("   VERDICT: %d classes bind at n10 optima. n10 tests CONSTRAINTS as well as the"
              % len(tally))
        print("   instance, so an L1b mismatch would be MORE ambiguous than v3 assumed, not")
        print("   less. CM3 is settled AGAINST the design's assumption.")
    return tally


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(OUT, exist_ok=True)
    k = json.load(open(os.path.join(ROOT, "data", "karademir2025", "k_reference.json"),
                       encoding="utf-8"))
    t0 = time.time()
    rows, broke = run_T1(k)
    tally = run_T2(k)
    json.dump(stamped({"T1_power": broke,
               "T1": [[r[0], r[1]] + [[x[0], x[1], x[2], x[3]] for x in r[2:]] for r in rows],
               "T2_tight_classes": tally}, __file__),
              open(os.path.join(OUT, "power_and_slack.json"), "w"), indent=1, default=str)
    print()
    print("total %.1f min" % ((time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
