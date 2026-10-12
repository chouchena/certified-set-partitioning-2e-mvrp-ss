"""lb_crossing_samehw.py -- ZERO-compute SAME-MACHINE crossing (R10 cheap-before-expensive).

Corrects lb_rerun_design.md's false premise: the reproduced-LBBD curves DO exist on disk
(runs/lbbd_<cell>_n20_karademir.jsonl). This joins, per loose |C|=20 cell:
  - our proven bound: best (max proven block_relax) AND cold-k_max (largest-k single solve)
    from crossfeed/easy_reduction*_<cell>_n20.json  (proven, verified metric)
  - K's REPRODUCED same-machine final LBBD bound + time-to-plateau, split across concatenated
    runs (seq resets) in runs/lbbd_<cell>_n20_karademir.jsonl
  - K's PAPER LB (their hardware, from easy_reduction_consolidated.md)
and reports the THREAD-INDEPENDENT crossing: our proven bound > K's best-ever same-machine bound?
No solver is launched; this reads only finished artifacts.
"""
import glob, json, os, re
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K_PAPER_LB = {"C203": 314.0, "RC202": 507.6, "R203": 402.2, "RC204": 321.2, "RC203": 331.9,
              "R204": 351.3, "R211": 347.9, "R208": 346.4, "R207": 385.1, "C204": 293.9, "RC208": 308.6}


def our_bounds(cell, size=20):
    """(best_proven, k_best, cold_kmax_proven, k_max, cold_wall) from the descend/sweep JSON.

    SIZE IS A PARAMETER. Hardcoding it to _n20.json made `rt_normalize.py` print n20 bounds
    under an n30 heading for the whole M7 arm. Default 20 leaves every existing caller
    unchanged. The glob is exact-suffix on purpose: it must not pick up the variant artifacts
    (_noprov, _tl450, _kcapbug) that sit beside the canonical ones at n30.
    """
    files = (glob.glob(os.path.join(ROOT, "crossfeed", f"easy_reduction_descend_{cell}_n{size}.json"))
             or glob.glob(os.path.join(ROOT, "crossfeed", f"easy_reduction_{cell}_n{size}.json")))
    if not files:
        return None
    recs = json.load(open(files[0], encoding="utf-8"))
    recs = [r for r in (recs if isinstance(recs, list) else [recs])
            if isinstance(r, dict) and r.get("proven") and "block_relax" in r]
    if not recs:
        return None
    best = max(recs, key=lambda r: r["block_relax"])
    kmax = max(recs, key=lambda r: r["k"])          # largest k = the cold root solve
    return (best["block_relax"], best["k"], kmax["block_relax"], kmax["k"], kmax.get("wall"))


def k_repro(cell):
    """K's reproduced same-machine LBBD: final best_bound + wall to reach it, best over the
    concatenated runs in the jsonl (split on seq reset)."""
    fp = os.path.join(ROOT, "runs", f"lbbd_{cell}_n20_karademir.jsonl")
    if not os.path.exists(fp):
        return None
    recs = [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
    runs, cur, last_seq = [], [], -1
    for r in recs:
        s = r.get("seq", 0)
        if s < last_seq:                 # new run started
            runs.append(cur); cur = []
        cur.append(r); last_seq = s
    runs.append(cur)
    best_final, best_t = None, None
    for run in runs:
        pts = [(r.get("wall_s"), r.get("best_bound")) for r in run
               if isinstance(r.get("best_bound"), (int, float)) and isinstance(r.get("wall_s"), (int, float))]
        if not pts:
            continue
        fb = max(b for _, b in pts)
        tt = min(w for w, b in pts if b >= fb - 0.5)
        if best_final is None or fb > best_final:
            best_final, best_t = fb, tt
    return (best_final, best_t)


def main():
    hdr = (f"{'cell':6} {'our_best':>9} {'our_coldkmax':>12} {'K_repro':>8} {'K_rep_t':>8} "
           f"{'K_paper':>8} {'best>Krep':>9} {'cold>Krep':>9} {'best>Kpap':>9}")
    print(hdr); print("-" * len(hdr))
    n = w_best = w_cold = w_pap = 0
    out = []
    for cell in sorted(K_PAPER_LB):
        ob = our_bounds(cell); kr = k_repro(cell); kp = K_PAPER_LB[cell]
        if not ob or not kr:
            print(f"{cell:6}  MISSING  ours={bool(ob)} krepro={bool(kr)}"); continue
        best, kb, cold, km, cw = ob
        krf, krt = kr
        c_best, c_cold, c_pap = best > krf, cold > krf, best > kp
        n += 1; w_best += c_best; w_cold += c_cold; w_pap += c_pap
        print(f"{cell:6} {best:9.1f} {cold:12.1f} {krf:8.1f} {krt:8.1f} {kp:8.1f} "
              f"{str(c_best):>9} {str(c_cold):>9} {str(c_pap):>9}")
        out.append({"cell": cell, "our_best": best, "k_best": kb, "our_cold_kmax": cold,
                    "k_max": km, "cold_wall_s": cw, "K_repro_final": krf, "K_repro_t_s": krt,
                    "K_paper": kp, "best_gt_Krepro": c_best, "cold_gt_Krepro": c_cold})
    print(f"\nSAME-MACHINE: best proven bound > K reproduced final: {w_best}/{n} | "
          f"single COLD k_max solve > K reproduced final: {w_cold}/{n} | best > K paper: {w_pap}/{n}")
    json.dump(stamped(out, __file__), open(os.path.join(ROOT, "validation", "lb_crossing_samehw.json"), "w"), indent=2)
    print("wrote validation/lb_crossing_samehw.json")


if __name__ == "__main__":
    main()
