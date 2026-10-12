"""
S1 — the primal validation layer. Runs on every primal incumbent we hold, forever.

Three checks, none of which trust the solver (validation/PRIMAL_TEST_DESIGN.md S1):

  V1  VERIFIER      the independent verifier accepted the incumbent (run_valid / verified)
  V2  LB FLOOR      incumbent >= our frozen dual bound for that cell
  V3  OPTIMUM       incumbent >= a known proven optimum, where one exists (35 cells)

V2 is a CROSS-LEG check that only became possible when the LB leg closed at all five sizes on
2026-09-12, and it has never been run before. A violation of V2 or V3 is a HARD STOP: either
the primal is emitting infeasible solutions or the dual bound is invalid, and both end the
paper. V1 failing is a quarantine, not necessarily a stop.

    python analysis/s1_validate_primal.py            # every primal incumbent we hold
    python analysis/s1_validate_primal.py --csv <f>  # one calibration csv

Exit 0 clean, 2 on any V2/V3 violation, 1 if the check could not run.
"""
import os, re, sys, csv, json, glob, argparse
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import kref

TOL = 1e-6              # V2: both sides are ours, at full precision
# V3 compares against K's PUBLISHED optima, which are printed to ONE decimal. Comparing at 1e-6
# flagged C205 n20 (incumbent 685.185 vs published 685.2) as a hard stop 9 times -- our value
# ROUNDS to theirs, i.e. we reproduce their optimum exactly and the "violation" is their display
# precision. This is the same tolerance-vs-precision error made on the AB grid the same morning.
# 0.05 is the rounding bound for a 1-decimal published value; anything beyond it is real.
TOL_PUBLISHED = 0.05


def lb_floor(cell, size):
    """Best frozen dual bound: max over MILP block relaxation and the arithmetic bound."""
    best = None
    for pat in (f"easy_reduction_descend_{cell}_n{size}.json",
                f"easy_reduction_descend_{cell}_n{size}_*.json",
                f"easy_reduction_{cell}_n{size}.json",
                f"easy_reduction_{cell}_n{size}_*.json"):
        for f in glob.glob(os.path.join(ROOT, "crossfeed", pat)):
            try:
                recs = json.load(open(f))
            except Exception:
                continue
            for r in (recs if isinstance(recs, list) else [recs]):
                v = r.get("block_relax")
                if isinstance(v, (int, float)) and (best is None or v > best):
                    best = v
    gp = os.path.join(ROOT, "runs", "ab_grid_provenanced.json")
    if os.path.exists(gp):
        for r in json.load(open(gp))["records"]:
            if r["cell"] == cell and r["size"] == size:
                ab = r.get("ab4_full", r.get("ab4"))
                if isinstance(ab, (int, float)) and (best is None or ab > best):
                    best = ab
    return best


def optimum(cell, size):
    """K's proven optimum where their gap is 0 (35 cells: 27 at n10, 8 at n20/n30)."""
    if size not in (10, 20, 30):
        return None
    t = kref.table3(size).get(cell)
    if not t:
        return None
    return t["joint_bk"] if abs(t["joint_gap"]) < 1e-9 else None


