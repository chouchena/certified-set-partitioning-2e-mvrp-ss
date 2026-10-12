"""
n50 completion sequence — runs the full close-out the moment the campaign reaches 27/27.

Written 2026-09-12 at 25/27 so nothing waits on a human after the last cell lands (standing
rule: do not stop runs, and do not leave the box idle).

Refuses to produce any aggregate below 27/27, because K publish only a POOLED 27-instance
average at |C|=50 (Table 4). One missing cell means there is nothing valid to compare against,
and a partial mean is not a smaller version of the real one -- the outstanding cells are
R-family, the family where AB wins, so a partial figure is biased in a known direction.

    python analysis/n50_close.py            # refuses unless 27/27
    python analysis/n50_close.py --preview  # run on whatever is complete, clearly labelled
"""
import os, re, sys, json, glob, argparse, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped
import kref

CELLS = ([f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC2{i:02d}" for i in range(1, 9)])
LOG = os.path.join(ROOT, "runs", "lb_reprov_n50.log")


def completed():
    """Authoritative: the completion log, NOT files on disk. An artifact appears while its
    cell is still being written (C206 sat at 11 records/352 s for 24 minutes before finishing
    at 15 records/1797 s)."""
    txt = open(LOG, encoding="utf-8", errors="replace").read()
    return set(re.findall(r"\]\s+([A-Z]+\d+) done in", txt))


def milp(cell, size=50):
    best = None
    for pat in (f"easy_reduction_descend_{cell}_n{size}.json",
                f"easy_reduction_descend_{cell}_n{size}_*.json"):
        # "_n{size}*" would make n10 match n100 -- see join_freshness.live_milp.
        for f in glob.glob(os.path.join(ROOT, "crossfeed", pat)):
            recs = json.load(open(f))
            for r in (recs if isinstance(recs, list) else [recs]):
                v = r.get("block_relax")
                if isinstance(v, (int, float)) and (best is None or v > best):
                    best = v
    return best


def depth(cell, size=50):
    h = 0
    for pat in (f"easy_reduction_descend_{cell}_n{size}.json",
                f"easy_reduction_descend_{cell}_n{size}_*.json"):
        for f in glob.glob(os.path.join(ROOT, "crossfeed", pat)):
            recs = json.load(open(f))
            for r in (recs if isinstance(recs, list) else [recs]):
                h = max(h, r.get("nH") or 0)
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    done = completed()
    missing = [c for c in CELLS if c not in done]
    print("=" * 76)
    print(f"n50 CLOSE-OUT — {len(done)}/27 complete")
    if missing:
        print(f"  outstanding: {missing}")
        fams = {("RC" if c.startswith("RC") else c[0]) for c in missing}
        print(f"  families still open: {sorted(fams)}")
    print("=" * 76)
    if missing and not a.preview:
        print("\nREFUSING to aggregate below 27/27. K publish only a pooled 27-instance average")
        print("at |C|=50, so a partial mean has nothing valid to compare against. Re-run when")
        print("the log shows 27, or pass --preview for a clearly-labelled partial.")
        return 1
    if missing:
        print("\n*** PREVIEW ONLY — PARTIAL, NOT REPORTABLE ***\n")

    grid = {r["cell"]: r for r in json.load(open(os.path.join(
        ROOT, "runs", "ab_grid_provenanced.json")))["records"] if r["size"] == 50}
    rows = []
    for c in sorted(done):
        m = milp(c)
        if m is None:
            continue
        ab = grid[c]["ab4_full"]
        rows.append({"cell": c, "milp": m, "ab": ab, "best2": max(m, ab),
                     "ratio": ab / m, "depth": depth(c)})

    # 1. crossover
    w = sum(1 for r in rows if r["ratio"] > 1)
    print(f"1. CROSSOVER  AB beats MILP on {w}/{len(rows)}   "
          f"median AB/MILP {st.median(r['ratio'] for r in rows):.3f}")
    print(f"   context: n20 0/27 (0.589) | n30 0/27 (0.658) | n100 17/27 (1.090)")
    win = [r for r in rows if r["ratio"] > 1]
    los = [r for r in rows if r["ratio"] <= 1]
    if win and los:
        print(f"   depth separation: wins {min(r['depth'] for r in win)}-"
              f"{max(r['depth'] for r in win)} of 50, losses "
              f"{min(r['depth'] for r in los)}-{max(r['depth'] for r in los)}")
        xs = [r["depth"] / 50 for r in rows]
        ys = [r["ratio"] for r in rows]
        mx, my = st.mean(xs), st.mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        print(f"   correlation(depth, AB/MILP) = {num/den:+.3f}")

    # 2. pooled comparison against K Table 4 -- only meaningful at 27/27
    k = kref.table4(size=50, wls="1:10", method="Joint")[0]
    klbbd = kref.table4(size=50, wls="1:10", method="LBBD")[0]
    klb = k["bk"] * (1 - k["gap_imp"] / 100)
    b2 = st.mean(r["best2"] for r in rows)
    print(f"\n2. vs K POOLED (Table 4, |C|=50, WLS 1:10)")
    print(f"   K derived LB  {klb:8.1f}  = BK {k['bk']} x (1 - {k['gap_imp']}%)")
    print(f"   our Best-of-2 {b2:8.1f}   ratio {b2/klb:.3f}")
    print(f"   K gap {k['gap_imp']:.1f}%  ->  with Best-2 {(klbbd['bk']-b2)/klbbd['bk']*100:.1f}%"
          f"   (upper ref = LBBD BK {klbbd['bk']})")
    print(f"   closed share of K's closable gap: "
          f"{(b2-klb)/(klbbd['bk']-klb)*100:.1f}%")
    print("   !! JENSEN CAVEAT: K's n50 LB is derived from a POOLED mean, so the bias sign is")
    print("      unknown and unrecoverable. This figure is an approximation, and no per-instance")
    print("      n50 data exists or ever will (claim: k-repo-publishes-no-results).")

    # 3. bound-vs-achieved at n50
    t4 = {(r["size"], r["wls"], r["method"]): r for r in kref._doc()["table4_full"]}
    r50 = t4[(50, "1:10", "LBBD")]
    d = st.mean(grid[r["cell"]]["best_travel"] for r in rows)
    v = st.mean(grid[r["cell"]]["V_final"] for r in rows)
    print(f"\n3. BOUND-vs-ACHIEVED at n50 (K LBBD row)")
    print(f"   Dist_LB {d:7.1f} vs street travel {r50['travel_streets']:7.1f}  "
          f"ratio {d/r50['travel_streets']:.3f}")
    print(f"   V_LB    {v:7.2f} vs fleet SL      {r50['fleet_sl']:7.2f}  "
          f"ratio {v/r50['fleet_sl']:.3f}")

    out = os.path.join(ROOT, "runs", "n50_final.json")
    if not missing:
        json.dump(stamped({"cells": rows, "crossover_wins": w,
                   "median_ratio": st.median(r["ratio"] for r in rows),
                   "best2_mean": b2, "k_derived_lb": klb, "ratio_vs_k": b2 / klb}, __file__),
                  open(out, "w"), indent=1)
        print(f"\n-> {os.path.relpath(out, ROOT)}")
        print("\nNEXT (validation/SESSION_RESUME.md section 4):")
        print("  python analysis/join_freshness.py      # n50 ages the crossover by construction")
        print("  python analysis/ab_vs_milp_build.py    # rebuild the derived view WITH n50")
        print("  then: commit (LB REPROV n50 COMPLETE), then the merged AB change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
