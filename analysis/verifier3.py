"""verifier3 -- CHECKED AGAINST THE PUBLISHED CONSTRAINTS, NOT AGAINST OUR MODEL.

Design: validation/DESIGN_verifier3.md.  Design audit: validation/AUDIT_design_verifier3.md.

WHY A THIRD VERIFIER. verify2 is sound in its arithmetic and independent of the solver, but its
constraint classes were derived from our own transcription (joint_model_cplex.py). The only parity
ever established was MODEL <-> VERIFIER, and that check is blind to a constraint K state which our
model ALSO omits -- both sides agree, silently, about a problem that is not quite the published one.

Author, 2026-09-20: *"For our verifier -- I ONLY need alignment with original form constraints."*

So every class here carries the published constraint number it discharges, read from pp. 484-486 of
Karademir, Beirigo & Atasoy (2025), EJOR 322(2) 480-499. THE PUBLISHED FORM IS QUOTED BESIDE EACH
CHECK so a reviewer holding the article can falsify the transcription line by line rather than
trusting this file. This module imports NO builder: it can be audited without opening our model.

THE DISTINCTION THIS FILE TURNS ON. K's (1)-(30) are three kinds of thing:

  SEMANTIC  a requirement on the assignment                      -> checked
  DOMAIN    a variable's type or range                           -> checked as well-formedness
  ENCODING  a row that exists to make a MILP work: the big-M
            conditionals, and the lower-bounding definitions of
            f^s_ij and f^w_ij                                    -> NEVER checked as a row

The last line is the whole reason the (26) defect was findable. (27)-(30) is an ENCODING of (26),
and every violating timetable satisfies it. A verifier that checks encodings inherits the
encoding's defects. The correct treatment is to RECOMPUTE the quantity the row defines and check
the requirement underneath: f^s and f^w are only lower-bounded and are minimised in (1), so this
file never reads them -- it recomputes travel from the routing and the hub assignment.

LIMITS, carried from the design audit so they are not rediscovered as defects:

  * (3) and (17) cap fleet size at K_s, K_w. K's S5.1: "the fleet size of each level is assumed to
    be unlimited". So the <= K halves NEVER FIRE on anything we run. The equality halves do.
  * (31)-(38) are the DELIVERY variant (their S3.4). Our instances are the pickup problem, so they
    are out of scope -- a scoping choice of ours, not an absence in K. On a delivery instance this
    file would check the wrong set and say nothing about it.
  * This file certifies FEASIBILITY and recomputes the objective. It cannot say a solution is
    optimal, and it cannot detect that a model EXCLUDED better solutions -- an over-tight big-M is
    invisible to any verifier, because the evidence is an absence.
  * Agreement with verify2 is NOT success. The two must be built from different sources for the
    comparison to mean anything; see the falsification plan in the design.

NOTATION MAP, K -> ours:  g = depot (node 0) | d = CDC | U = tau | t_ij = D[i][j] |
q_i = demand | a_i = earliest | b_i = latest | tau_i = service | Q_s/Q_w = LEFV/VESSEL capacity |
beta_s/beta_w = penalty_cars/penalty_vessels | c^s/c^w = travelcoststreet/travelcostwater.

    python analysis/verifier3.py "runs/solutions/*.json"
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import instance_view                                   # instance rebuild only; no builder

ACCEPT, REJECT, NOT_CHECKED = "ACCEPT", "REJECT", "NOT_CHECKED"

# A shortfall at or below this is recorded as TOLERANCE rather than VIOLATION, reported
# separately and never silently dropped. It is the ONLY threshold, and the comparison
# itself is EXACT -- a satisfied constraint passes on slack >= 0 with no tolerance.
#
# THIS IS NOT PARITY WITH THE SOLVER, and an earlier comment here wrongly said it was.
# CPLEX's feasibility tolerance applies to the ROW RESIDUAL, so a row carrying a large
# coefficient permits a far larger violation in variable space. On 2026-09-21 a (26)
# row with Mbig = 1187 returned |u_i - u_j| = 19.999987 against tau = 20 -- feasible to
# the solver, a real 1.3049e-5 violation here. Being STRICTER than the solver is the
# property that caught it, and it is deliberate.
FEAS_TOL = Fraction(1, 10 ** 6)


def F(x):
    """Exact. Floats enter as exact binary rationals; nothing is rounded on the way in."""
    return x if isinstance(x, Fraction) else Fraction(x).limit_denominator(10 ** 12)


def code_hash():
    h = hashlib.sha256()
    with open(os.path.abspath(__file__), "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------------------------
#  THE PUBLISHED CONSTRAINT SET. Every one of (1)-(30) is accounted for here or the self-check
#  below FAILS. "ENCODING" entries are deliberate non-checks with a stated reason.
# --------------------------------------------------------------------------------------------
PUBLISHED = {
    1:  ("SEMANTIC", ["OBJ"],                     "objective: fleet + travel, both levels"),
    2:  ("SEMANTIC", ["C2-DEG-out", "C2-DEG-in"], "each customer served exactly once by a LEFV"),
    3:  ("SEMANTIC", ["C3-FLEET"],                "LEFVs leaving = returning, <= K_s"),
    4:  ("SEMANTIC", ["C4-LASTXFER"],             "final transfer before returning to the garage"),
    5:  ("SEMANTIC", ["C5-LOAD"],                 "LEFV capacity with reset at a transfer"),
    6:  ("SEMANTIC", ["C6-ARC"],                  "street service-start timing along an arc"),
    7:  ("ENCODING", [],                          "defines f^s; recomputed, never read"),
    8:  ("DOMAIN",   ["D8-ARCSET"],               "x_ij binary"),
    9:  ("DOMAIN",   ["D9-PHI"],                  "phi_i binary"),
    10: ("SEMANTIC", ["C10-HUB"],                 "exactly one satellite iff a transfer exists"),
    11: ("SEMANTIC", ["C11-XFER-START"],          "transfer cannot start before the LEFV arrives"),
    12: ("SEMANTIC", ["C12-XFER-DEPART"],         "LEFV cannot leave the satellite until done"),
    13: ("SEMANTIC", ["C13-SYNC-lo", "C13-SYNC-hi"], "vessel-window bounds on u_i"),
    14: ("ENCODING", [],                          "defines f^s at a transfer; recomputed"),
    15: ("DOMAIN",   ["D15-HUB"],                 "v_ip binary"),
    16: ("SEMANTIC", ["C16-WDEG-out", "C16-WDEG-in"], "each transfer served once by a vessel"),
    17: ("SEMANTIC", ["C17-WFLEET"],              "vessels leaving = returning, <= K_w"),
    18: ("SEMANTIC", ["C18-WLOAD"],               "m_i <= l_i <= Q_w"),
    19: ("SEMANTIC", ["C19-WACC"],                "vessel load accumulation -- SUBSUMED: the "
                                                  "artifact carries no l_i, so l is recomputed "
                                                  "and accumulation holds by construction; the "
                                                  "falsifiable content is C18-WLOAD's capacity "
                                                  "bound"),
    20: ("SEMANTIC", ["C20-WSEQ"],                "vessel task sequencing in time"),
    21: ("ENCODING", [],                          "defines f^w depot->hub; recomputed"),
    22: ("ENCODING", [],                          "defines f^w hub->depot; recomputed"),
    23: ("ENCODING", [],                          "defines f^w hub->hub; recomputed"),
    24: ("DOMAIN",   [],                          "f^w >= 0; implied by recomputation from a metric"),
    25: ("DOMAIN",   ["D25-WARCSET"],             "y_ij binary"),
    26: ("SEMANTIC", ["C26"],                     "same-satellite transfers at least U apart"),
    27: ("ENCODING", [],                          "linearization of (26) -- NEVER checked"),
    28: ("ENCODING", [],                          "linearization of (26) -- NEVER checked"),
    29: ("ENCODING", [],                          "linearization of (26) -- NEVER checked"),
    30: ("ENCODING", [],                          "linearization of (26) -- NEVER checked"),
}

# Classes with no published constraint number: properties of the ARTIFACT, or variable-domain
# bounds stated in Table 1 rather than in a numbered row.
ARTIFACT_CLASSES = {
    "A-FIELD":      "a required field is absent from the dump",
    "A-TIMETABLE":  "no committed (h, u): not a primal result at all",
    "A-ALIEN":      "a node index outside the instance",
    "A-STRUCT":     "the routing does not form closed tours from the garage",
    "T1-H-lo":      "Table 1: h_i >= max{a_g + t_gi, a_i}",
    "T1-H-hi":      "Table 1: h_i <= min{b_g - t_ig - tau_i - U, b_i}",
}


class Finding:
    __slots__ = ("cls", "node", "lhs", "rhs", "slack", "severity", "detail")

    def __init__(self, cls, node, lhs, rhs, slack, severity, detail=""):
        self.cls, self.node = cls, node
        self.lhs, self.rhs, self.slack = lhs, rhs, slack
        self.severity, self.detail = severity, detail

    def as_dict(self):
        return {"class": self.cls, "node": self.node,
                "lhs": None if self.lhs is None else float(self.lhs),
                "rhs": None if self.rhs is None else float(self.rhs),
                "shortfall": None if self.slack is None else float(-self.slack),
                "severity": self.severity, "detail": self.detail}


class Run:
    """One verification. Every evaluation goes through `req` or `fail` -- a single path, so a
    semantics change cannot reach twelve classes and miss the thirteenth."""

    def __init__(self, label):
        self.label = label
        self.findings = []
        self.checks_run = {}
        self.missing = set()        # (kind, node) a check needed and the artifact lacks
        self.blocking = []          # doubt about WHICH INSTANCE: precedes every finding
        self.notes = []             # annotation on a verification that did happen
        self.meta = {}
        self.objective = {}

    def req(self, cls, node, lhs, rhs, detail=""):
        """Assert lhs >= rhs in exact arithmetic. Records the evaluation either way."""
        self.checks_run[cls] = self.checks_run.get(cls, 0) + 1
        if lhs is None or rhs is None:
            self.findings.append(Finding(cls, node, lhs, rhs, None, "UNEVALUATED",
                                         detail or "an operand was unavailable"))
            return False
        lhs, rhs = F(lhs), F(rhs)
        slack = lhs - rhs
        if slack >= 0:
            return True
        self.findings.append(Finding(cls, node, lhs, rhs, slack,
                                     "TOLERANCE" if -slack <= FEAS_TOL else "VIOLATION", detail))
        return False

    def eq(self, cls, node, a, b, detail=""):
        """Assert a == b, as two inequalities so the reported shortfall keeps its sign."""
        ok1 = self.req(cls, node, a, b, detail)
        ok2 = self.req(cls, node, b, a, detail)
        return ok1 and ok2

    def fail(self, cls, node, detail):
        self.checks_run[cls] = self.checks_run.get(cls, 0) + 1
        self.findings.append(Finding(cls, node, None, None, None, "VIOLATION", detail))

    def ok(self, cls):
        self.checks_run[cls] = self.checks_run.get(cls, 0) + 1

    def need(self, kind, node):
        """A value the check requires and the artifact does not carry. Never a pass (I4)."""
        self.missing.add((kind, node))
        self.checks_run["A-" + kind.upper()] = self.checks_run.get("A-" + kind.upper(), 0) + 1
        self.findings.append(Finding("A-" + kind.upper(), node, None, None, None,
                                     "UNEVALUATED", "required value absent: %s" % kind))

    @property
    def violations(self):
        return [f for f in self.findings if f.severity == "VIOLATION"]

    @property
    def unevaluated(self):
        return [f for f in self.findings if f.severity == "UNEVALUATED"]

    @property
    def tolerances(self):
        return [f for f in self.findings if f.severity == "TOLERANCE"]

    @property
    def total_checks(self):
        return sum(self.checks_run.values())

    def verdict(self):
        # 1. a blocking note means the INSTANCE is in doubt, so no finding is interpretable.
        if self.blocking:
            return NOT_CHECKED
        # 2. failures. Precedes the empty test so a run whose only signal is need() REJECTs
        #    rather than laundering into NOT_CHECKED: there is no path from a missing value
        #    to ACCEPT.
        if self.violations or self.unevaluated or self.missing:
            return REJECT
        # 3. nothing ran, so nothing passed.
        if self.total_checks == 0:
            return NOT_CHECKED
        return ACCEPT


# --------------------------------------------------------------------------------------------
#  instance + artifact
# --------------------------------------------------------------------------------------------
def tau_for(raw, size):
    """U = ceil(2 * mean customer service duration), per K's S5.1."""
    import math
    svc = [raw["customer_%d" % i]["service_time"] for i in range(1, size + 1)]
    return math.ceil(2.0 * (sum(svc) / len(svc)))


