"""domination_table.py -- ZERO-compute combined OV + LB + RT vs K (|C|=20).

Per cell: our OV / K OV / diff%, our LB / K LB / diff%, our RT-to-K-optimal / K Inc.Time.
Sign: OV lower=better (neg diff% = win); LB higher=better (pos diff% = win); RT lower=better.
Sources: K = paper/paper-reference-data.md (§|C|=20); our OV = min incumbent over runs/fixopt_<cell>_n20_*.jsonl;
our LB = validation/lb_crossing_samehw.json (block_relax); our RT = fastest wall to reach K_OV in fixopt logs.
CAVEATS (not banked): our OV/RT are BEST-OF-RUNS (need mean+/-std); dev core count (not 4-core); LB validity
contingent on task #13.
"""
import glob, json, os, re
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import load_result

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL = 0.001


def parse_k():
    txt = open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8").read()
    m = re.search(r"###\s*\|C\|\s*=\s*20(.*?)###\s*\|C\|\s*=\s*30", txt, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) < 7 or not re.match(r"^[CR]C?\d+$", c[0]):
            continue
        try:
            jbk, jgap, jinct = float(c[1]), float(c[2]), float(c[3])
            lbk, linct = float(c[4]), float(c[6])
        except ValueError:
            continue
        k_ov = min(jbk, lbk)
        k_rt = linct if lbk <= jbk else jinct
        k_lb = round(jbk * (1 - jgap / 100), 1)   # K's Joint LB from its gap
        out[c[0]] = {"k_ov": k_ov, "k_lb": k_lb, "k_rt": k_rt}
    return out


def our_ov(cell):
    best = None
    for fp in glob.glob(os.path.join(ROOT, "runs", f"fixopt_{cell}_n20_*.jsonl")):
        try:
            for l in open(fp, encoding="utf-8"):
                if not l.strip():
                    continue
                r = json.loads(l)
                inc = r.get("best_incumbent") if r.get("best_incumbent") is not None else r.get("incumbent")
                if isinstance(inc, (int, float)) and (best is None or inc < best):
                    best = inc
        except Exception:
            continue
    return best


def our_rt(cell, k_ov):
    best = None
    for fp in glob.glob(os.path.join(ROOT, "runs", f"fixopt_{cell}_n20_*.jsonl")):
        try:
            recs = [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        for r in recs:
            inc, w = r.get("incumbent"), r.get("wall_s")
            if isinstance(inc, (int, float)) and isinstance(w, (int, float)) and inc <= k_ov * (1 + TOL):
                if best is None or w < best:
                    best = w
                break
    return best


def main():
    K = parse_k()
    ourlb = {d["cell"]: d.get("our_best") for d in load_result(os.path.join(ROOT, "validation", "lb_crossing_samehw.json"))}
    hdr = (f"{'cell':6} | {'ourOV':>7} {'K_OV':>7} {'dOV%':>6} | "
           f"{'ourLB':>7} {'K_LB':>7} {'dLB%':>6} | {'ourRT':>8} {'K_RT':>7} {'RTx':>6}")
    print(hdr); print("-" * len(hdr))
    for cell in sorted(K):
        oov, olb = our_ov(cell), ourlb.get(cell)
        kov, klb, krt = K[cell]["k_ov"], K[cell]["k_lb"], K[cell]["k_rt"]
        ort = our_rt(cell, kov) if oov is not None else None
        if oov is None and olb is None:
            continue
        dov = f"{(oov-kov)/kov*100:+.1f}" if oov else "-"
        dlb = f"{(olb-klb)/klb*100:+.1f}" if olb else "-"
        rtx = f"{krt/ort:.0f}x" if ort else "-"
        print(f"{cell:6} | {(f'{oov:.1f}' if oov else '-'):>7} {kov:7.1f} {dov:>6} | "
              f"{(f'{olb:.1f}' if olb else '-'):>7} {klb:7.1f} {dlb:>6} | "
              f"{(f'{ort:.1f}' if ort else '-'):>8} {krt:7.0f} {rtx:>6}")
    print("\nSign: dOV% neg = we win (lower OV); dLB% pos = we win (higher LB); RTx = K_time/our_time (>1 faster).")
    print("BEST-OF-RUNS (OV,RT) + dev cores + LB validity pending task #13 -> DIRECTIONAL, not banked.")


if __name__ == "__main__":
    main()
