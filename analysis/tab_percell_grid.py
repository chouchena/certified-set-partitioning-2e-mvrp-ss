"""Per-cell grid appendix (#53, d775): paper/tables/percell_grid.tex.

One tabular per size (|C| = 10, 20, 30, 50, 100), 27 cells each, grouped by family. Columns:
  Cell | OV | LB | gap (%) | cert | RT (s) | K gap (%) | flag
where
  OV, LB, RT  -- recap_grid_vs_k.our_union (the budget-fit union the body reports); LB = the
                reported max(certified LP, AB4).
  gap         -- (OV - LB)/OV, the body's convention.
  cert        -- the honest certificate class of the reported bound: AB where the closed-form
                arithmetic bound carries (ab4 > lb_composed, the 11 smallest instances at |C|=10),
                else ng (the ng-route LP certificate; NOT elementary -- the frozen grid is
                ng-certified at every size, matching the artifacts).
  K gap       -- K's published per-instance gap at |C| = 10/20/30 (Table 3); '--' at |C| = 50/100
                where K publish pooled / family aggregates only.
  flag        -- P proven (K report a zero gap: calibration), D dual-derived (refinement not
                applied: R204/R208 at |C|=100), blank otherwise (open/competition).

Read-only over the committed evidence. Asserts AB-carries total == portfolio.ab-carries-cells and
the |C|=50/100 mean gaps == optgap, so the appendix cannot drift from the body.
"""
import os
import sys
import glob
import json
import math
import statistics as st

EPS = 1e-6  # pricing tolerance; the certified-bound dual correction is EPS*|C| (Lemma tepcert)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import recap_grid_vs_k as R

NUMS = json.load(open(os.path.join(ROOT, "paper", "numbers.json")))
SIZES = [10, 20, 30, 50, 100]
FAMS = (("C", lambda c: c.startswith("C")),
        ("R", lambda c: c.startswith("R") and not c.startswith("RC")),
        ("RC", lambda c: c.startswith("RC")))


def _frz(cell, size):
    f = glob.glob(os.path.join(ROOT, "runs/oracle/tep_solve_frzdual2_%s_n%d.json" % (cell, size)))
    return json.load(open(f[0])).get("rows", [{}])[0] if f else {}


def _proven(size):
    d = json.load(open(os.path.join(ROOT, "runs/oracle/tep_uniform_n%d.json" % size)))
    return {r["cell"]: bool(r.get("proven")) for r in d["rows"]}


def cert_of(cell, size):
    r = _frz(cell, size)
    ab, lc = r.get("ab4"), r.get("lb_composed")
    if ab is not None and lc is not None and float(ab) > float(lc) + 1e-6:
        return "AB"
    return "ng"


def safe_lb(cell, size, lb):
    """Displayed lower bound, rounded DOWN so the printed value is itself a valid lower bound.

    The certified value carries an EPS*|C| dual correction where the LP certificate carries (none
    where the closed-form arithmetic bound carries; it is exact), per Lemma~\\ref{lem:tepcert}. We
    subtract that correction and then FLOOR to one decimal, so the printed bound never rounds up past
    the certified value -- a bound displayed to nearest could exceed it (e.g. 355.559 -> 355.6).
    """
    r = _frz(cell, size)
    ab, lc = float(r.get("ab4") or 0.0), float(r.get("lb_composed") or 0.0)
    ab_carries = ab > lc + 1e-9
    safe = lb - (0.0 if ab_carries else EPS * size)
    return math.floor(safe * 10.0) / 10.0


def rows_for(size):
    u = R.our_union(size)
    prov = _proven(size)
    kpc = R.k_percell(size) if size in (10, 20, 30) else None
    out = []
    ab_n = 0
    for fam, pred in FAMS:
        for c in [x for x in sorted(u) if pred(x)]:
            ov, lb, rt, flags = u[c][0], u[c][1], u[c][2], u[c][3]
            lb = safe_lb(c, size, lb)          # floored valid lower bound (Lemma tepcert); display
            gap = 100.0 * (ov - lb) / ov       # gap derived from the floored bound (conservative)
            cert = cert_of(c, size)
            ab_n += (cert == "AB")
            kg = "--"
            if kpc and kpc.get(c):
                kov, klb = kpc[c]
                kg = "%.1f" % (100.0 * (kov - klb) / kov)
            flag = "D" if flags == ["derived"] else ("P" if prov.get(c) else "")
            out.append((fam, c, ov, lb, gap, cert, rt, kg, flag))
    return out, ab_n


