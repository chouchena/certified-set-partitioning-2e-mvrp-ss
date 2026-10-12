"""Is the (26) gate slack really the mechanism, and does the fix close it?

THE SUSPECT. joint_model_cplex enforces corrected (26) as a big-M disjunction gated on vip:

    gate = Mbig * (2 - vip[i,p] - vip[j,p])          # 0 only when BOTH transfer at p
    u[j] >= u[i] + TD - Mbig*(1 - o[i,j]) - gate
    u[i] >= u[j] + TD - Mbig*o[i,j]      - gate

`gate` is exactly zero only if vip is exactly 1. At the solver's integrality tolerance vip may be
1 - tol, and _extract_solution still reads it as 1 (`> 0.5`). The model then permits a separation
of TD - Mbig*2*tol while the extracted solution claims both customers transfer at p, and
verifier3's exact check rejects it.

WHY ELIMINATION IS NOT ENOUGH. Every other hypothesis was ruled out -- hubs derive from the same
vip the gate uses, TD equals the verifier's U exactly, spatial_destroy does go through the MILP,
and an undersized Mbig would over-constrain rather than under-constrain. That makes this the only
survivor, which is not the same as showing it is the cause.

THE TEST. The mechanism makes a QUANTITATIVE prediction that nothing else does:

    permitted violation  =  Mbig * 2 * integrality_tol        (linear in Mbig)

So inflate Mbig and the violations must grow in proportion; shrink it and they must vanish. A
mechanism that is not the cause has no reason to track Mbig at all.

    NO FALSE POSITIVE   if violations do NOT scale with Mbig, the suspect is wrong and the fix
                        would be treating the wrong thing. The run says so rather than assuming.
    NO FALSE NEGATIVE   with the fix applied (require TD + eps, eps > Mbig*2*tol), violations must
                        be ZERO at every multiplier tested, including the inflated ones where the
                        unfixed model fails loudly.

CELLS. Small instances from the arbiter's own generator, which is independent of the project's
builder, at the sizes and satellite counts where (26) actually binds: |P| = 1 forces every
transfer onto one satellite, which is the condition the constraint exists for. Small means many
replicates, and exactness -- the violation is measured on the returned u values directly, with no
heuristic in the way.

    python analysis/c26_gate_validation.py [--instances 60] [--n 5]
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import arbiter as A
from arbiter_vs_milp import Adapter

OUT = os.path.join(ROOT, "runs", "oracle")

# Multipliers on Mbig. 1.0 is the shipped model. The mechanism predicts the permitted violation
# scales with these; anything else predicts no relationship.
MULTIPLIERS = (1.0, 10.0, 100.0, 1000.0)


def worst_violation(sol, tau):
    """Largest amount by which two same-satellite transfers sit closer than tau. Exact."""
    tset = [int(c) for c in sol.get("vi", [])]
    hubs = [int(q) for q in sol.get("hubs", [])]
    u = {int(k): float(v) for k, v in (sol.get("ui") or {}).items()}
    hub = dict(zip(tset, hubs))
    worst, pairs = 0.0, 0
    for a in range(len(tset)):
        for b in range(a + 1, len(tset)):
            i, j = tset[a], tset[b]
            if hub.get(i) != hub.get(j) or i not in u or j not in u:
                continue
            pairs += 1
            gap = abs(u[i] - u[j])
            if gap < tau:
                worst = max(worst, tau - gap)
    return worst, pairs


def solve_with(inst, mult, eps, tl=60.0):
    """Solve the corrected-(26) model with Mbig scaled by `mult` and a separation of TD + eps."""
    import joint_model_cplex as J
    p = Adapter(inst, hard=True, valid=True)
    orig = J.build_joint_model
    # The scaling and the epsilon are injected here rather than edited into the builder, so the
    # shipped file is untouched and the comparison is against the code that actually runs.
    J._C26_MBIG_MULT, J._C26_EPS = mult, eps
    try:
        H = orig(p)
        m = H.m
        try:
            m.set_time_limit(tl)
        except Exception:
            pass
        sol = m.solve()
        if sol is None:
            return None, None
        from joint_model_cplex import _extract_solution
        return _extract_solution(H), float(p.TransferDuration)
    finally:
        J._C26_MBIG_MULT, J._C26_EPS = 1.0, 0.0


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, default=60)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--sats", type=int, default=1)
    ap.add_argument("--eps", type=float, default=0.0)
    a = ap.parse_args()

    print("(26) GATE VALIDATION -- does the violation scale with Mbig, and does eps close it?")
    print("   |C|=%d  |P|=%d  %d instances per multiplier   eps=%.3f"
          % (a.n, a.sats, a.instances, a.eps))
    print()
    print("   PREDICTION of the suspect: permitted violation = Mbig x 2 x integrality_tol,")
    print("   so it grows LINEARLY with the multiplier. Any other cause has no reason to.")
    print()
    print("   %-10s %9s %12s %14s %14s %10s"
          % ("Mbig x", "solved", "violations", "worst", "mean", "sat-pairs"))
    rows = []
    for mult in MULTIPLIERS:
        worsts, solved, npairs = [], 0, 0
        for s in range(a.instances):
            inst = A.Tiny(s, a.n, a.sats)
            try:
                sol, tau = solve_with(inst, mult, a.eps)
            except Exception as exc:
                print("      instance %d raised %s" % (s, type(exc).__name__))
                continue
            if sol is None:
                continue
            solved += 1
            w, pr = worst_violation(sol, tau)
            worsts.append(w); npairs += pr
        bad = [w for w in worsts if w > 1e-9]
        rows.append(dict(mult=mult, solved=solved, violations=len(bad), same_sat_pairs=npairs,
                         worst=max(worsts) if worsts else 0.0,
                         mean=(sum(bad) / len(bad)) if bad else 0.0))
        print("   %-10.0f %9d %12d %14.6f %14.6f %10d"
              % (mult, solved, len(bad), rows[-1]["worst"], rows[-1]["mean"], npairs))

    print()
    base = next((r for r in rows if r["mult"] == 1.0), None)
    top = rows[-1]
    scaled = (base and top["worst"] > 0 and base["worst"] >= 0
              and top["worst"] > 10 * max(base["worst"], 1e-9))
    if a.eps > 0:
        clean = all(r["violations"] == 0 for r in rows)
        print("   FIX ARM (eps=%.3f): %s" % (a.eps,
              "NO violation at ANY multiplier -- the fix closes it (no false negative)" if clean
              else "STILL VIOLATING -- the fix does NOT close it"))
    else:
        print("   SUSPECT ARM: %s" % (
            "violations SCALE with Mbig -- the gate slack is confirmed as the mechanism"
            if scaled else
            "violations do NOT scale with Mbig -- THE SUSPECT IS WRONG. Do not apply the fix; "
            "the cause is something else and this run says so."))
    json.dump(stamped({"rows": rows, "n": a.n, "sats": a.sats, "eps": a.eps,
                       "instances": a.instances, "scaled_with_mbig": bool(scaled)},
                      __file__, "joint_model_cplex.py"),
              io.open(os.path.join(OUT, "c26_gate_validation_eps%g.json" % a.eps), "w",
                      encoding="utf-8"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
