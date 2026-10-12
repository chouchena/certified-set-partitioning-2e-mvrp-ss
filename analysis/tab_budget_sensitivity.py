"""Budget-sensitivity table (#41/d754-759): paper/tables/budget_sensitivity.tex.

One panel per size (|C| = 50, 100). Rows sweep the hardware factor f over the common grid
{2.5, 5, 7.5, 10, 12.5} (2.5-steps up to the n100 certification ceiling f_max = 12.6); each cell's
budget is K_cap/f with K_cap = 14400 s. Columns: f, cap (s), mean certified LB, mean incumbent
(OV), opt-gap (OV-LB)/OV %, OV degradation %, gap degradation pp -- the last two relative to the
reported point f = 2.5.

The numbers are a read-only re-slice of the banked ng10 trajectory, computed with the SAME helpers
the \\num pipeline uses (_cons, _ov_at_cap in manuscript_numbers), so the table cannot drift from
the text. The LB is deterministic-tick-bounded, hence invariant in f (degradation 0 at every row).
The script asserts its f=12.5 n100 row equals paper/numbers.json budget-sens (n100-derived-mean,
ov-degrade-max-pct, gap-degrade-max-pp) and its f=2.5 rows equal n{50,100}-base-mean.

Emits the tabular only (the section supplies \\begin{table}, caption and label), with a
provenance sidecar via stamp.stamped -- refused if its sources are uncommitted.
"""
import os
import sys
import json
import datetime
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import manuscript_numbers as M
from stamp import stamped

KCAP = 14400.0
FGRID = [2.5, 5.0, 7.5, 10.0, 12.5]
TABDIR = os.path.join(ROOT, "paper", "tables")
NUMS = json.load(open(os.path.join(ROOT, "paper", "numbers.json")))["budget-sens"]["value"]


def grid(size):
    """Per-f (cap, mean LB, mean OV, gap%, OV-deg%, gap-deg pp), re-sliced from the ng10 story."""
    rows = M._cons(size)
    base_cap = KCAP / 2.5
    lbd, base_ov = {}, {}
    for r in rows:
        lb = r.get("our_lb")
        if not lb:
            continue
        ob = M._ov_at_cap(r["cell"], size, base_cap)
        if ob is None:
            continue
        lbd[r["cell"]], base_ov[r["cell"]] = lb, ob
    cells = sorted(lbd)
    base_gap = st.mean([100.0 * (base_ov[c] - lbd[c]) / base_ov[c] for c in cells])
    out = []
    for f in FGRID:
        cap = KCAP / f
        ov = {c: M._ov_at_cap(c, size, cap) for c in cells}
        mlb = st.mean([lbd[c] for c in cells])
        mov = st.mean([ov[c] for c in cells])
        gap = st.mean([100.0 * (ov[c] - lbd[c]) / ov[c] for c in cells])
        ovdeg = st.mean([100.0 * (ov[c] - base_ov[c]) / base_ov[c] for c in cells])
        out.append((f, cap, mlb, mov, gap, ovdeg, gap - base_gap))
    return out


g50, g100 = grid(50), grid(100)

# guard: the extreme row and the baseline must equal the registered \num values (no drift)
assert abs(g100[0][4] - float(NUMS["n100-base-mean"])) < 0.05, g100[0]
assert abs(g50[0][4] - float(NUMS["n50-base-mean"])) < 0.05, g50[0]
assert abs(g100[-1][4] - float(NUMS["n100-derived-mean"])) < 0.05, g100[-1]
assert abs(g100[-1][5] - float(NUMS["ov-degrade-max-pct"])) < 0.05, g100[-1]
assert abs(g100[-1][6] - float(NUMS["gap-degrade-max-pp"])) < 0.05, g100[-1]


def rows_tex(g):
    L = []
    for f, cap, mlb, mov, gap, ovdeg, gapdeg in g:
        L.append(r"%.1f & %.0f & %.0f & %.0f & %.1f & %.2f & %.2f \\" %
                 (f, cap, mlb, mov, gap, ovdeg, gapdeg))
    return L


TEX = (
    [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}rrrrrrr}", r"\toprule",
     r"$f$ & cap (s) & mean LB & mean OV & gap (\%) & OV deg.\ (\%) & gap deg.\ (pp) \\",
     r"\midrule",
     r"\multicolumn{7}{l}{\emph{$|C| = 50$}} \\"]
    + rows_tex(g50)
    + [r"\midrule", r"\multicolumn{7}{l}{\emph{$|C| = 100$}} \\"]
    + rows_tex(g100)
    + [r"\bottomrule", r"\end{tabular*}"]
)
tex = "\n".join(TEX) + "\n"

os.makedirs(TABDIR, exist_ok=True)
p = os.path.join(TABDIR, "budget_sensitivity.tex")
open(p, "w", encoding="utf-8").write(tex)
prov = dict(table="budget_sensitivity", generated_by="analysis/tab_budget_sensitivity.py",
            sources=["runs/oracle/tep_uniform_n{50,100}.json (our_lb; _cons)",
                     "runs/oracle/tep_solve_pu_ng10_*_n{50,100}.json (story; _ov_at_cap)",
                     "runs/oracle/tep_solve_frzdual2_*_n{50,100}.json (dual-derived fallback)",
                     "paper/numbers.json:budget-sens (asserted equal)"],
            outputs=[os.path.relpath(p, ROOT)],
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            python=sys.version.split()[0])
json.dump(stamped(prov, __file__), open(os.path.join(TABDIR, "budget_sensitivity.prov.json"), "w"),
          indent=1, default=str)
print("n50 :", [(r[0], round(r[4], 1), round(r[6], 2)) for r in g50])
print("n100:", [(r[0], round(r[4], 1), round(r[6], 2)) for r in g100])
print("wrote paper/tables/budget_sensitivity.tex + .prov.json")
