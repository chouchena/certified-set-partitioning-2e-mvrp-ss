"""
FixOptPrimal — a fix-and-optimize / MIP-based large-neighbourhood-search
matheuristic (roadmap Phase 3b(ii)).

Construction is delegated to ConstructivePrimal. The improvement loop
builds the joint MILP once (via joint_model_cplex.build_joint_model) and
then repeatedly:

  1. pick a DESTROY set S of `k` customers (spatial cluster around a random
     seed customer);
  2. FIX every binary decision that does NOT touch S to its incumbent
     value  (vi, vip for retained customers; xij / y arcs whose BOTH
     endpoints are retained) — only the "on" arcs are pinned to 1, so the
     solver is free to reconnect around the removed customers;
  3. warm-start from the incumbent and re-solve the restricted MILP with a
     short node/time budget;
  4. if it returns a strictly cheaper solution, yield it (the orchestrator
     verifies it independently — rule 3); otherwise roll the fixings back
     and enlarge k.

Nothing here is trusted: the orchestrator re-verifies every yielded
solution and logs every step. The MILP restriction only ever *adds*
equality constraints to a faithful copy of the compact model, so any
solution it returns is feasible for the compact model by construction —
but we still gate it.
"""
from __future__ import annotations
import math
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from joint_model_cplex import build_joint_model, _extract_solution
from solver.engines.base import PrimalEngine
from solver.engines.construct import ConstructivePrimal

# ENGINE RELEASE. v2 EMBEDS CONSTRAINT (26); v1 did not post it at all.
#
# K's published linearization (27)-(30) introduces a continuous auxiliary f_ij that is bounded
# below twice and never costed, so nothing pushes it and the row is VACUOUS -- verified: f_ij
# appears in no objective anywhere in this repository. v1 therefore solved a model that could
# not represent (26), proposed timetables its own model permitted, and had them refused by the
# independent verifier: 35 quarantined runs, and 13 of 14 |C|=100 dumps violating (26) at their
# committed {h,u} INCLUDING every cell the pipeline called valid (d203, d216, d225).
#
# v2 posts the corrected disjunctive form (joint_model_cplex.py:254) by DEFAULT. The vacuous
# arm remains reachable with --no-posts-26 for a K-faithful reproduction; it is not the default,
# and every artifact declares which arm produced it via _posts_26.
ENGINE_VERSION = "3.0"

# K's PUBLISHED SETTINGS, KEYED BY EXHIBIT. Author, 2026-09-19: "re-key it on the exhibit".
#
# PROXIMITY IS A PROPERTY OF THE EXHIBIT, NOT OF THE SIZE. The first version of this guard was a
# {size: proximity} map, which is wrong: |C| = 50 is at 0.0 in Table 4 and at 0.1 in Fig. 5, and
# |C| = 10/20/30 are at 0.0 in Table 3 and 0.1 in Fig. 5. A size->proximity function does not
# exist in the article; it only exists once a comparator set is chosen, and choosing one is OUR
# decision, not a fact about K.
#
#   Table 3   proximity 0.0   sizes 10, 20, 30          INFERRED (see basis below)
#   Table 4   proximity 0.0   sizes 10, 20, 50          INFERRED
#   Fig. 4    sweep 0 .. 0.4  size  50                  STATED   (not a single-value comparator)
#   Fig. 5    proximity 0.1   sizes 10, 20, 30, 40, 50  STATED
#   Table 6   proximity 0.1   size  100                 STATED
#
# INFERRED vs STATED matters. Tables 3 and 4 never state a proximity; 0.0 follows from S5.4's
# "compared to the base scenario, where proximity equals to 0" and from proximity being varied
# only in S5.4. That inference is ours and is labelled so it is never quoted as K's sentence.
#
# Source: data/karademir2025/k_reference.json text_facts.proximity / proximity_basis, audited
# against the article by analysis/audit_k_alignment.py. Held here as a literal as well so the two
# must AGREE -- one source can be edited and nothing notices.
K_EXHIBITS = {
    "table3": {"sizes": (10, 20, 30), "proximity": 0.0, "basis": "INFERRED"},
    "table4": {"sizes": (10, 20, 50), "proximity": 0.0, "basis": "INFERRED"},
    "table6": {"sizes": (100,), "proximity": 0.1, "basis": "STATED"},
    "fig5": {"sizes": (10, 20, 30, 40, 50), "proximity": 0.1, "basis": "STATED"},
}

# WHICH EXHIBIT WE COMPARE AGAINST AT EACH SIZE. This is the scoping decision, written down in
# one place instead of being implied by which numbers happened to be captured. Fig. 5 is not here
# because it reports average travel time and fleet size, not the objective z -- comparing to it
# is a different comparison object, not a different proximity.
OUR_COMPARATOR = {10: "table3", 20: "table3", 30: "table3", 50: "table4", 100: "table6"}


def k_setting(size, exhibit=None):
    """(proximity, exhibit, basis) for a size. Raises if the pairing is not one K published."""
    ex = exhibit or OUR_COMPARATOR.get(size)
    if ex is None:
        raise KeyError("no comparator exhibit for |C| = %s; K's sizes are %s"
                       % (size, sorted({n for e in K_EXHIBITS.values() for n in e["sizes"]})))
    if ex not in K_EXHIBITS:
        raise KeyError("unknown exhibit %r; known: %s" % (ex, sorted(K_EXHIBITS)))
    e = K_EXHIBITS[ex]
    if size not in e["sizes"]:
        raise KeyError("K's %s does not test |C| = %s (it tests %s)" % (ex, size, list(e["sizes"])))
    return e["proximity"], ex, e["basis"]

# run-until-stall: consecutive failed kicks since the last gain after which
# diversification is deemed exhausted and the island is allowed to stop.
KICK_CAP = 5


def _sol_hash(sol):
    """structural signature: the arc set + transfer set."""
    try:
        xs = tuple(sorted(tuple(a) for a in sol.get("xij", [])))
        vs = tuple(sorted(sol.get("vi", [])))
        return str(hash((xs, vs)))
    except Exception:
        return None


def _arcset(sol):
    """Structural signature as a SET, so two solutions can be compared by how much they share.

    `_sol_hash` answers "identical?" and nothing else. A restart pool needs "how different?",
    because a pool of near-copies buys no diversification even when every hash is distinct.
    """
    try:
        return set(tuple(a) for a in (sol.get("xij") or []))
    except Exception:
        return set()


def _sol_distance(a, b):
    """Jaccard distance on arc sets: 0 = identical, 1 = no arc in common.

    Measured on the banked |C| = 30 pools, the five entries sit at mean pairwise distance
    0.67-0.90 -- but C201's closest pair is 0.295 against R211's 0.692, so diversity is NOT
    guaranteed by quality ranking plus exact-duplicate removal. It happened to hold there.
    """
    if not a or not b:
        return 1.0
    u = a | b
    return 1.0 - (len(a & b) / len(u)) if u else 0.0


def _min_distance(sol_arcs, visited):
    """How far is this candidate from the NEAREST basin already visited?

    This is a SOFT, LONG-TERM TABU on exhausted basins: it repels rather than forbids, has no
    tenure (the list only grows), and its aspiration criterion is the quality band rather than
    "override if it yields a new global best". It prevents RE-EXPLORING, not cycling -- the
    diversification memory of scatter search, not short-term tabu.

    THE LIST IS NOT SMALL, and an earlier comment here wrongly said it was "bounded by the pool
    size". It grows by 1 (the constructive start) + 2 per restart + 1 per NEW GLOBAL BEST, and the
    |C| = 20 corpus shows a median of 17 new-global-best events per run (p90 24, max 40).

    That is harmless, and it was measured rather than assumed. The worry is that `min` over a
    growing list can only shrink every candidate's score, so the criterion might saturate and
    collapse back into best-first. It does not: across a 5-entry pool the SPREAD of min-distance
    goes 0.138 at one visited entry, 0.174 at seventeen, 0.230 at forty -- it widens slightly.
    The reason is that successive global bests inside one basin sit near each other, and a min
    over near-duplicates equals the distance to that basin, so redundant entries are INERT.

    The classic tabu failure mode, everything forbidden, cannot arise either -- but because
    nothing is ever forbidden, not because the list is short.
    """
    if not visited:
        return 1.0
    return min(_sol_distance(sol_arcs, v) for v in visited)


def _elite_read(path):
    """shared reference set: sorted list of {obj, sol, hash}, best first."""
    try:
        import json
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        pool = d.get("pool") or []
        return [(float(e["obj"]), e["sol"], e.get("hash")) for e in pool]
    except Exception:
        return []


def _elite_publish(path, obj, sol, K=4):
    """insert this incumbent into the reference set (dedupe by structural hash,
    keep the K best).  compare-and-set style; a lost race self-heals next round."""
    try:
        import json, tempfile
        h = _sol_hash(sol)
        pool = _elite_read(path)
        if any(hh == h for (_, _, hh) in pool):
            # already present -- keep the cheaper obj
            pool = [(min(o, obj) if hh == h else o, s, hh) for (o, s, hh) in pool]
        else:
            pool.append((round(float(obj), 4), sol, h))
        pool.sort(key=lambda t: t[0])
        pool = pool[:K]
        d = {"pool": [{"obj": o, "sol": s, "hash": hh} for (o, s, hh) in pool]}
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, default=str)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _migrate_read(path):
    """the portfolio's shared global-best incumbent, or None."""
    try:
        import json
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("obj") is not None and d.get("sol"):
            return float(d["obj"]), d["sol"]
    except Exception:
        pass
    return None


def _migrate_write_if_better(path, obj, sol):
    """compare-and-set: publish this incumbent only if it still beats the file.
    The race window is small and non-fatal (a marginally worse global best is
    corrected on the next island's read)."""
    try:
        import json, tempfile
        cur = _migrate_read(path)
        if cur is not None and cur[0] <= obj + 1e-6:
            return False
        d = {"obj": round(float(obj), 4), "sol": sol}
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, default=str)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _parse_tries(v):
    """"1" -> 1 (unchanged behaviour). "1,3,5" -> [1,3,5], the adopted portfolio."""
    if isinstance(v, int):
        return v
    parts = [x.strip() for x in str(v).split(",") if x.strip()]
    return int(parts[0]) if len(parts) == 1 else [int(x) for x in parts]