def load_instance(cell, size, proximity, wls=0.1):
    raw = instance_view.VInstance._load_json(cell)
    return instance_view.VInstance(cell, size, wls=wls, tau=tau_for(raw, size),
                                   proximity=proximity)


def resolve_proximity(sol, path):
    """The proximity the RUN used, from its own record. NEVER K's table for the size: rebuilding
    at the wrong proximity moves every satellite and therefore every distance, and a finding about
    the wrong instance means nothing. Returns (value, source); None means REFUSE."""
    for k in ("_proximity", "proximity"):
        if sol.get(k) is not None:
            return float(sol[k]), "artifact:%s" % k
    rid = sol.get("_run_id") or os.path.basename(path)[:-5]
    for log in (os.path.join(ROOT, "runs", rid + ".jsonl"),
                os.path.join(ROOT, "runs", "invalid", rid + ".jsonl")):
        if os.path.exists(log):
            try:
                txt = open(log, encoding="utf-8", errors="replace").read(200000)
                m = re.search(r'"proximity":\s*([0-9.]+)', txt)
                if m:
                    return float(m.group(1)), "run-config"
            except Exception:
                pass
    return None, "no proximity in the artifact and no run log found"


def routes_from(sol, inst, run):
    """Street routes as lists of customers, walked from the garage. Returns None if the routing
    is not a set of closed tours -- a structural failure that must stop the timing legs, or a
    broken routing emits thousands of fabricated findings downstream."""
    depot = inst.depot
    arcs = [(int(a), int(b)) for a, b in (sol.get("xij") or [])]
    nodes = set(inst.customers) | {depot}
    for a, b in arcs:
        if a not in nodes or b not in nodes:
            run.fail("A-ALIEN", (a, b), "arc touches a node outside C u {g}")
            return None
    if len(set(arcs)) != len(arcs):
        # A DUPLICATE ARC IS A DOMAIN VIOLATION, not a structural one: it says x_ij = 2, which
        # breaks (8)'s binarity. Attributing it to A-STRUCT left D8-ARCSET unreachable -- a class
        # that claimed to check (8) and could never fire. Found by the 30-impairment run.
        run.fail("D8-ARCSET", None, "duplicate arcs in xij: x_ij is not binary (8)")
        return None
    # The GARAGE legitimately has out-degree nCars and in-degree nCars -- (2)'s "exactly once"
    # binds on CUSTOMERS, and (3) is what governs the garage. Applying the customer rule to it
    # rejected every multi-route solution; caught by the code audit on an 8-route greedy26 seed.
    succ = {}
    for a, b in arcs:
        if a == depot:
            continue
        if a in succ:
            run.fail("A-STRUCT", a, "customer %s has out-degree > 1" % a)
            return None
        succ[a] = b
    routes, seen = [], set()
    for start in [b for a, b in arcs if a == depot]:
        r, cur = [], start
        while cur != depot:
            if cur in seen or len(r) > len(inst.customers) + 1:
                run.fail("A-STRUCT", cur, "route revisits %s or does not close" % cur)
                return None
            seen.add(cur)
            r.append(cur)
            if cur not in succ:
                run.fail("A-STRUCT", cur, "route leaves %s with no successor" % cur)
                return None
            cur = succ[cur]
        routes.append(r)
    run.ok("A-STRUCT")
    return routes


