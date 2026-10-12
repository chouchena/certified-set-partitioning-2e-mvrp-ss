"""
Correlate run-log outcomes with instance-structural features.

Question: what property of an instance actually predicts (a) whether the
exact methods converge, (b) how tight the block-relaxation bound gets,
(c) whether the fix-and-optimize matheuristic beats Karademir?

Descriptive, not inferential -- n is 7-9 per size. Spearman rank
correlation + scatter; the mechanism (wide TW -> big-M -> weak LP) is an
a-priori hypothesis being checked, not a fishing expedition.

Outputs: analysis/corr_table.csv, analysis/corr_report.md, analysis/*.png
"""
from __future__ import annotations
import json
import math
import os
import re
import sys

sys.path.insert(0, ".")
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from build_instance import build

OUT = "analysis"
os.makedirs(OUT, exist_ok=True)

# instances we have run data for
SET10 = ["C201", "C203", "C204", "R201", "R205", "R211", "RC201", "RC203", "RC208"]
SET20 = ["C201", "C203", "C204", "R201", "R205", "RC201", "RC203"]

# Karademir published (paper/paper-reference-data.md)
K10 = {"C201": 365.5, "C203": 327.5, "C204": 304.3, "R201": 420.1, "R205": 376.4,
       "R211": 344.5, "RC201": 392.8, "RC203": 356.5, "RC208": 318.7}
K20 = {  # (Joint BK, Joint gap%, LBBD BK)
    "C201": (697.7, 0, 697.7), "C203": (682.7, 54, 676.3), "C204": (683.5, 57, 668.1),
    "R201": (821.7, 0, 821.7), "R205": (642.2, 0, 676.3),
    "RC201": (981.2, 0, 981.2), "RC203": (754.3, 56, 767.6)}


# ---------------------------------------------------------------------------
def features(name, size):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=20)
    C = list(p.customers); nd = p.nodes; D = p.DistMatrix
    S = list(p.satellites); CDC = p.CDC
    dem = np.array([nd[c].demand for c in C], float)
    tw = np.array([nd[c].latest - nd[c].earliest for c in C], float)
    svc = nd[C[0]].serviceTime
    horizon = nd[CDC].latest - nd[CDC].earliest
    xs = np.array([nd[c].xcor for c in C]); ys = np.array([nd[c].ycor for c in C])
    # geographic dispersion: mean nearest-neighbour distance / bounding-box diagonal
    cc = np.array([[math.hypot(xs[i]-xs[j], ys[i]-ys[j]) for j in range(len(C))]
                   for i in range(len(C))])
    np.fill_diagonal(cc, np.inf)
    nn = cc.min(axis=1)
    diag = math.hypot(np.ptp(xs), np.ptp(ys))
    # feasible street arcs surviving the TW filter (a direct looseness proxy)
    setCd = [0] + C
    feas = sum(1 for i in setCd for j in setCd if i != j
               and nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest)
    npairs = len(setCd) * (len(setCd) - 1)
    tau = p.TransferDuration
    maxTravel = max(D[i][s1] + D[s1][j] for i in C for j in setCd if i != j for s1 in S) \
        if len(C) <= 25 else max(D[i][s1] for i in C for s1 in S) * 2
    bigM_street = float(np.mean([nd[i].latest + nd[i].serviceTime + tau
                                 + max(D[i][s1] + D[s1][j] for s1 in S) - nd[j].earliest
                                 for i in C for j in setCd if i != j and (i, j)]))
    return {
        "instance": name, "size": size, "family": name[:2] if name[1].isalpha() else name[0],
        "tau": tau, "svc": svc, "horizon": round(horizon, 0),
        "total_demand": float(dem.sum()), "demand_cv": round(dem.std() / dem.mean(), 3),
        "demand_max": float(dem.max()),
        "tw_frac": round(float(tw.mean()) / horizon, 3),
        "tw_width_mean": round(float(tw.mean()), 0), "tw_width_min": round(float(tw.min()), 0),
        "tw_width_cv": round(float(tw.std() / tw.mean()), 3),
        "arc_survival": round(feas / npairs, 3),
        "geo_dispersion": round(float(nn.mean()) / diag, 4),
        "bigM_street_mean": round(bigM_street, 0),
        "lcars": math.ceil(dem.sum() / p.CarCapacity),
        "lvessels": math.ceil(dem.sum() / p.VesselCapacity),
    }


