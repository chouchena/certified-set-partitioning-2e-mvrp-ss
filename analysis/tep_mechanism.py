"""WHY does the master's trip selection beat the composition heuristics? (author, 09:05)

d338/d339 located the gap to K in WAITING INSIDE TRIPS, which follows the temporal spread of the
customer windows inside a satellite's region. If that diagnosis is right, the new solutions should
win by carrying less waiting, not by travelling less. This compares, for the same cell, the
previous best-known against the new master-selected solution, decomposing each into the quantities
the formulation actually controls:

  per trip   customers, load against Q, intra-trip travel, service, and WAITING -- the span from
             the first service start to the last service end, less travel and service
  per car    trips per car, and the idle time a car spends between trips (the tau wait and any
             slack on top of it)
  per cell   the street cost split into entry legs (hub or depot -> first customer), intra-trip
             travel, exit legs (last customer -> hub) and returns

Pure Python over banked artifacts, no solver.

    python analysis/tep_mechanism.py [--cells R204,C204,RC204]
"""
import argparse
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from analysis.path_cover_fleet import trips_of
from k_comparison import k_proximity
from tep_pretests import chains_of


def anatomy(inst, sol):
    """Decompose one solution into the quantities the formulation controls."""
    nd, D, g = inst.nodes, inst.D, inst.depot
    hi = {int(k): float(v) for k, v in (sol.get("hi") or {}).items()}
    ui = {int(k): float(v) for k, v in (sol.get("ui") or {}).items()}
    trips = trips_of(sol)
    chains = chains_of(sol, trips)
    rows = []
    for seq, hub in trips:
        svc = sum(float(nd[c].service) for c in seq)
        intra = sum(D[a][b] for a, b in zip(seq, seq[1:]))
        load = sum(float(nd[c].demand) for c in seq)
        span = (hi[seq[-1]] + float(nd[seq[-1]].service) - hi[seq[0]]) if (seq[0] in hi and seq[-1] in hi) else None
        wait = (span - intra - svc + float(nd[seq[0]].service)) if span is not None else None
        rows.append(dict(n=len(seq), load=load, intra=intra, svc=svc, span=span, wait=wait, hub=hub,
                         exit_leg=(D[seq[-1]][hub] if hub is not None else 0.0)))
    # car idle: between the transfer of trip k and the first service of trip k+1
    idle = []
    for ch in chains:
        for i, j in zip(ch, ch[1:]):
            a_hub, b_seq = trips[i][1], trips[j][0]
            if trips[i][0][-1] in ui and b_seq[0] in hi and a_hub is not None:
                idle.append(hi[b_seq[0]] - (ui[trips[i][0][-1]] + float(inst.tau) + D[a_hub][b_seq[0]]))
    waits = [r["wait"] for r in rows if r["wait"] is not None]
    return dict(trips=len(trips), cars=len(chains), cust_per_trip=st.mean(r["n"] for r in rows),
                load_per_trip=st.mean(r["load"] for r in rows), q_util=100.0 * st.mean(r["load"] for r in rows) / 50.0,
                intra_total=sum(r["intra"] for r in rows), exit_total=sum(r["exit_leg"] for r in rows),
                wait_total=(sum(waits) if waits else None), wait_per_trip=(st.mean(waits) if waits else None),
                idle_total=(sum(idle) if idle else None), idle_per_link=(st.mean(idle) if idle else None),
                trips_per_car=len(trips) / max(1, len(chains)),
                street=float(sol.get("FleetStreet", 0)) + float(sol.get("TravelStreet", 0)))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cells", default="R204,C204,RC204"); ap.add_argument("--size", type=int, default=100)
    a = ap.parse_args()
    out = {}
    for cell in a.cells.split(","):
        inst = V.load_instance(cell, a.size, k_proximity(a.size))
        new_p = os.path.join(ROOT, "runs", "postpass", "ipchain_%s_n%d.json" % (cell, a.size))
        if not os.path.exists(new_p):
            print("%-6s no master-selected solution yet" % cell); continue
        new = json.load(io.open(new_p, encoding="utf-8"))
        # the record this one beat: the cheapest verified artifact that is NOT the new route
        import bks_n100 as B
        prev = [r for r in B.scan(False) if r["cell"] == cell and "ipchain" not in r["file"]]
        old_rec = min(prev, key=lambda r: r["obj"])
        old = json.load(io.open(os.path.join(ROOT, old_rec["file"]), encoding="utf-8"))
        A, Bn = anatomy(inst, old), anatomy(inst, new)
        print("\n%s  tau %.0f   previous %.1f (%s)  ->  master-selected %.1f  (%+.2f%%)"
              % (cell, inst.tau, old["objVal"], os.path.basename(old_rec["file"]), new["objVal"],
                 100.0 * (new["objVal"] / old["objVal"] - 1)))
        print("  %-22s %12s %12s %10s" % ("", "previous", "new", "change"))
        for k, lab, fmt in (("cars", "cars", "%.0f"), ("trips", "trips", "%.0f"), ("trips_per_car", "trips per car", "%.2f"),
                            ("cust_per_trip", "customers per trip", "%.2f"), ("q_util", "capacity used %", "%.1f"),
                            ("intra_total", "travel inside trips", "%.1f"), ("exit_total", "legs to the hubs", "%.1f"),
                            ("street", "street cost", "%.1f"), ("wait_total", "WAITING in trips", "%.1f"),
                            ("wait_per_trip", "waiting per trip", "%.2f"), ("idle_total", "car idle between trips", "%.1f")):
            x, y = A.get(k), Bn.get(k)
            if x is None or y is None:
                continue
            print("  %-22s %12s %12s %9s" % (lab, fmt % x, fmt % y, ("%+.1f%%" % (100.0 * (y / x - 1))) if x else "-"))
        out[cell] = dict(previous=A, new=Bn, prev_obj=old["objVal"], new_obj=new["objVal"], prev_file=old_rec["file"])
    json.dump(out, io.open(os.path.join(ROOT, "runs", "oracle", "tep_mechanism.json"), "w", encoding="utf-8"), indent=1)
    print("\nwrote runs/oracle/tep_mechanism.json")


if __name__ == "__main__":
    main()
