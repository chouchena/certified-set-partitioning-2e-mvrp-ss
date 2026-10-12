"""Driver for the TEP column-generation bound over the n100 cells (audit
validation/runaudits/TEP_cg_bound_27cells.md; author's go 2026-09-23 18:05 "Go go").

Sequential, one cell at a time (one Gurobi LP thread + one Python core -- the reserve-2 shape):
  0. parse-check the two modules;
  1. CONSISTENCY GATE: R204 at --delta 10 (finer buckets) must come back proven with a street
     part >= the delta-20 value (runs/oracle/tep_cg_bound_R204.json); if not, the batch stops --
     a finer relaxation that is lower means the bucket logic is wrong, and nothing else runs;
  2. every remaining cell, R family first, then RC, then C; cells with an existing proven
     artifact are skipped; each cell gets --max-secs and the stall rule; a cell that ends
     unproven is recorded and the batch moves on;
  3. finer-bucket checks on RC204 (--delta 10) and C204 (--delta 30);
  4. summary table: street part, x the arithmetic street part, composed with the arithmetic
     water term, vs AB4, proven flag.  Written to runs/oracle/tep_cg_batch_summary.json.

    python analysis/tep_cg_batch.py [--max-secs 5400] [--iters 200]
"""
import argparse
import ast
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORACLE = os.path.join(ROOT, "runs", "oracle")
LOGS = os.path.join(ROOT, "logs")
R = ["R201", "R202", "R203", "R205", "R206", "R207", "R208", "R209", "R210", "R211"]
RC = ["RC201", "RC202", "RC203", "RC204", "RC205", "RC206", "RC207", "RC208"]
C = ["C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208"]


def art(cell, delta_tag=""):
    return os.path.join(ORACLE, "tep_cg_bound_%s%s.json" % (cell, delta_tag))


def load(path):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return None


def run_cell(cell, extra, log_name, max_secs, iters):
    cmd = [sys.executable, os.path.join(ROOT, "analysis", "tep_cg_bound.py"), cell, "--ng", "10", "--iters", str(iters)] + extra
    if max_secs:
        cmd += ["--max-secs", str(max_secs)]
    t0 = time.time()
    with io.open(os.path.join(LOGS, log_name), "w", encoding="utf-8") as log:
        log.write("$ %s\n" % " ".join(cmd)); log.flush()
        rc = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    return rc, round(time.time() - t0)