def vessel_routes_from(sol, inst, run):
    """Vessel tours as lists of transfer tasks, walked from the central depot d (= CDC)."""
    CDC = inst.CDC
    arcs = [(int(a), int(b)) for a, b in (sol.get("yij") or [])]
    tset = {int(c) for c in (sol.get("vi") or [])}
    ok_nodes = tset | {CDC}
    for a, b in arcs:
        if a not in ok_nodes or b not in ok_nodes:
            run.fail("A-ALIEN", (a, b), "vessel arc touches a node that is not a transfer or d")
            return None
    if len(set(arcs)) != len(arcs):
        run.fail("D25-WARCSET", None, "duplicate arcs in yij: y_ij is not binary (25)")
        return None
    succ = {}
    for a, b in arcs:
        if a != CDC:
            if a in succ:
                run.fail("A-STRUCT", a, "transfer %s has vessel out-degree > 1" % a)
                return None
            succ[a] = b
    tours, seen = [], set()
    for start in [b for a, b in arcs if a == CDC]:
        t, cur = [], start
        while cur != CDC:
            if cur in seen or len(t) > len(tset) + 1:
                run.fail("A-STRUCT", cur, "vessel tour revisits %s or does not close" % cur)
                return None
            seen.add(cur)
            t.append(cur)
            if cur not in succ:
                run.fail("A-STRUCT", cur, "vessel tour leaves %s with no successor" % cur)
                return None
            cur = succ[cur]
        tours.append(t)
    run.ok("A-STRUCT")
    return tours


