"""Production grid for the FROZEN uniform primal variant (d684-d708), with maximal ablation logging.

Per cell, run the integrated tep_solve (primal wired at the dual tail: the floor CG is the dual bound,
then ceil/refine/alns/select/fleet-cap inherit it) at the deduped, opt-gap-gated, BUDGET-FIT ng-set:
  * ng=10 always (the baseline + the FROZEN dual LB, d678);
  * if its opt-gap (OV-LB)/OV exceeds --gate, add ng in --ngset (default 5,25), each deduped by
    ng>=size==elementary, and ONLY while the per-cell wall stays under K-budget/2.5 = 5760 s
    (so the ng-union is budget-fit by construction, d706 -- a cell gets as many ng as fit).

EVERY ng run is BANKED under its own tag (pu_ng<g>), carrying the full per-stage `story`
(in_val/out_val/accepted -> stage ablation), `fleetcap_trigger` (fleet-cap ablation), `lb_hist`, and
the ng that produced it (ng ablation). So fleet-cap / ng-union / post-refine ablation claims are
derivable from the banked corpus with NO further runs. Consolidation (best OV + ng=10 LB) is
analysis/tep_uniform_grid.py.

Size-by-size, STOP-on-defect (a value below a proven optimum, or an invalid bound). Single-tenant.

    python analysis/run_primal_uniform.py --size 20
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])
BUDGET = 14400 / 2.5   # 5760 our-seconds per cell (dual+primal), d245/d246/d250
# frozen variant flags (ng and envelope are set per call; tag per ng)
FROZEN = ["--seed", "0", "--fast-pricer", "--rule-b", "--grow-max", "5", "--grow-step", "100",
          "--helpless-probe", "200", "--threads", "4", "--submission", "--select-cap", "300",
          "--fleetcap-ng", "40"]


def one(cell, size, ng, envelope):
    """Run+bank one ng; return (ov, lb, cars, wall, proven) from the banked artifact."""
    tag = "pu_ng%d" % ng
    cmd = ["python", "-u", os.path.join("analysis", "tep_solve.py"), cell, "--size", str(size),
           "--ng", str(ng), "--envelope", str(int(envelope)), "--tag", tag] + FROZEN
    t0 = time.time()
    subprocess.run(cmd, cwd=ROOT)
    wall = time.time() - t0
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n%d.json" % (tag, cell, size))
    if not os.path.exists(p):
        return None, None, None, wall, None     # stamp refused / no artifact
    d = json.load(io.open(p, encoding="utf-8")); r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
    return r.get("ov"), r.get("lb"), r.get("nCars"), wall, r.get("proven")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True, choices=(10, 20, 30, 50, 100))
    ap.add_argument("--gate", type=float, default=0.10, help="run extra ng only where opt-gap (OV-LB)/OV > this")
    ap.add_argument("--ngset", default="5,25", help="extra ng values (beyond 10); deduped ng>=size->elementary")
    a = ap.parse_args(argv[1:])
    extra = sorted({min(int(x), a.size) for x in a.ngset.split(",")} - {10})   # dedup ng>=size to elementary==size
    pi = K._kref()["table3"]["per_instance"].get(str(a.size), {})
    print("UNIFORM PRIMAL GRID  n%d  | gate opt-gap>%.0f%% | ng-set {10}+%s | budget %.0fs/cell"
          % (a.size, 100 * a.gate, extra, BUDGET))
    for cell in CELLS:
        spent = 0.0
        ov10, lb10, c10, w10, prov = one(cell, a.size, 10, BUDGET)
        spent += w10
        if ov10 is None:
            print("  %-6s  NO ARTIFACT (stamp refused?) -- STOP" % cell); return 2
        og = 100.0 * (ov10 - lb10) / ov10 if (ov10 and lb10) else None
        banked = {10: (ov10, c10, w10)}
        # defect guards (STOP): value below a proven optimum, or LB above OV
        kb, _ = K.k_best_incumbent(cell, a.size); proven_k = (pi.get(cell, {}).get("joint_gap") == 0)
        if proven_k and kb and ov10 < kb - 0.05:
            kstr = "%.1f" % kb if kb else "n/a"   # guard the format to kb's own line (G23)
            print("  %-6s  DEFECT ov %.1f < proven opt %s -- STOP" % (cell, ov10, kstr)); return 1
        if lb10 and ov10 and lb10 > ov10 + 1e-6:
            print("  %-6s  DEFECT LB %.1f > OV %.1f -- STOP" % (cell, lb10, ov10)); return 1
        # opt-gap-gated, budget-fit ng-union
        if og is not None and og > 100 * a.gate:
            for g in extra:
                if spent + w10 > BUDGET * 0.95:         # budget-fit: only if the next ng still fits
                    break
                ovg, lbg, cg, wg, _ = one(cell, a.size, g, BUDGET - spent); spent += wg
                if ovg is not None:
                    banked[g] = (ovg, cg, wg)
        best_ng = min(banked, key=lambda g: banked[g][0])
        best_ov, best_c, _ = banked[best_ng]
        tag = (" fleet%s" % c10) if c10 != best_c else ""
        print("  %-6s ng10 %.1f (%dc, og %.1f%%) | union %s -> best %.1f ng%d (%dc)%s | vsK %+.1f%% | wall %.0fs/%d"
              % (cell, ov10, c10, og or -1,
                 ",".join("ng%d:%.1f" % (g, banked[g][0]) for g in sorted(banked)),
                 best_ov, best_ng, best_c, tag, (100 * (best_ov / kb - 1)) if kb else -1, spent, int(BUDGET)))
    print("N%d UNIFORM GRID DONE" % a.size)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
