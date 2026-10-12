"""ARITHMETIC VERIFIER VARIANT -- no solver, no search, no CP-SAT. A PARALLEL DIAGNOSTIC.

IT DOES NOT REPLACE verifier.py. The incumbent verifier remains the authority until this code is
audited and frozen (author, 2026-09-18: *"we won't drop current verifier until we have frozen our
bug analysis and replacing code stainless steel validity"*).

WHY THIS EXISTS -- the author's argument, 2026-09-18:

    *"Primal produces an incumbent, verifier has to do 2 simple things: check all constraints are
    respected and verify OV value. Both simple mathematical inequality/equality checks. No
    solve/search required. Am i right?"*

Yes. `verifier._schedule_feasible` asks CP-SAT whether ANY timetable exists for the committed
ROUTING, discarding the `h_i`/`u_i` the incumbent carries. That answers a question about a
DIFFERENT object than the one being verified. Measured across every solution store: 433 of 434
stored solutions carry a COMPLETE timetable (every visited customer has an h, every declared
transfer has a u), and the sole exception is `cov_C207_n100_s0.json`, an unimproved construction.
So the search was run on the wrong object 433 times, returned ok=True, and 14 |C| = 100 dumps --
six of them from ACCEPTED runs -- were infeasible throughout (d216, d225).

WHY NO SEARCH IS NEEDED, including for constraint (26). Eleven of the twelve constraint classes are
difference constraints `x - y >= c`; evaluating one is a subtraction and a comparison. (26) is
`|u_i - u_j| >= tau`, a DISJUNCTION, and a disjunction is what forces a search -- but ONLY when the
values are unknown. Given the committed u, it is one subtraction per same-satellite pair. The
NP-hardness lives entirely in FINDING a timetable, never in CHECKING one.

WHAT IS AND IS NOT SHARED WITH verifier.py (Rule 3 independence):
  * SHARED, deliberately: `VInstance` -- coordinates, distances, time windows, tau, cost
    coefficients. That is INSTANCE GROUND TRUTH, not verification logic, and re-deriving it would
    add my own transcription risk without adding independence. Importing it does NOT pull OR-Tools:
    verifier.py imports cp_model lazily at line 216, inside `_schedule_feasible`.
  * NOT SHARED: every structural derivation and every check below. Routes, hub_of, tset and
    vroutes are re-derived HERE from the dump, so a defect in the verifier's derivation cannot
    propagate into this variant's verdict. Audit 9 cross-checks the two derivations on the corpus.

THREE LEGS, all arithmetic:
  LEG 1 STRUCTURE  -- the routing is well-formed and the fleet counts are what the dump claims.
  LEG 2 TIMETABLE  -- the committed {h_i, u_i} satisfies all twelve constraint classes.
  LEG 3 OBJECTIVE  -- z recomputed from the routing equals the claimed objVal.

ROUNDING. Bounds use the model's own permissive `lo = floor(x*1000)` / `hi = ceil(x*1000)`. The
COMMITTED value is made permissive PER ROLE (design audit 1, fix F5): ceil where it is the LHS of a
`>=`, floor where it is the LHS of a `<=` or sits inside the RHS of a `>=`. Under `int(round(...))`
on both sides a satisfied constraint could be reported violated by up to 0.001 and a real violation
of up to 0.002 hidden; under role-permissive rounding NO REPORTED VIOLATION CAN BE MANUFACTURED.
Magnitudes at or below INDET are reported INDETERMINATE rather than VIOLATION.
"""
import glob, json, math, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCALE = 1000
INDET = 0.002          # display annotation only -- see rec(); audit 4 C3
OBJ_TOL = 1e-6
TOL = 1e-6
LEFV_CAPACITY = 50     # verifier.py:29-30 -- the same constants, not a re-derivation
VESSEL_CAPACITY = 250

# ---------------------------------------------------------------- rounding helpers
lo = lambda x: math.floor(x * SCALE)      # permissive lower bound (model side)
hi = lambda x: math.ceil(x * SCALE)       # permissive upper bound (model side)
up = lambda x: math.ceil(x * SCALE)       # committed value, LHS of a ">="  -> round UP
dn = lambda x: math.floor(x * SCALE)      # committed value, LHS of a "<=" or inside a ">=" RHS


