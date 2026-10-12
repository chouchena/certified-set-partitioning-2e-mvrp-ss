"""
ConstructivePrimal — a time-window- and capacity-feasible constructive
warm start.

Street side: reuses `feasible_construct.construct_feasible_decision`
(nearest-neighbour with periodic satellite transfers, every route ends in
a transfer). Water side: builds vessel tours over the transfer tasks by
nearest-neighbour from the CDC, splitting when a tour would exceed vessel
capacity or the CDC time window.

This is a SKELETON primal engine — its job is to prove the
orchestrate → verify → log pipeline and give later engines something to
improve. The roadmap's real constructive heuristic (the paper's
clustering warm start) is a drop-in replacement behind the same
interface.
"""
from __future__ import annotations
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import greedy26                      # the (26)-embedded constructor (2026-09-19)
from solver.engines.base import PrimalEngine


class ConstructivePrimal(PrimalEngine):
    name = "construct"

    def __init__(self, transfer_every: int = 4, singleton_vessels: bool = False,
                 hub_congestion: float = 0.0,
                 w_deadend: float = 0.0, w_urgency: float = 0.0,
                 successor_tries: int = 1, reuse: bool = False):
        self.transfer_every = transfer_every
        # REUSE CONSTRUCTOR (solver/greedy26_reuse.py), default OFF. Tried FIRST when set, and
        # the base path below is the fallback whenever it declines or fails verification.
        # Measured 2026-09-23 on all 27 n100 cells, every output through verifier3: 26 built,
        # 26 clean, median 1.33x the production final against this constructor's 2.75x, and on
        # four cells (R211 0.81x, RC208 0.84x, R208 0.98x, R209 1.00x) below the production
        # final outright. d304.
        self.reuse = reuse
        # one CDC->transfer->CDC vessel trip per transfer. Costs more
        # vessels but is always CDC-time-window feasible (no chain pushes a
        # later transfer past the deadline) — needed for the tight C-family
        # where nearest-neighbour vessel chaining violates W-TIMEFLOW. The
        # fix-and-optimize MILP re-consolidates the vessel routes.
        self.singleton_vessels = singleton_vessels
        # Prefer a less-loaded satellite when detours are comparable. 0.0 = previous behaviour.
        # See feasible_construct.construct_feasible_decision for the measurement behind it.
        self.hub_congestion = hub_congestion
        # COST AWARENESS, both 0.0 = previous behaviour bit for bit.
        # w_deadend charges penaltyCars to a candidate that strands the route; w_urgency is a
        # heuristic deadline preference and is NOT in cost units. See feasible_construct.
        self.w_deadend = w_deadend
        self.w_urgency = w_urgency
        # 1 = original nearest-only successor after a forced transfer. Higher values
        # let the route survive rather than open a car. See feasible_construct.
        self.successor_tries = successor_tries

    def construct(self, problem, rng) -> dict | None:
        # LADDER = THE ADOPTED VARIANT. `successor_tries` may be an int (one rung, the original
        # behaviour at 1) or a sequence, in which case every rung is built and the best VERIFIED
        # one is returned -- the portfolio of decision 21.
        #
        # WHY A PORTFOLIO AND NOT A SINGLE RUNG, measured 2026-09-17 at |C| = 30: a single
        # aggressive rung is frequently WORSE than blind on a given seed (R203 seed 3: blind 5
        # cars / 1956.3 against st=3's 7 cars / 2373.7, +21.3%). Only the min over the ladder is
        # monotone, which is why the grid measurement showed -7.6% at n30 while single-rung
        # st=3 loses on individual seeds. Wiring one rung as "the aware warm start" would wire
        # the variant we did NOT adopt.
        #
        # SELECTION USES selfObjVal, which is safe because it was checked against the verifier's
        # independent recomputation on 7458 of 7458 constructions with max |delta| 0.0. Feasibility
        # still comes from the verifier, never from the objective.
        tries = self.successor_tries
        if not isinstance(tries, int):
            rungs = [int(t) for t in tries]
            if len(rungs) > 1:
                return self._construct_ladder(problem, rng, rungs)
            tries = rungs[0]
        return self._construct_one(problem, rng, tries)

    def _construct_ladder(self, problem, rng, rungs):
        """Build each rung from the SAME seed and keep the best verified one."""
        seed = rng.randint(0, 2**31 - 1)
        best = None
        for t in rungs:
            sol = self._construct_one(problem, None, t, seed=seed)
            if sol is None:
                continue
            try:
                ok = bool(problem.verify(sol).ok)
            except Exception:
                ok = False
            if not ok:
                continue
            o = sol.get("selfObjVal")
            if o is not None and (best is None or o < best[0]):
                best = (o, sol)
        return best[1] if best else None

    def _construct_one(self, problem, rng, tries, seed=None) -> dict | None:
        """One greedy26 construction, VERIFIED BY verify2 BEFORE IT IS RETURNED.

        `tries` is the ladder rung and is mapped to greedy26's `transfer_every`, because greedy26
        has no successor-tries lever: its levers are where transfers are forced and which satellite
        slot is free. The old parameters (successor_tries as a successor search, hub_congestion,
        w_deadend, w_urgency) described feasible_construct, which was destroyed. They are accepted
        on __init__ so callers do not break, and they are INERT -- said here rather than left for
        someone to infer from silence.
        """
        inst = problem._vinst          # the verifier's own instance; greedy26 builds against it
        if self.reuse:
            # Verify-gated, fallback-on-anything: the base constructor below runs unchanged if
            # the reuse variant declines (C203 does) or its output does not verify.
            from solver.greedy26_reuse import construct as construct_reuse
            rs = construct_reuse(inst)
            if rs is not None:
                try:
                    vd = problem.verify(rs)
                except Exception:
                    vd = None
                if vd is not None and vd.ok:
                    if vd.recomputed_obj is not None:
                        rs["objVal"] = vd.recomputed_obj
                    rs["selfObjVal"] = rs.get("objVal")
                    rs["_construct"] = "reuse"
                    return rs
        sol = greedy26.construct(inst, transfer_every=self._rung_to_transfer_every(tries))
        if sol is None:
            return None

        # THE verify2 PASS, BEFORE THE SEED IS HANDED TO fixopt.
        #
        # A seed is not a proposal here, it is a claim: greedy26 commits (h, u) and asserts they
        # satisfy (26) and every window. This re-checks that claim with code that shares nothing
        # with the constructor, on the same instance, and DISCARDS the construction if it fails.
        # The engine therefore never starts from a point that has not been independently verified
        # on its COMMITTED timetable -- which is exactly what the destroyed chain never did.
        try:
            vd = problem.verify(sol)
        except Exception:
            return None
        if not vd.ok:
            return None
        if vd.recomputed_obj is not None:
            sol["objVal"] = vd.recomputed_obj
        sol["selfObjVal"] = sol.get("objVal")
        return sol

    @staticmethod
    def _rung_to_transfer_every(tries):
        """Ladder rung -> transfer_every. Rung 1 keeps the default 4; higher rungs let a route
        carry more customers between transfers, which opens fewer cars and books fewer satellite
        slots -- the scarce resource under (26)."""
        try:
            t = int(tries)
        except Exception:
            return 4
        return {1: 4, 2: 5, 3: 6, 5: 8}.get(t, max(2, t + 3))

    # ------------------------------------------------------------------
    def _self_objective(self, problem, arcs, transfers, hubs, yij, n_cars, n_vessel):
        """Mirror of verifier.py's objective recompute, computed by the constructor itself.

        z = nCars*penaltyCars + nVessel*penaltyVessels + c_s*street + c_w*water

        THE ONE SUBTLETY, and it is where a naive version goes wrong: a street arc leaving a
        TRANSFER customer does not cost D[i][j]. The vehicle detours through that customer's
        satellite, so it costs D[i][hub_i] + D[hub_i][j] -- verifier.py:511-516. A constructor
        that scored its own routes at D[i][j] would understate every route that carries a
        transfer, which is every route this constructor builds.

        Water arcs are measured between HUBS, not between the transfer customers that name them
        (verifier.py:517-524); the CDC maps to itself.
        """
        p = problem.raw
        D = problem.D
        CDC = problem.CDC
        hub_of = dict(zip(transfers, hubs))
        tset = set(transfers)

        street = 0.0
        for i, j in arcs:
            if i in tset:
                h = hub_of[i]
                street += D[i][h] + D[h][j]
            else:
                street += D[i][j]

        water = 0.0
        for i, j in (yij or []):
            hi_ = CDC if i == CDC else hub_of.get(i)
            hj_ = CDC if j == CDC else hub_of.get(j)
            if hi_ is None or hj_ is None:
                return None          # malformed; say nothing rather than guess
            water += D[hi_][hj_]

        return (n_cars * p.penaltyCars + n_vessel * p.penaltyVessels
                + p.travelcoststreet * street + p.travelcostwater * water)

    # ------------------------------------------------------------------
    def _trip_loads(self, problem, transfers, arcs):
        """demand feeding each transfer task (its street trip)."""
        pred = {}
        for i, j in arcs:
            pred[j] = i
        tset = set(transfers)
        loads = {}
        for t in transfers:
            load = problem.nodes[t].demand
            cur = pred.get(t, 0)
            while cur != 0 and cur not in tset:
                load += problem.nodes[cur].demand
                cur = pred.get(cur, 0)
            loads[t] = load
        return loads

    def _route_vessels(self, problem, transfers, hubs, arcs):
        """Nearest-neighbour vessel tours from the CDC over transfer tasks,
        split by vessel capacity. Returns (yij, n_vessel)."""
        D = problem.D
        CDC = problem.CDC
        cap = problem.vessel_capacity
        hub_of = {t: h for t, h in zip(transfers, hubs)}
        loads = self._trip_loads(problem.raw, transfers, arcs)

        if self.singleton_vessels:
            yij = []
            for t in transfers:
                yij.append([CDC, t]); yij.append([t, CDC])
            n_vessel = max(len(transfers), math.ceil(problem.total_demand / cap))
            return yij, n_vessel

        remaining = list(transfers)
        yij = []
        n_vessel = 0
        while remaining:
            n_vessel += 1
            tour, load = [], 0.0
            cur_hub = CDC
            while remaining:
                nxt = min(remaining, key=lambda t: D[cur_hub][hub_of[t]])
                if load + loads[nxt] > cap + 1e-9 and tour:
                    break
                tour.append(nxt)
                load += loads[nxt]
                remaining.remove(nxt)
                cur_hub = hub_of[nxt]
            # stitch CDC -> t1 -> t2 -> ... -> CDC
            prev = CDC
            for t in tour:
                yij.append([prev, t])
                prev = t
            yij.append([prev, CDC])
        n_vessel = max(n_vessel, math.ceil(problem.total_demand / cap))
        return yij, n_vessel
