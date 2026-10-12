"""
dual_bound_harness.py — THE single harness for every dual-bound experiment
on this project (rule 21 generalised, rule 22e). Supersedes and replaces:
  crossfeed/dual_bound_table.py
  crossfeed/blockA_hard_n20.py
  crossfeed/ld_probe_stratified.py
(kept in archive/superseded_dualbound/ for reference only — do not run.)

Per cell it produces, all through one fixed protocol:
  * joint LP relaxation (LinearRelaxer)                    -- context
  * joint MILP, solution re-checked by the independent verifier (rule 3).
    z_joint is "trusted" only if the solve proved optimality AND the
    verifier passes; else the cell reports absolute bounds and flags
    "% of opt" undefined.
  * block A (street+sync, integer, lambda=0) with ADAPTIVE stopping
    (crossfeed.stall_stopper): time_limit is a CEILING; abort once the
    best bound plateaus for `--blockA-patience` s. Full (t, bound,
    incumbent) convergence curve logged via RunLogger (rule 4).
  * Karademir's valid water LB  w = c^w*(2 minTr)*L + L*beta_w.
  * block-relaxation bound = (block A's valid LB) + w.
  * optional: full LD subgradient bound (crossfeed.lagrangian_decomp).
  * comparison vs Karademir's published Joint MILP / LBBD numbers.

Every cell gets ONE status: TRUSTED_OPT / INCUMBENT_ONLY / BLOCKA_TIMEOUT
/ ERROR. Output: <out>.json + <out>.md + one RunLogger run per cell.

    python -m crossfeed.dual_bound_harness --cells C203,C204,R205,RC203 \
        --size 20 --blockA-tl 7200 --blockA-patience 600 --threads 4
"""
from __future__ import annotations
import argparse
import json
import math
import sys
import time

sys.path.insert(0, ".")
from build_instance import build
from joint_model_cplex import joint_synchronized_cplex
from crossfeed.block_a import BlockA
from instance_view import VInstance
# 2026-09-20: verifier3 replaces verify2 -- it checks K's PUBLISHED (1)-(30) in original form.
from analysis.verifier3 import verify_for_engine as verify_solution
from runlog import RunLogger

# ---------------------------------------------------------------------------
# Karademir et al. (2025) published numbers, from paper/paper-reference-data.md
#   |C|=10: all proven -> BK == optimum, gap 0.
#   |C|=20: Joint BK / Joint Gap% / LBBD BK  (Joint bound = BK*(1-gap/100)).
# ---------------------------------------------------------------------------
K_REF = {
    10: {  # BK == optimum (all proven) -- paper-reference-data.md, re-read from crop
        "C201": 365.5, "C203": 327.5, "C204": 304.3,
        "R201": 420.1, "R205": 376.4, "R211": 344.5,
        "RC201": 392.8, "RC203": 356.5, "RC208": 318.7,
    },
    20: {  # (Joint BK, Joint Gap%, LBBD BK)
        "C201": (697.7, 0, 697.7), "C203": (682.7, 54, 676.3),
        "C204": (683.5, 57, 668.1), "C205": (685.2, 0, 685.2),
        "R201": (821.7, 0, 821.7), "R205": (642.2, 0, 676.3),
        "R211": (669.1, 48, 584.4),
        "RC201": (981.2, 0, 981.2), "RC203": (754.3, 56, 767.6),
        "RC208": (881.6, 65, 858.7),
    },
}


def _karademir(name, size):
    r = K_REF.get(size, {}).get(name)
    if r is None:
        return {}
    if size == 10:
        return {"k_joint": r, "k_gap": 0, "k_bound": r, "k_lbbd": r, "k_proven": True}
    bk, gap, lbbd = r
    return {"k_joint": bk, "k_gap": gap, "k_bound": round(bk * (1 - gap / 100), 1),
            "k_lbbd": lbbd, "k_proven": gap == 0}


