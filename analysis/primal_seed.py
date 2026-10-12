"""Primal-seed contract: compose the dual-leg handoff into a single object a FUTURE primal
variant can warm-start from -- derived OV, incumbent routes, and the certified LB together.

Directive (2): "wire future primal variant with derived OV and incumbent and LB."

The dual leg writes two files per cell:
  * handoff/dualinc2_<cell>_n<size>.json   -- {ov, solution(routes)}         (incumbent)
  * runs/oracle/tep_solve_frzdual2_<cell>_n<size>.json -- {rows[0].lb, .certificate, .ov},
    with _provenance.code_hash and _rt (certified submission wall).            (bound + provenance)

LB is NOT in the handoff by design (the handoff carries "NO runtime claim"); it lives on the
banked record whose _rt is rt_class=submission. This reader MERGES the two so the primal has
one object, and refuses (ProvenanceError-style) to emit a seed that fails its falsifiers.

Run SINGLE-TENANT (after any citable solve python has exited).
Falsifiers (a seed that trips any of these is not emitted):
  F1  handoff.solution.objVal == handoff.ov == banked.rows[0].ov   (the three OVs agree)
  F2  banked.lb <= seed.ov                                         (a bound does not exceed what it bounds)
  F3  banked._provenance.code_hash present                         (no seed without provenance)
  F4  banked._rt.rt_class == "submission"                          (seed inherits a citable wall) [warn-only]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ATOL = 1e-6


def _load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def _row(d):
    if d is None:
        return None
    r = d.get("rows", [d])
    return (r[0] if isinstance(r, list) else r) if isinstance(r, (list, dict)) else None


def seed(cell, size=100, strict=True):
    """Return the merged primal seed for one cell, or raise ValueError on a falsifier."""
    hp = os.path.join(ROOT, "handoff", "dualinc2_%s_n%d.json" % (cell, size))
    bp = os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (cell, size))
    h = _load(hp)
    b = _load(bp)
    if h is None:
        raise ValueError("%s: no handoff (%s)" % (cell, os.path.relpath(hp, ROOT)))
    if b is None:
        raise ValueError("%s: no banked record (%s)" % (cell, os.path.relpath(bp, ROOT)))
    br = _row(b)
    sol = h.get("solution") or {}
    ov_h = h.get("ov")
    ov_b = br.get("ov")
    ov_sol = sol.get("objVal")
    lb = br.get("lb")
    cert = br.get("certificate")
    prov = (b.get("_provenance") or {})
    rt = (b.get("_rt") or {})
    code_hash = prov.get("code_hash")

    # F1: the three OVs agree
    ovs = [x for x in (ov_h, ov_b, ov_sol) if x is not None]
    if len(ovs) < 2 or any(abs(x - ovs[0]) > ATOL for x in ovs):
        raise ValueError("%s F1: OVs disagree handoff=%s banked=%s sol.objVal=%s" % (cell, ov_h, ov_b, ov_sol))
    ov = ovs[0]
    # F2: bound does not exceed the incumbent it bounds
    if lb is None:
        raise ValueError("%s F2: banked record has no lb" % cell)
    if lb > ov + ATOL:
        raise ValueError("%s F2: lb %.6f > ov %.6f" % (cell, lb, ov))
    # F3: provenance present
    if not code_hash:
        raise ValueError("%s F3: banked record carries no _provenance.code_hash" % cell)
    # F4: citable wall (warn-only -- a seed can still warm-start a non-citable exploratory primal)
    rt_class = rt.get("rt_class")
    if strict and rt_class != "submission":
        sys.stderr.write("  WARN %s F4: dual _rt.rt_class=%s (not 'submission'); seed wall not citable\n" % (cell, rt_class))

    return {
        "cell": cell, "size": size,
        "ov": ov, "lb": lb, "gap_pct": 100.0 * (ov - lb) / lb, "certificate": cert,
        "solution": sol,                       # incumbent routes -> primal warm start
        "dual_wall_s": rt.get("wall_s"),       # certified submission wall (envelope-denominated)
        "dual_work_det": br.get("work"),       # Gurobi Work (deterministic anchor; excludes pricer)
        "dual_rt_class": rt_class, "threads": rt.get("threads"), "tenancy": rt.get("tenancy"),
        "code_hash": code_hash,
    }


CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])


def main(argv):
    size = 100
    if len(argv) >= 2 and argv[1] == "--all":
        if len(argv) >= 3:
            size = int(argv[2])
        ok = miss = bad = 0
        for c in CELLS:
            try:
                s = seed(c, size, strict=True)
                print("  %-7s OV %9.2f  LB %9.2f  gap %5.1f%%  cert=%-4s  dualwall %6.1fs  work %7.2f"
                      % (c, s["ov"], s["lb"], s["gap_pct"], s["certificate"], s["dual_wall_s"] or -1, s["dual_work_det"] or -1))
                ok += 1
            except ValueError as e:
                msg = str(e)
                if "no handoff" in msg or "no banked" in msg:
                    miss += 1
                else:
                    print("  !! %s" % msg); bad += 1
        print("\n  %d seeds OK | %d not yet run | %d FAILED falsifier" % (ok, miss, bad))
        return 1 if bad else 0
    cell = argv[1]
    size = int(argv[2]) if len(argv) > 2 else 100
    print(json.dumps(seed(cell, size, strict=True), indent=1)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