# --------------------------------------------------------------------------------------------
#  LEG 1 -- structure and domains: (2) (3) (4) (8) (9) (10) (15) (16) (17) (25)
# --------------------------------------------------------------------------------------------
def leg_structure(run, sol, inst, routes, vroutes):
    depot, CDC, P = inst.depot, inst.CDC, set(inst.satellites)
    C = list(inst.customers)
    arcs = [(int(a), int(b)) for a, b in (sol.get("xij") or [])]
    tlist = [int(c) for c in (sol.get("vi") or [])]
    hubs = [int(p) for p in (sol.get("hubs") or [])]
    tset = set(tlist)

    # (8) x_ij in {0,1}: the artifact stores a SET of traversed arcs, so bivalence is
    # structural -- what must be checked is that it is a set and its nodes exist. Done in
    # routes_from; recorded here for the accounting.
    run.ok("D8-ARCSET")
    # (9) phi_i in {0,1}: the transfer list must be a set of customers.
    if len(tset) != len(tlist):
        run.fail("D9-PHI", None, "vi repeats a customer; phi is not binary")
    elif any(c not in set(C) for c in tset):
        run.fail("D9-PHI", None, "vi names a node that is not a customer")
    else:
        run.ok("D9-PHI")
    # (15) v_ip in {0,1}, and (10) exactly one satellite iff a transfer exists.
    if len(hubs) != len(tlist):
        run.fail("D15-HUB", None, "hubs has %d entries, vi has %d" % (len(hubs), len(tlist)))
    elif any(p not in P for p in hubs):
        run.fail("D15-HUB", None, "hubs names a node that is not a satellite")
    else:
        run.ok("D15-HUB")
    #   (10)  sum_p v_ip = phi_i   for all i in C
    #   The artifact stores hubs as a list PARALLEL to vi, so "exactly one satellite" is carried
    #   by the data shape. What is falsifiable is that the assignment covers exactly the
    #   transfers: a hub for every transfer, and none for any non-transfer. An earlier version
    #   of this block compared a value with itself -- always true, and it overwrote its own
    #   evaluation count on the way out.
    assigned = set(zip(tlist, hubs)) if len(hubs) == len(tlist) else set()
    have_hub = {c for c, _p in assigned}
    for c in C:
        want = c in tset
        run.req("C10-HUB", c, 1 if (c in have_hub) == want else 0, 1,
                "hub assigned iff transfer (phi_%s = %d)" % (c, int(want)))

    #   (2)  sum_j x_ij = sum_j x_ji = 1   for all i in C
    outd, ind = {}, {}
    for a, b in arcs:
        outd[a] = outd.get(a, 0) + 1
        ind[b] = ind.get(b, 0) + 1
    for c in C:
        run.eq("C2-DEG-out", c, outd.get(c, 0), 1, "out-degree")
        run.eq("C2-DEG-in", c, ind.get(c, 0), 1, "in-degree")

    #   (3)  sum_i x_gi = sum_i x_ig <= K_s ; and the claimed nCars must equal it.
    #   K's S5.1 sets the fleet unlimited, so the <= K_s half never fires here (design audit A4).
    left = sum(1 for a, b in arcs if a == depot)
    back = sum(1 for a, b in arcs if b == depot)
    run.eq("C3-FLEET", None, left, back, "LEFVs leaving vs returning")
    if sol.get("nCars") is None:
        run.need("ncars", None)
    else:
        run.eq("C3-FLEET", None, int(sol["nCars"]), left, "claimed nCars vs routes")

    #   (4)  phi_i >= x_ig : the last customer of every route must carry a transfer.
    for r in routes or []:
        if not r:
            continue
        run.req("C4-LASTXFER", r[-1], 1 if r[-1] in tset else 0, 1,
                "route ends at %s with no transfer" % r[-1])

    #   (16) sum_j y_ji = sum_j y_ij = sum_p v_ip : every transfer served exactly once by a vessel.
    warcs = [(int(a), int(b)) for a, b in (sol.get("yij") or [])]
    woutd, wind = {}, {}
    for a, b in warcs:
        woutd[a] = woutd.get(a, 0) + 1
        wind[b] = wind.get(b, 0) + 1
    for c in C:
        want = 1 if c in tset else 0
        run.eq("C16-WDEG-out", c, woutd.get(c, 0), want)
        run.eq("C16-WDEG-in", c, wind.get(c, 0), want)

    #   (17) sum_i y_di = sum_i y_id <= K_w ; claimed nVessel must equal it. K_w unlimited: see A4.
    wleft = sum(1 for a, b in warcs if a == CDC)
    wback = sum(1 for a, b in warcs if b == CDC)
    run.eq("C17-WFLEET", None, wleft, wback, "vessels leaving vs returning")
    if sol.get("nVessel") is None:
        run.need("nvessel", None)
    else:
        run.eq("C17-WFLEET", None, int(sol["nVessel"]), wleft, "claimed nVessel vs tours")

    #   (25) y_ij in {0,1}: a set of pairs over C_w.
    # duplicates are caught earlier, in vessel_routes_from, where the walk needs a clean arc set
    run.ok("D25-WARCSET")

    return dict(zip(tlist, hubs)), tset


