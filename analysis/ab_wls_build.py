"""
Provenanced rebuild of the AB WLS sweep -- and a fidelity test of the existing one.

Companion to `analysis/ab_grid_build.py`. Refactor finding A1 (2026-09-12) established that
`runs/ab_wls_sweep.json` (540 records, the source of the WLS finding and STORY_ARC Beat 8)
carries NO provenance AND has NO producer left in the repo. The grid arm of A1 was closed by
recomputation -- 162/162 exact. This closes the WLS arm the same way.

    --verify   recompute and diff against the stored sweep
    (default)  also write runs/ab_wls_provenanced.json WITH provenance

540 records = 27 cells x 5 sizes {10,20,30,50,100} x 4 WLS {1:10, 1:5, 1:1, 10:1}.
Proximity follows the grid convention: 0.1 at |C|=100 (K Table 6), 0.0 elsewhere.

The original artifact is evidence and is NOT overwritten.
"""
import os, sys, json, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

from build_instance import build
from crossfeed.fullset_bound import fullset_bound
from ab_grid_build import provenance, CELLS

SIZES = [10, 20, 30, 50, 100]
WLS = [("1:10", 0.1), ("1:5", 0.2), ("1:1", 1.0), ("10:1", 10.0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--sizes", default="10,20,30,50,100")
    a = ap.parse_args()
    sizes = [int(x) for x in a.sizes.split(",")]

    old = json.load(open(os.path.join(ROOT, "runs", "ab_wls_sweep.json")))
    recs, diffs, checked = [], [], 0
    for size in sizes:
        prox = 0.1 if size == 100 else 0.0
        for cell in CELLS:
            for tag, wrs in WLS:
                p = build(cell, size, wls=wrs, tau="formula", proximity=prox, time_limit=60)
                b, parts = fullset_bound(p)
                r = {"cell": cell, "size": size, "wls": tag, "wrs": wrs,
                     "ab4": round(b, 3), "ab4_full": b, "V_LB": parts["V_LB"],
                     "penCars": p.penaltyCars, "water": parts["water"],
                     "travel": parts["dist_raw"], "fleet": parts["fleet_term"]}
                recs.append(r)
                o = old.get(f"{cell}|{size}|{tag}")
                if o is not None:
                    checked += 1
                    # stored at 3 dp; round from FULL precision, never from a rounded field
                    if abs(round(b, 3) - o["ab4"]) > 1e-9:
                        diffs.append((f"{cell}|{size}|{tag}", o["ab4"], round(b, 3)))
                        print(f"  MISMATCH {cell}|{size}|{tag}: stored={o['ab4']} "
                              f"recomputed={round(b, 3)}", flush=True)
        print(f"  n{size}: {len(CELLS) * len(WLS)} records", flush=True)

    print(f"\n{'=' * 70}\nrecords {len(recs)}   compared {checked}   MISMATCHES {len(diffs)}")
    if diffs:
        print("\n*** The stored WLS sweep was NOT produced by the current fullset_bound.")
    elif checked:
        print("\nEXACT MATCH at stored precision. The WLS sweep is retroactively validated.")

    if not a.verify:
        out = {"provenance": provenance(), "records": recs}
        json.dump(stamped(out, __file__), open(os.path.join(ROOT, "runs", "ab_wls_provenanced.json"), "w"), indent=1)
        print(f"-> runs/ab_wls_provenanced.json  "
              f"ab_code_hash={out['provenance']['ab_code_hash']}")
    return 2 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
