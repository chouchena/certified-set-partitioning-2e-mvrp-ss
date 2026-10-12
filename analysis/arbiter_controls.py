"""FR2 and FR3 -- validate the ARBITER, the instrument that now adjudicates disagreements.

FR3 comes first because it is the load-bearing one. The arbiter is the sole evidence for the
big-M finding, and it has never been shown capable of disagreeing CORRECTLY -- while it has
already produced one WRONG verdict, blaming the MILP when its own enumeration was incomplete.
An instrument that has never been falsified is not evidence.

FR3 -- CONTROLS. Four, each perturbing the model and requiring the arbiter's answer to MOVE in
       the predicted direction. A control that changes the model and not the answer is silent.

       C1 ENUMERATION COMPLETENESS, aimed squarely at the bug that actually happened. The
          canonical enumeration is cross-checked against a NAIVE one -- every permutation with
          every split, deduplicated -- which has no canonical form to get wrong. Counts must
          match exactly. The first version of ordered_partitions would have failed this.
       C2 drop (26) on an instance where it binds     -> the optimum must FALL or hold
       C3 inflate the vessel penalty                  -> the optimum must RISE
       C4 widen every time window                     -> the optimum must FALL or hold

FR2 -- AGREEMENT WITH verifier3 ON EVERY ENUMERATED POINT. verifier3's behaviour is currently
       tested against 30 impaired solutions. The arbiter enumerates thousands of feasible
       structures per instance, each with an exact schedule from the difference-constraint
       system. Every one is handed to verifier3, which must ACCEPT it and must recompute the
       same objective the arbiter computed.

       This is the largest available increase in evidence about verifier3, and it is genuinely
       two-sided: the arbiter decides feasibility by negative-cycle detection in exact rationals,
       verifier3 by arithmetic on the committed values. They share no code.

       WHAT IT STILL CANNOT DO: both were written from one reading of K's article. A misreading
       present in both agrees with itself. That residue is oracle-residue-open's, and closing it
       is reading, not running.

    python analysis/arbiter_controls.py [--instances 8]
"""
import argparse
import itertools
import json
import os
import sys
import time
from fractions import Fraction as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import arbiter as A
import verifier3

OUT = os.path.join(ROOT, "runs", "oracle")


class VNodeShim:
    __slots__ = ("demand", "earliest", "latest", "service")

    def __init__(self, n):
        self.demand, self.service = n.demand, n.service
        self.earliest, self.latest = n.earliest, n.latest


class InstShim:
    """A Tiny instance in the shape verifier3 reads. Attribute names only -- no model crosses."""

    def __init__(self, t):
        self.customers = list(t.customers)
        self.satellites = list(t.satellites)
        self.CDC, self.depot, self.tau = t.CDC, t.garage, t.tau
        self.D = t.D
        n = max(t.nodes) + 1
        self.nodes = [VNodeShim(t.nodes[i]) if i in t.nodes
                      else VNodeShim(t.nodes[t.garage]) for i in range(n)]
        self.penalty_cars, self.penalty_vessels = t.penaltyCars, t.penaltyVessels
        self.travelcoststreet, self.travelcostwater = t.cost_street, t.cost_water
        self.name, self.size, self.proximity = "tiny", len(self.customers), 0.0


def solution_of(t, routes, transfers, hub, vroutes, dist, cost):
    """The arbiter's structure + its exact schedule, in the artifact format verifier3 reads."""
    z = dist[("z",)]
    xij, yij = [], []
    for r in routes:
        seq = [t.garage] + r + [t.garage]
        for a in range(len(seq) - 1):
            xij.append([seq[a], seq[a + 1]])
    for v in vroutes:
        seq = [t.CDC] + list(v) + [t.CDC]
        for a in range(len(seq) - 1):
            yij.append([seq[a], seq[a + 1]])
    tset = sorted(transfers)
    return {"xij": xij, "yij": yij, "vi": tset, "hubs": [hub[c] for c in tset],
            "nCars": len(routes), "nVessel": len(vroutes),
            "hi": {str(i): float(dist[("h", i)] - z) for i in [t.garage] + t.customers},
            "ui": {str(i): float(dist[("u", i)] - z) for i in tset},
            "objVal": float(cost),
            "_posts_26": True, "_valid_bigm": True, "_proximity": 0.0}