# --------------------------------------------------------------------------------------------
#  LEG 2 -- loads: (5) (18) (19)
# --------------------------------------------------------------------------------------------
def leg_loads(run, sol, inst, routes, hub_of, tset):
    Qs = instance_view.LEFV_CAPACITY
    Qw = instance_view.VESSEL_CAPACITY
    nd = inst.nodes

    #   (5)  m_j - m_i >= q_j - Q_s(1 - x_ij + phi_i), with q_i <= m_i <= Q_s (Table 1).
    #   Recomputed forward along each route: load accumulates and RESETS after a transfer, which
    #   is what the phi_i term in (5) expresses.
    trip_load = {}          # transfer -> demand of the street trip feeding it
    for r in routes or []:
        load = Fraction(0)
        for c in r:
            load += F(nd[c].demand)
            run.req("C5-LOAD", c, F(Qs), load, "LEFV load after %s" % c)
            run.req("C5-LOAD", c, load, F(nd[c].demand), "m_i >= q_i")
            if c in tset:
                trip_load[c] = load
                load = Fraction(0)

    return trip_load, Qw


def leg_vessel_loads(run, inst, vroutes, trip_load, Qw):
    for t in vroutes or []:
        load = Fraction(0)
        for c in t:
            if c not in trip_load:
                run.need("trip_load", c)
                continue
            load += trip_load[c]
            run.req("C18-WLOAD", c, F(Qw), load, "vessel load after task %s" % c)
            # (19) IS NOT INDEPENDENTLY CHECKABLE HERE, and a class that cannot fire is worse
            # than no class. The artifact carries no l_i, so l is RECOMPUTED by accumulating the
            # trip loads along the tour -- which satisfies (19)'s accumulation BY CONSTRUCTION.
            # The earlier C19-WACC asserted `load >= trip_load[c]` immediately after adding
            # trip_load[c] to load: always true for non-negative demand. It never fired in 30
            # impairments, and inspection shows it never could. The falsifiable content of (19)
            # is the CAPACITY bound, which is C18-WLOAD above.
            run.ok("C19-WACC")


