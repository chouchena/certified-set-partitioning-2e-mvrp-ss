"""
CPLEX (docplex) port of integratedJointModel.JointSynchronized — the joint
/ compact MILP for the 2E-MVRP-SS.

Purpose:
  1. Phase 2 needs a runnable joint model (Gurobi is not installed).
  2. Rule 12 reproduction gate: reproduce Table 3 |C|=10 best-known values
     to lock the ground-truth config (tau = 0 vs 180; proximity).
  3. Rule 3 port-equivalence: variable / constraint counts are reported so
     they can be checked against the original.
  4. Phase 3b primal: `build_joint_model` exposes the model + variable
     handles so the fix-and-optimize matheuristic (solver/engines/fixopt.py)
     can add temporary fixings and MIP starts without touching the solve
     path used for reproduction.

Line-by-line translation of integratedJointModel.py (Gurobi) lines 13-308.
The Gurobi model is a PLAIN MILP (its LazyConstraints flag is set but the
callback only records incumbent timing — no cuts). So this is a straight
MILP solve, not a decomposition.

Requires: docplex + full local CPLEX (not the size-capped Community wheel).

ATTRIBUTION AND DERIVATIVE STATUS (declared 2026-09-13).
This module is a CPLEX/docplex implementation of the joint MILP published by
Karademir, C., Beirigo, B.A., Atasoy, B. (2025), "A two-echelon multi-trip vehicle routing
problem with synchronization for an integrated water- and land-based transportation system",
European Journal of Operational Research 322(2) 480-499, doi:10.1016/j.ejor.2024.10.047.

It implements the formulation published in that paper. It was written WITH REFERENCE TO the
authors' Gurobi source `integratedJointModel.py` (github.com/cigdemkarademir/2echelon-
synchronization, commit ebec1b5cd075) and is therefore declared a DERIVATIVE WORK of that
file rather than an independent clean-room reimplementation. That declaration is made openly
because it is the honest description, not because the distinction is disputed.

Their repository declares no licence. Nothing of theirs is redistributed here; see
fetch_karademir.py and third_party_manifest.json. Equivalence to the original is recorded in
validation/port_equivalence.md (15/15 cells match to <0.02).
"""
import math
import time
from dataclasses import dataclass, field
from docplex.mp.model import Model


@dataclass
class JointHandles:
    """Every variable/expression handle a caller needs to add fixings,
    MIP starts, or read a solution back. Field names mirror the model."""
    m: Model
    Customers: list
    Satellites: list
    CDC: int
    setCw: list
    arcList: list
    nofCars: object
    nofVessels: object
    vi: dict
    hi: dict
    mi: dict
    ui: dict
    vip: dict
    xij: dict
    arcStreetCost: dict
    li: dict
    fij: dict
    y: dict
    arcWaterCost: dict
    FleetStreet: object
    TravelStreet: object
    FleetWater: object
    TravelWater: object
    zObj: object
    lowerVessels: int
    n_vars: int = 0
    n_cons: int = 0