# ---------------------------------------------------------------------------
def joint_outcomes():
    """joint MILP: from runs/summary.csv (repro_* rows)."""
    df = pd.read_csv("runs/summary.csv")
    out = {}
    for _, r in df.iterrows():
        m = re.match(r"repro_([A-Z]+\d+)_n(\d+)_tauformula", str(r["run_id"]))
        if not m:
            continue
        inst, size = m.group(1), int(m.group(2))
        proven = str(r["status"]).startswith("integer optimal")
        out[(inst, size)] = {
            "joint_obj": r["final_incumbent"], "joint_bound": r["final_bound"],
            "joint_gap_pct": None if pd.isna(r["final_gap_pct"]) else float(r["final_gap_pct"]),
            "joint_wall_s": float(r["wall_s"]), "joint_proven": int(proven),
        }
    return out


def blockA_outcomes():
    """block A adaptive / fixed runs: from runs/{,invalid/}dualbnd_*/blockA_* jsonl."""
    out = {}
    for base in ("runs", "runs/invalid"):
        for fn in os.listdir(base) if os.path.isdir(base) else []:
            m = re.match(r"(?:dualbnd|blockA)_([A-Z]+\d+)_n(\d+)\.jsonl", fn)
            if not m:
                continue
            inst, size = m.group(1), int(m.group(2))
            evs = [json.loads(l) for l in open(os.path.join(base, fn))]
            bp = [(e["extra"]["t"], e["bound"]) for e in evs
                  if e.get("trigger") == "blockA_progress" and e.get("extra", {}).get("t") is not None]
            fin = next((e for e in evs if e.get("trigger") in
                        ("block_relaxation", "block_relaxation_final")), None)
            x = (fin or {}).get("extra", {})
            rec = out.setdefault((inst, size), {})
            if x:
                lb = x.get("blockA_lb", x.get("blockA_bestbound", x.get("blockA")))
                inc = x.get("blockA", x.get("blockA_incumbent"))
                rec.update({
                    "blockA_lb": lb, "blockA_incumbent": inc,
                    "blockA_proven": int(bool(x.get("proven") or x.get("blockA_proven"))),
                    "water_lb": x.get("water_lb"),
                    "blockA_internal_gap": (None if not (lb and inc) else round(100 * (inc - lb) / inc, 1)),
                })
            if bp:
                def at(t): return next((b for tt, b in reversed(bp) if tt <= t), None)
                rec["blockA_bound_60s"] = at(60)
                rec["blockA_bound_600s"] = at(600)
                rec["blockA_bound_3600s"] = at(3600) or bp[-1][1]
                last600 = [b for t, b in bp if t >= bp[-1][0] - 600]
                if len(last600) >= 2:
                    rec["blockA_tail_slope_per_min"] = round((last600[-1] - last600[0]) /
                                                             max(1, (bp[-1][0] - (bp[-1][0]-600)) / 60), 3)
    return out


