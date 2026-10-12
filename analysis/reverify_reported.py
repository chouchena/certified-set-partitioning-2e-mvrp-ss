r"""Area 6 -- independent joint re-verification of every REPORTED incumbent (d793). READ-ONLY.

The banked tep_reverify_all.json is older than the current frozen grid, so this re-runs the joint
verifier over exactly the incumbents the manuscript reports (the budget-fit union of
recap_grid_vs_k.our_union: the min-OV admitted pu_ng run per cell, or the dual-derived frzdual2
incumbent where no primal artifact exists). For each it loads the instance, reconstructs and checks
the FULL joint solution against every transcribed constraint (street routing/timing, vessel
routing/windows, street-vessel coincidence at transfers, satellite spacing, fleet), and RECOMPUTES
the objective, asserting it equals the reported one. No solver runs -- verification only.

verify_for_engine(expect="any") is used so .ok reflects joint FEASIBILITY (the production-provenance
gate is a separate concern, covered by the release gate and cert_audit). Writes
validation/AREA6_INCUMBENT_REVERIFY.md and exits nonzero on any infeasible or mis-costed incumbent.
"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
import recap_grid_vs_k as R

SIZES = (10, 20, 30, 50, 100)
COST_TOL = 1e-4   # objective match, tightened from 1e-2 (referee #5): feasibility is v.ok, separate


def reported_row(cell, size):
    """Replicate our_union's selection and return (row_with_solution, tag, source_basename)."""
    byng = {}
    for p in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_solve_pu_ng*_%s_n%d.json" % (cell, size))):
        m = re.search(r"pu_ng(\d+)_%s_n%d\.json$" % (cell, size), os.path.basename(p))
        if not m:
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        r = d.get("rows", [d])
        byng[int(m.group(1))] = (r[0] if isinstance(r, list) else r, os.path.basename(p))
    base = byng.get(10)
    if not base or base[0].get("ov") is None:
        fp = os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (cell, size))
        if os.path.exists(fp):
            dd = json.load(io.open(fp, encoding="utf-8"))
            dd = dd.get("rows", [dd])
            dd = dd[0] if isinstance(dd, list) else dd
            if dd.get("ov") is not None:
                return dd, "derived", os.path.basename(fp)
        return None, None, None
    cum = 0.0
    admitted = {}
    for g in R.NG_ORDER:
        rp = byng.get(g)
        if rp is None or rp[0].get("ov") is None:
            continue
        w = float(rp[0].get("wall_s") or 0.0)
        if g != 10 and cum + w > R.BUDGET + 1e-6:
            continue
        cum += w
        admitted[g] = rp
    bestg = min(admitted, key=lambda g: admitted[g][0]["ov"])
    return admitted[bestg][0], "ng%d" % bestg, admitted[bestg][1]


def main():
    rows, problems = [], []
    for size in SIZES:
        prox = k_proximity(size)
        for cell in R.CELLS:
            row, tag, src = reported_row(cell, size)
            if row is None:
                continue
            sol = row.get("solution")
            ov = row.get("ov")
            if sol is None or ov is None:
                problems.append("%s n%d: no solution/ov on the reported row" % (cell, size))
                continue
            inst = V.load_instance(cell, size, prox)
            try:
                v = V.verify_for_engine(inst, sol, cell=cell, size=size, proximity=prox,
                                        label="area6", expect="any")
                ok = bool(v.ok)
                rec = float(getattr(v, "recomputed_obj", None) or 0.0)
                nviol = len(getattr(v, "violations", []) or [])
            except Exception as e:
                problems.append("%s n%d: verifier raised %s" % (cell, size, e))
                continue
            cost_ok = abs(rec - float(ov)) < COST_TOL * max(1.0, abs(float(ov)))
            rows.append({"cell": cell, "size": size, "tag": tag, "source": src, "ov": float(ov),
                         "recomputed": rec, "ok": ok, "nviol": nviol, "cost_ok": cost_ok})
            if not ok:
                problems.append("%s n%d (%s): INFEASIBLE, %d violation(s)" % (cell, size, tag, nviol))
            if not cost_ok:
                problems.append("%s n%d (%s): recomputed %.4f != reported %.4f"
                                % (cell, size, tag, rec, float(ov)))

    # ---- write the audit ---------------------------------------------------------------------
    lines = ["# Area 6 -- joint re-verification of every reported incumbent", "",
             "> Evidence for the \"Feasible solutions\" acceptance row (d793). Generated READ-ONLY by",
             "> `analysis/reverify_reported.py`: the joint verifier (`verifier3`, street + vessel + sync +",
             "> spacing + fleet) run over exactly the incumbents `recap_grid_vs_k.our_union` reports, with",
             "> the objective recomputed and checked against the reported value. No solver runs.", ""]
    by_size = {}
    for r in rows:
        by_size.setdefault(r["size"], []).append(r)
    for size in SIZES:
        rs = by_size.get(size)
        if not rs:
            continue
        npass = sum(1 for r in rs if r["ok"] and r["cost_ok"])
        lines += ["## $|C| = %d$  (%d incumbents; %d feasible with matching cost)"
                  % (size, len(rs), npass), "",
                  "| cell | source | reported OV | recomputed | feasible | viol | cost matches |",
                  "|------|--------|-------------|-----------|----------|------|--------------|"]
        for r in sorted(rs, key=lambda x: x["cell"]):
            lines.append("| %s | %s | %.3f | %.3f | %s | %d | %s |"
                         % (r["cell"], r["tag"], r["ov"], r["recomputed"],
                            "yes" if r["ok"] else "**NO**", r["nviol"],
                            "yes" if r["cost_ok"] else "**NO**"))
        lines.append("")
    npass = sum(1 for r in rows if r["ok"] and r["cost_ok"])
    lines += ["## Summary", "",
              "- incumbents re-verified: **%d**" % len(rows),
              "- feasible with recomputed cost matching the reported value: **%d**" % npass,
              "", ("**EVERY REPORTED INCUMBENT IS A FEASIBLE JOINT SOLUTION WITH MATCHING COST.**"
                   if not problems else "**VIOLATIONS:**")]
    for p in problems:
        lines.append("- " + p)
    out = os.path.join(ROOT, "validation", "AREA6_INCUMBENT_REVERIFY.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")

    # MANIFEST (referee #5): link each reported cell to the exact source artifact + its verdict, so the
    # packaged solutions can be checked one-to-one against the manuscript. The objective tolerance is
    # COST_TOL (1e-4 relative), separate from the feasibility/timing checks inside the verifier.
    manifest = {"cost_tol_relative": COST_TOL,
                "note": "source is the runs/oracle artifact our_union selects per cell; its `solution` "
                        "field is the reported incumbent (packaged under certificates/). recomputed is "
                        "verifier3's independent objective.",
                "cells": [{"cell": r["cell"], "size": r["size"], "source": r["source"],
                           "selection": r["tag"], "reported_ov": round(r["ov"], 6),
                           "recomputed_obj": round(r["recomputed"], 6), "feasible": r["ok"],
                           "cost_match": r["cost_ok"]} for r in rows]}
    mpath = os.path.join(ROOT, "validation", "incumbent_manifest.json")
    json.dump(manifest, open(mpath, "w"), indent=1, sort_keys=True)
    print("wrote %s (%d incumbents, %d clean, %d problem(s))"
          % (os.path.relpath(out), len(rows), npass, len(problems)))
    print("wrote %s (%d cells, objective tolerance %.0e relative)"
          % (os.path.relpath(mpath), len(rows), COST_TOL))
    for p in problems[:20]:
        print("  PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
