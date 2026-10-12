"""MECHANISM TEST for the LP-anatomy finding.

The anatomy says the compact LP recovers 0% of FleetStreet on 4/4 cells -- i.e.
the relaxation is BLIND to street fleet cost -- while recovering FleetWater
exactly (K's water fleet floor is valid; the street analogue is not, because
cars reload).

PREDICTION, if that mechanism drives observed difficulty:
    K's reported MIP gap should be LARGER on cells where the fleet term is a
    LARGER share of the objective.

This is falsifiable and uses only existing data: K's per-cell joint_gap from
data/karademir2025/k_reference.json, and fleet share from our own
component-bearing incumbents.

A null result matters as much as a positive one: it would mean the FleetStreet
blindness, while real, is NOT what makes these instances hard for K -- and the
reformulation ranking in FINDING_LP_anatomy_and_reformulation_space sec 3 would
lose its mechanistic justification.
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.stamp import stamped
from lp_component_anatomy import harvest, COMPONENTS   # noqa: E402


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")

    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:                      # average ties
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return num / (dx * dy) if dx > 0 and dy > 0 else float("nan")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/fleet_share_mechanism.json")
    a = ap.parse_args()

    kref = json.load(open("data/karademir2025/k_reference.json"))
    per = kref["table3"]["per_instance"][str(a.size)]

    best = harvest(set(per), a.size)          # every cell we have components for
    rows = []
    for c, s in sorted(best.items()):
        k = per[c]
        fleet = s["FleetStreet"] + s["FleetWater"]
        rows.append(dict(cell=c, obj=s["objVal"],
                         fleet=fleet, fleet_share=fleet / s["objVal"] * 100,
                         street_share=s["FleetStreet"] / s["objVal"] * 100,
                         k_gap=k["joint_gap"], k_bk=k["joint_bk"],
                         src=s["_src"]))

    rows.sort(key=lambda r: -r["fleet_share"])
    print(f"n = {len(rows)} cells with component-bearing incumbents, |C| = {a.size}\n")
    print(f"{'cell':7s} {'our obj':>8s} {'fleet':>7s} {'fleet%':>7s} {'street%':>8s} {'K gap%':>7s}")
    for r in rows:
        print(f"{r['cell']:7s} {r['obj']:8.1f} {r['fleet']:7.1f} "
              f"{r['fleet_share']:6.1f}% {r['street_share']:7.1f}% {r['k_gap']:6.1f}%")

    fs = [r["fleet_share"] for r in rows]
    ss = [r["street_share"] for r in rows]
    kg = [r["k_gap"] for r in rows]
    r_fleet, r_street = spearman(fs, kg), spearman(ss, kg)
    print(f"\nSpearman(total fleet share,  K's gap) = {r_fleet:+.3f}")
    print(f"Spearman(STREET fleet share, K's gap) = {r_street:+.3f}")
    print("\nPREDICTION was a POSITIVE correlation (LP blind to fleet -> bigger gap")
    print("where fleet matters more).")
    verdict = ("SUPPORTED" if r_street > 0.3 else
               "CONTRADICTED" if r_street < -0.3 else "NULL -- no relation")
    print(f"VERDICT: {verdict}")

    os.makedirs("runs", exist_ok=True)
    json.dump(stamped(dict(rows=rows, spearman_fleet=r_fleet, spearman_street=r_street,
                   n=len(rows), verdict=verdict), __file__), open(a.out, "w"), indent=1)
    print("wrote", a.out)
