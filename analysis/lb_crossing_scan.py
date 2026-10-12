"""lb_crossing_scan.py -- CHEAP, no-solver disk scan (R10 cheap-before-expensive).

Answers, from data ALREADY on disk, the user's RT-to-beat-K assumption at COARSE
granularity: does our proven dual bound exceed Karademir's LB *early* (small cumulative
wall) rather than only at our final RT?

For each easy_reduction*_n<size>.json descend/sweep file it reads the per-k records
(block_relax, wall, proven), then under the SEQUENTIAL-DESCEND model (k solved high->low,
walls cumulative) reports:
  - t_first_cross : cumulative wall at the first PROVEN k whose bound > K_bound
  - bound_first   : that first crossing bound
  - t_best        : cumulative wall to the best (max) proven bound
  - bound_best    : the best proven bound (== the cited proven LB)
K_bound is Karademir's PAPER LB (their hardware) from easy_reduction_consolidated.md
-- a PLACEHOLDER denominator; the same-machine reproduced-LBBD bound is a re-run (design doc).

Caveat (R2): walls are single-run, 8-core dev, non-deterministic; this is a coarse
YES/NO screen, NOT the referee metric. It does not prove the crossing, it scopes it.
"""
import glob, json, os, re
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Karademir PAPER LB (their hardware) from validation/easy_reduction_consolidated.md, table §1.
# PLACEHOLDER denominator -- flagged: same-machine reproduced-LBBD bound is pending (re-run).
K_PAPER_LB = {
    "C203": 314.0, "RC202": 507.6, "R203": 402.2, "RC204": 321.2, "RC203": 331.9,
    "R204": 351.3, "R211": 347.9, "R208": 346.4, "R207": 385.1, "C204": 293.9, "RC208": 308.6,
}


def cell_of(fp):
    m = re.search(r"easy_reduction(?:_descend)?_([A-Z]+\d+)_n(\d+)\.json$", os.path.basename(fp))
    return (m.group(1), int(m.group(2))) if m else (None, None)


def scan_file(fp):
    try:
        recs = json.load(open(fp, encoding="utf-8"))
    except Exception as e:
        return None
    if not isinstance(recs, list):
        recs = [recs]
    # sort by k DESCENDING = descend order (cheapest/most-drops first)
    recs = [r for r in recs if isinstance(r, dict) and "k" in r and "block_relax" in r]
    recs.sort(key=lambda r: -int(r["k"]))
    cum = 0.0
    first = None
    best = None
    cum_at_best = None
    cell, size = cell_of(fp)
    kb = K_PAPER_LB.get(cell)
    for r in recs:
        cum += float(r.get("wall", 0.0))
        if not r.get("proven"):
            continue
        b = float(r["block_relax"])
        if best is None or b > best[0]:
            best = (b, int(r["k"]), r.get("wall"))
            cum_at_best = cum
        if first is None and kb is not None and b > kb:
            first = (b, int(r["k"]), cum)
    return {"cell": cell, "size": size, "file": os.path.basename(fp), "K_paper_LB": kb,
            "bound_first": first[0] if first else None,
            "k_first": first[1] if first else None,
            "t_first_cross_s": round(first[2], 1) if first else None,
            "bound_best": best[0] if best else None,
            "k_best": best[1] if best else None,
            "t_best_s": round(cum_at_best, 1) if cum_at_best is not None else None}


def main():
    rows = []
    seen = {}
    for fp in glob.glob(os.path.join(ROOT, "crossfeed", "easy_reduction*_n*.json")):
        r = scan_file(fp)
        if not r or not r["cell"]:
            continue
        # prefer descend file (more k's) when a cell has both
        key = (r["cell"], r["size"])
        if key in seen and "descend" not in r["file"]:
            continue
        seen[key] = r
    rows = sorted(seen.values(), key=lambda d: (d["t_first_cross_s"] is None, d["t_first_cross_s"] or 1e9))
    hdr = f"{'cell':6} {'K_LB':>7} {'1st>K':>7} {'@k':>3} {'t_1st':>7} {'best':>8} {'@k':>3} {'t_best':>7}"
    print(hdr); print("-" * len(hdr))
    n_cross = 0
    for d in rows:
        if d["bound_first"] is not None:
            n_cross += 1
        print(f"{d['cell']:6} {str(d['K_paper_LB']):>7} "
              f"{('%.1f'%d['bound_first']) if d['bound_first'] else '-':>7} "
              f"{str(d['k_first'] or '-'):>3} "
              f"{('%.1f'%d['t_first_cross_s']) if d['t_first_cross_s'] is not None else '-':>7} "
              f"{('%.1f'%d['bound_best']) if d['bound_best'] else '-':>8} "
              f"{str(d['k_best'] or '-'):>3} "
              f"{('%.1f'%d['t_best_s']) if d['t_best_s'] is not None else '-':>7}")
    print(f"\n{n_cross}/{len(rows)} cells: first proven bound > K's PAPER LB (coarse, non-deterministic 8-core wall).")
    json.dump(stamped(rows, __file__), open(os.path.join(ROOT, "validation", "lb_crossing_coarse.json"), "w"), indent=2)
    print("wrote validation/lb_crossing_coarse.json")


if __name__ == "__main__":
    main()
