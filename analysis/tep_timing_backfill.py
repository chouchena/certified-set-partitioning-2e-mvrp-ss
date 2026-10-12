"""Backfill the missing per-stage SECONDS without touching a single banked solution. (2026-09-27)

WHY. 226 of 491 banked artifacts carry no `secs` (every floor artifact at n10, n20, n30 and n100, and the ceil
artifacts at n30, all written before the stamp existed). The consequence is not cosmetic: our TIME TO BEST is the
charged seconds up to the stage that produced the incumbent, and on most cells that stage is one of the unstamped
ones, so the quantity reads 0 s -- missing data reported as a number. The predecessors publish time-to-incumbent
per instance at |C| = 20 and 30, so this is a column the paper must be able to fill honestly or not at all.

WHAT THIS DOES, AND WHAT IT REFUSES TO DO. It RE-RUNS the stage on the same inputs with the same code, times it,
and asserts the objective REPRODUCES the banked value to 1e-6. The banked artifact is never overwritten: the
timing lands in runs/oracle/tep_timing_backfill_n<size>.json alongside the reproduction check. A cell that does
not reproduce is a finding (non-determinism in a stage we present as deterministic) and is listed, not smoothed.

Only the two selection routes are backfilled here, because they are the ones that lack seconds and that the
time-to-best depends on: floor (tep_chain_own_water) and ceil (--primal-round). Both read a master-IP selection
that is already on disk, so no column generation is repeated and the timing is of the chaining + water stages
exactly as the pipeline runs them.

    python analysis/tep_timing_backfill.py --size 20 [--cells C201 C202]
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

PY = sys.executable
CELLS = ["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)] + ["RC%d" % i for i in range(201, 209)]


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True); ap.add_argument("--cells", nargs="*", default=None)
    ap.add_argument("--stages", nargs="*", default=["floor", "ceil"])
    a = ap.parse_args()
    cells = a.cells or CELLS
    out = os.path.join(ROOT, "runs", "oracle", "tep_timing_backfill_n%d.json" % a.size)
    prev = load(out); rows = prev["rows"] if prev else []
    done = {(r["cell"], r["stage"]) for r in rows}
    print("timing backfill at n%d: %d cell(s), stages %s; %d already done" % (a.size, len(cells), a.stages, len(done)), flush=True)
    for c in cells:
        for stage in a.stages:
            if (c, stage) in done: continue
            sub = "" if stage == "floor" else "ceil"
            p = os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (c, a.size))
            banked = load(p)
            if not banked:
                continue
            if isinstance(banked.get("secs"), (int, float)):
                rows.append(dict(cell=c, stage=stage, secs=float(banked["secs"]), source="already stamped", reproduces=True)); continue
            keep = io.open(p, "rb").read()                       # the banked artifact is restored byte for byte afterwards
            cmd = [PY, "analysis/tep_chain_own_water.py", c, "--size", str(a.size)] + (["--primal-round"] if stage == "ceil" else [])
            log = os.path.join(ROOT, "logs", "timing_%s_%s_n%d.out" % (stage, c, a.size))
            t0 = time.time()
            with io.open(log, "w", encoding="utf-8", errors="replace") as fh:
                rc = subprocess.call(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
            secs = time.time() - t0
            fresh = load(p)
            repro = bool(fresh) and abs(float(fresh["objVal"]) - float(banked["objVal"])) <= 1e-6
            io.open(p, "wb").write(keep)                          # never let a timing run change a banked result
            rows.append(dict(cell=c, stage=stage, secs=round(secs, 1), rc=rc, banked=float(banked["objVal"]),
                             rerun=(float(fresh["objVal"]) if fresh else None), reproduces=repro, source="re-run"))
            print("  %-6s %-5s %7.1f s | banked %10.3f | re-run %10s | %s" % (c, stage, secs, banked["objVal"],
                  ("%.3f" % fresh["objVal"]) if fresh else "-", "reproduces" if repro else "DOES NOT REPRODUCE"), flush=True)
            json.dump(stamped(dict(size=a.size, rows=rows)), io.open(out, "w", encoding="utf-8"), indent=1, default=str)
    bad = [r for r in rows if not r.get("reproduces")]
    print("\n  %d row(s); %d do not reproduce%s" % (len(rows), len(bad), (": " + ", ".join("%s/%s" % (r["cell"], r["stage"]) for r in bad)) if bad else ""))
    print("  wrote %s" % os.path.relpath(out, ROOT))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
