"""The true shape of the objective as a function of the FLEET (d443).

Author, 2026-09-25: "we never proved OV is monotone over cars", and "my deep feeling is that we
didn't exhaust the real relationship between cars/fleet, OV, slacks, street vs water sides".

Nothing in this project has ever measured that relationship directly. This does, exactly, at n10,
by solving the predecessors' joint model to proven optimality with the fleet FIXED at k, for every
k from one upward, and splitting the result into its components:

    z*(k)  =  penalty * k   +   street travel*(k)   +   water*(k)

The fleet term rises linearly by construction. The question is what the other two do. If street
travel falls with k, the objective is a sum of an increasing and a decreasing term and its optimum
is INTERIOR -- not at the smallest feasible fleet -- and "monotone over cars" is false in the only
sense that would have mattered.

We disclaim the use of the predecessors' formulation: `joint_model_cplex` is our transcription of
their joint model.

    python analysis/tep_ov_vs_cars.py --cells R201,R204,RC201,C204 --kmax 4
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped


def solve_at(cell, size, k, tl, threads):
    """Proven optimum with the fleet fixed at exactly k cars, split into its components."""
    from solver.config import InstanceSpec
    from solver.problem import SolverProblem
    from joint_model_cplex import build_joint_model, _extract_solution
    prob = SolverProblem(InstanceSpec(cell, size))
    h = build_joint_model(prob.raw)
    m = h.m
    m.add_constraint(h.nofCars == k, ctname="fix_fleet")
    m.parameters.timelimit = tl
    m.parameters.mip.tolerances.mipgap = 0.0
    m.parameters.threads = threads
    t0 = time.time()
    sol = m.solve(log_output=False)
    wall = time.time() - t0
    sd = m.solve_details
    if sol is None:
        return dict(k=k, obj=None, status=str(sd.status if sd else "none"), wall=round(wall, 1), closed=False)
    o = _extract_solution(h)
    gap = getattr(sd, "mip_relative_gap", None)
    obj = float(sol.objective_value)
    fleet = float(o.get("FleetStreet", 0)); travel = float(o.get("TravelStreet", 0))
    return dict(k=k, obj=obj, fleet=fleet, street=travel, water=obj - fleet - travel,
                wall=round(wall, 1), closed=bool(gap is not None and gap <= 1e-6),
                status=str(sd.status if sd else "none"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="R201,R204,RC201,C204"); ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--kmax", type=int, default=4); ap.add_argument("--tl", type=float, default=600.0)
    ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args()
    out = {}
    for cell in a.cells.split(","):
        print("\n=== %s n%d ===" % (cell, a.size), flush=True)
        print("  %3s %11s %10s %11s %10s %9s %s" % ("k", "z*(k)", "fleet", "street", "water", "vs k=1", "status"))
        rows = []
        base = None
        for k in range(1, a.kmax + 1):
            r = solve_at(cell, a.size, k, a.tl, a.threads)
            rows.append(r)
            if r["obj"] is None:
                print("  %3d %11s %10s %11s %10s %9s %s" % (k, "-", "-", "-", "-", "-", r["status"])); continue
            if base is None:
                base = r["obj"]
            print("  %3d %11.3f %10.2f %11.2f %10.2f %+8.2f%% %s"
                  % (k, r["obj"], r["fleet"], r["street"], r["water"], 100.0 * (r["obj"] / base - 1),
                     "proven" if r["closed"] else r["status"]), flush=True)
        ok = [r for r in rows if r["obj"] is not None]
        if len(ok) >= 2:
            best = min(ok, key=lambda r: r["obj"])
            st = [r["street"] for r in ok]
            falling = all(st[i + 1] <= st[i] + 1e-6 for i in range(len(st) - 1))
            print("  optimum at k = %d ; street travel %s with k ; water %s"
                  % (best["k"], "FALLS monotonically" if falling else "is NOT monotone",
                     "%.2f -> %.2f" % (ok[0]["water"], ok[-1]["water"])))
            print("  marginal street saving per extra car: %s   (penalty per car %.2f)"
                  % (", ".join("%.1f" % (st[i] - st[i + 1]) for i in range(len(st) - 1)),
                     ok[0]["fleet"]))
        out[cell] = rows
    p = os.path.join(ROOT, "runs", "oracle", "tep_ov_vs_cars_n%d.json" % a.size)
    json.dump(stamped(dict(size=a.size, cells=out)), io.open(p, "w", encoding="utf-8"), indent=1)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
