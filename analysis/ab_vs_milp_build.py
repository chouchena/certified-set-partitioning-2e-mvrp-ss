"""
Rebuild the AB-vs-MILP crossover as a DERIVED VIEW over two provenanced sources.

Refactor finding A1 (2026-09-12): `runs/ab_vs_milp.json` (67 records) had no provenance and no
producer. Unlike the grid and the WLS sweep it is not a primary measurement -- every field is a
join of two things we already hold stamped:

    ab1 / ab3 / ab4  <- runs/ab_grid_provenanced.json   (ab_code_hash)
    milp             <- crossfeed/easy_reduction_descend_<cell>_n<size>.json  (code_hash, git_sha)

So the right fix is not to re-measure it but to stop treating it as an artifact. This script
regenerates it from the two sources and records BOTH their provenance stamps, so the crossover
can always be re-derived and never drifts from its inputs.

    --verify   diff against the stored runs/ab_vs_milp.json
    (default)  also write runs/ab_vs_milp_derived.json

NOTE on `milp`: the descend bound is `max_k block_relax` over all records of a cell -- a
truncated dual bound is still a valid LB. This mirrors `lb_monitor.our_bound()`; if that
definition ever changes, this script must change with it.
"""
import os, sys, json, glob, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped


def milp_bound(cell, size):
    """max_k block_relax over ALL records -- same rule as lb_monitor.our_bound()."""
    fs = (glob.glob(os.path.join(ROOT, "crossfeed",
                                 f"easy_reduction_descend_{cell}_n{size}.json"))
          or glob.glob(os.path.join(ROOT, "crossfeed", f"easy_reduction_{cell}_n{size}.json")))
    best, prov = None, None
    for f in fs:
        try:
            recs = json.load(open(f))
        except Exception:
            continue
        for r in (recs if isinstance(recs, list) else [recs]):
            v = r.get("block_relax")
            if isinstance(v, (int, float)) and (best is None or v > best):
                best = v
                prov = {"code_hash": r.get("code_hash"), "git_sha": r.get("git_sha"),
                        "seed": r.get("seed"), "det_tl": r.get("det_tl")}
    return best, prov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    gp = os.path.join(ROOT, "runs", "ab_grid_provenanced.json")
    if not os.path.exists(gp):
        print("runs/ab_grid_provenanced.json missing -- run analysis/ab_grid_build.py first")
        return 1
    grid = json.load(open(gp))
    ab = {(r["cell"], r["size"]): r for r in grid["records"]}

    old = json.load(open(os.path.join(ROOT, "runs", "ab_vs_milp.json")))
    old = old if isinstance(old, list) else list(old.values())
    oldmap = {(r["cell"], r["size"]): r for r in old}

    # Build the FULL grid, not just whatever the stale file happened to cover. The stored
    # ab_vs_milp.json holds 17/26/24 of 27 cells at n20/n30/n100 and NOTHING at n50; mirroring
    # its keys reproduced that gap and silently omitted the entire n50 size. Coverage and
    # staleness are different defects (join_freshness.py checks both).
    CELLS = ([f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
             + [f"RC2{i:02d}" for i in range(1, 9)])
    targets = sorted({(c, s) for s in (20, 30, 50, 100) for c in CELLS}
                     | set(oldmap.keys()))

    recs, diffs, missing = [], [], []
    for (cell, size) in targets:
        o = oldmap.get((cell, size))
        g = ab.get((cell, size))
        m, mprov = milp_bound(cell, size)
        if g is None or m is None:
            missing.append((cell, size))
            continue
        r = {"cell": cell, "size": size, "milp": round(m, 2),
             "ab4": round(g["ab4_full"], 2) if "ab4_full" in g else g["ab4"],
             "ratio": round((g.get("ab4_full", g["ab4"])) / m, 4) if m else None,
             "milp_provenance": mprov}
        recs.append(r)
        if o is None:
            continue                       # new coverage, nothing stored to compare against
        for fld in ("milp", "ab4"):
            if abs(r[fld] - o[fld]) > 0.011:      # both stored at 2 dp
                diffs.append((cell, size, fld, o[fld], r[fld]))
                print(f"  MISMATCH {cell} n{size} {fld}: stored={o[fld]} rebuilt={r[fld]}")

    print(f"\n{'=' * 70}")
    import collections
    by = collections.Counter(r["size"] for r in recs)
    print(f"rebuilt {len(recs)} records ({dict(sorted(by.items()))}) | "
          f"stored file had {len(oldmap)} | MISMATCHES vs stored {len(diffs)}")
    if missing:
        print(f"could not rebuild {len(missing)}: {missing[:6]}")
    if not diffs and recs:
        print("\nEXACT MATCH at stored precision. The crossover is a DERIVED VIEW over")
        print("runs/ab_grid_provenanced.json + the stamped descend artifacts, and carries")
        print("both provenance chains. It is no longer a primary artifact.")

    if not a.verify:
        out = {"derived_from": {"ab": grid["provenance"],
                                "milp": "per-record milp_provenance below"},
               "records": recs}
        json.dump(stamped(out, __file__), open(os.path.join(ROOT, "runs", "ab_vs_milp_derived.json"), "w"), indent=1)
        print("-> runs/ab_vs_milp_derived.json")
    return 2 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
