"""
instance_specs.py -- one row per |C|=20 instance, every spec that could
explain how the easy-reduction bound behaves.  Read-only; safe to run
alongside the sweep.

Columns
  family, series           C/R/RC ; Solomon series number
  nC, demand_tot           customers, total demand
  Qc, Qv                   car / vessel capacity
  carLB, vesLB             ceil(demand/Q)  -- binding fleet lower bounds
  nSat                     satellites
  tw_mean, tw_min, tw_max  time-window widths
  tw_frac                  tw_mean / horizon           (wide TW -> big-M weak)
  ovl_deg                  interval-graph degree: mean # windows overlapping a customer's
  reach_frac               fraction of ordered pairs (i,j) where j can follow i on one route
  contention               spatial-weighted temporal contention (mean)
  bbox_diag, nn_mean       geometry: bbox diagonal, mean nearest-neighbour distance
  clus                     nn_mean / bbox_diag         (small -> clustered)
  k_joint, k_gap, k_lbbd   Karademir Joint BK / gap% / LBBD BK
  k_bound                  Karademir bound = k_joint*(1-gap/100)
  k_proven                 gap == 0
"""
from __future__ import annotations
import sys, math, json
sys.path.insert(0, ".")
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
import numpy as np
from build_instance import build

K_REF = {  # (Joint BK, Joint Gap%, LBBD BK) -- paper/paper-reference-data.md
    "C201": (697.7, 0, 697.7), "C203": (682.7, 54, 676.3),
    "C204": (683.5, 57, 668.1), "C205": (685.2, 0, 685.2),
    "R201": (821.7, 0, 821.7), "R205": (642.2, 0, 676.3),
    "R211": (669.1, 48, 584.4),
    "RC201": (981.2, 0, 981.2), "RC203": (754.3, 56, 767.6),
    "RC208": (881.6, 65, 858.7),
}

LOOSE = ["C203", "C204", "R203", "R204", "R207", "R208", "R211",
         "RC202", "RC203", "RC204", "RC208"]


def specs(nm, size=20):
    p = build(nm, size, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
    C = list(p.customers); n = len(C)
    nd = p.nodes
    q = np.array([nd[c].demand for c in C], float)
    e = np.array([nd[c].earliest for c in C], float)
    l = np.array([nd[c].latest for c in C], float)
    s = np.array([nd[c].serviceTime for c in C], float)
    w = l - e
    hz = nd[p.CDC].latest - nd[p.CDC].earliest
    D = np.array(p.DistMatrix, float)
    xs = np.array([nd[c].xcor for c in C]); ys = np.array([nd[c].ycor for c in C])
    cc = np.array([[math.hypot(xs[i]-xs[j], ys[i]-ys[j]) for j in range(n)]
                   for i in range(n)])
    np.fill_diagonal(cc, np.inf)
    nn = np.sort(cc, axis=1)
    diag = math.hypot(np.ptp(xs), np.ptp(ys)) or 1.0
    dscale = float(np.median([D[C[i], C[j]] for i in range(n) for j in range(n) if i != j]))

    raw_ov = np.zeros((n, n)); prox_ov = np.zeros((n, n)); reach = 0
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            ov = max(0.0, min(l[i], l[j]) - max(e[i], e[j]))
            raw_ov[i, j] = ov
            prox_ov[i, j] = ov / max(1.0, w[i]) * math.exp(-D[C[i], C[j]] / dscale)
            if e[i] + s[i] + D[C[i], C[j]] <= l[j]:
                reach += 1

    kr = K_REF.get(nm)
    row = dict(
        inst=nm, family="".join(ch for ch in nm if ch.isalpha()),
        series=int("".join(ch for ch in nm if ch.isdigit())),
        nC=n, demand_tot=float(q.sum()),
        Qc=p.CarCapacity, Qv=p.VesselCapacity,
        carLB=math.ceil(q.sum() / p.CarCapacity),
        vesLB=math.ceil(q.sum() / p.VesselCapacity),
        nSat=len(p.satellites),
        tw_mean=round(float(w.mean()), 0), tw_min=round(float(w.min()), 0),
        tw_max=round(float(w.max()), 0), tw_frac=round(float(w.mean() / hz), 3),
        ovl_deg=round(float((raw_ov > 0).sum(axis=1).mean()), 1),
        reach_frac=round(reach / (n * (n - 1)), 3),
        contention=round(float(prox_ov.sum(axis=1).mean()), 2),
        bbox_diag=round(diag, 1), nn_mean=round(float(nn[:, 0].mean()), 2),
        clus=round(float(nn[:, 0].mean() / diag), 3),
        k_joint=kr[0] if kr else None, k_gap=kr[1] if kr else None,
        k_lbbd=kr[2] if kr else None,
        k_bound=round(kr[0] * (1 - kr[1] / 100), 1) if kr else None,
        k_proven=(kr[1] == 0) if kr else None,
        loose=nm in LOOSE,
    )
    return row


if __name__ == "__main__":
    which = sys.argv[1].split(",") if len(sys.argv) > 1 else \
        ["C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208",
         "R201", "R202", "R203", "R204", "R205", "R206", "R207", "R208",
         "R209", "R210", "R211",
         "RC201", "RC202", "RC203", "RC204", "RC205", "RC206", "RC207", "RC208"]
    rows = []
    for nm in which:
        try:
            rows.append(specs(nm.strip()))
            print(f"  {nm} ok", file=sys.stderr)
        except Exception as ex:
            print(f"  {nm} FAIL {ex}", file=sys.stderr)
    json.dump(rows, open("analysis/instance_specs.json", "w"), indent=1, default=str)

    cols = ["inst", "family", "series", "demand_tot", "carLB", "vesLB", "nSat",
            "tw_mean", "tw_frac", "ovl_deg", "reach_frac", "contention",
            "clus", "nn_mean", "k_gap", "k_bound", "k_lbbd", "loose"]
    print("| " + " | ".join(cols) + " |")
    print("|" + "|".join("---" for _ in cols) + "|")
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
