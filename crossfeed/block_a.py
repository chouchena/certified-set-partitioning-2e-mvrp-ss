"""
Lagrangian Decomposition — Candidate A, BLOCK A (street + synchronization).

Block A = the joint compact model MINUS the water level:
  variables : nofCars, v_i, h_i, m_i, x_ij, f^s_ij (arcStreetCost), u_i, v_ip, f_ij
  constraints: (2)-(15) street+sync, (26)-(30) unitary transshipment
  objective : FleetStreet + TravelStreet   [ + Lagrangian penalty ]

The copy constraints v^A = v^B, u^A = u^B, m^A = m^B are dualized with
free-sign multipliers lam_v[(i,p)], lam_u[i], lam_m[i]; block A carries the
+lam terms:
    z_A(lam) = FleetStreet + TravelStreet
             + sum_{i,p} lam_v[i,p] * v_ip
             + sum_i     lam_u[i]   * u_i
             + sum_i     lam_m[i]   * m_i

At lam = 0, z_A is a VALID lower bound on z_joint (dropping the water
block + its non-negative cost is a relaxation).

Line-by-line from `joint_model_cplex.py` lines 37-125 + the singleTransfer
block, verified against the joint model there.
"""
from __future__ import annotations
import math
import time
from docplex.mp.model import Model