def build_joint_model(problem) -> JointHandles:
    """Build the joint MILP exactly as `joint_synchronized_cplex` does and
    return the model + handles WITHOUT solving. The two share this builder
    so anything reproduced through the solve path is reproduced here too."""
    Customers = list(problem.customers)
    Satellites = list(problem.satellites)
    CDC = problem.CDC
    D = problem.DistMatrix
    nd = problem.nodes
    TD = problem.TransferDuration
    SetCd = [0] + Customers
    setCw = [CDC] + Customers

    # d242, OPTIONAL and defaulting to FALSE so the faithful arm is byte-identical:
    # the semantic reading of (14) and (22), whose big-Ms K derive from the
    # CUSTOMER's time window although both rows involve u, which lives in the CDC
    # window. Undersized by 13.4x on the arbiter's witness.
    validBigM = bool(getattr(problem, "validBigM", False))
    m = Model(name="2EMVRPTWSS_joint")

    # ---------------- STREET VARIABLES ----------------
    nofCars = m.integer_var(lb=0, ub=len(Customers), name="nofCars")
    vi, hi, mi = {}, {}, {}
    for i in Customers:
        vi[i] = m.binary_var(name=f"v.{i}")
        hi[i] = m.continuous_var(lb=nd[i].earliest, ub=nd[i].latest, name=f"h[{i}]")
        mi[i] = m.continuous_var(lb=nd[i].demand, ub=problem.CarCapacity, name=f"m[{i}]")
    hi[0] = m.continuous_var(lb=nd[0].earliest, ub=nd[0].latest, name="h[0]")

    xij, arcStreetCost = {}, {}
    arcList = []
    for i in SetCd:
        for j in SetCd:
            if i == j:
                continue
            if nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest:
                xij[i, j] = m.binary_var(name=f"x.{i}.{j}")
                arcStreetCost[i, j] = m.continuous_var(lb=0, ub=m.infinity,
                                                       name=f"arcCostS[{i}.{j}]")
                arcList.append([i, j])
    arcset = set((i, j) for i, j in arcList)

    # ---------------- STREET CONSTRAINTS ----------------
    for i in Customers:
        m.add_constraint(m.sum(xij[i, j] for j in SetCd if (i, j) in arcset) == 1, f"outflow.{i}")
        m.add_constraint(m.sum(xij[j, i] for j in SetCd if (j, i) in arcset) == 1, f"inflow.{i}")

    m.add_constraint(m.sum(xij[i, 0] for i in Customers if (i, 0) in arcset) == nofCars)
    m.add_constraint(m.sum((xij[i, 0] if (i, 0) in arcset else 0)
                           - (xij[0, i] if (0, i) in arcset else 0)
                           for i in Customers) == 0)

    for i in Customers:
        if (i, 0) in arcset:
            m.add_constraint(vi[i] >= xij[i, 0])                       # Const4

    for i in Customers:                                               # Const5
        for j in Customers:
            if (i, j) in arcset:
                m.add_constraint(
                    mi[j] - mi[i] >= nd[j].demand - problem.CarCapacity * (1 - xij[i, j] + vi[i]))

    for i in Customers:                                               # Const7
        m.add_constraint(float(nd[0].earliest + D[0][i]) <= hi[i])
        m.add_constraint(float(nd[0].latest - D[i][0] - nd[i].serviceTime - TD) >= hi[i])

    for i in Customers:                                               # Const8
        for j in SetCd:
            if (i, j) in arcset:
                maxTravel = max(D[i][p] + D[p][j] for p in Satellites)
                Mij = nd[i].latest + nd[i].serviceTime + TD + maxTravel - nd[j].earliest
                if validBigM:
                    # (14)'s LHS carries u_i, whose domain is the CDC window -- NOT customer i's
                    # window. K's constant is derived from nd[i].latest, so with l_CDC >> l_i it
                    # is UNDERSIZED and the row stays active at x_ij = 0, excluding feasible
                    # routings. d242: a big-M is an encoding device, and an undersized one
                    # encodes a different model than the article states.
                    Mij = nd[CDC].latest + TD + max(D[p][j] for p in Satellites) - nd[j].earliest
                m.add_constraint(
                    hi[i] + nd[i].serviceTime + TD * vi[i] + arcStreetCost[i, j]
                    <= hi[j] + Mij - Mij * xij[i, j])

    for (i, j) in arcList:                                            # Const9
        m.add_constraint(arcStreetCost[i, j] >= D[i][j] * xij[i, j])
        if i in Customers:
            minTravel = min(D[i][p] + D[p][j] - D[i][j] for p in Satellites)
            m.add_constraint(
                arcStreetCost[i, j] >= D[i][j] * xij[i, j] + minTravel * (xij[i, j] + vi[i] - 1))

    # ---------------- SYNCHRONIZATION ----------------
    ui, vip = {}, {}
    for i in Customers:
        ui[i] = m.continuous_var(lb=nd[CDC].earliest, ub=nd[CDC].latest, name=f"u[{i}]")
        for p in Satellites:
            vip[i, p] = m.binary_var(name=f"vip.{i}.{p}")

    for i in Customers:                                               # Const12
        m.add_constraint(m.sum(vip[i, p] for p in Satellites) == vi[i])

    for i in Customers:
        m.add_constraint(ui[i] >= hi[i] + nd[i].serviceTime
                         + m.sum(D[i][p] * vip[i, p] for p in Satellites))          # Const13
        m.add_constraint(nd[CDC].earliest + m.sum(D[CDC][p] * vip[i, p] for p in Satellites)
                         <= ui[i])                                                  # Const15
        m.add_constraint(nd[CDC].latest >= ui[i]
                         + m.sum((TD + D[p][CDC]) * vip[i, p] for p in Satellites))  # Const15
        for j in SetCd:
            if (i, j) in arcset:
                m.add_constraint(
                    m.sum((D[i][p] + D[p][j]) * (xij[i, j] + vip[i, p] - 1) for p in Satellites)
                    <= arcStreetCost[i, j])
                maxTravel = max(D[i][p] + D[p][j] for p in Satellites)
                Mij = nd[i].latest + nd[i].serviceTime + TD + maxTravel - nd[j].earliest
                m.add_constraint(
                    ui[i] + m.sum((TD + D[p][j]) * vip[i, p] for p in Satellites)
                    <= hi[j] + Mij - Mij * xij[i, j])                               # Const14

    # ---------------- WATER LEVEL ----------------
    nofVessels = m.integer_var(lb=0, ub=len(Customers), name="nofVessels")
    z = {}
    if problem.stationaryBarges:
        for p in Satellites:
            z[p] = m.binary_var(name=f"z[{p}]")

    li, fij = {}, {}
    for i in Customers:
        li[i] = m.continuous_var(lb=nd[i].demand, ub=problem.VesselCapacity, name=f"l[{i}]")
        for j in Customers:
            if i != j:
                fij[i, j] = m.continuous_var(lb=0, ub=nd[CDC].latest, name=f"fij[{i},{j}]")

    y, arcWaterCost = {}, {}
    for i in setCw:
        for j in setCw:
            if i != j:
                y[i, j] = m.binary_var(name=f"Y[{i},{j}]")
                arcWaterCost[i, j] = m.continuous_var(lb=0, ub=m.infinity, name=f"arcCostW[{i}.{j}]")

    for i in Customers:                                               # Const18
        m.add_constraint(m.sum(y[i, j] for j in setCw if i != j) == vi[i])
        m.add_constraint(m.sum(y[j, i] for j in setCw if i != j) == vi[i])

    m.add_constraint(m.sum(y[i, CDC] - y[CDC, i] for i in Customers) == 0)          # Const19

    for i in Customers:                                               # Const20/21
        m.add_constraint(li[i] >= mi[i])
        for j in Customers:
            if i != j:
                m.add_constraint(li[j] - li[i] >= mi[j] - problem.VesselCapacity * (1 - y[i, j]))

    sumDemand = sum(nd[i].demand for i in Customers)
    lowerVessels = math.ceil(sumDemand / problem.VesselCapacity)
    m.add_constraint(m.sum(y[i, CDC] for i in Customers) == nofVessels)
    m.add_constraint(nofVessels >= lowerVessels)

    for i in Customers:                                               # Const22
        for j in Customers:
            if i != j:
                MijWater = (nd[i].latest + nd[i].serviceTime + max(D[i][p] for p in Satellites) + TD
                            + max(D[p][r] for p in Satellites for r in Satellites)
                            - (nd[j].earliest + nd[j].serviceTime + min(D[j][p] for p in Satellites)))
                if validBigM:
                    # Same root cause: the constant bounds u_j below by e_j + s_j + min_p D_jp,
                    # which holds only where customer j TRANSFERS. With v_j = 0, u_j is free over
                    # the whole CDC window. Valid constant: the u-span, plus tau, plus the largest
                    # hub-to-hub leg (f^w at any optimum never exceeds it).
                    MijWater = ((nd[CDC].latest - nd[CDC].earliest) + TD
                                + max(D[p][r] for p in Satellites for r in Satellites))
                m.add_constraint(
                    ui[i] + TD + arcWaterCost[i, j] <= ui[j] + MijWater - MijWater * y[i, j])

    for i in Customers:                                               # Const23/24
        m.add_constraint(arcWaterCost[CDC, i] >=
                         m.sum(D[CDC][p] * (y[CDC, i] + vip[i, p] - 1) for p in Satellites))
        m.add_constraint(arcWaterCost[i, CDC] >=
                         m.sum(D[p][CDC] * (y[i, CDC] + vip[i, p] - 1) for p in Satellites))
        for p in Satellites:
            for j in Customers:
                if i != j:
                    for r in Satellites:
                        if p != r:
                            m.add_constraint(
                                arcWaterCost[i, j] >=
                                D[p][r] * (y[i, j] + vip[i, p] + vip[j, r] - 2))

    if problem.singleTransfer:
        for i in Customers:
            for j in Customers:
                if i < j:
                    m.add_constraint(ui[i] - ui[j] <= fij[i, j])
                    m.add_constraint(ui[j] - ui[i] <= fij[i, j])
                    m.add_constraint(fij[j, i] == fij[i, j])
                    for p in Satellites:
                        m.add_constraint(fij[i, j] >= TD * (vip[i, p] + vip[j, p] - 1))

    if getattr(problem, "hardSingleTransfer", False):
        # CORRECTED constraint (26): two transfers at the SAME satellite must be >= TD apart.
        # K's published fij encoding above is VACUOUS -- fij is uncosted and only bounded below,
        # so it never binds -- and this replaces it with an enforced separation.
        #
        # INDICATOR CONSTRAINTS, NOT BIG-M. 2026-09-21. The big-M form previously used here
        #
        #     gate = Mbig * (2 - vip[i,p] - vip[j,p])
        #     u[j] >= u[i] + TD - Mbig*(1 - o[i,j]) - gate
        #
        # is mathematically correct for exactly integral binaries and WRONG in practice, because
        # a MIP solver accepts a binary as integral within EpInt (CPLEX default 1e-5) and Mbig
        # then multiplies that slack straight into the constraint. Captured on R202/n100 seed 0,
        # reproducibly: o sitting at 1 - 1.1e-8 with Mbig = 1187 produced |u3 - u34| = 19.999987,
        # a real 1.3049e-5 violation of a 20-unit separation, which verifier3 rejected. The run
        # discarded the candidate, so nothing invalid was ever banked -- but the model was not
        # enforcing the constraint we claim over K, and it burned budget generating and
        # verifying solutions it then threw away.
        #
        # Confirmed by varying ONLY the tolerance, model byte-identical: the violation
        # reproduces at EpInt 1e-5 and disappears at 1e-9 and 0. Tightening Mbig was measured
        # and is NOT sufficient -- customer time windows take it only from 1187 to 1000, leaving
        # the worst-case amplification at 1e-2, four orders above verifier3's threshold.
        #
        # An indicator constraint is enforced by the solver's branching, not by a coefficient.
        # There is no M, so there is nothing for EpInt to be multiplied by, and the separation
        # is exactly TD rather than TD minus an epsilon we would have to explain to a referee.
        #
        # sep[i,j] : i and j transfer at the SAME satellite
        # a1/a0    : that, AND the chosen ordering. Indicators take one binary, so the
        #            conjunction is materialised rather than nested.
        sep, a1, a0 = {}, {}, {}
        for i in Customers:
            for j in Customers:
                if i >= j:
                    continue
                sep[i, j] = m.binary_var(name=f"sep.{i}.{j}")
                # sep is FORCED ON when both sit at the same p. It is left free to be 1
                # otherwise, which only ever adds separation -- never removes it.
                for p in Satellites:
                    m.add_constraint(sep[i, j] >= vip[i, p] + vip[j, p] - 1)
                o = m.binary_var(name=f"o.{i}.{j}")          # 1 => i precedes j
                a1[i, j] = m.binary_var(name=f"a1.{i}.{j}")
                a0[i, j] = m.binary_var(name=f"a0.{i}.{j}")
                m.add_constraint(a1[i, j] <= sep[i, j])
                m.add_constraint(a1[i, j] <= o)
                m.add_constraint(a0[i, j] <= sep[i, j])
                m.add_constraint(a0[i, j] <= 1 - o)
                # when they share a satellite, exactly one ordering must be active
                m.add_constraint(a1[i, j] + a0[i, j] >= sep[i, j])
                m.add_indicator(a1[i, j], ui[j] >= ui[i] + TD, active_value=1)
                m.add_indicator(a0[i, j], ui[i] >= ui[j] + TD, active_value=1)

    # ---------------- OBJECTIVE ----------------
    FleetStreet = m.continuous_var(lb=0, ub=m.infinity, name="FleetStreet")
    TravelStreet = m.continuous_var(lb=0, ub=m.infinity, name="TravelStreet")
    FleetWater = m.continuous_var(lb=0, ub=m.infinity, name="FleetWater")
    TravelWater = m.continuous_var(lb=0, ub=m.infinity, name="TravelWater")

    m.add_constraint(nofVessels * problem.penaltyVessels == FleetWater)
    m.add_constraint(nofCars * problem.penaltyCars == FleetStreet)
    m.add_constraint(m.sum(problem.travelcoststreet * arcStreetCost[i, j] for (i, j) in arcList)
                     == TravelStreet)
    m.add_constraint(m.sum(problem.travelcostwater * arcWaterCost[i, j]
                           for i in setCw for j in setCw if i != j) == TravelWater)

    minTr = min(D[CDC][s] for s in Satellites)
    m.add_constraint(TravelWater >= problem.travelcostwater * minTr * lowerVessels)

    if problem.stationaryBarges:
        nofBarges = math.ceil(sumDemand / problem.VesselCapacity)
        m.add_constraint(FleetWater == problem.penaltyVessels * nofBarges)
        m.add_constraint(m.sum(z[p] for p in Satellites) <= nofBarges)
        for i in Customers:
            for p in Satellites:
                m.add_constraint(vip[i, p] <= z[p])
        for i in setCw:
            for j in setCw:
                if i != j and i != CDC and j != CDC:
                    m.add_constraint(arcWaterCost[i, j] == 0)

    zObj = m.continuous_var(lb=0, ub=m.infinity, name="zObj")
    m.add_constraint(FleetStreet + FleetWater + TravelStreet + TravelWater <= zObj)
    m.minimize(zObj)

    H = JointHandles(
        m=m, Customers=Customers, Satellites=Satellites, CDC=CDC, setCw=setCw,
        arcList=arcList, nofCars=nofCars, nofVessels=nofVessels,
        vi=vi, hi=hi, mi=mi, ui=ui, vip=vip, xij=xij, arcStreetCost=arcStreetCost,
        li=li, fij=fij, y=y, arcWaterCost=arcWaterCost,
        FleetStreet=FleetStreet, TravelStreet=TravelStreet,
        FleetWater=FleetWater, TravelWater=TravelWater, zObj=zObj,
        lowerVessels=lowerVessels,
        n_vars=m.number_of_variables, n_cons=m.number_of_constraints)
    return H


