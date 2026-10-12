"""THE ARBITER -- an independent optimum for the 2E-MVRP-SS, by enumeration, with no solver.

WHY IT EXISTS. Every other instrument in this project is two of my own artifacts agreeing with
each other, or one of them agreeing with K's published numbers on 35 cells. Nothing has ever
computed an answer by a route that does not pass through my transcription. A referee's sharpest
question -- "show me one answer computed without your code" -- has had no answer.

WHAT MAKES IT INDEPENDENT. It imports NO project module: not build_instance, not
joint_model_gurobi, not instance_view, not verifier3. It shares no data structure, no index set
and no algorithm with them. It is a different method (exhaustive enumeration, not branch and
bound), in different arithmetic (exact Fraction, not float), with no big-M, no tolerance and no
solver. The one thing it shares with the MILP is the INSTANCE, which it must, or they would not
be answering the same question.

WHAT IT STILL SHARES, stated so it is not over-read: the READING of K's article. The arbiter was
written from the same understanding of the model as verifier3. Two implementations of one
misreading still agree. That residue is closed by the source check (oracle_residue.py), not by
this -- and it is registered as A1-A11 in validation/AMBIGUITY_REGISTER.md.

THE INSIGHT THAT MAKES ENUMERATION EXACT AND FAST. Once the discrete structure is fixed --
routes, which customers transfer, which satellite each uses, and the order of tasks on each
vessel -- EVERY remaining constraint is a DIFFERENCE CONSTRAINT on the schedule variables:

    h_i >= e_i,  h_i <= l_i                      Table 1
    h_j >= h_i + s_i + tau*v_i + f^s_ij          (6)
    u_i >= h_i + s_i + D_ip                      (11)
    h_j >= u_i + tau + D_pj                      (12)
    e_CDC + D_CDCp <= u_i,  u_i + tau + D_pCDC <= l_CDC   (13)
    u_j >= u_i + tau + D_{p_i p_j}               (20), consecutive vessel tasks
    u_j >= u_i + tau                             (26), same satellite, in the enumerated order

A system of difference constraints is feasible IFF its constraint graph has NO NEGATIVE CYCLE.
Bellman-Ford decides that exactly, in rationals, with no LP and no tolerance. And the objective
-- fleet plus travel -- depends only on the discrete structure, so no optimisation over the
continuous variables is needed at all. The optimum is a minimum over a finite enumerated set.

SCOPE. Tiny instances only: this is exponential by design. |C| <= 5 and |P| in {1, 2}.

    |P| = 1 IS DELIBERATE. With K's four satellites, (26) cannot bind below |C| ~ 40 (L0), so a
    small-instance check with |P| = 4 would reproduce exactly the blind spot the whole oracle
    already has. With ONE satellite every transfer collides, (26) binds at the second one, and
    the constraint this project exists to correct becomes testable at |C| = 4.

    python analysis/arbiter.py --selftest
"""
from fractions import Fraction as F
import itertools
import math
import random

TIE = F(0)


# --------------------------------------------------------------------------------------------
# Instances. Generated here, in exact rationals, so nothing about them comes from project code.
# --------------------------------------------------------------------------------------------
class Node:
    __slots__ = ("x", "y", "demand", "earliest", "latest", "service")

    def __init__(self, x, y, demand, earliest, latest, service):
        self.x, self.y = F(x), F(y)
        self.demand, self.service = F(demand), F(service)
        self.earliest, self.latest = F(earliest), F(latest)