class BlockA:
    def __init__(self, problem, *, integral: bool = True, timing_mode: str = "bigM",
                 drop=None, trip_cut: bool = True):
        """
        drop: customer ids to remove from block A (the 'easy customer'
              reduction). z_A(H)* + water_LB(full demand) stays a valid LB
              on z_joint -- see crossfeed/easy_reduction.py.

        timing_mode:
          "bigM"      -- the paper's formulation: Const8/Const14 as
                         LHS <= hi[j] + Mij(1 - xij).  Mij is structurally
                         large on wide-TW instances (analysis/bigM_audit.py)
                         -> weak LP -> block-A B&B plateaus (C203/C204).
          "indicator" -- D1-revised (paper/bigM-tightening-methods.md):
                         xij[i,j] == 1  ->  LHS <= hi[j].  No big-M; CPLEX
                         branches the implication. Every integer solution is
                         identical; the LP relaxation is (weakly) tighter and
                         the disjunctive handling can move the bound faster.
        """
        assert timing_mode in ("bigM", "indicator", "disagg")
        self.timing_mode = timing_mode
        p = self.problem = problem
        D = p.DistMatrix
        nd = p.nodes
        CDC = p.CDC
        TD = p.TransferDuration
        _drop = set(drop or [])
        self._n_dropped = len(_drop)
        Customers = [c for c in p.customers if c not in _drop]
        Sats = list(p.satellites)
        SetCd = [0] + Customers
        self.Customers, self.Sats = Customers, Sats

        m = Model(name="LD_blockA")
        bvar = (lambda nm: m.binary_var(name=nm)) if integral else (lambda nm: m.continuous_var(0, 1, nm))
        ivar = ((lambda lb, ub, nm: m.integer_var(lb=lb, ub=ub, name=nm)) if integral
                else (lambda lb, ub, nm: m.continuous_var(lb=lb, ub=ub, name=nm)))

        nofCars = ivar(0, len(Customers), "nofCars")
        vi, hi, mi = {}, {}, {}
        for i in Customers:
            vi[i] = bvar(f"v.{i}")
            hi[i] = m.continuous_var(lb=nd[i].earliest, ub=nd[i].latest, name=f"h[{i}]")
            mi[i] = m.continuous_var(lb=nd[i].demand, ub=p.CarCapacity, name=f"m[{i}]")
        hi[0] = m.continuous_var(lb=nd[0].earliest, ub=nd[0].latest, name="h[0]")

        xij, aS = {}, {}
        arcList = []
        for i in SetCd:
            for j in SetCd:
                if i == j:
                    continue
                if nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest:
                    xij[i, j] = bvar(f"x.{i}.{j}")
                    aS[i, j] = m.continuous_var(lb=0, ub=m.infinity, name=f"aS[{i}.{j}]")
                    arcList.append((i, j))
        arcset = set(arcList)

        for i in Customers:
            m.add_constraint(m.sum(xij[i, j] for j in SetCd if (i, j) in arcset) == 1)
            m.add_constraint(m.sum(xij[j, i] for j in SetCd if (j, i) in arcset) == 1)
        m.add_constraint(m.sum(xij[i, 0] for i in Customers if (i, 0) in arcset) == nofCars)
        m.add_constraint(m.sum((xij[i, 0] if (i, 0) in arcset else 0)
                               - (xij[0, i] if (0, i) in arcset else 0) for i in Customers) == 0)
        for i in Customers:
            if (i, 0) in arcset:
                m.add_constraint(vi[i] >= xij[i, 0])
        for i in Customers:
            for j in Customers:
                if (i, j) in arcset:
                    m.add_constraint(mi[j] - mi[i] >= nd[j].demand - p.CarCapacity * (1 - xij[i, j] + vi[i]))
        for i in Customers:
            m.add_constraint(float(nd[0].earliest + D[0][i]) <= hi[i])
            m.add_constraint(float(nd[0].latest - D[i][0] - nd[i].serviceTime - TD) >= hi[i])
        for i in Customers:
            for j in SetCd:
                if (i, j) in arcset:
                    lhs8 = hi[i] + nd[i].serviceTime + TD * vi[i] + aS[i, j] - hi[j]
                    if timing_mode == "indicator":
                        m.add_indicator(xij[i, j], lhs8 <= 0, active_value=1)
                    elif timing_mode == "disagg":
                        # split the arc-timing implication by whether i is a
                        # transfer.  The unified big-M carries `TD + max_detour`
                        # (~2 satellite legs) on EVERY arc; most arcs have
                        # vi[i]=0 and need only the direct-travel slack.
                        # regime A  (xij=1, vi[i]=0): hi[i]+svc+D[i][j] <= hi[j].
                        # M must upper-bound the LHS over hi[i]<=latest_i,
                        # hi[j]>=earliest_j; clamp >=0 (a negative bound would
                        # spuriously constrain inactive arcs -> infeasible).
                        M_A = max(0.0, nd[i].latest + nd[i].serviceTime + D[i][j] - nd[j].earliest)
                        m.add_constraint(
                            hi[i] + nd[i].serviceTime + D[i][j] - hi[j]
                            <= M_A * (1 - xij[i, j] + vi[i]))
                        # regime B  (xij=1, vi[i]=1): full detour via aS
                        mt = max(D[i][pp] + D[pp][j] for pp in Sats)
                        M_B = max(0.0, nd[i].latest + nd[i].serviceTime + TD + mt - nd[j].earliest)
                        m.add_constraint(
                            lhs8 <= M_B * (2 - xij[i, j] - vi[i]))
                    else:
                        mt = max(D[i][pp] + D[pp][j] for pp in Sats)
                        Mij = nd[i].latest + nd[i].serviceTime + TD + mt - nd[j].earliest
                        m.add_constraint(lhs8 <= Mij - Mij * xij[i, j])
        for (i, j) in arcList:
            m.add_constraint(aS[i, j] >= D[i][j] * xij[i, j])
            if i in Customers:
                mn = min(D[i][pp] + D[pp][j] - D[i][j] for pp in Sats)
                m.add_constraint(aS[i, j] >= D[i][j] * xij[i, j] + mn * (xij[i, j] + vi[i] - 1))

        ui, vip = {}, {}
        for i in Customers:
            ui[i] = m.continuous_var(lb=nd[CDC].earliest, ub=nd[CDC].latest, name=f"u[{i}]")
            for pp in Sats:
                vip[i, pp] = bvar(f"vip.{i}.{pp}")
        for i in Customers:
            m.add_constraint(m.sum(vip[i, pp] for pp in Sats) == vi[i])
            m.add_constraint(ui[i] >= hi[i] + nd[i].serviceTime + m.sum(D[i][pp] * vip[i, pp] for pp in Sats))
            m.add_constraint(nd[CDC].earliest + m.sum(D[CDC][pp] * vip[i, pp] for pp in Sats) <= ui[i])
            m.add_constraint(nd[CDC].latest >= ui[i] + m.sum((TD + D[pp][CDC]) * vip[i, pp] for pp in Sats))
            for j in SetCd:
                if (i, j) in arcset:
                    m.add_constraint(m.sum((D[i][pp] + D[pp][j]) * (xij[i, j] + vip[i, pp] - 1)
                                           for pp in Sats) <= aS[i, j])
                    lhs14 = (ui[i] + m.sum((TD + D[pp][j]) * vip[i, pp] for pp in Sats) - hi[j])
                    if timing_mode == "indicator":
                        m.add_indicator(xij[i, j], lhs14 <= 0, active_value=1)
                    elif timing_mode == "disagg":
                        # Const14 stays active for every used arc: when vi[i]=0
                        # it still bounds hi[j] via ui[i] (vip=0), and gating it
                        # on vi[i] frees ui[i]/vip in a way that loses the true
                        # optimum (verified on C201/RC201).  Only Const8 splits.
                        mt = max(D[i][pp] + D[pp][j] for pp in Sats)
                        M_B = nd[i].latest + nd[i].serviceTime + TD + mt - nd[j].earliest
                        m.add_constraint(lhs14 <= M_B * (1 - xij[i, j]))
                    else:
                        mt = max(D[i][pp] + D[pp][j] for pp in Sats)
                        Mij = nd[i].latest + nd[i].serviceTime + TD + mt - nd[j].earliest
                        m.add_constraint(lhs14 <= Mij - Mij * xij[i, j])

        # (26)-(30) unitary transshipment
        fij = {}
        if p.singleTransfer:
            for i in Customers:
                for j in Customers:
                    if i != j:
                        fij[i, j] = m.continuous_var(lb=0, ub=nd[CDC].latest, name=f"fij[{i}.{j}]")
            for i in Customers:
                for j in Customers:
                    if i < j:
                        m.add_constraint(ui[i] - ui[j] <= fij[i, j])
                        m.add_constraint(ui[j] - ui[i] <= fij[i, j])
                        m.add_constraint(fij[j, i] == fij[i, j])
                        for pp in Sats:
                            m.add_constraint(fij[i, j] >= TD * (vip[i, pp] + vip[j, pp] - 1))

        # objective
        FleetStreet = m.continuous_var(lb=0, ub=m.infinity, name="FleetStreet")
        TravelStreet = m.continuous_var(lb=0, ub=m.infinity, name="TravelStreet")
        m.add_constraint(nofCars * p.penaltyCars <= FleetStreet)
        m.add_constraint(m.sum(p.travelcoststreet * aS[i, j] for (i, j) in arcList) <= TravelStreet)

        # trip-count valid inequality: each trip ends in a transfer (vi=1) and
        # carries <= CarCapacity, so the number of transfers is at least the
        # ceiling of total demand over capacity.  Validated on 8 verified
        # incumbents (crossfeed/check_cuts.py, 2026-09-03) -- often tight on
        # tight-TW cells.  `trip_cut=False` for the ablation baseline.
        self.trip_cut_rhs = None
        if trip_cut and Customers:
            import math as _math
            demH = sum(nd[c].demand for c in Customers)
            rhs = _math.ceil(demH / p.CarCapacity)
            m.add_constraint(m.sum(vi[i] for i in Customers) >= rhs)
            self.trip_cut_rhs = rhs

        self.m = m
        self.vi, self.vip, self.ui, self.mi = vi, vip, ui, mi
        self.xij, self.hi, self.aS, self.arcList = xij, hi, aS, arcList
        self.nofCars, self.FleetStreet, self.TravelStreet = nofCars, FleetStreet, TravelStreet
        self._streetobj = FleetStreet + TravelStreet
        m.parameters.mip.tolerances.mipgap = 1e-4

    # ------------------------------------------------------------------
    def solve(self, lam_v=None, lam_u=None, lam_m=None, time_limit=120,
              track_progress=None, stall_patience_s=300.0, run_logger=None,
              mip_start_x=None):
        """
        track_progress: None (default) = auto-on whenever time_limit >= 60 s
            -- rule 4/11: any solve budgeted beyond a minute gets its
            (time, best_bound, incumbent) convergence curve captured, not
            just a before/after snapshot (see crossfeed/stall_stopper.py;
            gap found + fixed 2026-09-01, SESSION log). Pass False to force
            off (e.g. tight repeated calls inside a subgradient loop),
            True to force on regardless of time_limit.
        stall_patience_s: once tracking is on, treat `time_limit` as a
            CEILING and abort as soon as the best bound hasn't improved for
            this many seconds -- distinguishes "still converging, needs
            more time" from "plateaued, more time won't help" instead of
            just reporting whatever CPLEX reached at the wall.
        run_logger: an optional runlog.RunLogger; every bound improvement
            is also logged there (trigger="blockA_progress"), so the curve
            is on disk, not only in the returned dict.
        """
        # LAUNCH BACKSTOP (opt-in): when env AUDIT_ENFORCE=1, an in-process solve
        # requires a valid preflight token (env AUDIT_TOKEN -> runs/audit_tokens/<hash>.json).
        # Closes the in-process launch path the PreToolUse shell hook can't see. OFF by
        # default so dev/tests are unaffected; set for campaign runs.
        import os as _os
        if _os.environ.get("AUDIT_ENFORCE") == "1":
            _tk = _os.environ.get("AUDIT_TOKEN", "")
            _tp = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                                "runs", "audit_tokens", _tk + ".json")
            if not (_tk and _os.path.exists(_tp)):
                raise RuntimeError("block_a.solve blocked: AUDIT_ENFORCE=1 but no valid "
                                   "preflight token (run analysis.preflight, export AUDIT_TOKEN).")
        m = self.m
        pen = 0
        if lam_v:
            pen += m.sum(lam_v[(i, pp)] * self.vip[i, pp]
                         for i in self.Customers for pp in self.Sats if (i, pp) in lam_v)
        if lam_u:
            pen += m.sum(lam_u[i] * self.ui[i] for i in self.Customers if i in lam_u)
        if lam_m:
            pen += m.sum(lam_m[i] * self.mi[i] for i in self.Customers if i in lam_m)
        m.minimize(self._streetobj + pen)

        auto_track = (time_limit >= 60) if track_progress is None else track_progress
        stopper = None
        if auto_track:
            from crossfeed.stall_stopper import StallStopper
            # window criterion: abort if best bound gained < 2% over the last
            # `patience` s (tuned 2026-09-01 against the C203/C204/RC203 traces
            # -- catches the crawl, leaves R205-style real convergence alone)
            stopper = StallStopper(patience_s=stall_patience_s, min_window_improve=0.02,
                                   max_time_s=time_limit, warmup_s=300.0)
            m.add_progress_listener(stopper)

        # warm start: a routing skeleton {(i,j): 0/1} for the x.i.j vars.
        # Partial start (arcs only); CPLEX repairs timing/vehicle vars.
        # z_A(H)* is unchanged -- a MIP start only seeds the incumbent, so
        # the reported bound stays identical; it just proves sooner.
        if mip_start_x:
            try:
                ws = m.new_solution()
                for (i, j), xv in self.xij.items():
                    if (i, j) in mip_start_x:
                        ws.add_var_value(xv, int(round(mip_start_x[(i, j)])))
                m.add_mip_start(ws, effort_level=4)  # 4 = repair
            except Exception as _ex:
                print(f"  [warm-start skipped: {_ex}]", flush=True)

        m.parameters.timelimit = time_limit
        t0 = time.time()
        sol = m.solve()
        wall = time.time() - t0
        det = m.solve_details
        status = det.status if det else "none"
        proven = "optimal" in status.lower()

        def _attach_progress(result):
            if stopper is None:
                return result
            result["progress_trace"] = stopper.trace
            result["convergence"] = stopper.summary()
            result["stopped_reason"] = stopper.stopped_reason
            if run_logger is not None:
                last_logged = None
                for (t, bb, obj) in stopper.trace:
                    if bb is not None and bb != last_logged:
                        run_logger.bound(bb, trigger="blockA_progress",
                                         extra={"t": t, "incumbent": obj})
                        last_logged = bb
            return result

        if sol is None:
            bb = getattr(det, "best_bound", None) if det else None
            return _attach_progress({"value": bb, "status": status, "wall_s": round(wall, 1),
                    "proven": False, "incumbent": None})
        inc = round(sol.objective_value, 4)
        bb = getattr(det, "best_bound", None)
        value = inc if proven else (round(bb, 4) if bb is not None else None)
        return _attach_progress({"value": value, "incumbent": inc, "status": status,
                "wall_s": round(wall, 1), "proven": proven,
                "mip_gap": det.mip_relative_gap if det else None,
                "n_vars": m.number_of_variables, "n_cons": m.number_of_constraints,
                "vi_sol": {i: self.vi[i].solution_value for i in self.Customers},
                "vip_sol": {(i, pp): self.vip[i, pp].solution_value
                            for i in self.Customers for pp in self.Sats},
                "ui_sol": {i: self.ui[i].solution_value for i in self.Customers},
                "mi_sol": {i: self.mi[i].solution_value for i in self.Customers},
                "xij_sol": {(i, j): int(round(self.xij[i, j].solution_value))
                            for (i, j) in self.arcList}})


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from build_instance import build
    from joint_model_cplex import joint_synchronized_cplex

    for name, size in [("C201", 10), ("R201", 20), ("R205", 20), ("RC201", 20)]:
        p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=300)
        ba = BlockA(p, integral=True)
        r = ba.solve(time_limit=180)
        p2 = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=300)
        zj = joint_synchronized_cplex(p2, time_limit=180, mip_gap=0.0)
        ratio = (r["value"] / zj["objVal"]) if (r["value"] and zj["objVal"]) else None
        print(f"{name} n={size}: blockA(lam=0)={r['value']} ({r['status']}, {r['wall_s']}s, "
              f"{r.get('n_cons')}c)  z_joint={zj['objVal']} ({zj['status']})  "
              f"A/z={('%.3f' % ratio) if ratio else '-'}", flush=True)
