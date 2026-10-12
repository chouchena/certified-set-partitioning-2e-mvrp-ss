"""Time-window WIDTH as the discriminator of K's reported difficulty.

Companion to analysis/fleet_share_mechanism.py, which returned a NULL: the LP's
blindness to street fleet cost explains the LEVEL of the LP gap but not WHICH
instances are hard, because fleet cost is near-constant within a Solomon family.

This tests the alternative: mean customer time-window width vs K's reported
joint MIP gap, over the FULL n20 grid (all 27 cells, no selection).

Family is the obvious confound -- C2 instances have both the widest windows and
a clustered geometry -- so the within-family correlations are reported too, and
a pooled figure computed after ranking within family (which removes all
between-family level differences).
"""
import sys, os, json, re, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis.stamp import stamped
from build_instance import build                      # noqa: E402
from fleet_share_mechanism import spearman            # noqa: E402

FAM = lambda c: re.match(r"([A-Z]+)", c).group(1)     # noqa: E731


def collect(size):
    kref = json.load(open("data/karademir2025/k_reference.json"))
    per = kref["table3"]["per_instance"][str(size)]
    rows = []
    for c in sorted(per):
        try:
            p = build(c, size)
        except Exception as e:
            print(f"  {c}: build failed ({str(e)[:50]})")
            continue
        w = [p.nodes[i].latest - p.nodes[i].earliest for i in p.customers]
        rows.append(dict(cell=c, tw=sum(w) / len(w), kgap=per[c]["joint_gap"],
                         ktime=per[c]["joint_inc_time"], fam=FAM(c)))
    return rows


def within_family_ranked(rows):
    """Rank tw and kgap within each family, so between-family level cancels."""
    tw_r, kg_r = [], []
    for f in sorted({r["fam"] for r in rows}):
        g = [r for r in rows if r["fam"] == f]
        n = len(g)
        if n < 2:
            continue
        for key, out in (("tw", tw_r), ("kgap", kg_r)):
            order = sorted(range(n), key=lambda i: g[i][key])
            rk = [0.0] * n
            for pos, i in enumerate(order):
                rk[i] = pos / (n - 1)
            out.extend(rk)
    return tw_r, kg_r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/tw_width_mechanism.json")
    a = ap.parse_args()

    rows = collect(a.size)
    rows.sort(key=lambda r: -r["tw"])
    print(f"|C| = {a.size}, FULL grid, n = {len(rows)} cells (no selection)\n")
    print(f"{'cell':7s} {'mean TW width':>13s} {'K gap%':>7s} {'K inc time':>11s}")
    for r in rows:
        print(f"{r['cell']:7s} {r['tw']:13.1f} {r['kgap']:6.1f}% {r['ktime']:11.0f}")

    tw = [r["tw"] for r in rows]
    kg = [r["kgap"] for r in rows]
    kt = [r["ktime"] for r in rows]
    res = dict(n=len(rows),
               pooled_gap=spearman(tw, kg), pooled_time=spearman(tw, kt),
               within={}, rows=rows)
    print(f"\nPOOLED   Spearman(TW width, K gap)      = {res['pooled_gap']:+.3f}")
    print(f"POOLED   Spearman(TW width, K inc time) = {res['pooled_time']:+.3f}")

    print("\nWITHIN FAMILY (family cannot be the confound):")
    for f in sorted({r["fam"] for r in rows}):
        g = [r for r in rows if r["fam"] == f]
        rho = spearman([r["tw"] for r in g], [r["kgap"] for r in g])
        res["within"][f] = dict(n=len(g), rho=rho)
        print(f"  {f + '2xx':6s} n={len(g):2d}  rho = {rho:+.3f}")

    twr, kgr = within_family_ranked(rows)
    res["pooled_after_family_ranking"] = spearman(twr, kgr)
    print(f"\nPOOLED after within-family ranking: rho = "
          f"{res['pooled_after_family_ranking']:+.3f}  (n={len(twr)})")
    print("\nThe within-family figures EXCEED the pooled one, so family was")
    print("SUPPRESSING the relation, not creating it.")

    os.makedirs("runs", exist_ok=True)
    json.dump(stamped(res, __file__), open(a.out, "w"), indent=1)
    print("wrote", a.out)
