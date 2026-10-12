"""FR1 -- does the MILP reproduce the arbiter's exact optimum?

The arbiter (analysis/arbiter.py) computes the optimum by exhaustive enumeration in exact
rationals, importing no project module. This drives it against joint_model_gurobi on the SAME
instance and requires agreement.

THE ONLY COUPLING IS THE INSTANCE. The adapter below hands the arbiter's own randomly generated
instance to the MILP builder. It must, or the two would be answering different questions. Nothing
about the MODEL crosses over: the arbiter's constraints were written independently, it uses no
big-M, no tolerance and no solver.

DISAGREEMENT PROTOCOL, fixed before any data (d240 rule 2). If the two differ, THE MILP IS THE
SUSPECT. The arbiter has no big-M to be undersized, no tolerance to be mis-set and no solver to
be trusted; it enumerates a finite set and checks each member exactly. That ordering is recorded
now so a disagreement is a finding rather than a negotiation.

BOTH ARMS ARE RUN. The vacuous arm must agree with the arbiter WITHOUT (26) enforced; the
corrected arm must agree WITH it. A single arm agreeing would not distinguish a model that
ignores (26) from one that enforces it.

    python analysis/arbiter_vs_milp.py [--n 4] [--sats 1] [--instances 200]
"""
import argparse
import json
import os
import sys
import time
from fractions import Fraction as F
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import arbiter as A

OUT = os.path.join(ROOT, "runs", "oracle")


class _N:
    """A node in the shape joint_model_gurobi expects. Floats, because gurobipy needs floats."""
    __slots__ = ("earliest", "latest", "demand", "serviceTime")

    def __init__(self, nd):
        self.earliest = float(nd.earliest)
        self.latest = float(nd.latest)
        self.demand = float(nd.demand)
        self.serviceTime = float(nd.service)


class Adapter:
    """The arbiter's instance, in the shape the MILP builder reads. Instance only, never model."""

    def __init__(self, inst, hard, valid=False):
        self.customers = list(inst.customers)
        self.satellites = list(inst.satellites)
        self.CDC = inst.CDC
        N = max(inst.nodes) + 1
        self.nodes = {i: _N(inst.nodes[i]) for i in inst.nodes}
        self.DistMatrix = [[float(inst.D[i][j]) if i < len(inst.D) and j < len(inst.D[0]) else 0.0
                            for j in range(N)] for i in range(N)]
        self.TransferDuration = float(inst.tau)
        self.CarCapacity = float(inst.CarCapacity)
        self.VesselCapacity = float(inst.VesselCapacity)
        self.penaltyCars = float(inst.penaltyCars)
        self.penaltyVessels = float(inst.penaltyVessels)
        self.travelcoststreet = float(inst.cost_street)
        self.travelcostwater = float(inst.cost_water)
        self.singleTransfer = True
        self.hardSingleTransfer = bool(hard)
        self.stationaryBarges = False
        # joint_model_gurobi defaults this to False -- K's OWN undersized constants. FR1 ran
        # that way and never said so, which left a disagreement ambiguous between "our MILP is
        # wrong" and "K's constants exclude the optimum". Those are opposite conclusions.
        self.validBigM = bool(valid)


