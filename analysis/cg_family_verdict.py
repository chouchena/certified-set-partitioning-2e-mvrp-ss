"""Family-level verdict for the TEP column-generation bound batch, against the pre-registered
table in validation/runaudits/TEP_cg_bound_27cells.md section 2.

Per cell: standing portfolio bound = max(proved MILP frontier via manuscript_numbers._frontier,
arithmetic AB4), the CG composed bound (street LP + the arithmetic water term), and whether the
composed bound is above the standing one. Family means of both; the new portfolio is
max(standing, composed). Verdict: DECISIVE if composed > standing on >= 20 of 27 cells AND every
family mean rises >= 25 percent; STRONG if >= 14 cells and >= 2 families rise >= 10 percent;
otherwise WEAK/NULL. Unproven cells count as not above.

    python analysis/cg_family_verdict.py
Writes runs/oracle/cg_family_verdict.json.
"""
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import manuscript_numbers as MN
import bks_n100 as B

K_DUAL = {"C": 1704.2, "R": 1056.4, "RC": 1249.5}      # K's derived family duals (d361)


def main():
    AB = MN._AB()
    rows = []
    for c in B.CELLS:
        fam = "RC" if c.startswith("RC") else c[0]
        ab = AB.get((c, 100))
        try:
            fr = MN._frontier(c, 100)[0]
        except Exception:
            fr = None
        standing = max(x for x in (fr, ab) if x is not None)
        f = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s.json" % c)
        r = json.load(io.open(f, encoding="utf-8")) if os.path.exists(f) else None
        proven = bool(r and r.get("proven"))
        comp = r["composed"] if proven else None
        # the finer-bucket artifact, when proven, is the tighter valid value
        for tag in ("_d10", "_d30"):
            g = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s.json" % (c, tag))
            if os.path.exists(g):
                q = json.load(io.open(g, encoding="utf-8"))
                if q.get("proven") and q["composed"] > (comp or 0):
                    comp = q["composed"]
        rows.append(dict(cell=c, fam=fam, frontier=fr, ab4=ab, standing=standing, composed=comp, proven=proven,
                         above=(comp is not None and comp > standing + 1e-6), new=max(standing, comp or 0)))
    print("%-6s %9s %9s %9s %9s %6s" % ("cell", "frontier", "AB4", "standing", "CG_comp", "above"))
    for r in rows:
        print("%-6s %9s %9.1f %9.1f %9s %6s" % (r["cell"], "%.1f" % r["frontier"] if r["frontier"] else "-", r["ab4"], r["standing"],
                                              "%.1f" % r["composed"] if r["composed"] else "unproven", "yes" if r["above"] else "no"))
    n_above = sum(1 for r in rows if r["above"])
    fams = {}
    for f in ("C", "R", "RC"):
        rs = [r for r in rows if r["fam"] == f]
        s = st.mean(r["standing"] for r in rs); n = st.mean(r["new"] for r in rs)
        fams[f] = dict(standing=s, new=n, rise_pct=100.0 * (n / s - 1), vs_k_dual=n / K_DUAL[f], cells_above=sum(1 for r in rs if r["above"]), n=len(rs))
        print("family %-3s standing mean %8.1f -> new portfolio mean %8.1f (+%.1f%%), %.3f x K's dual, above on %d of %d"
              % (f, s, n, fams[f]["rise_pct"], fams[f]["vs_k_dual"], fams[f]["cells_above"], len(rs)))
    rises = [fams[f]["rise_pct"] for f in fams]
    if n_above >= 20 and all(x >= 25 for x in rises):
        verdict = "DECISIVE"
    elif n_above >= 14 and sum(1 for x in rises if x >= 10) >= 2:
        verdict = "STRONG"
    else:
        verdict = "WEAK/NULL"
    print("\ncells above the standing portfolio: %d of 27 -> VERDICT %s (section 2 of TEP_cg_bound_27cells.md)" % (n_above, verdict))
    json.dump(dict(rows=rows, families=fams, n_above=n_above, verdict=verdict), io.open(os.path.join(ROOT, "runs", "oracle", "cg_family_verdict.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
