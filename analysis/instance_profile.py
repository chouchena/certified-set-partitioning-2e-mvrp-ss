"""Instance-level covariate profile, and which cells are extremal on each.

WHY. Tail points in our results get noticed one at a time and then explained ad hoc, which is how
a coincidence becomes a story. This profiles every cell on the covariates we have actually measured
as mattering, so a cell appearing at a tail can be checked against its position in the grid instead
of being narrated.

The covariate that matters is TW WIDTH RELATIVE TO THE HORIZON. `tw-width-drives-k-difficulty`
measures Spearman(mean TW width, K's reported gap) at +0.913 / +0.868 / +0.881 within the C / R / RC
families. Wide windows admit many feasible orderings, so proving is hard; they also reduce forced
travel and fleet, so the optimum is cheap. Both tails of one mechanism.

Usage:  python analysis/instance_profile.py [--size 20] [--cell R208]
"""
import sys, os, json, argparse, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from build_instance import build                                   # noqa: E402


def profile(size):
    kref = json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))
    per = kref["table3"]["per_instance"][str(size)]
    rows = []
    for c in sorted(per):
        p = build(c, size, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
        nd, C = p.nodes, list(p.customers)
        hz = nd[0].latest - nd[0].earliest
        tw = st.mean(nd[i].latest - nd[i].earliest for i in C)
        rec = dict(cell=c, bk=per[c]["joint_bk"], gap=per[c]["joint_gap"],
                   tw=tw, tw_ratio=tw / hz, horizon=hz,
                   demand=sum(nd[i].demand for i in C),
                   service=st.mean(nd[i].serviceTime for i in C))
        f = os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{c}_n{size}.json")
        if os.path.exists(f):
            recs = [x for x in json.load(open(f)) if x.get("proven")]
            if recs:
                kf = min(x["k"] for x in recs)
                rec["frontier_k"] = kf
                rec["block_relax"] = [x["block_relax"] for x in recs if x["k"] == kf][0]
        rows.append(rec)
    return rows


def main(size, focus):
    rows = profile(size)
    keys = ["bk", "gap", "tw", "tw_ratio", "horizon", "demand", "service", "frontier_k"]

    print(f"n{size}: {len(rows)} cells\n")
    print(f"{'cell':7s} " + "".join(f"{k:>11s}" for k in keys))
    for r in sorted(rows, key=lambda r: -r.get("tw_ratio", 0)):
        print(f"{r['cell']:7s} " + "".join(
            f"{r.get(k, float('nan')):11.3f}" if isinstance(r.get(k), (int, float)) else f"{'-':>11s}"
            for k in keys))

    print("\nEXTREMAL cells per covariate (min | max):")
    for k in keys:
        have = [r for r in rows if isinstance(r.get(k), (int, float))]
        if not have:
            continue
        lo = min(have, key=lambda r: r[k]); hi = max(have, key=lambda r: r[k])
        print(f"  {k:11s} min {lo['cell']:7s} {lo[k]:9.3f}   max {hi['cell']:7s} {hi[k]:9.3f}")

    if focus:
        f = [r for r in rows if r["cell"] == focus]
        if not f:
            print(f"\n{focus} not found"); return
        f = f[0]
        print(f"\n{focus} rank among {len(rows)} cells (1 = lowest):")
        for k in keys:
            have = [r for r in rows if isinstance(r.get(k), (int, float))]
            if not isinstance(f.get(k), (int, float)):
                continue
            rank = sorted(have, key=lambda r: r[k]).index(f) + 1
            flag = "  <== EXTREMAL" if rank in (1, len(have)) else ""
            print(f"  {k:11s} {f[k]:10.3f}   rank {rank:2d}/{len(have)}{flag}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--cell", default="R208")
    a = ap.parse_args()
    main(a.size, a.cell)
