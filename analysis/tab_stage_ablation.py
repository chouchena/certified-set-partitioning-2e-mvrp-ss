"""Per-stage ablation (the online resource §6.4 promises): paper/tables/stage_ablation.tex.

For each instance size, the mean marginal objective reduction contributed by each primal stage,
read from the banked pu_ng10 trajectory ('story'): construction (the best-of ceil candidate over
the floor seed), then the improvement stages refine, ALNS and the master select. Floor is the
seed baseline (0 by definition) and is omitted. Over the cells where the primal ran (R204/R208 at
|C|=100 are refinement-not-applied, so n100 is 25 cells). Read-only; sums to the net primal gain.
"""
import os
import sys
import glob
import json
import datetime
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

SIZES = [10, 20, 30, 50, 100]
STAGES = ["1-6 ceil", "8 refine", "9 alns", "11 select"]
LABEL = {"1-6 ceil": "construct", "8 refine": "refine", "9 alns": "ALNS", "11 select": "select"}


def size_row(size):
    per = {s: [] for s in STAGES}
    tot = []
    nc = 0
    for f in glob.glob(os.path.join(ROOT, "runs/oracle/tep_solve_pu_ng10_*_n%d.json" % size)):
        r = json.load(open(f)).get("rows", [{}])[0]
        story = r.get("story") or []
        best = None
        start = None
        nc += 1
        for s in story:
            ov = s.get("out_val")
            nm = s.get("stage")
            if ov is None:
                continue
            ov = float(ov)
            if best is None:
                best = ov
                start = ov
                continue
            red = 100.0 * (best - ov) / best if ov < best else 0.0
            if nm in per:
                per[nm].append(red)
            if ov < best:
                best = ov
        if start:
            tot.append(100.0 * (start - best) / start)
    return nc, {s: (st.mean(per[s]) if per[s] else 0.0) for s in STAGES}, (st.mean(tot) if tot else 0.0)


rows = [(s,) + size_row(s) for s in SIZES]

L = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}rrrrrr}", r"\toprule",
     r"$|C|$ & cells & construct & refine & ALNS & select \\",
     r"\midrule"]
for size, nc, per, tot in rows:
    L.append(r"%d & %d & %.2f & %.2f & %.2f & %.2f \\"
             % (size, nc, per["1-6 ceil"], per["8 refine"], per["9 alns"], per["11 select"]))
L += [r"\bottomrule", r"\end{tabular*}"]
tex = "\n".join(L) + "\n"

TABDIR = os.path.join(ROOT, "paper", "tables")
os.makedirs(TABDIR, exist_ok=True)
p = os.path.join(TABDIR, "stage_ablation.tex")
open(p, "w", encoding="utf-8").write(tex)
prov = dict(table="stage_ablation", generated_by="analysis/tab_stage_ablation.py",
            sources=["runs/oracle/tep_solve_pu_ng10_*_n*.json (story out_val per stage)"],
            outputs=[os.path.relpath(p, ROOT)],
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            python=sys.version.split()[0])
json.dump(stamped(prov, __file__), open(os.path.join(TABDIR, "stage_ablation.prov.json"), "w"),
          indent=1, default=str)
print("per-stage (%% reduction):", [(r[0], round(r[3], 2)) for r in rows])
print("wrote paper/tables/stage_ablation.tex")