panels = {}
tot_ab = 0
for s in SIZES:
    rows, ab_n = rows_for(s)
    panels[s] = rows
    tot_ab += ab_n

# guards: the appendix cannot drift from the body
assert tot_ab == int(NUMS["portfolio"]["value"]["ab-carries-cells"]), tot_ab
for s in (50, 100):
    g = st.mean([r[4] for r in panels[s]])
    assert abs(g - float(NUMS["optgap"]["value"]["n%d-competition-mean" % s])) < 0.1, (s, g)


def panel_tex(size, rows):
    L = [r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}llrrrcrrc}", r"\toprule",
         r"& Cell & OV & LB & gap(\%) & cert & RT(s) & K gap(\%) & flag \\", r"\midrule"]
    cur = None
    for fam, c, ov, lb, gap, cert, rt, kg, flag in rows:
        fam_cell = (r"\multirow{%d}{*}{%s}" % (sum(1 for x in rows if x[0] == fam), fam)) if fam != cur else ""
        cur = fam
        L.append(r"%s & %s & %.1f & %.1f & %.1f & %s & %.0f & %s & %s \\"
                 % (fam_cell, c, ov, lb, gap, cert, rt, kg, flag))
    L += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(L)


# Each size is emitted as a NUMBERED table float (reviewer 6, d784): a \caption and \label per
# panel, the former carrying the per-size note and the legend. The appendix input no longer sets
# the font, so each float sizes itself with \footnotesize.
blocks = []
for s in SIZES:
    knote = "K gap is per-instance (their Table~3)." if s in (10, 20, 30) \
        else "K publish only pooled/family aggregates at this size, so K gap is omitted (`--'); see Section~\\ref{sec:dual-results}."
    cap = (r"Per-cell results at $|C| = %d$: objective value (OV), certified lower bound (LB), "
           r"optimality gap $(\mathrm{OV}-\mathrm{LB})/\mathrm{OV}$, certificate class, bound-leg "
           r"runtime (s) and, where published, K's per-instance gap. The LB is the certified value "
           r"less its $\varepsilon\lvert C\rvert$ dual correction, rounded \emph{down} to one decimal "
           r"so the printed figure is itself a valid lower bound (Lemma~\ref{lem:tepcert}); the gap is "
           r"computed from that figure. %s Certificate: ng = ng-route "
           r"LP certificate, AB = closed-form arithmetic bound carries. Flags: P proven "
           r"(calibration), D dual-derived." % (s, knote))
    blocks.append("\n".join([r"\begin{table}[htbp]", r"\centering",
                             r"\caption{%s}\label{tab:percell-%d}" % (cap, s),
                             r"\footnotesize", panel_tex(s, panels[s]), r"\end{table}"]))
tex = "\n\n".join(blocks) + "\n"

TABDIR = os.path.join(ROOT, "paper", "tables")
os.makedirs(TABDIR, exist_ok=True)
p = os.path.join(TABDIR, "percell_grid.tex")
open(p, "w", encoding="utf-8").write(tex)

import datetime
from stamp import stamped
prov = dict(table="percell_grid", generated_by="analysis/tab_percell_grid.py",
            sources=["runs/oracle/tep_uniform_n*.json (OV/LB/proven)",
                     "runs/oracle/tep_solve_pu_ng*/frzdual2_* via recap_grid_vs_k.our_union (RT/flags)",
                     "runs/oracle/tep_solve_frzdual2_* (ab4/lb_composed for cert)",
                     "data/karademir2025/k_reference.json (K per-cell gap n10/20/30)",
                     "paper/numbers.json:portfolio,optgap (asserted equal)"],
            outputs=[os.path.relpath(p, ROOT)],
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            python=sys.version.split()[0])
json.dump(stamped(prov, __file__), open(os.path.join(TABDIR, "percell_grid.prov.json"), "w"),
          indent=1, default=str)
print("AB-carries total:", tot_ab, "| wrote paper/tables/percell_grid.tex (%d-size panels)" % len(SIZES))
