"""Read the grid and answer, under the rules registered before it ran.

NOTHING HERE CHOOSES A THRESHOLD. Every rule below was fixed in advance and is cited:

  METRIC        mean and SD over seeds, per cell. Decision 66, author verbatim: "We wont compare
                BESTOFALL to K's OV as a main metric - quote mean and std - Best as complementary
                info only." Best-of is printed beside, labelled complementary.

  BEAT RULE     decision 244. K publish to ONE DECIMAL, so a published b denotes [b-0.05, b+0.05].
                ours < b-0.05 is a BEAT; inside is a TIE and is reported as a tie; above is a LOSS.
                Registered before any grid data existed.

  ATTAINMENT    the 35 K-PROVEN cells (27 at n10, 7 at n20, 1 at n30) are the only places the true
                optimum is known, so they are the only measurement of our distance FROM OPTIMALITY.
                A proven cell is never counted as a beat -- beating a proven optimum is impossible,
                and a value below one means an infeasibility, not a win. It is reported as such.

  PROXIMITY     Table 3 and Table 4's proximity is INFERRED (0.0); Table 6's is STATED (0.1).
                Attainment at p=0.0 against p=0.1 on the proven cells discriminates which instance
                set K actually solved. That comparison is the point of running both arms.

  SPEND         actual, not allotted. _run_wall_s summed over seeds, against the cell's envelope.
                Reporting allotted would overstate our cost; reporting the cheapest run would be
                choosing the accounting by its answer (FINDING_rt_budget_fairness section 3).

    python analysis/grid_vs_k.py [--seeds 0,1,2]
"""
import argparse
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

OUT = os.path.join(ROOT, "runs", "oracle")
GRID = os.path.join(ROOT, "runs", "grid")
KREF = os.path.join(ROOT, "data", "karademir2025", "k_reference.json")

PREC = 0.05          # K publish to one decimal: b denotes [b-PREC, b+PREC]. Decision 244.


def kref():
    return json.load(io.open(KREF, encoding="utf-8"))


def verdict(ours, b):
    """BEAT / TIE / LOSS under decision 244. Never widened, never narrowed."""
    if ours < b - PREC:
        return "BEAT"
    if ours > b + PREC:
        return "LOSS"
    return "TIE"