def fixopt_outcomes():
    """fixopt 3-mode: parse validation/fixopt_n{10,20}_3mode.log trajectories."""
    out = {}
    for path, size in [("validation/fixopt_n10_3mode.log", 10),
                       ("validation/fixopt_n20_3mode.log", 20)]:
        if not os.path.exists(path):
            continue
        txt = open(path).read()
        for blk in re.split(r"=== (\w+) n=\d+ fixopt", txt)[1:]:
            pass
        # simpler: iterate blocks
        blocks = re.findall(
            r"=== (\w+) n=(\d+) fixopt.*?construct: ok=\w+ obj=([\d.]+)(.*?)final best \(verified\) = ([\d.]+)",
            txt, re.S)
        for inst, sz, seed_obj, body, final in blocks:
            imps = re.findall(r"\+improve obj=([\d.]+).*?t=(\d+)s", body)
            imps = [(float(v), int(t)) for v, t in imps]
            t_plateau = imps[-1][1] if imps else 0
            biggest = max(((imps[i-1][0]-imps[i][0]) if i else (float(seed_obj)-imps[0][0]) for i in range(len(imps))), default=0)
            out[(inst, int(sz))] = {
                "fixopt_seed": float(seed_obj), "fixopt_final": float(final),
                "fixopt_n_improve": len(imps), "fixopt_t_plateau_s": t_plateau,
                "fixopt_biggest_jump": round(biggest, 1),
            }
    return out


# ---------------------------------------------------------------------------
def build_frame():
    rows = []
    for size, names in [(10, SET10), (20, SET20)]:
        jo, ba, fo = joint_outcomes(), blockA_outcomes(), fixopt_outcomes()
        for nm in names:
            r = features(nm, size)
            r.update(jo.get((nm, size), {}))
            r.update(ba.get((nm, size), {}))
            r.update(fo.get((nm, size), {}))
            if size == 10:
                r["k_ref"] = K10[nm]; r["k_gap"] = 0; r["k_proven"] = 1
                r["k_bound"] = K10[nm]
            else:
                bk, g, lb = K20[nm]
                r["k_ref"] = bk; r["k_gap"] = g; r["k_proven"] = int(g == 0)
                r["k_bound"] = round(bk * (1 - g / 100), 1); r["k_lbbd"] = lb
            if r.get("fixopt_final") and r.get("k_ref"):
                r["fixopt_vs_k_pct"] = round(100 * (r["fixopt_final"] - r["k_ref"]) / r["k_ref"], 2)
            if r.get("blockA_lb") and r.get("water_lb") and r.get("k_bound"):
                br = r["blockA_lb"] + r["water_lb"]
                r["block_relax_bound"] = round(br, 1)
                r["block_relax_vs_k_x"] = round(br / r["k_bound"], 3)
            rows.append(r)
    return pd.DataFrame(rows)


def corr_report(df):
    feat_cols = ["tau", "svc", "horizon", "total_demand", "demand_cv", "demand_max",
                 "tw_frac", "tw_width_mean", "tw_width_min", "tw_width_cv",
                 "arc_survival", "geo_dispersion", "bigM_street_mean", "lcars", "lvessels"]
    out_cols = ["joint_gap_pct", "joint_wall_s", "joint_proven", "k_gap", "k_proven",
                "blockA_internal_gap", "blockA_proven", "block_relax_vs_k_x",
                "fixopt_vs_k_pct", "fixopt_n_improve", "fixopt_t_plateau_s", "fixopt_biggest_jump"]
    lines = ["# Log-outcome × instance-feature correlation\n",
             f"_n={len(df)} instance-runs ({(df['size']==10).sum()} at |C|=10, "
             f"{(df['size']==20).sum()} at |C|=20). Spearman ρ; |ρ|≥0.6 flagged. "
             "Descriptive — small n._\n"]
    tab = []
    for oc in out_cols:
        if oc not in df or df[oc].notna().sum() < 4:
            continue
        row = {"outcome": oc, "n": int(df[oc].notna().sum())}
        for fc in feat_cols:
            sub = df[[fc, oc]].dropna()
            if len(sub) < 4:
                row[fc] = ""
                continue
            rho, pv = spearmanr(sub[fc], sub[oc])
            row[fc] = f"{rho:+.2f}{'*' if abs(rho) >= 0.6 else ''}"
        tab.append(row)
    cdf = pd.DataFrame(tab)
    lines.append(cdf.to_markdown(index=False))
    lines.append("\n\n## Strong relationships (|ρ| ≥ 0.6)\n")
    for oc in out_cols:
        if oc not in df or df[oc].notna().sum() < 4:
            continue
        hits = []
        for fc in feat_cols:
            sub = df[[fc, oc]].dropna()
            if len(sub) < 4:
                continue
            rho, _ = spearmanr(sub[fc], sub[oc])
            if abs(rho) >= 0.6:
                hits.append((fc, rho, len(sub)))
        if hits:
            lines.append(f"- **{oc}**: " + ", ".join(f"{fc} (ρ={r:+.2f}, n={n})"
                                                     for fc, r, n in sorted(hits, key=lambda z: -abs(z[1]))))
    open(f"{OUT}/corr_report.md", "w", encoding="utf-8").write("\n".join(lines))
    df.to_csv(f"{OUT}/corr_table.csv", index=False)
    return cdf


