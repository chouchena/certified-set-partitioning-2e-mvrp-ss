"""Full-set decomposed lower bound -- no customer is dropped, so nothing degrades with size.

THE PROBLEM IT SOLVES. The easy-reduction bound is  z_A(H)* + w(full).  Dropping k customers
shrinks H, and z_A = FleetStreet + TravelStreet, so the fleet term collapses with |H|:

    size   k_hi   |H|   drop fraction     because |H| is capped by what CPLEX can PROVE,
      20      9    11        45%          not by what the instance needs. |H| stays ~11-15
      30     15    15        50%          at every size, so the drop fraction GROWS with n
     100     87    13        87%          and the bound degrades BY CONSTRUCTION.

Measured at |C|=100: w(full) alone reaches only 0.19-0.24x of K's Table 6 bound, i.e. ~80% of
the required bound had to come from z_A(H) -- from a sub-instance holding 13 of 100 customers.

THE FIX IS STRUCTURAL, NOT COMPUTATIONAL. z_A is ADDITIVE:

    z_A(full)* = penaltyCars * V(full*)  +  travelcoststreet * Dist(full*)

so instead of bounding it with ONE shrunken sub-instance solve, bound each component
separately over the FULL customer set and sum. Each piece is a valid bound on its own
component, so the sum is a valid bound on z_A(full)*, and adding w(full) keeps the original
proof (Step 0) intact.

  V_LB    = max(routes_lb_time, clique)   -- BOTH are pre-existing cuts from check_cuts.py,
            already validated there against verified feasible incumbents on the full customer
            set. routes_lb_time = ceil(work_lb/horizon) with work_lb = service + dist/2 +
            trips*TD; clique = largest set of pairwise time-incompatible customers, none of
            which can share a vehicle.
  Dist_LB = max of three independently valid relaxations over the FULL customer set:
            AP     assignment -- one distinct successor per customer, depot replicated n
                   times (which RELAXES the vehicle limit, keeping it a valid LB).
                   Shortcutting a via-satellite leg i->pp->j down to the direct arc (i,j) is
                   licensed by the MODEL CONSTRAINT block_a.py:132, aS[i,j] >= D[i][j]*x[i,j],
                   NOT by the triangle inequality as this docstring previously claimed. The
                   distinction matters: the model constraint holds at proximity 0.1 where D is
                   NOT metric, so AP and MST need no metricity gate -- unlike the clique term.
            MST    (AB3) routes are cycles through the depot, so their undirected edge set is
                   a connected spanning subgraph and costs at least the spanning tree.
            FORCED (AB4) needs neither -- it prices the LITERAL next node, so no shortcutting
                   argument of any kind is invoked. The assignment lets every customer escape
                   to its cheapest neighbour;
                   at least trips_lb of them must instead end a trip at a satellite or the
                   depot. Forcing that is strictly stronger and needs NO triangle inequality.
            Dist_LB then also replaces check_cuts' weak dmin/2 travel term inside work_lb,
            which is what lifts V_LB (R/RC n50 1->2, RC n100 2->3).

NO DOUBLE COUNTING. Distance enters work_lb as TIME CONSUMED (to bound the vehicle count) and
enters Dist_LB as TRAVEL COST. They constrain different additive terms of the objective.

VALIDATION. Falsification test over all 54 target cells at n20 and n30: the bound must never
exceed K's BK, which is a FEASIBLE solution. Result 0/54 violations, before and after AB3/AB4.
Family means at n50 and n100 also stay below K's best feasible value. This is the decisive
test -- an invalid component would push the bound above a known achievable value.

HONEST LIMITS, STATED HERE SO THEY TRAVEL WITH THE CODE:
1. At n20/n30 this is still WEAKER than the MILP block_relax on most cells, because there |H|
   retains half the instance and z_A(H) is nearly z_A(full). Use max(block_relax,
   fullset_bound) -- both are valid, so taking the better of the two is free.
2. The bound is MOSTLY CONSTANT WITHIN A FAMILY: Solomon class-2 instances share coordinates
   and demands and differ only in time windows, which enter through V_LB. AB4 broke this only
   at RC/n100, where the per-cell depot horizon splits the family 3/5 across a ceil() boundary.
   It still cannot discriminate cells by time-window WIDTH, the dimension R201-R211 vary on.
3. The RC/n100 V_LB=3 flip clears its ceil() threshold by 0.09% (work 2353.0 vs 2350.8). The
   BOUND IS VALID either way -- every term is a proven LB -- but the SIZE of that particular
   gain is knife-edge and must not be presented as robust. The n50 flips are safer (1.5-6.9%).
4. R at n100 remains the weak family: V_LB=2 against K's ~9.3 street vehicles. AB4 lifts travel
   only 571 -> 587 there, short of the 733 needed for V_LB=3. Time is not the binding resource
   for R, so a stronger vehicle bound must come from synchronisation structure no cut captures.
"""
from __future__ import annotations
import math

