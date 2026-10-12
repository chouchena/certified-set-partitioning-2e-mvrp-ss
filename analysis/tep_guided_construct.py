"""FIX B: realise the master's trip partition with MINIMAL routing-respecting consolidation (d449).

Author, 2026-09-25: "inherit the routing and build a constructor-solution fed by it", and then
twice: "it wont help without minimal routing-respecting greedy consolidation."

That objection is correct and it decides the design. The car penalty dominates the objective, so a
realisation that follows the trips but consolidates them badly is worse than useless -- it will
lose to the chaining route wherever the chaining route works, and prove nothing where it does not.
A first-fit assignment of trips to cars is exactly that mistake.

SO CONSOLIDATION IS DONE BY MATCHING, NOT GREEDILY. Build a compatibility digraph over the master's
trips: trip A may precede trip B on one car if a car finishing A, transferring at A's hub, can
still reach B's first customer inside its window. The fewest cars covering every trip is then the
MINIMUM PATH COVER of that digraph, which for an acyclic digraph equals `|trips| - |maximum
bipartite matching|` and is computed exactly by augmenting paths. No mixed-integer program, no work
limit, and the car count is minimal for the relation given.

THE RELATION IS OPTIMISTIC, AND THE SCHEDULER IS THE JUDGE. Compatibility is tested with A at its
EARLIEST completion and B at its LATEST start, which is the most permissive reading, so a proposed
chain can still fail once real times are committed. The scheduler therefore walks each chain and
BREAKS it the moment a trip will not schedule, opening a fresh car instead. Breaking a chain only
ever adds cars; it can never produce an infeasible solution. The matching proposes, the scheduler
disposes.

WHY THIS CANNOT REPRODUCE THE FAILURE IT REPLACES. `assemble_precluster.chain` emits a street and
hopes a timetable exists; it carries no vessel capacity and no vessel routing, and on C204 and C205
at n100 it returned streets the exact re-timing rejected in about a second. Here every service time
and every transfer is committed through `greedy26._h_ok` and `_transfer` as it is chosen, so the
output is feasible for the full problem by construction. The only failure mode left is a single
trip that cannot be scheduled even alone from the depot, which is a defect in the SELECTION and is
reported as such.

NOT A FALLBACK. It does not run when something else fails. It is a different realisation of stage
three and it replaces the one stage that currently solves the predecessors' model.

KNOWN WEAKNESS, STATED UP FRONT: `greedy26` uses singleton vessels, one per transfer, so the water
side is feasible but expensive. Expect a worse objective than the chaining route where that route
works. The cells that matter for this fix are the ones where it does not.

    python analysis/tep_guided_construct.py C204 --size 100

DEFECT FOUND 2026-09-25, BEFORE ANY RESULT WAS BANKED. Minimum path cover by bipartite matching
requires an ACYCLIC precedence relation. The relation built here is NOT acyclic: with overlapping
time windows trip A can precede B and B precede A. The matching then contains cycles, and the
chain walk below starts only from unmatched nodes, so every trip inside a cycle is SILENTLY
DROPPED. On RC204 this produced a 'solution' serving 9 of 100 customers, reported as 1 car and
objective 494.6, which verifier3 rejected only via an A-ALIEN violation. No number from this
module is a result. Fixing it needs either a genuinely acyclic relation (order trips by earliest
start and allow only forward links) or a path cover that tolerates cycles, plus an assertion that
every trip appears in exactly one chain.
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from stamp import stamped
from greedy26 import Greedy26, TOL


# ---------------------------------------------------------------- consolidation
def trip_windows(inst, trips):
    """Earliest completion and latest start of each trip, scheduled alone."""
    nd, D = inst.nodes, inst.D
    out = []
    for t in trips:
        h = max(float(nd[t[0]].earliest), float(nd[inst.depot].earliest) + D[inst.depot][t[0]])
        ok = h <= float(nd[t[0]].latest) + 1e-9
        for a, b in zip(t, t[1:]):
            h = max(h + float(nd[a].service) + D[a][b], float(nd[b].earliest))
            if h > float(nd[b].latest) + 1e-9:
                ok = False
        end = h + float(nd[t[-1]].service)
        # latest start: walk the windows backwards
        l = float(nd[t[-1]].latest)
        for a, b in zip(reversed(t[:-1]), reversed(t[1:])):
            l = min(float(nd[a].latest), l - float(nd[a].service) - D[a][b])
        out.append(dict(trip=t, earliest_end=end, latest_start=l, feasible=ok))
    return out


def min_path_cover(inst, tw):
    """Fewest cars covering every trip, by maximum matching on an ACYCLIC precedence relation.

    Minimum path cover by bipartite matching is only correct on a DAG. The natural precedence
    relation here is NOT acyclic -- with overlapping windows trip A can precede B and B precede A
    -- and version one of this function built it anyway. The matching then contained cycles, the
    chain walk started only from unmatched nodes, and every trip inside a cycle was SILENTLY
    DROPPED: on RC204 it returned 1 car, 3 transfers and 9 served customers of 100 (d449).

    The fix is to admit only FORWARD edges in a fixed order (earliest completion). That can only
    remove edges, so it never invents an unrealisable chain; it may yield more chains than the
    unrestricted relation, which is the safe direction. The cover is then asserted to be a cover.
    """
    nd, D, tau = inst.nodes, inst.D, float(inst.tau)
    n = len(tw)
    sats = list(inst.satellites)
    order = sorted(range(n), key=lambda i: tw[i]["earliest_end"])
    pos = {t: p for p, t in enumerate(order)}
    adj = [[] for _ in range(n)]
    for i in range(n):
        hop = min(D[tw[i]["trip"][-1]][p] for p in sats)
        ready = tw[i]["earliest_end"] + hop + tau
        for j in range(n):
            if i == j or pos[j] <= pos[i]:
                continue                      # forward edges only -> the relation is a DAG
            best = min(D[p][tw[j]["trip"][0]] for p in sats)
            if ready + best <= tw[j]["latest_start"] + 1e-9:
                adj[i].append(j)
    matchL = [-1] * n; matchR = [-1] * n

    def try_aug(u, seen):
        for v in adj[u]:
            if seen[v]:
                continue
            seen[v] = True
            if matchR[v] == -1 or try_aug(matchR[v], seen):
                matchR[v] = u; matchL[u] = v
                return True
        return False

    sys.setrecursionlimit(10000)
    for u in order:
        try_aug(u, [False] * n)
    chains = []
    for s in (i for i in range(n) if matchR[i] == -1):
        ch, cur = [s], s
        while matchL[cur] != -1:
            cur = matchL[cur]; ch.append(cur)
        chains.append(ch)
    # 3b: the cover must BE a cover. This assertion is what version one lacked.
    flat = [i for ch in chains for i in ch]
    assert len(flat) == n and set(flat) == set(range(n)), (
        "min_path_cover did not partition the trips: %d of %d covered" % (len(set(flat)), n))
    return chains, sum(1 for u in range(n) if matchL[u] != -1)


class Guided(Greedy26):
    """greedy26 whose customer order is dictated by the master's trips, in chain order."""

    def __init__(self, inst, chains_of_trips, car_capacity=None, street='online', water='tours'):
        super().__init__(inst, transfer_every=10 ** 9, car_capacity=car_capacity)
        self.order = [t for ch in chains_of_trips for t in ch]
        self.declined = None
        self.breaks = 0
        self.car_last = []
        self.street = street      # 'online' probes every candidate; 'firstfit' takes list order
        self.water = water        # 'tours' consolidates vessels; 'singleton' is one per transfer

    def _try_trip(self, trip, cur, ready, from_hub, H, U, arcs, transfers, hubs, probe=False):
        """Schedule one trip from the car's current state. Returns the new state, or None."""
        nd, D, depot, tau = self.nd, self.D, self.depot, self.tau
        # TIMING uses where the car physically is -- the hub it just transferred at. The street
        # ARC does not: xij may only touch customers and the depot (verifier3 A-ALIEN), because a
        # street arc LEAVING a transfer customer is charged as the detour D[i][p] + D[p][j]
        # through that customer's own satellite. Version two emitted [hub, c] and every cell
        # failed A-ALIEN (d449).
        origin = from_hub if from_hub is not None else cur
        arc_tail = cur                      # depot on a fresh car, else the previous customer
        extra = tau if from_hub is not None else (nd[cur].service if cur != depot else 0.0)
        loc_H, loc_U, loc_arcs, loc_tr, loc_hubs = {}, {}, [], [], []
        load = 0.0
        h = max(ready + extra + D[origin][trip[0]], float(nd[trip[0]].earliest))
        prev = arc_tail
        booked_here = []
        def _rollback():
            for pp, uu in booked_here:
                self.booked[pp].remove(uu)
        for pos, c in enumerate(trip):
            if pos > 0:
                h = max(h + float(nd[prev].service) + D[prev][c], float(nd[c].earliest))
            if not self._h_ok(c, h):
                _rollback(); return None
            if load + float(nd[c].demand) > self.cap + TOL:
                _rollback(); return None
            last = (pos == len(trip) - 1)
            res = None
            if last:
                res = self._transfer(c, h, last_in_route=True) or self._transfer(c, h, last_in_route=False)
                if res is None:
                    _rollback(); return None
            loc_H[c] = h; loc_arcs.append([prev, c]); load += float(nd[c].demand)
            prev = c
            if res is not None:
                p, u = res
                # `_transfer` only FINDS a slot; the caller must BOOK it. greedy26 does this at
                # its own two commit points (lines 202 and 226). Version three omitted it, so
                # every transfer was scheduled against an empty table and all four cells failed
                # C26, the tau-spacing constraint (d449).
                self.booked[p].append(u); booked_here.append((p, u))
                loc_U[c] = u; loc_tr.append(c); loc_hubs.append(p)
        if probe:
            # a probe must leave NO trace: every slot it booked is released before returning
            _rollback()
            return (trip[-1], loc_U[trip[-1]], loc_hubs[-1])
        H.update(loc_H); U.update(loc_U); arcs.extend(loc_arcs)
        transfers.extend(loc_tr); hubs.extend(loc_hubs)
        return (trip[-1], loc_U[trip[-1]], loc_hubs[-1])

    def build(self):
        """Consolidate ONLINE: test each candidate against the car's committed state (d449 A6)."""
        arcs, transfers, hubs = [], [], []
        H, U = {}, {}
        n_cars = 0
        pending = list(self.order)
        while pending:
            n_cars += 1
            cur, ready, from_hub = self.depot, float(self.nd[self.depot].earliest), None
            placed_any = False
            while pending:
                best = None
                if self.street == "firstfit":
                    # the NAIVE arm: take the next trip in the given order if it fits, else close
                    r = self._try_trip(pending[0], cur, ready, from_hub, H, U, arcs, transfers, hubs, probe=True)
                    best = (0, r) if r is not None else None
                else:
                    for idx, trip in enumerate(pending):
                        r = self._try_trip(trip, cur, ready, from_hub, H, U, arcs, transfers, hubs, probe=True)
                        if r is None:
                            continue
                        # earliest transfer time wins: it leaves the car readiest for another trip
                        if best is None or r[1] < best[1][1]:
                            best = (idx, r)
                if best is None:
                    break
                idx = best[0]
                st = self._try_trip(pending[idx], cur, ready, from_hub, H, U, arcs, transfers, hubs)
                if st is None:                       # cannot happen: the probe just succeeded
                    raise AssertionError("probe succeeded but the commit failed -- probe leaked state")
                cur, ready, from_hub = st
                pending.pop(idx)
                placed_any = True
            if not placed_any:
                self.declined = dict(trip=pending[0], reason="not schedulable alone from the depot")
                return None
            self.car_last.append(cur)
        self.breaks = 0
        if not transfers:
            self.declined = dict(reason="no transfer committed")
            return None
        nd, D, depot, tau = self.nd, self.D, self.depot, self.tau
        for last in self.car_last:
            arcs.append([last, depot])
        hub_of = dict(zip(transfers, hubs))
        h0 = float(nd[depot].earliest)
        for r_last in {a[0] for a in arcs if a[1] == depot}:
            if r_last in hub_of:
                h0 = max(h0, U[r_last] + tau + D[hub_of[r_last]][depot])
            else:
                h0 = max(h0, H[r_last] + float(nd[r_last].service) + D[r_last][depot])
        if h0 > float(nd[depot].latest) + TOL:
            self.declined = dict(reason="depot return window violated", h0=h0)
            return None
        H[0] = h0
        # ---- vessel tours, by the same online rule as the cars (d449 A7) ----------------
        # Committed u and hub per transfer, so this cannot affect street feasibility. Legality is
        # taken from verifier3: C20-WSEQ  u(b) >= u(a) + tau + travel(hub_a, hub_b), and
        # C18-WLOAD  cumulative trip load <= vessel capacity.
        # the verifier reads the vessel capacity from instance_view, not from the instance
        # object; my first attempt guessed two attribute names, got 0, and the capacity test
        # silently did not apply -- every cell then failed C18-WLOAD (d449)
        from instance_view import VESSEL_CAPACITY as Qw
        assert Qw and Qw > 0, "vessel capacity unavailable -- refusing to build without it"
        tload = {}
        for t in self.order:
            tload[t[-1]] = sum(float(nd[c].demand) for c in t)
        tours = []                                   # each: dict(seq=[...], load=..)
        if self.water == "singleton":
            tours = [dict(seq=[c], load=tload[c]) for c in transfers]   # the NAIVE arm
        for c in ([] if self.water == "singleton" else sorted(transfers, key=lambda x: U[x])):
            best = None
            for tr in tours:
                a = tr["seq"][-1]
                if U[c] + 1e-9 < U[a] + tau + D[hub_of[a]][hub_of[c]]:
                    continue                          # C20-WSEQ
                if tr["load"] + tload[c] > Qw + TOL:
                    continue                          # C18-WLOAD
                add = D[hub_of[a]][hub_of[c]]
                if best is None or add < best[1]:
                    best = (tr, add)
            if best is None:
                tours.append(dict(seq=[c], load=tload[c]))
            else:
                best[0]["seq"].append(c); best[0]["load"] += tload[c]
        yij = []
        for tr in tours:
            prev = self.CDC
            for c in tr["seq"]:
                yij.append([prev, c]); prev = c
            yij.append([prev, self.CDC])
        want = {c for t in self.order for c in t}
        got = {int(k) for k in H if int(k) != 0}
        assert got == want, ("guided construction dropped work: %d of %d customers scheduled"
                             % (len(got), len(want)))
        assert len(transfers) == len(self.order), (
            "one transfer per trip expected: %d transfers for %d trips" % (len(transfers), len(self.order)))
        sol = {"xij": [list(x) for x in arcs], "vi": list(transfers), "hubs": list(hubs), "yij": yij,
               "nCars": n_cars, "nVessel": len(tours),
               "hi": {str(k): float(v) for k, v in H.items()},
               "ui": {str(k): float(v) for k, v in U.items()}}
        sol["objVal"] = self._objective(sol, hub_of)
        sol["_posts_26"] = True
        sol["_timetable_source"] = "greedy26_guided_online"
        return sol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--select-suffix", default="")
    ap.add_argument("--street", default="online", choices=["online", "firstfit"])
    ap.add_argument("--water", default="tours", choices=["tours", "singleton"])
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    src = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s_ip%s.json"
                       % (a.cell, "" if a.size == 100 else "_n%d" % a.size,
                          ("_" + a.select_suffix) if a.select_suffix else ""))
    ip = json.load(io.open(src, encoding="utf-8"))["ip"]
    trips = [list(t) for t in ip["trips"]]
    print("%s n%d: %d trips from the master IP" % (a.cell, a.size, len(trips)), flush=True)

    t0 = time.time()
    tw = trip_windows(inst, trips)
    infeas = [i for i, x in enumerate(tw) if not x["feasible"]]
    chains, matched = min_path_cover(inst, tw)
    print("  consolidation: %d trips -> %d chains by maximum matching (%d links), %.2f s"
          % (len(trips), len(chains), matched, time.time() - t0), flush=True)
    if infeas:
        print("  NOTE: %d selected trip(s) are not schedulable alone -- a SELECTION defect" % len(infeas), flush=True)

    g = Guided(inst, [[tw[i]["trip"] for i in ch] for ch in chains], street=a.street, water=a.water)
    t1 = time.time(); sol = g.build(); secs = time.time() - t1
    if sol is None:
        print("  guided construction DECLINED in %.1f s: %s" % (secs, g.declined), flush=True)
        return 1
    run = V.verify_solution(inst, sol, cell=a.cell, size=a.size, proximity=prox, label="guided")
    bad = [x for x in run.findings if x.severity != "TOLERANCE"]
    ok = (not bad) and (not run.blocking)
    print("  scheduled in %.1f s: obj %.3f, %d cars (%d chain breaks), %d vessels | verifier3 %s"
          % (secs, sol["objVal"], sol["nCars"], g.breaks, sol["nVessel"], "PASS" if ok else "FAIL"), flush=True)
    for f in (bad or [])[:3]:
        print("      %s %s" % (f.severity, f.cls))
    prev = os.path.join(ROOT, "runs", "postpass", "ipchain_%s_n%d.json" % (a.cell, a.size))
    if os.path.exists(prev):
        p = json.load(io.open(prev, encoding="utf-8"))
        print("  chaining route on this cell: %.3f, %d cars, %d vessels  (guided %+.2f%%)"
              % (p["objVal"], p["nCars"], p["nVessel"], 100.0 * (sol["objVal"] / p["objVal"] - 1)), flush=True)
    else:
        print("  the chaining route produced NOTHING on this cell", flush=True)
    if ok:
        sol["size"] = a.size; sol["_proximity"] = prox; sol["_verified"] = True
        sol["_cars_lower_from_matching"] = len(chains)
        dst = os.path.join(ROOT, "runs", "postpass", "guided%s_%s_n%d.json" % (a.tag, a.cell, a.size))
        json.dump(stamped(sol, "analysis/tep_guided_construct.py", "greedy26.py"),
                  io.open(dst, "w", encoding="utf-8"), indent=1, default=str)
        print("  banked %s" % os.path.relpath(dst, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
