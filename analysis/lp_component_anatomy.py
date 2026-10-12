"""Component-level anatomy of the LP gap, for ALL probed cells.

Closes the n=1 evidence gap in FINDING_LP_anatomy_and_reformulation_space.md
sec 2: the `nofCars = 0` observation held on 4/4 cells, but the quantitative
split (FleetStreet = 55.4% of the LP gap) rested on C202 alone, because it was
the only cell with a stored component-level incumbent in runs/solutions/.

results/portfolio/*.sol.json carries the same schema, so the remaining cells
are recoverable at ZERO runtime cost -- no re-solve.

Guards:
  * components must sum to objVal (1e-3) or the record is rejected
  * the harvested best is compared against the known incumbent; if it is worse
    the row is flagged, because the split would then describe a DIFFERENT
    (sub-optimal) solution and must not be reported as the incumbent's anatomy
"""
import sys, os, json, glob, re, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.stamp import stamped

# best known incumbents (see FINDING_LP_relaxation_is_the_bottleneck sec 1)
INCUMBENT = {"C202": 678.7, "C203": 673.7, "R204": 582.8, "RC202": 900.6}
COMPONENTS = ["FleetStreet", "TravelStreet", "TravelWater", "FleetWater"]

STORES = [
    ("runs/solutions",     r"fixopt_([A-Za-z0-9]+)_n(\d+)_"),
    ("results/portfolio",  r"([A-Za-z0-9]+)_n(\d+)_"),
]


def harvest(cells, size):
    """Best component-bearing solution per cell, across both stores."""
    best = {}
    for root, pat in STORES:
        for f in glob.glob(os.path.join(root, "*.json")):
            m = re.match(pat, os.path.basename(f))
            if not m:
                continue
            cell, sz = m.group(1), int(m.group(2))
            if cell not in cells or sz != size:
                continue
            try:
                d = json.load(open(f))
            except Exception:
                continue
            if not all(k in d for k in COMPONENTS + ["objVal"]):
                continue
            o = d["objVal"]
            if o is None:
                continue
            # guard: components must reconstruct the objective
            if abs(sum(d[k] for k in COMPONENTS) - o) > 1e-3:
                continue
            if cell not in best or o < best[cell]["objVal"]:
                d["_src"] = os.path.relpath(f)
                best[cell] = d
    return best


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/lp_component_anatomy.json")
    a = ap.parse_args()

    lp = {r["cell"]: r for r in json.load(open("runs/lp_anatomy.json"))}
    cells = set(lp)
    best = harvest(cells, a.size)

    rows, agg = [], {k: [0.0, 0.0] for k in COMPONENTS}   # [missed, gap]
    for c in sorted(cells):
        if c not in best:
            print(f"{c}: NO component-bearing solution found"); continue
        s, L = best[c], lp[c]
        inc, known = s["objVal"], INCUMBENT.get(c)
        flag = ""
        if known is not None and inc > known + 0.05:   # INCUMBENT is stored to 1 dp
            flag = f"  [!] harvested {inc:.1f} is WORSE than known incumbent {known:.1f}"
        gap = inc - L["lp"]
        print(f"\n=== {c}   LP {L['lp']:.1f} -> incumbent {inc:.1f}   (gap {gap:.1f}){flag}")
        print(f"    src: {s['_src']}")
        print(f"    {'component':14s} {'LP':>8s} {'incumb':>8s} {'recovers':>9s} {'% of gap':>9s}")
        row = dict(cell=c, lp=L["lp"], incumbent=inc, gap=gap,
                   src=s["_src"], worse_than_known=bool(flag))
        for k in COMPONENTS:
            lo, hi = L[k], s[k]
            rec = (lo / hi * 100) if abs(hi) > 1e-9 else float("nan")
            sh = (hi - lo) / gap * 100 if gap > 1e-9 else float("nan")
            agg[k][0] += hi - lo
            agg[k][1] += gap
            row[k] = dict(lp=lo, incumbent=hi, recovers_pct=rec, share_of_gap_pct=sh)
            print(f"    {k:14s} {lo:8.1f} {hi:8.1f} {rec:8.0f}% {sh:8.1f}%")
        rows.append(row)

    if rows:
        print(f"\n=== POOLED over {len(rows)} cells: share of total LP gap by component")
        tot = sum(r["gap"] for r in rows)
        for k in COMPONENTS:
            print(f"    {k:14s} {agg[k][0] / tot * 100:6.1f}%")
        os.makedirs("runs", exist_ok=True)
        json.dump(stamped(rows, __file__), open(a.out, "w"), indent=1)
        print("\nwrote", a.out)
