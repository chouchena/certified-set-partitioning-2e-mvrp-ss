"""What a per-run cap costs when the ELEM pass can be truncated and AB4 is always the floor.

WHY (author, 2026-09-29). Two corrections to the earlier cap simulation, both of which made it
far too pessimistic:

  1. IT KILLED THE WHOLE RUN when secs > cap. But the value AND a valid ng certificate are both
     complete at cg_end -- the ng pass IS the column-generation loop. Only the ELEMENTARY
     upgrade needs the long tail. On R208 n50 that tail is 5,796 s of a 6,996 s run: capping it
     costs the class, not the bound.
  2. IT IGNORED AB4 AS A FLOOR. AB4 is deterministic arithmetic, 0.023 s median, valid with no
     certificate at all. It always fits any cap, so no cell can fall below it.

THE POLICY SIMULATED, per cell, at cap T:
     AB4                                          always available -> the floor
     a TEP run with secs   <= T                   full value, at its own certificate class
     a TEP run with cg_end <= T < secs            value at cg_end, ng class, IF the artifact's
                                                  ng pass satisfies ng_certified
     otherwise                                    that run contributes nothing
     reported = max(AB4, best surviving TEP)

WHAT IS AND IS NOT SIMULATED. The values are the ones the runs actually produced; truncating the
ELEM pass does not change the CG trajectory that preceded it, so the cg_end value is exactly what
that run had at that moment. What this CANNOT model is a re-run under a cap generating a
different column sequence. It is a replay of observed runs, not a prediction.

SCOPE: banked dual only (finished before 2026-09-29), K-proven cells excluded -- where K proved
the optimum our lower bound means nothing.

    python analysis/lb_cap_with_ab_floor.py --caps 600 900 1500 2100
"""
import argparse
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
from bound_certificate import certified, ng_certified, best_valid
from k_comparison import proven_cells
from lb_method_ablation import method, CELLS
from stamp import stamped
import bound_source as BS

CUT = "2026-09-29"


def phases(d):
    """(value_at_cg_end, cg_end_secs, total_secs) from the stored history."""
    h = [x for x in (d.get("hist") or [])
         if isinstance(x.get("lp"), (int, float)) and x.get("secs") is not None]
    cg = [x for x in h if not str(x.get("tag", "")).strip().upper().startswith("ELEM")]
    if not cg:
        return None
    return float(cg[-1]["lp"]), float(cg[-1]["secs"]), float(d.get("secs") or cg[-1]["secs"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caps", nargs="*", type=float, default=[600, 900, 1500, 2100])
    a = ap.parse_args()

    # collect once
    cells = []
    for size in (20, 30, 50, 100):
        prov = set(proven_cells(size))
        for c in [x for x in CELLS if x not in prov]:
            runs, ab = [], None
            for q, d in bound_artifacts(c, size):
                if (d.get("_finished") or "")[:10] >= CUT:
                    continue
                if d.get("lp_street") is None or d.get("primal_rounding") or d.get("drop"):
                    continue
                if not (certified(d) or ng_certified(d)):
                    continue
                p = phases(d)
                if not p:
                    continue
                runs.append(dict(method=method(d), full=float(d["lp_street"]),
                                 cg_val=p[0], cg_s=p[1], total_s=p[2],
                                 ng_ok=bool(ng_certified(d)),
                                 cls="elementary" if certified(d) else "ng"))
            if not runs:
                continue
            water = BS._ab(c, size)
            ab = float(water["ab4"]) if water and water.get("ab4") is not None else None
            cells.append(dict(cell=c, size=size, runs=runs, ab4=ab,
                              best=max(r["full"] for r in runs)))

    print("CAP SIMULATION -- ELEM pass truncatable, AB4 as the floor")
    print("banked dual only, K-proven excluded | %d cells\n" % len(cells))
    print("  %6s %7s %8s %9s %11s %11s %9s %10s"
          % ("cap_s", "no loss", "weaker", "no bound", "median loss", "worst loss",
             "downgrade", "wall_h"))
    out = []
    for cap in a.caps:
        full = weak = none = down = 0
        losses, wall = [], 0.0
        detail = []
        for x in cells:
            cands = []
            for r in x["runs"]:
                if r["total_s"] <= cap:
                    cands.append((r["full"], r["cls"], r["method"], min(r["total_s"], cap)))
                elif r["cg_s"] <= cap and r["ng_ok"]:
                    cands.append((r["cg_val"], "ng (ELEM truncated)", r["method"], cap))
                # else: contributes nothing
                wall += min(r["total_s"], cap)
            if x["ab4"] is not None:
                cands.append((x["ab4"], "ab4", "ab4", 0.023))
            # at equal value the stronger class wins (bound_certificate.best_valid, 2026-09-30)
            v, cls, m, _s = best_valid(cands, value=lambda t: t[0], klass=lambda t: t[1])
            loss = x["best"] - v
            if loss <= 1e-6:
                full += 1
            else:
                weak += 1
                losses.append(100.0 * loss / x["best"])
                detail.append((x["cell"], x["size"], x["best"], v, cls,
                               100.0 * loss / x["best"]))
            if cls.startswith("ng (ELEM"):
                down += 1
            if v <= (x["ab4"] or -1) + 1e-9 and x["ab4"] is not None and loss > 1e-6:
                none += 1
            out.append(dict(cap=cap, cell=x["cell"], size=x["size"], best=x["best"],
                            capped=v, carrier=cls, method=m, loss=loss))
        print("  %6.0f %7d %8d %9d %11s %11s %9d %10.2f"
              % (cap, full, weak, none,
                 ("%.2f%%" % statistics.median(losses)) if losses else "-",
                 ("%.2f%%" % max(losses)) if losses else "-", down, wall / 3600.0))
        if detail:
            for c, s, b, v, cls, pc in sorted(detail, key=lambda t: -t[5])[:5]:
                print("         %-7s n%-4d %8.1f -> %8.1f  (-%.1f%%)  now carried by %s"
                      % (c, s, b, v, pc, cls))
    print("\n  'no bound' counts cells that fell all the way to the AB4 floor.")
    print("  'downgrade' counts cells kept only by truncating the ELEM pass (ng class).")

    p = os.path.join(ROOT, "runs", "oracle", "lb_cap_with_ab_floor.json")
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(stamped(dict(rows=out, caps=a.caps, cut=CUT),
                          "analysis/lb_cap_with_ab_floor.py", "analysis/best_known.py",
                          "analysis/bound_certificate.py"), f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
