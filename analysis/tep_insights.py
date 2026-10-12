"""Derived analyses and figures over the TEP event, operator, runtime and objective record. (2026-09-27)

Six figures, each stating ONE claim, each from banked artifacts only (no solver). Derived data is written to
runs/oracle/tep_insights.json so every number in a caption has generating code, and every figure carries the
provenance sidecar figstyle.save() writes.

  T1  the headline      proven optimality gap by size, ours vs theirs, with the attainment layer beside it
  T2  where it comes from   the same reduction split into bound-side and primal-side, per size
  T3  the mechanism     cars above the LP fleet term vs cost distance to the best known, all sizes
  T4  bound calibration (OPT - LB)/OPT against the share of the objective one car costs, where optima are known
  T5  anytime           the bound's LP trajectory and the primal's improvement chain against charged seconds
  T6  attribution       what each pipeline stage contributed, and which ALNS operators produced the new bests

    python analysis/tep_insights.py [--figs T1 T3] [--no-figs]
"""
import argparse
import collections
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped
from bound_certificate import certified

CELLS = ["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)] + ["RC%d" % i for i in range(201, 209)]
DIRS = ("", "ceil", "selchain", "forced", "refine", "alns", "masterip")
STAGE_ORDER = ("floor", "ceil", "refine", "alns", "selchain", "masterip", "forced")
STAGE_LABEL = {"floor": "floor selection", "ceil": "ceil selection", "refine": "local search", "alns": "ALNS", "selchain": "select+chain", "forced": "fleet cap"}


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def art(cell, size, sub):
    return load(os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, size)))


def stage_values(cell, size):
    return {s: art(cell, size, "" if s == "floor" else s) for s in STAGE_ORDER}


def best_of(size):
    d = load(os.path.join(ROOT, "runs", "oracle", "tep_n%d_best_of.json" % size))
    return {r["cell"]: r for r in d["rows"]} if d else {}