class Result:
    def __init__(self, path):
        self.path = path
        self.structure = []       # LEG 1 failures
        self.timetable = []       # LEG 2 (class, node, magnitude)
        self.indeterminate = []   # LEG 2, magnitude <= INDET
        self.missing = []         # committed value absent
        self.obj_claimed = None
        self.obj_recomputed = None
        self.obj_matches = None
        self.components = {}
        self.notes = []
        self.meta = {}            # cell, size, proximity, proximity_source, tau -- for record()

    @property
    def checked(self):
        return not self.notes or "NOT-CHECKED" not in " ".join(self.notes)

    @property
    def ok(self):
        # AUDIT 2, finding 5: `ok` did not consult `notes`, so a solution on which NOTHING was
        # evaluated -- no committed timetable, or an unresolvable proximity -- returned ok=True.
        # A verdict of "fine" from a check that never ran is the defect d219 records, and this is
        # the second time this file family has produced it.
        if not self.checked:
            return False
        return (not self.structure and not self.timetable and not self.missing
                and self.obj_matches is True)


# ---------------------------------------------------------------- structure, from the dump
def derive(sol, inst):
    """Re-derive routes / hub_of / tset / vroutes FROM THE DUMP. Shares no code with verifier.py.

    Returns (routes, hub_of, tset, vroutes, problems). `problems` are structural failures; a
    structurally broken dump yields whatever could be derived plus the reasons, never an exception.
    """
    problems = []
    depot, CDC = inst.depot, inst.CDC
    xij = [tuple(e) for e in (sol.get("xij") or [])]
    yij = [tuple(e) for e in (sol.get("yij") or [])]
    vi = list(sol.get("vi") or [])
    hubs = list(sol.get("hubs") or [])

    if len(vi) != len(hubs):
        problems.append("S-HUBLEN: vi has %d entries, hubs has %d" % (len(vi), len(hubs)))
    hub_of = {c: h for c, h in zip(vi, hubs)}
    tset = set(vi)
    for c, h in hub_of.items():
        if h not in getattr(inst, "satellites", []):
            problems.append("S-HUBNODE: transfer %s assigned to non-satellite %s" % (c, h))

    # ---- street routes: follow successors out of the depot
    out, inn = {}, {}
    for (i, j) in xij:
        out.setdefault(i, []).append(j)
        inn.setdefault(j, []).append(i)
    served = set()
    for n in set(list(out) + list(inn)):
        if n == depot:
            continue
        if len(out.get(n, [])) != 1 or len(inn.get(n, [])) != 1:
            problems.append("S-DEGREE: node %s out=%s in=%s (want 1/1)"
                            % (n, len(out.get(n, [])), len(inn.get(n, []))))
    routes = []
    for first in out.get(depot, []):
        r, node, guard = [], first, 0
        while node != depot and guard < 100000:
            r.append(node)
            served.add(node)
            nxt = out.get(node, [])
            if len(nxt) != 1:
                problems.append("S-BROKEN: street route breaks at %s (successors %s)" % (node, nxt))
                break
            node = nxt[0]
            guard += 1
        routes.append(r)
    n_routes = len(out.get(depot, []))
    if "nCars" in sol and sol["nCars"] != n_routes:
        problems.append("S-FLEET-STREET: nCars claimed %s, routes from depot %d"
                        % (sol["nCars"], n_routes))
    # every customer served exactly once
    allc = set(n for n in set(list(out) + list(inn)) if n != depot)
    dup = [c for c in allc if len(out.get(c, [])) > 1]
    if dup:
        problems.append("S-MULTI: node(s) with several successors %s" % sorted(dup)[:6])
    unreached = sorted(allc - served)
    if unreached:
        problems.append("S-UNREACHED: %d node(s) not on any depot route, e.g. %s"
                        % (len(unreached), unreached[:6]))

    # AUDITS 2 and 3, both BLOCKING and both demonstrated with live mutations: the customer set
    # was built FROM THE ARCS, so a customer absent from xij entirely never entered the candidate
    # set and no degree test could fire. Splice a customer out and this tool said "fully ok" while
    # verifier.py said S-ASSIGN. inst.customers had ZERO references in this file.
    cust = set(getattr(inst, "customers", []) or [])
    if cust:
        lost = sorted(cust - served)
        if lost:
            problems.append("S-COVER: %d instance customer(s) served by no route, e.g. %s"
                            % (len(lost), lost[:6]))
        alien = sorted(n for n in allc if n not in cust and n != depot)
        if alien:
            # verifier.py:350 tests only served-vs-customers and so ACCEPTS a phantom street
            # subtour over satellite ids (audit 3, C12). This direction is ours, not inherited.
            problems.append("S-ALIEN: %d node(s) in xij are neither depot nor customer: %s"
                            % (len(alien), alien[:6]))

    # S-LASTXFER (verifier.py:363-365): an LEFV must unload at a satellite before returning.
    for r in routes:
        if r and r[-1] not in tset:
            problems.append("S-LASTXFER: route ending at %s does not end in a transfer" % r[-1])

    # S-LOAD (verifier.py:369-377): cumulative demand per TRIP, reset at each transfer.
    trip_load = {}
    for r in routes:
        load = 0.0
        for c in r:
            load += getattr(inst.nodes[c], "demand", 0.0)
            if c in tset:
                if load > LEFV_CAPACITY + TOL:
                    problems.append("S-LOAD: trip ending at transfer %s carries %.3f > %s"
                                    % (c, load, LEFV_CAPACITY))
                trip_load[c] = load
                load = 0.0
        if load > TOL:
            problems.append("S-RESIDUAL: route %s leaves %.3f demand after its last transfer"
                            % (r[:4], load))

    # Duplicate vi entries (audit 3, C6): hub_of is a dict, so a repeated customer paired with a
    # different satellite is silently last-write-wins and S-HUBNODE never sees the shadowed one.
    if len(vi) != len(set(vi)):
        dups = sorted({c for c in vi if vi.count(c) > 1})
        problems.append("S-VIDUP: vi lists %s more than once; hub assignment is ambiguous" % dups[:5])
    for c, h in zip(vi, hubs):
        if h not in getattr(inst, "satellites", []):
            problems.append("S-HUBNODE-LIST: transfer %s paired with non-satellite %s" % (c, h))

    # ---- vessel routes: follow successors out of the CDC
    vout, vin = {}, {}
    for (i, j) in yij:
        vout.setdefault(i, []).append(j)
        vin.setdefault(j, []).append(i)
    for c in tset:
        if len(vout.get(c, [])) != 1 or len(vin.get(c, [])) != 1:
            problems.append("S-WASSIGN: transfer %s vessel out=%s in=%s"
                            % (c, vout.get(c, []), vin.get(c, [])))
    vroutes = []
    for first in vout.get(CDC, []):
        vr, node, guard = [], first, 0
        while node != CDC and guard < 100000:
            vr.append(node)
            nxt = vout.get(node, [])
            if len(nxt) != 1:
                problems.append("S-WBROKEN: vessel route breaks at %s" % node)
                break
            node = nxt[0]
            guard += 1
        vroutes.append(vr)
    n_vessel = len(vout.get(CDC, []))
    if "nVessel" in sol and sol["nVessel"] != n_vessel:
        problems.append("S-FLEET-WATER: nVessel claimed %s, vessel routes from CDC %d"
                        % (sol["nVessel"], n_vessel))
    covered = sorted(c for vr in vroutes for c in vr)
    if covered != sorted(tset):
        extra = sorted(set(covered) - tset)
        lost = sorted(tset - set(covered))
        problems.append("S-WCOVER: vessel routes cover %d transfers vs %d declared "
                        "(extra %s, uncovered %s)" % (len(covered), len(tset), extra[:5], lost[:5]))

    # W-LOAD (verifier.py:473-477) and W-VESSEL-LB (verifier.py:451-452). These must sit AFTER
    # vroutes and n_vessel exist -- I first placed them beside the street-side checks and the tool
    # died with UnboundLocalError on every dump.
    for vr in vroutes:
        load = 0.0
        for c in vr:
            load += trip_load.get(c, getattr(inst.nodes[c], "demand", 0.0))
            if load > VESSEL_CAPACITY + TOL:
                problems.append("W-LOAD: vessel route through %s reaches %.3f > %s"
                                % (c, load, VESSEL_CAPACITY))
                break
    minv = getattr(inst, "min_vessels", None)
    if minv is not None and n_vessel < minv:
        problems.append("W-VESSEL-LB: %d vessels < lower bound %d (ceil(total demand / %d))"
                        % (n_vessel, minv, VESSEL_CAPACITY))
    return routes, hub_of, tset, vroutes, problems