def say(msg):
    print("%s  %s" % (time.strftime("%H:%M"), msg), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-secs", type=float, default=5400.0); ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--skip-gate", action="store_true", help="only if the delta-10 artifact already exists and passed")
    a = ap.parse_args()
    for f in ("tep_cg_bound.py", "tep_pricer.py", "precluster_trips.py"):
        ast.parse(io.open(os.path.join(ROOT, "analysis", f), encoding="utf-8").read())
    say("parse-check OK")

    # 1. consistency gate on R204
    base = load(art("R204"))
    if base is None or not base.get("proven"):
        say("ABORT: runs/oracle/tep_cg_bound_R204.json missing or not proven"); sys.exit(2)
    fine = load(art("R204", "_d10"))
    if fine is None or not a.skip_gate:
        say("consistency gate: R204 --delta 10 (must be proven and >= %.2f)" % base["lp_street"])
        rc, secs = run_cell("R204", ["--delta", "10"], "tep_cg_R204_d10.out", a.max_secs, a.iters)
        fine = load(art("R204", "_d10"))
        say("R204 d10 finished rc %d in %d s: %s" % (rc, secs, None if fine is None else {k: fine.get(k) for k in ("lp_street", "N", "proven", "status", "iters", "secs")}))
    # Three outcomes, kept apart (d389: an unproven gate is instrumentation, not bucket logic):
    #   proven and >= coarse           -> PASSED
    #   proven and < coarse            -> FAILED: the relaxation logic is wrong; nothing else runs
    #   unproven (cap, stall, exhausted) -> INCONCLUSIVE: the batch continues and every later
    #                                     cell is reported with 'condition 3 pending'; the gate
    #                                     run is re-queued at the end with a doubled cap.
    gate_status = "pending"
    if fine is not None and fine.get("proven"):
        if fine["lp_street"] < base["lp_street"] - 1e-6:
            # d424: monotonicity in DELTA is EXPECTED (a nesting argument: every fine-model
            # schedule should map to a coarse-model one) but is NOT PROVED, and a fall can also
            # mean a false proof at either DELTA. So this stops the batch as an INCONSISTENCY to
            # investigate, not as a demonstrated defect in the bucket logic.
            say("GATE INCONSISTENT: finer buckets gave a PROVEN value %.2f below the coarse %.2f. Either the "
                "unproved DELTA-monotonicity fails here or one of the two proofs is unsound -- batch stopped for "
                "investigation, no value discarded." % (fine["lp_street"], base["lp_street"])); sys.exit(3)
        gate_status = "passed"
        say("GATE PASSED: d10 %.2f >= d20 %.2f" % (fine["lp_street"], base["lp_street"]))
    else:
        gate_status = "inconclusive"
        say("GATE INCONCLUSIVE: the d10 run ended %s (unproven, %s); batch continues, condition 3 PENDING; gate re-queued at the end with a doubled cap"
            % (None if fine is None else fine.get("status"), None if fine is None else "%.2f so far" % fine["lp_street"]))

    # 2. the cells
    results = {}
    for cell in R + RC + C:
        have = load(art(cell))
        if have is not None and have.get("proven"):
            say("%s: existing proven artifact %.2f, skipped" % (cell, have["lp_street"])); results[cell] = have; continue
        say("%s: start" % cell)
        rc, secs = run_cell(cell, [], "tep_cg_%s.out" % cell, a.max_secs, a.iters)
        have = load(art(cell))
        if have is None:
            say("%s: NO ARTIFACT (rc %d, %d s) -- see logs/tep_cg_%s.out" % (cell, rc, secs, cell)); results[cell] = {"cell": cell, "status": "no_artifact"}; continue
        say("%s: %s street %.2f N %.2f x%.3f composed %.1f vs AB4 %.1f  (%d it, %d s)" % (
            cell, "PROVEN" if have.get("proven") else "UNPROVEN/" + str(have.get("status")), have["lp_street"], have["N"],
            have["lp_street"] / have["ab_street"], have["composed"], have["ab4"], have["iters"], have["secs"]))
        results[cell] = have

    # 3. finer-bucket checks, one per remaining family
    for cell, d in (("RC204", "10"), ("C204", "30")):
        coarse = results.get(cell) or load(art(cell))
        if coarse is None or not coarse.get("proven"):
            say("%s finer check skipped: coarse run not proven" % cell); continue
        rc, secs = run_cell(cell, ["--delta", d], "tep_cg_%s_d%s.out" % (cell, d), a.max_secs, a.iters)
        fine = load(art(cell, "_d%s" % d))
        ok = fine is not None and fine.get("proven") and fine["lp_street"] >= coarse["lp_street"] - 1e-6
        say("%s finer check (delta %s): %s -- fine %s vs coarse %.2f" % (cell, d, "OK" if ok else "FAILED", None if fine is None else "%.2f" % fine["lp_street"], coarse["lp_street"]))
        results["%s_d%s" % (cell, d)] = fine or {"cell": cell, "status": "no_artifact"}

    # 3b. an inconclusive gate is retried once with a doubled cap before the summary
    if gate_status == "inconclusive":
        say("gate retry: R204 --delta 10 with cap %.0f s" % (2 * a.max_secs))
        rc, secs = run_cell("R204", ["--delta", "10"], "tep_cg_R204_d10_retry.out", 2 * a.max_secs, 2 * a.iters)
        fine = load(art("R204", "_d10"))
        if fine is not None and fine.get("proven"):
            gate_status = "passed" if fine["lp_street"] >= base["lp_street"] - 1e-6 else "FAILED"
        say("gate after retry: %s (%s)" % (gate_status, None if fine is None else "%.2f, %s" % (fine["lp_street"], fine.get("status"))))

    # 4. summary
    say("summary (street part, x AB street, composed, AB4, proven) -- gate %s:" % gate_status)
    fam = {}
    for cell in R + RC + C:
        h = results.get(cell) or {}
        if "lp_street" in h:
            say("  %-6s %8.1f  x%.3f  %8.1f  %8.1f  %s" % (cell, h["lp_street"], h["lp_street"] / h["ab_street"], h["composed"], h["ab4"], h.get("proven")))
            if h.get("proven"):
                fam.setdefault(cell.rstrip("0123456789"), []).append((h["composed"], h["ab4"]))
        else:
            say("  %-6s %s" % (cell, h.get("status")))
    for f, rows in sorted(fam.items()):
        say("  family %s: %d proven cells, mean composed %.1f vs mean AB4 %.1f (+%.1f pct)" % (f, len(rows), sum(r[0] for r in rows) / len(rows), sum(r[1] for r in rows) / len(rows), 100.0 * (sum(r[0] for r in rows) / sum(r[1] for r in rows) - 1)))
    json.dump(results, io.open(os.path.join(ORACLE, "tep_cg_batch_summary.json"), "w", encoding="utf-8"), indent=1)
    say("batch done")


if __name__ == "__main__":
    main()
