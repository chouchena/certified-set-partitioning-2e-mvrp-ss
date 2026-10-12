"""
Our iterative logic-based Benders decomposition (roadmap Phase 3b(i)).

Fresh docplex implementation — the inherited `LBBDmodel.py` is built on
Gurobi lazy callbacks and can't run on the restricted licence. No
callbacks here: solve master to optimality, solve subproblem, add a cut,
repeat until master bound >= incumbent.

  master     = street + synchronisation (= crossfeed.block_a.BlockA)
               + water surrogate `zwater` (Karademir's own valid water LB)
               + `synch_ij` street-detour lower bounds
               + a growing cut pool
  subproblem = sync + water scheduling for the fixed (routing, transfers)
               -> feasibility + cost + a cut
               (crossfeed.lagrangian_subproblem.SubModel)

Cut arms (config `cut_arm`):
  "karademir" : ciko3 optimality cut (LP-relaxation duals) + naive no-good
  "ours"      : block-relaxation / Lagrangian-strengthened cut + IIS no-good  [TODO]

Every incumbent is gated by the independent verifier (rule 3) and the
whole run is logged (rule 4).
"""
from __future__ import annotations
import math
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, ".")
from crossfeed.block_a import BlockA
from crossfeed.lagrangian_subproblem import SubModel
from instance_view import VInstance
# 2026-09-20: verifier3 replaces verify2 -- it checks K's PUBLISHED (1)-(30) in original form.
from analysis.verifier3 import verify_for_engine as verify_solution
from runlog import RunLogger


@dataclass
class LBBDResult:
    incumbent: dict | None = None
    incumbent_obj: float | None = None
    bound: float | None = None
    gap_pct: float | None = None
    iters: int = 0
    status: str = ""
    verified: bool = False
    history: list = field(default_factory=list)


class Master:
    """BlockA (street+sync) + water surrogate + synch_ij + cut pool."""

    def __init__(self, problem):
        self.p = problem
        self.ba = BlockA(problem, integral=True)
        m = self.ba.m
        D, CDC = problem.DistMatrix, problem.CDC
        Sats = list(problem.satellites)
        Customers = list(problem.customers)

        lv = math.ceil(sum(problem.nodes[c].demand for c in Customers) / problem.VesselCapacity)
        minTr = min(2 * D[CDC][s] for s in Sats)
        zwater_lb = problem.travelcostwater * minTr * lv + lv * problem.penaltyVessels

        # AUDIT FIX (H2): BlockA.TravelStreet ALREADY includes the full
        # satellite-detour cost for transfer arcs (via aS and the vip-indexed
        # lower bounds). Adding Karademir's `synch_ij` on top of it would
        # DOUBLE-COUNT the detour and bias the master bound ABOVE z_joint
        # (invalid — could falsely certify). Their master uses a detour-free
        # street cost + synch_ij; ours uses the full street+sync block.
        # So estWater = the water LB only. The master's optimum is then
        # exactly the block-relaxation bound z_A + w  (valid, see
        # crossfeed/bound_validity.md).
        estWater = m.continuous_var(lb=0, ub=m.infinity, name="estWater")
        m.add_constraint(estWater >= zwater_lb)

        zObj = m.continuous_var(lb=0, ub=m.infinity, name="zObj_master")
        m.add_constraint(self.ba.FleetStreet + self.ba.TravelStreet + estWater <= zObj)
        m.minimize(zObj)

        self.m, self.zObj, self.estWater = m, zObj, estWater
        self.zwater_lb = zwater_lb
        self.cuts = 0
        m.parameters.mip.tolerances.mipgap = 0.0

    def solve(self, time_limit=300, threads=None):
        self.m.parameters.timelimit = time_limit
        if threads:
            self.m.parameters.threads = threads
        t0 = time.time()
        sol = self.m.solve()
        wall = time.time() - t0
        det = self.m.solve_details
        if sol is None:
            return None
        Customers = list(self.p.customers)
        xij = [[i, j] for (i, j) in self.ba.arcList
               if self.ba.xij[i, j].solution_value > 0.5]
        vi = [i for i in Customers if self.ba.vi[i].solution_value > 0.5]
        hubs = []
        for i in vi:
            for pp in self.p.satellites:
                if self.ba.vip[i, pp].solution_value > 0.5:
                    hubs.append(pp)
                    break
        return {"xij": xij, "vi": vi, "hubs": hubs,
                "master_obj": round(sol.objective_value, 4),
                "bound": round(det.best_bound, 4) if det and det.best_bound is not None else round(sol.objective_value, 4),
                "status": det.status if det else "", "wall_s": round(wall, 1)}

    # ---- cuts -----------------------------------------------------
    def add_nogood(self, xij, vi):
        """Karademir's naive combinatorial feasibility cut (their Eq. 59)."""
        m = self.ba.m
        used = set((i, j) for i, j in xij)
        vset = set(vi)
        expr = (m.sum(self.ba.xij[i, j] for (i, j) in self.ba.arcList if (i, j) not in used)
                + m.sum(1 - self.ba.vi[i] for i in vset)
                + m.sum(self.ba.vi[i] for i in self.p.customers if i not in vset))
        m.add_constraint(expr >= 1, ctname=f"nogood_{self.cuts}")
        self.cuts += 1

    def add_optcut(self, xij, vi, full_sub_obj):
        """Combinatorial (Codato–Fischetti style) optimality cut, on zObj
        DIRECTLY:  when the master re-proposes exactly this (routing,
        transfers), the true objective is at least the subproblem's proven
        optimum `full_sub_obj`.  Weak (bites only on exact re-proposal) but
        VALID — it never raises the master's minimum above z_joint, because
        for the re-proposed combo z_joint(combo) = full_sub_obj exactly, and
        for every other combo `deviation >= 1` makes the RHS <= 0.
        (Earlier version cut `estWater` with a sync-inclusive RHS, which
        double-counted the satellite detour already in BlockA.TravelStreet
        and produced bound > incumbent — fixed 2026-09-01.)"""
        m = self.ba.m
        used = set((i, j) for i, j in xij)
        vset = set(vi)
        deviation = (m.sum(self.ba.xij[i, j] for (i, j) in self.ba.arcList if (i, j) not in used)
                     + m.sum(1 - self.ba.vi[i] for i in vset)
                     + m.sum(self.ba.vi[i] for i in self.p.customers if i not in vset))
        bigM = full_sub_obj + 1.0
        m.add_constraint(self.zObj >= full_sub_obj - bigM * deviation,
                         ctname=f"optcut_{self.cuts}")
        self.cuts += 1