# --------------------------------------------------------------------------------------------
#  LEG 3 -- timing: (6) (11) (12) (13) (26) + Table 1's h_i bounds
# --------------------------------------------------------------------------------------------
def leg_timing(run, sol, inst, routes, vroutes, hub_of, tset):
    nd, D = inst.nodes, inst.D
    g, d, U = inst.depot, inst.CDC, F(inst.tau)
    H = {int(k): F(v) for k, v in (sol.get("hi") or {}).items()}
    Uu = {int(k): F(v) for k, v in (sol.get("ui") or {}).items()}

    if not H and not Uu:
        # V1 requires a complete committed (h, u). Without one this is not a primal result,
        # and per I4 a missing required value REJECTs rather than laundering into NOT_CHECKED.
        run.need("timetable", None)
        return

    def h(c):
        if c not in H:
            run.need("h", c)
            return None
        return H[c]

    def u(c):
        if c not in Uu:
            run.need("u", c)
            return None
        return Uu[c]

    def t(a, b):
        return F(D[a][b])

    # Table 1:  max{a_g + t_gi, a_i} <= h_i <= min{b_g - t_ig - tau_i - U, b_i}
    # (reading resolved in the design audit A1: two terms in the max, three subtractions in the
    #  min, corroborated independently by the builder's declaration plus its (7) rows)
    for r in routes or []:
        for c in r:
            hc = h(c)
            run.req("T1-H-lo", c, hc, F(nd[c].earliest), "h_i >= a_i")
            run.req("T1-H-lo", c, hc, F(nd[g].earliest) + t(g, c), "h_i >= a_g + t_gi")
            run.req("T1-H-hi", c, F(nd[c].latest), hc, "h_i <= b_i")
            run.req("T1-H-hi", c, F(nd[g].latest) - t(c, g) - F(nd[c].service) - U, hc,
                    "h_i <= b_g - t_ig - tau_i - U")

    #   (6)  h_i + tau_i + f^s_ij + U*phi_i <= h_j        on a traversed arc (i,j)
    #   f^s is RECOMPUTED, never read: t_ij plain, t_ip + t_pj through the hub at a transfer.
    #   NOTE (design audit A3): on a transfer arc this row is IMPLIED by (11) and (12) --
    #     (11) u_i >= h_i + tau_i + t_ip ; (12) h_j >= u_i + U + t_pj  =>  (6) with phi_i = 1.
    #   It is still evaluated: a redundant check that passes costs nothing and guards against an
    #   error in either premise. It must NOT be counted as independent evidence.
    for r in routes or []:
        prev = None
        for c in r:
            if prev is not None:
                hp, hc = h(prev), h(c)
                if prev in tset:
                    p = hub_of.get(prev)
                    if p is None:
                        run.fail("C6-ARC", c, "transfer %s has no hub" % prev)
                    else:
                        run.req("C6-ARC", c, hc,
                                None if hp is None else hp + F(nd[prev].service)
                                + t(prev, p) + t(p, c) + U,
                                "(6) at a transfer -- IMPLIED by (11)+(12)")
                else:
                    run.req("C6-ARC", c, hc,
                            None if hp is None else hp + F(nd[prev].service) + t(prev, c),
                            "(6) on a plain arc")
            prev = c

    #   (11) u_i >= h_i + tau_i + sum_p t_ip v_ip
    #   (12) u_i + sum_p (U + t_pj) v_ip <= h_j   for the successor j on the route
    #   (13) a_d + sum_p t_dp v_ip <= u_i <= b_d - sum_p (U + t_pd) v_ip
    for r in routes or []:
        for idx, c in enumerate(r):
            if c not in tset:
                continue
            p = hub_of.get(c)
            if p is None:
                run.fail("C11-XFER-START", c, "transfer %s has no hub" % c)
                continue
            hc, uc = h(c), u(c)
            run.req("C11-XFER-START", c, uc,
                    None if hc is None else hc + F(nd[c].service) + t(c, p), "(11)")
            nxt = r[idx + 1] if idx + 1 < len(r) else g
            if nxt != g:
                run.req("C12-XFER-DEPART", nxt, h(nxt),
                        None if uc is None else uc + U + t(p, nxt), "(12)")
            else:
                # j = g is in C_s, so (12) applies to the return to the garage too.
                run.req("C12-XFER-DEPART", g, F(nd[g].latest),
                        None if uc is None else uc + U + t(p, g), "(12) with j = g")
            run.req("C13-SYNC-lo", c, uc, F(nd[d].earliest) + t(d, p), "(13) lower")
            run.req("C13-SYNC-hi", c, F(nd[d].latest) - U - t(p, d), uc, "(13) upper")

    #   (26) |u_i - u_j| >= U (v_ip + v_jp - 1)      for all i,j in C, i != j, p in P
    #   CHECKED IN ITS ORIGINAL FORM. (27)-(30) are never read: they are an ENCODING of this, and
    #   every violating timetable satisfies them -- which is exactly how 14 of 17 |C|=100 dumps
    #   passed a check that looked at the encoding instead.
    #   Sorting each satellite's transfers by u makes the minimum gap fall on a CONSECUTIVE pair,
    #   so consecutive testing is equivalent to the full pairwise statement.
    if U > 0:
        by_sat = {}
        for c in tset:
            p = hub_of.get(c)
            if p is not None:
                by_sat.setdefault(p, []).append(c)
        for p, members in sorted(by_sat.items()):
            have = [c for c in members if c in Uu]
            for c in members:
                if c not in Uu:
                    run.need("u", c)
            if len(have) < 2:
                continue
            ordered = sorted(have, key=lambda c: Uu[c])
            for a, b in zip(ordered, ordered[1:]):
                run.req("C26", b, Uu[b] - Uu[a], U,
                        "transfers %s and %s share satellite %s" % (a, b, p))

    #   (20) u_i + U + f^w_ij <= u_j  along a vessel tour. f^w RECOMPUTED between hubs.
    for t_ in (vroutes or []):
        for a, b in zip(t_, t_[1:]):
            pa, pb = hub_of.get(a), hub_of.get(b)
            if pa is None or pb is None:
                run.fail("C20-WSEQ", b, "vessel arc %s->%s touches a task with no hub" % (a, b))
                continue
            ua = u(a)
            run.req("C20-WSEQ", b, u(b),
                    None if ua is None else ua + U + t(pa, pb), "(20)")


