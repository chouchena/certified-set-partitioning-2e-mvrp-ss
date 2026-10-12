"""Where does our water cost come from? Four free checks, no solver. (d458)

WHY THIS EXISTS. Against the predecessors' Table 6 split at n100 we beat them on cars in all three
families and on street travel in two, and LOSE on water travel in all three by 12 to 21 percent.
The master ranks partitions by a bucketed street cost with no water term at all, so the natural
suspicion is that hub assignment is unpriced and that embedding water into the master is the fix.
This decides that before any of it is built.

A FIRST ATTEMPT WAS WRONG AND IS RECORDED SO IT IS NOT REPEATED. I first wrote the floor as one
dedicated CDC round trip per transfer. That is a CONSTRUCTION, not a bound -- vessels chain several
transfers into one tour -- so our incumbents came in at 0.31x of it. A floor our incumbent beats is
not a floor. The denominator has to be the number of TOURS, which load forces, not the number of
transfers, which it does not.

STAGE 1, three floors that are floors.
  F_tours = V_min * 2 * min_p D[CDC][p], V_min = ceil(transferred load / VESSEL_CAPACITY). C18-WLOAD
      caps a tour's cumulative load, so no routing uses fewer than V_min tours and each leaves CDC
      and returns. Prices nothing about hub choice: this is the floor if hubs were free.
  F_mst = MST(S_used u {CDC}). The union of the tours is a connected spanning subgraph of the
      satellites used and every edge is traversed at least once.
  F_reach = 2 * max_p in S_used D[CDC][p]. Under the triangle inequality, whichever vessel reaches
      the furthest chosen satellite goes out and back at least that far.

STAGE 2, the per-tour floor: sum over tours of 2 * max_p in tour D[CDC][p]. A floor GIVEN which
      transfers share a tour, so it prices the ROUTING alone and nothing else.

STAGE 3, greedy hub re-assignment scored on the TRUE objective with tours held fixed. Street is
      exact; water assumes each transfer keeps its tour. Timing is NOT re-checked, so a gain here is
      an OPTIMISTIC estimate of a prize and a zero here is the informative outcome: if re-pricing
      the hub cannot improve the objective even when allowed to ignore time windows, then hub
      choice is not the lever and no water term in any upstream model will make it one.

STAGE 4, the accounting identity transfers + cars == trips, checked rather than assumed, against
      the marginal water cost of a transfer and the car penalty. This is what says whether the water
      loss is a defect or the price of the car win.

    python analysis/water_floor_check.py --size 100
"""
import argparse
import glob
import io
import json
import math
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from instance_view import VESSEL_CAPACITY, LEFV_CAPACITY
from stamp import stamped


def street_walk(inst, sol):
    """Successors on the street, and the load attributed to each transfer.

    Mirrors `tep_chain_own_water.water_tours`, which builds tload from trips[r] with trips[r][-1]
    the transfer -- so the quantity C18-WLOAD sees is reproduced, not re-invented.
    """
    dep = inst.depot
    nxt, starts = {}, []
    for a, b in sol["xij"]:
        a, b = int(a), int(b)
        if a == dep:
            starts.append(b)
        else:
            nxt[a] = b
    tset = set(int(x) for x in sol["vi"])
    load = {}
    for s in starts:
        cur, acc = s, 0.0
        while cur is not None and cur != dep:
            acc += float(inst.nodes[cur].demand)
            if cur in tset:
                load[cur] = acc; acc = 0.0
            cur = nxt.get(cur)
    return nxt, load


def tours_of(sol, CDC):
    nxt, starts = {}, []
    for a, b in sol["yij"]:
        a, b = int(a), int(b)
        if a == CDC:
            starts.append(b)
        else:
            nxt[a] = b
    out = []
    for s in starts:
        seq, cur = [], s
        while cur is not None and cur != CDC:
            seq.append(cur); cur = nxt.get(cur)
        if seq:
            out.append(seq)
    return out


def mst(D, nodes):
    nodes = list(nodes)
    if len(nodes) < 2:
        return 0.0
    seen, rest, tot = {nodes[0]}, set(nodes[1:]), 0.0
    while rest:
        w, b = min((D[a][b], b) for a in seen for b in rest)
        tot += w; seen.add(b); rest.discard(b)
    return tot