# ---------------------------------------------------------------- LEG 2, the twelve classes
def check_timetable(inst, routes, hub_of, tset, vroutes, H, U, res):
    D, nd = inst.D, inst.nodes
    CDC, depot, tau = inst.CDC, inst.depot, inst.tau

    def rec(kind, c, lhs, rhs, op):
        """lhs/rhs already scaled ints. op '>=' means lhs must be >= rhs."""
        if lhs is None or rhs is None:
            return
        gap = (rhs - lhs) if op == ">=" else (lhs - rhs)
        if gap > 0:
            # AUDIT 4, C3: under ROLE-PERMISSIVE rounding every gap > 0 is a GENUINE violation.
            # For a ">=": gap>0 means floor(1000y)+floor(1000a) > ceil(1000x), and since
            # floor(.) <= the real value and ceil(.) >= it, that forces y+a > x strictly. So the
            # 0.002 band -- derived for the OLD int(round(.)) scheme, where false positives were
            # possible -- is now a pure FALSE-NEGATIVE generator. Every violation is recorded;
            # INDETERMINATE survives only as a DISPLAY annotation on the small ones.
            mag = gap / SCALE
            res.timetable.append((kind, c, mag))
            if mag <= INDET:
                res.indeterminate.append((kind, c, mag))

    def h_ge(c):                      # committed h as the LHS of a ">=" -> permissive UP
        if c not in H:
            res.missing.append(("h", c)); return None
        return up(H[c])

    def h_le(c):                      # committed h as the LHS of a "<=" -> permissive DOWN
        if c not in H:
            res.missing.append(("h", c)); return None
        return dn(H[c])

    def h_rhs(c):                     # committed h inside the RHS of a ">=" -> permissive DOWN
        return dn(H[c]) if c in H else None

    def u_ge(c):
        if c not in U:
            res.missing.append(("u", c)); return None
        return up(U[c])

    def u_le(c):
        if c not in U:
            res.missing.append(("u", c)); return None
        return dn(U[c])

    def u_rhs(c):
        return dn(U[c]) if c in U else None

    # 1/2 -- street time windows
    for r in routes:
        for c in r:
            rec("S-TW-lower", c, h_ge(c), lo(nd[c].earliest), ">=")
            rec("S-TW-upper", c, h_le(c), hi(nd[c].latest), "<=")

    # 3-9 -- arc timing, depot upper bound, transfer and synchronisation bounds
    for r in routes:
        prev, prev_xfer = depot, False
        for c in r:
            # AUDIT 4, C1: K post BOTH halves of Const7 `for i in Customers`
            # (integratedJointModel.py:93-95, joint_model_cplex.py:135-137) -- every customer, not
            # only the route-first one. verifier.py:234 posts the LOWER half inside the
            # `prev == depot` branch, so its CP-SAT model is a RELAXATION of K's here, and this
            # variant inherited that. Checked explicitly now, as a 13th class.
            # I FIRST JUSTIFIED THIS AS FREE AND THE JUSTIFICATION WAS WRONG. I argued the arc
            # chain back to the depot implies this bound for interior customers by the triangle
            # inequality, having sampled 40,000 random triples on three instances and found zero
            # violations. Audit 1 checked all 66 instances EXHAUSTIVELY and found 16 that violate
            # it. Re-run exhaustively: R204/n100 and R202/n100 have 18 violating triples each,
            # RC201/n100 has 8, worst 0.0100 -- e.g. D[10][16] = 44.72 > D[10][88] + D[88][16] =
            # 8.94 + 35.77 = 44.71, a 2-decimal rounding artifact of verifier.py:126-133's single
            # non-convergent pass. 0.0100 EXCEEDS the 0.002 band. There are only 18 violating
            # triples among ~1.19M, so my sample had about a coin-flip chance of seeing any and I
            # reported the miss as a result. The implication argument does not hold, so this check
            # is load-bearing, not free. Empirically still latent: audit 1 swept 238 dumps and
            # found no Const7-lower violation on a non-first customer.
            rec("S-TW-DEP-LB", c, h_ge(c), lo(nd[depot].earliest + D[depot][c]), ">=")
            if prev == depot:
                rec("arc-from-depot", c, h_ge(c), lo(nd[depot].earliest + D[depot][c]), ">=")
            elif prev_xfer:
                q = hub_of[prev]
                ur = u_rhs(prev)
                rec("arc-after-transfer", c, h_ge(c),
                    (ur + lo(tau + D[q][c])) if ur is not None else None, ">=")
            else:
                hr = h_rhs(prev)
                rec("arc-plain", c, h_ge(c),
                    (hr + lo(nd[prev].service + D[prev][c])) if hr is not None else None, ">=")
            rec("S-TW-DEP-UB", c, h_le(c),
                hi(nd[depot].latest - D[c][depot] - nd[c].service - tau), "<=")
            if c in tset:
                p = hub_of[c]
                hr = h_rhs(c)
                rec("xfer-after-service", c, u_ge(c),
                    (hr + lo(nd[c].service + D[c][p])) if hr is not None else None, ">=")
                rec("sync-CDC-lower", c, u_ge(c), lo(nd[CDC].earliest + D[CDC][p]), ">=")
                rec("sync-CDC-upper", c, u_le(c), hi(nd[CDC].latest - tau - D[p][CDC]), "<=")
                prev_xfer = True
            else:
                prev_xfer = False
            prev = c
        # 10 -- multi-trip return, only when the route ends in a transfer
        if r and r[-1] in tset:
            q = hub_of[r[-1]]
            rec("multitrip-return", r[-1], u_le(r[-1]),
                hi(nd[depot].latest - tau - D[q][depot]), "<=")

    # 11 -- vessel sequencing
    for vr in vroutes:
        for a, b in zip(vr, vr[1:]):
            if a in hub_of and b in hub_of:
                ua = u_rhs(a)
                rec("vessel-seq", b, u_ge(b),
                    (ua + lo(tau + D[hub_of[a]][hub_of[b]])) if ua is not None else None, ">=")

    # 12 -- constraint (26). NoOverlap on equal-duration intervals is exactly pairwise
    # |u_i - u_j| >= tau; with members sorted, the minimum gap is on a CONSECUTIVE pair, so the
    # consecutive test is equivalent (design audit 1 established this reduction is exact).
    if tau > 0:
        by_sat = {}
        for c in tset:
            by_sat.setdefault(hub_of[c], []).append(c)
        for p, members in by_sat.items():
            have = [c for c in members if c in U]
            if len(have) < 2:
                continue
            ts = sorted((U[c], c) for c in have)
            for (t1, c1), (t2, c2) in zip(ts, ts[1:]):
                # gap permissive: ceil(later) - floor(earlier) can only OVERSTATE the gap,
                # so a violation reported here cannot be manufactured by rounding.
                gap = up(t2) - dn(t1)
                if gap < lo(tau):
                    mag = (lo(tau) - gap) / SCALE
                    (res.indeterminate if mag <= INDET else res.timetable).append(
                        ("c26-satellite-%s" % p, c2, mag))


