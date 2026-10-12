"""Is K's published optimum for a cell ATTAINABLE under constraint (26)?

Pre-run audit: validation/runaudits/c26_attainability_C201_n30.md (d229).

THE CLAIM THIS TESTS, stated so it can fail:

    min{ z(s) : s feasible for the model WITH (26) }  >  BK

where BK is the value K publish for the cell AND report as proven (gap 0). Proven matters: against
a best-known, a larger corrected optimum would only mean their search stopped early.

WHY THIS FORM AND NOT "their incumbent violates (26)". That weaker claim dies to multiple optima --
their published solution might be a different optimum of the same value. Comparing two OPTIMA is
immune to it: if the corrected optimum exceeds BK, then NO (26)-feasible solution attains BK,
whichever one they found.

THREE ARMS, and B runs first on purpose:
  B  ours, hardSingleTransfer=False  -> must reproduce BK. Validates instance identity AND our
                                        transcription. If it fails, the experiment is VOID and C
                                        is not worth the budget.
  C  ours, hardSingleTransfer=True   -> the test.
  A  K's own integratedJointModel    -> their code agrees with our transcription.

THE FALSE-POSITIVE PATH, named before running: if the big-M is too SMALL the inactive branch stays
binding, the corrected model becomes stricter than (26), z*_corr inflates, and this script
"proves" something false. Validity needs M >= max|u_i - u_j| + tau; with u in
[CDC.earliest, CDC.latest] that is (latest - earliest) + tau. The encoding uses
(latest - earliest) + tau + 1. Asserted below at runtime, not assumed.

OUTPUTS ARE AN OPTIMUM AND A PROOF STATUS. Never a runtime -- this runs co-tenant with a
wall-limited batch, so every wall figure here is diagnostic only (d45/d47).

    python analysis/c26_attainability.py --cell C201 --size 30 --bk 1011.9
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

OUTDIR = os.path.join(ROOT, "runs", "c26_attainability")


def bigM_is_valid(p):
    """M >= max|u_i - u_j| + tau, checked against the instance rather than trusted."""
    nd, CDC = p.nodes, p.CDC
    span = nd[CDC].latest - nd[CDC].earliest
    tau = p.TransferDuration
    need = span + tau
    used = span + tau + 1.0
    return used >= need, used, need


def check_arm(rec, cell, size, prox):
    """verify2 on ONE arm, immediately. Arm B's verdict is informative on its own -- it says
    whether a solution attaining K's published value satisfies (26) -- and deferring it until
    after arm C means the most interesting object in the experiment sits unchecked for up to
    90 minutes. It gates arm C rather than trailing it."""
    import verifier3, instance_view
    if not rec.get("solution"):
        return None
    sol = dict(rec["solution"])
    sol["objVal"] = rec["objVal"]
    raw = instance_view.VInstance._load_json(cell)
    inst = instance_view.VInstance(cell, size, wls=0.1,
                                   tau=verifier3.tau_for(raw, size), proximity=prox)
    # d243: an oracle probe that runs BOTH arms deliberately, so provenance must not block
    vd = verifier3.verify_for_engine(inst, sol, cell=cell, size=size, proximity=prox,
                                     expect="any")
    c26 = [f for f in vd.run.findings
           if str(f.cls).startswith("C26") and f.severity == "VIOLATION"]
    rec["verifier3"] = {"verdict": vd.verdict, "violations": len(vd.violations),
                      "c26_violations": len(c26),
                      "worst_c26": (max((abs(float(f.slack)) for f in c26
                                         if f.slack is not None), default=None))}
    print("   verifier3 -> %-8s   violations %d   of which C26 %d%s"
          % (vd.verdict, len(vd.violations), len(c26),
             ("   worst C26 short by %.4f" % rec["verifier3"]["worst_c26"])
             if rec["verifier3"]["worst_c26"] else ""), flush=True)
    return rec["verifier3"]


def run_arm(p, hard, tl, threads, tag, cell, size):
    from joint_model_gurobi import joint_synchronized_gurobi
    p.hardSingleTransfer = hard
    trace = os.path.join(OUTDIR, "trace_%s_%s_n%d.jsonl" % (tag, cell, size))
    t0 = time.time()
    r = joint_synchronized_gurobi(p, time_limit=tl, mip_gap=0.0, threads=threads,
                                  log_output=False, trace_path=trace)
    r["wall_s_diagnostic_only"] = round(time.time() - t0, 1)
    r["arm"] = tag
    r["hardSingleTransfer"] = hard
    r.pop("progress_trace", None)            # on disk already; keep the record small
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="C201")
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--bk", type=float, required=True, help="K's published, PROVEN value")
    ap.add_argument("--tl", type=float, default=5400.0)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--tol", type=float, default=1e-4)
    ap.add_argument("--skip-k-arm", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    from analysis.k_comparison import k_proximity
    from build_instance import build
    import verifier3
    import instance_view

    prox = k_proximity(a.size)
    print("cell %s  n%d   K published (proven) BK = %s" % (a.cell, a.size, a.bk))
    print("proximity %s  (K's Table 3 for this size; basis INFERRED, see the audit)" % prox)

    p = build(a.cell, a.size, wls=0.1, tau="formula", proximity=prox)
    ok, used, need = bigM_is_valid(p)
    print("big-M check: uses %.2f, needs >= %.2f  -> %s" % (used, need, "VALID" if ok else "INVALID"))
    if not ok:
        print("REFUSING: the disjunction's big-M is too small. It would make the corrected model "
              "STRICTER than (26) and manufacture a false positive.")
        return 3
    print("tau = %s   threads = %d   time limit = %.0fs per arm" % (p.TransferDuration, a.threads, a.tl))
    print()

    records = []

    # ---- ARM B: reproduce K's optimum. If this fails nothing else is worth running. -------
    print("ARM B  vacuous (K's published linearization) -- must reproduce %s" % a.bk, flush=True)
    B = run_arm(p, False, a.tl, a.threads, "B_vacuous", a.cell, a.size)
    records.append(B)
    print("   objVal %s   bound %s   gap %s   status %s   (%.0fs)"
          % (B["objVal"], round(B["best_bound"], 4) if B["best_bound"] is not None else None,
             B["mip_gap"], B["status"], B["wall_s_diagnostic_only"]), flush=True)
    check_arm(B, a.cell, a.size, prox)          # immediately, not after arm C
    reproduced = B["objVal"] is not None and abs(B["objVal"] - a.bk) <= 0.05
    print("   reproduces K's BK: %s" % ("YES" if reproduced else "NO"), flush=True)
    if not reproduced:
        print()
        print("VOID: arm B did not reproduce K's published value. Either the instance we build is "
              "not theirs, or our transcription differs. Both must be resolved before arm C means "
              "anything. NOT running arm C.")
        json.dump(stamped(records, __file__), open(os.path.join(OUTDIR, "report_%s_n%d.json" % (a.cell, a.size)), "w"),
                  indent=2, default=str)
        return 1
    print()

    # ---- ARM C: the test -------------------------------------------------------------------
    print("ARM C  corrected disjunctive (26) -- the test", flush=True)
    C = run_arm(p, True, a.tl, a.threads, "C_corrected", a.cell, a.size)
    records.append(C)
    print("   objVal %s   bound %s   gap %s   status %s   (%.0fs)"
          % (C["objVal"], round(C["best_bound"], 4) if C["best_bound"] is not None else None,
             C["mip_gap"], C["status"], C["wall_s_diagnostic_only"]), flush=True)

    check_arm(C, a.cell, a.size, prox)
    GRB_OPTIMAL = 2
    proven = C["status"] == GRB_OPTIMAL
    print()
    if not proven:
        verdict = "INCONCLUSIVE"
        print("VERDICT: INCONCLUSIVE -- arm C did not prove optimality (status %s). An unproven "
              "corrected arm establishes nothing: it is a relaxation being compared to a feasible "
              "solution, which is on this project's failure list." % C["status"])
    elif C["objVal"] > a.bk + a.tol:
        verdict = "UNATTAINABLE"
        print("VERDICT: UNATTAINABLE -- the optimum with (26) enforced is %.4f, above K's published "
              "%.4f. No (26)-feasible solution attains their value ON THIS CELL." % (C["objVal"], a.bk))
    else:
        verdict = "ATTAINABLE"
        print("VERDICT: ATTAINABLE -- the corrected optimum is %.4f, not above K's published %.4f. "
              "(26) does not bind here and their value survives enforcement. REFUTED on this cell, "
              "and this is a finding in their favour." % (C["objVal"], a.bk))

    # ---- ARM A: K's own code -----------------------------------------------------------------
    if not a.skip_k_arm:
        print()
        print("ARM A  K's own integratedJointModel -- does their code agree with our "
              "transcription?", flush=True)
        try:
            import integratedJointModel as KJM
            print("   K's module imported; entry points: %s"
                  % [n for n in dir(KJM) if not n.startswith("_")][:8], flush=True)
            records.append({"arm": "A_kcode", "status": "NOT RUN -- entry point needs a driver, "
                                                        "see notes"})
        except Exception as e:
            records.append({"arm": "A_kcode", "status": "import failed: %s" % e})
            print("   import failed: %s" % e)

    out = os.path.join(OUTDIR, "report_%s_n%d.json" % (a.cell, a.size))
    json.dump(stamped({"cell": a.cell, "size": a.size, "proximity": prox, "k_bk": a.bk,
               "verdict": verdict, "arms": records}, __file__), open(out, "w"), indent=2, default=str)
    print()
    print("report -> %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