class Tiny:
    """A 2E-MVRP-SS instance: garage 0, customers, satellites, CDC.

    Distances are Euclidean rounded to 2 decimals and held EXACTLY as Fractions with denominator
    100, matching ambiguity-register pick A4 while keeping the arithmetic exact.
    """

    def __init__(self, seed, n_cust, n_sat, horizon=600, cap_lefv=50, cap_vessel=250):
        rng = random.Random(seed)
        self.seed = seed
        self.nC, self.nP = n_cust, n_sat
        self.garage = 0
        self.customers = list(range(1, n_cust + 1))
        self.satellites = list(range(n_cust + 1, n_cust + 1 + n_sat))
        self.CDC = n_cust + n_sat + 1
        self.tau = F(rng.randrange(20, 61))
        self.CarCapacity, self.VesselCapacity = F(cap_lefv), F(cap_vessel)
        self.penaltyCars, self.penaltyVessels = F(rng.randrange(50, 151)), F(rng.randrange(80, 201))
        self.cost_street, self.cost_water = F(1), F(1)
        self.nodes = {}
        for i in [self.garage] + self.customers + self.satellites + [self.CDC]:
            x, y = rng.randrange(0, 60), rng.randrange(0, 60)
            if i in self.customers:
                dem = rng.randrange(5, 26)
                svc = F(rng.randrange(5, 21))
                e = F(rng.randrange(0, horizon // 2))
                l = e + F(rng.randrange(horizon // 4, horizon))
            else:
                dem, svc, e, l = 0, F(0), F(0), F(horizon * 2)
            self.nodes[i] = Node(x, y, dem, e, l, svc)
        N = max(self.nodes) + 1
        self.D = [[F(0)] * N for _ in range(N)]
        for i in self.nodes:
            for j in self.nodes:
                if i == j:
                    continue
                a, b = self.nodes[i], self.nodes[j]
                d = math.sqrt(float((a.x - b.x) ** 2 + (a.y - b.y) ** 2))
                self.D[i][j] = F(round(d * 100)) / 100        # 2 decimals, exactly
        # single, non-iterated triangle pass -- register pick A4
        idx = sorted(self.nodes)
        for i in idx:
            for j in idx:
                for k in idx:
                    c = self.D[i][k] + self.D[k][j]
                    if c < self.D[i][j]:
                        self.D[i][j] = c

    def total_demand(self):
        return sum(self.nodes[i].demand for i in self.customers)


# --------------------------------------------------------------------------------------------
# Difference-constraint feasibility. Exact, no tolerance, no solver.
# --------------------------------------------------------------------------------------------
def feasible(constraints, nodes):
    """constraints: (a, b, w) meaning x_a - x_b <= w. Feasible iff no negative cycle."""
    edges = [(b, a, w) for (a, b, w) in constraints]        # edge b -> a with weight w
    dist = {v: F(0) for v in nodes}
    n = len(nodes)
    for _ in range(n):
        changed = False
        for (u, v, w) in edges:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                changed = True
        if not changed:
            return True, dist
    for (u, v, w) in edges:                                  # one more pass: still improving?
        if dist[u] + w < dist[v]:
            return False, None
    return True, dist


# --------------------------------------------------------------------------------------------
# Enumeration of the discrete structure
# --------------------------------------------------------------------------------------------
def set_partitions(items):
    """Canonical set partitions: each block is identified by its SMALLEST member, so no
    partition is produced twice."""
    items = list(items)
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for k in range(len(rest) + 1):
        for chosen in itertools.combinations(rest, k):
            block = [first] + list(chosen)
            remaining = [x for x in rest if x not in chosen]
            for tail in set_partitions(remaining):
                yield [block] + tail


def ordered_partitions(items):
    """Every way to split items into non-empty ORDERED routes. Count = the Lah number sum
    (13 for n=3, 73 for n=4, 501 for n=5).

    THE FIRST VERSION OF THIS WAS WRONG AND IT MATTERED. It canonicalised by forcing each route
    to START with its smallest remaining member. That is a correct canonical form for UNORDERED
    set partitions, but here the order within a route is a decision, so it silently enumerated a
    strict SUBSET of the search space -- for n=3 it never produced 0->3->1->2->0 at all. The
    arbiter therefore reported optima that were too HIGH, and the first comparison against the
    MILP showed the MILP lower on 7 of 10 instances. The disagreement protocol says to suspect
    the MILP; the MILP was right and the arbiter was wrong. Recorded because the protocol's prior
    is only sound once the arbiter has passed its own controls, which at that point it had not.

    The fix: canonicalise the PARTITION (blocks identified by smallest member), then take every
    permutation WITHIN each block.
    """
    for part in set_partitions(items):
        for perms in itertools.product(*[itertools.permutations(b) for b in part]):
            yield [list(pp) for pp in perms]


def street_cost(inst, routes, hub):
    """Travel on the street level: f^s on every traversed arc, per (7).

    f^s_ij = D_ij normally; where i transfers, the LEFV detours through its satellite, so
    f^s_ij = D_{i,p} + D_{p,j}. Both are lower bounds in the article and the objective
    minimises f^s, so at any optimum f^s equals the binding one.
    """
    D, tot = inst.D, F(0)
    for r in routes:
        seq = [inst.garage] + r + [inst.garage]
        for a in range(len(seq) - 1):
            i, j = seq[a], seq[a + 1]
            if i in hub:
                p = hub[i]
                tot += D[i][p] + D[p][j]
            else:
                tot += D[i][j]
    return tot


def water_cost(inst, vroutes, hub):
    """Travel on the water level: CDC -> hub -> ... -> hub -> CDC for each vessel, per (21)-(24)."""
    D, tot = inst.D, F(0)
    for vr in vroutes:
        seq = [inst.CDC] + [hub[t] for t in vr] + [inst.CDC]
        for a in range(len(seq) - 1):
            tot += D[seq[a]][seq[a + 1]]
    return tot


def load_ok(inst, routes, transfers):
    """(5): LEFV load accumulates along the route and RESETS at a transfer."""
    load = F(0)
    for r in routes:
        load = F(0)
        for c in r:
            load += inst.nodes[c].demand
            if load > inst.CarCapacity:
                return False
            if c in transfers:
                load = F(0)
    return True


def vessel_load_ok(inst, vroutes, route_of):
    """(18)/(19): the vessel carries at least the LEFV's accumulated load at each task, and its
    capacity is never exceeded along its sequence."""
    for vr in vroutes:
        tot = F(0)
        for t in vr:
            tot += route_of[t]
            if tot > inst.VesselCapacity:
                return False
    return True


def trip_loads(inst, routes, transfers):
    """Load handed over at each transfer: what the LEFV accumulated since its last reset."""
    out, load = {}, F(0)
    for r in routes:
        load = F(0)
        for c in r:
            load += inst.nodes[c].demand
            if c in transfers:
                out[c] = load
                load = F(0)
    return out


def schedule_constraints(inst, routes, transfers, hub, vroutes):
    """Every timing rule of the model, as difference constraints x_a - x_b <= w."""
    D, tau, nd = inst.D, inst.tau, inst.nodes
    Z = ("z",)
    cons, vs = [], {Z}
    h = {i: ("h", i) for i in [inst.garage] + inst.customers}
    u = {i: ("u", i) for i in transfers}
    vs |= set(h.values()) | set(u.values())

    for i in [inst.garage] + inst.customers:                 # Table 1, own window
        cons.append((Z, h[i], -nd[i].earliest))
        cons.append((h[i], Z, nd[i].latest))
    # Table 1 also bounds h by the GARAGE's window and the round trip -- the LEFV cannot reach i
    # before leaving the garage, nor start so late that it cannot get back. Omitting these
    # UNDER-constrained the arbiter, so it reported optima that were too LOW. Found by FR2:
    # 26 structures it called feasible were rejected by verifier3 on T1-H-lo.
    for i in inst.customers:
        cons.append((Z, h[i], -(nd[inst.garage].earliest + D[inst.garage][i])))
        cons.append((h[i], Z, nd[inst.garage].latest - D[i][inst.garage]
                     - nd[i].service - tau))

    for r in routes:
        seq = [inst.garage] + r + [inst.garage]
        for a in range(len(seq) - 1):
            i, j = seq[a], seq[a + 1]
            if i == inst.garage:
                continue                                     # (6) is quantified over i in C
            hj = h[inst.garage] if j == inst.garage else h[j]
            if i in transfers:
                p = hub[i]
                # (6) aggregated: h_j >= h_i + s_i + tau + f^s_ij with the detour f^s
                cons.append((h[i], hj, -(nd[i].service + tau + D[i][p] + D[p][j])))
                # (11) u_i >= h_i + s_i + D_ip
                cons.append((h[i], u[i], -(nd[i].service + D[i][p])))
                # (12) h_j >= u_i + tau + D_pj
                cons.append((u[i], hj, -(tau + D[p][j])))
                # (13) the CDC window
                cons.append((Z, u[i], -(nd[inst.CDC].earliest + D[inst.CDC][p])))
                cons.append((u[i], Z, nd[inst.CDC].latest - tau - D[p][inst.CDC]))
            else:
                cons.append((h[i], hj, -(nd[i].service + D[i][j])))

    for vr in vroutes:                                       # (20) vessel task sequencing
        for a in range(len(vr) - 1):
            i, j = vr[a], vr[a + 1]
            cons.append((u[i], u[j], -(tau + D[hub[i]][hub[j]])))

    # (26): two transfers at the SAME satellite are at least tau apart. Disjunctive in general;
    # here the vessel sequence fixes the order for same-vessel pairs, and for pairs on different
    # vessels both orders are enumerated by the caller.
    return cons, vs, h, u


def same_sat_pairs_ok(inst, transfers, hub, order):
    """(26) as difference constraints, given a total order on transfers at each satellite."""
    cons = []
    pos = {t: k for k, t in enumerate(order)}
    ts = sorted(transfers)
    for a in range(len(ts)):
        for b in range(a + 1, len(ts)):
            i, j = ts[a], ts[b]
            if hub[i] != hub[j]:
                continue
            first, second = (i, j) if pos[i] < pos[j] else (j, i)
            cons.append((("u", first), ("u", second), -inst.tau))
    return cons


def brute_optimum(inst, enforce_26=True, collect=None):
    """The exact optimum by enumeration. Returns (best_cost, best_structure, n_feasible)."""
    best, best_struct, n_feas = None, None, 0
    cust = inst.customers
    for routes in ordered_partitions(cust):
        lasts = {r[-1] for r in routes}                       # (4): last of each route transfers
        optional = [c for c in cust if c not in lasts]
        n_cars = len(routes)
        for mask in range(1 << len(optional)):
            transfers = set(lasts)
            for b, c in enumerate(optional):
                if mask >> b & 1:
                    transfers.add(c)
            if not load_ok(inst, routes, transfers):
                continue
            tl = trip_loads(inst, routes, transfers)
            for hubs in itertools.product(inst.satellites, repeat=len(transfers)):
                hub = dict(zip(sorted(transfers), hubs))
                for vroutes in ordered_partitions(sorted(transfers)):
                    if not vessel_load_ok(inst, vroutes, tl):
                        continue
                    n_ves = len(vroutes)
                    cost = (inst.penaltyCars * n_cars + inst.penaltyVessels * n_ves
                            + inst.cost_street * street_cost(inst, routes, hub)
                            + inst.cost_water * water_cost(inst, vroutes, hub))
                    if best is not None and cost >= best:
                        continue                              # cost is structure-only: prune
                    base, vs, h, u = schedule_constraints(inst, routes, transfers, hub, vroutes)
                    orders = _orders_for_26(inst, transfers, hub, vroutes) if enforce_26 else [None]
                    ok = False
                    for order in orders:
                        cons = list(base)
                        if order is not None:
                            cons += same_sat_pairs_ok(inst, transfers, hub, order)
                        good, _d = feasible(cons, vs)
                        if good:
                            ok = True
                            break
                    if not ok:
                        continue
                    n_feas += 1
                    if collect is not None:
                        collect.append(dict(routes=[list(r) for r in routes],
                                            transfers=sorted(transfers), hub=dict(hub),
                                            vroutes=[list(v) for v in vroutes], cost=cost))
                    if best is None or cost < best:
                        best, best_struct = cost, dict(
                            routes=[list(r) for r in routes], transfers=sorted(transfers),
                            hub=dict(hub), vroutes=[list(v) for v in vroutes],
                            n_cars=n_cars, n_vessels=n_ves)
    return best, best_struct, n_feas


def _orders_for_26(inst, transfers, hub, vroutes):
    """Candidate total orders for (26). Same-vessel pairs are already ordered by the vessel
    sequence; for pairs sharing a satellite across DIFFERENT vessels both orders must be tried,
    so every interleaving of the vessel sequences is enumerated. Tiny by construction."""
    seqs = [list(v) for v in vroutes]
    if len(seqs) == 1:
        return [seqs[0]]
    out = []

    def weave(prefix, rest):
        if all(not r for r in rest):
            out.append(list(prefix))
            return
        for k, r in enumerate(rest):
            if r:
                nxt = [list(x) for x in rest]
                head = nxt[k].pop(0)
                weave(prefix + [head], nxt)

    weave([], seqs)
    return out
