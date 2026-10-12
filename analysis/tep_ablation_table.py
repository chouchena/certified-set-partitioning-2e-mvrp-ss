"""Ablation of the TEP primal pipeline, per size: what each stage bought, from the banked artifacts. (d526, item 6)

The pipeline (paper/TEP_FORMULATION.md section 6) is a minimum over stages, so the contribution of stage k is
    min over stages 1..k  minus  min over stages 1..k-1,
per cell, then summarised per size. The stage order is the pipeline order:
    floor -> ceil -> refine -> alns -> selchain (cars-first select+chain) -> forced (master fleet cap, triggered).

INTERIM, AND SAID SO. Until the uniform runs of PREREG_uniform_pipeline.md exist, some stages were run on a
subset of cells and some refine/alns artifacts descend from an incumbent that already contained a later stage's
result (the historical run order was not the pipeline order). The table therefore reports, per stage, how many
cells CARRY an artifact of that stage, and the prefix-minimum gain is exact only where every stage ran. The
coverage column is what tells the reader which rows are uniform. Numbers are gaps to K best incumbent where a
per-cell K value exists (n10, n20, n30), PROVEN and OPEN apart; at n50 and n100 the gain is reported in objective
units and percent of the floor value only.

    python analysis/tep_ablation_table.py --size 30
"""
import argparse
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped
from k_comparison import k_best_incumbent

STAGES = ("floor", "ceil", "refine", "alns", "selchain", "masterip", "forced")
CELLS = ["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)] + ["RC%d" % i for i in range(201, 209)]


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--size", type=int, default=30, choices=(10, 20, 30, 50, 100)); a = ap.parse_args()
    n = a.size
    kt = {}
    kts = load(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json")) or {}
    if ("n%d" % n) in kts:
        kt = {r["cell"]: r for r in kts["n%d" % n]["rows"]}
    rows = []
    for c in CELLS:
        vals = {}
        for s in STAGES:
            p = os.path.join(ROOT, "runs", "postpass", "" if s == "floor" else s, "ownwater_%s_n%d.json" % (c, n))
            d = load(p)
            if d: vals[s] = float(d["objVal"])
        if "floor" not in vals:
            continue
        kb, _ = k_best_incumbent(c, n)
        run = None; prefix = {}; gain = {}
        for s in STAGES:
            v = vals.get(s)
            before = run
            run = v if run is None else (min(run, v) if v is not None else run)
            prefix[s] = run
            gain[s] = (before - run) if (before is not None and v is not None) else None
        rows.append(dict(cell=c, proven=bool(kt.get(c, {}).get("proven", False)), theirs=kb, floor=vals["floor"], final=run,
                         has={s: (s in vals) for s in STAGES}, gain=gain, prefix=prefix,
                         best_stage=min((s for s in STAGES if s in vals), key=lambda s: vals[s])))
    if not rows:
        print("no artifacts at n%d" % n); return 1
    print("ABLATION n%d (%d cells): prefix-minimum gain of each pipeline stage, from the banked artifacts (interim: see docstring)\n" % (n, len(rows)))
    print("%-9s %8s | %12s %12s %12s | %s" % ("stage", "coverage", "mean gain", "median gain", "cells gained", "gain as % of the floor value: mean / max (cell)"))
    for s in STAGES[1:]:
        have = [r for r in rows if r["has"][s]]
        g = [r["gain"][s] for r in have if r["gain"][s] is not None]
        if not have:
            print("%-9s %8s | %s" % (s, "0/%d" % len(rows), "not run at this size")); continue
        pct = [(100.0 * r["gain"][s] / r["floor"], r["cell"]) for r in have if r["gain"][s] is not None]
        mx = max(pct) if pct else (0.0, "-")
        print("%-9s %8s | %12.3f %12.3f %12s | %.2f%% / %.2f%% (%s)"
              % (s, "%d/%d" % (len(have), len(rows)), st.mean(g) if g else 0.0, st.median(g) if g else 0.0,
                 "%d" % sum(1 for x in g if x > 1e-6), st.mean(p for p, _ in pct) if pct else 0.0, mx[0], mx[1]))
    tot = [100.0 * (r["floor"] - r["final"]) / r["floor"] for r in rows]
    print("\n  floor -> final: mean %.2f%%, median %.2f%%, max %.2f%% of the floor value; best stage picked: %s"
          % (st.mean(tot), st.median(tot), max(tot), dict(sorted(((s, sum(1 for r in rows if r["best_stage"] == s)) for s in STAGES), key=lambda x: -x[1]))))
    if kt:
        for lab, flag in (("PROVEN", True), ("OPEN", False)):
            rs = [r for r in rows if r["proven"] == flag and r["theirs"]]
            if not rs: continue
            gf = [100.0 * (r["floor"] / r["theirs"] - 1) for r in rs]; ge = [100.0 * (r["final"] / r["theirs"] - 1) for r in rs]
            print("  %s (%d): gap to K median %+.2f%% (floor only) -> %+.2f%% (full pipeline); below K %d -> %d"
                  % (lab, len(rs), st.median(gf), st.median(ge), sum(1 for r in rs if r["floor"] < r["theirs"] - 0.05), sum(1 for r in rs if r["final"] < r["theirs"] - 0.05)))
    out = os.path.join(ROOT, "runs", "oracle", "tep_ablation_n%d.json" % n)
    json.dump(stamped(dict(size=n, stages=list(STAGES), rows=rows)), io.open(out, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