import numpy as np
from scipy.optimize import linear_sum_assignment


def admits(p, i, j):
    """K's OWN street-arc admission rule, integratedJointModel.py:58.

    Their model creates x[i,j] only when e_i + s_i + D[i][j] <= l_j, so no feasible solution
    can use an arc failing this test. Restricting our distance relaxations to the admitted set
    is therefore valid with NO new argument beyond their line -- the true successor map stays
    feasible for the restricted problem, so the restricted optimum is still a lower bound.

    Adopted 2026-09-12 after measuring it on every size: it raises the bound on 33/54 cells at
    n20+n30 (mean +3.35%), 16/27 at n50 (+3.84%), and 24/27 at n100 (+5.59%). The effect GROWS
    with size, and at n100 -- where the arithmetic bound carries the portfolio -- it moves the
    published-comparison ratios by R +0.031 and RC +0.039. A read from n20/n30 alone said it did
    not matter; that read was wrong for the sizes that count.

    It also breaks AB's family-constancy for C and R (1 distinct value per family -> 8 and 6-10),
    because this is the first term that reads time-window WIDTH. RC stays at 2 values, so the
    family-constancy caveat SURVIVES for RC and any phrasing must be per family.
    """
    nd = p.nodes
    return nd[i].earliest + nd[i].serviceTime + p.DistMatrix[i][j] <= nd[j].latest


def assignment_dist_lb(p, customers=None):
    """Valid LB on total direct street distance: distinct successors, depot free to repeat."""
    D = p.DistMatrix
    cust = list(customers if customers is not None else p.customers)
    n = len(cust)
    if n == 0:
        return 0.0
    BIG = 1e9
    M = np.full((n, 2 * n), BIG)
    for a, i in enumerate(cust):
        for b, j in enumerate(cust):
            if i != j and admits(p, i, j):
                M[a, b] = D[i][j]
        if admits(p, i, 0):
            for b in range(n):
                M[a, n + b] = D[i][0]
    r, c = linear_sum_assignment(M)
    tot = float(M[r, c].sum())
    # An all-BIG assignment would mean no admissible successor map exists, which cannot happen
    # for a feasible instance. Fall back to 0 rather than emit a garbage bound.
    return 0.0 if tot >= BIG / 2 else tot



def mst_dist_lb(p, customers=None):
    """AB3. Routes are cycles through the depot, so their undirected edge set is a CONNECTED
    SPANNING subgraph on customers+depot and costs at least the minimum spanning tree."""
    from scipy.sparse.csgraph import minimum_spanning_tree
    cust = list(customers if customers is not None else p.customers)
    if not cust:
        return 0.0
    idx = [0] + cust
    D = np.asarray(p.DistMatrix, dtype=float)[np.ix_(idx, idx)].copy()
    # Pruning here must be UNDIRECTED: a route may traverse {i,j} either way, so the edge
    # survives if EITHER direction is admitted.
    m = len(idx)
    for a in range(m):
        for b in range(a + 1, m):
            i, j = idx[a], idx[b]
            if not (admits(p, i, j) or admits(p, j, i)):
                D[a, b] = D[b, a] = 0.0        # 0 == absent edge for scipy's MST
    t = minimum_spanning_tree(D).toarray()
    if (t > 0).sum() < m - 1:
        return 0.0                              # disconnected: impossible for a feasible
    return float(t.sum())


