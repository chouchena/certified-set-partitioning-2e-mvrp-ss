"""Decompose the joint model's LP relaxation into its four cost components.

HYPOTHESIS under test: the LP is weak not uniformly, but because the WATER
travel cost collapses to ~0. Const23/24 have the form

    arcWaterCost[i,j] >= d[p][r] * (y[i,j] + vip[i,p] + vip[j,r] - 2)

which is a big-M linearisation of a TRILINEAR product. At fractional values
(y=vip=vip=0.5) the RHS is -0.5 -> the constraint is VACUOUS, so the LP can
drive every water arc cost to zero. The only thing holding TravelWater up is
the single valid inequality TravelWater >= c_w * minTr * lowerVessels.

If confirmed, the LP's weakness has a precise, nameable cause -- and it tells
us exactly which part a reformulation must replace.
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.stamp import stamped

from docplex.mp.relax_linear import LinearRelaxer
from build_instance import build
from joint_model_cplex import build_joint_model


def anatomy(cell, size, tl=300):
    problem = build(cell, size, tau="formula")   # MUST match InstanceSpec; build() defaults to tau="code" (TD=0)
    H = build_joint_model(problem)
    m = H.m
    lp = LinearRelaxer().linear_relaxation(m)
    lp.parameters.timelimit = tl
    sol = lp.solve(log_output=False)
    if sol is None:
        return None
    g = lambda nm: sol.get_value(lp.get_var_by_name(nm))
    fs, ts = g("FleetStreet"), g("TravelStreet")
    fw, tw = g("FleetWater"), g("TravelWater")
    # the floor that the single valid inequality imposes on TravelWater
    minTr = min(problem.DistMatrix[problem.CDC][s] for s in problem.satellites)
    import math
    sumD = sum(problem.nodes[i].demand for i in problem.customers)
    lowerV = math.ceil(sumD / problem.VesselCapacity)
    floor_tw = problem.travelcostwater * minTr * lowerV
    return dict(cell=cell, size=size, lp=sol.objective_value,
                FleetStreet=fs, TravelStreet=ts,
                FleetWater=fw, TravelWater=tw,
                TravelWater_floor=floor_tw,
                nofCars=g("nofCars"), nofVessels=g("nofVessels"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C202,C203,R204,RC202")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/lp_anatomy.json")
    a = ap.parse_args()

    rows = []
    print(f"{'cell':8s} {'LP':>9s} {'FleetSt':>9s} {'TravSt':>9s} "
          f"{'FleetWat':>9s} {'TravWat':>9s} {'TWfloor':>9s}  TW at floor?")
    for c in a.cells.split(","):
        r = anatomy(c.strip(), a.size)
        if r is None:
            print(f"{c:8s}  LP FAILED"); continue
        rows.append(r)
        atfloor = abs(r["TravelWater"] - r["TravelWater_floor"]) < 1e-4
        print(f"{r['cell']:8s} {r['lp']:9.1f} {r['FleetStreet']:9.1f} "
              f"{r['TravelStreet']:9.1f} {r['FleetWater']:9.1f} "
              f"{r['TravelWater']:9.1f} {r['TravelWater_floor']:9.1f}  "
              f"{'YES -- vacuous' if atfloor else 'no'}")
    if rows:
        os.makedirs("runs", exist_ok=True)
        json.dump(stamped(rows, __file__), open(a.out, "w"), indent=1)
        print("\nwrote", a.out)