def n100_bound(cell):
    v = [float(d["lp_composed"]) for f in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_%s_n100_k*.json" % cell)) for d in [load(f)] if d and certified(d)]
    return max(v) if v else None


def collect():
    """Everything the figures need, per size and per cell, from the artifacts."""
    out = {}
    for n in (10, 20, 30, 50, 100):
        bo = best_of(n); cells = {}
        for c in CELLS:
            sv = stage_values(c, n)
            have = {s: float(v["objVal"]) for s, v in sv.items() if v}
            if not have: continue
            cars = {s: int(v["nCars"]) for s, v in sv.items() if v}
            secs = {s: v.get("secs") for s, v in sv.items() if v}
            r = bo.get(c, {})
            lb = r.get("our_lb") if n != 100 else n100_bound(c)
            cands = [load(os.path.join(ROOT, "runs", "oracle", ("tep_cg_bound_%s.json" % c) if n == 100 else ("tep_cg_bound_%s_n%d.json" % (c, n)))),
                     load(os.path.join(ROOT, "runs", "oracle", ("tep_cg_bound_%s_ip.json" % c) if n == 100 else ("tep_cg_bound_%s_n%d_ip.json" % (c, n))))]
            cands = [x for x in cands if x and not x.get("primal_rounding")]
            b = next((x for x in cands if certified(x)), (cands[0] if cands else None))   # a CERTIFIED artifact wins over one that merely exists
            abandoned = sum((x.get("secs") or 0) for x in cands if not certified(x))      # machine time spent on attempts whose value is not reported
            ops = []
            a = sv.get("alns")
            if a and isinstance(a.get("stats"), dict): ops = a["stats"].get("best_ops") or []
            rf = sv.get("refine")
            cells[c] = dict(cell=c, family=fam(c), stages=have, cars=cars, secs=secs,
                            best=min(have.values()), best_stage=min(have, key=have.get),
                            theirs=r.get("theirs"), their_lb=r.get("their_lb"), proven=bool(r.get("proven")),
                            our_lb=lb, N_lp=(float(b["N"]) if b and b.get("N") is not None else None),
                            bound_hist=[(h.get("secs"), h.get("lp")) for h in ((b or {}).get("hist") or []) if h.get("lp") is not None],
                            bound_secs=((b or {}).get("secs") if certified(b or {}) else 0), abandoned_secs=abandoned, alns_ops=ops,
                            refine_types=(rf.get("by_type") if rf else None))
        out["n%d" % n] = cells
    return out


def gaps(D):
    """Proven optimality gap (OV - LB)/OV per size, ours and theirs, on the open cells; and the attainment layer."""
    g = {}
    for n in (20, 30):
        rs = [r for r in D["n%d" % n].values() if r["our_lb"] and r["theirs"] and not r["proven"]]
        if not rs: continue
        g["n%d" % n] = dict(cells=len(rs),
                            ours=st.mean(100 * (1 - r["our_lb"] / r["best"]) for r in rs),
                            theirs=st.mean(100 * (1 - r["their_lb"] / r["theirs"]) for r in rs),
                            ours_med=st.median(100 * (1 - r["our_lb"] / r["best"]) for r in rs),
                            theirs_med=st.median(100 * (1 - r["their_lb"] / r["theirs"]) for r in rs),
                            smaller=sum(1 for r in rs if (1 - r["our_lb"] / r["best"]) < (1 - r["their_lb"] / r["theirs"])))
    f = load(os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json"))
    if f:
        W = sum(r["n"] for r in f["rows"])
        g["n100"] = dict(cells=W, ours=sum(r["n"] * r["our_gap"] for r in f["rows"]) / W,
                         theirs=sum(r["n"] * r["their_gap"] for r in f["rows"]) / W, ours_med=None, theirs_med=None, smaller=None)
    att = {}
    for n in (10, 20, 30):
        rs = [r for r in D["n%d" % n].values() if r["proven"] and r["theirs"]]
        if rs: att["n%d" % n] = dict(cells=len(rs), mean=st.mean(100 * (r["best"] / r["theirs"] - 1) for r in rs),
                                     within1=sum(1 for r in rs if r["best"] / r["theirs"] - 1 <= 0.01))
    return g, att


def decomposition(D):
    """Of the interval K left open, how much each leg closes: bound side (our LB - their LB) and primal side (their OV - our OV)."""
    out = {}
    for n in (20, 30):
        rs = [r for r in D["n%d" % n].values() if r["our_lb"] and r["theirs"] and not r["proven"]]
        if not rs: continue
        b = [100 * (r["our_lb"] - r["their_lb"]) / (r["theirs"] - r["their_lb"]) for r in rs]
        p = [100 * (r["theirs"] - r["best"]) / (r["theirs"] - r["their_lb"]) for r in rs]
        out["n%d" % n] = dict(cells=len(rs), bound=st.median(b), primal=st.median(p))
    f = load(os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json"))
    if f:
        W = sum(r["n"] for r in f["rows"])
        out["n100"] = dict(cells=W,
                           bound=sum(r["n"] * 100 * (r["our_lb"] - r["their_lb"]) / (r["their_inc"] - r["their_lb"]) for r in f["rows"]) / W,
                           primal=sum(r["n"] * 100 * (r["their_inc"] - r["our_inc"]) / (r["their_inc"] - r["their_lb"]) for r in f["rows"]) / W)
    return out


def calibration(D):
    """(OPT - LB)/OPT against the share of the objective one car costs, on the cells whose optimum is proven."""
    import verifier3 as V
    out = {}
    for n in (10, 20, 30):
        rs = [r for r in D["n%d" % n].values() if r["proven"] and r["our_lb"] and r["theirs"]]
        if not rs: continue
        inst = V.load_instance(rs[0]["cell"], n, 0.0); pen = float(inst.penalty_cars)
        pts = [dict(cell=r["cell"], family=r["family"], gap=100 * (1 - r["our_lb"] / r["theirs"]), share=100 * pen / r["theirs"]) for r in rs]
        out["n%d" % n] = dict(cells=len(rs), mean_gap=st.mean(p["gap"] for p in pts), mean_share=st.mean(p["share"] for p in pts), points=pts)
    return out


def attribution(D):
    """What each stage contributed (prefix-minimum), and which ALNS operator pairs produced the new bests."""
    stage, ops = {}, collections.Counter()
    for n in (10, 20, 30, 50, 100):
        acc = collections.defaultdict(list); cov = collections.Counter()
        for r in D["n%d" % n].values():
            run = None
            for s in STAGE_ORDER:
                if s not in r["stages"]: continue
                cov[s] += 1
                v = r["stages"][s]
                gain = 0.0 if run is None else max(0.0, run - v)
                if run is None or v < run: run = v
                acc[s].append(100 * gain / r["stages"]["floor"] if "floor" in r["stages"] else 0.0)
            for o in r["alns_ops"] or []:
                ops[(o.get("destroy"), o.get("repair"))] += 1
        stage["n%d" % n] = {s: dict(cells=cov[s], mean_gain_pct=st.mean(acc[s]) if acc[s] else 0.0,
                                    cells_gained=sum(1 for x in acc[s] if x > 1e-9)) for s in STAGE_ORDER if cov[s]}
    return stage, {"%s+%s" % k: v for k, v in sorted(ops.items(), key=lambda kv: -kv[1])}


def runtime(D):
    """Charged seconds per stage against the per-cell envelope."""
    import run_full_grid as G
    out = {}
    for n in (10, 20, 30, 50, 100):
        rows = []
        for r in D["n%d" % n].values():
            env = G.envelope(n, 2.5, r["cell"])
            prim = sum(v for v in r["secs"].values() if isinstance(v, (int, float)))
            bnd = r["bound_secs"] if isinstance(r["bound_secs"], (int, float)) else 0
            ab = r.get("abandoned_secs") or 0
            rows.append(dict(cell=r["cell"], envelope=env, primal_s=prim, bound_s=bnd, abandoned_s=ab,
                             share=100 * (prim + bnd) / env, share_with_abandoned=100 * (prim + bnd + ab) / env))
        if rows:
            out["n%d" % n] = dict(cells=len(rows), median_share=st.median(r["share"] for r in rows),
                                  max_share=max(r["share"] for r in rows), max_cell=max(rows, key=lambda r: r["share"])["cell"],
                                  over_envelope=[r["cell"] for r in rows if r["share"] > 100],
                                  median_share_with_abandoned=st.median(r["share_with_abandoned"] for r in rows),
                                  max_share_with_abandoned=max(r["share_with_abandoned"] for r in rows),
                                  over_envelope_with_abandoned=[r["cell"] for r in rows if r["share_with_abandoned"] > 100], rows=rows)
    return out


# ------------------------------------------------------------------ figures
def figures(D, G_, A, DEC, CAL, STG, OPS, RT, want):
    import figstyle as F
    import matplotlib.pyplot as plt
    import numpy as np
    F.apply()
    made = []

    if "T1" in want and G_:
        fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.0, 2.8), gridspec_kw=dict(width_ratios=[2.0, 1.0]))
        sizes = [s for s in ("n20", "n30", "n100") if s in G_]
        x = np.arange(len(sizes)); w = 0.36
        ax.bar(x - w / 2, [G_[s]["theirs"] for s in sizes], w, color=F.LIGHT, edgecolor=F.GREY, label="predecessors")
        ax.bar(x + w / 2, [G_[s]["ours"] for s in sizes], w, color=F.FAMILY["C"], label="this paper")
        for i, s in enumerate(sizes):
            ax.text(i - w / 2, G_[s]["theirs"] + 1.5, "%.0f" % G_[s]["theirs"], ha="center", fontsize=8, color=F.GREY)
            ax.text(i + w / 2, G_[s]["ours"] + 1.5, "%.0f" % G_[s]["ours"], ha="center", fontsize=8, color=F.FAMILY["C"])
        ax.set_xticks(x); ax.set_xticklabels(["|C|=%s\n%d open cells" % (s[1:], G_[s]["cells"]) for s in sizes])
        ax.set_ylabel("proven optimality gap (%)"); ax.set_ylim(0, max(G_[s]["theirs"] for s in sizes) * 1.25)
        ax.legend(frameon=False, loc="upper left"); ax.spines[["top", "right"]].set_visible(False)
        ks = [s for s in ("n10", "n20") if s in A]
        ax2.bar(np.arange(len(ks)), [A[s]["mean"] for s in ks], 0.5, color=F.FAMILY["RC"])
        for i, s in enumerate(ks): ax2.text(i, A[s]["mean"] + 0.04, "%.2f%%" % A[s]["mean"], ha="center", fontsize=8, color=F.FAMILY["RC"])
        ax2.set_xticks(np.arange(len(ks))); ax2.set_xticklabels(["|C|=%s\n%d proven" % (s[1:], A[s]["cells"]) for s in ks])
        ax2.set_ylabel("above the proven optimum (%)"); ax2.set_ylim(0, max(A[s]["mean"] for s in ks) * 1.8)
        ax2.spines[["top", "right"]].set_visible(False)
        made.append(F.save(fig, "T1_proven_gap_by_size", ["analysis/tep_insights.py"])); plt.close(fig)

    if "T2" in want and DEC:
        fig, ax = plt.subplots(figsize=(4.2, 2.8))
        sizes = [s for s in ("n20", "n30", "n100") if s in DEC]
        x = np.arange(len(sizes))
        b = [DEC[s]["bound"] for s in sizes]; p = [DEC[s]["primal"] for s in sizes]
        ax.bar(x, b, 0.5, color=F.FAMILY["C"], label="bound side")
        ax.bar(x, p, 0.5, bottom=b, color=F.FAMILY["R"], label="primal side")
        for i, s in enumerate(sizes):
            if b[i] > 6: ax.text(i, b[i] / 2, "%.0f" % b[i], ha="center", va="center", color="white", fontsize=8)
            if p[i] > 6: ax.text(i, b[i] + p[i] / 2, "%.0f" % p[i], ha="center", va="center", color="white", fontsize=8)
        ax.axhline(0, color=F.GREY, lw=0.6)
        ax.set_xticks(x); ax.set_xticklabels(["|C|=%s" % s[1:] for s in sizes])
        ax.set_ylabel("share of the interval they left open,\nclosed by each leg (%)")
        ax.legend(frameon=False, loc="upper left"); ax.spines[["top", "right"]].set_visible(False)
        made.append(F.save(fig, "T2_which_leg_closes_it", ["analysis/tep_insights.py"])); plt.close(fig)

    if "T3" in want:
        fig, ax = plt.subplots(figsize=(4.6, 3.0))
        for fm in ("C", "R", "RC"):
            xs, ys = [], []
            for n in (10, 20, 30):
                for r in D["n%d" % n].values():
                    if r["family"] != fm or r["N_lp"] is None or not r["theirs"]: continue
                    xs.append(r["cars"][r["best_stage"]] - r["N_lp"]); ys.append(100 * (r["best"] / r["theirs"] - 1))
            if xs: ax.scatter(xs, ys, s=16, c=F.FAMILY[fm], marker=F.MARKER[fm], alpha=0.75, label=fm, edgecolors="none")
        ax.axhline(0, color=F.GREY, lw=0.6); ax.axvline(1.0, color=F.LIGHT, lw=0.8, ls="--")
        ax.text(1.03, ax.get_ylim()[1] * 0.92, "one car above\nthe LP fleet", fontsize=7, color=F.GREY)
        ax.set_xlabel("cars in our solution minus the LP fleet term"); ax.set_ylabel("distance to their best known (%)")
        ax.legend(frameon=False, title=None, loc="upper left"); ax.spines[["top", "right"]].set_visible(False)
        made.append(F.save(fig, "T3_fleet_excess_explains_the_tail", ["analysis/tep_insights.py"])); plt.close(fig)

    if "T4" in want and CAL:
        fig, ax = plt.subplots(figsize=(4.6, 3.0))
        for n, mk in ((10, "o"), (20, "s"), (30, "^")):
            k = "n%d" % n
            if k not in CAL: continue
            pts = CAL[k]["points"]
            ax.scatter([p["share"] for p in pts], [p["gap"] for p in pts], s=18, marker=mk, alpha=0.55,
                       c=[F.FAMILY[p["family"]] for p in pts], edgecolors="none")
            ax.scatter([CAL[k]["mean_share"]], [CAL[k]["mean_gap"]], s=90, marker=mk, facecolors="none", edgecolors=F.GREY, linewidths=1.2)
            ax.annotate("|C|=%d" % n, (CAL[k]["mean_share"], CAL[k]["mean_gap"]), textcoords="offset points", xytext=(8, 4), fontsize=8, color=F.GREY)
        lim = ax.get_xlim(); ax.plot(lim, lim, color=F.LIGHT, lw=0.8, ls="--"); ax.set_xlim(lim)
        ax.text(lim[1] * 0.62, lim[1] * 0.66, "gap = car share", fontsize=7, color=F.GREY, rotation=28)
        ax.set_xlabel("one car as a share of the optimum (%)"); ax.set_ylabel("bound below the proven optimum (%)")
        ax.spines[["top", "right"]].set_visible(False)
        made.append(F.save(fig, "T4_bound_calibration", ["analysis/tep_insights.py"])); plt.close(fig)

    if "T5" in want:
        fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.0, 2.8))
        shown = 0
        for r in sorted(D["n30"].values(), key=lambda r: r["cell"]):
            h = [(s, v) for s, v in r["bound_hist"] if isinstance(s, (int, float)) and s > 0]
            if len(h) < 4: continue
            fin = h[-1][1]
            ax.plot([s for s, _ in h], [100 * v / fin for _, v in h], lw=0.8, color=F.FAMILY[r["family"]], alpha=0.5)
            shown += 1
        ax.set_xscale("log"); ax.set_xlabel("seconds (log)"); ax.set_ylabel("% of the converged LP value")
        ax.set_ylim(50, 102); ax.set_title("bound, |C|=30 (%d cells)" % shown, fontsize=8, color=F.GREY)
        ax.spines[["top", "right"]].set_visible(False)
        for n, col in ((30, F.FAMILY["C"]), (100, F.FAMILY["R"])):
            xs, ys = [], []
            for r in D["n%d" % n].values():
                tot = sum(v for v in r["secs"].values() if isinstance(v, (int, float)))
                if tot and r["stages"].get("floor"):
                    xs.append(tot); ys.append(100 * (1 - r["best"] / r["stages"]["floor"]))
            if xs: ax2.scatter(xs, ys, s=16, color=col, alpha=0.7, edgecolors="none", label="|C|=%d" % n)
        ax2.set_xscale("log"); ax2.set_xlabel("primal seconds charged (log)"); ax2.set_ylabel("improvement over the floor route (%)")
        ax2.legend(frameon=False, loc="upper left"); ax2.spines[["top", "right"]].set_visible(False)
        made.append(F.save(fig, "T5_anytime_and_productivity", ["analysis/tep_insights.py"])); plt.close(fig)

    if "T6" in want and STG:
        fig, (ax, ax2) = plt.subplots(1, 2, figsize=(7.2, 2.9), gridspec_kw=dict(width_ratios=[1.6, 1.0]))
        sizes = [s for s in ("n10", "n20", "n30", "n50", "n100") if s in STG and STG[s]]
        stages = [s for s in STAGE_ORDER[1:] if any(s in STG[z] for z in sizes)]
        bottom = np.zeros(len(sizes))
        cols = {"ceil": F.FAMILY["C"], "refine": F.FAMILY["R"], "alns": F.FAMILY["RC"], "selchain": "#8a6d3b", "forced": F.GREY}
        for s in stages:
            v = np.array([STG[z].get(s, {}).get("mean_gain_pct", 0.0) for z in sizes])
            ax.bar(np.arange(len(sizes)), v, 0.55, bottom=bottom, color=cols.get(s, F.LIGHT), label=STAGE_LABEL[s])
            bottom += v
        ax.set_xticks(np.arange(len(sizes))); ax.set_xticklabels(["|C|=%s" % z[1:] for z in sizes])
        ax.set_ylabel("mean improvement over the\nfloor route (%)"); ax.legend(frameon=False, fontsize=7, ncol=2)
        ax.spines[["top", "right"]].set_visible(False)
        top = list(OPS.items())[:6]
        if top:
            ax2.barh(np.arange(len(top)), [v for _, v in top][::-1], 0.6, color=F.FAMILY["RC"])
            ax2.set_yticks(np.arange(len(top))); ax2.set_yticklabels([k.replace("+", " + ") for k, _ in top][::-1], fontsize=7)
            ax2.set_xlabel("new incumbents produced")
        ax2.set_title("ALNS destroy + repair pairs", fontsize=8, color=F.GREY); ax2.spines[["top", "right"]].set_visible(False)
        made.append(F.save(fig, "T6_stage_attribution", ["analysis/tep_insights.py"])); plt.close(fig)

    if "T7" in want:
        # OUR RESULTS THEMSELVES: per cell, the interval [LB, OV] we leave against the one they leave.
        for n in (20, 30):
            rs = [r for r in D["n%d" % n].values() if r["our_lb"] and r["theirs"] and r["their_lb"]]
            if not rs: continue
            rs.sort(key=lambda r: -(1 - r["their_lb"] / r["theirs"]))
            fig, ax = plt.subplots(figsize=(7.2, 3.0))
            x = np.arange(len(rs)); w = 0.2
            for i, r in enumerate(rs):
                if i % 2 == 0: ax.axvspan(i - 0.5, i + 0.5, color="#f4f4f4", lw=0, zorder=0)
                # BOTH intervals in the same unit: percent of THEIR best known. (2026-09-27: the first draft
                # divided our lower end by OUR incumbent and our upper end by theirs, which is not one scale.)
                ax.vlines(i - w, 100 * r["their_lb"] / r["theirs"], 100.0, color="#9a9a9a", lw=3.2, capstyle="butt", zorder=2)   # darker than the row shading, for print contrast
                ax.vlines(i + w, 100 * r["our_lb"] / r["theirs"], 100.0 * r["best"] / r["theirs"], color=F.FAMILY[r["family"]], lw=3.2, capstyle="butt", zorder=3)
                if r["proven"]: ax.plot([i - w], [100.0], marker="_", color=F.GREY, ms=7, mew=1.2)
            ax.axhline(100, color=F.GREY, lw=0.6)
            ax.set_xticks(x); ax.set_xticklabels([r["cell"] for r in rs], rotation=90, fontsize=6)
            ax.set_ylabel("% of their best known"); ax.set_xlim(-1, len(rs))
            ax.set_title("|C|=%d: the interval each paper leaves open (grey: theirs, colour: ours)" % n, fontsize=8, color=F.GREY)
            ax.spines[["top", "right"]].set_visible(False)
            made.append(F.save(fig, "T7_intervals_per_cell_n%d" % n, ["analysis/tep_insights.py"])); plt.close(fig)
        rs = [r for r in D["n100"].values() if r["our_lb"]]
        f100 = load(os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json"))
        if rs and f100:
            rs.sort(key=lambda r: (r["family"], r["cell"]))
            fig, ax = plt.subplots(figsize=(7.2, 3.0))
            kb = {r["family"]: r for r in f100["rows"]}
            for i, r in enumerate(rs):
                base = kb[r["family"]]["their_inc"]
                if i % 2 == 0: ax.axvspan(i - 0.5, i + 0.5, color="#f4f4f4", lw=0, zorder=0)
                ax.vlines(i, 100 * r["our_lb"] / base, 100 * r["best"] / base, color=F.FAMILY[r["family"]], lw=3.6, capstyle="butt", zorder=3)
            for fm, k in kb.items():
                idx = [i for i, r in enumerate(rs) if r["family"] == fm]
                ax.hlines(100.0, min(idx) - 0.4, max(idx) + 0.4, color=F.GREY, lw=1.0)
                ax.hlines(100 * k["their_lb"] / k["their_inc"], min(idx) - 0.4, max(idx) + 0.4, color=F.GREY, lw=1.0, ls="--")
            ax.set_xticks(np.arange(len(rs))); ax.set_xticklabels([r["cell"] for r in rs], rotation=90, fontsize=6)
            ax.set_ylabel("% of their family mean"); ax.set_xlim(-1, len(rs))
            ax.set_title("|C|=100: our per-cell interval against their family mean (solid) and derived family bound (dashed)", fontsize=8, color=F.GREY)
            ax.spines[["top", "right"]].set_visible(False)
            made.append(F.save(fig, "T7_intervals_per_cell_n100", ["analysis/tep_insights.py"])); plt.close(fig)

    if "T8" in want:
        # THE SAME RESULTS BY FAMILY: incumbent against theirs, bound against theirs, and the two gaps.
        fig, axes = plt.subplots(1, 3, figsize=(7.4, 2.7))
        sizes = [(20, "n20"), (30, "n30"), (100, "n100")]
        f100 = load(os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json"))
        rowsy = []
        for n, key in sizes:
            for fm in ("C", "R", "RC"):
                if n == 100 and f100:
                    k = next(r for r in f100["rows"] if r["family"] == fm)
                    rowsy.append((n, fm, 100 * (k["our_inc"] / k["their_inc"] - 1), k["our_lb"] / k["their_lb"], k["our_gap"], k["their_gap"]))
                else:
                    rr = [r for r in D[key].values() if r["family"] == fm and r["our_lb"] and r["theirs"] and not r["proven"]]
                    if not rr: continue
                    rowsy.append((n, fm, st.mean(100 * (r["best"] / r["theirs"] - 1) for r in rr), st.mean(r["our_lb"] / r["their_lb"] for r in rr),
                                  st.mean(100 * (1 - r["our_lb"] / r["best"]) for r in rr), st.mean(100 * (1 - r["their_lb"] / r["theirs"]) for r in rr)))
        lab = ["%d %s" % (n, fm) for n, fm, *_ in rowsy]; y = np.arange(len(rowsy))
        cols = [F.FAMILY[fm] for _, fm, *_ in rowsy]
        axes[0].barh(y, [r[2] for r in rowsy], 0.6, color=cols); axes[0].axvline(0, color=F.GREY, lw=0.6)
        axes[0].set_title("incumbent vs theirs (%)", fontsize=8, color=F.GREY)
        axes[1].barh(y, [r[3] for r in rowsy], 0.6, color=cols); axes[1].axvline(1, color=F.GREY, lw=0.6)
        axes[1].set_title("bound / their bound", fontsize=8, color=F.GREY)
        axes[2].barh(y - 0.18, [r[5] for r in rowsy], 0.34, color=F.LIGHT, label="theirs")
        axes[2].barh(y + 0.18, [r[4] for r in rowsy], 0.34, color=cols, label="ours")
        axes[2].set_title("proven optimality gap (%)", fontsize=8, color=F.GREY); axes[2].legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
        for i, ax in enumerate(axes):
            ax.set_yticks(y); ax.set_yticklabels(lab if i == 0 else [], fontsize=7); ax.invert_yaxis(); ax.spines[["top", "right"]].set_visible(False)
        made.append(F.save(fig, "T8_results_by_family", ["analysis/tep_insights.py"])); plt.close(fig)
    return made


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--figs", nargs="*", default=["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]); ap.add_argument("--no-figs", action="store_true"); a = ap.parse_args()
    D = collect()
    G_, A = gaps(D); DEC = decomposition(D); CAL = calibration(D); STG, OPS = attribution(D); RT = runtime(D)
    print("DERIVED DATA\n  proven optimality gap (open cells, mean):")
    for k, v in G_.items(): print("    %-5s %2d cells | ours %.1f%% vs theirs %.1f%%%s" % (k, v["cells"], v["ours"], v["theirs"], ("" if v["smaller"] is None else " | ours smaller on %d" % v["smaller"])))
    print("  attainment where they prove:")
    for k, v in A.items(): print("    %-5s %2d cells | mean %+.2f%% above the optimum, %d within 1%%" % (k, v["cells"], v["mean"], v["within1"]))
    print("  which leg closes the interval (median share):")
    for k, v in DEC.items(): print("    %-5s bound %.0f%% | primal %+.0f%%" % (k, v["bound"], v["primal"]))
    print("  bound calibration against proven optima:")
    for k, v in CAL.items(): print("    %-5s %2d cells | gap %.1f%% | one car = %.1f%% of the optimum" % (k, v["cells"], v["mean_gap"], v["mean_share"]))
    print("  stage attribution (mean %% of the floor value, cells covered):")
    for k, v in STG.items():
        print("    %-5s %s" % (k, ", ".join("%s %.2f%% (%d/%d)" % (STAGE_LABEL[s], d["mean_gain_pct"], d["cells_gained"], d["cells"]) for s, d in v.items() if s != "floor")))
    print("  ALNS operator pairs by new incumbents: %s" % (", ".join("%s %d" % kv for kv in list(OPS.items())[:6]) or "none recorded yet"))
    print("  runtime charged against the envelope:")
    for k, v in RT.items():
        print("    %-5s reported instruments: median %.1f%%, max %.1f%% (%s), over envelope %s | incl. abandoned attempts: median %.1f%%, max %.1f%%, over %s"
              % (k, v["median_share"], v["max_share"], v["max_cell"], v["over_envelope"] or "none", v["median_share_with_abandoned"], v["max_share_with_abandoned"], v["over_envelope_with_abandoned"] or "none"))
    out = dict(gaps=G_, attainment=A, decomposition=DEC, calibration=CAL, stage_attribution=STG, alns_operators=OPS, runtime=RT)
    p = os.path.join(ROOT, "runs", "oracle", "tep_insights.json")
    json.dump(stamped(out), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    if not a.no_figs:
        made = figures(D, G_, A, DEC, CAL, STG, OPS, RT, set(a.figs))
        print("  figures: %s" % ", ".join(os.path.basename(str(m)) for m in made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