def scatters(df):
    pairs = [("tw_frac", "joint_gap_pct", "|C|=20 joint MILP gap vs TW width"),
             ("tw_frac", "blockA_internal_gap", "block A internal gap vs TW width"),
             ("geo_dispersion", "fixopt_vs_k_pct", "fixopt vs Karademir (%) vs geo dispersion"),
             ("bigM_street_mean", "block_relax_vs_k_x", "block-relax / Karademir bound vs big-M")]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for ax, (fx, fy, title) in zip(axes.flat, pairs):
        sub = df[[fx, fy, "family", "size"]].dropna()
        if sub.empty:
            ax.set_visible(False); continue
        for fam, mk in [("C", "o"), ("R", "s"), ("RC", "^")]:
            s2 = sub[sub["family"] == fam]
            ax.scatter(s2[fx], s2[fy], marker=mk, s=90, label=fam,
                       edgecolor="k", linewidth=0.6)
        if len(sub) >= 4:
            rho, _ = spearmanr(sub[fx], sub[fy])
            ax.set_title(f"{title}\nρ={rho:+.2f} (n={len(sub)})", fontsize=10)
        ax.set_xlabel(fx); ax.set_ylabel(fy); ax.legend(fontsize=8); ax.grid(alpha=.3)
    plt.tight_layout()
    plt.savefig(f"{OUT}/scatters.png", dpi=110)
    print(f"wrote {OUT}/scatters.png")


def within_family(df):
    """Controlled view: same family + size => demand, geography, tau, svc
    held ~constant, so TW width is the only thing varying."""
    lines = ["\n## Controlled: within family+size (TW is ~the only varying feature)\n"]
    for (fam, size), g in df.groupby(["family", "size"]):
        if len(g) < 3:
            continue
        g = g.sort_values("tw_frac")
        lines.append(f"\n**{fam}, |C|={size}** (demand cv≈{g['demand_cv'].mean():.2f}, "
                     f"geo≈{g['geo_dispersion'].mean():.3f}, tau={g['tau'].iloc[0]}):")
        for _, r in g.iterrows():
            lines.append(f"  - {r['instance']}: TW={r['tw_frac']:.2f}  "
                         f"joint_gap={_fmt(r.get('joint_gap_pct'))}%  "
                         f"K_gap={r.get('k_gap')}%  "
                         f"blockA_gap={_fmt(r.get('blockA_internal_gap'))}%  "
                         f"fixopt_vs_K={_fmt(r.get('fixopt_vs_k_pct'))}%")
    return lines


def _fmt(v):
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "—"


if __name__ == "__main__":
    df = build_frame()
    print(df[["instance", "size", "family", "tw_frac", "arc_survival", "geo_dispersion",
              "bigM_street_mean", "joint_gap_pct", "blockA_internal_gap",
              "block_relax_vs_k_x", "fixopt_vs_k_pct"]].to_string(index=False))
    print()
    cdf = corr_report(df)
    wf = within_family(df)
    with open(f"{OUT}/corr_report.md", "a", encoding="utf-8") as fh:
        fh.write("\n".join(wf))
    print(cdf.to_string(index=False))
    print("\n".join(wf))
    scatters(df)
    print(f"\nwrote {OUT}/corr_report.md, {OUT}/corr_table.csv")
