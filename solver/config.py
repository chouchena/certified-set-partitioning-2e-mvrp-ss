"""
SolverConfig — the single configuration surface for the modular
2E-MVRP-SS solver (roadmap Phase 3.3).

One config object toggles: which primal engine(s) are active, which dual
component(s) are active, the re-bound cadence, and the time-budget split
between primal and dual effort. This is what makes the Phase-5 ablation
study possible without rewriting code per experiment.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class InstanceSpec:
    """Which instance + the LOCKED reproduction config (rules 12, 20)."""
    name: str
    size: int
    wls: float = 0.1                     # 1:10
    tau: str | float = "formula"         # per-family ceil(2*mean service)
    # THE DEFAULT IS CORRECT FOR TABLES 3 AND 4 ONLY -- |C| in {10, 20, 30, 50}. K's Table 6,
    # which is |C| = 100, is at proximity 0.1. Constructing InstanceSpec(cell, 100) and taking
    # this default therefore builds a DIFFERENT problem from the one the published n100 figures
    # describe, and does so silently.
    #
    # THE DEFAULT IS DELIBERATELY NOT MADE SIZE-DEPENDENT. Proximity is an INSTANCE parameter;
    # "which proximity K's table used" is a COMPARISON parameter, and conflating them is the
    # actual bug. `analysis/ab_proximity_sweep.py` deliberately sweeps 0.0 through 0.4 at fixed
    # size to broaden K's Fig. 4 study -- auto-deriving from size would silently override the one
    # parameter that script exists to vary.
    #
    # Use `InstanceSpec.for_k_comparison(name, size)` when the point is to compare against their
    # published table. Explicit at the call site, silent nowhere.
    proximity: float = 0.0               # Tables 3/4 base; see note above for |C| = 100

    @classmethod
    def for_k_comparison(cls, name: str, size: int, **kw) -> "InstanceSpec":
        """An InstanceSpec at the proximity K's published table FOR THIS SIZE uses.

        0.0 for |C| in {10, 20, 30, 50} (Tables 3 and 4), 0.1 for |C| = 100 (Table 6). The value
        is resolved from `k_reference.json` via `analysis.k_comparison.k_proximity`, never
        hardcoded here, so a correction to our extraction of their paper propagates.

        Use this whenever the instance is being built in order to compare against their numbers.
        Use the plain constructor when the proximity is yours to choose -- a sensitivity sweep,
        or any run that is not measured against their table.
        """
        if "proximity" in kw:
            raise TypeError("for_k_comparison resolves proximity from the size; pass it to "
                            "InstanceSpec() directly if you mean to override it")
        from analysis.k_comparison import k_proximity      # local: avoids an import cycle
        return cls(name=name, size=size, proximity=k_proximity(size), **kw)


@dataclass
class SolverConfig:
    instance: InstanceSpec

    # ---- primal engine(s) -- run in the order listed --------------
    #   "construct"  : clustering / TW-feasible constructive warm start
    #   "fixopt"     : fix-and-optimize matheuristic (local branching)
    #   "rmp_dive"   : restricted-master diving (column generation)
    #   "alns"       : ALNS metaheuristic (outside the course toolkit)
    primal: list[str] = field(default_factory=lambda: ["construct"])

    # ---- dual engine(s) ------------------------------------------
    #   "lagr_relax" : reused single-constraint Lagrangian relaxation
    #   "lagr_decomp": Lagrangian DECOMPOSITION, routing/scheduling split
    #   "surrogate"  : surrogate / convex-hull relaxation
    #   "dw_cg"      : Dantzig-Wolfe column generation LP bound
    dual: list[str] = field(default_factory=list)

    # ---- cadence & budget ---------------------------------------
    time_budget_s: float = 600.0
    primal_dual_split: float = 0.7        # fraction of budget to primal
    rebound_every_n_incumbents: int = 1   # how often the dual re-bounds
    seed: int = 0

    # ---- gating / logging --------------------------------------
    verify_incumbents: bool = True        # rule 3 — every incumbent gated
    verify_final: bool = True
    log: bool = True                      # rule 4

    def run_id(self) -> str:
        i = self.instance
        p = "+".join(self.primal) or "none"
        d = "+".join(self.dual) or "none"
        return f"solve_{i.name}_n{i.size}_p[{p}]_d[{d}]_s{self.seed}"

    def as_dict(self) -> dict:
        i = self.instance
        return {
            "instance": i.name, "size": i.size, "wls": i.wls,
            "tau": i.tau, "proximity": i.proximity,
            "primal": self.primal, "dual": self.dual,
            "time_budget_s": self.time_budget_s,
            "primal_dual_split": self.primal_dual_split,
            "rebound_every_n_incumbents": self.rebound_every_n_incumbents,
            "seed": self.seed, "engine": "modular_solver",
        }
