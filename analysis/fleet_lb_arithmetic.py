"""QUICK fleet-count test: an arithmetic lower bound on nCars, computed in milliseconds.

MOTIVATION. FINDING_S2p_control_failed_primal_beats_cplex showed the MILP route is
dead at |C| = 20: CPLEX could not find a known-to-exist one-car solution in 420 s
of dedicated feasibility search. Proving INFEASIBILITY that way is strictly
harder. So the question "can we drop one car?" needs an instrument that is not a
MILP solve.

THE BOUND. Every street vehicle operates inside the depot window
[depot.earliest, depot.latest], so with k cars the total vehicle-time available
is at most k * W. All customers must be served, and the vehicles must travel
between them. Hence

    k * W  >=  sum_i serviceTime_i  +  (a valid lower bound on total street travel)

    =>  nCars >= ceil( (service + travel_LB) / W )

TRAVEL_LB uses the assignment relaxation: in any feasible solution every customer
has exactly one outgoing street arc (Const2), so the total travelled distance is
at least the sum over customers of the cheapest available outgoing arc. That is
valid and costs one pass over the distance matrix.

RESULT 2026-09-14: THIS BOUND IS TOO WEAK TO BE USEFUL AT |C| = 20. Measured
work/W ratios are 0.24-0.57 across all 27 cells, so it returns fleet_lb = 1
everywhere and never rules out a drop. The reason is diagnostic and worth
keeping: the DEPOT window (1011-3489) dwarfs total service plus assignment
travel (271-1903), so aggregate time is nowhere near binding. The difficulty at
this size lives in the PER-CUSTOMER time windows, which this relaxation discards
entirely -- consistent with tw-width-drives-k-difficulty. Retained as a recorded
negative result and as a cheap screen at larger |C|, where the ratio must grow.

This is CONSERVATIVE on purpose -- transfer durations and the return-to-depot legs
are EXCLUDED, so the true requirement is higher than what is computed here. A
bound that says "2 cars are needed" is therefore trustworthy; one that says
"1 is enough" says only that this test could not rule it out.
"""
import sys, os, math, json, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis.stamp import stamped
from build_instance import build                       # noqa: E402
from lp_component_anatomy import harvest               # noqa: E402


def fleet_lb(cell, size):
    p = build(cell, size)
    D = p.DistMatrix
    C = list(p.customers)
    W = p.nodes[0].latest - p.nodes[0].earliest
    service = sum(p.nodes[i].serviceTime for i in C)
    # assignment relaxation: each customer has exactly one outgoing street arc
    travel = 0.0
    for i in C:
        cand = [D[i][j] for j in ([0] + C) if j != i]
        travel += min(cand) if cand else 0.0
    need = service + travel
    return dict(cell=cell, window=W, service=service, travel_lb=travel,
                work=need, fleet_lb=math.ceil(need / W - 1e-9),
                ratio=need / W)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/fleet_lb_arithmetic.json")
    a = ap.parse_args()

    kref = json.load(open("data/karademir2025/k_reference.json"))
    # K publish a per-instance table at |C| = 10, 20 and 30 ONLY. Indexing it
    # unconditionally made this screen unrunnable at 50 and 100 -- the exact sizes the
    # module docstring retains it for. With --cells given, the table is not needed.
    per = kref["table3"]["per_instance"].get(str(a.size), {})
    cells = [c.strip() for c in a.cells.split(",") if c.strip()] or sorted(per)
    best = harvest(set(cells), a.size)

    print(f"{'cell':7s} {'window':>8s} {'service':>8s} {'travelLB':>9s} {'work/W':>7s} "
          f"{'fleetLB':>7s} {'ours':>5s}  verdict")
    rows = []
    for c in cells:
        r = fleet_lb(c, a.size)
        nc = (best.get(c) or {}).get("nCars")
        r["our_cars"] = nc
        if nc is None:
            v = "(no incumbent)"
        elif r["fleet_lb"] >= nc and r["fleet_lb"] > 1:
            v = "PROVED: fleet cannot be reduced"
        elif r["fleet_lb"] >= nc:
            # VACUOUS: fleet_lb == nc == 1 is the trivial statement 1 >= 1.
            v = "vacuous (LB=1, ours=1) -- proves nothing"
        else:
            v = f"drop to {nc-1} NOT ruled out"
        r["verdict"] = v
        rows.append(r)
        print(f"{c:7s} {r['window']:8.0f} {r['service']:8.0f} {r['travel_lb']:9.1f} "
              f"{r['ratio']:7.3f} {r['fleet_lb']:7d} {str(nc):>5s}  {v}")

    os.makedirs("runs", exist_ok=True)
    json.dump(stamped(rows, __file__), open(a.out, "w"), indent=1)
    print("\nwrote", a.out)
    print("\nA fleetLB >= our nCars PROVES the fleet cannot be reduced -- a valid dual fact.")
    print("A fleetLB below it proves nothing; this test simply could not rule the drop out.")
