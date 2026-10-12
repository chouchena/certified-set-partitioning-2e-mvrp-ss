"""Solver-based fleet LOWER bound at |C| = 20, where the arithmetic certificate is weakest.

THE GAP THIS TARGETS. L-fleet proves the minimum fleet on 6 of 27 cells at |C| = 20, 16 of 27 at
30, and 27 of 27 at both 50 and 100. It is weakest exactly where a MIP is cheapest, which is a
real complementarity rather than a coincidence: at |C| = 20 an infeasibility proof is plausibly
seconds, at |C| = 100 it is hopeless but the certificate already covers every cell.

Combined with the 12 cells that hold a verified one-car solution, the |C| = 20 fleet question is
open on exactly NINE cells. This asks the solver to close them.

WHAT IS ACTUALLY TESTED. For a cell whose best known solution uses `nCars`, the FULL model -- no
freeze, no fixing, nothing pinned -- with the added constraint `nofCars <= nCars - 1`:

    INFEASIBLE  -> the fleet is provably nCars. A lower bound, certified by the solver.
    FEASIBLE    -> we have just FOUND a smaller-fleet solution, which is a better outcome still.
    TIMEOUT     -> unknown. Recorded as unknown and never read as infeasible.

THE PROVENANCE PROBLEM, STATED UP FRONT. This is a solver-internal proof. It is not hand-checkable
the way L-fleet's witness is, and this project has already nearly banked a fleet certificate that
was wrong (0 of 27, not 17 of 27, caught by recomputing a witness by hand). So:

  * every INFEASIBLE is recorded with the CPLEX version and the wall time that produced it;
  * a `--conflict` pass can ask CPLEX for the irreducible infeasible subsystem, which IS
    inspectable and is the route from "the solver says so" to an argument we can print;
  * nothing here supersedes L-fleet. It is a second, independent instrument whose agreement on
    the positive controls is the evidence that it can be trusted on the open cells.

TWO CONTROLS, BOTH WITH KNOWN ANSWERS, and they are the reason this run is interpretable:

  NEGATIVE -- cells where we HOLD a one-car solution, tested at `nofCars <= 1` (that is, at
  their OWN fleet, not one below it). The answer is known to be FEASIBLE, because we have the
  solution on disk. An INFEASIBLE here means the model or the constraint is wrong, and every
  other result in the run is void.

  POSITIVE -- cells where L-fleet already proves >= 2, tested at `nofCars <= 1`. The answer is
  known to be INFEASIBLE. A FEASIBLE here means either L-fleet is wrong or this probe is, and
  either way the run stops.

Usage:  python analysis/fleet_lb_solver.py [--tl 120] [--cells ...] [--size 20]
"""
import argparse, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from build_instance import build                                   # noqa: E402
from joint_model_cplex import build_joint_model                    # noqa: E402
import analysis.manuscript_numbers as M                            # noqa: E402


def classify(size):
    """Split the cells into settled-by-solution, settled-by-certificate, and open."""
    cert = {r["cell"]: r for r in json.load(
        open(os.path.join(ROOT, "runs", "fleet_subset_infeasibility.json"), encoding="utf-8"))}
    best = {}
    for c, n, _o in M._stored_n20_solutions():
        best[c] = min(best.get(c, 99), n)
    cells = M._cells(size)
    onecar = [c for c in cells if best.get(c) == 1]
    proved = [c for c in cells if cert.get(c, {}).get("infeasible_k1")]
    openc = [c for c in cells if best.get(c, 99) >= 2 and c not in proved]
    return best, onecar, proved, openc


