"""rt_to_k_optimal.py -- ZERO-compute RT comparison from existing logs.

For each |C|=20 cell: OUR heuristic's time-to-reach K's best-known value, vs K's Inc.Time.
- K values parsed directly from paper/paper-reference-data.md (§|C| = 20 table; no hand transcription).
  Columns: Inst | Joint BK | Joint Gap% | Joint IncT | LBBD BK | LBBD Imp% | LBBD IncT.
  K_best = min(Joint BK, LBBD BK); K_time = the IncT of the method that achieved K_best.
- OUR time = first wall_s in any runs/fixopt_<cell>_n20_*.jsonl where incumbent <= K_best*(1+tol).
  Reported as the FASTEST across runs (best-case) + #runs that reached it (honesty: not mean-of-seeds).
CAVEAT: our fixopt runs' core count is whatever they ran at (dev), K's is 4-core Gurobi/Xeon -> DIRECTIONAL,
not a banked similar-settings cell.
"""
import glob, json, os, re
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "paper", "paper-reference-data.md")
TOL = 0.001   # reach K_best within 0.1%


def parse_k_n20():
    txt = open(REF, encoding="utf-8").read()
    # isolate the "### |C| = 20" section up to the next "### |C|"
    m = re.search(r"###\s*\|C\|\s*=\s*20(.*?)###\s*\|C\|\s*=\s*30", txt, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not re.match(r"^[CR]C?\d+$", cells[0]):
            continue
        try:
            inst = cells[0]
            joint_bk, joint_inct = float(cells[1]), float(cells[3])
            lbbd_bk, lbbd_inct = float(cells[4]), float(cells[6])
        except ValueError:
            continue
        if lbbd_bk <= joint_bk:
            k_best, k_time, k_src = lbbd_bk, lbbd_inct, "LBBD"
        else:
            k_best, k_time, k_src = joint_bk, joint_inct, "Joint"
        out[inst] = {"k_best": k_best, "k_time": k_time, "k_src": k_src,
                     "joint_bk": joint_bk, "lbbd_bk": lbbd_bk}
    return out


def our_time_to(cell, k_best):
    """fastest wall_s across fixopt runs at which incumbent <= k_best*(1+TOL); + #runs reached / total."""
    best_t, reached, total = None, 0, 0
    for fp in glob.glob(os.path.join(ROOT, "runs", f"fixopt_{cell}_n20_*.jsonl")):
        total += 1
        try:
            recs = [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        t_hit = None
        for r in recs:
            inc = r.get("incumbent")
            w = r.get("wall_s")
            if isinstance(inc, (int, float)) and isinstance(w, (int, float)) and inc <= k_best * (1 + TOL):
                t_hit = w
                break
        if t_hit is not None:
            reached += 1
            if best_t is None or t_hit < best_t:
                best_t = t_hit
    return best_t, reached, total


def main():
    K = parse_k_n20()
    print(f"parsed {len(K)} K n20 cells from paper-reference-data.md\n")
    hdr = f"{'cell':6} {'K_best':>8} {'K_src':>6} {'K_time':>8} {'our_fastest':>11} {'reached':>8} {'verdict':>9}"
    print(hdr); print("-" * len(hdr))
    wins = losses = noreach = 0
    rows = []
    for cell in sorted(K):
        kb, kt, ksrc = K[cell]["k_best"], K[cell]["k_time"], K[cell]["k_src"]
        ot, reached, total = our_time_to(cell, kb)
        if total == 0:
            continue   # no fixopt run for this cell
        if ot is None:
            verdict = "NO-REACH"; noreach += 1
        elif ot < kt:
            verdict = "WIN"; wins += 1
        else:
            verdict = "slower"; losses += 1
        rows.append({"cell": cell, "k_best": kb, "k_src": ksrc, "k_time": kt,
                     "our_fastest_s": ot, "reached_runs": f"{reached}/{total}", "verdict": verdict})
        print(f"{cell:6} {kb:8.1f} {ksrc:>6} {kt:8.0f} "
              f"{(f'{ot:.1f}' if ot is not None else '-'):>11} {reached}/{total:<6} {verdict:>9}")
    print(f"\nOn cells we have runs for: WIN (reached K_best faster than K) {wins} | "
          f"slower {losses} | never reached K_best {noreach}")
    print("DIRECTIONAL: our fixopt core count is dev-setting, not the 4-core similar-settings basis; "
          "K_time is K's Gurobi/Xeon Inc.Time. Not banked cells.")
    json.dump(stamped(rows, __file__), open(os.path.join(ROOT, "validation", "rt_to_k_optimal.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
