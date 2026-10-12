"""joint_model_gurobi.py -- faithful Gurobi port of joint_model_cplex.py.

Rule-3 port-equivalence: this must reproduce the CPLEX joint model's proven optima
(C205 n20 = 685.19, C201 n20 = 697.69) before any Gurobi output is trusted. It is a
line-by-line translation of `build_joint_model` / `joint_synchronized_cplex`, including
the corrected disjunctive (26) behind `hardSingleTransfer`. Solver-agnosticism leg (P3):
lets us run K's own solver (Gurobi) and remove the CPLEX-vs-Gurobi referee point.

docplex -> gurobipy map: Model->gp.Model; integer_var/binary_var/continuous_var->addVar
with vtype; add_constraint->addConstr; m.sum->gp.quicksum; minimize->setObjective(...,
GRB.MINIMIZE); solution_value->.X; objective bound->ObjBound; gap->MIPGap.
"""
from __future__ import annotations
import math
import gurobipy as gp
from gurobipy import GRB


def build_joint_model_gurobi(problem):
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
    m = gp.Model("2EMVRPTWSS_joint_gurobi")
    INF = GRB.INFINITY

    # ---------------- STREET VARIABLES ----------------
    nofCars = m.addVar(lb=0, ub=len(Customers), vtype=GRB.INTEGER, name="nofCars")
    vi, hi, mi = {}, {}, {}
    for i in Customers:
        vi[i] = m.addVar(vtype=GRB.BINARY, name=f"v.{i}")
        hi[i] = m.addVar(lb=nd[i].earliest, ub=nd[i].latest, vtype=GRB.CONTINUOUS, name=f"h[{i}]")
        mi[i] = m.addVar(lb=nd[i].demand, ub=problem.CarCapacity, vtype=GRB.CONTINUOUS, name=f"m[{i}]")
    hi[0] = m.addVar(lb=nd[0].earliest, ub=nd[0].latest, vtype=GRB.CONTINUOUS, name="h[0]")

    xij, arcStreetCost, arcList = {}, {}, []
    for i in SetCd:
        for j in SetCd:
            if i == j:
                continue
            if nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest:
                xij[i, j] = m.addVar(vtype=GRB.BINARY, name=f"x.{i}.{j}")
                arcStreetCost[i, j] = m.addVar(lb=0, ub=INF, vtype=GRB.CONTINUOUS, name=f"arcCostS[{i}.{j}]")
                arcList.append([i, j])
    arcset = set((i, j) for i, j in arcList)
    m.update()

    # ---------------- STREET CONSTRAINTS ----------------
    for i in Customers:
        m.addConstr(gp.quicksum(xij[i, j] for j in SetCd if (i, j) in arcset) == 1, f"outflow.{i}")
        m.addConstr(gp.quicksum(xij[j, i] for j in SetCd if (j, i) in arcset) == 1, f"inflow.{i}")
    m.addConstr(gp.quicksum(xij[i, 0] for i in Customers if (i, 0) in arcset) == nofCars)
    m.addConstr(gp.quicksum((xij[i, 0] if (i, 0) in arcset else 0)
                            - (xij[0, i] if (0, i) in arcset else 0)
                            for i in Customers) == 0)
    for i in Customers:                                               # Const4
        if (i, 0) in arcset:
            m.addConstr(vi[i] >= xij[i, 0])
    for i in Customers:                                               # Const5
        for j in Customers:
            if (i, j) in arcset:
                m.addConstr(mi[j] - mi[i] >= nd[j].demand - problem.CarCapacity * (1 - xij[i, j] + vi[i]))
    for i in Customers:                                               # Const7
        m.addConstr(float(nd[0].earliest + D[0][i]) <= hi[i])
        m.addConstr(float(nd[0].latest - D[i][0] - nd[i].serviceTime - TD) >= hi[i])
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
                m.addConstr(hi[i] + nd[i].serviceTime + TD * vi[i] + arcStreetCost[i, j]
                            <= hi[j] + Mij - Mij * xij[i, j])
    for (i, j) in arcList:                                            # Const9
        m.addConstr(arcStreetCost[i, j] >= D[i][j] * xij[i, j])
        if i in Customers:
            minTravel = min(D[i][p] + D[p][j] - D[i][j] for p in Satellites)
            m.addConstr(arcStreetCost[i, j] >= D[i][j] * xij[i, j] + minTravel * (xij[i, j] + vi[i] - 1))

    # ---------------- SYNCHRONIZATION ----------------
    ui, vip = {}, {}
    for i in Customers:
        ui[i] = m.addVar(lb=nd[CDC].earliest, ub=nd[CDC].latest, vtype=GRB.CONTINUOUS, name=f"u[{i}]")
        for p in Satellites:
            vip[i, p] = m.addVar(vtype=GRB.BINARY, name=f"vip.{i}.{p}")
    m.update()
    for i in Customers:                                               # Const12
        m.addConstr(gp.quicksum(vip[i, p] for p in Satellites) == vi[i])
    for i in Customers:
        m.addConstr(ui[i] >= hi[i] + nd[i].serviceTime
                    + gp.quicksum(D[i][p] * vip[i, p] for p in Satellites))            # Const13
        m.addConstr(nd[CDC].earliest + gp.quicksum(D[CDC][p] * vip[i, p] for p in Satellites) <= ui[i])   # Const15
        m.addConstr(nd[CDC].latest >= ui[i]
                    + gp.quicksum((TD + D[p][CDC]) * vip[i, p] for p in Satellites))    # Const15
        for j in SetCd:
            if (i, j) in arcset:
                m.addConstr(gp.quicksum((D[i][p] + D[p][j]) * (xij[i, j] + vip[i, p] - 1) for p in Satellites)
                            <= arcStreetCost[i, j])
                maxTravel = max(D[i][p] + D[p][j] for p in Satellites)
                Mij = nd[i].latest + nd[i].serviceTime + TD + maxTravel - nd[j].earliest
                m.addConstr(ui[i] + gp.quicksum((TD + D[p][j]) * vip[i, p] for p in Satellites)
                            <= hi[j] + Mij - Mij * xij[i, j])                           # Const14

    # ---------------- WATER LEVEL ----------------
    nofVessels = m.addVar(lb=0, ub=len(Customers), vtype=GRB.INTEGER, name="nofVessels")
    z = {}
    if problem.stationaryBarges:
        for p in Satellites:
            z[p] = m.addVar(vtype=GRB.BINARY, name=f"z[{p}]")
    li, fij = {}, {}
    for i in Customers:
        li[i] = m.addVar(lb=nd[i].demand, ub=problem.VesselCapacity, vtype=GRB.CONTINUOUS, name=f"l[{i}]")
        for j in Customers:
            if i != j:
                fij[i, j] = m.addVar(lb=0, ub=nd[CDC].latest, vtype=GRB.CONTINUOUS, name=f"fij[{i},{j}]")
    y, arcWaterCost = {}, {}
    for i in setCw:
        for j in setCw:
            if i != j:
                y[i, j] = m.addVar(vtype=GRB.BINARY, name=f"Y[{i},{j}]")
                arcWaterCost[i, j] = m.addVar(lb=0, ub=INF, vtype=GRB.CONTINUOUS, name=f"arcCostW[{i}.{j}]")
    m.update()

    for i in Customers:                                               # Const18
        m.addConstr(gp.quicksum(y[i, j] for j in setCw if i != j) == vi[i])
        m.addConstr(gp.quicksum(y[j, i] for j in setCw if i != j) == vi[i])
    m.addConstr(gp.quicksum(y[i, CDC] - y[CDC, i] for i in Customers) == 0)             # Const19
    for i in Customers:                                               # Const20/21
        m.addConstr(li[i] >= mi[i])
        for j in Customers:
            if i != j:
                m.addConstr(li[j] - li[i] >= mi[j] - problem.VesselCapacity * (1 - y[i, j]))

    sumDemand = sum(nd[i].demand for i in Customers)
    lowerVessels = math.ceil(sumDemand / problem.VesselCapacity)
    m.addConstr(gp.quicksum(y[i, CDC] for i in Customers) == nofVessels)
    m.addConstr(nofVessels >= lowerVessels)

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
                m.addConstr(ui[i] + TD + arcWaterCost[i, j] <= ui[j] + MijWater - MijWater * y[i, j])

    for i in Customers:                                               # Const23/24
        m.addConstr(arcWaterCost[CDC, i] >= gp.quicksum(D[CDC][p] * (y[CDC, i] + vip[i, p] - 1) for p in Satellites))
        m.addConstr(arcWaterCost[i, CDC] >= gp.quicksum(D[p][CDC] * (y[i, CDC] + vip[i, p] - 1) for p in Satellites))
        for p in Satellites:
            for j in Customers:
                if i != j:
                    for r in Satellites:
                        if p != r:
                            m.addConstr(arcWaterCost[i, j] >= D[p][r] * (y[i, j] + vip[i, p] + vip[j, r] - 2))

    if problem.singleTransfer:                                        # (26) vacuous (faithful to K)
        for i in Customers:
            for j in Customers:
                if i < j:
                    m.addConstr(ui[i] - ui[j] <= fij[i, j])
                    m.addConstr(ui[j] - ui[i] <= fij[i, j])
                    m.addConstr(fij[j, i] == fij[i, j])
                    for p in Satellites:
                        m.addConstr(fij[i, j] >= TD * (vip[i, p] + vip[j, p] - 1))

    if getattr(problem, "hardSingleTransfer", False):                # (26) corrected disjunctive
        # INDICATOR CONSTRAINTS, NOT BIG-M -- see joint_model_cplex for the full account.
        # The big-M form here was identical to the CPLEX one, Mbig and gate alike, and carries
        # the same defect: a solver accepts a binary as integral within its tolerance, and Mbig
        # multiplies that slack into the constraint. Captured reproducibly on R202/n100 with
        # CPLEX: o at 1 - 1.1e-8 and Mbig = 1187 gave a real 1.3049e-5 violation of a 20-unit
        # separation. Gurobi's default IntFeasTol is also 1e-5, so the same arithmetic applies.
        # An indicator is enforced by branching, so there is no coefficient for the tolerance
        # to be multiplied by and the separation is exactly TD.
        sep, a1, a0 = {}, {}, {}
        for i in Customers:
            for j in Customers:
                if i >= j:
                    continue
                sep[i, j] = m.addVar(vtype=GRB.BINARY, name=f"sep.{i}.{j}")
                # forced ON when both sit at the same p; free otherwise, which can only ever
                # ADD separation, never remove it
                for p in Satellites:
                    m.addConstr(sep[i, j] >= vip[i, p] + vip[j, p] - 1)
                o = m.addVar(vtype=GRB.BINARY, name=f"o.{i}.{j}")
                a1[i, j] = m.addVar(vtype=GRB.BINARY, name=f"a1.{i}.{j}")
                a0[i, j] = m.addVar(vtype=GRB.BINARY, name=f"a0.{i}.{j}")
                m.addConstr(a1[i, j] <= sep[i, j])
                m.addConstr(a1[i, j] <= o)
                m.addConstr(a0[i, j] <= sep[i, j])
                m.addConstr(a0[i, j] <= 1 - o)
                m.addConstr(a1[i, j] + a0[i, j] >= sep[i, j])
                m.addConstr((a1[i, j] == 1) >> (ui[j] >= ui[i] + TD))
                m.addConstr((a0[i, j] == 1) >> (ui[i] >= ui[j] + TD))

    # ---------------- OBJECTIVE ----------------
    FleetStreet = m.addVar(lb=0, ub=INF, name="FleetStreet")
    TravelStreet = m.addVar(lb=0, ub=INF, name="TravelStreet")
    FleetWater = m.addVar(lb=0, ub=INF, name="FleetWater")
    TravelWater = m.addVar(lb=0, ub=INF, name="TravelWater")
    m.update()
    m.addConstr(nofVessels * problem.penaltyVessels == FleetWater)
    m.addConstr(nofCars * problem.penaltyCars == FleetStreet)
    m.addConstr(gp.quicksum(problem.travelcoststreet * arcStreetCost[i, j] for (i, j) in arcList) == TravelStreet)
    m.addConstr(gp.quicksum(problem.travelcostwater * arcWaterCost[i, j]
                            for i in setCw for j in setCw if i != j) == TravelWater)
    minTr = min(D[CDC][s] for s in Satellites)
    m.addConstr(TravelWater >= problem.travelcostwater * minTr * lowerVessels)

    if problem.stationaryBarges:
        nofBarges = math.ceil(sumDemand / problem.VesselCapacity)
        m.addConstr(FleetWater == problem.penaltyVessels * nofBarges)
        m.addConstr(gp.quicksum(z[p] for p in Satellites) <= nofBarges)
        for i in Customers:
            for p in Satellites:
                m.addConstr(vip[i, p] <= z[p])
        for i in setCw:
            for j in setCw:
                if i != j and i != CDC and j != CDC:
                    m.addConstr(arcWaterCost[i, j] == 0)

    zObj = m.addVar(lb=0, ub=INF, name="zObj")
    m.update()
    m.addConstr(FleetStreet + FleetWater + TravelStreet + TravelWater <= zObj)
    m.setObjective(zObj, GRB.MINIMIZE)

    H = dict(m=m, Customers=Customers, Satellites=Satellites, CDC=CDC, setCw=setCw,
             arcList=arcList, nofCars=nofCars, nofVessels=nofVessels, vi=vi, hi=hi, mi=mi,
             ui=ui, vip=vip, xij=xij, y=y, arcStreetCost=arcStreetCost, arcWaterCost=arcWaterCost,
             FleetStreet=FleetStreet, TravelStreet=TravelStreet, FleetWater=FleetWater,
             TravelWater=TravelWater, zObj=zObj, lowerVessels=lowerVessels,
             n_vars=m.NumVars, n_cons=m.NumConstrs)
    return H