def water_lb(p):
    D, CDC = p.DistMatrix, p.CDC
    L = math.ceil(sum(p.nodes[c].demand for c in p.customers) / p.VesselCapacity)
    minTr = min(2 * D[CDC][s] for s in p.satellites)
    return p.travelcostwater * minTr * L + L * p.penaltyVessels, L


# ---------------------------------------------------------------------------
def preflight(cells, size, blockA_tl):
    """Rule 22b/d: hard-assert the instrumentation is in place before any
    compute is spent. Raises on any failure."""
    checks = []
    # verifier independent + importable
    import verifier as _v
    assert hasattr(_v, "verify") and hasattr(_v, "VInstance")
    checks.append("verifier importable")
    # RunLogger writable
    import os
    from runlog import RUNS_DIR
    assert os.path.isdir(RUNS_DIR) or os.access(os.path.dirname(RUNS_DIR), os.W_OK)
    checks.append("RunLogger dir writable")
    # progress tracking WILL be on for this block-A budget (rule 4 / 22b)
    assert blockA_tl >= 60, "blockA_tl < 60s would disable auto progress tracking"
    from crossfeed.stall_stopper import StallStopper  # noqa: F401
    checks.append(f"block-A progress tracking active (tl={blockA_tl}s >= 60)")
    # build path works for the first cell
    n0, _ = cells[0]
    p = build(n0, size, wls=0.1, tau="formula", proximity=0.0, time_limit=30)
    assert p._resolved_tau is not None
    checks.append(f"build_instance OK (tau={p._resolved_tau} for {n0})")
    print("PREFLIGHT:")
    for c in checks:
        print(f"  [OK] {c}")
    print(flush=True)


