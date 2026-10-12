"""L0 and L1b of the transcription oracle (DESIGN_transcription_oracle_v4.md).

L0  BINDING PRE-PASS, structural, no solve. Per constraint, how many of the 8 PROVEN n20/n30 cells
    give it a chance to bind. GATES L3: if fewer than half the constraints have an opportunity,
    L3 is decorative and is reported as such rather than run.

L1b DISTANCE ORACLE. Solve the 27 proven n10 cells on the VACUOUS arm -- K's own linearization, so
    the comparison is against their implementation -- and compare to their published BK.

    CM1: do NOT test per-cell pass/fail. K publish to one decimal, so the resolution is +-0.05,
    and a 0.005 rounding slip on each of ~12 arcs shifts z by ~0.06 -- right at that tolerance.
    Collect the 27 SIGNED residuals instead. Rounding noise is SYMMETRIC about zero; a systematic
    rebuild error is BIASED. 27 signed residuals detect a bias far below the per-cell tolerance.

    CM2: these are 27 instances through ONE rebuild code path, not 27 independent tests.
    CM3: n10 is RELATIVELY slack, not slack -- a mismatch stays ambiguous between instance and
         constraints. L1b NARROWS the attribution problem; it does not eliminate it.
    CM4: record the solver's own optimality status. Anything short of proven is INCONCLUSIVE.

    python analysis/oracle_L0_L1b.py
"""
import json
import os
import statistics as st
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import instance_view
import verifier3

OUT = os.path.join(ROOT, "runs", "oracle")
KREF = os.path.join(ROOT, "data", "karademir2025", "k_reference.json")
CELLS = (["C20%d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC20%d" % i for i in range(1, 9)])


def kref():
    return json.load(open(KREF, encoding="utf-8"))


def proven(k, size):
    return {c: v for c, v in k["table3"]["per_instance"][str(size)].items()
            if v.get("joint_gap") == 0}


# ---------------------------------------------------------------- L0
def binding_opportunity(inst, n):
    """Structural: can published constraint n bind on this instance? No solve."""
    nd, D = inst.nodes, inst.D
    C, P = list(inst.customers), list(inst.satellites)
    dem = sum(nd[i].demand for i in C)
    horizon = nd[inst.CDC].latest - nd[inst.CDC].earliest
    xfers = max(1.0, len(C) / 4.0)
    Qs, Qw = instance_view.LEFV_CAPACITY, instance_view.VESSEL_CAPACITY

    if n in (2, 3, 4, 8, 9, 10, 15, 16, 17, 25):
        return True                                  # structural: always live
    if n == 5:
        return dem > Qs                              # more than one street trip needed
    if n in (6, 11, 12):
        return True                                  # timing always evaluated on any route
    if n == 13:
        return horizon > 0
    if n in (18, 19):
        return dem > Qw                              # vessel capacity can be reached
    if n == 20:
        return xfers > len(P)                        # vessels must chain tasks
    if n == 26:
        # (26) binds only if a satellite can carry 2+ transfers within tau of each other
        return inst.tau > 0 and (xfers / len(P)) >= 2.0
    if n in (1, 7, 14, 21, 22, 23, 24, 27, 28, 29, 30):
        return None                                  # objective / encoding: not a binding question
    return None


def run_L0(k):
    cells = []
    for size in (20, 30):
        for c in proven(k, size):
            cells.append((c, size))
    print("L0 -- BINDING PRE-PASS over the %d PROVEN n20/n30 cells (no solve)" % len(cells))
    print("   cells: %s" % ", ".join("%s/n%d" % x for x in cells))
    print()
    insts = {}
    for c, size in cells:
        raw = instance_view.VInstance._load_json(c)
        insts[(c, size)] = instance_view.VInstance(
            c, size, wls=0.1, tau=verifier3.tau_for(raw, size), proximity=0.0)
    rows, live, na = [], 0, 0
    print("   %-4s %-28s %s" % ("(n)", "constraint", "cells with a binding opportunity"))
    for n in range(1, 31):
        note = verifier3.PUBLISHED[n][2][:28]
        hits = [k2 for k2, i in insts.items() if binding_opportunity(i, n) is True]
        kind = binding_opportunity(next(iter(insts.values())), n)
        if kind is None:
            na += 1
            rows.append(dict(constraint=n, opportunity=None, cells=[]))
            print("   %-4d %-28s  n/a (objective or encoding)" % (n, note))
            continue
        if hits:
            live += 1
        rows.append(dict(constraint=n, opportunity=len(hits),
                         cells=["%s/n%d" % x for x in hits]))
        print("   %-4d %-28s  %d/%d%s" % (n, note, len(hits), len(cells),
                                          "" if hits else "   <- NEVER BINDS HERE"))
    testable = 30 - na
    print()
    print("   constraints with >=1 binding opportunity : %d of %d testable (%d n/a)"
          % (live, testable, na))
    gate = live >= testable / 2.0
    print("   L3 GATE: %s" % ("PASS -- L3 is worth running"
                              if gate else "FAIL -- L3 is DECORATIVE and must not be run"))
    return rows, gate, cells


