"""The three pre-tests method B required before any trip-based primal was built, applied to TEP
(d417; validation/DESIGN_B_trip_based_primal.md A1.1, A2.1, A2.2). Each is cheap and each catches
a class of defect that a price-and-branch run would otherwise hit after an hour of solving.

T1  COST RECONSTRUCTION -- decompose a verified solution into trips (path_cover_fleet.trips_of,
    the validated decomposer with the hub-pairing trap documented) and rebuild the street part
    from the trips alone: car penalty x chains + travel over depot->first, intra, last->hub,
    hub->next first, last hub->depot. Must equal the artifact's FleetStreet + TravelStreet.
    Catches: a wrong cost model, wrong hub pairing, a mis-split chain.

T2  ROUND-TRIP EMISSION -- feed that same decomposition back through the emitter
    (assemble_precluster.decode) and the exact re-timing, then verifier3. Must produce a verified
    solution no worse than the original (the timetable is re-optimised, so it may be better).
    Catches: an emitter that cannot express what the model produces -- the d412/d414 decoder bug.

T2b PERTURBED EMISSION (A2.2) -- swap the hubs of two trips that the time test alone would accept
    and emit again. Must either verify or be rejected by the re-timing, never pass the emitter and
    fail the verifier, which is what "the compatibility test checks time only" means in practice.

    python analysis/tep_pretests.py RC204 [R204 ...] [--size 100] [--cap 240]
"""
import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from analysis.path_cover_fleet import trips_of
from assemble_precluster import decode, retime
from k_comparison import k_proximity


def best_artifact(cell, size):
    """The cheapest verified banked solution of the cell, with its street split."""
    best = None
    for pat in ("runs/postpass/assembled_%s_n%d_*.json", "runs/trial_C2/C2_%s.json",
                "runs/grid/g_%s_n%d_p*_s0.json", "runs/trial_F7/*%s*.json", "runs/trial_F5/*%s*.json"):
        for f in glob.glob(os.path.join(ROOT, pat % ((cell, size) if pat.count("%") == 2 else (cell,)))):
            try:
                d = json.load(io.open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict) or d.get("FleetStreet") is None or d.get("objVal") is None:
                continue
            # d434: the size test rejected every runs/trial_C2 artifact -- they carry no `size`
            # field and no "n100" in the filename -- so the C2 polish results were invisible and
            # C-cell baselines were reported against older assembly artifacts (the C204 figure of
            # -5.66% should have been -5.53%). A pattern that can only hold one size counts as
            # that size.
            fixed_size = 100 if ("trial_C2" in f.replace("\\", "/")) else None
            got = d.get("size") or fixed_size or (size if ("n%d" % size) in os.path.basename(f) else None)
            if got != size:
                continue
            if best is None or d["objVal"] < best[1]["objVal"]:
                best = (os.path.relpath(f, ROOT).replace("\\", "/"), d)
    return best


def street_from_trips(inst, trips, chains):
    """Rebuild the street travel of a decomposition, chain by chain, exactly as verifier3 charges
    it (leg_objective): a transfer at i with hub p costs D[i][p] + D[p][next], and the chain's
    LAST trip returns from its hub to the depot -- D[last][p] + D[p][g]. The first draft of this
    test omitted that return leg and reported 1904.64 against the verifier's 2058.73 on RC204,
    5 chains x ~30.8: the test was wrong, not the model (d418)."""
    D, g = inst.D, inst.depot
    tot = 0.0
    for ch in chains:
        prev_hub = None
        for i in ch:
            seq, hub = trips[i]
            tot += D[prev_hub if prev_hub is not None else g][seq[0]]
            tot += sum(D[x][y] for x, y in zip(seq, seq[1:]))
            tot += D[seq[-1]][hub] if hub is not None else 0.0
            prev_hub = hub
        seq, hub = trips[ch[-1]]
        tot += D[hub][g] if hub is not None else D[seq[-1]][g]        # (4): the last trip transfers
    return tot


def chains_of(sol, trips):
    """Group the decomposition back into vehicle chains, in the order the arcs give."""
    succ = {}
    for a, b in sol["xij"]:
        succ.setdefault(a, []).append(b)
    idx = {}
    for i, (seq, hub) in enumerate(trips):
        idx.setdefault(seq[0], []).append(i)
    chains = []
    for s in list(succ.get(0, [])):
        cur, chain = s, []
        while cur != 0 and len(chain) < 200:
            cand = idx.get(cur)
            if not cand:
                break
            i = cand.pop(0); chain.append(i)
            seq = trips[i][0]; cur = seq[-1]
            nxt = succ.get(cur)
            if not nxt:
                break
            cur = nxt[0]
        if chain:
            chains.append(chain)
    return chains


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="+"); ap.add_argument("--size", type=int, default=100); ap.add_argument("--cap", type=float, default=240.0)
    a = ap.parse_args()
    out = {}
    for cell in a.cells:
        prox = k_proximity(a.size)
        inst = V.load_instance(cell, a.size, prox)
        got = best_artifact(cell, a.size)
        if not got:
            print("%-6s no verified banked artifact with a street split" % cell); continue
        path, sol = got
        trips = trips_of(sol)
        chains = chains_of(sol, trips)
        flat = [i for ch in chains for i in ch]
        covered = sorted(c for i in flat for c in trips[i][0])
        # ---- T1 cost reconstruction
        street = street_from_trips(inst, trips, chains)
        claimed = float(sol["TravelStreet"]); pen = float(inst.penalty_cars)
        t1 = abs(street - claimed) < 1e-3 and abs(pen * len(chains) - float(sol["FleetStreet"])) < 1e-3
        print("%-6s T1 cost reconstruction: trips %d, chains %d, customers %d/%d | travel %.2f vs %.2f | fleet %.2f vs %.2f -> %s"
              % (cell, len(trips), len(chains), len(set(covered)), len(inst.customers), street, claimed,
                 pen * len(chains), float(sol["FleetStreet"]), "PASS" if t1 else "FAIL"))
        # ---- T2 round-trip emission
        cand = decode([t[0] for t in trips], {"chains": chains, "hub": {i: trips[i][1] for i in range(len(trips))}}, depot=inst.depot)
        res, status, secs = retime(cell, cand, cap=a.cap)
        if res is None:
            print("%-6s T2 round-trip emission: re-timing %s in %.0f s -> FAIL (a verified solution must re-time)" % (cell, status, secs))
            t2 = False; obj = None
        else:
            run = V.verify_solution(inst, res, cell=cell, size=a.size, proximity=prox, label="pretest_T2")
            bad = [x for x in run.findings if x.severity != "TOLERANCE"]
            ok = (not bad) and (not run.blocking)
            obj = res["objVal"]; t2 = ok and obj <= float(sol["objVal"]) + 1e-6
            print("%-6s T2 round-trip emission: %s in %.0f s -> obj %.1f vs original %.1f, verifier3 %s -> %s"
                  % (cell, status, secs, obj, float(sol["objVal"]), "PASS" if ok else "FAIL", "PASS" if t2 else "FAIL"))
        out[cell] = dict(artifact=path, trips=len(trips), chains=len(chains), t1=t1, t2=t2, t2_obj=obj, original=float(sol["objVal"]))
    json.dump(out, io.open(os.path.join(ROOT, "runs", "oracle", "tep_pretests.json"), "w", encoding="utf-8"), indent=1)
    print("\nwrote runs/oracle/tep_pretests.json")


if __name__ == "__main__":
    main()
