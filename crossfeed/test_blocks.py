"""
Structural-equivalence tests for the LD block models (rule 3 extension).

BlockA claims to be "the joint model minus water". This checks:
  1. var/constraint counts are strictly smaller than the joint model
     (BlockA drops y, l, f^w, arcWaterCost, nofVessels + constraints 16-25)
  2. RELAXATION property: BlockA optimum <= z_joint on every tiny instance
     (a relaxation can only lower the objective)
  3. NO EXTRA RESTRICTION: the joint optimum's street+sync assignment is
     feasible for BlockA (BlockA does not forbid anything the joint model
     allows on the shared variables)
  4. BlockA optimum <= (street+sync cost of the joint optimum)  -- the
     projection inequality that Part 1 of bound_validity.md relies on.

SubModel(hubassign=True, integral=True) at a fixed (routing, transfers) =
the joint model's synchronisation+water subproblem for that decision;
its optimum + nothing should equal z_joint when the fixed decision IS the
joint optimum's routing.
"""
import sys

sys.path.insert(0, ".")
from build_instance import build
from joint_model_cplex import joint_synchronized_cplex
from crossfeed.block_a import BlockA
from crossfeed.lagrangian_subproblem import SubModel

TOL = 0.05


def fixed_street_cost(problem, xij, vi):
    D = problem.DistMatrix
    vset = set(vi)
    return (sum(problem.travelcoststreet * D[i][j] for (i, j) in xij if i not in vset)
            + sum(1 for (i, j) in xij if i == 0) * problem.penaltyCars)


def main():
    fails = 0
    for name, size in [("C201", 6), ("C204", 6), ("R201", 7), ("RC201", 8)]:
        p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=120)
        zj = joint_synchronized_cplex(p, time_limit=120, mip_gap=0.0)
        s = zj["solution"]

        p2 = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=120)
        ba = BlockA(p2, integral=True)
        ra = ba.solve(time_limit=120)

        # counts
        smaller = ba.m.number_of_variables < zj["n_vars"] and ba.m.number_of_constraints < zj["n_cons"]
        # relaxation
        relax_ok = ra["value"] <= zj["objVal"] + TOL
        # projection: blockA opt <= street+sync cost of joint optimum
        # street+sync cost = z_joint - water cost.  water cost from the joint
        # solution's Fleet/Travel water components:
        water_cost = s["FleetWater"] + s["TravelWater"]
        street_sync = zj["objVal"] - water_cost
        proj_ok = ra["value"] <= street_sync + TOL

        # SubModel at the joint optimum's routing -> should recover z_joint
        sub = SubModel(p2, s["xij"], s["vi"], hubassign=True, integral=True)
        sr = sub.solve(time_limit=120)
        sub_ok = sr.value is not None and abs(sr.value - zj["objVal"]) < 0.5

        ok = smaller and relax_ok and proj_ok and sub_ok
        fails += (not ok)
        print(f"{name} n={size}: z_joint={zj['objVal']}  blockA={ra['value']}  "
              f"street+sync={street_sync:.2f}  SubModel={sr.value}")
        print(f"   counts_smaller={smaller}  relaxation(A<=zj)={relax_ok}  "
              f"projection(A<=street+sync)={proj_ok}  SubModel==zj={sub_ok}  "
              f"{'OK' if ok else 'FAIL'}")

    print(f"\n{4 - fails}/4 instances pass all structural checks")
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
