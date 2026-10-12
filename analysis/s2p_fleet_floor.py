"""S2p — fleet-count reduction at |C| = 20, per validation/PREREG_S2p_fleet_floor_smoke.md.

Adds `nofCars <= (incumbent nCars) - 1` to K's joint MILP and solves cold.

Three outcomes, and the third must never be confused with the second:
  IMPROVED    a better incumbent exists at a smaller fleet      -> primal result
  INFEASIBLE  PROVED no solution at that fleet size             -> valid fleet floor, dual result
  TIMEOUT     unknown                                           -> reported as unknown, never as a floor

Stage 0 is a POSITIVE CONTROL on RC208, where a one-car solution (693.868) is
verified to exist. If the control does not recover it, the method is broken and
nothing else runs.
"""
import sys, os, json, argparse, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis.stamp import stamped

from build_instance import build                       # noqa: E402
from joint_model_cplex import build_joint_model        # noqa: E402
from lp_component_anatomy import harvest               # noqa: E402


def drop_fleet(cell, size, cur_cars, tl, threads, target=None):
    """Solve K's joint model with nofCars <= cur_cars-1. Cold start (the incumbent
    is infeasible for this model by construction, so it cannot seed it)."""
    problem = build(cell, size, tau="formula")   # MUST match InstanceSpec; build() defaults to tau="code" (TD=0)
    H = build_joint_model(problem)
    m = H.m
    target = cur_cars - 1 if target is None else target
    m.add_constraint(H.nofCars <= target, ctname="fleet_drop")
    p = m.parameters
    p.timelimit = tl
    p.threads = threads
    p.mip.tolerances.mipgap = 0.0
    t0 = time.time()
    sol = m.solve(log_output=False)
    d = m.solve_details
    wall = time.time() - t0
    st = (d.status or "").lower()
    if sol is not None:
        return dict(outcome="IMPROVED", obj=sol.objective_value,
                    cars=target, status=d.status, wall=wall, bound=d.best_bound)
    if "infeasible" in st:
        return dict(outcome="INFEASIBLE", obj=None, cars=target,
                    status=d.status, wall=wall, bound=None)
    return dict(outcome="TIMEOUT", obj=None, cars=target,
                status=d.status, wall=wall, bound=d.best_bound)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--tl", type=float, default=300)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--target", type=int, default=None,
                    help="force this fleet ceiling instead of (incumbent nCars - 1). "
                         "Needed for the RC208 control, whose BEST incumbent is already 1-car: "
                         "the control asks whether a cold solve at nofCars<=1 RECOVERS 693.868.")
    ap.add_argument("--control", action="store_true",
                    help="Stage 0: RC208 must recover <= 693.868 or the method is broken")
    ap.add_argument("--out", default="runs/s2p_fleet_floor.json")
    a = ap.parse_args()

    cells = [c.strip() for c in a.cells.split(",")]
    best = harvest(set(cells), a.size)
    rows = []
    print(f"{'cell':7s} {'from':>5s} {'to':>4s} {'incumbent':>10s} {'outcome':>11s} "
          f"{'new obj':>10s} {'delta%':>8s} {'wall':>7s}")
    for c in cells:
        if c not in best:
            print(f"{c:7s}  NO STORED INCUMBENT -- skipped"); continue
        inc = best[c]
        nc = inc.get("nCars")
        if a.target is None and (not nc or nc < 2):
            print(f"{c:7s}  nCars={nc} -- nothing to drop, skipped"); continue
        r = drop_fleet(c, a.size, nc or 0, a.tl, a.threads, target=a.target)
        r.update(cell=c, from_cars=nc, incumbent=inc["objVal"])
        rows.append(r)
        dl = ("%+.2f%%" % ((r["obj"] - inc["objVal"]) / inc["objVal"] * 100)) if r["obj"] else "--"
        ob = ("%10.2f" % r["obj"]) if r["obj"] else " " * 10
        print(f"{c:7s} {(nc or 0):5d} {r['cars']:4d} {inc['objVal']:10.2f} {r['outcome']:>11s} "
              f"{ob} {dl:>8s} {r['wall']:6.0f}s")

    if a.control:
        ok = [r for r in rows if r["cell"] == "RC208"]
        if not ok:
            print("\nCONTROL DID NOT RUN"); sys.exit(2)
        r = ok[0]
        if r["outcome"] == "INFEASIBLE":
            print("\nCONTROL FAILED: INFEASIBLE, yet 693.868 is a VERIFIED one-car solution.")
            print("HARD STOP -- the model build or the verifier is wrong.")
            sys.exit(2)
        if r["outcome"] == "TIMEOUT":
            print(f"\nCONTROL TIMED OUT at {a.tl}s -- raise the limit once, else Stage 1 is not worth running.")
            sys.exit(3)
        if r["obj"] <= 693.868 + 0.05:
            print(f"\nCONTROL PASSED: recovered {r['obj']:.3f} <= 693.868. Method works.")
        else:
            print(f"\nCONTROL WEAK: found {r['obj']:.3f} > 693.868 known. Solver reached a worse "
                  f"one-car solution; method works but is not finding the best.")
    os.makedirs("runs", exist_ok=True)
    json.dump(stamped(rows, __file__), open(a.out, "w"), indent=1)
    print("\nwrote", a.out)
