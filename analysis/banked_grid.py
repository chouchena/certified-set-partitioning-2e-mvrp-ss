"""Run tep_cg_banked over the grid, and VERIFY each artifact before moving to the next cell.

    python analysis/banked_grid.py --sizes 10 20 30 50 100 --det-budget 200000

WHY A CHECK AFTER EVERY CELL RATHER THAN A SWEEP AT THE END. On 2026-09-29 a defect in the
event log's `labels` column survived 38 cells and four and a half hours because nothing looked
at an artifact until the run was over. A per-cell gate turns that into one wasted cell. The
grid HALTS on the first artifact that fails; it does not warn and carry on, because every cell
after a failure would be built on the same defect.

WHAT IS CHECKED, and "exhaustivity" is the point -- presence is not enough:

  PROVENANCE   every field present and non-empty: sources, source_hash, code_in_play_hash,
               code_in_play, git_sha, sources_dirty EMPTY, sources_unresolved EMPTY, cpu,
               python, platform, solver_versions. Every hash re-verified against the file on
               disk, so a stale or wrong hash fails rather than merely existing.

  RT TRAJECTORY  events, phases, gates, det_ticks, params all present and non-empty; the event
               log covers EVERY CG iteration (len(events) == len(hist)); both clocks monotone
               non-decreasing; phases start at `start` and end at `run_end`; gates cover every
               iteration; params carry every key the run was invoked with; and improvements is
               consistent with `proven`.

The deciding clock is the DETERMINISTIC label budget. No max_secs is passed, so nothing can be
stopped by the wall and every artifact is reproducible by construction -- gap C's refusal
therefore never fires, which is the intended steady state rather than a bypass.
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
from lb_method_ablation import CELLS
from k_comparison import proven_cells

PROV_REQUIRED = ("sources", "source_hash", "code_in_play_hash", "code_in_play", "git_sha",
                 "python", "platform", "cpu", "solver_versions", "when")
RT_REQUIRED = ("events", "phases", "gates", "det_ticks", "params", "hist")


def _sha(path):
    import hashlib
    try:
        return hashlib.sha256(io.open(path, "rb").read()).hexdigest()[:16]
    except Exception:
        return None


def verify(path):
    """Every failure this artifact has. Empty list means it passed."""
    bad = []
    try:
        d = json.load(io.open(path, encoding="utf-8"))
    except Exception as e:
        return ["unreadable: %s" % type(e).__name__]

    p = d.get("_provenance")
    if not isinstance(p, dict):
        return ["no _provenance"]
    for k in PROV_REQUIRED:
        if not p.get(k):
            bad.append("provenance.%s missing or empty" % k)
    if p.get("sources_dirty"):
        bad.append("sources_dirty NOT empty: %s" % p["sources_dirty"])
    if p.get("sources_unresolved"):
        bad.append("sources_unresolved NOT empty: %s" % p["sources_unresolved"])
    # RE-VERIFY every hash against disk. A recorded hash that no longer matches is worse than
    # an absent one, because it looks like provenance.
    for rel, h in (p.get("code_in_play") or {}).items():
        cur = _sha(os.path.join(ROOT, rel))
        if cur is None:
            bad.append("code_in_play %s not on disk" % rel)
        elif cur != h:
            bad.append("code_in_play %s hash drifted %s -> %s" % (rel, h, cur))
    if not isinstance(d.get("_rt"), dict) or not (d["_rt"].get("det_ticks")):
        bad.append("_rt missing or carries no det_ticks")
    # d47's thread/tenancy rule. This driver produced 55 one-thread artifacts on 2026-09-30
    # without ever asking, because `threads` was in neither required list below. It is asked
    # here now, and the check is on the VALUE.
    rtb = d.get("_rt") or {}
    if rtb.get("rt_class") is None and d.get("secs") is not None:
        bad.append("reports seconds with no _rt.rt_class: nothing decided whether this wall "
                   "is quotable (d47)")
    elif rtb.get("rt_class") == "submission":
        from rt_class import quotable
        ok, why = quotable(d)
        if not ok:
            bad.append("rt_class=submission but %s (d47: 4 threads, single tenancy)" % why)

    for k in RT_REQUIRED:
        v = d.get(k)
        if v is None or (isinstance(v, (list, dict)) and len(v) == 0):
            bad.append("%s missing or empty" % k)
    ev, hist, ph, ga = d.get("events") or [], d.get("hist") or [], d.get("phases") or [], d.get("gates") or []

    # EXHAUSTIVITY: one event per CG iteration, no gaps.
    if len(ev) != len(hist):
        bad.append("events %d != hist %d -- the trajectory does not cover every iteration"
                   % (len(ev), len(hist)))
    if ev:
        for col in ("work", "labels", "t"):
            vals = [e.get(col) for e in ev]
            if any(v is None for v in vals):
                bad.append("events.%s has nulls" % col)
            elif any(vals[i] < vals[i - 1] - 1e-9 for i in range(1, len(vals))):
                bad.append("events.%s NOT monotone -- a clock that runs backwards" % col)
        its = [e.get("it") for e in ev]
        if its != sorted(its):
            bad.append("events are not in iteration order")
    if ph:
        if ph[0].get("phase") != "start":
            bad.append("phases do not begin at `start` (%s)" % ph[0].get("phase"))
        if ph[-1].get("phase") != "run_end":
            bad.append("phases do not end at `run_end` (%s)" % ph[-1].get("phase"))
        for need in ("instance_loaded", "master_and_pricer_built", "seed_columns_added",
                     "cg_loop_start"):
            if not any(x.get("phase") == need for x in ph):
                bad.append("phase %s absent" % need)
    if ga:
        covered = {g.get("it") for g in ga if g.get("it") is not None}
        missing = [h.get("it") for h in hist if h.get("it") not in covered]
        if missing:
            bad.append("gates cover no decision on iterations %s" % missing[:6])
        for g in ga:
            if g.get("decision") is None or g.get("fired") is None:
                bad.append("a gate row lacks fired/decision: %s" % g.get("gate"))
                break
    # improvements must agree with `proven`
    imp = d.get("improvements")
    if d.get("proven") and not imp:
        bad.append("proven but no improvement row recorded")
    if imp and not d.get("proven"):
        bad.append("improvement recorded on an unproven run")
    if d.get("bound_by") == "wall":
        bad.append("wall-decided: not reproducible")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="+", type=int, default=[10, 20, 30, 50, 100])
    ap.add_argument("--cells", nargs="+", default=list(CELLS))
    ap.add_argument("--det-budget", type=int, default=200000)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--ng", type=int, default=10)
    # THE LB LEG IS ONLY RELEVANT OVER K-UNPROVEN CELLS (author, 2026-09-29). Where K publish a
    # gap of exactly 0 the instance is closed and a bound of ours is calibration, not a claim.
    # 35 cells are K-proven: all 27 at |C| = 10, seven at n20 (C201 C205 C206 C208 R201 R205
    # RC201) and one at n30 (C201). The first corrected grid dropped the n10 block and kept the
    # other eight, so its cell list did not match the claim scope.
    ap.add_argument("--all-cells", dest="k_unproven_only", action="store_false", default=True,
                    help="include cells K prove optimal. Calibration only: a bound there is not a claim.")
    a = ap.parse_args()

    # THE CORES REGIME, AT LAUNCH. Printed before the first cell so it is in the log while the
    # run can still be killed, not discovered in the artifacts afterwards -- which is how 55
    # one-thread cells were produced on 2026-09-30.
    from rt_class import regime, banner, SUBMISSION_THREADS, tenancy
    _reg = regime(None, tenancy())
    print(banner(_reg, "declared per cell by the writer"), flush=True)
    if (_reg.get("tenancy") or 2) > 1:
        print("  WARNING: %d python processes alive at launch. A wall measured beside another "
              "solver is the wall of the pair (d47 single tenancy)." % _reg["tenancy"], flush=True)
    print("BANKED GRID -- tep_cg_banked, deterministic budget %s labels, NO wall stop"
          % "{:,}".format(a.det_budget))
    print("  every cell is verified before the next one starts; the grid HALTS on the first failure")
    print("  %-6s %5s %11s %7s %9s %8s %9s %s"
          % ("cell", "size", "lp_street", "proven", "labels", "secs", "verify", "note"), flush=True)
    done, failed = [], None
    t_start = time.time()
    for size in a.sizes:
        skip = set(proven_cells(size)) if a.k_unproven_only else set()
        for cell in a.cells:
            if cell in skip:
                print("  %-6s %5d  K-proven, out of scope" % (cell, size), flush=True)
                continue
            out = os.path.join(ROOT, "runs", "oracle", "tep_cg_banked_%s%s.json"
                               % (cell, "" if size == 100 else "_n%d" % size))
            if os.path.exists(out):
                print("  %-6s %5d  already banked, skipped" % (cell, size), flush=True)
                continue
            cmd = [sys.executable, os.path.join(ROOT, "analysis", "tep_cg_banked.py"), cell,
                   "--size", str(size), "--ng", str(a.ng), "--iters", str(a.iters),
                   "--det-budget", str(a.det_budget)]
            t0 = time.time()
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                tail = (r.stdout or "")[-400:] + (r.stderr or "")[-400:]
                print("  %-6s %5d  RUN FAILED rc=%d\n%s" % (cell, size, r.returncode, tail), flush=True)
                failed = (cell, size, "run exited %d" % r.returncode); break
            if not os.path.exists(out):
                print("  %-6s %5d  NO ARTIFACT WRITTEN" % (cell, size), flush=True)
                failed = (cell, size, "no artifact"); break
            bad = verify(out)
            d = json.load(io.open(out, encoding="utf-8"))
            print("  %-6s %5d %11.4f %7s %9d %8.0f %9s %s"
                  % (cell, size, d.get("lp_street") or 0, d.get("proven"),
                     (d.get("det_ticks") or {}).get("pricer_labels", 0), time.time() - t0,
                     "OK" if not bad else "FAIL", d.get("status")), flush=True)
            if bad:
                for b in bad:
                    print("        *** %s" % b, flush=True)
                failed = (cell, size, "; ".join(bad)); break
            done.append((cell, size))
        if failed:
            break

    print("\n  cells verified %d | wall %.2f h" % (len(done), (time.time() - t_start) / 3600.0))
    if failed:
        print("  HALTED on %s n%d: %s" % failed)
        return 3
    print("  grid complete; every artifact carries full provenance and a complete RT trajectory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