def forced_terminal_dist_lb(p, customers=None, trips_lb=None):
    """AB4. The assignment relaxation lets EVERY customer escape to its cheapest neighbour.
    It cannot: at least trips_lb of them must end a trip.

    Each customer has exactly one successor (the literal next node on its route) and exactly
    one predecessor, so successors are distinct among customers. Each trip runs
    satellite -> customers -> satellite, except the last trip of each vehicle which ends at
    the depot; so the number of customer->(satellite|depot) arcs equals the number of trips,
    which is at least trips_lb = ceil(demand/Q). Writing V for the vehicle count, that is
    (trips-V) satellite terminals plus V depot terminals -- trips either way.

    NO TRIANGLE INEQUALITY IS NEEDED. A customer arc is priced at D[i][j] EXACTLY and a
    terminal arc at min(min_s D[i][s], D[i][0]), both on the literal next node, so unlike the
    clique term (AB-L3) this is safe at proximity 0.1 where D is not metric. A route passing
    THROUGH a satellite mid-trip only adds terminal arcs, which keeps the count >= trips_lb.

    The LP relaxation of that program is a valid LB on its integer optimum, so a fractional
    solution would cost validity nothing -- measured integral on all 162 grid cells anyway.
    """
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix
    D = np.asarray(p.DistMatrix, dtype=float)
    cust = list(customers if customers is not None else p.customers)
    n = len(cust)
    if n == 0:
        return 0.0
    if trips_lb is None:
        from crossfeed.check_cuts import cut_bounds
        trips_lb = cut_bounds(p, cust)["trips_lb"]
    T = max(0, min(int(trips_lb), n))
    sats = list(p.satellites)
    sub = D[np.ix_(cust, cust)].copy()
    np.fill_diagonal(sub, 1e7)
    for a, i in enumerate(cust):                    # arcs no feasible solution can use
        for b, j in enumerate(cust):
            if a != b and not admits(p, i, j):
                sub[a, b] = 1e7
    # Terminal arcs are NOT pruned: satellites are detours on an arc, not routing nodes, so
    # K's node-to-node admission rule does not apply to them.
    term = np.array([min(min(D[i][s] for s in sats), D[i][0]) for i in cust])
    cost = np.concatenate([sub.ravel(), term])
    Aeq = lil_matrix((n, n * n + n))
    for a in range(n):                                  # exactly one successor per customer
        Aeq[a, a * n:(a + 1) * n] = 1
        Aeq[a, n * n + a] = 1
    Aub = lil_matrix((n + 1, n * n + n))
    bub = np.ones(n + 1)
    for j in range(n):                                  # each customer succeeds at most one
        Aub[j, [a * n + j for a in range(n)]] = 1
    Aub[n, n * n:] = -1
    bub[n] = -T                                         # at least T terminal arcs
    r = linprog(cost, A_ub=Aub.tocsr(), b_ub=bub, A_eq=Aeq.tocsr(), b_eq=np.ones(n),
                bounds=(0, 1), method="highs")
    return float(r.fun) if r.success else 0.0


def max_triangle_excess(p):
    """max over i,j,k of D[i][k] - (D[i][j] + D[j][k]). <= 0 means exactly metric."""
    D = np.asarray(p.DistMatrix, dtype=float)
    return float(np.max(D[:, None, :] - (D[:, :, None] + D[None, :, :])))