# ---------------------------------------------------------------- LEG 3, the objective
def check_objective(inst, sol, hub_of, tset, res):
    D = inst.D
    CDC = inst.CDC
    xij = [tuple(e) for e in (sol.get("xij") or [])]
    yij = [tuple(e) for e in (sol.get("yij") or [])]

    street = 0.0
    for (i, j) in xij:
        if i in tset:
            p = hub_of[i]
            street += D[i][p] + D[p][j]
        else:
            street += D[i][j]
    water = 0.0
    for (i, j) in yij:
        a = CDC if i == CDC else hub_of.get(i)
        b = CDC if j == CDC else hub_of.get(j)
        if a is None or b is None:
            res.structure.append("O-ARC: vessel arc %s touches a non-transfer non-CDC node"
                                 % str((i, j)))
            continue
        water += D[a][b]

    # AUDIT 5, fix 1: n_cars was COPIED FROM THE DUMP while the docstring said LEG 3 recomputes z
    # "from the routing". FleetStreet is 22.7%-56.6% of the objective (median 36.5%), so over a
    # third of z was being taken on trust from the object under test. Demonstrated consequence:
    # nCars+1 with objVal += penalty_cars passed LEG 3, and was caught only incidentally by LEG 1.
    n_cars = len([j for (i, j) in xij if i == inst.depot])
    claimed_cars = sol.get("nCars")
    if claimed_cars is not None and claimed_cars != n_cars:
        res.structure.append("O-FLEET: nCars claimed %s, derived from depot out-arcs %d"
                             % (claimed_cars, n_cars))
    n_vessel = len([1 for (i, j) in yij if i == CDC])
    z = (n_cars * inst.penalty_cars
         + n_vessel * inst.penalty_vessels
         + inst.travelcoststreet * street
         + inst.travelcostwater * water)
    res.components = {
        "n_cars": n_cars, "n_vessel": n_vessel,
        "travel_street": round(street, 3), "travel_water": round(water, 3),
        "fleet_street_cost": round(n_cars * inst.penalty_cars, 3),
        "fleet_water_cost": round(n_vessel * inst.penalty_vessels, 3),
    }
    res.obj_recomputed = z
    res.obj_claimed = sol.get("objVal")
    if res.obj_claimed is not None:
        res.obj_matches = abs(z - res.obj_claimed) <= max(OBJ_TOL, OBJ_TOL * abs(res.obj_claimed))

    # AUDIT 5, fix 2 -- THE ONLY NON-TAUTOLOGICAL SIGNAL IN A FIXOPT DUMP, and nothing was reading
    # it. `objVal` is NOT the solver's objective: fixopt.py:1394 sets s0["objVal"] = vd.recomputed_obj
    # and :1415 sets best_sol["objVal"] = best, which is also vd.recomputed_obj. So comparing our z
    # to objVal compares our recompute of verifier.py's formula against verifier.py's recompute of
    # the same formula, over the same VInstance.D -- it CANNOT FAIL, and "0 OV mismatches over 238
    # dumps" is the expected output of a check with no teeth, not evidence.
    # The four component fields ARE independent: joint_model_cplex.py:273-283 declares FleetStreet,
    # TravelStreet, FleetWater and TravelWater as CPLEX continuous_vars, and :336-341 writes CPLEX's
    # own solution values for them. TravelStreet in particular is the MODEL's linearised detour cost
    # via Const9 and the spatial-sync constraint, arrived at without any distance lookup we perform.
    res.components["objval_provenance"] = (
        "verifier-recompute (fixopt.py:1394,1415) -- comparison to objVal is a TAUTOLOGY"
        if "_run_id" in sol or "_iter" in sol else "unknown -- may be solver-written")
    comp_claimed = {"fleet_street_cost": sol.get("FleetStreet"),
                    "travel_street_cost": sol.get("TravelStreet"),
                    "fleet_water_cost": sol.get("FleetWater"),
                    "travel_water_cost": sol.get("TravelWater")}
    comp_ours = {"fleet_street_cost": n_cars * inst.penalty_cars,
                 "travel_street_cost": inst.travelcoststreet * street,
                 "fleet_water_cost": n_vessel * inst.penalty_vessels,
                 "travel_water_cost": inst.travelcostwater * water}
    deltas = {}
    for k, claimed in comp_claimed.items():
        if claimed is None:
            continue
        d = comp_ours[k] - claimed
        deltas[k] = d
        if abs(d) > max(OBJ_TOL, OBJ_TOL * abs(claimed)):
            res.structure.append(
                "O-COMPONENT: %s recomputed %.6f vs solver-written %.6f (delta %+.6f)"
                % (k, comp_ours[k], claimed, d))
    res.components["component_deltas"] = deltas
    return res


