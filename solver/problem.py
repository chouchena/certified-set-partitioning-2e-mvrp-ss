"""
SolverProblem — thin wrapper the engines see. Holds the built instance
(via build_instance, the only sanctioned path — rule 19/21) plus a
matching independent VInstance for verification (rule 3).
"""
from __future__ import annotations
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from build_instance import build
# 2026-09-20: the in-loop check runs VERIFIER3, which checks K's PUBLISHED constraints (1)-(30)
# in their original form rather than our model's rows. verify2 checked the right object -- the
# committed {h,u} -- but its class list was derived from our own transcription, so the only parity
# ever established was model <-> verifier, which is blind to a constraint K state that our model
# also omits.
from instance_view import VInstance
from analysis.verifier3 import verify_for_engine


class SolverProblem:
    def __init__(self, spec):
        self.spec = spec
        self._p = build(spec.name, spec.size, wls=spec.wls, tau=spec.tau,
                        proximity=spec.proximity, time_limit=spec.__dict__.get("time_limit", 600))
        self.tau = self._p._resolved_tau
        # engine-facing shortcuts
        self.D = self._p.DistMatrix
        self.nodes = self._p.nodes
        self.customers = list(self._p.customers)
        self.satellites = list(self._p.satellites)
        self.CDC = self._p.CDC
        self.depot = 0
        self.car_capacity = self._p.CarCapacity
        self.vessel_capacity = self._p.VesselCapacity
        self.penalty_cars = self._p.penaltyCars
        self.penalty_vessels = self._p.penaltyVessels
        self.travelcoststreet = self._p.travelcoststreet
        self.travelcostwater = self._p.travelcostwater
        self.total_demand = sum(self.nodes[c].demand for c in self.customers)
        # independent verifier instance
        self._vinst = VInstance(spec.name, spec.size, wls=spec.wls,
                                tau=self.tau, proximity=spec.proximity)

    @property
    def raw(self):
        """The underlying instanceGenerator object (for engines that call
        joint_model_cplex on a sub-region)."""
        return self._p

    def verify(self, solution: dict):
        """Run the independent verifier (verifier3) on this candidate. Returns a Verdict3.

        THE COMMITTED TIMETABLE IS WHAT IS CHECKED. The destroyed verifier asked CP-SAT whether
        ANY schedule existed for the routing and ignored the h/u actually being proposed, so a
        candidate whose own timetable violated (26) was accepted whenever some other timetable
        would have worked. verifier3 evaluates the committed values by arithmetic -- one subtraction
        per same-satellite pair -- and never solves anything.

        Exposes `.ok`, `.recomputed_obj`, `.violations`, the three attributes the engines read.
        """
        # d243 PROVENANCE IS NOT CHECKED HERE, deliberately. It is a property of the finished
        # ARTIFACT, not of an in-flight candidate: the configuration lives on the problem object
        # and the flags are stamped at dump time, so a candidate can never declare it. Checking
        # it per candidate made every constructive seed UNDECLARED, hence not .ok, so construct
        # returned None and the engine died before its first improvement. The assertion belongs
        # at the dump, and fixopt makes it there.
        return verify_for_engine(self._vinst, solution,
                                 cell=self.spec.name, size=self.spec.size,
                                 proximity=self.spec.proximity,
                                 label="fixopt:%s/n%d" % (self.spec.name, self.spec.size),
                                 expect="any")