def fullset_bound(p, customers=None, wlb=None, metric_tol=1e-9):
    """penaltyCars*V_LB + travelcoststreet*Dist_LB + w(full). Returns (bound, parts).

    THE CLIQUE TERM IS GATED ON THE TRIANGLE INEQUALITY (added 2026-09-10).
    AB-L3 of validation/fullset_bound_proof.md derives V* >= |clique| from the fact that the
    elapsed time between two customers on one route is at least D[i][j] -- which needs D metric.
    Re-verifying F9 rather than inheriting it found that D is exactly metric at proximity 0.0
    (n20, n30: excess 0.00e+00 on all 27 cells) but NOT at |C|=100 (excess 1.00e-02).

    CORRECTED 2026-09-12: that excess is SIZE-triggered, not proximity-triggered. A sweep of all
    five proximity values (0/0.1/0.2/0.3/0.4) x 27 cells x n20/n30 retained the clique on 54/54
    cells at EVERY proximity -- non-metricity never appeared. Attributing the gate to
    "proximity 0.1" would mislead anyone reasoning about when the clique term is safe; the gate
    is on the measured excess, which is what the code actually tests.
    A violated triangle inequality can make the incompatibility test declare a false clique,
    inflating V_LB and rendering the bound INVALID.

    Dropping the clique where the property fails costs nothing measurable: routes_lb_time
    dominates the clique on 27/27 cells at n100, so V_LB is unchanged. Validity is restored at
    zero cost, which is why this is a gate rather than a tolerance fudge.
    """
    import math as _math
    from crossfeed.check_cuts import cut_bounds
    cust = list(customers if customers is not None else p.customers)
    cb = cut_bounds(p, cust)
    excess = max_triangle_excess(p)
    metric = excess <= metric_tol
    # Dist_LB is the best of three INDEPENDENTLY VALID relaxations, so the max is valid.
    d_ap = assignment_dist_lb(p, cust)
    d_mst = mst_dist_lb(p, cust)
    d_ft = forced_terminal_dist_lb(p, cust, cb["trips_lb"])
    dist = max(d_ap, d_mst, d_ft)
    # The same distance also lower-bounds TIME CONSUMED, so it strengthens the vehicle count.
    # check_cuts' work_lb uses a weak dmin/2 travel term; substituting Dist_LB is valid because
    # total street travel time >= total street distance LB. NO DOUBLE COUNTING: distance enters
    # here as time (bounding the fleet term) and below as cost (bounding the travel term) --
    # two different additive terms of the objective, exactly as for the original dmin/2.
    _nd, _hz = p.nodes, p.nodes[0].latest - p.nodes[0].earliest
    _work = (sum(_nd[c].serviceTime for c in cust) + dist
             + cb["trips_lb"] * p.TransferDuration)
    routes_lb = max(cb["routes_lb_time"], _math.ceil(_work / _hz) if _hz > 0 else 1)
    V = max(1, routes_lb, cb["clique"] if metric else 1)
    from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
    _wl, _L = water_lb_scaled(p)
    if wlb is None:
        wlb = _wl / SCALE
    # w(full) bundles vessel FLEET and water TRAVEL into one cost, which is why the water side
    # could not be compared against K at all (C4_bound_vs_achieved_n100.md section 4): K report
    # travel and fleet in separate columns. Exposing the three terms lets the split be made.
    _minTr = min(2 * p.DistMatrix[p.CDC][sat] for sat in p.satellites)
    fleet = V * p.penaltyCars
    trav = p.travelcoststreet * dist
    return fleet + trav + wlb, dict(
        V_LB=V, routes_lb_time=cb["routes_lb_time"], routes_lb_strong=routes_lb,
        dist_ap=round(d_ap, 4), dist_mst=round(d_mst, 4), dist_forced=round(d_ft, 4),
        dist_winner=max((("AP", d_ap), ("MST", d_mst), ("FORCED", d_ft)),
                        key=lambda z: z[1])[0], clique=cb["clique"],
        clique_used=bool(metric), triangle_excess=round(excess, 6),
        trips_lb=cb["trips_lb"], fleet_term=round(fleet, 4), dist_raw=round(dist, 4),
        travel_term=round(trav, 4), water=round(wlb, 4),
        water_trips_L=_L, water_minTr=round(_minTr, 4),
        water_travel_term=round(p.travelcostwater * _minTr * _L, 4),
        water_fleet_term=round(_L * p.penaltyVessels, 4))


if __name__ == "__main__":
    import argparse, sys
    sys.path.insert(0, ".")
    from build_instance import build
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C201,R201,RC201")
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--proximity", type=float, default=None,
                    help="default: 0.1 at |C|=100 (K Table 6), else 0.0")
    A = ap.parse_args()
    prox = A.proximity if A.proximity is not None else (0.1 if A.size == 100 else 0.0)
    print(f"{'cell':7}{'V_LB':>6}{'time':>6}{'clique':>8}{'fleet':>10}{'travel':>10}"
          f"{'water':>9}{'BOUND':>10}")
    for c in [x.strip() for x in A.cells.split(",") if x.strip()]:
        p = build(c, A.size, wls=0.1, tau="formula", proximity=prox, time_limit=60)
        b, parts = fullset_bound(p)
        print(f"{c:7}{parts['V_LB']:>6}{parts['routes_lb_time']:>6}{parts['clique']:>8}"
              f"{parts['fleet_term']:>10.1f}{parts['travel_term']:>10.1f}"
              f"{parts['water']:>9.1f}{b:>10.1f}")
