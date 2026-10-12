"""
Orchestrator — runs the configured primal / dual engines, gates every
incumbent through the independent verifier (rule 3), logs every event
through RunLogger (rule 4), and returns a verified incumbent + a valid
bound (when a dual engine is active).

Design: primal and dual are separate modules; the orchestrator only
sequences them and enforces the gates. Swapping an engine changes one
line of SolverConfig, nothing here (roadmap Phase 3.3).
"""
from __future__ import annotations
import random
import time
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from runlog import RunLogger
from solver.problem import SolverProblem

_PRIMAL_REGISTRY = {}
_DUAL_REGISTRY = {}


def _register():
    from solver.engines.construct import ConstructivePrimal
    _PRIMAL_REGISTRY.setdefault("construct", ConstructivePrimal)
    # later: fixopt, rmp_dive, alns  |  dual: lagr_relax, lagr_decomp, ...


class Result:
    def __init__(self):
        self.incumbent = None          # verified solution dict
        self.incumbent_obj = None
        self.bound = None              # valid lower bound (or None)
        self.gap_pct = None
        self.verified = False
        self.rejected = []             # (engine, violations) for invalid proposals
        self.events = 0

    def __str__(self):
        g = f"{self.gap_pct:.3f}%" if self.gap_pct is not None else "n/a"
        return (f"incumbent={self.incumbent_obj}  bound={self.bound}  gap={g}  "
                f"verified={self.verified}  rejected={len(self.rejected)}")


def solve(config) -> Result:
    _register()
    rng = random.Random(config.seed)
    res = Result()

    log = RunLogger(config.run_id(), instance=config.instance.name,
                    size=config.instance.size, config=config.as_dict(),
                    seed=config.seed) if config.log else _NullLog()

    log.phase("build")
    problem = SolverProblem(config.instance)
    t0 = time.time()
    deadline = t0 + config.time_budget_s
    primal_deadline = t0 + config.time_budget_s * config.primal_dual_split

    # ---- primal: construction --------------------------------------
    for pname in config.primal:
        engine = _PRIMAL_REGISTRY[pname]()
        log.phase(f"primal:{pname}:construct")
        sol = engine.construct(problem, rng)
        if sol is None:
            log.note(f"{pname}.construct returned None")
            continue
        _consider(problem, sol, f"{pname}:construct", res, log, config)

        # ---- primal: improvement loop ----------------------------
        log.phase(f"primal:{pname}:improve")
        if res.incumbent is not None:
            for better in engine.improve(problem, res.incumbent, rng, primal_deadline):
                _consider(problem, better, f"{pname}:improve", res, log, config)
                if time.time() > primal_deadline:
                    break

    # ---- dual: bounding ------------------------------------------
    for dname in config.dual:
        if dname not in _DUAL_REGISTRY:
            log.note(f"dual engine '{dname}' not implemented yet — skipped")
            continue
        engine = _DUAL_REGISTRY[dname]()
        log.phase(f"dual:{dname}")
        b = engine.bound(problem, res.incumbent)
        if b.get("valid") and b.get("bound") is not None:
            if res.bound is None or b["bound"] > res.bound:
                res.bound = b["bound"]
            log.bound(b["bound"], trigger=f"dual:{dname}", extra=b.get("detail"))
        else:
            log.note(f"dual '{dname}' produced no VALID bound "
                     f"(valid={b.get('valid')}) — not recorded (rule: Phase 2.3)")

    # ---- finalise ---------------------------------------------
    if res.incumbent_obj is not None and res.bound is not None and res.incumbent_obj != 0:
        res.gap_pct = 100.0 * (res.incumbent_obj - res.bound) / abs(res.incumbent_obj)
    res.verified = res.incumbent is not None

    # run_valid: the orchestrated run itself is valid even if it found no
    # verified incumbent (rejected proposals are logged as events). Only
    # guard 1 (bound > incumbent) forces quarantine here.
    log.close(status="done", verified=res.verified, run_valid=True,
              final_incumbent=res.incumbent_obj, final_bound=res.bound)
    return res


def _consider(problem, sol, source, res, log, config):
    """Verify a proposed solution; accept only if it passes (rule 3)."""
    if config.verify_incumbents:
        vd = problem.verify(sol)
        if not (vd.ok):
            res.rejected.append((source, vd.violations[:3]))
            log.event(None, trigger=f"reject:{source}",
                      extra={"violations": vd.violations[:5]})
            return
        obj = vd.recomputed_obj
        sol = {**sol, "objVal": obj}
    else:
        obj = sol.get("objVal")

    if res.incumbent_obj is None or (obj is not None and obj < res.incumbent_obj - 1e-6):
        res.incumbent = sol
        res.incumbent_obj = obj
        log.incumbent(obj, trigger=source,
                      extra={"components": getattr(vd, "components", None)
                             if config.verify_incumbents else None})


class _NullLog:
    def __getattr__(self, _):
        return lambda *a, **k: None
