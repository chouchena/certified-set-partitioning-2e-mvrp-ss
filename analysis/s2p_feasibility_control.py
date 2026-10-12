import sys, os, time, json
R=r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir"
sys.path.insert(0,R); sys.path.insert(0,os.path.join(R,"analysis"))
from build_instance import build
from joint_model_cplex import build_joint_model
# FEASIBILITY-ONLY: drop the cost objective, ask only "does a 1-car solution exist?"
# Control: RC208 at nofCars<=1, where 693.868 is a VERIFIED one-car solution.
pr=build("RC208",20); H=build_joint_model(pr); m=H.m
m.add_constraint(H.nofCars <= 1, ctname="fleet_drop")
m.minimize(0)                      # pure feasibility
p=m.parameters; p.timelimit=420; p.threads=4
p.emphasis.mip.set(1)              # emphasise FEASIBILITY over optimality
t0=time.time(); sol=m.solve(log_output=False); d=m.solve_details
print(f"feasibility-only RC208 nofCars<=1: status={d.status} wall={time.time()-t0:.0f}s "
      f"found={'YES' if sol is not None else 'no'}")
if sol is not None:
    print(f"  a 1-car solution EXISTS and was found; true cost = "
          f"{sol.get_value(H.FleetStreet)+sol.get_value(H.TravelStreet)+sol.get_value(H.FleetWater)+sol.get_value(H.TravelWater):.2f}")
