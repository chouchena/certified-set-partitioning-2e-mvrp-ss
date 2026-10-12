"""restrict_to_H_check.py -- S1c: tighter bound-validity check (zero solver).

The incumbent restricted to H is a block-A-FEASIBLE solution over H, so its street cost must be
>= z_A(H)* (=440.96 for R207 n20 k=6, drop {1,2,6,7,17,20}). If street(inc|H) < z_A(H)*, then
z_A(H)* is not the true minimum -> the solver returned a wrong (too-high) bound -> BUG.
Route surgery only (splice dropped customers out of the incumbent's route); nCars=1 so fleet is
unchanged. Cost model auto-detected against the incumbent's stored TravelStreet.
"""
import glob, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys; sys.path.insert(0, ROOT)
from build_instance import build

CELL, SIZE, K, DROP, ZA_H = "R207", 20, 6, {1, 2, 6, 7, 17, 20}, 440.96


def main():
    p = build(CELL, SIZE, wls=0.1, tau="formula", proximity=0.0)
    D = p.DistMatrix
    tc = getattr(p, "travelcoststreet", 1.0)
    sol = json.load(open(sorted(glob.glob(os.path.join(ROOT, "results", "portfolio", f"{CELL}_n{SIZE}*.sol.json")))[0]))
    xij = [tuple(a) for a in sol["xij"]]
    fleet = sol["FleetStreet"]; travel_full = sol["TravelStreet"]; nCars = sol["nCars"]

    # auto-detect cost model: arc cost = D[i][j]*tc  vs  D[i][j]
    s_tc = sum(D[i][j] * tc for i, j in xij)
    s_raw = sum(D[i][j] for i, j in xij)
    if abs(s_tc - travel_full) <= abs(s_raw - travel_full):
        cost = lambda i, j: D[i][j] * tc; model = f"D*tc (tc={tc})"
    else:
        cost = lambda i, j: D[i][j]; model = "D (raw)"
    print(f"cost model = {model}; recomputed full travel {min(s_tc,s_raw):.2f}/{max(s_tc,s_raw):.2f} vs stored {travel_full:.2f}")

    # reconstruct route(s): follow succ from depot 0
    succ = {}
    for i, j in xij:
        succ.setdefault(i, []).append(j)
    # single tour from 0 (nCars=1). Walk until back to 0.
    seq, cur, seen = [0], 0, set()
    while True:
        nxts = succ.get(cur, [])
        nxt = next((n for n in nxts if n not in seen), None)
        if nxt is None or nxt == 0:
            seq.append(0); break
        seq.append(nxt); seen.add(nxt); cur = nxt
        if len(seq) > 3 * (SIZE + 5):
            break
    visited = [c for c in seq if c != 0]
    print(f"route: {len(visited)} street stops, nCars={nCars}; drop set (H^c) = {sorted(DROP)}")

    # splice: remove dropped customers, recompute travel along reduced sequence
    reduced = [c for c in seq if c == 0 or c not in DROP]
    travel_H = sum(cost(reduced[t], reduced[t + 1]) for t in range(len(reduced) - 1))
    street_H = fleet + travel_H

    print(f"\nfull incumbent street = {fleet:.2f} (fleet) + {travel_full:.2f} (travel) = {fleet+travel_full:.2f}")
    print(f"restricted-to-H street = {fleet:.2f} (fleet, nCars=1 unchanged) + {travel_H:.2f} (travel) = {street_H:.2f}")
    print(f"z_A(H)* (block-A optimum over H, k={K}) = {ZA_H}")
    ok = street_H >= ZA_H - 1e-6
    print(f"\nCHECK  street(inc|H)={street_H:.2f}  >=  z_A(H)*={ZA_H}   ->  {'PASS' if ok else 'FAIL (bound too high = BUG)'}"
          f"   margin {street_H-ZA_H:+.2f}")


if __name__ == "__main__":
    main()
