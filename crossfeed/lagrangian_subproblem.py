"""
#4 — the bounded synchronization+water subproblem for a FIXED
(routing, transfer-set) decision, with the satellite-assignment coupling
`hubAssignment_i : sum_p v_ip = 1` either kept OR Lagrangian-relaxed.

Karademir's LBBD (`DecomposedModels.Subproblem_bounded`) keeps that
constraint and solves the LP relaxation of the whole subproblem, then
reads its dual at the incumbent for the `ciko3` cut.

Here we instead:
  * DROP `hubAssignment_i` and add `sum_i lam_i (sum_p v_ip - 1)` to the
    objective, and
  * solve the resulting subproblem to integer optimality (or as an LP),
  * so a subgradient loop over `lam` optimizes the Lagrangian dual
    `max_lam L(lam)` — the best possible multipliers, not the LP-dual
    values at one point.

Translated from `subproblem_bounded_cplex.py` (which itself is the
docplex port of `Subproblem_bounded`, verified structurally).

`SubModel.solve(lam)` returns:
    value      : L(lam) if lam given, else z* (true subproblem optimum)
    subgrad    : {i: sum_p v*_ip - 1}  (0 at a feasible point)
    status, wall_s, vip_sol
"""
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
from docplex.mp.model import Model


@dataclass
class SubResult:
    value: float | None          # a VALID lower bound on the true min L(lam)
    subgrad: dict = field(default_factory=dict)
    status: str = ""
    wall_s: float = 0.0
    vip_sol: dict = field(default_factory=dict)
    mip_gap: float | None = None
    incumbent: float | None = None   # CPLEX incumbent (>= value); subgrad taken here
    proven: bool = True              # False if solve was truncated (value = best_bound)
    y_sol: list = field(default_factory=list)   # vessel arcs [[i,j]] at the incumbent