# ---------------------------------------------------------------- driver
FORCE_PROX = None      # set only by --proximity; see resolve() for why it is labelled, not silent


def resolve(sol, path):
    """(cell, size, proximity, tau, source) -- proximity from the RUN's own config record.

    NEVER from K's table for the size (d209/d217: every n100 run used 0.0 while K's table 6 is 0.1,
    and rebuilding at 0.1 moves every satellite and therefore every entry of D). When the run log
    is absent -- as for validation/certificates/, which are frozen artifacts with no run beside
    them -- the tool REFUSES rather than defaulting, unless the operator supplies one explicitly
    with --proximity. That override is recorded as 'operator-supplied' in the source field and
    printed, so a number produced under it can never be mistaken for one resolved from a run."""
    from analysis.verify_committed import resolve_proximity, _resolve_tau
    # (?:^|_) -- the frozen certificates are named "R205_n20_optimal_solution.json" with no
    # leading underscore, and a regex demanding one silently reported them NOT-CHECKED.
    m = re.search(r"(?:^|_)((?:RC|R|C)\d{3})_n(\d+)", os.path.basename(path))
    if not m:
        return None
    cell, size = m.group(1), int(m.group(2))
    prox, src = resolve_proximity(sol, path)
    if prox is None and FORCE_PROX is not None:
        prox, src = FORCE_PROX, "operator-supplied"
    if prox is None:
        return cell, size, None, None, src
    return cell, size, prox, _resolve_tau(cell, size, prox), src