def sources():
    """(cell, size, incumbent, origin) over every primal result we hold."""
    out = []
    for f in glob.glob(os.path.join(ROOT, "validation", "*.csv")):
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8")))
        except Exception:
            continue
        if not rows or "best_obj" not in rows[0]:
            continue
        for r in rows:
            v = (r.get("best_obj") or "").strip()
            if v:
                out.append((r["cell"], int(r["size"]), float(v),
                            f"{os.path.basename(f)}:{r.get('variant')}:s{r.get('seed')}",
                            (r.get("run_id") or "").strip(),
                            (r.get("stdout_path") or "").strip()))
    led = os.path.join(ROOT, "results", "ledger.jsonl")
    if os.path.exists(led):
        for line in open(led, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            o = (d.get("metrics") or {}).get("final_obj")
            if d.get("cell") and d.get("size") and isinstance(o, (int, float)) and o > 0:
                out.append((d["cell"], d["size"], float(o),
                            f"ledger:{d.get('experiment')}:{d.get('run_id')}",
                            str(d.get("run_id") or ""), ""))
    return out


def v1_evidence(run_id, cell, size, stored_obj):
    """V1 — what verification evidence exists for this incumbent?

    Three tiers, strongest first. Implemented 2026-09-13; the header has promised V1 since the
    script was written and `main()` never ran it, so every "CLEAN" it printed covered V2/V3 only.

      INDEPENDENT  a dumped solution exists and THIS script re-verifies it from the instance,
                   recomputing the objective. Requires --dump-best, which calib_run now always
                   passes (DEFECT 5). This is what PIPELINE P2c asks for.
      SELF         no solution vector survives, but the run's own spool records
                   `final best (verified) = <obj>` matching the stored value. The solver checked
                   itself; we cannot re-check it.
      NONE         neither. The number is asserted and nothing supports it.
    """
    solp = os.path.join(ROOT, "runs", "solutions", f"{run_id}.json") if run_id else None
    if solp and os.path.exists(solp):
        try:
            sol = json.load(open(solp, encoding="utf-8"))
            from solver.config import InstanceSpec
            from solver.problem import SolverProblem
            prob = SolverProblem(InstanceSpec(cell, size))
            vd = prob.verify(sol)
            rec = getattr(vd, "recomputed_obj", None)
            if not bool(vd.ok):
                return "INDEPENDENT", False, f"verifier REJECTED: {getattr(vd, 'reasons', '')}"
            if rec is not None and abs(rec - stored_obj) > 1e-3:
                return "INDEPENDENT", False, f"objective mismatch: stored {stored_obj} vs recomputed {rec}"
            return "INDEPENDENT", True, ""
        except Exception as e:
            return "INDEPENDENT", False, f"re-verification raised {type(e).__name__}: {e}"
    return "NONE", None, "no dumped solution"


def v1_from_spool(spool, stored_obj):
    """SELF tier: the run's own verified-final line agrees with the stored objective."""
    try:
        txt = open(os.path.join(ROOT, spool.replace(chr(92), os.sep)),
                   encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    m = re.search(r"final best \(verified\)\s*=\s*([0-9.]+)", txt)
    if not m:
        return False
    return abs(float(m.group(1)) - stored_obj) <= 1e-3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()
    rows = sources()
    if a.csv:
        rows = [r for r in rows if a.csv in r[3]]
    if not rows:
        print("no primal incumbents found -- NOT a pass, the check examined nothing")
        return 1

    v2, v3, near, checked2, checked3 = [], [], [], 0, 0
    floors, opts = {}, {}
    for cell, size, inc, origin, _rid, _sp in rows:
        k = (cell, size)
        if k not in floors:
            floors[k] = lb_floor(cell, size)
            opts[k] = optimum(cell, size)
        lb, op = floors[k], opts[k]
        if lb is not None:
            checked2 += 1
            if inc < lb - TOL:
                v2.append((cell, size, inc, lb, origin))
        if op is not None:
            checked3 += 1
            if inc < op - TOL_PUBLISHED:
                v3.append((cell, size, inc, op, origin))
            elif inc < op - TOL:
                near.append((cell, size, inc, op))

    print("=" * 74)
    print(f"S1 PRIMAL VALIDATION — {len(rows)} incumbents over "
          f"{len({(c, s) for c, s, _, _, _, _ in rows})} (cell,size) pairs")
    print("=" * 74)
    # ---- V1: verification evidence, strongest tier available per incumbent ----
    tiers = {"INDEPENDENT": 0, "SELF": 0, "NONE": 0}
    v1_fail = []
    for cell, size, inc, origin, rid, sp in rows:
        tier, ok, why = v1_evidence(rid, cell, size, inc)
        if tier == "INDEPENDENT":
            if ok:
                tiers["INDEPENDENT"] += 1
            else:
                v1_fail.append((cell, size, inc, origin, why))
            continue
        if sp and v1_from_spool(sp, inc):
            tiers["SELF"] += 1
        else:
            tiers["NONE"] += 1
    print(f"V1 VERIFIER   independent {tiers['INDEPENDENT']:>4}   "
          f"solver-self {tiers['SELF']:>4}   NO EVIDENCE {tiers['NONE']:>4}")
    for c, s_, i, o, why in v1_fail[:8]:
        print(f"   *** {c} n{s_}: {i:.3f} FAILED re-verification -- {why}   [{o}]")
    if tiers["NONE"]:
        print("   (incumbents with no evidence are quarantined: not independently re-verifiable")
        print("    and no self-verification line survives. Re-run with --dump-best to clear.)")
    print(f"V2 LB FLOOR   checked {checked2:>4}   violations {len(v2)}")
    for c, s, i, lb, o in v2[:8]:
        print(f"   *** {c} n{s}: incumbent {i:.3f} < LB {lb:.3f}   [{o}]")
    print(f"V3 OPTIMUM    checked {checked3:>4}   violations {len(v3)}   "
          f"within-rounding {len(near)}")
    for c, s_, i, op in sorted(set(near))[:4]:
        print(f"   ok  {c} n{s_}: {i:.3f} vs published {op:.1f} -- rounds to it, "
              f"i.e. we reproduce the optimum")
    for c, s, i, op, o in v3[:8]:
        print(f"   *** {c} n{s}: incumbent {i:.3f} < optimum {op:.3f}   [{o}]")
    if checked2 == 0:
        print("   NOTE: V2 examined nothing -- that is a FAILURE of the check, not a pass")
    print("-" * 74)
    if v2 or v3:
        print("HARD STOP. Either the primal emits infeasible solutions or the dual is invalid.")
        return 2
    if v1_fail:
        print(f"V1 FAILURES: {len(v1_fail)} incumbent(s) failed independent re-verification.")
        print("This is a QUARANTINE, not necessarily a hard stop (V1 failing means the solution")
        print("we stored does not re-verify; V2/V3 concern the bound and the optimum).")
        return 2
    print("CLEAN. No incumbent sits below our frozen dual bound or below a known optimum.")
    # how tight are we against the LB, where both exist?
    rat = [(inc / floors[(c, s)]) for c, s, inc, _, _, _ in rows if floors.get((c, s))]
    if rat:
        rat.sort()
        print(f"incumbent / LB ratio: min {rat[0]:.3f}  median {st.median(rat):.3f}  "
              f"max {rat[-1]:.3f}  (1.0 would mean the gap is closed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