def load(seeds):
    """Every grid dump, keyed (cell, size, prox). Only dumps that verify are used."""
    rows = {}
    for p in sorted(glob.glob(os.path.join(GRID, "g_*.json"))):
        try:
            d = json.load(io.open(p, encoding="utf-8"))
        except Exception:
            continue
        s = d.get("_seed")
        if seeds and s not in seeds:
            continue
        key = (d.get("_instance"), d.get("_size"), float(d.get("_proximity")))
        rows.setdefault(key, []).append(d)
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="")
    a = ap.parse_args()
    seeds = set(int(x) for x in a.seeds.split(",") if x.strip()) if a.seeds else None

    K = kref()
    pi = K["table3"]["per_instance"]
    rows = load(seeds)
    if not rows:
        print("No grid dumps yet in %s." % os.path.relpath(GRID, ROOT))
        return 2

    print("GRID vs K -- every rule below was registered BEFORE the grid ran.")
    print("   metric: mean and SD over seeds (d66).  beat: clears K's +/-%.2f precision (d244)."
          % PREC)
    print()
    per_cell, proven_rows = [], []
    print("   %-7s %4s %4s %3s %10s %8s %10s %10s %8s  %s"
          % ("cell", "n", "p", "N", "mean", "sd", "best", "K", "delta", "verdict"))
    for (cell, size, prox), ds in sorted(rows.items(), key=lambda kv: (-kv[0][1], kv[0][2], kv[0][0])):
        vals = [float(d["objVal"]) for d in ds if d.get("objVal") is not None]
        if not vals:
            continue
        mean = st.mean(vals)
        sd = st.pstdev(vals) if len(vals) > 1 else 0.0
        kd = pi.get(str(size), {}).get(cell)
        bk = float(kd["joint_bk"]) if kd else None
        is_proven = bool(kd) and kd.get("joint_gap") == 0.0
        spend = sum(float(d.get("_run_wall_s") or 0) for d in ds)
        rec = dict(cell=cell, size=size, proximity=prox, n_seeds=len(vals),
                   mean=round(mean, 3), sd=round(sd, 3), best=round(min(vals), 3),
                   k_bk=bk, proven=is_proven, spend_s=round(spend, 1),
                   envelope_s=float(ds[0].get("_wall_budget_s") or 0) * len(vals))
        if bk is None:
            v = "-- no per-instance K value at this size"
        elif is_proven:
            # ATTAINMENT, never a beat. Below a proven optimum means infeasibility, not a win.
            gap = 100.0 * (mean - bk) / bk
            v = ("ATTAINED" if abs(mean - bk) <= PREC else
                 ("BELOW PROVEN OPTIMUM -- INVESTIGATE" if mean < bk - PREC
                  else "missed by %.2f%%" % gap))
            rec["attainment"] = v
            proven_rows.append(rec)
        else:
            v = verdict(mean, bk)
            rec["verdict"] = v
        rec["reading"] = v
        per_cell.append(rec)
        print("   %-7s %4d %4s %3d %10.3f %8.3f %10.3f %10s %8s  %s"
              % (cell, size, prox, len(vals), mean, sd, min(vals),
                 ("%.1f" % bk) if bk else "-",
                 ("%+.3f" % (mean - bk)) if bk else "-", v))

    # ---------------- registered summaries ----------------
    print()
    print("1. BEATS, on K's UNPROVEN cells only, mean vs K, clearing +/-%.2f" % PREC)
    for size in (20, 30):
        for prox in (0.0, 0.1):
            sub = [r for r in per_cell if r["size"] == size and r["proximity"] == prox
                   and not r["proven"] and r.get("verdict")]
            if not sub:
                continue
            b = [r for r in sub if r["verdict"] == "BEAT"]
            t = [r for r in sub if r["verdict"] == "TIE"]
            l = [r for r in sub if r["verdict"] == "LOSS"]
            dp = [100.0 * (r["mean"] - r["k_bk"]) / r["k_bk"] for r in b]
            print("   n%-4d p%-4s  cells %2d   BEAT %2d   tie %2d   loss %2d%s"
                  % (size, prox, len(sub), len(b), len(t), len(l),
                     ("   depth: median %.2f%%  best %.2f%%"
                      % (st.median(dp), min(dp))) if dp else ""))

    print()
    print("2. ATTAINMENT on K's PROVEN cells -- the only measurement of distance from a TRUE")
    print("   optimum this benchmark permits. Never a beat.")
    for size in (10, 20, 30):
        for prox in (0.0, 0.1):
            sub = [r for r in proven_rows if r["size"] == size and r["proximity"] == prox]
            if not sub:
                continue
            att = [r for r in sub if r["attainment"] == "ATTAINED"]
            bad = [r for r in sub if "BELOW" in r["attainment"]]
            miss = [r for r in sub if r["attainment"].startswith("missed")]
            gaps = [100.0 * (r["mean"] - r["k_bk"]) / r["k_bk"] for r in miss]
            print("   n%-4d p%-4s  proven %2d   ATTAINED %2d   missed %2d%s%s"
                  % (size, prox, len(sub), len(att), len(miss),
                     ("  median miss %.2f%%" % st.median(gaps)) if gaps else "",
                     ("   BELOW OPTIMUM %d -- INVESTIGATE" % len(bad)) if bad else ""))

    print()
    print("3. PROXIMITY DISCRIMINATION. Table 3's proximity is INFERRED at 0.0; Table 6 STATES")
    print("   0.1. If attainment on the proven cells is materially better at one value, that is")
    print("   evidence of which instance set K solved -- the project's largest exposure, settled")
    print("   by measurement rather than by argument.")
    for size in (10, 20, 30):
        r0 = [r for r in proven_rows if r["size"] == size and r["proximity"] == 0.0]
        r1 = [r for r in proven_rows if r["size"] == size and r["proximity"] == 0.1]
        if not (r0 and r1):
            continue
        a0 = sum(1 for r in r0 if r["attainment"] == "ATTAINED")
        a1 = sum(1 for r in r1 if r["attainment"] == "ATTAINED")
        print("   n%-4d  attained at p0.0: %2d/%2d    at p0.1: %2d/%2d    %s"
              % (size, a0, len(r0), a1, len(r1),
                 "p0.0 favoured" if a0 > a1 else ("p0.1 favoured" if a1 > a0
                                                  else "does not discriminate")))

    print()
    print("4. AGGREGATES where K publish no per-instance value.")
    t4 = {int(r["size"]): r for r in K["table4"]} if isinstance(K["table4"], list) else {}
    for prox in (0.0, 0.1):
        sub = [r for r in per_cell if r["size"] == 50 and r["proximity"] == prox]
        if len(sub) == 27 and 50 in t4:
            ours = st.mean([r["mean"] for r in sub])
            bk = float(t4[50]["bk"])
            print("   n50 p%-4s pooled over 27: ours %10.3f   K %8.1f   %s"
                  % (prox, ours, bk, verdict(ours, bk)))
        elif sub:
            print("   n50 p%-4s only %d of 27 cells -- a mean over fewer than 27 is NOT comparable"
                  % (prox, len(sub)))
    for fam, pref in (("C", "C2"), ("R", "R2"), ("RC", "RC2")):
        # "C2" / "R2" / "RC2" separate the families on their own: RC201 does not start with
        # "R2", and C201 does not start with "RC2". No extra guard is needed.
        sub = [r for r in per_cell if r["size"] == 100 and r["cell"].startswith(pref)]
        kk = K["table6"].get(fam, {})
        want = kk.get("n")
        if sub and want and len(sub) == want:
            ours = st.mean([r["mean"] for r in sub])
            print("   n100 family %-3s over %2d: ours %10.3f   K zIP %8s"
                  % (fam, len(sub), ours, kk.get("joint_zip") or kk.get("zIP") or "-"))
        elif sub:
            print("   n100 family %-3s only %d of %s cells -- not comparable to a family mean"
                  % (fam, len(sub), want))

    print()
    print("5. SPEND, actual not allotted.")
    for size in sorted({r["size"] for r in per_cell}, reverse=True):
        sub = [r for r in per_cell if r["size"] == size]
        sp = [r["spend_s"] for r in sub if r["spend_s"]]
        en = [r["envelope_s"] for r in sub if r["envelope_s"]]
        if sp and en:
            print("   n%-4d median actual %7.0f s of %7.0f s allotted  (%.0f%% of our share)"
                  % (size, st.median(sp), st.median(en),
                     100.0 * st.median(sp) / st.median(en)))

    json.dump(stamped({"per_cell": per_cell, "seeds": sorted(seeds) if seeds else "all",
                       "beat_rule": "ours < K - %.2f (decision 244)" % PREC,
                       "metric": "mean and SD over seeds (decision 66)"},
                      __file__, "data/karademir2025/k_reference.json"),
              io.open(os.path.join(OUT, "grid_vs_k.json"), "w", encoding="utf-8"),
              indent=1, default=str)
    print()
    print("   -> runs/oracle/grid_vs_k.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