def enumerate_feasible(t, limit=None, enforce_26=True):
    """Every feasible structure with its exact schedule. Mirrors brute_optimum's loop."""
    out = []
    cust = t.customers
    for routes in A.ordered_partitions(cust):
        lasts = {r[-1] for r in routes}
        optional = [c for c in cust if c not in lasts]
        for mask in range(1 << len(optional)):
            transfers = set(lasts)
            for b, c in enumerate(optional):
                if mask >> b & 1:
                    transfers.add(c)
            if not A.load_ok(t, routes, transfers):
                continue
            tl = A.trip_loads(t, routes, transfers)
            for hubs in itertools.product(t.satellites, repeat=len(transfers)):
                hub = dict(zip(sorted(transfers), hubs))
                for vroutes in A.ordered_partitions(sorted(transfers)):
                    if not A.vessel_load_ok(t, vroutes, tl):
                        continue
                    base, vs, _h, _u = A.schedule_constraints(t, routes, transfers, hub, vroutes)
                    orders = (A._orders_for_26(t, transfers, hub, vroutes) if enforce_26
                              else [None])
                    for order in orders:
                        cons = list(base)
                        if order is not None:
                            cons += A.same_sat_pairs_ok(t, transfers, hub, order)
                        ok, dist = A.feasible(cons, vs)
                        if not ok:
                            continue
                        cost = (t.penaltyCars * len(routes) + t.penaltyVessels * len(vroutes)
                                + t.cost_street * A.street_cost(t, routes, hub)
                                + t.cost_water * A.water_cost(t, vroutes, hub))
                        out.append((routes, transfers, hub, vroutes, dist, cost))
                        break
                    if limit and len(out) >= limit:
                        return out
    return out


def naive_partitions(items):
    """Every ordered partition, built with NO canonical form: all permutations x all splits,
    deduplicated. Slow and obviously correct -- the reference C1 checks the fast one against."""
    items = list(items)
    seen, out = set(), []
    n = len(items)
    for perm in itertools.permutations(items):
        for cuts in itertools.product([0, 1], repeat=max(0, n - 1)):
            routes, cur = [], [perm[0]]
            for k, c in enumerate(cuts):
                if c:
                    routes.append(cur); cur = []
                cur.append(perm[k + 1])
            routes.append(cur)
            key = tuple(sorted(tuple(r) for r in routes))
            if key not in seen:
                seen.add(key); out.append([list(r) for r in routes])
    return out


def fr3(seeds):
    print("FR3 -- CONTROLS. Can the arbiter report a DIFFERENT answer when the model changes?")
    print()
    fails = []

    print("   C1 ENUMERATION COMPLETENESS -- canonical vs a naive all-permutations reference")
    for n in (3, 4, 5):
        fast = sum(1 for _ in A.ordered_partitions(list(range(1, n + 1))))
        slow = len(naive_partitions(list(range(1, n + 1))))
        ok = fast == slow
        print("      n=%d  canonical %4d   naive %4d   %s" % (n, fast, slow,
                                                              "ok" if ok else "MISMATCH"))
        if not ok:
            fails.append("C1 n=%d: canonical %d != naive %d" % (n, fast, slow))
    print("      (the enumeration bug found by the MILP would have failed this)")

    print()
    print("   C2/C3/C4 -- perturb the model, require the optimum to MOVE as predicted")
    print("      %-6s %12s %12s %12s %12s" % ("seed", "baseline", "no (26)", "3x vessel",
                                              "wide windows"))
    moved = {"C2": 0, "C3": 0, "C4": 0}
    tested = 0
    for s in seeds:
        t = A.Tiny(s, 4, 1)
        base, _st, _n = A.brute_optimum(t, enforce_26=True)
        if base is None:
            continue
        tested += 1
        no26, _s2, _n2 = A.brute_optimum(t, enforce_26=False)
        t3 = A.Tiny(s, 4, 1); t3.penaltyVessels = t3.penaltyVessels * 3
        pen, _s3, _n3 = A.brute_optimum(t3, enforce_26=True)
        t4 = A.Tiny(s, 4, 1)
        for i in t4.customers:
            t4.nodes[i].earliest = F(0); t4.nodes[i].latest = F(5000)
        wide, _s4, _n4 = A.brute_optimum(t4, enforce_26=True)
        if no26 is not None and no26 <= base:
            moved["C2"] += 1 if no26 < base else 0
        if pen is not None and pen > base:
            moved["C3"] += 1
        if wide is not None and wide <= base:
            moved["C4"] += 1 if wide < base else 0
        for nm, val, rule in (("C2", no26, "<= baseline"), ("C3", pen, "> baseline"),
                              ("C4", wide, "<= baseline")):
            if val is None:
                continue
            bad = ((nm == "C3" and val <= base) or (nm != "C3" and val > base))
            if bad:
                fails.append("%s seed %d: %.3f violates '%s %s'"
                             % (nm, s, float(val), nm, rule))
        print("      %-6d %12.3f %12s %12s %12s"
              % (s, float(base),
                 "-" if no26 is None else "%.3f" % float(no26),
                 "-" if pen is None else "%.3f" % float(pen),
                 "-" if wide is None else "%.3f" % float(wide)))
    print()
    print("      instances %d | (26) dropped CHANGED the optimum on %d | vessel penalty moved "
          "it on %d | widening moved it on %d" % (tested, moved["C2"], moved["C3"], moved["C4"]))
    if tested and moved["C3"] == 0:
        fails.append("C3 never moved the optimum on %d instances -- tripling the vessel penalty "
                     "must change a cost the arbiter computes; a silent control is a failure"
                     % tested)
    print()
    print("   FR3: %d failure(s)" % len(fails))
    for f in fails[:6]:
        print("      " + f)
    return fails