def _extract(H):
    m, Customers, Satellites, setCw, CDC = (H["m"], H["Customers"], H["Satellites"],
                                            H["setCw"], H["CDC"])
    xij, vi, vip, y = H["xij"], H["vi"], H["vip"], H["y"]
    used = [[i, j] for (i, j) in H["arcList"] if xij[i, j].X > 0.5]
    transfers, hubs = [], []
    for i in Customers:
        if vi[i].X > 0.5:
            transfers.append(i)
            for p in Satellites:
                if vip[i, p].X > 0.5:
                    hubs.append(p); break
    water = [[i, j] for i in setCw for j in setCw if i != j and y[i, j].X > 0.5]
    return {"xij": used, "vi": transfers, "hubs": hubs, "yij": water,
            "nCars": int(round(H["nofCars"].X)), "nVessel": int(round(H["nofVessels"].X)),
            "hi": {i: H["hi"][i].X for i in [0] + Customers},
            "ui": {i: H["ui"][i].X for i in Customers if vi[i].X > 0.5}}


def joint_synchronized_gurobi(problem, time_limit=600, mip_gap=0.0, threads=None, log_output=False,
                              trace_path=None):
    """trace_path: if given, the incumbent/bound-over-RT trajectory is written INCREMENTALLY
    (one JSON line per event) so a long solve is LIVE-monitorable and yields the RT-evolution
    plot data. Also returned as `progress_trace`. (Rule-4: no exact solve is a black box.)"""
    import time, json
    H = build_joint_model_gurobi(problem)
    m = H["m"]
    m.Params.OutputFlag = 1 if log_output else 0
    if time_limit is not None:
        m.Params.TimeLimit = time_limit
    m.Params.MIPGap = mip_gap
    if threads is not None:
        m.Params.Threads = threads
    import os as _os
    _t0 = time.time(); _trace = []; _last = [0.0]; _fh = None
    if trace_path:
        try:
            _os.makedirs(_os.path.dirname(trace_path) or ".", exist_ok=True)
            _fh = open(trace_path, "w", encoding="utf-8")     # fresh trace per solve (no cross-run append)
        except Exception:
            _fh = None

    def _rec(d):
        _trace.append(d)
        if _fh is not None:
            try:
                _fh.write(json.dumps(d) + "\n"); _fh.flush()   # flush -> live-monitorable
            except Exception:
                pass

    def _cb(model, where):
        t = time.time() - _t0
        if where == GRB.Callback.MIPSOL:                       # new incumbent
            _rec({"t": round(t, 2), "event": "incumbent",
                  "inc": model.cbGet(GRB.Callback.MIPSOL_OBJ),
                  "bound": model.cbGet(GRB.Callback.MIPSOL_OBJBND)})
        elif where == GRB.Callback.MIP and t - _last[0] >= 5.0:  # throttled bound snapshot
            _last[0] = t
            _rec({"t": round(t, 2), "event": "bound",
                  "inc": (model.cbGet(GRB.Callback.MIP_OBJBST) if model.cbGet(GRB.Callback.MIP_SOLCNT) > 0 else None),
                  "bound": model.cbGet(GRB.Callback.MIP_OBJBND)})

    m.optimize(_cb)
    if _fh is not None:
        try:
            _fh.close()
        except Exception:
            pass
    ok = m.SolCount > 0
    return {
        "objVal": (m.ObjVal if ok else None),
        "best_bound": m.ObjBound,
        "mip_gap": (m.MIPGap if ok else None),
        "status": int(m.Status),
        "solution": (_extract(H) if ok else None),
        "progress_trace": _trace,
        "params": {"tau": problem.TransferDuration, "n_vars": H["n_vars"], "n_cons": H["n_cons"],
                   "hardSingleTransfer": getattr(problem, "hardSingleTransfer", False)},
    }