def verify_file(path):
    """The whole thing: load, derive, check three legs. NO SOLVER IS IMPORTED OR CALLED."""
    import verifier as V
    res = Result(path)
    sol = json.load(open(path, encoding="utf-8"))
    got = resolve(sol, path)
    if got is None:
        res.notes.append("NOT-CHECKED: cell/size not parseable from the filename")
        return res, None
    cell, size, prox, tau, src = got
    res.meta = {"cell": cell, "size": size, "prox": prox, "psrc": src, "tau": tau}
    if prox is None:
        res.notes.append("NOT-CHECKED: proximity unresolvable (%s) -- refusing to invent one" % src)
        return res, None
    inst = V.VInstance(cell, size, wls=0.1, tau=tau, proximity=prox)
    H = {int(k): v for k, v in (sol.get("hi") or {}).items()}
    U = {int(k): v for k, v in (sol.get("ui") or {}).items()}
    routes, hub_of, tset, vroutes, problems = derive(sol, inst)
    res.structure.extend(problems)
    if not H and not U:
        res.notes.append("NOT-CHECKED: no committed timetable in the dump")
        check_objective(inst, sol, hub_of, tset, res)
        return res, (inst, routes, hub_of, tset, vroutes, H, U)
    check_timetable(inst, routes, hub_of, tset, vroutes, H, U, res)
    check_objective(inst, sol, hub_of, tset, res)
    return res, (inst, routes, hub_of, tset, vroutes, H, U)