def water_of(D, CDC, tours, hub):
    tot = 0.0
    for sq in tours:
        p = CDC
        for c in sq:
            tot += D[p][hub[c]]; p = hub[c]
        tot += D[p][CDC]
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--passes", type=int, default=3)
    a = ap.parse_args()
    prox = k_proximity(a.size)
    rows = []
    print("Water anatomy at n%d. Distances are raw water travel; objective terms are cost-weighted.\n" % a.size)
    print("%-7s %8s %8s %8s %8s %9s | %4s %5s %6s %6s"
          % ("cell", "water", "F_tours", "F_mst", "F_perT", "hub gain", "V", "V_min", "transf", "cars"))
    for f in sorted(glob.glob(os.path.join(ROOT, "runs", "postpass", "ownwater_*_n%d.json" % a.size))):
        c = os.path.basename(f).split("_")[1]
        sol = json.load(io.open(f, encoding="utf-8"))
        inst = V.load_instance(c, a.size, prox)
        D, CDC, dep = inst.D, inst.CDC, inst.depot
        cs, cw = float(inst.travelcoststreet), float(inst.travelcostwater)
        hub = {int(x): int(h) for x, h in zip(sol["vi"], sol["hubs"])}
        nxt, load = street_walk(inst, sol)
        T = tours_of(sol, CDC)
        water = water_of(D, CDC, T, hub)

        vmin = int(math.ceil((sum(load.values()) - 1e-9) / float(VESSEL_CAPACITY)))
        S = sorted(set(hub.values()))
        f_tours = vmin * 2.0 * min(D[CDC][p] for p in inst.satellites)
        f_mst = mst(D, [CDC] + S)
        f_reach = 2.0 * max(D[CDC][p] for p in S)
        f_pert = sum(2.0 * max(D[CDC][hub[x]] for x in sq) for sq in T)

        street = lambda h: sum(D[i][h[i]] + D[h[i]][nxt.get(i, dep)] for i in h)
        obj = lambda h: cs * street(h) + cw * water_of(D, CDC, T, h)
        cur, base, moves = dict(hub), obj(hub), 0
        for _ in range(a.passes):
            for i in sorted(hub):
                bq, bv = cur[i], obj(cur)
                for q in inst.satellites:
                    t = dict(cur); t[i] = q
                    v = obj(t)
                    if v < bv - 1e-6:
                        bq, bv = q, v
                if bq != cur[i]:
                    cur[i] = bq; moves += 1
        gain = 100.0 * (1 - obj(cur) / base)

        ntr, ncars = len(sol["vi"]), int(sol["nCars"])
        dem = sum(float(inst.nodes[i].demand) for i in inst.customers)
        rows.append(dict(cell=c, water=water, f_tours=f_tours, f_mst=f_mst, f_reach=f_reach,
                         f_pertour=f_pert, hub_gain_pct=gain, hub_moves=moves, vessels=int(sol["nVessel"]),
                         vmin=vmin, transfers=ntr, cars=ncars, trips=ntr + ncars,
                         trip_floor=int(math.ceil(dem / float(LEFV_CAPACITY))), hubs_used=len(S),
                         sats=len(list(inst.satellites)), car_penalty=float(inst.penalty_cars),
                         water_per_transfer=cw * water / max(ntr, 1), missing_load=len([x for x in hub if x not in load])))
        print("%-7s %8.1f %8.1f %8.1f %8.1f %8.2f%% | %4d %5d %6d %6d"
              % (c, water, f_tours, f_mst, f_pert, gain, sol["nVessel"], vmin, ntr, ncars))
    if not rows:
        print("  no banked solutions at this size"); return 1

    med = lambda k: st.median([r[k] for r in rows])
    bad = [r for r in rows if r["water"] < max(r["f_mst"], r["f_reach"], r["f_tours"], r["f_pertour"]) - 1e-6]
    pt = sorted(r["water"] / r["f_pertour"] for r in rows)
    ft = sorted(r["water"] / r["f_tours"] for r in rows)
    ident = sum(1 for r in rows if r["trips"] == r["transfers"] + r["cars"])
    print("\n  %d cells at n%d" % (len(rows), a.size))
    print("  1  water / tour floor, hubs free   : median %.2fx  min %.2fx  max %.2fx" % (st.median(ft), ft[0], ft[-1]))
    print("  2  water / per-tour floor          : median %.3fx  min %.3fx  max %.3fx  <- the ROUTING is tight"
          % (st.median(pt), pt[0], pt[-1]))
    print("  3  gain from re-pricing the hub    : median %.2f%%  max %.2f%%  |  no move helps on %d of %d cells"
          % (med("hub_gain_pct"), max(r["hub_gain_pct"] for r in rows),
             sum(1 for r in rows if r["hub_moves"] == 0), len(rows)))
    print("  4  transfers + cars == trips on %d of %d (an identity; this checks the transcription)" % (ident, len(rows)))
    print("     car penalty %.1f  vs  marginal water per transfer %.2f   -> trading a car for a transfer pays %.0f to 1"
          % (rows[0]["car_penalty"], med("water_per_transfer"), rows[0]["car_penalty"] / max(med("water_per_transfer"), 1e-9)))
    print("     trips above the demand floor: median %d  (satellites used: median %d of %d)"
          % (med("trips") - med("trip_floor"), med("hubs_used"), rows[0]["sats"]))
    print("     vessels above the load-forced count: median %d" % (med("vessels") - med("vmin")))
    if bad:
        print("  *** %d cell(s) BELOW a floor -- the floor or the accounting is wrong, not the solution: %s"
              % (len(bad), ", ".join(r["cell"] for r in bad[:6])))
    if any(r["missing_load"] for r in rows):
        print("  NOTE: some transfers were not reached by the street walk; V_min is understated there")
    p = os.path.join(ROOT, "runs", "oracle", "water_floor_check_n%d.json" % a.size)
    json.dump(stamped(dict(size=a.size, rows=rows)), io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
