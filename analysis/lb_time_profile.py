"""Where the dual leg's seconds actually go: value, confirmation, proof.

WHY. The LB grid charges 58.5 hours across 135 cells and puts 11 of them OVER the 5,760 s
envelope before the primal starts. Before anyone proposes a budget cut, it is worth knowing what
the seconds buy. The artifacts already carry a per-iteration history -- `lp` and cumulative
`secs` on 131 of 135 cells -- so this costs nothing but reading them.

THE THREE-WAY SPLIT, and the middle one is the interesting column:

  VALUE         seconds until the LP first reaches its final value (within tol). This is the
                part that moves the number.
  CONFIRMATION  from there to the end of column generation. The LP has stopped moving; the
                solver is establishing that no further column prices out.
  PROOF         the ELEM pass. This is what makes the value citable at all -- an unconverged
                master's LP is an upper bound on the relaxation, not a lower bound on the
                problem (d427), so these seconds are not overhead, they are the certificate.

WHY "CONFIRMATION" IS NOT WASTE EITHER, and why this measurement cannot license a truncation.
The tracked `lp` DECREASES toward the true LP from above: every intermediate value is an upper
bound on the relaxation. So stopping early does not yield a weaker bound, it yields NO bound.
Cutting the CG leg is all-or-nothing. The truncatable instruments are the descent (its dual
bound is valid at any truncation point, easy_reduction_bound_proof step 0) and AB4 (0.023 s).
This file measures where the time goes; it does not argue that any of it can be skipped.

    python analysis/lb_time_profile.py
"""
import collections
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
from best_known import bound_artifacts
from bound_certificate import certified, ng_certified
from stamp import stamped

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
TOL = 1e-6


def pick(cell, size):
    best = None
    for q, e in bound_artifacts(cell, size):
        if e.get("lp_street") is None or e.get("primal_rounding") or e.get("drop"):
            continue
        if not (certified(e) or ng_certified(e)):
            continue
        if best is None or e["lp_street"] > best[1]["lp_street"]:
            best = (q, e)
    return best


def main():
    print("WHERE THE DUAL LEG'S SECONDS GO -- value / confirmation / proof\n")
    print("  %-6s %7s %9s %9s %9s %9s  %s"
          % ("size", "cells", "total_s", "value_s", "confirm_s", "proof_s", "share value/confirm/proof"))
    rows, per = [], collections.defaultdict(list)
    for size in (10, 20, 30, 50, 100):
        for cell in CELLS:
            got = pick(cell, size)
            if not got:
                continue
            q, d = got
            h = [x for x in (d.get("hist") or [])
                 if isinstance(x.get("lp"), (int, float)) and x.get("secs") is not None]
            if len(h) < 2:
                continue
            cg = [x for x in h if not str(x.get("tag", "")).strip().upper().startswith("ELEM")]
            el = [x for x in h if str(x.get("tag", "")).strip().upper().startswith("ELEM")]
            if not cg:
                continue
            final_lp = cg[-1]["lp"]
            t_val = next((float(x["secs"]) for x in cg if x["lp"] <= final_lp + 1e-6), None)
            t_cg = float(cg[-1]["secs"])
            t_tot = float(el[-1]["secs"]) if el else t_cg
            rec = dict(cell=cell, size=size, artifact=os.path.relpath(q, ROOT),
                       total_s=t_tot, value_s=t_val, confirm_s=max(0.0, t_cg - (t_val or 0.0)),
                       proof_s=max(0.0, t_tot - t_cg), iters=len(cg),
                       lp_final=final_lp,
                       certificate="elementary" if certified(d) else "ng")
            rows.append(rec); per[size].append(rec)
    for size in (10, 20, 30, 50, 100):
        g = per[size]
        if not g:
            continue
        tot = sum(r["total_s"] for r in g) or 1.0
        v, c, p = (sum(r["value_s"] or 0 for r in g), sum(r["confirm_s"] for r in g),
                   sum(r["proof_s"] for r in g))
        print("  n%-5d %7d %9.0f %9.0f %9.0f %9.0f  %4.0f%% / %4.0f%% / %4.0f%%"
              % (size, len(g), tot, v, c, p, 100 * v / tot, 100 * c / tot, 100 * p / tot))
    tot = sum(r["total_s"] for r in rows) or 1.0
    v = sum(r["value_s"] or 0 for r in rows)
    c = sum(r["confirm_s"] for r in rows)
    p = sum(r["proof_s"] for r in rows)
    print("\n  ALL %d cells: %.1f h total | value %.0f%%  confirmation %.0f%%  proof %.0f%%"
          % (len(rows), tot / 3600.0, 100 * v / tot, 100 * c / tot, 100 * p / tot))
    byc = collections.Counter(r["certificate"] for r in rows)
    print("  certificate class of the traces: %s" % dict(byc))
    el = [r for r in rows if r["certificate"] == "elementary"]
    ng = [r for r in rows if r["certificate"] == "ng"]
    for lbl, g in (("elementary", el), ("ng", ng)):
        if g:
            print("    %-11s proof share median %.0f%%  max %.0f%%"
                  % (lbl, statistics.median([100 * r["proof_s"] / (r["total_s"] or 1) for r in g]),
                     max(100 * r["proof_s"] / (r["total_s"] or 1) for r in g)))
    worst = sorted(rows, key=lambda r: -(r["confirm_s"] + r["proof_s"]))[:6]
    print("  most seconds after the LP stopped moving:")
    for r in worst:
        print("    %-7s n%-4d total %7.0f s = value %6.0f + confirm %6.0f + proof %6.0f  [%s]"
              % (r["cell"], r["size"], r["total_s"], r["value_s"] or 0, r["confirm_s"],
                 r["proof_s"], r["certificate"]))

    out = os.path.join(ROOT, "runs", "oracle", "lb_time_profile.json")
    d = stamped(dict(rows=rows), "analysis/lb_time_profile.py", "analysis/best_known.py",
                "analysis/bound_certificate.py")
    tmp = out + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, out)
    print("\n  wrote %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