# ---------------------------------------------------------------------------
def one_cell(name, size, *, joint_tl, blockA_tl, blockA_patience, threads,
             with_ld, skip_joint, timing_mode="bigM"):
    lg = RunLogger(f"dualbnd_{name}_n{size}_{timing_mode}", instance=name, size=size,
                   config={"engine": "dual_bound_harness", "wls": 0.1,
                           "tau": "formula", "proximity": 0.0, "timing_mode": timing_mode,
                           "joint_tl": joint_tl, "blockA_tl": blockA_tl,
                           "blockA_patience": blockA_patience, "with_ld": with_ld})
    row = {"cell": f"{name}/{size}", "instance": name, "size": size}
    row.update({k: v for k, v in _karademir(name, size).items()})
    try:
        # ---- joint LP relaxation ----
        lg.phase("joint_lp")
        p0 = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=joint_tl)
        jlp = joint_synchronized_cplex(p0, time_limit=180, lp_relax=True)
        row["joint_lp"] = jlp["lp_bound"]

        # ---- joint MILP (verifier-gated) ----
        z_joint = z_joint_bound = None
        trusted = False
        if not skip_joint:
            lg.phase("joint_milp")
            p1 = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=joint_tl)
            zj = joint_synchronized_cplex(p1, time_limit=joint_tl, mip_gap=0.0, threads=threads)
            z_joint = zj["objVal"]
            z_joint_bound = round(zj["best_bound"], 3) if zj.get("best_bound") is not None else None
            proven = zj["status"].startswith("integer optimal")
            verified = False
            if zj.get("solution"):
                vinst = VInstance(name, size, wls=0.1, tau=p1._resolved_tau, proximity=0.0)
                s = dict(zj["solution"]); s["objVal"] = z_joint
                vd = verify_solution(vinst, s, expect="any")  # d243: dual leg: block_b posts no (22) row, so validBigM is moot
                verified = bool(vd.ok and vd.obj_matches)
                row["verifier"] = "ok" if verified else f"FAIL:{vd.violations[:2]}"
                if not verified:
                    lg.event(None, trigger="zjoint_verifier_fail",
                             extra={"violations": vd.violations[:5]})
            trusted = bool(proven and verified)
            if z_joint:
                lg.incumbent(z_joint, trigger="joint_milp",
                             extra={"proven": proven, "verified": verified})
        row["z_joint"] = z_joint
        row["z_joint_bound"] = z_joint_bound
        row["z_joint_trusted"] = trusted

        # ---- block A, ADAPTIVE (rule 4 / 22) ----
        lg.phase("block_a")
        pA = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=joint_tl)
        ba = BlockA(pA, integral=True, timing_mode=timing_mode)
        try:
            ba.m.parameters.threads = threads
        except Exception:
            pass
        rA = ba.solve(time_limit=blockA_tl, stall_patience_s=blockA_patience, run_logger=lg)
        row["blockA_lb"] = rA["value"]              # valid LB (proven -> exact)
        row["blockA_incumbent"] = rA.get("incumbent")
        row["blockA_proven"] = bool(rA.get("proven"))
        row["blockA_wall_s"] = rA["wall_s"]
        row["blockA_stopped"] = rA.get("stopped_reason")
        row["blockA_convergence"] = rA.get("convergence")

        wlb, L = water_lb(pA)
        row["water_lb"] = round(wlb, 2)
        row["vessel_lb"] = L
        br = (rA["value"] + wlb) if rA["value"] is not None else None
        row["block_relax_bound"] = round(br, 3) if br is not None else None
        if br is not None:
            lg.bound(br, trigger="block_relaxation_final",
                     extra={"blockA_lb": rA["value"], "water_lb": round(wlb, 2),
                            "blockA_proven": row["blockA_proven"]})

        # ---- optional full LD ----
        if with_ld:
            lg.phase("full_ld")
            from crossfeed.lagrangian_decomp import ld_bound
            ub = z_joint if trusted else (rA.get("incumbent") or 1e7)
            t0 = time.time()
            ld = ld_bound(pA, ub=ub, max_iter=30, blockB_tl=20, couplings=("v",), verbose=False)
            row["ld_bound"] = round(ld.best_bound, 3)
            row["ld_wall_s"] = round(time.time() - t0, 1)
            lg.bound(ld.best_bound, trigger="full_ld", extra={"iters": ld.n_iter, "reason": ld.reason})

        # ---- status + comparisons ----
        ref_opt = z_joint if trusted else row.get("k_joint")   # best available "true" value
        if ref_opt:
            if br:
                row["block_relax_pct"] = round(100 * br / ref_opt, 1)
            if row.get("joint_lp") is not None:
                row["joint_lp_pct"] = round(100 * row["joint_lp"] / ref_opt, 1)
        if row.get("k_bound") and br:
            row["vs_karademir_bound_x"] = round(br / row["k_bound"], 2)

        if row["blockA_proven"]:
            row["status"] = "TRUSTED_OPT" if trusted else "BLOCKA_PROVEN"
        elif trusted:
            row["status"] = "INCUMBENT_ONLY"
        else:
            row["status"] = "BLOCKA_TIMEOUT"

        # NOTE: `verified` here is the RUN-VALIDITY flag that RunLogger uses to
        # decide quarantine (rule 3). A truncated block-A bound is a VALID
        # lower bound by construction (crossfeed/bound_validity.md) -- it is
        # NOT a verifier failure, so the run is valid regardless of whether
        # block A proved optimality or z_joint is trusted. Those are recorded
        # separately in the row / events (z_joint_trusted, blockA_proven).
        # Only an exception or an actual verifier rejection is null.
        run_valid = not str(row.get("verifier", "")).startswith("FAIL")
        lg.close(status=row["status"], run_valid=run_valid,
                 verified=(row["status"] == "TRUSTED_OPT"),
                 final_incumbent=z_joint, final_bound=br)
    except Exception as e:
        import traceback
        row["error"] = repr(e)
        row["status"] = "ERROR"
        row["traceback"] = traceback.format_exc()
        lg.close(status="error", run_valid=False, verified=False)
    return row


