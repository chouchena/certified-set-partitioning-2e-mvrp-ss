"""Post-run audit: does a banked frozen-two-legs cell fulfil EVERY pre-registered request?

Governing spec: validation/PREREG_frozen_twolegs_campaign.md. This is the executable
"check after first run that all requests are fulfilled" gate, and the standing per-run check.
Read-only. Exit 0 iff ALL checks pass; nonzero (and prints the failures) otherwise.

Usage:  python analysis/audit_frozen_run.py <dual_artifact.json> <primal_artifact.json>
        python analysis/audit_frozen_run.py --cell C204 --size 100   (resolves by convention)
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, ROOT)

BUDGET = 5760.0
TOL = 20.0


def _load(p):
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return d[0] if isinstance(d, list) and d else d


def _rows(d):
    r = d.get("rows")
    return r if isinstance(r, list) else [d]


def ab4_floor(cell, size):
    """The deterministic arithmetic floor; a valid LB must be >= this (and this always exists)."""
    from k_comparison import k_proximity
    from build_instance import build as abuild
    from crossfeed.fullset_bound import fullset_bound as fsb
    p = abuild(cell, size, wls=0.1, tau="formula", proximity=k_proximity(size), time_limit=60)
    b, _ = fsb(p)
    return float(b)


def audit(dual, primal, cell, size):
    """Return (checks, ok). checks is a list of (name, passed, detail)."""
    from k_comparison import k_proximity
    checks = []

    def chk(name, passed, detail=""):
        checks.append((name, bool(passed), detail))

    prox_expect = k_proximity(size)
    dr = _rows(dual)[0] if dual else {}
    pr = _rows(primal)[0] if primal else {}

    # --- (1) valid LB banked, >= AB4, validity basis named ---
    # The LB leg is a PORTFOLIO max over VALID bounds: the AB4 arithmetic floor (valid by
    # construction, no elementary/ng certificate) and/or the certified CG LP bound. "Valid" =
    # lb_valid True with the basis explicit (certificate class elementary/ng, OR AB4 source).
    floor = ab4_floor(cell, size)
    lb = dr.get("lb") or dr.get("composed") or dr.get("best_lb")
    chk("LB present & >= AB4 floor",
        isinstance(lb, (int, float)) and lb >= floor - 1e-6,
        "lb=%s floor=%.2f" % (lb, floor))
    chk("LB declared valid (lb_valid)", dr.get("lb_valid") is True,
        "lb_valid=%s" % dr.get("lb_valid"))
    cert = dr.get("certificate") or dr.get("certificate_class") or dr.get("bound_class")
    src = str(dr.get("lb_source") or "")
    chk("LB validity basis named (elementary/ng or AB4)",
        cert in ("elementary", "ng") or "ab4" in src.lower() or "AB4" in src,
        "certificate=%s lb_source=%s" % (cert, src))

    # --- (2) feasible verified OV banked ---
    ov = pr.get("ov")
    chk("OV present", isinstance(ov, (int, float)), "ov=%s" % ov)
    sol = pr.get("solution")
    verified_ok = False
    rec_obj = None
    if sol is not None:
        try:
            import verifier3 as V
            inst = V.load_instance(cell, size, prox_expect)
            run = V.verify_solution(inst, sol, cell=cell, size=size, proximity=prox_expect,
                                    label="audit")
            bad = [f.cls for f in run.findings if f.severity != "TOLERANCE"]
            o = getattr(run, "objective", None)
            rec_obj = o.get("recomputed") if o else None
            verified_ok = (not bad) and (not run.blocking)
            chk("OV re-verifies clean (verifier3)", verified_ok,
                "findings=%s rec=%s" % (bad[:4], rec_obj))
            chk("OV matches banked (|rec-ov|<=0.01)",
                rec_obj is not None and ov is not None and abs(rec_obj - ov) <= 0.01,
                "rec=%s ov=%s" % (rec_obj, ov))
        except Exception as e:
            chk("OV re-verifies clean (verifier3)", False, "EXC %s" % type(e).__name__)
    else:
        chk("OV solution present to verify", False, "no solution on primal row")

    # --- (3) total RT <= 5780 ---
    def wall(row):
        rt = row.get("_rt", {}) if isinstance(row.get("_rt"), dict) else {}
        return rt.get("wall_s") or row.get("wall_s") or row.get("secs")
    dw, pw = wall(dr), wall(pr)
    # The FROZEN pipeline is INTEGRATED: one tep_solve run produces BOTH the dual LB and the
    # primal OV. When the reported primal ng equals the dual ng (ng10), dual and primal are the
    # SAME run (same run_id) -- its wall is one wall, not two. Summing would double-count a single
    # run and raise a spurious budget FAIL. Count a same-run artifact once. (The authoritative
    # per-cell budget check over the ADMITTED ng set is tep_grid_consolidate's cum<=5760 gate;
    # this check is a per-run <=5780 sanity, not the budget authority.)
    same_run = dr.get("run_id") is not None and dr.get("run_id") == pr.get("run_id")
    tot = (dw or 0) if same_run else (dw or 0) + (pw or 0)
    chk("total RT (dual+primal) <= 5780s",
        isinstance(dw, (int, float)) and isinstance(pw, (int, float)) and tot <= BUDGET + TOL,
        "dual=%s primal=%s total=%s%s" % (dw, pw, tot, " [same integrated run]" if same_run else ""))

    # --- (4) rt_class=submission (threads=4, tenancy=1) on BOTH legs ---
    # _rt / _provenance are stamped at the ARTIFACT TOP LEVEL (dual/primal), not on the row.
    for nm, top, row in (("dual", dual, dr), ("primal", primal, pr)):
        rt = top.get("_rt", {}) if isinstance(top.get("_rt"), dict) else {}
        rc = rt.get("rt_class")
        reg = rt.get("cores_regime", {}) if isinstance(rt.get("cores_regime"), dict) else {}
        th = reg.get("threads_requested") or top.get("threads") or row.get("threads")
        ten = reg.get("tenancy") or rt.get("tenancy")
        chk("%s rt_class=submission (threads=4, tenancy=1)" % nm,
            rc == "submission" and th == 4 and ten == 1,
            "rt_class=%s threads=%s tenancy=%s" % (rc, th, ten))
        # Reproducibility anchor is LEG-SPECIFIC (not a blanket det-clock rule): the DUAL bound is
        # CG-LP-based -> its anchor is the Gurobi Work det clock (>0); the PRIMAL is ALNS-dominated
        # and its finals are SEED-deterministic -> its anchor is the recorded seed. Wall is quotable
        # for both via rt_class=submission; this check is about reproducing the NUMBER.
        dt = rt.get("det_ticks") or row.get("det_ticks")
        work = (dt.get("gurobi_work") if isinstance(dt, dict) else None)
        if nm == "dual":
            chk("dual reproducibility: det clock (Gurobi Work) > 0",
                isinstance(work, (int, float)) and work > 0, "gurobi_work=%s" % work)
        else:
            chk("primal reproducibility: seed recorded (seed-deterministic finals)",
                row.get("seed") is not None, "seed=%s gurobi_work=%s" % (row.get("seed"), work))

    # --- (5) full provenance (top-level _provenance; proximity/seed on the row) ---
    for nm, top, row in (("dual", dual, dr), ("primal", primal, pr)):
        prov = top.get("_provenance", {}) if isinstance(top.get("_provenance"), dict) else {}
        # Reproducibility anchor is code_hash, NOT git cleanliness: CLAUDE.md d and stamp.py:106
        # ("the whole banked corpus carries git_dirty: true"; G6b is warn-level). So the gate is
        # code_hash+sources present; git_dirty is recorded for the record, not gated.
        chk("%s provenance anchor: code_hash + sources (git_dirty tolerated per d/G6b)" % nm,
            bool(prov.get("code_hash")) and bool(prov.get("sources")),
            "code_hash=%s sources=%s git_dirty=%s"
            % (prov.get("code_hash"), bool(prov.get("sources")), prov.get("git_dirty")))
        chk("%s seed recorded" % nm, row.get("seed") is not None,
            "seed=%s" % row.get("seed"))
        chk("%s proximity == K baseline" % nm, row.get("proximity") == prox_expect,
            "prox=%s expect=%s" % (row.get("proximity"), prox_expect))

    # --- (6) trajectories + gates banked ---
    def traj_len(row, keys):
        for k in keys:
            v = row.get(k)
            if isinstance(v, list) and v:
                return len(v)
        return 0
    _dkeys = ("lb_hist", "hist", "events", "improvements", "descent", "lb_curve")
    chk("dual LB trajectory non-empty", traj_len(dr, _dkeys) > 0,
        "entries=%d" % traj_len(dr, _dkeys))
    chk("primal OV trajectory non-empty",
        traj_len(pr, ("story", "improvements", "ov_curve")) > 0,
        "entries=%d" % traj_len(pr, ("story", "improvements", "ov_curve")))
    chk("gate trajectory banked (ceilings/budget/gates)",
        traj_len(dr, ("gates",)) + traj_len(pr, ("ceilings", "budget", "gates")) > 0,
        "dual_gates=%d primal_gate_rows=%d"
        % (traj_len(dr, ("gates",)), traj_len(pr, ("ceilings", "budget"))))

    # --- quarantine empty NOW ---
    try:
        import quarantine_guard as QG
        unt = [r for r in QG.rows() if QG.is_untriaged(r)]
        chk("quarantine empty (0 untriaged)", len(unt) == 0, "untriaged=%d" % len(unt))
    except Exception as e:
        chk("quarantine empty (0 untriaged)", False, "QG EXC %s" % type(e).__name__)

    ok = all(p for _, p, _ in checks)
    return checks, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("artifacts", nargs="*")
    ap.add_argument("--cell"); ap.add_argument("--size", type=int)
    ap.add_argument("--dual"); ap.add_argument("--primal")
    a = ap.parse_args()
    dual_p = a.dual or (a.artifacts[0] if len(a.artifacts) > 0 else None)
    primal_p = a.primal or (a.artifacts[1] if len(a.artifacts) > 1 else None)
    if not dual_p or not primal_p:
        print("need dual + primal artifact paths (or --dual/--primal)"); return 2
    cell = a.cell or _load(dual_p).get("cell") or _rows(_load(dual_p))[0].get("cell")
    size = a.size or _load(dual_p).get("size") or _rows(_load(dual_p))[0].get("size")
    checks, ok = audit(_load(dual_p), _load(primal_p), cell, size)
    print("=== AUDIT %s n%s ===" % (cell, size))
    for name, passed, detail in checks:
        print("  [%s] %-48s %s" % ("PASS" if passed else "FAIL", name, detail))
    print("\nVERDICT: %s (%d/%d checks)"
          % ("ALL REQUESTS FULFILLED" if ok else "NOT FULFILLED -- STOP",
             sum(p for _, p, _ in checks), len(checks)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
