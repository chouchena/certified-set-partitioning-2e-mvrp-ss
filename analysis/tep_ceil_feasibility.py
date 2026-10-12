"""Does the incumbent survive CEIL bucketing, and at which Δ? Pure Python, no solver (d421).

Test 3 asks whether the primal-rounded master can return the incumbent. That question has an
arithmetic core which needs no LP at all: take a verified solution, decompose it into trips and
chains, and replay each chain under the ceil-bucket semantics of the primal model --

    a car leaves the depot at H0 (bucket 0) or a satellite at its bucket's START time s_b;
    a trip's arrival bucket is ceil((earliest arrival at the hub - H0)/Δ)  [never earlier];
    its transfer may start at any bucket b_t >= that arrival for which (13) and (12,g) admit it;
    the car is free again at bucket b_t + τ/Δ, and the next trip leaves at s of that bucket;
    the last trip returns from its hub and must reach the depot by b_g;
    two transfers at one satellite must sit τ apart, i.e. in buckets τ/Δ apart.

If the replay survives, the incumbent is representable and Test 3 can only fail for solver
reasons. If it does not, Test 3 is predicted to fail at that Δ and the run is not worth its hour.
The output is the COARSEST Δ per cell at which the incumbent survives.

    python analysis/tep_ceil_feasibility.py [--cells ...] [--size 100] [--deltas 1,2,4]
"""
import argparse
import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from analysis.path_cover_fleet import trips_of
from k_comparison import k_proximity
from tep_pretests import best_artifact, chains_of

CELLS = ["C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208",
         "R201", "R202", "R203", "R204", "R205", "R206", "R207", "R208", "R209", "R210", "R211",
         "RC201", "RC202", "RC203", "RC204", "RC205", "RC206", "RC207", "RC208"]


def replay(inst, trips, chains, delta, ignore_booking=False):
    """Replay every chain under ceil-bucket semantics. Returns (ok, reason, buckets_used)."""
    nd, D = inst.nodes, inst.D
    g, d, U = inst.depot, inst.CDC, float(inst.tau)
    H0, H1 = float(nd[g].earliest), float(nd[g].latest)
    d0, d1 = float(nd[d].earliest), float(nd[d].latest)
    win = int(round(U / delta))
    nb = int(math.floor((H1 - H0) / delta))
    e = {c: max(float(nd[c].earliest), H0 + D[g][c]) for c in inst.customers}
    l = {c: min(float(nd[c].latest), H1 - D[c][g] - float(nd[c].service) - U) for c in inst.customers}
    sv = {c: float(nd[c].service) for c in inst.customers}
    taken = {}                                    # satellite -> sorted transfer buckets already used
    for ch in chains:
        loc, b_free = g, 0
        for k, i in enumerate(ch):
            seq, hub = trips[i]
            if hub is None:
                return False, "trip %d has no hub" % i, None
            t = (H0 + b_free * delta) + D[loc][seq[0]]
            for j, c in enumerate(seq):
                if j:
                    t += sv[seq[j - 1]] + D[seq[j - 1]][c]
                t = max(t, e[c])
                if t > l[c] + 1e-6:
                    return False, "window of customer %d misses by %.1f" % (c, t - l[c]), None
            arr = t + sv[seq[-1]] + D[seq[-1]][hub]
            b_arr = int(math.ceil((arr - H0) / delta - 1e-9))
            lo = d0 + D[d][hub]
            hi = min(d1 - U - D[hub][d], H1 - U - D[hub][g])
            b_t = max(b_arr, int(math.ceil((lo - H0) / delta - 1e-9)))
            used = taken.setdefault(hub, [])
            if not ignore_booking:
                while any(abs(b_t - x) < win for x in used):    # (26) as buckets
                    b_t += 1
            if H0 + b_t * delta > hi + 1e-6:
                return False, "no transfer bucket at satellite %d (latest %.1f)" % (hub, hi), None
            used.append(b_t); used.sort()
            b_free = b_t + win
            if b_free > nb:
                return False, "past the horizon after trip %d" % i, None
            loc = hub
        if H0 + b_free * delta + D[loc][g] > H1 + 1e-6:
            return False, "return to the depot misses by %.1f" % (H0 + b_free * delta + D[loc][g] - H1), None
    return True, "", sum(len(v) for v in taken.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default=",".join(CELLS)); ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--deltas", default="1,2,4,8", help="divisors of tau to try, coarsest first")
    ap.add_argument("--ignore-booking", action="store_true", help="drop the (26) slot collisions: isolates pure ceil DRIFT, and since earliest-possible transfers are optimal for downstream slack, a failure here is policy-independent")
    a = ap.parse_args()
    divs = [int(x) for x in a.deltas.split(",")]
    out = {}
    print("%-6s %6s  %s" % ("cell", "tau", "  ".join("t/%d" % d for d in divs)))
    for cell in a.cells.split(","):
        prox = k_proximity(a.size)
        inst = V.load_instance(cell, a.size, prox)
        got = best_artifact(cell, a.size)
        if not got:
            print("%-6s  no verified artifact" % cell); continue
        path, sol = got
        trips = trips_of(sol); chains = chains_of(sol, trips)
        marks, coarsest, reason = [], None, ""
        for dv in divs:
            delta = float(inst.tau) / dv
            ok, why, _ = replay(inst, trips, chains, delta, ignore_booking=a.ignore_booking)
            marks.append("OK " if ok else "-- ")
            if ok and coarsest is None:
                coarsest = delta
            if not ok and not reason:
                reason = "tau/%d: %s" % (dv, why)
        print("%-6s %6.0f  %s %s" % (cell, inst.tau, " ".join(marks), ("coarsest Delta %.1f" % coarsest) if coarsest else ("NONE -- " + reason)))
        out[cell] = dict(tau=float(inst.tau), coarsest=coarsest, marks=dict(zip(divs, [m.strip() == "OK" for m in marks])),
                         chains=len(chains), trips=len(trips), artifact=path, first_failure=reason)
    ok = [c for c, v in out.items() if v.get("coarsest")]
    print("\nincumbent survives ceil bucketing on %d of %d cells; by family: %s"
          % (len(ok), len(out), {f: sum(1 for c in ok if (c.startswith("RC") and f == "RC") or (f != "RC" and c[0] == f and not c.startswith("RC")))
                                 for f in ("C", "R", "RC")}))
    json.dump(out, io.open(os.path.join(ROOT, "runs", "oracle", "tep_ceil_feasibility.json"), "w", encoding="utf-8"), indent=1)
    print("wrote runs/oracle/tep_ceil_feasibility.json")


if __name__ == "__main__":
    main()