class SubModel:
    def __init__(self, problem, arcList, transferSet, *, hubassign: bool,
                 integral: bool, name="lagr_sub"):
        self.problem = problem
        self.transferSet = list(transferSet)
        self.Sats = list(problem.satellites)
        self.hubassign = hubassign
        self.integral = integral
        self._build(arcList)

    # ------------------------------------------------------------------
    def _bin(self, m, nm):
        return m.binary_var(name=nm) if self.integral else m.continuous_var(lb=0, ub=1, name=nm)

    def _int(self, m, lb, ub, nm):
        return (m.integer_var(lb=lb, ub=ub, name=nm) if self.integral
                else m.continuous_var(lb=lb, ub=ub, name=nm))

    def _build(self, arcList):
        p = self.problem
        D = p.DistMatrix
        nd = p.nodes
        CDC = p.CDC
        TD = p.TransferDuration
        Customers = p.customers
        Sats = self.Sats
        transferSet = self.transferSet
        m = Model(name="lagr_sub")

        # ---- street ----
        hi = {}
        mi = {}
        for i in Customers:
            hi[i] = m.continuous_var(lb=nd[i].earliest, ub=nd[i].latest, name=f"h_{i}")
            mi[i] = 0
        hi[0] = m.continuous_var(lb=nd[CDC].earliest, ub=nd[CDC].latest, name="h_0")

        for i in transferSet:
            load = nd[i].demand
            nxt = i
            inc = next(j for [j, k] in arcList if k == nxt)
            while inc != 0 and inc not in transferSet:
                load += nd[inc].demand
                nxt = inc
                inc = next(j for [j, k] in arcList if k == nxt)
            mi[i] = load

        for i in Customers:
            m.add_constraint(float(nd[0].earliest + D[0][i]) <= hi[i])
            m.add_constraint(nd[i].earliest <= hi[i])
            m.add_constraint(hi[i] <= nd[i].latest)

        # ---- synchronization ----
        vip, ui, detour = {}, {}, {}
        for i in transferSet:
            ui[i] = m.continuous_var(lb=nd[CDC].earliest, ub=nd[CDC].latest, name=f"u_{i}")
            detour[i] = m.continuous_var(lb=0, ub=m.infinity, name=f"detour_{i}")
            for pp in Sats:
                vip[i, pp] = self._bin(m, f"vip_{i}_{pp}")

        if self.hubassign:
            for i in transferSet:
                m.add_constraint(m.sum(vip[i, pp] for pp in Sats) == 1,
                                 ctname=f"hubAssignment_{i}")

        for i in transferSet:
            m.add_constraint(ui[i] >= hi[i] + nd[i].serviceTime
                             + m.sum(D[i][pp] * vip[i, pp] for pp in Sats),
                             ctname=f"transferCustomerLower_{i}")
            m.add_constraint(nd[CDC].earliest + m.sum(D[CDC][pp] * vip[i, pp] for pp in Sats) <= ui[i],
                             ctname=f"depotLower_{i}")
            m.add_constraint(nd[CDC].latest >= ui[i] + TD
                             + m.sum(D[pp][CDC] * vip[i, pp] for pp in Sats),
                             ctname=f"depotUpper_{i}")
            j = next(jj for [k, jj] in arcList if k == i)
            m.add_constraint(m.sum((D[i][pp] + D[pp][j]) * vip[i, pp] for pp in Sats) <= detour[i],
                             ctname=f"detourC_{i}")
            if j != 0:
                maxTravel = max(D[i][pp] + D[pp][j] for pp in Sats)
                Mij = nd[i].latest + nd[i].serviceTime + TD + maxTravel - nd[j].earliest
                m.add_constraint(
                    ui[i] + TD + m.sum(D[pp][j] * vip[i, pp] for pp in Sats)
                    <= hi[j] + Mij * (1 - m.sum(vip[i, pp] for pp in Sats)),
                    ctname=f"nextDelayed_{i}")

        for [i, j] in arcList:
            if i not in transferSet and j != 0:
                m.add_constraint(hi[i] + nd[i].serviceTime + D[i][j] <= hi[j],
                                 ctname=f"timeDependency_{i}_{j}")

        # ---- water ----
        setCw = [CDC] + transferSet
        li, fij, y, arcW = {}, {}, {}, {}
        nofVessels = self._int(m, 0, len(transferSet), "nofVessels")
        for i in transferSet:
            li[i] = m.continuous_var(lb=nd[i].demand, ub=p.VesselCapacity, name=f"l_{i}")
            for j in transferSet:
                if i != j:
                    fij[i, j] = m.continuous_var(lb=0, ub=nd[CDC].latest, name=f"fij_{i}_{j}")
        for i in setCw:
            for j in setCw:
                if i != j:
                    y[i, j] = self._bin(m, f"Y_{i}_{j}")
                    arcW[i, j] = m.continuous_var(lb=0, ub=m.infinity, name=f"arcCostW_{i}_{j}")
        self._y = y
        self._setCw = setCw

        for i in transferSet:
            m.add_constraint(m.sum(y[i, j] for j in setCw if i != j)
                             == m.sum(vip[i, pp] for pp in Sats))
            m.add_constraint(m.sum(y[j, i] for j in setCw if i != j)
                             == m.sum(vip[i, pp] for pp in Sats))
        m.add_constraint(m.sum(y[i, CDC] - y[CDC, i] for i in transferSet) == 0)

        for i in transferSet:
            m.add_constraint(li[i] >= mi[i])
            for j in transferSet:
                if i != j:
                    m.add_constraint(li[j] - li[i] >= mi[j] - p.VesselCapacity * (1 - y[i, j]))
        m.add_constraint(m.sum(y[i, CDC] for i in transferSet) <= nofVessels)

        for i in transferSet:
            for j in transferSet:
                if i != j:
                    m.add_constraint(ui[i] + TD + arcW[i, j]
                                     <= ui[j] + nd[CDC].latest - nd[CDC].latest * y[i, j])

        for i in transferSet:
            m.add_constraint(arcW[i, CDC] >= m.sum(D[pp][CDC] * (y[i, CDC] + vip[i, pp] - 1) for pp in Sats))
            m.add_constraint(arcW[CDC, i] >= m.sum(D[CDC][pp] * (y[CDC, i] + vip[i, pp] - 1) for pp in Sats))
            for pp in Sats:
                m.add_constraint(arcW[i, CDC] >= D[pp][CDC] * (y[i, CDC] + vip[i, pp] - 1))
                m.add_constraint(arcW[CDC, i] >= D[CDC][pp] * (y[CDC, i] + vip[i, pp] - 1))
                for j in transferSet:
                    if i != j and j in setCw:
                        for r in Sats:
                            m.add_constraint(arcW[i, j] >= D[pp][r] * (y[i, j] + vip[i, pp] + vip[j, r] - 2))

        if p.singleTransfer:
            for i in transferSet:
                for j in transferSet:
                    if i < j:
                        m.add_constraint(ui[i] - ui[j] <= fij[i, j])
                        m.add_constraint(ui[j] - ui[i] <= fij[i, j])
                        m.add_constraint(fij[j, i] == fij[i, j])
                        for pp in Sats:
                            m.add_constraint(fij[i, j] >= TD * (vip[i, pp] + vip[j, pp] - 1))

        # ---- objective ----
        FleetStreet = m.continuous_var(lb=0, ub=m.infinity, name="FleetStreet")
        TravelStreet = m.continuous_var(lb=0, ub=m.infinity, name="TravelStreet")
        FleetWater = m.continuous_var(lb=0, ub=m.infinity, name="FleetWater")
        TravelWater = m.continuous_var(lb=0, ub=m.infinity, name="TravelWater")

        arcs_from_garage = [j for [i, j] in arcList if i == 0]
        arcs_no_transfers = [[i, j] for [i, j] in arcList if i not in transferSet]
        fixed_cost = sum(D[i][j] * p.travelcoststreet for [i, j] in arcs_no_transfers)

        m.add_constraint(len(arcs_from_garage) * p.penaltyCars <= FleetStreet)
        m.add_constraint(fixed_cost + m.sum(p.travelcoststreet * detour[i] for i in transferSet) <= TravelStreet)
        m.add_constraint(nofVessels * p.penaltyVessels <= FleetWater)
        m.add_constraint(m.sum(p.travelcostwater * arcW[i, j] for i in setCw for j in setCw if i != j) <= TravelWater)

        sumDemand = sum(nd[i].demand for i in Customers)
        lowerVessels = math.ceil(sumDemand / p.VesselCapacity)
        minTr = min(2 * D[CDC][s] for s in Sats)
        m.add_constraint(TravelWater >= p.travelcostwater * minTr * lowerVessels)
        m.add_constraint(nofVessels >= lowerVessels)

        zObj = m.continuous_var(lb=0, ub=m.infinity, name="zObj")
        m.add_constraint(FleetStreet + FleetWater + TravelStreet + TravelWater <= zObj)

        m.parameters.preprocessing.presolve = 1
        m.parameters.mip.tolerances.mipgap = 1e-6

        self.m, self.vip, self.zObj = m, vip, zObj
        self.lowerVessels = lowerVessels

    # ------------------------------------------------------------------
    def solve(self, lam: dict | None = None, time_limit: float = 60.0) -> SubResult:
        m = self.m
        if lam:
            pen = m.sum(lam[i] * (m.sum(self.vip[i, pp] for pp in self.Sats) - 1)
                        for i in self.transferSet)
            m.minimize(self.zObj + pen)
        else:
            m.minimize(self.zObj)
        m.parameters.timelimit = time_limit
        t0 = time.time()
        sol = m.solve()
        wall = time.time() - t0
        det = m.solve_details
        if sol is None:
            # infeasible / no incumbent: the proven bound is still a valid LB
            bb = getattr(det, "best_bound", None) if det else None
            return SubResult(bb, {}, det.status if det else "no_solution",
                             wall, proven=False)
        incumbent = round(sol.objective_value, 6)
        status = det.status if det else ""
        proven = ("optimal" in status.lower()) if status else False
        if proven:
            value = incumbent
        else:
            # truncated: CPLEX's best_bound is a VALID lower bound on min L(lam)
            bb = getattr(det, "best_bound", None)
            value = round(bb, 6) if bb is not None else None
        vip_sol = {(i, pp): self.vip[i, pp].solution_value
                   for i in self.transferSet for pp in self.Sats}
        subgrad = {i: sum(vip_sol[i, pp] for pp in self.Sats) - 1.0
                   for i in self.transferSet}
        r = SubResult(value, subgrad, status, wall, vip_sol,
                      det.mip_relative_gap if det else None,
                      incumbent=incumbent, proven=proven)
        r.y_sol = [[i, j] for i in self._setCw for j in self._setCw
                   if i != j and self._y[i, j].solution_value > 0.5]
        return r

    def hub_duals(self) -> dict:
        """LP-relaxation dual values of hubAssignment_i (Karademir's `piT`).
        Only meaningful after an LP solve with hubassign=True, integral=False."""
        out = {}
        for i in self.transferSet:
            c = self.m.get_constraint_by_name(f"hubAssignment_{i}")
            try:
                out[i] = float(c.dual_value)
            except Exception:
                out[i] = 0.0
        return out