def lbbd_solve(problem, spec, *, cut_arm="karademir", time_limit=600,
               master_tl=180, sub_tl=60, max_iter=25, log=True,
               threads=None) -> LBBDResult:
    vinst = VInstance(spec.name, spec.size, wls=spec.wls, tau=problem._resolved_tau,
                      proximity=spec.proximity)
    lg = (RunLogger(f"lbbd_{spec.name}_n{spec.size}_{cut_arm}",
                    instance=spec.name, size=spec.size,
                    config={"engine": "lbbd", "cut_arm": cut_arm,
                            "wls": spec.wls, "tau": spec.tau, "proximity": spec.proximity})
          if log else _Null())

    res = LBBDResult()
    lg.phase("master_build")
    master = Master(problem)
    t0 = time.time()
    seen = set()

    for k in range(max_iter):
        if time.time() - t0 > time_limit:
            res.status = "time_limit"
            break
        lg.phase(f"iter{k}:master")
        ms = master.solve(time_limit=master_tl, threads=threads)
        if ms is None:
            res.status = "master_infeasible"
            break
        # master bound is monotone (cuts only add constraints) but guard
        # against a weaker best_bound from a time-limited master solve (H5)
        res.bound = ms["bound"] if res.bound is None else max(res.bound, ms["bound"])
        lg.bound(res.bound, trigger=f"master:iter{k}",
                 extra={"master_obj": ms["master_obj"], "cuts": master.cuts})

        key = (tuple(sorted(map(tuple, ms["xij"]))), tuple(sorted(ms["vi"])))
        if key in seen:
            # the master re-proposed a decision it already made. If the master
            # bound has caught up to the verified incumbent this is a valid
            # optimality certificate (the master minimises zObj over all
            # routings and still chose this one); otherwise the cuts are too
            # weak to move it -> a genuine stall.
            if (res.incumbent_obj is not None and res.bound is not None
                    and res.bound >= res.incumbent_obj - 1e-3):
                res.status = "optimal"
            else:
                res.status = "stall_master_repeated"
            break
        seen.add(key)

        # ---- subproblem: exact integral scheduling for this decision ----
        lg.phase(f"iter{k}:subproblem")
        sub = SubModel(problem, ms["xij"], ms["vi"], hubassign=True, integral=True)
        try:
            sr = sub.solve(time_limit=sub_tl, threads=threads)
        except TypeError:      # SubModel predates the threads kwarg
            sr = sub.solve(time_limit=sub_tl)
        if sr.value is None:
            master.add_nogood(ms["xij"], ms["vi"])
            lg.event(None, trigger=f"feas_cut:iter{k}", extra={"sub_status": sr.status})
            res.history.append((k, ms["bound"], None, "infeasible"))
            continue

        # sr.value = a VALID lower bound on the subproblem optimum (= incumbent
        # if proven, else CPLEX best_bound). The optcut RHS must use the
        # PROVEN value (sr.value), not the incumbent — an over-large RHS on a
        # truncated subproblem would be an invalid cut.
        full_obj = sr.incumbent if sr.incumbent is not None else sr.value
        cut_rhs = sr.value if sr.proven else None
        # hubs from the subproblem's own assignment (it re-optimises them)
        sub_hubs = []
        for i in ms["vi"]:
            best_p = max(problem.satellites, key=lambda pp: sr.vip_sol.get((i, pp), 0.0))
            sub_hubs.append(best_p)
        s = {"xij": ms["xij"], "vi": ms["vi"], "hubs": sub_hubs,
             "yij": sr.y_sol, "objVal": full_obj}
        vd = verify_solution(vinst, s, expect="any")  # d243: dual leg: block_b posts no (22) row, so validBigM is moot
        verified = vd.ok and vd.obj_matches
        obj = vd.recomputed_obj if vd.recomputed_obj is not None else full_obj

        if verified and (res.incumbent_obj is None or obj < res.incumbent_obj - 1e-6):
            res.incumbent = {**s, "objVal": obj}
            res.incumbent_obj = obj
            res.verified = True
            lg.incumbent(obj, trigger=f"lbbd:iter{k}")
        elif not verified:
            lg.event(None, trigger=f"reject_incumbent:iter{k}",
                     extra={"violations": vd.violations[:3]})

        # optimality cut — only from a PROVEN subproblem (rule 3 / audit H3)
        if cut_rhs is not None:
            master.add_optcut(ms["xij"], ms["vi"], cut_rhs)
            lg.event(None, trigger=f"opt_cut:iter{k}", extra={"rhs": round(cut_rhs, 2)})
        else:
            lg.event(None, trigger=f"opt_cut_skipped:iter{k}", extra={"reason": "subproblem not proven"})

        res.history.append((k, ms["bound"], res.incumbent_obj, "feasible"))
        res.iters = k + 1

        if res.incumbent_obj is not None and ms["bound"] >= res.incumbent_obj - 1e-3:
            res.status = "optimal"
            break
    else:
        res.status = res.status or "max_iter"

    if res.incumbent_obj and res.bound:
        res.gap_pct = 100 * (res.incumbent_obj - res.bound) / abs(res.incumbent_obj)
    # run_valid: an LBBD run that doesn't converge is still a valid run; only
    # a verifier rejection makes it null. Guard 1 auto-quarantines if the
    # master bound ever exceeds the verified incumbent (the old detour
    # double-count would have been caught here automatically).
    lg.close(status=res.status, verified=res.verified, run_valid=True,
             final_incumbent=res.incumbent_obj, final_bound=res.bound)
    return res


