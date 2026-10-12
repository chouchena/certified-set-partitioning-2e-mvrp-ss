"""Ablation claims derived ENTIRELY from the banked uniform-primal grid (pu_ng* artifacts) -- no
further solver runs. Three ablations, all read off the per-run `story`, `fleetcap_trigger`, and the
per-ng OVs that run_primal_uniform banks:

  1. STAGE ablation -- per pipeline stage (1-6 ceil, 8 refine, 9 alns, 11 select, 13 fleetcap,
     13b refine, 13c alns): on how many cells it was the/an accepted improver, and the total and
     mean objective it removed (sum of in_val-out_val over cells where it was accepted). Answers
     "what does each stage buy?".
  2. FLEET-CAP ablation -- fired / accepted counts, car-count reductions, mean gain. Answers
     "what does the fleet cap buy, and where?".
  3. ng-UNION ablation -- per cell best-over-ng vs the ng=10 baseline: #cells improved, mean/total
     gain, which ng won, AND the RT COST (wall + deterministic gurobi-Work) of the extra-ng runs,
     per ng value and per improved cell. Answers "what does the ng-union buy, and at what runtime
     cost?" -- the cost-benefit traceability behind the gate-removal decision (d713).

    python analysis/ablation_report.py                # all sizes present
    python analysis/ablation_report.py --sizes 10,20
"""
import argparse
import glob
import io
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p):
    d = json.load(io.open(p, encoding="utf-8")); r = d.get("rows", [d])
    return r[0] if isinstance(r, list) else r


def runs_for(size):
    """{cell: {ng: row}} over the banked pu_ng<g> artifacts for one size."""
    out = defaultdict(dict)
    for f in glob.glob(os.path.join(ROOT, "runs", "oracle", "pu_ng*_n%d.json" % size)) + \
             glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_solve_pu_ng*_n%d.json" % size)):
        m = re.search(r"pu_ng(\d+)_([A-Z]+\d+)_n%d" % size, os.path.basename(f))
        if m:
            out[m.group(2)][int(m.group(1))] = load(f)
    return out


def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", default="10,20,30,50,100")
    a = ap.parse_args(argv[1:]); sizes = [int(x) for x in a.sizes.split(",")]
    stage_n = defaultdict(int); stage_sum = defaultdict(float)   # stage -> cells moved / total removed
    fc_fired = fc_acc = 0; fc_gain = 0.0; fc_cars = []
    ng_improved = 0; ng_cells = 0; ng_gain = 0.0; ng_gain_abs = 0.0; ng_winner = defaultdict(int)
    ngrun_n = defaultdict(int); ngrun_wall = defaultdict(float); ngrun_work = defaultdict(float)
    ngwin_gain = defaultdict(float); extra_wall_total = 0.0; extra_work_total = 0.0; ng_trace = []
    for size in sizes:
        R = runs_for(size)
        if not R:
            continue
        for cell, byng in R.items():
            base = byng.get(10)
            if not base:
                continue
            # 1. STAGE ablation (from the ng=10 run's story -- the baseline pipeline)
            for st in base.get("story", []):
                if st.get("accepted") and st.get("in_val") and st.get("out_val"):
                    d = st["in_val"] - st["out_val"]
                    if d > 1e-6:
                        stage_n[st["stage"]] += 1; stage_sum[st["stage"]] += d
            # 2. FLEET-CAP ablation
            ft = base.get("fleetcap_trigger") or {}
            if ft.get("fired"):
                fc_fired += 1
                if ft.get("accepted"):
                    fc_acc += 1
                    if ft.get("cars") and ft.get("cars_after"):
                        fc_cars.append((ft["cars"], ft["cars_after"]))
            # 3. ng-UNION ablation -- with per-ng RT cost (wall + gurobi-Work) for full traceability
            ovs = {g: r.get("ov") for g, r in byng.items() if r.get("ov")}
            if 10 in ovs and len(ovs) >= 1:
                ng_cells += 1; best_ng = min(ovs, key=ovs.get); ng_winner[best_ng] += 1
                for g, rr in byng.items():            # RT of every banked ng run, by ng value
                    ngrun_n[g] += 1
                    ngrun_wall[g] += float(rr.get("wall_s") or 0.0)
                    ngrun_work[g] += float(rr.get("work") or 0.0)
                extra_wall = sum(float(byng[g].get("wall_s") or 0.0) for g in byng if g != 10)
                extra_work = sum(float(byng[g].get("work") or 0.0) for g in byng if g != 10)
                extra_wall_total += extra_wall; extra_work_total += extra_work
                if ovs[best_ng] < ovs[10] - 0.05:     # the union improved this cell over ng=10
                    gp = 100.0 * (1 - ovs[best_ng] / ovs[10])
                    ng_improved += 1; ng_gain += gp; ng_gain_abs += (ovs[10] - ovs[best_ng])
                    ngwin_gain[best_ng] += gp
                    ng_trace.append((size, cell, ovs[10], ovs[best_ng], best_ng, gp, extra_wall, extra_work))
    print("=== STAGE ablation (accepted improvements across the banked grid) ===")
    print("  %-14s %6s  %10s  %8s" % ("stage", "#cells", "total obj", "mean"))
    for s in sorted(stage_sum, key=lambda x: -stage_sum[x]):
        print("  %-14s %6d  %10.1f  %8.1f" % (s, stage_n[s], stage_sum[s], stage_sum[s] / stage_n[s]))
    print("\n=== FLEET-CAP ablation ===")
    print("  fired %d | accepted %d | car reductions: %s | mean gain %.1f"
          % (fc_fired, fc_acc, ", ".join("%d->%d" % (a_, b) for a_, b in fc_cars) or "none",
             (fc_gain / fc_acc) if fc_acc else 0))
    print("\n=== ng-UNION ablation (best-over-ng vs ng=10, with RT cost) ===")
    print("  cells %d | improved %d | mean gain on improved %.2f%% | total OV removed %.1f | winning ng: %s"
          % (ng_cells, ng_improved, (ng_gain / ng_improved) if ng_improved else 0,
             ng_gain_abs, dict(sorted(ng_winner.items()))))
    print("  extra-ng RT cost: %.0fs wall | %.1f gurobi-work  (mean %.0fs / %.1f-work per union cell over %d cells)"
          % (extra_wall_total, extra_work_total,
             (extra_wall_total / ng_cells) if ng_cells else 0,
             (extra_work_total / ng_cells) if ng_cells else 0, ng_cells))
    print("  per-ng run cost & wins:")
    for g in sorted(ngrun_n):
        print("    ng%-3d  %3d runs  wall %8.0fs  work %9.1f  |  won %2d cells  gain %+7.2f%%"
              % (g, ngrun_n[g], ngrun_wall[g], ngrun_work[g], ng_winner.get(g, 0), ngwin_gain.get(g, 0.0)))
    if ng_trace:
        print("  per-cell improvements (traceability: ng10 -> union, gain, extra-ng RT):")
        for (sz, c, o10, ou, bg, gp, ew, ewk) in sorted(ng_trace):
            print("    n%-3d %-6s  %9.3f -> %9.3f  via ng%-2d  (-%5.2f%%)  extra-RT %6.0fs / %7.1f-work"
                  % (sz, c, o10, ou, bg, gp, ew, ewk))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