# ---------------------------------------------------------------------------
def write_md(rows, path):
    L = []
    L.append("# Dual-bound harness results\n")
    L.append(f"_generated {time.strftime('%Y-%m-%d %H:%M')}_\n")
    L.append("| cell | status | joint LP | block A LB (proven?) | water LB | "
             "**block-relax** | Karademir bound | K LBBD | z_joint(ours) | br % | ×K bound |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        pv = "✓" if r.get("blockA_proven") else "✗"
        L.append(
            f"| {r['cell']} | {r.get('status','')} | {r.get('joint_lp')} | "
            f"{r.get('blockA_lb')} ({pv}) | {r.get('water_lb')} | "
            f"**{r.get('block_relax_bound')}** | {r.get('k_bound')} | {r.get('k_lbbd')} | "
            f"{r.get('z_joint')} | {r.get('block_relax_pct')} | {r.get('vs_karademir_bound_x')} |")
    L.append("")
    for r in rows:
        cv = r.get("blockA_convergence")
        if cv and cv.get("checkpoints"):
            L.append(f"**{r['cell']} block-A convergence** "
                     f"(stopped: {r.get('blockA_stopped')}, wall {r.get('blockA_wall_s')}s): "
                     + ", ".join(f"{k}={v}" for k, v in cv["checkpoints"].items()))
    open(path, "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C203,C204,R205,RC203")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--joint-tl", type=float, default=1800)
    ap.add_argument("--skip-joint", action="store_true",
                    help="skip the joint MILP re-solve (use Karademir's published value as reference)")
    ap.add_argument("--blockA-tl", type=float, default=7200, help="block-A time CEILING (s)")
    ap.add_argument("--blockA-patience", type=float, default=600,
                    help="abort block A once best bound plateaus this many s")
    ap.add_argument("--with-ld", action="store_true")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--timing", choices=["bigM", "indicator"], default="bigM")
    ap.add_argument("--out", default="crossfeed/dual_bound_results")
    a = ap.parse_args()

    cells = [(c.strip(), a.size) for c in a.cells.split(",")]
    preflight(cells, a.size, a.blockA_tl)

    rows = []
    hdr = (f"{'cell':>10} {'status':>15} {'blkA_LB':>10} {'prov':>5} "
           f"{'blkRelax':>10} {'Kbound':>9} {'br%':>6} {'xK':>5} {'wall_s':>8}")
    print(hdr, flush=True)
    for name, size in cells:
        r = one_cell(name, size, joint_tl=a.joint_tl, blockA_tl=a.blockA_tl,
                     blockA_patience=a.blockA_patience, threads=a.threads,
                     with_ld=a.with_ld, skip_joint=a.skip_joint, timing_mode=a.timing)
        rows.append(r)
        print(f"{r['cell']:>10} {str(r.get('status'))[:15]:>15} {str(r.get('blockA_lb')):>10} "
              f"{('Y' if r.get('blockA_proven') else 'n'):>5} {str(r.get('block_relax_bound')):>10} "
              f"{str(r.get('k_bound')):>9} {str(r.get('block_relax_pct')):>6} "
              f"{str(r.get('vs_karademir_bound_x')):>5} {str(r.get('blockA_wall_s')):>8}", flush=True)
        json.dump(rows, open(a.out + ".json", "w"), indent=2, default=str)
        write_md(rows, a.out + ".md")

    print("\n=== verdict ===", flush=True)
    for r in rows:
        c, br, kb = r["cell"], r.get("block_relax_bound"), r.get("k_bound")
        if r.get("blockA_proven") and br and kb:
            print(f"  {c}: block A PROVEN -> block-relax {br} vs Karademir {kb}  = {br/kb:.2f}x", flush=True)
        elif br and kb:
            print(f"  {c}: block A NOT proven ({r.get('blockA_stopped')}, {r.get('blockA_wall_s')}s) "
                  f"-> best block-relax {br} vs Karademir {kb} = {br/kb:.2f}x  "
                  f"[curve: {(r.get('blockA_convergence') or {}).get('checkpoints')}]", flush=True)
        else:
            print(f"  {c}: {r.get('status')} {r.get('error','')}", flush=True)


if __name__ == "__main__":
    main()