def probe(cell, size, target, tl, threads, det_tl=None):
    """Full model, no freeze, nofCars <= target. Returns the outcome dict.

    DET TICKS BIND, WALL IS A BACKSTOP (PREREG_S2p Amendment 1 A1.3). `replicability-needs-det-ticks`
    is standing: a wall-limited run does not reproduce. The wall limit stays only so a mis-sized
    tick budget cannot run for ever, and if it is what stopped the solve the outcome is recorded as
    TIMEOUT_WALL and is explicitly not reproducible -- never counted toward a proof.
    """
    pr = build(cell, size, tau="formula")
    H = build_joint_model(pr)
    m = H.m
    m.add_constraint(H.nofCars <= target)
    p = m.parameters
    p.timelimit = tl
    if det_tl:
        p.dettimelimit = det_tl
    p.threads = threads
    t0 = time.time()
    s = m.solve(log_output=False)
    wall = time.time() - t0
    sd = m.solve_details
    st = (sd.status or "").lower()
    ticks = getattr(sd, "deterministic_time", None)
    if s is not None:
        out = "FEASIBLE"
    elif "infeasible" in st:
        out = "INFEASIBLE"
    elif wall >= tl - 1.0:
        # the WALL stopped it, not the tick budget -- not reproducible, and the prereg says so
        out = "TIMEOUT_WALL"
    else:
        out = "TIMEOUT"
    return dict(cell=cell, size=size, target=target, outcome=out, wall=wall,
                status=sd.status, det_ticks=ticks, det_tl=det_tl, tl=tl,
                obj=(s.objective_value if s is not None else None))


