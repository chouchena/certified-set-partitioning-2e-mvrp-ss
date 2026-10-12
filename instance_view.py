"""instance_view.py -- INDEPENDENT instance reconstruction for the 2E-MVRP-SS
(Karademir, Beirigo & Atasoy 2025, EJOR 322(2) 480-499), per collaboration rule 3.

EXTRACTED 2026-09-19 from verifier.py, which was DESTROYED on author instruction. The old
verifier's CHECKING logic was unsound -- `_schedule_feasible` discarded the committed {h,u} and
asked CP-SAT whether ANY timetable existed, a different and weaker object, which is why 13 of 14
|C|=100 dumps violated (26) at their committed values while the pipeline called them valid.

Its INSTANCE REBUILD was never the defect, and verify2 depends on it. This module is that rebuild
and nothing else: no checking, no solving, no search.

Independence contract, inherited unchanged:
  * Rebuilds the instance from the raw Solomon JSON with its OWN parsing, distance-matrix
    construction, satellite placement, time-window adjustment and cost-coefficient logic.
  * Imports NOTHING from instanceGenerator.py, integratedJointModel.py, DecomposedModels.py,
    LBBDmodel.py, solution.py, joint_model_cplex.py.

Our use of the predecessors' formulation, code and instance set is gratefully acknowledged.
"""
from __future__ import annotations
import json
import math
import os
from dataclasses import dataclass

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "json")

LEFV_CAPACITY = 50
VESSEL_CAPACITY = 250
NOF_SATELLITES = 4

# WLS code param -> (wcost, scost)
_WLS = {0.1: (1, 10), 0.2: (1, 5), 1: (1, 1), 10: (10, 1)}


# --------------------------------------------------------------------------
#  Independent instance rebuild
# --------------------------------------------------------------------------
@dataclass
class VNode:
    idx: int
    typ: str
    x: float
    y: float
    demand: float
    earliest: float
    latest: float
    service: float


class VInstance:
    """Independent reconstruction. Node layout: 0 = garage/depot,
    1..N = customers, N+1 = CDC, N+2..N+1+P = satellites."""

    def __init__(self, instance_name: str, size: int, wls: float = 0.1,
                 tau: float = 0.0, proximity: float = 0.0):
        self.name = instance_name
        self.size = size
        self.wls = wls
        self.tau = tau
        self.proximity = proximity

        raw = self._load_json(instance_name)
        self._build_nodes(raw, size)
        self._add_cdc()
        self._add_satellites(proximity)
        self._build_distance_matrix()
        self._update_time_windows()
        self._set_cost_coefficients(wls)

    # ---- parsing -------------------------------------------------------
    @staticmethod
    def _load_json(instance_name):
        path = os.path.join(DATA_DIR, instance_name if instance_name.endswith(".json")
                            else instance_name + ".json")
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _build_nodes(self, raw, size):
        d = raw["depart"]
        self.nodes = [VNode(0, "D", d["coordinates"]["x"], d["coordinates"]["y"],
                            d["demand"], d["ready_time"], d["due_time"], d["service_time"])]
        for i in range(1, size + 1):
            c = raw[f"customer_{i}"]
            self.nodes.append(VNode(i, "C", c["coordinates"]["x"], c["coordinates"]["y"],
                                    c["demand"], c["ready_time"], c["due_time"], c["service_time"]))
        self.customers = list(range(1, size + 1))
        self.depot = 0

    def _add_cdc(self):
        xs = [self.nodes[i].x for i in self.customers]
        ys = [self.nodes[i].y for i in self.customers]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        self._bbox = (minx, maxx, miny, maxy)
        xcdc = minx - (maxx - minx) / 2.0
        ycdc = maxy + (maxy - miny) / 2.0
        self.CDC = len(self.nodes)
        self.nodes.append(VNode(self.CDC, "CDC", xcdc, ycdc, 0,
                                self.nodes[0].earliest, self.nodes[0].latest, 0))
        self.total_demand = sum(self.nodes[i].demand for i in self.customers)
        self.min_vessels = math.ceil(self.total_demand / VESSEL_CAPACITY)

    def _add_satellites(self, c):
        minx, maxx, miny, maxy = self._bbox
        self.satellites = []
        coords = [
            (minx + (maxx - minx) / 2.0, miny + (maxy - miny) * c),   # side 0
            (minx + (maxx - minx) / 2.0, maxy - (maxy - miny) * c),   # side 1
            (minx + (maxx - minx) * c, miny + (maxy - miny) / 2.0),   # side 2
            (maxx - (maxx - minx) * c, miny + (maxy - miny) / 2.0),   # side 3
        ]
        for (sx, sy) in coords:
            k = len(self.nodes)
            self.nodes.append(VNode(k, "S", sx, sy, 0,
                                    self.nodes[0].earliest, self.nodes[0].latest, self.tau))
            self.satellites.append(k)

    def _build_distance_matrix(self):
        n = len(self.nodes)
        d = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                a, b = self.nodes[i], self.nodes[j]
                d[i][j] = round(math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2), 2)
        # exact replica of instanceGenerator.CreateDistMatrix: single in-place
        # sequential pass, '<=' comparison, NOT iterated to convergence.
        for i in range(n):
            for j in range(n):
                for k in range(n):
                    cc = d[i][k] + d[k][j]
                    if cc <= d[i][j]:
                        d[i][j] = cc
        self.D = d

    def _update_time_windows(self):
        # isDelivery = False branch of instanceGenerator.UpdateTWs
        max_return = max(
            self.nodes[i].latest + self.nodes[i].service + self.D[i][p]
            + self.tau + self.D[p][self.CDC]
            for i in self.customers for p in self.satellites
        )
        for i in [self.depot, self.CDC, *self.satellites]:
            self.nodes[i].latest = float(max_return)
        self.max_return = float(max_return)

    def _set_cost_coefficients(self, wls):
        wcost, scost = _WLS[wls]
        WRS = round(wcost / scost, 2)            # normalized = False
        self.travelcoststreet = 1.0
        self.travelcostwater = 1.0 * WRS
        base = round(max(
            self.travelcoststreet * (self.D[0][c] + self.D[c][p] + self.D[p][0])
            + self.travelcostwater * (self.D[self.CDC][p] + self.D[p][self.CDC])
            for c in self.customers for p in self.satellites
        ), 2)
        self.penalty_cars = base
        self.penalty_vessels = base * WRS
