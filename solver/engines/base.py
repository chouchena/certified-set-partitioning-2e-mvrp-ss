"""
Abstract engine interfaces. The primal engine and the dual engine are
separate, independently swappable modules (roadmap Phase 3 design
principle) so ablations can isolate what drives any improvement.

A "solution" is the plain dict the independent verifier consumes:
    {xij:[[i,j]], vi:[int], hubs:[int], yij:[[i,j]], nCars:int, nVessel:int,
     objVal: float}
so no solver-specific representation leaks into the verification path
(rule 3).
"""
from __future__ import annotations
import abc


class PrimalEngine(abc.ABC):
    """Produces / improves feasible solutions."""

    name: str = "primal"

    @abc.abstractmethod
    def construct(self, problem, rng) -> dict | None:
        """Return an initial feasible solution dict, or None if it can't."""

    def improve(self, problem, incumbent: dict, rng, deadline: float):
        """
        Yield improved solution dicts (each strictly better than the last)
        until `deadline` (time.time() seconds). Default: no-op.
        """
        return
        yield  # make this a generator


class DualEngine(abc.ABC):
    """Produces valid lower bounds on the optimum (minimisation)."""

    name: str = "dual"

    @abc.abstractmethod
    def bound(self, problem, incumbent: dict | None) -> dict:
        """
        Return {'bound': float, 'valid': bool, 'detail': {...}}.
        'valid' must be False unless the relaxation is proven to bound the
        SAME feasible region as the compact model (roadmap Phase 2.3 —
        no bound is reported without this).
        """