def _extract_solution(H) -> dict:
    """Read the current solution off the handles (model must be solved)."""
    m, Customers, Satellites = H.m, H.Customers, H.Satellites
    setCw, CDC = H.setCw, H.CDC
    used_arcs = [[i, j] for (i, j) in H.arcList if H.xij[i, j].solution_value > 0.5]
    transfers, hubs = [], []
    for i in Customers:
        if H.vi[i].solution_value > 0.5:
            transfers.append(i)
            for p in Satellites:
                if H.vip[i, p].solution_value > 0.5:
                    hubs.append(p)
                    break
    water_arcs = [[i, j] for i in setCw for j in setCw
                  if i != j and H.y[i, j].solution_value > 0.5]
    return {
        "xij": used_arcs,
        "vi": transfers,
        "hubs": hubs,
        "yij": water_arcs,
        "nCars": int(round(H.nofCars.solution_value)),
        "nVessel": int(round(H.nofVessels.solution_value)),
        "FleetStreet": H.FleetStreet.solution_value,
        "TravelStreet": H.TravelStreet.solution_value,
        "FleetWater": H.FleetWater.solution_value,
        "TravelWater": H.TravelWater.solution_value,
        "hi": {i: H.hi[i].solution_value for i in [0] + Customers},
        "ui": {i: H.ui[i].solution_value for i in Customers
               if H.vi[i].solution_value > 0.5},
    }