# --------------------------------------------------------------------------------------------
#  LEG 4 -- objective (1), with f^s and f^w recomputed from (7)(14)(21)(22)(23)
# --------------------------------------------------------------------------------------------
def leg_objective(run, sol, inst, routes, vroutes, hub_of, tset):
    nd, D = inst.nodes, inst.D
    g, d = inst.depot, inst.CDC

    #   f^s: per (7) and (14), the realised street travel on arc (i,j) is t_ij, or t_ip + t_pj
    #   when a transfer at satellite p happens immediately after i. Recomputed, never read.
    street = Fraction(0)
    for r in routes or []:
        prev = g
        for c in r:
            if prev in tset:
                p = hub_of.get(prev)
                if p is None:
                    run.fail("OBJ", prev, "transfer with no hub in the street cost")
                    return
                street += F(D[prev][p]) + F(D[p][c])
            else:
                street += F(D[prev][c])
            prev = c
        if prev in tset:
            p = hub_of.get(prev)
            street += F(D[prev][p]) + F(D[p][g])
        else:
            street += F(D[prev][g])

    #   f^w: per (21)(22)(23), water travel is measured between the HUBS of consecutive tasks,
    #   with the central depot mapping to itself.
    water = Fraction(0)
    for t_ in vroutes or []:
        prev = d
        for c in t_:
            pc = hub_of.get(c)
            if pc is None:
                run.fail("OBJ", c, "vessel task with no hub in the water cost")
                return
            water += F(D[d if prev == d else hub_of[prev]][pc])
            prev = c
        water += F(D[hub_of[prev]][d]) if prev != d else Fraction(0)

    n_cars = len(routes or [])
    n_vessel = len(vroutes or [])
    z = (F(inst.penalty_cars) * n_cars + F(inst.penalty_vessels) * n_vessel
         + F(inst.travelcoststreet) * street + F(inst.travelcostwater) * water)

    claimed = sol.get("objVal")
    run.objective = {"recomputed": float(z), "claimed": None if claimed is None else float(claimed),
                     "street": float(street), "water": float(water),
                     "n_cars": n_cars, "n_vessel": n_vessel}

    if claimed is None:
        run.need("objVal", None)
        return
    #   ASYMMETRIC, per design audit A2. f^s and f^w are only LOWER-bounded by (7)(14)(21)-(23)
    #   and pushed down by (1), so a feasible-but-non-optimal point may report MORE travel than it
    #   realises. That is legal. Claiming LESS than the routing supports is not.
    c = F(claimed)
    run.req("OBJ", None, c, z - FEAS_TOL, "claimed must not be below the recomputed objective")
    if c > z + FEAS_TOL:
        run.notes.append("claimed objective %.4f exceeds the recomputed %.4f: legal (f^s/f^w are "
                         "only lower-bounded) but non-minimal" % (float(c), float(z)))


# --------------------------------------------------------------------------------------------
#  drivers
# --------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------------
# d243: PROVENANCE. A solution can satisfy every published constraint and still not be a
# production artifact, because the MODEL that produced it was not the one we decided on. That is
# not a feasibility question -- a (26)-compliant timetable is (26)-compliant however it arose --
# so it is reported on its OWN axis and never folded into ACCEPT/REJECT.
#
# The oracle deliberately runs the faithful arm (L3 asks whether we reproduce K's implementation,
# which requires K's constants), so this is PARAMETERISED. `expect="production"` is what an
# engine passes; `expect="any"` is what the oracle passes.
PRODUCTION = "PRODUCTION"
NON_PRODUCTION = "NON-PRODUCTION"
UNDECLARED = "UNDECLARED"


def provenance(sol):
    """(status, reasons) from the artifact's own declared configuration.

    Reads only fields the artifact declares about ITSELF. An artifact that declares nothing is
    UNDECLARED, not PRODUCTION: silence is not compliance, and the pre-d243 corpus is exactly the
    silent case.
    """
    reasons = []
    posts = sol.get("_posts_26")
    bigm = sol.get("_valid_bigm")
    if posts is None and bigm is None:
        return UNDECLARED, ["the artifact declares neither _posts_26 nor _valid_bigm"]
    if posts is None:
        reasons.append("_posts_26 not declared")
    elif not posts:
        reasons.append("produced with the VACUOUS (27)-(30): the model could not represent (26)")
    if bigm is None:
        reasons.append("_valid_bigm not declared -- predates d243, so K's undersized constants "
                       "in (14)/(22) were in force and the objective may be inflated")
    elif not bigm:
        reasons.append("produced with K's UNDERSIZED big-Ms: the model was over-tight")
    return (PRODUCTION if not reasons else NON_PRODUCTION), reasons


def verify_solution(inst, sol, cell=None, size=None, proximity=None, label="<in-memory>"):
    """Verify a committed assignment. No file, no solver, no search."""
    run = Run(label)
    run.meta.update({"cell": cell or getattr(inst, "name", None),
                     "size": size or getattr(inst, "size", None),
                     "proximity": proximity if proximity is not None
                     else getattr(inst, "proximity", None),
                     "tau": getattr(inst, "tau", None),
                     "run_id": sol.get("_run_id")})
    prov, why = provenance(sol)
    run.meta["provenance"] = prov
    run.meta["provenance_reasons"] = why

    for key in ("xij", "vi", "hubs", "yij", "nCars", "nVessel"):
        if sol.get(key) is None:
            run.fail("A-FIELD", key, "required field %r absent" % key)
        else:
            run.ok("A-FIELD")

    routes = routes_from(sol, inst, run)
    vroutes = vessel_routes_from(sol, inst, run)
    if routes is None or vroutes is None:
        return run                      # structural failure: the later legs would fabricate

    hub_of, tset = leg_structure(run, sol, inst, routes, vroutes)
    trip_load, Qw = leg_loads(run, sol, inst, routes, hub_of, tset)
    leg_vessel_loads(run, inst, vroutes, trip_load, Qw)
    leg_timing(run, sol, inst, routes, vroutes, hub_of, tset)
    leg_objective(run, sol, inst, routes, vroutes, hub_of, tset)
    return run


def verify(path):
    run = Run(os.path.basename(path))
    try:
        sol = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        run.blocking.append("unreadable dump (%s)" % type(e).__name__)
        return run
    m = re.search(r"(?:^|_)((?:RC|R|C)\d{3})_n(\d+)", os.path.basename(path))
    if not m:
        run.blocking.append("cell/size not parseable from the filename")
        return run
    cell, size = m.group(1), int(m.group(2))
    prox, psrc = resolve_proximity(sol, path)
    if prox is None:
        run.blocking.append("proximity unresolvable (%s) -- refusing to invent one" % psrc)
        return run
    inst = load_instance(cell, size, prox)
    out = verify_solution(inst, sol, cell=cell, size=size, proximity=prox,
                          label=os.path.basename(path))
    out.meta["proximity_source"] = psrc
    return out