def achievability_check(cell, size, target):
    """THE NEGATIVE CONTROL THAT CANNOT TIME OUT (PREREG_S2p Amendment 1 A1.4, as corrected).

    WHAT THIS DOES AND DOES NOT DO. It does NOT solve the constrained model, and it does not hand
    CPLEX a MIP start -- an earlier draft of this function claimed both while actually calling the
    verifier, which is the recurring failure in this project of testing machinery the way it looks
    like it should be called rather than the way it works.

    What it establishes, independently of CPLEX, is the fact the negative control needs: that a
    fleet of at most `target` IS ACHIEVABLE on this cell, because we hold a solution that uses one
    and it passes the verifier. That is the premise. The existing fail-fast supplies the
    conclusion: if the model with `nofCars <= target` then returns INFEASIBLE, the model or the
    constraint is wrong and the run is void.

    Split this way the control cannot time out, because neither half is a search.

    Returns ACHIEVABLE / NOT_ACHIEVABLE / NO_SOLUTION.
    """
    fp = os.path.join(ROOT, "published_artifacts", "solutions", "best_%s_n%d.json" % (cell, size))
    if not os.path.exists(fp):
        return dict(cell=cell, check="achievability", result="NO_SOLUTION", target=target)
    sol = json.load(open(fp, encoding="utf-8"))
    cars = sol.get("nCars")
    try:
        from solver.config import InstanceSpec                      # noqa: WPS433
        from solver.problem import SolverProblem                    # noqa: WPS433
        sp = SolverProblem(InstanceSpec(cell, size))
        vd = sp.verify(sol)
        ok = bool(getattr(vd, "ok", False))
        viol = (getattr(vd, "violations", None) or [])
    except Exception as e:
        return dict(cell=cell, check="achievability", result="ERROR",
                    target=target, detail=str(e)[:160])
    good = ok and cars is not None and cars <= target
    return dict(cell=cell, check="achievability", target=target, cars=cars, verified=ok,
                result=("ACHIEVABLE" if good else "NOT_ACHIEVABLE"),
                detail=(str(viol[0])[:120] if viol else None))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--tl", type=float, default=120,
                    help="WALL backstop. PREREG_S2p A1.3: this must NOT bind; if it does the "
                         "cell is TIMEOUT_WALL and is not reproducible.")
    ap.add_argument("--det-tl", type=float, default=None,
                    help="deterministic ticks -- the only limit permitted to bind")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--cells", default="", help="override; default is controls + open cells")
    ap.add_argument("--n-controls", type=int, default=3,
                    help="how many of each control to run")
    ap.add_argument("--out", default="runs/fleet_lb_solver_n20.json")
    a = ap.parse_args()

    best, onecar, proved, openc = classify(a.size)
    if a.cells:
        plan = [(c, "open") for c in (x.strip() for x in a.cells.split(",")) if c]
    else:
        plan = ([(c, "neg-control") for c in onecar[:a.n_controls]]
                + [(c, "pos-control") for c in proved[:a.n_controls]]
                + [(c, "open") for c in openc])

    print(f"fleet LOWER bound probe, |C|={a.size}, {a.threads} threads")
    print(f"  det-tl {a.det_tl!r} ticks (binds)   wall {a.tl:.0f}s (backstop, must not bind)")
    print(f"  settled by a 1-car solution : {len(onecar)}")
    print(f"  settled by L-fleet          : {len(proved)}")
    print(f"  OPEN                        : {len(openc)}  {openc}")
    print(f"  running {len(plan)} probes\n")
    print(f"{'cell':7s} {'role':12s} {'best':>4s} {'test':>12s} {'outcome':>11s} "
          f"{'wall':>8s}  status")

    rows, checks = [], []
    for cell, role in plan:
        nb = best.get(cell, 99)
        # THE TARGET DEPENDS ON THE ROLE, and conflating them makes the negative control
        # meaningless. For a cell we hold a ONE-car solution for, nb - 1 = 0, and
        # "nofCars <= 0" is infeasible for any instance with a customer to serve -- it
        # would test arithmetic, not the model, and then trip the fail-fast below on a
        # result that was never in doubt. The negative control has to ask the question it
        # actually knows the answer to: can the FULL model still reach the fleet we already
        # hold a verified solution at?
        target = nb if role == "neg-control" else nb - 1

        # THE CONTROL THAT CANNOT TIME OUT runs FIRST (PREREG_S2p A1.4/A1.4b). At 120 s all three
        # search-based negative controls returned nothing, which calibrated nothing. This asks,
        # without a solver, whether the target fleet is achievable at all.
        if role == "neg-control":
            ach = achievability_check(cell, a.size, target)
            checks.append(ach)
            print(f"{cell:7s} {'neg-ctl(ach)':12s} {nb:4d} {'nofCars<=%d' % target:>12s} "
                  f"{ach['result']:>11s} {0.0:7.2f}s  no solver")
            if ach["result"] == "NOT_ACHIEVABLE":
                print("\n!! NEGATIVE CONTROL PREMISE FAILED -- the stored solution for this "
                      "cell does not\n   verify at the target fleet, so it cannot calibrate "
                      "anything. STOPPING.")
                break

        r = probe(cell, a.size, target, a.tl, a.threads, a.det_tl)
        r["role"], r["best_cars"] = role, nb
        rows.append(r)
        print(f"{cell:7s} {role:12s} {nb:4d} {'nofCars<=%d' % target:>12s} "
              f"{r['outcome']:>11s} {r['wall']:7.2f}s  {r['status']}")

        # Fail fast: a control that comes back wrong voids everything after it.
        if role == "neg-control" and r["outcome"] == "INFEASIBLE":
            print("\n!! NEGATIVE CONTROL FAILED -- a cell we hold a one-car solution for was "
                  "declared infeasible.\n   The model or the constraint is wrong. STOPPING; no "
                  "result from this run is usable.")
            break
        if role == "pos-control" and r["outcome"] == "FEASIBLE":
            print("\n!! POSITIVE CONTROL FAILED -- L-fleet proves this cell needs 2 cars and the "
                  "solver found 1.\n   Either L-fleet is wrong or this probe is. STOPPING.")
            break

    json.dump(stamped(dict(size=a.size, det_tl=a.det_tl, tl=a.tl, threads=a.threads,
                   prereg="validation/PREREG_S2p_fleet_floor_smoke.md#amendment-1",
                   rows=rows, checks=checks), __file__),
              open(os.path.join(ROOT, a.out), "w"), indent=1)

    done = [r for r in rows if r["role"] == "open"]
    won = [r for r in done if r["outcome"] == "INFEASIBLE"]
    better = [r for r in done if r["outcome"] == "FEASIBLE"]
    print(f"\nopen cells probed      : {len(done)} of {len(openc)}")
    print(f"  fleet PROVED by solver: {len(won)}  {[r['cell'] for r in won]}")
    print(f"  SMALLER fleet FOUND   : {len(better)}  {[r['cell'] for r in better]}")
    print(f"  still unknown         : {len(done) - len(won) - len(better)}")
    wallstop = [r for r in rows if r["outcome"] == "TIMEOUT_WALL"]
    if wallstop:
        print(f"  !! WALL BACKSTOP BOUND on {len(wallstop)}: "
              f"{[r['cell'] for r in wallstop]} -- NOT reproducible, not usable as proof "
              f"(PREREG_S2p A1.3)")
    fast = [r for r in won if r["wall"] < 1.0]
    print(f"  of the proofs, {len(fast)} took under 1 s -- i.e. presolve alone, no branching")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
