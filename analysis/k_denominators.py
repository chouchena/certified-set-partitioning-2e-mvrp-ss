"""k_denominators.py -- S1a: K's per-cell comparison denominators, PROVENANCE-STAMPED.

Zero-compute. Parses paper/paper-reference-data.md Table-3 |C|=20 and |C|=30 per-instance rows
(cols: Inst | Joint BK | Joint Gap% | Joint IncT | LBBD BK | LBBD Imp% | LBBD IncT) and emits, per cell:
  K_OV   = min(Joint BK, LBBD BK)                  (K's best incumbent)
  K_LB   = Joint BK * (1 - Joint Gap%/100)         (K's strongest PUBLISHED per-cell LB; no per-cell
                                                     LBBD LB is published -> Joint LB is the best available)
  K_IncT = IncT of whichever method achieved K_OV  (K's time-to-best)
  provenance = "Karademir 2025 Table 3, |C|=N, row <cell>"
Note: |C|=10 uses a different compact layout in the source (proven-trivial BK only) -> handled separately/TODO.
"""
import json, os, re
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "paper", "paper-reference-data.md")


def parse_size(txt, size, nxt):
    m = re.search(rf"###\s*\|C\|\s*=\s*{size}(.*?)###\s*\|C\|\s*=\s*{nxt}", txt, re.S)
    if not m:
        m = re.search(rf"###\s*\|C\|\s*=\s*{size}(.*)$", txt, re.S)  # last table
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
        out[c[0]] = {"K_OV": k_ov, "K_LB": round(jbk * (1 - jgap / 100), 1), "K_IncT": k_rt,
                     "joint_bk": jbk, "joint_gap_pct": jgap, "lbbd_bk": lbk,
                     "proven": (jgap == 0), "prov": f"Karademir 2025 Table 3, |C|={size}, row {c[0]}"}
    return out


def main():
    txt = open(REF, encoding="utf-8").read()
    data = {"20": parse_size(txt, 20, 30), "30": parse_size(txt, 30, 999)}
    for size in ("20", "30"):
        d = data[size]
        print(f"\n=== K denominators |C|={size}  ({len(d)} cells) ===")
        print(f"{'cell':6} {'K_OV':>8} {'K_LB':>8} {'K_IncT':>8} {'proven':>7}")
        for cell in sorted(d):
            r = d[cell]
            print(f"{cell:6} {r['K_OV']:8.1f} {r['K_LB']:8.1f} {r['K_IncT']:8.0f} {str(r['proven']):>7}")
    json.dump(stamped(data, __file__), open(os.path.join(ROOT, "validation", "k_denominators.json"), "w"), indent=2)
    n_proven = sum(1 for d in data.values() for r in d.values() if r["proven"])
    print(f"\ntotal cells: {sum(len(d) for d in data.values())}; proven (gap=0): {n_proven}. "
          "wrote validation/k_denominators.json  (|C|=10 compact-layout parse = TODO)")


if __name__ == "__main__":
    main()