def record(path, res, cell=None, size=None, prox=None, psrc=None, tau=None):
    """THE COMPLETE REJECTION RECORD for one solution. Nothing truncated, nothing summarised.

    AUTHOR, 2026-09-18: *"Make sure reject reason is fully logged"*. The console table shows class
    counts and the worst magnitude only; that is a LOSSY DERIVED VIEW, and d212 records an entire
    set of per-cell narratives being read off one and every one of them being an artifact. So the
    table is a VIEW of this record, never the record itself. Every structural problem string in
    full, every (class, node, magnitude) triple, every missing committed value, both objective
    values and their signed delta, and the not-checked reason verbatim."""
    verdict = ("NOT-CHECKED" if any("NOT-CHECKED" in n for n in res.notes)
               else "REJECT" if (res.structure or res.timetable or res.missing
                                 or res.obj_matches is False)
               else "ACCEPT")
    reasons = []
    for s in res.structure:
        reasons.append({"leg": 1, "kind": "structure", "detail": s})
    for k, c, d in res.timetable:
        reasons.append({"leg": 2, "kind": "timetable", "class": k, "node": c,
                        "magnitude": d, "severity": "VIOLATION"})
    for k, c, d in res.indeterminate:
        reasons.append({"leg": 2, "kind": "timetable", "class": k, "node": c,
                        "magnitude": d, "severity": "INDETERMINATE",
                        "detail": "at or below the %.3f rounding band" % INDET})
    for kind, c in res.missing:
        reasons.append({"leg": 2, "kind": "missing-committed-value",
                        "variable": kind, "node": c})
    if res.obj_matches is False:
        reasons.append({"leg": 3, "kind": "objective-mismatch",
                        "claimed": res.obj_claimed, "recomputed": res.obj_recomputed,
                        "delta": (res.obj_recomputed - res.obj_claimed)
                        if (res.obj_recomputed is not None and res.obj_claimed is not None)
                        else None, "tolerance": OBJ_TOL})
    for n in res.notes:
        reasons.append({"leg": 0, "kind": "not-checked", "detail": n})
    return {
        "solution": os.path.basename(path), "path": os.path.relpath(path, ROOT).replace("\\", "/"),
        "cell": cell, "size": size, "proximity": prox, "proximity_source": psrc, "tau": tau,
        "verdict": verdict,
        "n_reasons": len(reasons),
        "counts": {"structure": len(res.structure), "timetable": len(res.timetable),
                   "indeterminate": len(res.indeterminate), "missing": len(res.missing)},
        "objective": {"claimed": res.obj_claimed, "recomputed": res.obj_recomputed,
                      "matches": res.obj_matches,
                      "delta": (res.obj_recomputed - res.obj_claimed)
                      if (res.obj_recomputed is not None and res.obj_claimed is not None)
                      else None},
        "components": res.components,
        "reject_reasons": reasons,
    }


