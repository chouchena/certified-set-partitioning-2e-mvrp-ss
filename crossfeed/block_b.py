"""
Lagrangian Decomposition — Candidate A, BLOCK B (water level).

Block B = the joint model's water block, over DUPLICATED copies
v^B_ip, u^B_i, m^B_i of the coupling variables:

  variables : y_ij, l_i, f^w_ij (arcWaterCost), nofVessels, v^B_ip, u^B_i, m^B_i
  constraints: (16),(18),(19),(20),(21),(22),(23),(24),(25)
               -- (17)'s `nofVessels >= lowerVessels` and the water-travel
               LB cut are DROPPED: they are valid inequalities for the JOINT
               problem, not for a decoupled block where v^B is free. Keeping
               them would make block B infeasible whenever the multipliers
               push it toward zero transfers.
  objective : FleetWater + TravelWater
            - sum_{i,p} lam_v[i,p] * v^B_ip
            - sum_i     lam_u[i]   * u^B_i
            - sum_i     lam_m[i]   * m^B_i

Since block B owns y AND both v-endpoints, (23) f^w_ij >= t_pr(y_ij +
v^B_ip + v^B_jr - 2) is entirely internal (no bilinear cross-block term).

At lam = 0 block B is trivially 0 (no transfers). The multipliers "pay"
block B to serve transfers; the LD bound is max_lam [z_A(lam) + z_B(lam)].
"""
from __future__ import annotations
import time
from docplex.mp.model import Model


class BlockB:
    def __init__(self, problem, *, integral: bool = True):
        p = self.problem = problem
        D = p.DistMatrix
        nd = p.nodes
        CDC = p.CDC
        TD = p.TransferDuration
        Customers = list(p.customers)
        Sats = list(p.satellites)
        setCw = [CDC] + Customers
        self.Customers, self.Sats = Customers, Sats

        m = Model(name="LD_blockB")
        bvar = (lambda nm: m.binary_var(name=nm)) if integral else (lambda nm: m.continuous_var(0, 1, nm))

        vB, uB, mB = {}, {}, {}
        for i in Customers:
            uB[i] = m.continuous_var(lb=nd[CDC].earliest, ub=nd[CDC].latest, name=f"uB[{i}]")
            mB[i] = m.continuous_var(lb=nd[i].demand, ub=p.CarCapacity, name=f"mB[{i}]")
            for pp in Sats:
                vB[i, pp] = bvar(f"vB.{i}.{pp}")

        li = {i: m.continuous_var(lb=nd[i].demand, ub=p.VesselCapacity, name=f"l[{i}]")
              for i in Customers}
        nofVessels = (m.integer_var(lb=0, ub=len(Customers), name="nofVessels") if integral
                      else m.continuous_var(lb=0, ub=len(Customers), name="nofVessels"))

        y, aW = {}, {}
        for i in setCw:
            for j in setCw:
                if i != j:
                    y[i, j] = bvar(f"Y[{i}.{j}]")
                    aW[i, j] = m.continuous_var(lb=0, ub=m.infinity, name=f"aW[{i}.{j}]")

        for i in Customers:                                           # (16)
            m.add_constraint(m.sum(y[i, j] for j in setCw if i != j)
                             == m.sum(vB[i, pp] for pp in Sats))
            m.add_constraint(m.sum(y[j, i] for j in setCw if i != j)
                             == m.sum(vB[i, pp] for pp in Sats))
        m.add_constraint(m.sum(y[i, CDC] - y[CDC, i] for i in Customers) == 0)   # (17) flow bal
        m.add_constraint(m.sum(y[i, CDC] for i in Customers) == nofVessels)      # (17) def

        for i in Customers:                                           # (18)(19)
            m.add_constraint(li[i] >= mB[i])
            for j in Customers:
                if i != j:
                    m.add_constraint(li[j] - li[i] >= mB[j] - p.VesselCapacity * (1 - y[i, j]))

        for i in Customers:                                           # (20)
            for j in Customers:
                if i != j:
                    m.add_constraint(uB[i] + TD + aW[i, j]
                                     <= uB[j] + nd[CDC].latest - nd[CDC].latest * y[i, j])

        for i in Customers:                                           # (21)(22)(23)
            m.add_constraint(aW[i, CDC] >= m.sum(D[pp][CDC] * (y[i, CDC] + vB[i, pp] - 1) for pp in Sats))
            m.add_constraint(aW[CDC, i] >= m.sum(D[CDC][pp] * (y[CDC, i] + vB[i, pp] - 1) for pp in Sats))
            for pp in Sats:
                m.add_constraint(aW[i, CDC] >= D[pp][CDC] * (y[i, CDC] + vB[i, pp] - 1))
                m.add_constraint(aW[CDC, i] >= D[CDC][pp] * (y[CDC, i] + vB[i, pp] - 1))
                for j in Customers:
                    if i != j:
                        for r in Sats:
                            m.add_constraint(aW[i, j] >= D[pp][r] * (y[i, j] + vB[i, pp] + vB[j, r] - 2))

        FleetWater = m.continuous_var(lb=0, ub=m.infinity, name="FleetWater")
        TravelWater = m.continuous_var(lb=0, ub=m.infinity, name="TravelWater")
        m.add_constraint(nofVessels * p.penaltyVessels <= FleetWater)
        m.add_constraint(m.sum(p.travelcostwater * aW[i, j] for i in setCw for j in setCw if i != j)
                         <= TravelWater)

        self.m = m
        self.vB, self.uB, self.mB = vB, uB, mB
        self._waterobj = FleetWater + TravelWater
        m.parameters.mip.tolerances.mipgap = 1e-4

    # ------------------------------------------------------------------
    def solve(self, lam_v=None, lam_u=None, lam_m=None, time_limit=120):
        m = self.m
        pen = 0
        if lam_v:
            pen -= m.sum(lam_v[(i, pp)] * self.vB[i, pp]
                         for i in self.Customers for pp in self.Sats if (i, pp) in lam_v)
        if lam_u:
            pen -= m.sum(lam_u[i] * self.uB[i] for i in self.Customers if i in lam_u)
        if lam_m:
            pen -= m.sum(lam_m[i] * self.mB[i] for i in self.Customers if i in lam_m)
        m.minimize(self._waterobj + pen)
        m.parameters.timelimit = time_limit
        t0 = time.time()
        sol = m.solve()
        wall = time.time() - t0
        det = m.solve_details
        status = det.status if det else "none"
        proven = "optimal" in status.lower()
        if sol is None:
            bb = getattr(det, "best_bound", None) if det else None
            return {"value": bb, "status": status, "wall_s": round(wall, 1), "proven": False}
        inc = round(sol.objective_value, 4)
        bb = getattr(det, "best_bound", None)
        value = inc if proven else (round(bb, 4) if bb is not None else None)
        return {"value": value, "incumbent": inc, "status": status,
                "wall_s": round(wall, 1), "proven": proven,
                "n_vars": m.number_of_variables, "n_cons": m.number_of_constraints,
                "vB_sol": {(i, pp): self.vB[i, pp].solution_value
                           for i in self.Customers for pp in self.Sats},
                "uB_sol": {i: self.uB[i].solution_value for i in self.Customers},
                "mB_sol": {i: self.mB[i].solution_value for i in self.Customers}}