def solve_milp(inst, hard, tl=120.0, valid=False):
    from joint_model_gurobi import joint_synchronized_gurobi
    from gurobipy import GRB
    p = Adapter(inst, hard, valid)
    r = joint_synchronized_gurobi(p, time_limit=tl, mip_gap=0.0, threads=2, log_output=False)
    st = r["status"]
    if st == GRB.INFEASIBLE:
        return None, True, "INFEASIBLE"
    return r["objVal"], (st == GRB.OPTIMAL), {GRB.OPTIMAL: "OPTIMAL",
                                              GRB.TIME_LIMIT: "TIME_LIMIT"}.get(st, str(st))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--sats", type=int, default=1)
    ap.add_argument("--instances", type=int, default=200)
    ap.add_argument("--tol", type=float, default=1e-7,
                    help="RELATIVE tolerance, scaled by the objective. Absolute 1e-6 "
                         "flagged a 2e-8 relative artifact as a model disagreement.")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--valid-bigm", action="store_true",
                    help="run the MILP arm with a VALID big-M instead of K's undersized "
                         "constants -- this is what separates a model defect from theirs")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print("FR1 -- MILP against the arbiter's exact optimum. |C|=%d  |P|=%d  %d instances."
          % (a.n, a.sats, a.instances))
    print("       |P|=1 is deliberate: with K's four satellites (26) cannot bind at this size,")
    print("       so a small-instance check would reproduce the oracle's existing blind spot.")
    print("       Disagreement protocol, fixed before data: THE MILP IS THE SUSPECT.")
    print()
    rows, bad, t0 = [], [], time.time()
    excluded, admitted, noise = [], [], []
    n_both_inf, n_cmp26 = 0, 0
    for s in range(a.start, a.start + a.instances):
        inst = A.Tiny(s, a.n, a.sats)
        rec = {"seed": s}
        for arm, hard in (("vacuous", False), ("corrected", True)):
            bb, _st, _nf = A.brute_optimum(inst, enforce_26=hard)
            mv, proven, status = solve_milp(inst, hard, valid=a.valid_bigm)
            rec[arm] = {"arbiter": (None if bb is None else float(bb)),
                        "milp": mv, "milp_status": status, "proven": proven}
            if bb is None and mv is None:
                n_both_inf += 1
                continue
            if bb is None or mv is None:
                bad.append("seed %d %s: arbiter %s, MILP %s -- one says infeasible, the other "
                           "does not" % (s, arm, "INFEASIBLE" if bb is None else "%.4f" % bb,
                                         "INFEASIBLE" if mv is None else "%.4f" % mv))
                continue
            if not proven:
                bad.append("seed %d %s: MILP did not prove optimality (%s) -- not a comparison"
                           % (s, arm, status))
                continue
            # DIRECTION IS THE DIAGNOSIS, and a symmetric absolute tolerance destroys it.
            #   MILP ABOVE the arbiter: the arbiter's value is ATTAINED -- it enumerates
            #     feasible solutions and checks each exactly -- so a solver proving a higher
            #     optimum means the model EXCLUDES an achievable solution. Real, at any size.
            #   MILP BELOW the arbiter: the model ADMITS something the arbiter rejects, which
            #     would mean a constraint is missing. Serious -- but also where floating point
            #     lives, so it is judged against the solver's guarantee, not against zero.
            # On 2026-09-21 a single |P|=2 case came in 7e-6 low -- 2e-8 RELATIVE -- and the
            # symmetric 1e-6 absolute test reported it as a disagreement, which blocked a
            # freeze on what was arithmetic noise.
            delta = mv - float(bb)
            scale = max(1.0, abs(float(bb)))
            if delta > a.tol * scale:
                excluded.append("seed %d %s: arbiter %.6f vs MILP %.6f (MILP HIGHER by %+.6f, "
                                "%.3f%%) -- the model excludes an achievable solution"
                                % (s, arm, float(bb), mv, delta, 100.0 * delta / scale))
            elif delta < -a.tol * scale:
                admitted.append("seed %d %s: arbiter %.6f vs MILP %.6f (MILP LOWER by %.6f, "
                                "%.1e relative) -- the model admits what the arbiter rejects"
                                % (s, arm, float(bb), mv, -delta, -delta / scale))
            elif abs(delta) > 1e-9:
                noise.append((s, arm, delta, abs(delta) / scale))
        v, c = rec["vacuous"]["arbiter"], rec["corrected"]["arbiter"]
        if v is not None and c is not None:
            rec["c26_price"] = c - v
            if c - v > a.tol:
                n_cmp26 += 1
        rows.append(rec)
        if (s - a.start + 1) % 25 == 0:
            print("   %4d instances  %.1fs  disagreements %d"
                  % (s - a.start + 1, time.time() - t0,
                     len(bad) + len(excluded) + len(admitted)))

    priced = [r["c26_price"] for r in rows if r.get("c26_price") is not None]
    print()
    real = bad + excluded + admitted
    print("   instances %d   real disagreements %d   arithmetic noise %d   "
          "both-infeasible arms %d" % (len(rows), len(real), len(noise), n_both_inf))
    print("      MILP ABOVE the arbiter (model EXCLUDES an achievable solution): %d"
          % len(excluded))
    print("      MILP BELOW the arbiter (model ADMITS what the arbiter rejects): %d"
          % len(admitted))
    print("      other (infeasibility mismatch, or optimality not proven):       %d" % len(bad))
    for b in (excluded + admitted + bad)[:12]:
        print("      " + b)
    if noise:
        worst = max(noise, key=lambda x: x[3])
        print("   arithmetic noise, NOT counted: %d case(s), worst %.1e relative on seed %d %s."
              % (len(noise), worst[3], worst[0], worst[1]))
        print("   Below the solver's own guarantee. Counting it would block a freeze on a")
        print("   rounding difference, which is what a symmetric absolute tolerance did.")
    print()
    if priced:
        nz = [p for p in priced if p > a.tol]
        print("   (26) PRICED BY THE ARBITER, exactly, on %d instances:" % len(priced))
        print("      instances where the corrected optimum is STRICTLY HIGHER: %d of %d (%.0f%%)"
              % (len(nz), len(priced), 100.0 * len(nz) / len(priced)))
        if nz:
            print("      price  min %+.3f  median %+.3f  max %+.3f"
                  % (min(nz), st.median(nz), max(nz)))
            print()
            print("      THIS IS THE (26) MEASUREMENT THE WHOLE ORACLE COULD NOT MAKE. On these")
            print("      instances K's published linearization admits an optimum that (26), the")
            print("      constraint their own article states, forbids -- established by exhaustive")
            print("      enumeration in exact arithmetic, with no solver and no tolerance.")
        else:
            print("      none -- at this size the corrected optimum never exceeds the vacuous one")
    print()
    print("FR1: %s" % ("PASS -- the MILP reproduces the arbiter's exact optimum on every "
                       "instance, both arms" if not real
                       else "%d REAL DISAGREEMENT(S)" % len(real)))
    json.dump(stamped({"n": a.n, "sats": a.sats, "valid_bigm": a.valid_bigm,
               "instances": len(rows), "disagreements": real,
               "excludes_achievable": excluded, "admits_rejected": admitted,
               "arithmetic_noise": [list(x) for x in noise],
               "rows": rows, "c26_strictly_higher": len([p for p in priced if p > a.tol]),
               "wall_s": round(time.time() - t0, 1)}, __file__),
              open(os.path.join(OUT, "FR1_arbiter_vs_milp_n%d_p%d%s.json"
                                % (a.n, a.sats, "_validM" if a.valid_bigm else "")), "w"),
              indent=1, default=str)
    return 1 if real else 0


if __name__ == "__main__":
    sys.exit(main())
