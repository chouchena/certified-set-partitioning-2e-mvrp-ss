"""Does the primal margin over K hold at |C| = 30?

Tests the hypothesis "maybe ours is better on higher |C|". K's own gap grows
(26.2% at n20 -> 43.0% at n30), so their incumbents should be further from
optimal and there should be MORE room, not less.

[[RISK_margin_decay_with_size]] says the opposite but rests on 6 of 26 cells at
MIXED budgets. This recomputes from the trajectory files with the two corrections
this project has already had to make twice:

  * comparator = min(joint_bk, lbbd_bk)  -- K's BETTER method
    (AUDIT_comparator_asymmetry; at n30 LBBD is better on nearly every cell, so
     using joint_bk alone flatters us badly here)
  * variant pooling forbidden -- baseline tag only, no captl/k3/xsat mixed in

It reports the BUDGET SPREAD per cell, because a mixed-budget comparison is not
like-for-like and must not be presented as one.
"""
import sys, os, json, glob, re, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.stamp import stamped

DEADBAND = 0.05


def final_best(path):
    """(best_incumbent, wall_s, verified) from a trajectory's last useful row."""
    best = wall = None
    ver = True
    for ln in open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        b = d.get("best_incumbent")
        if b is not None:
            best = b
            wall = d.get("wall_s")
        ex = d.get("extra") or {}
        if ex.get("run_valid") is False or ex.get("reject") is True:
            ver = False
    return best, wall, ver


def collect(size, variant):
    pat = re.compile(rf"fixopt_([A-Za-z0-9]+)_n{size}_s(\d+)_(.+?)_(\d{{10}})\.jsonl$")
    out = {}
    for f in sorted(glob.glob(f"runs/fixopt_*_n{size}_*.jsonl")):
        m = pat.match(os.path.basename(f))
        if not m:
            continue
        cell, seed, tag = m.group(1), int(m.group(2)), m.group(3)
        if variant and not tag.endswith(variant):
            continue
        b, w, ok = final_best(f)
        if b is None or not ok:
            continue
        out.setdefault(cell, []).append((seed, b, w))
    return out


def median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--variant", default="baseline",
                    help="tag suffix to keep; '' pools every variant (NOT recommended)")
    a = ap.parse_args()

    kref = json.load(open("data/karademir2025/k_reference.json"))
    per = kref["table3"]["per_instance"][str(a.size)]
    data = collect(a.size, a.variant)

    print(f"|C| = {a.size}, variant filter = '{a.variant or 'NONE (pooled!)'}'")
    print(f"{len(data)} of {len(per)} cells have usable runs\n")
    print(f"{'cell':7s} {'runs':>4s} {'budget spread (s)':>19s} {'K best':>8s} "
          f"{'our best':>9s} {'best %':>8s} {'our med':>9s} {'med %':>8s} {'Kgap':>5s}")

    wb = wm = 0
    rows = []
    for c in sorted(data):
        v = data[c]
        obs = [x[1] for x in v]
        ws = [x[2] for x in v if x[2]]
        j, l = per[c]["joint_bk"], per[c]["lbbd_bk"]
        kb = min(j, l)
        bst, med = min(obs), median(obs)
        mb, mm = (bst - kb) / kb * 100, (med - kb) / kb * 100
        if bst < kb - DEADBAND:
            wb += 1
        if med < kb - DEADBAND:
            wm += 1
        sp = f"{min(ws):.0f}-{max(ws):.0f}" if ws else "?"
        rows.append(dict(cell=c, n=len(v), k_best=kb, best=bst, median=med,
                         best_pct=mb, med_pct=mm, budgets=sp,
                         k_gap=per[c]["joint_gap"]))
        print(f"{c:7s} {len(v):4d} {sp:>19s} {kb:8.1f} {bst:9.1f} {mb:+7.2f}% "
              f"{med:9.1f} {mm:+7.2f}% {per[c]['joint_gap']:4.0f}%")

    print(f"\nbest-of beats K's better method on {wb}/{len(rows)} cells; "
          f"median on {wm}/{len(rows)}")
    print("\nCAVEATS that block any headline from this table:")
    print("  * cells with runs are a SUBSET chosen by history, not by design")
    print("  * budgets differ ACROSS and sometimes WITHIN cells -- not like-for-like")
    print("  * best-of is not RT-honest (RULE_restart_accounting)")
    json.dump(stamped(rows, __file__), open(f"runs/n{a.size}_primal_picture.json", "w"), indent=1)