# ---------------------------------------------------------------- L1b
def run_L1b(k, tl=300.0, threads=4):
    from build_instance import build
    from joint_model_gurobi import joint_synchronized_gurobi
    from gurobipy import GRB

    pv = proven(k, 10)
    print()
    print("L1b -- DISTANCE ORACLE: %d proven n10 cells, VACUOUS arm, proximity 0.0" % len(pv))
    print("   comparison is against K's IMPLEMENTATION, never their article")
    print()
    print("   %-7s %12s %10s %10s %-6s %-10s %7s" % ("cell", "ours", "K BK", "residual",
                                                      "round", "status", "sec"))
    rows = []
    t0 = time.time()
    for c in CELLS:
        if c not in pv:
            continue
        p = build(c, 10, wls=0.1, tau="formula", proximity=0.0)
        p.hardSingleTransfer = False                     # K's own linearization
        t1 = time.time()
        r = joint_synchronized_gurobi(p, time_limit=tl, mip_gap=0.0, threads=threads,
                                      log_output=False)
        secs = time.time() - t1
        ours = r["objVal"]
        bk = pv[c]["joint_bk"]
        proven_ok = (r["status"] == GRB.OPTIMAL)
        resid = None if ours is None else ours - bk
        rounds_ok = None if ours is None else (abs(round(ours, 1) - bk) < 1e-9)
        rows.append(dict(cell=c, ours=ours, k_bk=bk, residual=resid, rounds_to_k=rounds_ok,
                         proven=proven_ok, status=int(r["status"]), seconds=round(secs, 1)))
        print("   %-7s %12s %10.1f %10s %-6s %-10s %7.1f"
              % (c, ("%.4f" % ours) if ours is not None else "-", bk,
                 ("%+.4f" % resid) if resid is not None else "-",
                 ("ROUNDS" if rounds_ok else "NO") if rounds_ok is not None else "-",
                 "PROVEN" if proven_ok else "INCONCLUSIVE", secs))
    print()
    print("   total %.1f min" % ((time.time() - t0) / 60))

    ok = [r for r in rows if r["residual"] is not None and r["proven"]]
    res = [r["residual"] for r in ok]
    inconc = [r["cell"] for r in rows if not r["proven"]]
    print()
    print("L1b RESULT -- the RESIDUAL DISTRIBUTION, not per-cell pass/fail (CM1)")
    print("   proven cells used   : %d of %d   INCONCLUSIVE: %s"
          % (len(ok), len(rows), inconc or "none"))
    rk = [r for r in ok if r["rounds_to_k"]]
    print("   PRIMARY TEST -- does round(ours,1) equal K's printed value?")
    print("   agrees        : %d of %d proven cells" % (len(rk), len(ok)))
    bad = [r["cell"] for r in ok if not r["rounds_to_k"]]
    if bad:
        print("   DISAGREES     : %s  <- these are real discrepancies, not rounding" % bad)
    print()
    print("   SECONDARY -- residual distribution, for systematic bias below the tolerance")
    if res:
        pos = sum(1 for x in res if x > 1e-9)
        neg = sum(1 for x in res if x < -1e-9)
        zer = len(res) - pos - neg
        print("   residual mean       : %+.6f" % st.mean(res))
        print("   residual median     : %+.6f" % st.median(res))
        print("   residual min / max  : %+.6f / %+.6f" % (min(res), max(res)))
        print("   sign balance        : %d positive, %d negative, %d zero" % (pos, neg, zer))
        print("   |residual| > 0.05   : %d  (beyond K's publication tolerance)"
              % sum(1 for x in res if abs(x) > 0.05))
        print()
        # rounding noise is symmetric about 0; a rebuild error is biased
        biased = abs(st.mean(res)) > 0.02 or (min(pos, neg) == 0 and len(res) >= 8)
        if biased:
            print("   VERDICT: BIASED -- the residuals do not look like symmetric rounding noise.")
            print("   That is a DISTANCE-REBUILD finding and must be resolved before any z*")
            print("   comparison at L3 is attributed to the constraint transcription.")
        else:
            print("   VERDICT: UNBIASED -- consistent with one-decimal rounding of a correct")
            print("   rebuild. This NARROWS the attribution problem (BM1); per CM2 it is 27")
            print("   instances through ONE code path, and per CM3 n10 is relatively slack, so")
            print("   it does not eliminate it.")
    os.makedirs(OUT, exist_ok=True)
    json.dump(stamped({"rows": rows}, __file__), open(os.path.join(OUT, "L1b.json"), "w"),
              indent=1, default=str)
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(OUT, exist_ok=True)
    k = kref()
    l0, gate, cells = run_L0(k)
    json.dump(stamped({"rows": l0, "gate": gate, "cells": ["%s/n%d" % c for c in cells]}, __file__),
              open(os.path.join(OUT, "L0.json"), "w"), indent=1, default=str)
    run_L1b(k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