def fr2(seeds, cap, sats=1):
    print()
    print("FR2 -- AGREEMENT WITH verifier3 ON EVERY ENUMERATED FEASIBLE POINT.  |P|=%d" % sats)
    print("       verifier3's behaviour is otherwise tested against 30 impaired solutions.")
    print()
    print("   %-6s %11s %10s %10s %12s" % ("seed", "structures", "ACCEPT", "REJECT", "obj mismatch"))
    fails, tot, acc, obj_bad = [], 0, 0, 0
    for s in seeds:
        t = A.Tiny(s, 4, sats)
        pts = enumerate_feasible(t, limit=cap)
        inst = InstShim(t)
        a = r = ob = 0
        for routes, transfers, hub, vroutes, dist, cost in pts:
            sol = solution_of(t, routes, transfers, hub, vroutes, dist, cost)
            run = verifier3.verify_solution(inst, sol, cell="tiny", size=len(t.customers),
                                            proximity=0.0, label="arb")
            if run.verdict() == verifier3.ACCEPT:
                a += 1
            else:
                r += 1
                if len(fails) < 8:
                    fails.append("seed %d: the arbiter says FEASIBLE, verifier3 says %s (%s)"
                                 % (s, run.verdict(),
                                    "; ".join(v[:60] for v in
                                              [f.cls for f in run.findings
                                               if f.severity == "VIOLATION"][:2]) or "-"))
            rec = (run.objective or {}).get("recomputed")
            if rec is not None and abs(float(rec) - float(cost)) > 1e-6:
                ob += 1
                if len(fails) < 8:
                    fails.append("seed %d: arbiter cost %.4f, verifier3 recomputed %.4f"
                                 % (s, float(cost), float(rec)))
        tot += len(pts); acc += a; obj_bad += ob
        print("   %-6d %11d %10d %10d %12d" % (s, len(pts), a, r, ob))
    print()
    print("   points %d | ACCEPT %d | REJECT %d | objective mismatches %d"
          % (tot, acc, tot - acc, obj_bad))
    print("   FR2: %d failure(s)" % len(fails))
    for f in fails[:6]:
        print("      " + f)
    return fails, tot


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, default=8)
    ap.add_argument("--cap", type=int, default=4000, help="max points per instance for FR2")
    ap.add_argument("--sats", type=int, default=1,
                    help="satellites. |P|=1 is the default: the only setting where (26) can bind "
                         "at enumerable size. |P|=2 widens FR2 coverage.")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    seeds = list(range(a.instances))
    t0 = time.time()
    f3 = fr3(seeds)
    f2, npts = fr2(seeds, a.cap, a.sats)
    tot = len(f2) + len(f3)
    json.dump(stamped({"fr3_failures": f3, "fr2_failures": f2, "fr2_points": npts,
               "verdict": "PASS" if not tot else "FAIL",
               "wall_s": round(time.time() - t0, 1)}, __file__),
              open(os.path.join(OUT, "arbiter_controls_p%d.json" % a.sats), "w"), indent=1, default=str)
    print()
    print("ARBITER VALIDATION: %s   %d failure(s)   %.1f min"
          % ("PASS" if not tot else "FAIL", tot, (time.time() - t0) / 60))
    if not tot:
        print()
        print("   The arbiter moves when the model moves, its enumeration matches a reference")
        print("   with no canonical form to get wrong, and it agrees with verifier3 on %d"
              % npts)
        print("   independently enumerated points -- feasibility AND objective, by two methods")
        print("   sharing no code.")
        print()
        print("   NOT ESTABLISHED: both were written from one reading of K's article, and a")
        print("   misreading present in both agrees with itself.")
    return 1 if tot else 0


if __name__ == "__main__":
    sys.exit(main())