def completeness():
    """Every published constraint (1)-(30) must be accounted for: checked, or declared ENCODING /
    DOMAIN with a reason. Returns a list of failures; empty means accounted for."""
    errs = []
    for n in range(1, 31):
        if n not in PUBLISHED:
            errs.append("published constraint (%d) is unaccounted for" % n)
            continue
        kind, classes, why = PUBLISHED[n]
        if kind == "SEMANTIC" and not classes:
            errs.append("(%d) is SEMANTIC but names no class" % n)
        if not why:
            errs.append("(%d) has no stated reason" % n)
    return errs


class Verdict3:
    """What an ENGINE consumes: .ok, .recomputed_obj, .violations. ACCEPT and only ACCEPT is ok --
    NOT_CHECKED means "we could not check it", which an engine must treat as "do not bank it"."""

    __slots__ = ("run", "ok", "recomputed_obj", "violations", "verdict")

    def __init__(self, run):
        self.run = run
        self.verdict = run.verdict()
        self.ok = (self.verdict == ACCEPT)
        self.recomputed_obj = run.objective.get("recomputed") if run.objective else None
        self.violations = ["%s%s: %s" % (f.cls, "" if f.node is None else "[%s]" % (f.node,),
                                         f.detail or f.severity)
                           for f in run.findings
                           if f.severity in ("VIOLATION", "UNEVALUATED")] + \
                          ["BLOCKING: %s" % b for b in run.blocking]


def verify_for_engine(inst, sol, cell=None, size=None, proximity=None, label="<engine>",
                      expect="production"):
    """What an ENGINE calls: returns a Verdict3 exposing .ok / .recomputed_obj / .violations.

    Kept separate from verify_solution (which returns the full Run) so an engine cannot
    accidentally consume a Run and read `.ok` off an object that does not have one.

    expect="production" (d243, the default for an engine) additionally requires the artifact to
    declare the production configuration. A feasible solution from the faithful arm is still
    feasible -- it is just not a result we may quote -- so the refusal is recorded as BLOCKING,
    which keeps it out of `.ok` without pretending the solution violates a constraint.

    The oracle passes expect="any": L3 and L4 run the faithful arm deliberately.
    """
    run = verify_solution(inst, sol, cell=cell, size=size, proximity=proximity, label=label)
    if expect == "production" and run.meta.get("provenance") != PRODUCTION:
        run.blocking.append("d243 provenance: %s -- %s"
                            % (run.meta.get("provenance"),
                               "; ".join(run.meta.get("provenance_reasons") or [])))
    return Verdict3(run)


def record(run):
    return {"solution": run.label, "verdict": run.verdict(), "meta": run.meta,
            "checks_run": run.checks_run, "total_checks": run.total_checks,
            "counts": {"violations": len(run.violations), "tolerances": len(run.tolerances),
                       "unevaluated": len(run.unevaluated), "missing": len(run.missing)},
            "objective": run.objective, "notes": run.notes,
            "findings": [f.as_dict() for f in run.findings], "code_hash": code_hash()}


def main():
    errs = completeness()
    if errs:
        print("REFUSING -- the published constraint set is not fully accounted for:")
        for e in errs:
            print("   " + e)
        return 3

    pats = sys.argv[1:] or ["runs/solutions/*.json"]
    files = []
    for p in pats:
        files.extend(sorted(glob.glob(p if os.path.isabs(p) else os.path.join(ROOT, p))))
    print(__doc__.strip().splitlines()[0])
    print("code_hash %s   %d file(s)   published constraints accounted for: 30/30"
          % (code_hash(), len(files)))
    print()
    hdr = "%-34s %-11s %7s %6s %5s %5s | %s" % ("solution", "verdict", "checks", "viol",
                                                "tol", "unev", "worst finding")
    print(hdr)
    print("-" * len(hdr))
    tally, recs = {}, []
    for f in files:
        run = verify(f)
        v = run.verdict()
        tally[v] = tally.get(v, 0) + 1
        worst = ""
        vs = run.violations
        if vs:
            w = max(vs, key=lambda x: abs(float(x.slack)) if x.slack is not None else 0)
            worst = "%s%s" % (w.cls, (" by %.6f" % abs(float(w.slack))) if w.slack is not None
                              else " " + (w.detail or "")[:40])
        elif run.blocking:
            worst = "BLOCKING: " + run.blocking[0][:40]
        print("%-34s %-11s %7d %6d %5d %5d | %s"
              % (run.label[:34], v, run.total_checks, len(vs), len(run.tolerances),
                 len(run.unevaluated), worst))
        recs.append(record(run))
    print()
    print("  " + " | ".join("%s %d" % (k, tally[k]) for k in sorted(tally))
          + "   = %d" % len(files))
    classes = {}
    for r in recs:
        for k, n in r["checks_run"].items():
            classes[k] = classes.get(k, 0) + n
    print("  %d evaluations over %d classes" % (sum(classes.values()), len(classes)))
    out = os.path.join(ROOT, "logs", "verifier3.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, default=str) + "\n")
    print("  -> %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
