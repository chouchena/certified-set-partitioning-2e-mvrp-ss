"""n50 longer-than-budget sensitivity table: paper/tables/n50_longrt.tex.

The fair-budget consolidation (d716/d717) drops any ng run that pushes a cell's cumulative wall past
the 5760 s cap. This table re-admits those over-budget runs (the full ng-union) and lists the cells
whose incumbent improves, with the budget multiple the full union reaches. Mean effect is reported in
the text as longrt-n50.delta-pp; this table is the per-cell detail.

Read-only re-slice of the banked pu_ng n50 artifacts. Asserts its aggregate (delta, improved count)
equals paper/numbers.json:longrt-n50 so the table cannot drift from the text. Provenance sidecar via
stamp.stamped -- refused if its sources are uncommitted.
"""
import os, sys, json, glob, datetime
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

CAP = 5760.0
TABDIR = os.path.join(ROOT, "paper", "tables")
NUMS = json.load(open(os.path.join(ROOT, "paper", "numbers.json")))["longrt-n50"]["value"]


def _row(ng, cell):
    p = glob.glob(os.path.join(ROOT, "runs/oracle/tep_solve_pu_ng%d_%s_n50.json" % (ng, cell)))
    if not p:
        return None
    d = json.load(open(p[0], encoding="utf-8"))
    return d.get("rows", [d])[0]


cells = sorted({os.path.basename(f).split("_")[4]
                for f in glob.glob(os.path.join(ROOT, "runs/oracle/tep_solve_pu_ng10_*_n50.json"))})
fitg, fullg, improved = [], [], []
for c in cells:
    runs = {ng: _row(ng, c) for ng in (10, 5, 25)}
    if runs[10] is None or not runs[10].get("lb"):
        continue
    lb = runs[10]["lb"]
    cum, fit, full, fullcum = 0.0, [], [], 0.0
    for ng in (10, 5, 25):
        r = runs[ng]
        if r is None or r.get("ov") is None:
            continue
        w = r.get("wall_s") or 0.0
        full.append(r["ov"]); fullcum += w
        if ng == 10 or cum + w <= CAP:
            fit.append(r["ov"]); cum += w
    if not fit or not full:
        continue
    fo, uo = min(fit), min(full)
    fg, ug = 100.0 * (fo - lb) / fo, 100.0 * (uo - lb) / uo
    fitg.append(fg); fullg.append(ug)
    if uo < fo - 1e-6:
        improved.append((c, fg, ug, fullcum / CAP))

delta = st.mean(fitg) - st.mean(fullg)
assert len(improved) == int(NUMS["cells-improved"]), (len(improved), NUMS["cells-improved"])
assert abs(delta - float(NUMS["delta-pp"])) < 0.005, (delta, NUMS["delta-pp"])
assert abs(max(m for *_, m in improved) - float(NUMS["max-mult"])) < 0.005

TEX = ([r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}lrrr}", r"\toprule",
        r"cell & gap at fair budget (\%) & gap at full budget (\%) & budget multiple \\",
        r"\midrule"]
       + [r"%s & %.2f & %.2f & %.2f \\" % (c, fg, ug, m)
          for c, fg, ug, m in sorted(improved)]
       + [r"\bottomrule", r"\end{tabular*}"])
tex = "\n".join(TEX) + "\n"

os.makedirs(TABDIR, exist_ok=True)
p = os.path.join(TABDIR, "n50_longrt.tex")
open(p, "w", encoding="utf-8").write(tex)
prov = dict(table="n50_longrt", generated_by="analysis/tab_n50_longrt.py",
            sources=["runs/oracle/tep_solve_pu_ng{5,10,25}_*_n50.json (ov, wall_s, lb)",
                     "paper/numbers.json:longrt-n50 (asserted equal)"],
            outputs=[os.path.relpath(p, ROOT)],
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            python=sys.version.split()[0])
json.dump(stamped(prov, __file__), open(os.path.join(TABDIR, "n50_longrt.prov.json"), "w"),
          indent=1, default=str)
print("improved cells:", [(c, round(fg, 2), round(ug, 2), round(m, 2)) for c, fg, ug, m in sorted(improved)])
print("mean delta pp:", round(delta, 3), " wrote paper/tables/n50_longrt.tex + .prov.json")