class FixOptPrimal(PrimalEngine):
    name = "fixopt"

    def __init__(self, k0: int = 4, k_max: int | None = None,
                 iter_tl: float = 25.0, transfer_every: int = 4,
                 successor_tries: int = 1, hub_congestion: float = 0.0,
                 restart_pool: str | None = None, restart_band: float = 0.25,
                 restart_accept_frac: float = float("inf"),
                 threads: int | None = None, frontload: bool = True,
                 improve_patience_s: float | None = None,
                 route_segment: bool = False, route_merge: bool = False,
                 kick_patience_s: float | None = None, kick_frac: float = 0.35,
                 kick_frac_max: float = 0.45, kick_frac_step: float = 0.0,
                 migrate_path: str | None = None, migrate_every: int = 3,
                 stall_patience_s: float | None = None, target_lb: float | None = None,
                 stall_kicks: int = 2, stall_lb_frac: float = 0.0,
                 migrate_patience_s: float | None = None,
                 kick_k: int = 1, kick_count: int | None = None,
                 kick_from_best: bool = False, kick_thresh: float = 0.0,
                 kick_accept_frac: float = float("inf"),
                 kick_complete_start: bool = False,
                 route_drop: bool = False, route_drop_k: int = 2,
                 route_drop_patience_s: float | None = None,
                 decouple_migrate: bool = False,
                 xsat: bool = False, xsat_k: int = 10,
                 random_rotation: bool = False, stall_streak: int | None = None,
                 fleet_floor: bool = False, rotation: list | None = None,
                 construct_reuse: bool = False,
                 kick_tl_cap: float | None = None,
                 dump_kick_states: str | None = None):
        self.k0 = k0
        self.k_max = k_max
        self.iter_tl = iter_tl
        # DETERMINISTIC BUDGET (audit defect 4, 2026-09-12). The dual leg has run on CPLEX
        # deterministic ticks since the reprovenance campaigns; the primal ran on wall clock,
        # so a replicator with our seed and code_hash still could not reproduce our incumbents,
        # and background load silently changed how much search each run received -- which
        # contaminates P(win) itself, the statistic the whole primal claim rests on.
        # When det_budget is set it becomes the PRIMARY stop rule and wall clock is a safety cap.
        self.det_budget = None          # total ticks for the run
        self.iter_det = None            # ticks per sub-solve
        self.det_used = 0.0             # accumulated, read from solve_details
        self.threads = threads
        # P2: add a route-segment destroy to the rotation (frees k CONSECUTIVE
        # customers on one incumbent route -- a coherent sub-route).
        self.route_segment = route_segment
        self.route_merge = route_merge
        # UNIFORM operator choice: makes measured yield merit rather than slot.
        self.fleet_floor = fleet_floor
        # Explicit operator schedule, e.g. ['spatial_destroy','spatial_destroy',
        # 'spatial_destroy','fix_street_sync']. None keeps the production rotation.
        self.rotation_override = rotation
        self.random_rotation = random_rotation
        # Stop the seed after this many CONSECUTIVE non-improving iterations. The other
        # stall fires on idle SECONDS; this fires on the direct signal.
        self.stall_streak = stall_streak
        # P3: on a plateau of this many s, do one large random "kick" (free
        # kick_frac of customers, solve longer, ACCEPT the result even if
        # worse -> diversify) then resume. best/reported is kept separate.
        self.kick_patience_s = kick_patience_s
        self.kick_frac = kick_frac
        # adaptive kick strength: on a run of kicks that all collapse back to
        # the same basin, widen the perturbation (free more customers) so the
        # next kick is likelier to cross a ridge. Reset to kick_frac on any
        # global-best gain. Calibrated on R203 (escaped kick #5 @ 0.35) and
        # RC204 (escaped kick #11 @ 0.35) -- both would have escaped sooner
        # freeing 10-13 customers instead of 7.
        self.kick_frac_max = kick_frac_max
        self.kick_frac_step = kick_frac_step
        # conditional multi-kick (VNS shake).  On a plateau, burst up to kick_k
        # perturbations; early-stop when improvement > kick_thresh * best.
        # kick_from_best: shake the INCUMBENT, not the drifted working point.
        # kick_count: absolute free count (repair-solvability is ~|C|-independent;
        #   9 works, 16 fails) -- overrides kick_frac when set.
        # kick_accept_frac: max worsening (as frac of best) to adopt the round
        #   result as `cur` for diversification; inf = always (legacy).
        # kick_complete_start: complete + LP-verify the warm start so a failed
        #   kick can't silently jump to a much worse feasible (the accidental
        #   accept-worse the current partial start causes).
        self.kick_k = max(1, kick_k)
        self.kick_count = kick_count
        self.kick_from_best = kick_from_best
        self.kick_thresh = kick_thresh
        self.kick_accept_frac = kick_accept_frac
        self.kick_complete_start = kick_complete_start
        # route_drop (TRAJECTORY §0.3): structural route-count reduction on a plateau.
        self.route_drop = route_drop
        self.route_drop_k = route_drop_k
        self.route_drop_patience_s = route_drop_patience_s
        self._v_lb = None               # certified vehicle floor, computed once on demand
        # xfeed decoupled-migration (TRAJECTORY §0.4): migrate_in updates the working
        # point but must NOT reset the kick escalation ladder (the fixopt.py:329 bug that
        # turned xfeed into a variance amplifier). decouple_migrate keeps the ladder.
        self.decouple_migrate = decouple_migrate
        # cross-satellite ruin-recreate (xsat_operator_design.md): free the k customers
        # most attracted to a DIFFERENT satellite than their incumbent hub, so the re-solve
        # (vip free) can reassign them across satellites — the 2E-specific degree of freedom
        # the street-only destroys under-use. Size-agnostic (needs >=2 used satellites).
        self.xsat = xsat
        self.xsat_k = xsat_k
        # kick_tl_cap: cap per-kick re-solve time at this fixed value AND disable the
        # escalation (the escalating 2^n_failed TL -> up to 300s made bursts eat the
        # budget). Cheap-burst multikick: k short-capped kicks per plateau, no time sink.
        self.kick_tl_cap = kick_tl_cap
        # calibration hook: dump each kick's base incumbent for off-line replay
        self.dump_kick_states = dump_kick_states
        # P1 (audit action): mode-0 ("fix routing, re-plan transfer set +
        # water") produces the big objective drops but on the it%4 schedule
        # it first fired at t~130 s. frontload runs [fix_routing,
        # fix_street_sync, fix_routing] first, then rotates.
        self.frontload = frontload
        # cooperative portfolio: a shared JSON file holding the global-best
        # verified incumbent across islands. Every `migrate_every` iterations
        # this island reads it and, if the global best beats its own, adopts
        # it as the working point (migration IN); on a new global best it
        # publishes (migration OUT). Independent islands: migrate_path=None.
        self.migrate_path = migrate_path
        self.migrate_every = max(1, migrate_every)
        # run-until-stall: stop this island when no global-best gain (migration
        # counted) for stall_patience_s.  `deadline` becomes a hard cap, not the
        # expected stopping point.  None -> run to the deadline (legacy).
        self.stall_patience_s = stall_patience_s
        # LB exact-match early exit: if a verified incumbent reaches this valid
        # lower bound, the solution is PROVEN optimal -> stop immediately.
        self.target_lb = target_lb
        # island-specific stall: break when idle > stall_patience_s AND
        # n_failed_kicks >= stall_kicks; BUT if target_lb is set and the gap to
        # it still exceeds stall_lb_frac, the island ignores the stall and runs
        # to the deadline (far from optimal -> keep escaping).  stall_lb_frac=0
        # -> the gap guard never blocks a stall (intensifier islands).
        self.stall_kicks = max(1, stall_kicks)
        self.stall_lb_frac = stall_lb_frac
        # plateau-triggered migration: after this many idle s, pull the best
        # reference-set solution this island has NOT pulled before (rung 1 of
        # the escape ladder, before kick).  Defaults to half the kick patience.
        self.migrate_patience_s = migrate_patience_s
        # right-size the budget: stop if no verified improvement for this
        # many seconds (the C-family converged by ~250 s and ran 600).
        self.improve_patience_s = improve_patience_s
        # singleton vessel trips: always CDC-time feasible; the MILP loop
        # re-consolidates the water routes (that is exactly the slack this
        # matheuristic is meant to recover).
        # COST-AWARE CONSTRUCTION REACHES THE WARM START, but only when asked.
        #
        # Until 2026-09-17 this line hardcoded the constructor and silently dropped every
        # parameter added to it, so `successor_tries` and `hub_congestion` were inert in the only
        # production path that uses a warm start at all. A constructor that cannot reach its one
        # consumer is not built.
        #
        # THE DEFAULTS ARE THE OLD BEHAVIOUR AND THAT IS DELIBERATE. 594 banked n20 fixopt runs
        # were produced with successor_tries = 1 and hub_congestion = 0.0; changing the default
        # would make every one of them incomparable with anything run afterwards. This is opt-in.
        #
        # WHAT THE EVIDENCE SAYS ABOUT WHETHER IT WILL HELP: unknown, and not to be assumed.
        # 0 of 199 fixopt logs record a warm-start objective, so seed quality has never been
        # linked to final quality here. What IS measured is that only 3 of 594 n20 runs died on
        # an infeasible seed (C201 x2, C203 x1) against 97% that died on a budget -- so at n20
        # the seed's FEASIBILITY is the axis that matters and its OBJECTIVE is probably not
        # binding. Compare `LB improvement does not imply primal pruning benefit`, CLAUDE.md 3.
        self.successor_tries = successor_tries
        self.hub_congestion = hub_congestion
        # RESTART POOL: diverse verified constructions, pre-built by
        # analysis/build_restart_pool.py. None = the ladder is unchanged.
        self.restart_pool_path = restart_pool
        # quality band for restart selection: candidates within this fraction of the
        # pool's best objective are eligible, and among those the FARTHEST from the
        # basins already visited is chosen. 0.0 = pure best-first (quality only).
        self.restart_band = restart_band
        # how much WORSE than the current best a restart entry may be and still be adopted.
        # 0.0 = never accept worse, which makes the pool unusable; inf = accept anything.
        self.restart_accept_frac = restart_accept_frac
        self._restart_pool = []
        if restart_pool:
            try:
                import json as _j
                with open(restart_pool, encoding='utf-8') as _f:
                    self._restart_pool = (_j.load(_f) or {}).get('pool') or []
            except Exception:
                self._restart_pool = []
        self._ctor = ConstructivePrimal(reuse=construct_reuse,
                                        transfer_every=transfer_every,
                                        singleton_vessels=True,
                                        successor_tries=successor_tries,
                                        hub_congestion=hub_congestion)

    # ------------------------------------------------------------------
    def construct(self, problem, rng) -> dict | None:
        return self._ctor.construct(problem, rng)

    # ------------------------------------------------------------------
    _MODE_NAME = {0: "fix_routing", 2: "fix_street_sync"}  # else -> spatial_destroy

    def _charge(self, m):
        """Accumulate the deterministic ticks a solve consumed. CPLEX reports them on
        solve_details; if unavailable the run degrades to wall clock and says so."""
        try:
            dt = getattr(m.solve_details, "deterministic_time", None)
            if isinstance(dt, (int, float)):
                self.det_used += float(dt)
                return True
        except Exception:
            pass
        return False

    def _vehicle_floor(self, problem):
        """Certified lower bound on the street fleet for this instance, cached.

        WHY route_drop NEEDS IT (QUEUED_primal_leverage section 1). route_drop forces
        `nofCars <= nCars - 1` and solves a frozen sub-MILP. When `nCars - 1` is below the
        certified floor that sub-MILP is PROVABLY INFEASIBLE by a bound we already own, so the
        work is wasted by construction. Worse, `best["nCars"]` does not change when it fails, so
        the patience guard re-enters the identical infeasible solve every window, indefinitely.

        MEASURED NO-OP AT |C| = 20, and that is not a reason to skip it: V_LB = 1 on every n20
        cell, which is exactly the existing `nCars > 1` guard, so this changes nothing there and
        must not be sold as a general win. It BINDS at larger sizes -- C at n30 is 2; n50 is 2 for
        R/RC and 3 for C; n100 is 5 for C, 2-3 for RC and 2 for R -- which is where any n100
        primal run would otherwise spend budget proving what the arithmetic already settles.

        Falls back to 1 -- i.e. to the previous behaviour exactly -- if the bound cannot be
        computed, because a guard that crashes a search is worse than a guard that does nothing.
        """
        if self._v_lb is None:
            # `fullset_bound` wants the RAW instanceGenerator problem -- it reads .DistMatrix and
            # .nodes. Passing the SolverProblem raised AttributeError on every call, the bare
            # except swallowed it, and this returned 1 for every cell of every run, so the
            # certified floor was NEVER used in production. Found 2026-09-23 while wiring
            # --fleet-floor: C204 reports V_LB = 1 here against 5 from fullset_bound(raw).
            # The failure is now recorded rather than silently degraded -- a guard that quietly
            # becomes a no-op is worse than one that is absent, because it reads as covered.
            from crossfeed.fullset_bound import fullset_bound
            raw = getattr(problem, "raw", problem)
            try:
                self._v_lb = max(1, int(fullset_bound(raw)[1]["V_LB"]))
            except Exception as exc:
                self._v_lb = 1
                self._v_lb_failed = "%s: %s" % (type(exc).__name__, exc)
        return self._v_lb

    def _det_left(self):
        return None if self.det_budget is None else max(0.0, self.det_budget - self.det_used)

    def _set_limits(self, m, wall_budget):
        """One place that decides a sub-solve's stopping rule."""
        if self.det_budget is not None:
            m.parameters.dettimelimit = max(1.0, min(self.iter_det, self._det_left()))
        m.parameters.timelimit = wall_budget      # retained as a safety cap either way

    def improve(self, problem, incumbent: dict, rng, deadline: float, logger=None):
        """`logger`: optional runlog.RunLogger. Every improvement AND every
        non-improving iteration is logged, tagged with the neighbourhood
        that produced it (guard 3 / rule 4) so stall analysis can see which
        move is doing the work and when it stops paying off."""
        raw = problem.raw
        H = build_joint_model(raw)
        m = H.m
        Customers = list(H.Customers)
        Satellites = list(H.Satellites)
        CDC = H.CDC
        D = problem.D
        n = len(Customers)
        k_max = self.k_max or max(self.k0 + 2, n // 2)

        m.parameters.mip.tolerances.mipgap = 0.0
        m.parameters.emphasis.mip = 1  # feasibility / improve incumbents
        if self.threads is not None:
            m.parameters.threads = self.threads

        # FLEET FLOOR (N3), default OFF. nofCars is declared lb=0 in the joint model while we
        # already compute a certified floor and use it only to skip infeasible route_drop solves.
        # Added ONCE, outside the loop: it is a property of the instance, not of a neighbourhood.
        #
        # MEASURED before wiring (d294, d298), by replaying the real frozen sub-MILP with an
        # identical destroy set in both arms, 120 solves over 4 cells x k in {4,10,20,35,50}:
        #   BETTER on 13 of 60, WORSE ON 0 of 60, tied on 47, at IDENTICAL wall time.
        #   k=4 ties 12/12 -- four freed customers cannot move the fleet, so the floor is inert.
        #   k=10 and k=20 give 10 better and 0 worse of 24: the cap binds AND the fleet can move.
        # It does NOT lift our published LB -- V_LB is already a term inside fullset_bound, so
        # this buys a better incumbent per truncated solve, not a better bound (d291).
        if self.fleet_floor:
            _vlb = self._vehicle_floor(problem)
            if _vlb > 1:
                m.add_constraint(H.nofCars >= _vlb)
                if logger is not None:
                    logger.event(None, trigger="fixopt_fleet_floor",
                                 extra={"v_lb": _vlb})

        best = _canonical(incumbent, Customers, Satellites, CDC)
        best_obj = incumbent.get("objVal")
        if best_obj is None:
            return  # need a scored incumbent to compare against
        cur, cur_obj = best, best_obj      # working point (may drift worse after a kick)

        # P1: explicit schedule. P2: route_segment folded into the rotation.
        warmup = ["fix_routing", "fix_street_sync", "fix_routing"] if self.frontload else []
        rotation = ["spatial_destroy", "fix_routing", "spatial_destroy", "fix_street_sync"]
        # Comparable-cost pool for --random-rotation. xsat and route_merge are EXCLUDED on
        # cost: 22.5 s and 25.0 s per attempt against 0.02-0.09 s for these four.
        RAND_POOL = ["spatial_destroy", "fix_routing", "fix_street_sync", "route_segment"]
        n_consec_miss = 0
        if self.rotation_override:
            # MEASURED before this existed (2026-09-23, 53 n100 runlogs, 2369 iterations):
            # gain per wall-second by mode -- spatial_destroy 37.80, fix_street_sync 1.34,
            # fix_routing 0.39 -- with the two full-routing modes holding 73% of the
            # budget. The ratio holds in every run quartile (17x in Q4). A schedule is the
            # cheapest thing to test against that.
            rotation = list(self.rotation_override)
        if self.route_segment:
            rotation = ["route_segment", "fix_routing", "spatial_destroy",
                        "route_segment", "fix_street_sync"]
        if self.route_merge:
            rotation = ["route_merge", "route_segment", "spatial_destroy",
                        "route_merge", "fix_routing"]
        if self.xsat:
            # weave the cross-satellite destroy into the route_segment rotation
            # (treatment = base behaviour + xsat, so the screen isolates "add xsat").
            rotation = ["xsat", "route_segment", "fix_routing", "spatial_destroy",
                        "xsat", "route_segment", "fix_street_sync"]

        k = self.k0
        it = 0
        n_kicks = 0
        t_start = time.time()
        t_last_gain = t_start        # last GLOBAL-best improvement (for kick + right-size)
        t_last_kick = t_start
        t_last_migrate = t_start
        t_last_route_drop = t_start
        pulled_hashes = set()        # reference-set entries this island has taken
        mig_pat = (self.migrate_patience_s if self.migrate_patience_s is not None
                   else (self.kick_patience_s * 0.5 if self.kick_patience_s else None))
        restart_pulled = set()               # restart-pool entries already adopted
        # BASINS ALREADY VISITED, as arc sets. Seeded with the constructive start, and
        # extended at every restart and every new global best -- so 'diverse' is measured
        # against where this run has ACTUALLY been, not against the pool alone.
        # seeded with the CONSTRUCTIVE START: the run begins in that basin, so a pool entry
        # sitting right next to it is the least useful escape on offer however good its OV.
        restart_visited = [_arcset(best)] if self._restart_pool else []
        n_restarts = 0
        kick_frac_cur = self.kick_frac       # small cap; escapes happen at low frac
        n_failed_kicks = 0
        best_obj_at_last_kick = best_obj
        # adaptive: escalate the kick RE-SOLVE TIME, not the fraction. Escapes
        # (R203, RC204, C204, RC203) all landed at frac 0.35-0.45 freeing 7-9
        # customers; bigger kicks free more but the sub-MILP can't be solved in
        # the base window and just collapses back. So on a run of misses, give
        # each kick more solver time (x2 per miss, capped), keeping frac small.
        kick_tl_base = self.kick_tl_cap if self.kick_tl_cap else 2.0 * self.iter_tl
        kick_tl_cur = kick_tl_base

        while time.time() < deadline:
            # Deterministic budget is the PRIMARY stop rule when set; the wall deadline above
            # remains as a safety cap so a pathological solve cannot run forever.
            if self.det_budget is not None and self._det_left() <= 1.0:
                break
            budget = min(self.iter_tl, deadline - time.time())
            if budget < 3:
                break
            idle = time.time() - t_last_gain

            # run-until-stall (island-specific).
            #   * if stall_lb_frac > 0 and the gap to target_lb still EXCEEDS it
            #     -> the island is far from optimal: NEVER stall, run to the
            #     deadline (Phase A showed kick's RC203 escape lands only after
            #     many failed kicks -- cutting it there loses the result).
            #   * otherwise stall once idle > patience AND either near the LB
            #     (diminishing returns) or >= stall_kicks consecutive failed
            #     kicks (diversification exhausted).
            if self.stall_patience_s and idle > self.stall_patience_s:
                gap_ok_to_stop = (self.stall_lb_frac <= 0 or not self.target_lb
                                  or best_obj <= self.target_lb * (1 + self.stall_lb_frac))
                near_lb = (self.stall_lb_frac > 0 and self.target_lb
                           and best_obj <= self.target_lb * (1 + self.stall_lb_frac))
                enough_failed = (self.kick_patience_s is None
                                 or n_failed_kicks >= self.stall_kicks)
                if gap_ok_to_stop and (enough_failed or near_lb):
                    if logger is not None:
                        logger.event(None, trigger="fixopt_stalled",
                                     extra={"iter": it, "idle_s": round(idle, 1),
                                            "n_failed_kicks": n_failed_kicks,
                                            "near_lb": bool(near_lb),
                                            "best": round(best_obj, 2)})
                    break

            # cooperative portfolio, rung 1 of the escape ladder: on a plateau,
            # pull the best reference-set solution this island has NOT pulled
            # before (spread the islands across distinct elites instead of all
            # collapsing onto #1).  Plateau-triggered, not periodic.
            if (self.migrate_path and mig_pat is not None
                    and idle > mig_pat and time.time() - t_last_migrate > mig_pat):
                t_last_migrate = time.time()
                pool = _elite_read(self.migrate_path)
                pick = next(((o, s) for (o, s, h) in pool
                             if h not in pulled_hashes and o < best_obj - 1e-6), None)
                if pick is not None:
                    try:
                        gc = _canonical(dict(pick[1]), Customers, Satellites, CDC)
                        best, best_obj = gc, pick[0]
                        cur, cur_obj = gc, pick[0]
                        t_last_gain = time.time()
                        pulled_hashes.add(_sol_hash(pick[1]))
                        if not self.decouple_migrate:      # xfeed §0.4: keep the ladder
                            n_failed_kicks = 0
                        if logger is not None:
                            logger.incumbent(round(pick[0], 4), trigger="migrate_in",
                                             extra={"iter": it, "pool": len(pool)})
                        # yield the pulled solution so the orchestrator tracks &
                        # re-verifies it as this island's best (it isn't produced
                        # by our own solve, so it would otherwise be invisible to
                        # --dump-best / the final-best tally).
                        _mc = dict(pick[1]); _mc["objVal"] = round(pick[0], 4)
                        _mc["_mode"] = "migrate_in"; _mc["_iter"] = it
                        yield _mc
                        if self.target_lb and pick[0] <= self.target_lb + 1e-4:
                            return
                    except Exception:
                        pass

            # route_drop (TRAJECTORY §0.3): STRUCTURAL route-count reduction, tried on
            # a plateau BEFORE the diversification kick. Free the k' shortest incumbent
            # routes and force nofCars <= nCars-1, re-solve -> reach the 1-vehicle-multi-
            # trip basin by intensification. No warm start (the incumbent has nCars cars,
            # infeasible for the nCars-1 constraint); the frozen sub-MILP is small.
            rd_pat = (self.route_drop_patience_s
                      or (self.kick_patience_s if self.kick_patience_s else budget))
            if (self.route_drop and best.get("nCars") and best["nCars"] > 1
                    and idle > rd_pat and time.time() - t_last_route_drop > rd_pat
                    and it >= len(warmup) + 4 and (deadline - time.time()) > 2 * budget
                    and best["nCars"] - 1 >= self._vehicle_floor(problem)):
                t_last_route_drop = time.time()
                S = _route_drop(best, Customers, self.route_drop_k)
                cons = _freeze(m, H, best, S, Customers, Satellites, CDC)
                fleet_con = m.add_constraint(H.nofCars <= best["nCars"] - 1)
                self._set_limits(m, max(2.0 * self.iter_tl,
                                        min(4.0 * self.iter_tl,
                                            0.5 * (deadline - time.time()))))
                sol = m.solve()
                self._charge(m)
                m.remove_constraints(cons + [fleet_con])
                t_now = round(time.time() - t_start, 1)
                if sol is not None and sol.objective_value < best_obj - 1e-6:
                    cand = _extract_solution(H)
                    cand["objVal"] = round(sol.objective_value, 4)
                    cand["_mode"] = "route_drop"; cand["_iter"] = it; cand["_wall_s"] = t_now
                    best = _canonical(cand, Customers, Satellites, CDC)
                    if self._restart_pool:
                        restart_visited.append(_arcset(best))
                    best_obj = sol.objective_value
                    cur, cur_obj = best, best_obj
                    t_last_gain = time.time()
                    n_failed_kicks = 0
                    if logger is not None:
                        logger.incumbent(round(best_obj, 4), trigger="fixopt:route_drop",
                                         extra={"iter": it, "wall_s": t_now,
                                                "freed_routes": self.route_drop_k,
                                                "nCars": cand.get("nCars")})
                    if self.migrate_path:
                        _elite_publish(self.migrate_path, best_obj, cand)
                    yield cand
                    if self.target_lb and best_obj <= self.target_lb + 1e-4:
                        return
                elif logger is not None:
                    logger.event(None, trigger="fixopt_route_drop_noimprove",
                                 extra={"iter": it, "wall_s": t_now, "feasible": sol is not None})
                continue

            # ---- RESTART POOL: a rung BELOW the kick on the escape ladder -----------------
            #
            # THE AUTHOR'S PROPOSAL (2026-09-17): pre-run 20 seeds, bank the top 5 verified
            # constructions, and buffer them for use on a plateau. The measurements behind it:
            #
            #   ROOM     the median banked n20 run reaches its FINAL best at 41% of the run
            #            (p25 0.17, p75 0.72) and 0 of 594 ever converged, so the remaining
            #            ~59% is the search STUCK, not the search finishing;
            #   MATERIAL 20 seeds x the (1,3,5) ladder gives 38-58 STRUCTURALLY DISTINCT
            #            verified constructions per cell, top five spanning 4-21% in objective;
            #   FIT      the first climb costs ~41% of the budget and ~59% remains, about
            #            enough for one more full climb from a different structure.
            #
            # WHY NOT THE MIGRATION PATH, which looks like the socket and is not: migration
            # pulls a reference entry only when `o < best_obj - 1e-6`, i.e. it accepts only
            # IMPROVEMENTS. A construction is multiples worse than the incumbent within a few
            # iterations, so a construction-seeded elite pool would never be pulled at all.
            # This rung has the KICK's accept-worse semantics instead.
            #
            # `best` IS NEVER TOUCHED. Only the working point `cur` is replaced, exactly as the
            # kick does -- the reported result cannot regress because of a restart.
            if (self._restart_pool and idle > (mig_pat or self.kick_patience_s or 1e18)
                    and (deadline - time.time()) > 3 * budget):
                # SELECTION IS QUALITY *AND* DIVERSITY-FROM-WHERE-WE-HAVE-BEEN.
                #
                # Picking the next-best-by-OV would walk the pool in quality order and ignore
                # that the search has already explored some of that territory -- the pool entry
                # closest to the basin we are stuck in is the least useful escape available,
                # however good its objective.
                #
                # Candidates are first restricted to a QUALITY BAND (within `restart_band` of
                # the pool's best) so a far-but-terrible structure is not adopted merely for
                # being far; among those, the one FARTHEST from every basin visited so far wins,
                # ties broken by objective. With an empty visited set this reduces to best-first,
                # so the first restart of a run is unchanged.
                # ACCEPT-WORSE IS AN EXPLICIT, BOUNDED DECISION -- not an accident of having no
                # threshold. A restart adopts a construction that is WORSE than the incumbent by
                # construction, so some willingness to accept worse is what makes the pool usable
                # at all: at a threshold of zero the pool can never fire and the aware greedy's
                # contribution is invisible. At an unbounded threshold any entry is adopted however
                # bad, and the remaining budget is spent climbing back from nowhere.
                #
                # `restart_accept_frac` is the middle: adopt only an entry within this fraction of
                # the current best. inf reproduces the previous unbounded behaviour.
                #
                # NOTE ON WHAT A RESTART CAN EVER SHOW. `best` is only updated on improvement, so a
                # restart that does not climb back ABOVE the incumbent records nothing. Its value
                # is entirely the chance of reaching a better basin; its cost is the budget spent
                # returning. That asymmetry is why the threshold matters rather than being cosmetic.
                _cap = (best_obj * (1.0 + self.restart_accept_frac)
                        if self.restart_accept_frac != float("inf") else float("inf"))
                _avail = [e for e in self._restart_pool
                          if e.get("hash") not in restart_pulled and e["obj"] <= _cap]
                pick = None
                if _avail:
                    _p0 = min(e["obj"] for e in self._restart_pool)
                    _band = [e for e in _avail
                             if e["obj"] <= _p0 * (1.0 + self.restart_band)] or _avail
                    pick = max(_band,
                               key=lambda e: (_min_distance(_arcset(e["sol"]), restart_visited),
                                              -e["obj"]))
                if pick is not None:
                    restart_pulled.add(pick.get("hash"))
                    # TABU THE BASIN WE ARE LEAVING, which is the one that is actually
                    # EXHAUSTED. Entering a basin is not the same as exhausting it: a basin
                    # abandoned early is still unexplored, while the basin we plateaued in has
                    # been worked and produced nothing further. `cur` is recorded as well as
                    # `best` because a kick may have drifted the working point away from the
                    # incumbent, so the exhausted region is not exactly `best`.
                    restart_visited.append(_arcset(cur))
                    try:
                        rc = _canonical(dict(pick["sol"]), Customers, Satellites, CDC)
                        cur, cur_obj = rc, float(pick["obj"])
                        restart_visited.append(_arcset(pick["sol"]))
                        n_restarts += 1
                        lg.event("restart_pool",
                                 extra={"obj": cur_obj, "best_obj": best_obj,
                                        "min_dist_to_visited": round(
                                            _min_distance(_arcset(pick["sol"]),
                                                          restart_visited[:-1]), 4),
                                        "n_restarts": n_restarts,
                                        "remaining": len(self._restart_pool) - len(restart_pulled)})
                        t_last_gain = time.time()      # give the new structure a fair plateau
                    except Exception as e:
                        lg.event("restart_pool_failed", extra={"err": str(e)[:120]})

            # P3: conditional multi-kick on plateau (VNS shake).  Burst up to
            # kick_k perturbations FROM `best` (or `cur` if kick_from_best off),
            # early-stop when improvement > kick_thresh*best; adopt the round
            # best as `cur` for diversification (bounded by kick_accept_frac).
            if (self.kick_patience_s is not None and idle > self.kick_patience_s
                    and time.time() - t_last_kick > self.kick_patience_s
                    and it >= len(warmup) + 4 and (deadline - time.time()) > 3 * budget
                    and n_failed_kicks < max(KICK_CAP, self.stall_kicks + 2)):
                if best_obj < best_obj_at_last_kick - 1e-6:
                    kick_frac_cur = self.kick_frac
                    kick_tl_cur = kick_tl_base
                    n_failed_kicks = 0
                best_obj_at_last_kick = best_obj
                t_last_kick = time.time()
                base_pt = best if self.kick_from_best else cur
                cnt = self.kick_count or max(2, int(round(kick_frac_cur * len(Customers))))
                cnt = min(cnt, max(2, (len(Customers) + 1) // 2))  # floor at tiny n
                if self.dump_kick_states:
                    _dump_kick_state(self.dump_kick_states, base_pt, best_obj,
                                     round(time.time() - t_start, 1), it, cnt)
                round_cand, round_obj = None, float("inf")
                for kk in range(self.kick_k):
                    n_kicks += 1
                    S = set(rng.sample(list(Customers), cnt))
                    cons = _freeze(m, H, base_pt, S, Customers, Satellites, CDC)
                    _warm_start(m, H, base_pt, Customers, Satellites, CDC,
                                complete=self.kick_complete_start)
                    if self.kick_tl_cap:      # cheap-burst: fixed short TL, no floor, no escalation
                        self._set_limits(m, max(1.0, min(self.kick_tl_cap, 0.5 * (deadline - time.time()))))
                    else:
                        _tl = min(kick_tl_cur * (1.0 + 0.5 * kk),
                                  12.0 * self.iter_tl, 0.5 * (deadline - time.time()))
                        self._set_limits(m, max(2.0 * self.iter_tl, _tl))
                    sol = m.solve()
                    self._charge(m)
                    m.remove_constraints(cons)
                    if sol is not None and sol.objective_value < round_obj:
                        round_obj = sol.objective_value
                        round_cand = _extract_solution(H)
                        round_cand["objVal"] = round(round_obj, 4)
                    if sol is not None and sol.objective_value < best_obj - self.kick_thresh * best_obj - 1e-6:
                        break  # "enough" success -> stop the burst
                t_now = round(time.time() - t_start, 1)
                if round_cand is not None:
                    rc = _canonical(round_cand, Customers, Satellites, CDC)
                    if round_obj < best_obj - 1e-6:
                        best, best_obj = rc, round_obj
                        cur, cur_obj = rc, round_obj
                        t_last_gain = time.time()
                        kick_tl_cur = kick_tl_base
                        n_failed_kicks = 0
                        round_cand["_mode"] = "kick"; round_cand["_iter"] = it
                        round_cand["_wall_s"] = t_now
                        if logger is not None:
                            logger.incumbent(round(round_obj, 4), trigger="fixopt:kick",
                                             extra={"iter": it, "wall_s": t_now, "free": cnt,
                                                    "kick_k": self.kick_k})
                        if self.migrate_path:
                            _elite_publish(self.migrate_path, round_obj, round_cand)
                        yield round_cand
                        if self.target_lb and round_obj <= self.target_lb + 1e-4:
                            if logger is not None:
                                logger.event(None, trigger="fixopt_proven_optimal",
                                             extra={"obj": round(round_obj, 4), "lb": self.target_lb})
                            return
                    else:
                        # failed round: adopt as cur ONLY if bounded worsening
                        if round_obj <= best_obj * (1.0 + self.kick_accept_frac):
                            cur, cur_obj = rc, round_obj
                        else:
                            cur, cur_obj = best, best_obj  # don't drift into a bad point
                        n_failed_kicks += 1
                        kick_tl_cur = (kick_tl_base if self.kick_tl_cap
                                       else kick_tl_base * (2 ** min(n_failed_kicks, 4)))
                        if logger is not None:
                            logger.event(None, trigger="fixopt_kick",
                                         extra={"iter": it, "wall_s": t_now,
                                                "round_obj": round(round_obj, 2),
                                                "delta_vs_best": round(round_obj - best_obj, 2),
                                                "n_failed": n_failed_kicks,
                                                "adopted_cur": round_obj <= best_obj * (1.0 + self.kick_accept_frac),
                                                "next_kick_tl": round(min(kick_tl_cur, 12.0 * self.iter_tl), 1)})
                continue

            # P1: right-size the budget (only if not kicking)
            if (self.improve_patience_s is not None and idle > self.improve_patience_s
                    and self.kick_patience_s is None and it >= len(warmup) + 4):
                if logger is not None:
                    logger.event(None, trigger="fixopt_budget_rightsized",
                                 extra={"iter": it, "idle_s": round(idle, 1)})
                break

            it += 1
            if it <= len(warmup):
                mode_name = warmup[it - 1]
            elif self.random_rotation:
                mode_name = rng.choice(RAND_POOL)
            else:
                mode_name = rotation[(it - 1 - len(warmup)) % len(rotation)]
            xsat_old = None            # snapshot of freed customers' satellites, for mechanism logging
            if mode_name == "fix_routing":
                cons = _freeze_routing_only(m, H, cur)
            elif mode_name == "fix_street_sync":
                cons = _freeze_street_only(m, H, cur, Customers, Satellites, CDC)
            elif mode_name == "route_segment":
                S = _route_segment(rng, cur, Customers, k)
                cons = _freeze(m, H, cur, S, Customers, Satellites, CDC)
            elif mode_name == "route_merge":
                S = _route_merge(rng, cur, Customers, 2)
                cons = _freeze(m, H, cur, S, Customers, Satellites, CDC)
            elif mode_name == "xsat":
                S = _xsat(rng, cur, Customers, D, Satellites, self.xsat_k)
                if S is None:                      # <2 used satellites -> fall back
                    S = _cluster(rng, Customers, D, k)
                else:
                    xsat_old = {c: cur["hub"].get(c) for c in S}   # for mechanism logging
                cons = _freeze(m, H, cur, S, Customers, Satellites, CDC)
            else:
                S = _cluster(rng, Customers, D, k)
                cons = _freeze(m, H, cur, S, Customers, Satellites, CDC)
            _warm_start(m, H, cur, Customers, Satellites, CDC)
            self._set_limits(m, budget)

            sol = m.solve()
            self._charge(m)
            improved_cur = improved_best = False
            t_now = round(time.time() - t_start, 1)
            # xsat MECHANISM logging: did the re-solve actually reassign the freed
            # customers across satellites? (freed vs how many changed hub) -> tells us
            # whether xsat does its intended satellite-reassignment job, not just its objective.
            if xsat_old is not None and logger is not None:
                reassigned, new_obj = None, None
                if sol is not None:
                    _nh = _canonical(_extract_solution(H), Customers, Satellites, CDC)["hub"]
                    reassigned = sum(1 for c in xsat_old if _nh.get(c) != xsat_old.get(c))
                    new_obj = round(sol.objective_value, 4)
                logger.event(None, trigger="fixopt_xsat_mechanism",
                             extra={"iter": it, "wall_s": t_now, "freed": len(xsat_old),
                                    "reassigned": reassigned, "new_obj": new_obj,
                                    "cur_obj": round(cur_obj, 4)})
            if sol is not None:
                obj = sol.objective_value
                if obj < cur_obj - 1e-6:
                    cand = _extract_solution(H)
                    cand["objVal"] = round(obj, 4)
                    cand["_mode"] = mode_name; cand["_iter"] = it; cand["_wall_s"] = t_now
                    cur = _canonical(cand, Customers, Satellites, CDC); cur_obj = obj
                    improved_cur = True
                    if obj < best_obj - 1e-6:
                        best, best_obj = cur, obj
                        improved_best = True
                        t_last_gain = time.time()
                        if logger is not None:
                            logger.incumbent(round(obj, 4), trigger=f"fixopt:{mode_name}",
                                             extra={"iter": it, "k": k, "wall_s": t_now,
                                                    # FLEET TRAJECTORY: without these the
                                                    # 37->10 car cut is visible only as
                                                    # start-vs-end, so WHEN it happens --
                                                    # and how many iterations a better
                                                    # construction would free -- is not
                                                    # measurable.
                                                    "nCars": best.get("nCars"),
                                                    "nVessel": best.get("nVessel")})
                        if self.migrate_path:
                            _elite_publish(self.migrate_path, obj, cand)
                        yield cand
                        if self.target_lb and obj <= self.target_lb + 1e-4:
                            if logger is not None:
                                logger.event(None, trigger="fixopt_proven_optimal",
                                             extra={"obj": round(obj, 4), "lb": self.target_lb})
                            m.remove_constraints(cons)
                            return
                    elif logger is not None:
                        # a working-point improvement that isn't a global best
                        # (drifted after a kick, or a lateral basin) -- still an
                        # "improv", logged so the trace is complete
                        logger.event(None, trigger=f"fixopt_cur_improve:{mode_name}",
                                     extra={"iter": it, "k": k, "wall_s": t_now,
                                            "cur_obj": round(obj, 4),
                                            "delta_vs_best": round(obj - best_obj, 2)})
            if logger is not None and not improved_best:
                logger.event(None, trigger=f"fixopt_noimprove:{mode_name}",
                             extra={"iter": it, "k": k, "wall_s": t_now,
                                    "improved_cur": improved_cur,
                                    "sub_status": (sol is not None),
                                    "nCars": best.get("nCars")})

            m.remove_constraints(cons)
            k = (max(self.k0, k - 1) if improved_cur
                 else self.k0 + ((k - self.k0 + 1) % (k_max - self.k0 + 1)))

            # STREAK-BASED STALL: end the seed once the run is demonstrably dead rather
            # than merely quiet. Counts the same event the noimprove trace records.
            n_consec_miss = 0 if improved_best else n_consec_miss + 1
            if self.stall_streak and n_consec_miss >= self.stall_streak:
                if logger is not None:
                    logger.event(None, trigger='fixopt_stalled_streak',
                                 extra={'iter': it, 'k': k,
                                        'n_consec_miss': n_consec_miss,
                                        'best': round(best_obj, 2)})
                break


# ----------------------------------------------------------------------
def _canonical(sol, Customers, Satellites, CDC):
    """Normalise a solution dict into the sets/maps the freezer needs."""
    xset = set((i, j) for i, j in sol["xij"])
    vset = set(sol["vi"])
    hub = {}
    hubs = sol.get("hubs") or []
    for idx, i in enumerate(sol["vi"]):
        if idx < len(hubs):
            hub[i] = hubs[idx]
    yset = set((i, j) for i, j in sol.get("yij", []))
    return {"xset": xset, "vset": vset, "hub": hub, "yset": yset,
            "nCars": sol.get("nCars"), "nVessel": sol.get("nVessel")}


def _cluster(rng, Customers, D, k):
    """k customers: a random seed plus its k-1 nearest neighbours."""
    k = min(k, len(Customers))
    seed = rng.choice(Customers)
    others = sorted((c for c in Customers if c != seed), key=lambda c: D[seed][c])
    return set([seed] + others[:k - 1])


def _routes_from(best, Customers):
    """Reconstruct customer sequences from the incumbent's street arcs
    (arcs are [i,j]; depot is 0). Returns a list of routes, each a list of
    customer nodes in visit order. Robust to a partially-broken arc set."""
    succ = {}
    cset = set(Customers)
    for (i, j) in best["xset"]:
        succ.setdefault(i, []).append(j)
    routes = []
    for start in succ.get(0, []):
        route, cur, seen = [], start, set()
        while cur in cset and cur not in seen:
            route.append(cur); seen.add(cur)
            nxts = [x for x in succ.get(cur, []) if x != cur]
            cur = nxts[0] if nxts else 0
        if route:
            routes.append(route)
    return routes


def _route_drop(best, Customers, k_routes=2):
    """Free every customer on the k_routes SHORTEST incumbent routes (fewest
    customers). Paired with a forced fleet reduction (nofCars <= nCars-1), the
    sub-MILP must redistribute those customers into the retained routes as extra
    (multi-)trips -- the structural route-count-reduction move (TRAJECTORY §0.3):
    reach the 1-vehicle-multi-trip basin by INTENSIFICATION, not diversification
    luck. Deterministic (no rng) so the move is reproducible."""
    routes = [r for r in _routes_from(best, Customers) if r]
    if len(routes) <= 1:
        return set(Customers)
    routes.sort(key=len)                     # shortest (fewest customers) first
    kk = min(max(1, k_routes), len(routes) - 1)
    return set(c for r in routes[:kk] for c in r)


def _route_merge(rng, best, Customers, n_routes=2):
    """Free EVERY customer on `n_routes` random incumbent routes -- a genuine
    inter-route restructuring window (route_segment only frees a sub-path of
    ONE route, so it can never move a customer between routes or change the
    route count). Diagnosed as the RC203 blocker: fixopt gets the fleet right
    (2 cars / 2 vessels) but its local moves can't reach a better routing."""
    routes = _routes_from(best, Customers)
    if len(routes) <= n_routes:
        return set(Customers)
    pick = rng.sample(routes, n_routes)
    return set(c for r in pick for c in r)


def _route_segment(rng, best, Customers, k):
    """P2: free k CONSECUTIVE customers on one incumbent route — a coherent
    sub-route, unlike the spatial cluster (which the geo_dispersion signal
    said is not the lever for RC). Falls back to a random-k set if the
    routes can't be reconstructed."""
    routes = [r for r in _routes_from(best, Customers) if r]
    if not routes:
        return set(rng.sample(list(Customers), min(k, len(Customers))))
    r = rng.choice(routes)
    if len(r) <= k:
        return set(r)
    s = rng.randint(0, len(r) - k)
    return set(r[s:s + k])


def _xsat(rng, best, Customers, D, Satellites, k):
    """Cross-satellite ruin-recreate, COHERENT-BOUNDARY-CLUSTER redesign (2026-09-07).
    The scattered distance-greedy version reassigned 0% (measured): freeing single
    customers, the MILP keeps each on its satellite (TW/water/congestion couplings lock
    it). This version instead frees a COHERENT boundary region of ONE satellite PAIR,
    from BOTH sides at once, so the re-solve can SWAP customers between the two
    satellites (a balanced swap is feasible where a one-way move isn't).
      1. group customers by incumbent satellite; need >=2 used.
      2. pick the CLOSEST satellite pair (p,q) by min cross customer->other-satellite
         distance (rng tie-break among the 2 closest pairs for seed diversity).
      3. free the k/2 customers of p nearest q + the k/2 of q nearest p = the boundary
         region on both sides. Freed together (vip free in _freeze) -> MILP can swap.
    Returns None (caller falls back) if <2 used satellites or D unusable."""
    hub = best.get("hub") or {}
    groups = {}
    for c in Customers:
        h = hub.get(c)
        if h is not None:
            groups.setdefault(h, []).append(c)
    used = [s for s in groups if groups[s]]
    if len(used) < 2:
        return None
    pairs = []
    for i in range(len(used)):
        for j in range(i + 1, len(used)):
            p, q = used[i], used[j]
            try:
                score = min([D[c][q] for c in groups[p]] + [D[c][p] for c in groups[q]])
            except (KeyError, IndexError, TypeError):
                continue
            pairs.append((score, p, q))
    if not pairs:
        return None
    pairs.sort(key=lambda t: t[0])
    pick = pairs[1] if (len(pairs) > 1 and rng.random() < 0.5) else pairs[0]
    p, q = pick[1], pick[2]
    kk = max(2, min(k, (len(Customers) + 1) // 2))
    half = max(1, kk // 2)
    try:
        p_side = sorted(groups[p], key=lambda c: D[c][q])[:half]
        q_side = sorted(groups[q], key=lambda c: D[c][p])[:half]
    except (KeyError, IndexError, TypeError):
        return None
    S = set(p_side) | set(q_side)
    return S if len(S) >= 2 else None


def _kick(rng, Customers, frac):
    """P3: a large random destroy to escape a plateau."""
    m = max(2, int(round(frac * len(Customers))))
    return set(rng.sample(list(Customers), min(m, len(Customers))))


def _dump_kick_state(outdir, base_pt, best_obj, wall_s, it, cnt):
    """Persist the incumbent a kick is about to perturb, in the sol-dict shape _canonical
    consumes, so analysis/kick_bench.py can replay this exact subproblem off-line."""
    import json as _json, os as _os, time as _time
    _os.makedirs(outdir, exist_ok=True)
    vi = sorted(base_pt["vset"])
    hub = base_pt.get("hub") or {}
    rec = {"xij": [list(t) for t in sorted(base_pt["xset"])],
           "vi": list(vi),
           "hubs": [hub.get(i) for i in vi],
           "yij": [list(t) for t in sorted(base_pt.get("yset") or [])],
           "objVal": best_obj, "wall_s": wall_s, "iter": it, "kick_count": cnt}
    fn = _os.path.join(outdir, f"kickstate_{int(wall_s):06d}_{it}_{int(_time.time()*1000)%100000}.json")
    with open(fn, "w", encoding="utf-8") as fh:
        _json.dump(rec, fh)

def _freeze(m, H, best, S, Customers, Satellites, CDC):
    """Pin every binary decision not touching S to its incumbent value.
    Returns the list of added constraints so they can be removed."""
    cons = []
    xset, vset, hub, yset = best["xset"], best["vset"], best["hub"], best["yset"]

    for i in Customers:
        if i in S:
            continue
        # transfer decision of a retained customer (hub left free so the
        # satellite choice can still adapt around the destroyed region)
        cons.append(m.add_constraint(H.vi[i] == (1 if i in vset else 0)))

    # street arcs: pin only INTERIOR "on" arcs (both endpoints retained
    # customers). Depot-incident arcs stay free so the fleet size can flex
    # every iteration — pinning them was locking nofCars at a suboptimal
    # value.
    for (i, j) in H.arcList:
        if (i, j) in xset and i != 0 and j != 0 and i not in S and j not in S:
            cons.append(m.add_constraint(H.xij[i, j] == 1))

    # water arcs: pin only interior "on" arcs; CDC-incident arcs stay free
    # so the vessel count can flex.
    for (i, j), var in H.y.items():
        if (i, j) in yset and i != CDC and j != CDC and i not in S and j not in S:
            cons.append(m.add_constraint(var == 1))

    return cons


def _freeze_routing_only(m, H, best):
    """Fix only the street routing arcs xij. The transfer set (vi, vip),
    the load/time variables and the entire water side stay free."""
    xset = best["xset"]
    return [m.add_constraint(H.xij[i, j] == (1 if (i, j) in xset else 0))
            for (i, j) in H.arcList]


def _freeze_street_only(m, H, best, Customers, Satellites, CDC):
    """Fix the entire street + sync decision (vi, vip, xij) from the
    incumbent; leave the whole water side (y, nofVessels) free. CPLEX then
    returns the optimal vessel routing for this street solution."""
    cons = []
    xset, vset, hub = best["xset"], best["vset"], best["hub"]
    for i in Customers:
        cons.append(m.add_constraint(H.vi[i] == (1 if i in vset else 0)))
        for p in Satellites:
            want = 1 if (i in vset and hub.get(i) == p) else 0
            cons.append(m.add_constraint(H.vip[i, p] == want))
    for (i, j) in H.arcList:
        cons.append(m.add_constraint(H.xij[i, j] == (1 if (i, j) in xset else 0)))
    return cons


def _warm_start(m, H, best, Customers, Satellites, CDC, complete=False):
    try:
        m.clear_mip_starts()
    except Exception:
        pass
    ss = m.new_solution()
    xset, vset, hub, yset = best["xset"], best["vset"], best["hub"], best["yset"]
    for i in Customers:
        ss.add_var_value(H.vi[i], 1 if i in vset else 0)
        for p in Satellites:
            ss.add_var_value(H.vip[i, p], 1 if (hub.get(i) == p) else 0)
    for (i, j) in H.arcList:
        ss.add_var_value(H.xij[i, j], 1 if (i, j) in xset else 0)
    for (i, j), var in H.y.items():
        ss.add_var_value(var, 1 if (i, j) in yset else 0)
    if best.get("nCars") is not None:
        ss.add_var_value(H.nofCars, best["nCars"])
    if best.get("nVessel") is not None:
        ss.add_var_value(H.nofVessels, best["nVessel"])
    try:
        if complete:
            # complete the continuous vars + LP-verify with the integers fixed,
            # so a valid incumbent is guaranteed present at t=0 and a failed
            # kick can't silently return a much worse feasible.
            m.add_mip_start(ss, effort_level=2, complete_vars=True)
        else:
            m.add_mip_start(ss)
    except Exception:
        try:
            m.add_mip_start(ss)
        except Exception:
            pass


if __name__ == "__main__":
    import argparse
    import random
    from solver.config import InstanceSpec
    from solver.problem import SolverProblem

    ap = argparse.ArgumentParser()
    ap.add_argument("--proximity", type=float, default=None,
                    help="override the proximity K's table uses for this size. Omit for a "
                         "K-comparable run; pass a value ONLY for a deliberate sensitivity sweep.")
    ap.add_argument("--k-exhibit", default="",
                    help="which K exhibit this run is compared against (table3/table4/table6/"
                         "fig5). Default: the comparator for this size. Proximity is a property "
                         "of the exhibit, not of the size.")
    ap.add_argument("--proximity-ack", default="",
                    help="reason for deliberately running off K's published proximity. Required "
                         "by --proximity when the value does not match K's table for this size; "
                         "the reason is printed and stamped into the artifact.")
    ap.add_argument("--ignore-quarantine", action="store_true",
                    help="start even though an untriaged verifier/solver contradiction stands. "
                         "ONLY for triage runs diagnosing that contradiction.")
    ap.add_argument("--instance", default="C201")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--iter-tl", type=float, default=25.0)
    ap.add_argument("--det-budget", type=float, default=None,
                    help="TOTAL CPLEX deterministic ticks for the run. When set this is the "
                         "primary stop rule and --budget becomes a wall-clock SAFETY CAP. "
                         "Required for any result a third party must reproduce: wall-clock "
                         "budgets give a different amount of search on different hardware or "
                         "under load (audit defect 4, 2026-09-12).")
    ap.add_argument("--iter-det", type=float, default=None,
                    help="ticks per sub-solve; default det_budget/40, mirroring iter_tl:budget")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--no-frontload", action="store_true", help="legacy it%%4 schedule (for A/B)")
    ap.add_argument("--improve-patience", type=float, default=None,
                    help="stop if no verified improvement for this many s (right-size the budget)")
    ap.add_argument("--route-segment", action="store_true", help="P2: route-segment destroy in the rotation")
    ap.add_argument("--k0", type=int, default=4,
                    help="initial destroy size. k CYCLES k0..k_max on failure, so setting "
                         "--k0 == --k-max PINS it and removes the cycling confound.")
    ap.add_argument("--k-max", type=int, default=None,
                    help="max destroy size; default max(k0+2, n//2).")
    ap.add_argument("--stall-streak", type=int, default=None,
                    help="end the seed after this many CONSECUTIVE non-improving "
                         "iterations. Direct signal, against the idle-seconds proxy.")
    ap.add_argument("--random-rotation", action="store_true",
                    help="pick the destroy operator UNIFORMLY at random each iteration, "
                         "so measured yield is merit rather than scheduling slot.")
    ap.add_argument("--rotation", type=str, default=None,
                    help="comma-separated operator schedule replacing the production "
                         "rotation, e.g. spatial_destroy,spatial_destroy,fix_street_sync")
    ap.add_argument("--construct-reuse", action="store_true",
                    help="start from the reuse constructor (greedy26_reuse), verify-gated with "
                         "fallback to the base constructor. Median 1.33x final vs 2.75x (d304).")
    ap.add_argument("--fleet-floor", action="store_true",
                    help="impose nofCars >= certified V_LB on the sub-MILP. "
                         "Measured better on 13 of 60 paired sub-solves and worse "
                         "on 0, at identical wall time (d298).")
    ap.add_argument("--route-merge", action="store_true",
                    help="free all customers on 2 random routes (inter-route restructuring)")
    ap.add_argument("--kick-patience", type=float, default=None, help="P3: kick after this many s on a plateau")
    ap.add_argument("--kick-frac", type=float, default=0.35, help="P3: base perturbation fraction")
    ap.add_argument("--kick-frac-max", type=float, default=0.45,
                    help="P3: cap for frac escalation (escapes happen at low frac; keep small)")
    ap.add_argument("--kick-frac-step", type=float, default=0.0,
                    help="P3: += this per consecutive failed kick (default 0: escalate re-solve TIME instead)")
    ap.add_argument("--variant", default="", help="label for the run id")
    # ---- WARM-START VARIANT (2026-09-17) --------------------------------------------------
    # Every banked fixopt run to date used successor_tries=1 and hub_congestion=0.0, because
    # this module hardcoded the constructor and silently dropped both. These expose the
    # cost-aware warm start so a run can be launched with it AND so the artifact records which
    # start produced it -- without that, two runs with different seeds are indistinguishable
    # from two runs with different warm starts.
    #
    # DEFAULTS ARE THE OLD BEHAVIOUR ON PURPOSE. 594 banked n20 runs were produced under them.
    #
    # WHETHER THIS HELPS THE FINAL OV IS AN OPEN QUESTION, pre-registered in
    # validation/PREREG_WS_blind_vs_aware.md and NOT to be assumed in either direction. The
    # argument that it should: 0 of 594 banked n20 runs CONVERGED and 96% were cut off by a
    # budget, and under budget limitation where a search starts bounds how far it gets.
    ap.add_argument("--successor-tries", default="1",
                    help="int, or a comma list to run the LADDER and keep the best VERIFIED "
                         "construction (e.g. 1,3,5 = the adopted portfolio). A single "
                         "aggressive rung is frequently WORSE than blind on a given seed; only "
                         "the min over the ladder is monotone.")
    ap.add_argument("--_unused_successor_tries", type=int, default=1,
                    help="WS variant: after a forced transfer, try this many successors "
                         "nearest-first instead of committing to the single nearest (1 = the "
                         "original blind rule, and what every banked run used)")
    ap.add_argument("--restart-pool", default=None,
                    help="JSON of diverse verified constructions (analysis/build_restart_pool.py). "
                         "On a plateau, adopt an unused one as the working point -- a rung "
                         "BELOW the kick. `best` is never replaced, so results cannot regress.")
    ap.add_argument("--restart-accept-frac", type=float, default=float("inf"),
                    help="adopt a restart entry only if within this fraction of the current "
                         "best. 0.0 = never accept worse (the pool can then NEVER fire); "
                         "inf = accept anything.")
    ap.add_argument("--restart-band", type=float, default=0.25,
                    help="restart candidates within this fraction of the pool best are "
                         "eligible; among them the FARTHEST from visited basins wins. "
                         "0.0 = quality-only best-first.")
    ap.add_argument("--hub-congestion", type=float, default=0.0,
                    help="WS variant: prefer a less-loaded satellite when detours are "
                         "comparable (0.0 = original behaviour)")
    ap.add_argument("--posts-26", dest="posts_26", action="store_true", default=True,
                    help="v2 DEFAULT: post the corrected disjunctive constraint (26) so the "
                         "model cannot represent a (26)-violating timetable")
    ap.add_argument("--no-posts-26", dest="posts_26", action="store_false",
                    help="v1/K-faithful: post only the vacuous (27)-(30) linearization. The "
                         "engine can then emit incumbents the independent verifier refuses")
    ap.add_argument("--valid-bigm", dest="valid_bigm", action="store_true", default=True,
                    help="v3 DEFAULT (d243): size the big-Ms in (14) and (22) from the variable "
                         "domains they actually range over. K derive both from the CUSTOMER's "
                         "time window although both rows involve u, which lives in the CDC "
                         "window, so their constants are UNDERSIZED and the model is OVER-TIGHT")
    ap.add_argument("--no-valid-bigm", dest="valid_bigm", action="store_false",
                    help="K-faithful: keep their undersized constants. The model then excludes "
                         "feasible routings -- measured on 7 of 200 random small instances by "
                         "analysis/arbiter.py -- so objectives may be inflated")
    ap.add_argument("--warm-json", default=None,
                    help="seed_from_core JSON: use its verified block-A-core solution as the "
                         "fixopt start (keep the better of it and the constructive seed)")
    ap.add_argument("--dump-best", default=None,
                    help="write the final best verified solution dict to this JSON path "
                         "(for independent re-verification by the portfolio driver)")
    ap.add_argument("--migrate-path", default=None,
                    help="cooperative portfolio: shared global-best incumbent JSON "
                         "(this island reads/publishes it)")
    ap.add_argument("--migrate-every", type=int, default=3)
    ap.add_argument("--stall-patience", type=float, default=None,
                    help="run-until-stall: stop after this many s with no global-best "
                         "gain and kicks exhausted (--budget becomes a hard cap)")
    ap.add_argument("--target-lb", type=float, default=None,
                    help="valid LB; a verified incumbent reaching it is proven optimal -> stop")
    ap.add_argument("--stall-kicks", type=int, default=2,
                    help="consecutive failed kicks required before a stall is allowed")
    ap.add_argument("--stall-lb-frac", type=float, default=0.0,
                    help="if gap to --target-lb still exceeds this, ignore the stall and "
                         "run to the deadline (0 = gap guard off)")
    ap.add_argument("--migrate-patience", type=float, default=None,
                    help="plateau-triggered reference-set pull after this many idle s "
                         "(default: half the kick patience)")
    ap.add_argument("--kick-k", type=int, default=1,
                    help="conditional multi-kick: kicks per burst (1 = legacy single kick)")
    ap.add_argument("--kick-count", type=int, default=None,
                    help="absolute free count per kick (overrides --kick-frac)")
    ap.add_argument("--kick-from-best", action="store_true",
                    help="shake the incumbent, not the drifted working point")
    ap.add_argument("--kick-thresh", type=float, default=0.0,
                    help="min improvement (frac of best) to early-stop the burst")
    ap.add_argument("--kick-accept-frac", type=float, default=float("inf"),
                    help="max worsening (frac of best) to adopt the round result as cur")
    ap.add_argument("--kick-complete-start", action="store_true",
                    help="complete+LP-verify the kick warm start (no accidental accept-worse)")
    ap.add_argument("--route-drop", action="store_true",
                    help="route-count-reduction operator: free k' shortest routes + nofCars<=nCars-1")
    ap.add_argument("--route-drop-k", type=int, default=1,
                    help="number of shortest incumbent routes to free per route_drop")
    ap.add_argument("--decouple-migrate", action="store_true",
                    help="xfeed decoupled-migration: migrate resets working point but NOT the kick ladder")
    ap.add_argument("--xsat", action="store_true",
                    help="cross-satellite ruin-recreate: weave a satellite-reassignment destroy into the rotation")
    ap.add_argument("--xsat-k", type=int, default=10,
                    help="customers freed per xsat move (boundary/misassigned candidates)")
    ap.add_argument("--kick-tl-cap", type=float, default=None,
                    help="cheap-burst multikick: fixed per-kick re-solve TL (s), disables the escalating "
                         "2^n_failed time-limit that made bursts eat the budget")
    ap.add_argument("--dump-kick-states", default=None,
                    help="calibration: directory to dump each kick's base incumbent into "
                         "(off-line kick-bench replay); no effect on search behaviour")
    a = ap.parse_args()

    # ---- HALT ON A VERIFIER/SOLVER CONTRADICTION -------------------------------------------
    # AUTHOR RULE, 2026-09-18: "I want to stop all runs after any quarantine except if because
    # no incumbent found by main solver ie. if verifier contradict main solver validity claim."
    #
    # THIS LIVES HERE, IN THE ENGINE, AND NOT IN A CHECKER SCRIPT, BECAUSE THE AUTHOR ASKED THE
    # RIGHT QUESTION: "what will enforce the enforcement". runs/invalid/INDEX.md has said
    # "**BLOCKING**" since it was created and 22 runs were quarantined on 13-14 September with
    # no reaction for two weeks, because nothing read it (d206). A guard script, a release gate
    # and a status banner all have the same defect: they must be REMEMBERED. The only point that
    # cannot be forgotten is the one every run must pass through, so the refusal is here.
    #
    # A solver that finds NO INCUMBENT is failing honestly and never reaches the quarantine.
    # A solver whose solution the verifier REJECTS means one of the two is wrong, and every
    # result from this engine is suspect until it is known which. So this engine will not start.
    if not a.ignore_quarantine:
        try:
            import subprocess as _sp
            _g = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "analysis", "quarantine_guard.py")
            if os.path.exists(_g):
                _r = _sp.run([sys.executable, _g, "--quiet"], capture_output=True, text=True,
                             timeout=60)
                if _r.returncode != 0:
                    print("REFUSING TO START: an untriaged verifier/solver contradiction stands.",
                          flush=True)
                    print("  python analysis/quarantine_guard.py   # what and how many",
                          flush=True)
                    print("  Triage the root cause and set `triaged` in runs/invalid/INDEX.md,",
                          flush=True)
                    print("  or pass --ignore-quarantine if THIS run is the triage.", flush=True)
                    sys.exit(3)
        except Exception as _e:
            print(f"quarantine guard could not run ({type(_e).__name__}); "
                  f"proceeding is NOT safe -- refusing", flush=True)
            sys.exit(3)
    import json

    from runlog import RunLogger

    # PROXIMITY IS RESOLVED FROM K's TABLE FOR THIS SIZE, NOT DEFAULTED.
    # 2026-09-18 (d209/d215): every |C| = 100 run of the overnight sweep was built by the plain
    # constructor, which defaults proximity to 0.0, while K's Table 6 -- the only n100 reference
    # -- is at 0.1. Seven hours of "vs K" numbers were void. The knowledge already existed:
    # analysis/lb_n100_probe.py:30 says "PROXIMITY 0.1 IS MANDATORY", InstanceSpec.for_k_comparison
    # was written for exactly this trap, and 13 analysis scripts use it. fixopt was not one of them.
    # So the safe path is now the DEFAULT and the unsafe one must be asked for by name.
    if a.proximity is None:
        # THE SIZE CHECK COMES FIRST, before for_k_comparison, because k_proximity() raises on a
        # size K never published and a traceback is not a refusal: it says nothing about what to
        # do, and exits 1 like any other crash rather than with this guard's own code.
        try:
            expect, _ex, _basis = k_setting(a.size, a.k_exhibit or None)
        except KeyError as e:
            print(f"REFUSING: {e}. Pass --proximity with --proximity-ack to choose one "
                  f"deliberately; this run cannot be compared to K in any case.", flush=True)
            sys.exit(5)
        # THE EXHIBIT IS THE AUTHORITY, so the spec is built from its proximity directly.
        # for_k_comparison resolves by SIZE, which is the thing this re-key exists to stop
        # relying on: it cannot express "|C| = 50 at Fig. 5's 0.1" and it raises outright on
        # |C| = 40, a size K does test.
        spec = InstanceSpec(a.instance, a.size, proximity=expect)

        # TWO INDEPENDENT SOURCES MUST AGREE, or nothing runs. k_proximity() reads
        # k_reference.json; K_EXHIBITS above is the literal from K's article. A disagreement
        # means one of them has drifted, and continuing would rebuild every satellite at the
        # wrong offset -- silently, which is exactly how seven hours of n100 work was voided.
        # The cross-check only applies where k_reference has a size-keyed answer AND we are
        # using that size's default comparator; asking it about Fig. 5 would be asking it a
        # question it does not answer.
        if not a.k_exhibit or a.k_exhibit == OUR_COMPARATOR.get(a.size):
            try:
                from analysis.k_comparison import k_proximity
                ref = k_proximity(a.size)
            except Exception:
                ref = None
            if ref is not None and abs(float(ref) - expect) > 1e-12:
                print(f"REFUSING: proximity disagreement at |C| = {a.size}. "
                      f"k_reference.json gives {ref}, K's article gives {expect}. "
                      f"One of the two has drifted -- fix it before running.", flush=True)
                sys.exit(5)
            agree = "agrees with k_reference.json" if ref is not None else "no size-keyed cross-check"
        else:
            agree = "exhibit chosen explicitly; no size-keyed cross-check applies"
        print(f"proximity {spec.proximity} from K's {_ex} for |C| = {a.size} "
              f"[{_basis}; {agree}]", flush=True)
    else:
        # AN OVERRIDE MUST BE ASKED FOR BY NAME AND ACKNOWLEDGED. I launched C207/n100 at 0.0
        # myself on 2026-09-19 with a bare --proximity, hours after banking the decision that
        # this must never happen again. A flag that is easy to pass is not a guard.
        try:
            expect, _ex, _basis = k_setting(a.size, a.k_exhibit or None)
        except KeyError:
            expect, _ex, _basis = None, None, None
        off_table = expect is None or abs(float(a.proximity) - expect) > 1e-12
        if off_table and not a.proximity_ack:
            print(f"REFUSING: --proximity {a.proximity} does not match K's published "
                  f"{expect} for |C| = {a.size}. Any result would be incomparable to K. "
                  f"Pass --proximity-ack with a reason if that is deliberate.", flush=True)
            sys.exit(5)
        spec = InstanceSpec(a.instance, a.size, proximity=a.proximity)
        print(f"proximity {a.proximity} OVERRIDDEN at the call site -- this run is NOT "
              f"comparable to K's published table for |C| = {a.size} (K uses {expect}). "
              f"Reason given: {a.proximity_ack}", flush=True)
    prob = SolverProblem(spec)

    # (26) IS SET ON THE RAW INSTANCE, NOT PASSED TO THE BUILDER.
    # joint_model_cplex reads it off the problem object at :254 via getattr(..., False), and
    # fixopt's ONLY model build is `build_joint_model(problem.raw)` at improve(). Setting it
    # here therefore reaches every sub-solve, the kick rung and the restart rung alike. The
    # default of the getattr is False, which is exactly how v1 silently ran the vacuous arm.
    prob.raw.hardSingleTransfer = bool(a.posts_26)
    # d243: the semantic arm is the PRODUCTION configuration. Same reasoning as posts_26 -- the
    # flag must reach every sub-solve, kick and restart, and the builder's getattr default is
    # False, which is exactly how v1 silently ran the vacuous arm.
    prob.raw.validBigM = bool(a.valid_bigm)
    production = bool(a.posts_26) and bool(a.valid_bigm)
    print(f"fixopt v{ENGINE_VERSION}  posts_26={bool(a.posts_26)}  "
          f"valid_bigm={bool(a.valid_bigm)}  "
          f"[{'PRODUCTION (d243 semantic arm)' if production else 'NON-PRODUCTION'}]",
          flush=True)
    if not a.posts_26:
        print("  WARNING: the model cannot represent (26). Incumbents may carry timetables "
              "the independent verifier refuses.", flush=True)
    if not a.valid_bigm:
        print("  WARNING: K's undersized big-Ms in (14) and (22). The model is OVER-TIGHT and "
              "excludes feasible routings, so objectives may be INFLATED.", flush=True)
    if not production:
        print("  This run is NOT a production artifact under d243 and must not be quoted as a "
              "result. The faithful arm exists as an ORACLE INSTRUMENT only.", flush=True)

    rng = random.Random(a.seed)
    eng = FixOptPrimal(iter_tl=a.iter_tl, threads=a.threads,
                       successor_tries=_parse_tries(a.successor_tries),
                       hub_congestion=a.hub_congestion,
                       restart_pool=a.restart_pool, restart_band=a.restart_band,
                       restart_accept_frac=a.restart_accept_frac,
                       frontload=not a.no_frontload,
                       improve_patience_s=a.improve_patience,
                       route_segment=a.route_segment, route_merge=a.route_merge,
                       k0=a.k0, k_max=a.k_max,
                       random_rotation=a.random_rotation, stall_streak=a.stall_streak,
                       fleet_floor=a.fleet_floor, construct_reuse=a.construct_reuse,
                       rotation=(a.rotation.split(",") if a.rotation else None),
                       kick_patience_s=a.kick_patience, kick_frac=a.kick_frac,
                       kick_frac_max=a.kick_frac_max, kick_frac_step=a.kick_frac_step,
                       migrate_path=a.migrate_path, migrate_every=a.migrate_every,
                       stall_patience_s=a.stall_patience, target_lb=a.target_lb,
                       stall_kicks=a.stall_kicks, stall_lb_frac=a.stall_lb_frac,
                       migrate_patience_s=a.migrate_patience,
                       kick_k=a.kick_k, kick_count=a.kick_count,
                       kick_from_best=a.kick_from_best, kick_thresh=a.kick_thresh,
                       kick_accept_frac=a.kick_accept_frac,
                       kick_complete_start=a.kick_complete_start,
                       route_drop=a.route_drop, route_drop_k=a.route_drop_k,
                       decouple_migrate=a.decouple_migrate,
                       xsat=a.xsat, xsat_k=a.xsat_k, kick_tl_cap=a.kick_tl_cap,
                       dump_kick_states=a.dump_kick_states)
    # Deterministic budget: set AFTER construction so the constructor signature is untouched.
    if a.det_budget is not None:
        eng.det_budget = a.det_budget
        eng.iter_det = a.iter_det if a.iter_det is not None else a.det_budget / 40.0

    vlabel = a.variant or ("base" if not (a.route_segment or a.kick_patience) else
                           ("+".join(x for x in [("rseg" if a.route_segment else ""),
                                                 ("kick" if a.kick_patience else "")] if x)))
    # THE WARM START IS PART OF THE VARIANT'S IDENTITY. Without this a cost-aware-WS run and a
    # blind-WS run differ only by a seed in the filename, and the two become indistinguishable
    # in the corpus -- exactly the confusion that makes an OV corpus unable to select a variant.
    # Appended only when non-default, so every existing run id is unchanged.
    _st = _parse_tries(a.successor_tries)
    _ws = []
    if _st != 1:
        _ws.append("st" + (str(_st) if isinstance(_st, int)
                           else "".join(str(x) for x in _st)))
    if a.hub_congestion:
        _ws.append("hc%g" % a.hub_congestion)
    if a.restart_pool:
        _ws.append("rp")
    if _ws:
        vlabel = vlabel + "+ws" + "".join(_ws)
    # unique per invocation -> RunLogger append mode no longer mixes runs
    _run_id = f"fixopt_{a.instance}_n{a.size}_s{a.seed}_{vlabel}_{int(time.time())}"
    # Print the run_id so a parent harness can bind THIS run's log by identity instead of by
    # file mtime. mtime matching can attach the wrong run's result under concurrency
    # (audit defect 3, 2026-09-12).
    print(f"RUN_ID {_run_id}", flush=True)
    lg = RunLogger(_run_id,
                   instance=a.instance, size=a.size, seed=a.seed,
                   config={"engine": "fixopt", "engine_version": ENGINE_VERSION,
                           # WHICH (26) ARM PRODUCED THIS RUN. The audits found `_posts_26`
                           # existed nowhere in any .py, so an artifact could not declare its
                           # own arm and a mixed corpus could not be separated after the fact.
                           "posts_26": bool(a.posts_26),
                           "valid_bigm": bool(a.valid_bigm),
                           "production_d243": production,
                           "k_exhibit": a.k_exhibit or OUR_COMPARATOR.get(a.size),
                           "proximity_ack": a.proximity_ack or None,
                           "wls": spec.wls, "tau": spec.tau,
                           "proximity": spec.proximity, "budget": a.budget,
                           "iter_tl": a.iter_tl, "threads": a.threads, "variant": vlabel,
                           "route_segment": a.route_segment, "kick_patience": a.kick_patience,
                           # the warm start that produced this run, recorded explicitly so the
                           # artifact is self-describing and a later reader need not infer it
                           # from the variant label or from what the defaults were that week
                           "ws_successor_tries": _st,
                           "ws_hub_congestion": a.hub_congestion,
                           "restart_pool": a.restart_pool,
                           "frontload": not a.no_frontload,
                           # THE TRIAL FLAGS, stamped so an artifact declares its own arm (d326:
                           # F1-F6 treatment runs were attributable by variant label only).
                           "rotation": a.rotation,
                           "construct_reuse": bool(a.construct_reuse),
                           "fleet_floor": bool(a.fleet_floor),
                           "k0": a.k0, "k_max": a.k_max,
                           "stall_streak": a.stall_streak,
                           "random_rotation": bool(a.random_rotation)})
    t0 = time.time()
    lg.phase("construct")
    s0 = eng.construct(prob, rng)
    vd = prob.verify(s0)
    print(f"construct: ok={vd.ok} obj={vd.recomputed_obj}")

    if a.warm_json:
        import json as _json
        wj = _json.load(open(a.warm_json))
        # ACCEPT A RESTART POOL AS A WARM START, not only a single solution.
        #
        # The pool was wired for RESTARTS -- adopted on a plateau -- but fixopt's INITIAL
        # incumbent was still one construction from one seed, while the pool's best entry is the
        # best of 20 seeds x the (1,3,5) ladder, structurally deduped. Starting from the weaker
        # of the two we already have in hand is a waste, and at |C| = 100 where fixopt has never
        # run it is the difference between a fair test of the matheuristic and a test of whether
        # it can recover from a poor seed.
        #
        # Pool files are sorted best-first by build_restart_pool.py, so [0] is the best entry.
        if isinstance(wj, dict) and wj.get("pool"):
            wsol = wj["pool"][0]["sol"]
            print("warm-json: restart pool, taking best of %d banked constructions (obj %.2f)"
                  % (len(wj["pool"]), wj["pool"][0]["obj"]))
        else:
            wsol = wj.get("sol", wj)
        wvd = prob.verify(wsol)
        print(f"warm-json: ok={wvd.ok} obj={wvd.recomputed_obj}  (LB={wj.get('LB')})")
        lg.note("warm-json seed", extra={"ok": wvd.ok, "obj": wvd.recomputed_obj,
                                         "src": a.warm_json})
        if wvd.ok and wvd.recomputed_obj is not None and (
                not vd.ok or vd.recomputed_obj is None
                or wvd.recomputed_obj < vd.recomputed_obj):
            print(f"  -> warm-json seed adopted ({wvd.recomputed_obj} < "
                  f"{vd.recomputed_obj if vd.ok else 'infeasible'})")
            wsol["objVal"] = wvd.recomputed_obj
            s0, vd = wsol, wvd

    if not vd.ok:
        print("  seed infeasible — cannot start fixopt:", vd.violations[:3])
        lg.note("seed infeasible", extra={"violations": vd.violations[:3]})
        lg.close(status="seed_infeasible", run_valid=True, verified=False)
        sys.exit(1)
    s0["objVal"] = vd.recomputed_obj
    lg.incumbent(vd.recomputed_obj, trigger="construct")
    best = vd.recomputed_obj
    best_sol = dict(s0)
    rejects = 0
    lg.phase("improve")
    for better in eng.improve(prob, s0, rng, t0 + a.budget, logger=lg):
        vd = prob.verify(better)
        tag = "OK" if vd.ok else f"REJECT {vd.violations[:2]}"
        print(f"  +improve obj={better['objVal']} mode={better.get('_mode')} "
              f"verify={tag} (recomputed {vd.recomputed_obj})  t={time.time()-t0:.0f}s",
              flush=True)
        if vd.ok and vd.recomputed_obj is not None:
            if vd.recomputed_obj < best:
                best, best_sol = vd.recomputed_obj, dict(better)
        else:
            rejects += 1
            lg.event(None, trigger="reject_incumbent",
                     extra={"mode": better.get("_mode"), "violations": vd.violations[:3]})
            # DUMP THE REJECTED CANDIDATE. 2026-09-21: a C26 reject at R202/n100 could not be
            # diagnosed because the candidate was discarded with only its violation STRING
            # surviving -- no u values, no hub attribution, nothing to test a hypothesis
            # against. Three mechanisms were proposed and two were killed only after the fact;
            # the third is untestable from banked dumps by construction, because a candidate
            # that triggers the bug is precisely the one that never gets dumped.
            # Diagnostic only: this writes data that is currently thrown away, and changes
            # nothing about which solution the run adopts or reports.
            try:
                _rd = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))), "runs", "rejected")
                os.makedirs(_rd, exist_ok=True)
                _rc = dict(better)
                _rc["_rejected_violations"] = [str(v) for v in vd.violations[:10]]
                _rc["_rejected_mode"] = better.get("_mode")
                _rc["_rejected_t_s"] = round(time.time() - t0, 1)
                _rc["_rejected_recomputed"] = vd.recomputed_obj
                json.dump(_rc, open(os.path.join(_rd, "rej_%s_n%d_s%d_%s_%d.json"
                                                 % (a.instance, a.size, a.seed, a.variant,
                                                    int(time.time() * 1000) % 10**9)),
                                    "w"), indent=1, default=str)
            except Exception as _e:
                print("  (could not dump rejected candidate: %s)" % type(_e).__name__, flush=True)
    print(f"final best (verified) = {best}   wall={time.time()-t0:.0f}s")
    if a.dump_best:
        best_sol["objVal"] = best
        # RUN PROVENANCE ON THE SOLUTION ITSELF (2026-09-17, decision 64).
        #
        # All 60 solutions banked before today carry only _wall_s, _iter and _mode -- nothing
        # linking them to the run that produced them. That gap has a real consequence: the
        # fairness audit found our TOTAL per-cell compute exceeds K's 14,400 s budget at |C| = 30
        # and in the |C| = 20 tail, and the natural defence -- "the REPORTED solution came from
        # ONE run, within budget" -- could not be made, because the run could not be identified.
        #
        # Everything stamped here was already computed; none of it is new work. The budget fields
        # are what let a reader check the defence instead of taking it on trust.
        # SWISS-WATCH PROVENANCE. The engine stamped the model arm thoroughly but none of the
        # fields the project's OWN standard requires: G6 wants code_hash, git_sha and python,
        # G5 wants the solver version, and CLAUDE.md is explicit that CODE_HASH -- not git_sha --
        # is the reproducibility anchor, because a dirty tree makes the commit alone unable to
        # reconstruct the code state. An artifact that cannot be traced to the exact code,
        # solver and seed that produced it is not evidence.
        try:
            import subprocess as _sp, platform as _pl
            from analysis.repro_preflight import code_hash as _ch, solver_versions as _sv
            best_sol["_code_hash"] = _ch()
            best_sol["_solver_versions"] = _sv()
            _g = _sp.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True,
                         text=True, cwd=_ROOT)
            best_sol["_git_sha"] = (_g.stdout or "").strip() or None
            _d = _sp.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                         cwd=_ROOT)
            best_sol["_git_dirty"] = bool((_d.stdout or "").strip())
            best_sol["_python"] = _pl.python_version()
            best_sol["_host"] = _pl.node()
            best_sol["_platform"] = _pl.platform()
            # WHICH VERIFIER PASSED IT, exactly. _engine_version already names the producer;
            # without the verifier's own hash an artifact says it was accepted but not BY WHAT.
            # verifier3 changed twice today (the B1 garage fix, the d243 provenance axis), so
            # "verified" is meaningless unless the verifier is pinned too.
            import analysis.verifier3 as _v3
            best_sol["_verifier"] = "verifier3"
            best_sol["_verifier_code_hash"] = _v3.code_hash()
            # THE SOLVER THAT ACTUALLY RAN. repro_preflight.solver_versions reports docplex and
            # cplex; this engine solves with GUROBI, so without this the artifact names the wrong
            # solver entirely. And _threads records the ARGUMENT, which is None when unset --
            # record the EFFECTIVE count, because "None" is not a configuration anyone can
            # reproduce.
            try:
                import gurobipy as _gp
                best_sol["_solver"] = "gurobi"
                best_sol["_solver_version"] = ".".join(str(x) for x in _gp.gurobi.version())
            except Exception:
                best_sol["_solver"] = None
            # d351: this read best_sol["_threads"], which is written ~30 lines BELOW, so every
            # artifact claimed "argument unset" and stamped os.cpu_count() even when --threads
            # was given. Read the argument itself. Fixed 2026-09-25 (d415).
            if a.threads is None:
                best_sol["_threads_effective"] = os.cpu_count()
                best_sol["_threads_note"] = "argument unset; solver used all available cores"
            else:
                best_sol["_threads_effective"] = int(a.threads)
        except Exception as _e:
            best_sol["_provenance_error"] = "%s: %s" % (type(_e).__name__, _e)
        best_sol["_run_id"] = _run_id
        best_sol["_engine_version"] = ENGINE_VERSION
        best_sol["_posts_26"] = bool(a.posts_26)
        best_sol["_valid_bigm"] = bool(a.valid_bigm)
        best_sol["_production_d243"] = production
        # d243: the provenance assertion lives HERE, on the finished artifact, because only the
        # artifact can carry the declaration. verifier3.provenance reads what was just stamped,
        # so a mismatch between the flags and what is written cannot pass silently.
        try:
            from analysis.verifier3 import provenance as _prov, PRODUCTION as _PROD
            _st, _why = _prov(best_sol)
            if production and _st != _PROD:
                raise SystemExit("REFUSING to dump: the run was PRODUCTION but the artifact "
                                 "declares %s (%s)" % (_st, "; ".join(_why)))
            print(f"  artifact provenance: {_st}", flush=True)
        except ImportError:
            pass
        best_sol["_proximity"] = spec.proximity
        best_sol["_k_exhibit"] = a.k_exhibit or OUR_COMPARATOR.get(a.size)
        best_sol["_proximity_ack"] = a.proximity_ack or None
        best_sol["_variant"] = vlabel
        best_sol["_instance"] = a.instance
        best_sol["_size"] = a.size
        best_sol["_seed"] = a.seed
        best_sol["_threads"] = a.threads
        best_sol["_det_budget"] = a.det_budget
        # THE WORK ACTUALLY DONE. Without this the artifact carries a budget that
        # 69-100% of runs never reached and no record of what they did reach, so a
        # contended run is undetectable from the released record. Wall clock is the
        # declared stop rule now (primal-harness-blocking-defects-v3); det_used is
        # what replaces it -- a load MEASUREMENT rather than an equaliser. Gate G14
        # arms itself on this field appearing.
        best_sol["_det_used"] = round(eng.det_used, 2)
        best_sol["_det_bound"] = bool(a.det_budget
                                      and eng.det_used >= 0.98 * a.det_budget)
        best_sol["_wall_budget_s"] = a.budget
        best_sol["_run_wall_s"] = round(time.time() - t0, 1)
        best_sol["_ws_successor_tries"] = _st
        best_sol["_ws_hub_congestion"] = a.hub_congestion
        best_sol["_restart_pool"] = a.restart_pool
        # the arm this artifact came from, in the artifact itself (d326)
        best_sol["_flags"] = {"rotation": a.rotation, "construct_reuse": bool(a.construct_reuse),
                              "fleet_floor": bool(a.fleet_floor), "k0": a.k0, "k_max": a.k_max,
                              "stall_streak": a.stall_streak,
                              "random_rotation": bool(a.random_rotation),
                              "frontload": not a.no_frontload}
        json.dump(best_sol, open(a.dump_best, "w"), default=str)
        print(f"  dumped best -> {a.dump_best}  (run_id {_run_id})")
    # a fixopt reject = the joint-model restriction (a subset of the compact
    # model) produced a solution the independent verifier rejects -> a defect
    # in the model builder or the verifier. Quarantine for triage (guard 4).
    # Record what the run actually SPENT, deterministically. Without this a replicator cannot
    # tell whether a differing result came from a different budget or a different search.
    # RunLogger.event takes free fields in `extra`, not as loose kwargs. Passing them loosely
    # raised a TypeError that a bare `except: pass` swallowed, so the first version of this
    # stamp recorded NOTHING while appearing to work -- the same fail-quiet shape this project
    # has hit repeatedly. The failure is now printed: a provenance stamp that cannot be written
    # must be loud, since its whole purpose is to be there later.
    try:
        lg.event(None, trigger="det_budget_spent", extra={
            "det_budget": eng.det_budget, "det_used": round(eng.det_used, 2),
            "iter_det": eng.iter_det,
            # REPORTS WHAT BOUND, not what was configured. This read
            # "deterministic if eng.det_budget is not None", so every run with a
            # budget set was stamped deterministic whether or not it reached one --
            # 103 of 137 n100 runs were wall-stopped and labelled otherwise. That is
            # why d191 says to read det_used rather than the status.
            "stop_rule": ("deterministic"
                          if (eng.det_budget is not None
                              and eng.det_used >= 0.98 * eng.det_budget)
                          else "wall_clock")})
    except Exception as e:
        print(f"WARNING: det_budget_spent stamp FAILED to write: {type(e).__name__}: {e}",
              flush=True)
    # det_used reaches summary.csv through config_json, which runlog serialises from
    # self.config at close. This is the field G14 enforces.
    lg.config["det_used"] = round(eng.det_used, 2)
    _det_bound = bool(eng.det_budget is not None
                      and eng.det_used >= 0.98 * eng.det_budget)
    lg.close(status=("det_budget_exhausted" if _det_bound else "budget_exhausted"),
             run_valid=(rejects == 0),
             verified=(rejects == 0), final_incumbent=best)