def _fixed_street_cost(problem, xij, vi):
    D = problem.DistMatrix
    vset = set(vi)
    c = 0.0
    for (i, j) in xij:
        if i not in vset:
            c += problem.travelcoststreet * D[i][j]
    c += sum(1 for (i, j) in xij if i == 0) * problem.penaltyCars
    return c


def _dummy_water(problem, vi, hubs):
    """One CDC->i->CDC vessel per transfer — always feasible; the verifier
    checks capacity/timing. TODO: use the real y from the subproblem."""
    CDC = problem.CDC
    out = []
    for i in vi:
        out.append([CDC, i]); out.append([i, CDC])
    return out


class _Null:
    def __getattr__(self, _):
        return lambda *a, **k: None


if __name__ == "__main__":
    import argparse
    from build_instance import build
    from solver.config import InstanceSpec

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="C201")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--cut-arm", default="karademir")
    ap.add_argument("--max-iter", type=int, default=20)
    ap.add_argument("--time-limit", type=float, default=600,
                    help="overall LBBD budget (s). Was hardcoded at the 600 default, "
                         "which handicapped K's method by 0.24x-5.36x per cell.")
    ap.add_argument("--master-tl", type=float, default=180)
    ap.add_argument("--sub-tl", type=float, default=60)
    ap.add_argument("--threads", type=int, default=None,
                    help="solver threads. Unset = CPLEX default = ALL cores, which is "
                         "what every existing reproduction used. K ran 4.")
    a = ap.parse_args()

    spec = InstanceSpec(a.instance, a.size)
    p = build(a.instance, a.size, wls=spec.wls, tau=spec.tau, proximity=spec.proximity, time_limit=300)
    r = lbbd_solve(p, spec, cut_arm=a.cut_arm, max_iter=a.max_iter,
                   time_limit=a.time_limit, master_tl=a.master_tl, sub_tl=a.sub_tl,
                   threads=a.threads)
    print(f"\n{a.instance} n={a.size} [{a.cut_arm}]: incumbent={r.incumbent_obj} "
          f"bound={r.bound} gap={r.gap_pct}%  {r.status}  ({r.iters} iters, verified={r.verified})")
    for h in r.history:
        print(f"  iter {h[0]}: bound={h[1]} inc={h[2]} {h[3]}")
