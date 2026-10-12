"""THE headline table: our certified LB vs K's derived dual bound, at n20.

K's lower bound is not published directly; it is recoverable as BK x (1 - Gap%/100)
(register: k-lb-derivation, which reproduces their published gaps exactly at n20/n30).

The split below is the ONLY honest way to read the comparison:

  * On cells K PROVED, their "bound" IS the optimum. It cannot be beaten, and a ratio
    below 1 there is not a loss -- it is our distance to optimality. Pooling those cells
    into a win/loss count would understate the result AND misdescribe their work.
  * On cells K did NOT prove -- the cells where a bound is actually needed -- the
    comparison is meaningful.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def spearman(a, b):
    ra = {v: i for i, v in enumerate(sorted(a))}
    rb = {v: i for i, v in enumerate(sorted(b))}
    A = [ra[v] for v in a]; B = [rb[v] for v in b]
    ma, mb = sum(A) / len(A), sum(B) / len(B)
    num = sum((x - ma) * (y - mb) for x, y in zip(A, B))
    den = (sum((x - ma) ** 2 for x in A) * sum((y - mb) ** 2 for y in B)) ** 0.5
    return num / den


def main(size=20):
    kref = json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))
    per = kref["table3"]["per_instance"][str(size)]
    rows = []
    for c in sorted(per):
        f = os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{c}_n{size}.json")
        recs = [x for x in json.load(open(f)) if x["proven"]]
        if not recs:
            print(f"{c}: NO PROVEN RECORD -- excluded"); continue
        kf = min(x["k"] for x in recs)
        br = [x["block_relax"] for x in recs if x["k"] == kf][0]
        bk, g = per[c]["joint_bk"], per[c]["joint_gap"]
        klb = bk * (1 - g / 100.0)
        rows.append(dict(cell=c, k_bk=bk, k_gap=g, k_lb=klb, ours=br,
                         ratio=br / klb, pct_of_bk=br / bk, kf=kf))

    print(f"{'cell':7s} {'K_BK':>8s} {'gap%':>6s} {'K_LB':>9s} {'ours':>9s} {'ratio':>6s} {'k':>3s}")
    for r in rows:
        print(f"{r['cell']:7s} {r['k_bk']:8.1f} {r['k_gap']:6.1f} {r['k_lb']:9.2f} "
              f"{r['ours']:9.2f} {r['ratio']:6.3f} {r['kf']:3d}")

    prov = [r for r in rows if r["k_gap"] == 0.0]
    unpr = [r for r in rows if r["k_gap"] > 0.0]
    print(f"\nK-PROVEN ({len(prov)}): their bound IS the optimum; ours reaches "
          f"{100*min(r['pct_of_bk'] for r in prov):.1f}-{100*max(r['pct_of_bk'] for r in prov):.1f}% of it")
    w = sum(1 for r in unpr if r["ratio"] > 1)
    print(f"K-UNPROVEN ({len(unpr)}): we exceed K on {w}/{len(unpr)}; "
          f"mean ratio {sum(r['ratio'] for r in unpr)/len(unpr):.3f}; "
          f"losses {[(r['cell'], round(r['ratio'],3)) for r in unpr if r['ratio'] <= 1]}")
    print(f"Spearman(K gap%, our ratio) over unproven = "
          f"{spearman([r['k_gap'] for r in unpr], [r['ratio'] for r in unpr]):+.3f}")
    return rows


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