def main():
    global FORCE_PROX
    args = [a for a in sys.argv[1:]]
    logpath = None
    if "--log" in args:
        i = args.index("--log")
        logpath = args[i + 1]
        del args[i:i + 2]
    if "--proximity" in args:
        i = args.index("--proximity")
        FORCE_PROX = float(args[i + 1])
        del args[i:i + 2]
        print("!! proximity %g OPERATOR-SUPPLIED for files with no run log. Not resolved from a "
              "run; justify it at the call site." % FORCE_PROX)
    pat = args[0] if args else "runs/solutions/*_n100*.json"
    files = sorted(glob.glob(os.path.join(ROOT, pat)))
    print(__doc__.split("WHAT IS AND IS NOT SHARED")[0].strip())
    print()
    print("%-30s %6s %10s %10s %5s | %-9s | %s"
          % ("solution", "struct", "objVal", "recomp", "OV", "timetable", "worst / classes"))
    tally = {"ok": 0, "struct": 0, "timetable": 0, "objmismatch": 0, "notchecked": 0, "indet": 0}
    records = []
    for p in files:
        b = os.path.basename(p)
        try:
            res, _ = verify_file(p)
        except Exception as e:
            # An exception is a REJECT with a reason, never a row silently dropped from the
            # denominator. The earlier variant printed and continued, losing it from every rollup.
            records.append({"solution": b, "verdict": "ERROR", "n_reasons": 1,
                            "reject_reasons": [{"leg": 0, "kind": "exception",
                                                "type": type(e).__name__, "detail": str(e)}]})
            print("%-30s  ERROR %s: %s" % (b[:30], type(e).__name__, str(e)[:50]))
            continue
        m = res.meta
        records.append(record(p, res, m.get("cell"), m.get("size"), m.get("prox"),
                              m.get("psrc"), m.get("tau")))
        if res.notes and "NOT-CHECKED" in res.notes[0]:
            tally["notchecked"] += 1
            print("%-30s %6s %10s %10s %5s | %-9s | %s"
                  % (b[:30], len(res.structure), "-", "-", "-", "NOT-CHK", res.notes[0][12:]))
            continue
        if res.structure:
            tally["struct"] += 1
        if res.timetable:
            tally["timetable"] += 1
        if res.indeterminate:
            tally["indet"] += 1
        if res.obj_matches is False:
            tally["objmismatch"] += 1
        if res.ok:
            tally["ok"] += 1
        kinds = {}
        for k, c, d in res.timetable:
            kk = k.split("-satellite")[0]
            kinds[kk] = kinds.get(kk, 0) + 1
        worst = max((d for _, _, d in res.timetable), default=0.0)
        state = "VALID" if not res.timetable else "VIOLATES"
        detail = ("-" if not kinds else
                  "%.4f  %s" % (worst, ", ".join("%s x%d" % kv for kv in sorted(kinds.items()))))
        if res.indeterminate:
            detail += "   [+%d indeterminate <=%.3f]" % (len(res.indeterminate), INDET)
        print("%-30s %6d %10.3f %10.3f %5s | %-9s | %s"
              % (b[:30], len(res.structure), res.obj_claimed or float("nan"),
                 res.obj_recomputed or float("nan"), res.obj_matches, state, detail))
    print()
    print("  fully ok %d | structure failures %d | timetable violations %d | OV mismatches %d"
          " | not checked %d | with indeterminates %d"
          % (tally["ok"], tally["struct"], tally["timetable"], tally["objmismatch"],
             tally["notchecked"], tally["indet"]))
    nreasons = sum(r.get("n_reasons", 0) for r in records)
    print("  rejection reasons recorded in full: %d across %d solutions" % (nreasons, len(records)))
    if logpath:
        lp = logpath if os.path.isabs(logpath) else os.path.join(ROOT, logpath)
        with open(lp, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        print("  FULL REJECTION LOG -> %s  (%d records, %d reasons, nothing truncated)"
              % (logpath, len(records), nreasons))
    else:
        print("  (pass --log <file> to write the complete per-reason record; the table above is"
              " a VIEW and is lossy by design)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