def joint_synchronized_cplex(problem, time_limit=600, mip_gap=0.0,
                             threads=None, log_output=False, lp_relax=False):
    H = build_joint_model(problem)
    m = H.m
    n_vars, n_cons = H.n_vars, H.n_cons
    lowerVessels = H.lowerVessels

    if lp_relax:
        from docplex.mp.relax_linear import LinearRelaxer
        rel = LinearRelaxer.make_relaxed_model(m)
        rel.parameters.timelimit = time_limit or 300
        s = rel.solve()
        return {"n_vars": n_vars, "n_cons": n_cons,
                "lp_bound": (round(s.objective_value, 4) if s else None),
                "status": rel.solve_details.status if rel.solve_details else "none"}
    if mip_gap is not None:
        m.parameters.mip.tolerances.mipgap = mip_gap
    if time_limit is not None:
        m.parameters.timelimit = time_limit
    if threads is not None:
        m.parameters.threads = threads

    t0 = time.time()
    sol = m.solve(log_output=log_output)
    wall = time.time() - t0
    det = m.solve_details

    result = {
        "n_vars": n_vars, "n_cons": n_cons, "n_arcs": len(H.arcList),
        "wall_s": wall,
        "status": det.status if det else "no_solution",
        "cplex_status": det.status_code if det else None,
        "objVal": (round(sol.objective_value, 2) if sol else None),
        "mip_gap": (det.mip_relative_gap if det else None),
        "best_bound": (det.best_bound if det else None),
        "lowerVessels": lowerVessels,
        "params": {
            "tau": problem.TransferDuration, "costScenario": getattr(problem, "costScenario", None),
            "travelcoststreet": problem.travelcoststreet,
            "travelcostwater": problem.travelcostwater,
            "penaltyCars": problem.penaltyCars, "penaltyVessels": problem.penaltyVessels,
        },
    }

    if sol:
        result["solution"] = _extract_solution(H)
    return result


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    import instanceGenerator

    # quick smoke test at n=6 (tiny, should solve instantly)
    p = instanceGenerator.readGenerate("C201.json", 6, timeLimit=120,
                                       problem_type="2eVRP", closeness=0.0)
    p.costScenario = 0.1
    p.update_rule = [False, False]
    p.Set_cost_coefficients()
    r = joint_synchronized_cplex(p, time_limit=120)
    for k, v in r.items():
        if k != "solution":
            print(f"{k}: {v}")
    if "solution" in r:
        s = r["solution"]
        print("routes:", s["xij"])
        print("transfers:", s["vi"], "hubs:", s["hubs"], "nCars:", s["nCars"], "nVessel:", s["nVessel"])
