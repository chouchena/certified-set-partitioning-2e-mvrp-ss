"""The eight remaining |C|=50 R cells at a raised label cap, one at a time, each checked.

WHY. Nine n50 R cells have no elementary certificate. d558 diagnosed the cause -- the elementary
pricing pass exhausts its 3,000,000 label cap, so the CAP and not the clock binds -- and named
the decider: "the R202 probe at a 12M cap, which decides between 'raise the cap' and 'implement
dominance'". That probe was pre-registered on 2026-09-27 and never run. Run 2026-09-29 it CLOSED:
3,048,768 labels, no exhaustion, PROVEN True, LP street 1377.7 in 137 s. The old cap was cutting
R202 off by 1.6 per cent.

WHAT THIS DOES NOT ASSUME. One cell does not generalise, and OPEN_GAPS G1 says why: the pass has
no superset dominance, so the state count is the number of reachable (last, visited-set) pairs,
and "more budget does not fix a missing dominance rule" -- the 12M retry on R211 at n100 exhausted
anyway, with best reduced cost still -5.67. The nine are also not homogeneous: R202 hit the cap in
111 s, R208 took 6,970 s. So this run is a COUNT, not a claim: how many of the eight close at 12M.
Cells that still exhaust are evidence FOR dominance, not against the cap.

DESIGN, declared before the run.
  SCOPE     R203, R204, R206, R207, R209, R210, R211, and R208 LAST because it is the slowest
            by two orders of magnitude and should not block the cheap information.
  COMMAND   identical to the R202 probe in every respect except the cell -- uniform variant (C1).
  BUDGET    --max-secs 3600 per cell as a backstop, not a target. The cap is what binds.
  SEQUENTIAL one solver job at a time (the co-tenancy rule).
  CHECKED   after each cell the artifact is re-read and bound_certificate.certified() asked. A
            step that produces no certificate is reported as INCONCLUSIVE, not as a failure --
            they are different, and conflating them is a recorded defect of this project.

    python analysis/n50_bigcap_batch.py
"""
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from bound_certificate import certified, ng_certified, why_not
from stamp import stamped

CELLS = ["R203", "R204", "R206", "R207", "R209", "R210", "R211", "R208"]
CAP = 12_000_000
SIZE = 50


def artifacts(cell):
    """Every artifact that genuinely belongs to this cell at this size.

    Was a hand-built single path, which single_authority correctly flagged: that is the defect
    class that cost bound_source 85 of 135 cells. best_known.bound_artifacts applies the two
    filters that make the patterns correct -- the artifact's own size field must match, and
    INVALID_ files are skipped.
    """
    from best_known import bound_artifacts
    return bound_artifacts(cell, SIZE)


def main():
    print("n50 R CELLS AT A %s LABEL CAP -- %d cells, sequential\n" % ("{:,}".format(CAP), len(CELLS)))
    print("  R202 already closed at 3,048,768 labels (137 s). This measures how many of the")
    print("  rest do the same. A cell that still exhausts is evidence FOR dominance (G1).\n")
    rows = []
    for i, cell in enumerate(CELLS, 1):
        log = os.path.join(ROOT, "logs", "n50_bigcap_%s.out" % cell)
        cmd = [sys.executable, os.path.join(ROOT, "analysis", "tep_cg_bound.py"), cell,
               "--size", str(SIZE), "--ip", "--start-states",
               "--label-cap", str(CAP), "--max-secs", "3600"]
        print("  [%d/%d] %-6s launching ..." % (i, len(CELLS), cell), flush=True)
        t0 = time.time()
        with io.open(log, "w", encoding="utf-8") as lf:
            rc = subprocess.call(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=ROOT)
        secs = round(time.time() - t0, 1)

        rec = dict(cell=cell, size=SIZE, label_cap=CAP, exit_code=rc, secs=secs,
                   log=os.path.relpath(log, ROOT))
        # A4 (2026-09-29): report the artifact THIS RUN produced, identified by mtime against
        # the run's own start, NOT the strongest artifact on disk. The first version took the
        # max by lp_street, so when R204 died with MemoryError after 20,315 s the row was filled
        # from an OLD 3M-cap artifact and read "still exhausts, 3,000,001 labels" -- a crash
        # reported as a result. A non-zero exit is now recorded as a crash, with the tail of the
        # log, and no artifact is attributed to it.
        d = None
        if rc != 0:
            tail = ""
            try:
                tail = "".join(io.open(log, encoding="utf-8", errors="replace").readlines()[-3:])
            except Exception:
                pass
            rec["crashed"] = True
            rec["error"] = "exit %d: %s" % (rc, tail.strip()[-160:])
        else:
            try:
                fresh = [(q, e) for q, e in artifacts(cell)
                         if e.get("lp_street") is not None and not e.get("primal_rounding")
                         and not e.get("drop") and os.path.getmtime(q) >= t0 - 1.0]
                if fresh:
                    _q, d = max(fresh, key=lambda t: os.path.getmtime(t[0]))
                    rec["artifact"] = os.path.relpath(_q, ROOT)
                else:
                    rec["error"] = "exit 0 but no artifact newer than the run start"
            except Exception as e:
                rec["error"] = "artifacts unreadable: %s" % type(e).__name__
        if d is not None:
            h = d.get("hist") or []
            elem = [x for x in h if str(x.get("tag", "")).strip().upper().startswith("ELEM")]
            last = elem[-1] if elem else {}
            rec.update(lp_street=d.get("lp_street"), proven=d.get("proven"),
                       status=d.get("status"), certified=bool(certified(d)),
                       ng_certified=bool(ng_certified(d)),
                       elem_labels=last.get("labels"), elem_exhausted=last.get("exhausted"),
                       elem_cand=last.get("cand"), why_not=None if certified(d) else why_not(d))
        verdict = ("CRASHED" if rec.get("crashed") else
                   "CERTIFIED" if rec.get("certified") else
                   "still exhausts" if rec.get("elem_exhausted") else
                   "INCONCLUSIVE")
        print("        %-6s %-14s %7.0fs  labels %-11s lp_street %-9s %s"
              % (cell, verdict, secs, rec.get("elem_labels"),
                 ("%.1f" % rec["lp_street"]) if rec.get("lp_street") else "-",
                 "" if rec.get("certified") else str(rec.get("why_not") or "")[:48]), flush=True)
        rows.append(rec)
        # write after EVERY cell: a kill must not lose the ones already done
        p = os.path.join(ROOT, "runs", "oracle", "n50_bigcap_batch.json")
        tmp = p + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(stamped(dict(rows=rows, label_cap=CAP, size=SIZE, cells=CELLS,
                                   complete=(i == len(CELLS))),
                              "analysis/n50_bigcap_batch.py", "analysis/tep_cg_bound.py",
                              "analysis/tep_pricer.py", "analysis/bound_certificate.py"),
                      f, indent=1, default=str)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, p)

    cert = [r for r in rows if r.get("certified")]
    exh = [r for r in rows if r.get("elem_exhausted")]
    print("\n  CERTIFIED %d of %d | still exhausting %d" % (len(cert), len(rows), len(exh)))
    if cert:
        print("  labels used by the cells that closed: %s"
              % sorted(r["elem_labels"] for r in cert if r.get("elem_labels")))
    if exh:
        print("  STILL EXHAUSTING AT %s: %s -- these are evidence for superset dominance (G1),"
              % ("{:,}".format(CAP), ", ".join(r["cell"] for r in exh)))
        print("  not for a bigger cap.")
    print("  wrote runs/oracle/n50_bigcap_batch.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
