"""Integer-car cuts on the TEP bound over all 27 n100 cells, four at a time
(audit validation/runaudits/TEP_intcars_27cells.md; author approved 2026-09-25 06:18).

Each worker runs `analysis/tep_cg_bound.py <cell> --ng 10 --int-cars --check-cap 100000`, which
proves the LP, adds N >= ceil(N_LP), re-proves, and repeats while the proven car count crosses an
integer. Cells are ordered longest-first from the solo batch so the tail is short; a cell with an
existing proven `_intcars` artifact is skipped.

WALLS HERE ARE CO-TENANTED (policy d415): the VALUES are deterministic and unaffected, the walls
are not comparable with solo walls and must never reach the envelope table. Every summary row
carries `cotenanted: <workers>` to make that impossible to forget.

    python analysis/tep_intcars_batch.py [--workers 4] [--cells C201,...] [--dry-run]
"""
import argparse
import concurrent.futures as cf
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

PY = sys.executable
LOGS = os.path.join(ROOT, "logs", "intcars")
ORACLE = os.path.join(ROOT, "runs", "oracle")
CELLS = ["C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208",
         "R201", "R202", "R203", "R204", "R205", "R206", "R207", "R208", "R209", "R210", "R211",
         "RC201", "RC202", "RC203", "RC204", "RC205", "RC206", "RC207", "RC208"]


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def base(cell):
    return load(os.path.join(ORACLE, "tep_cg_bound_%s.json" % cell))


def cut(cell):
    return load(os.path.join(ORACLE, "tep_cg_bound_%s_intcars.json" % cell))


def one(cell):
    t0 = time.time()
    log = os.path.join(LOGS, "%s.out" % cell)
    cmd = [PY, os.path.join(ROOT, "analysis", "tep_cg_bound.py"), cell, "--ng", "10", "--int-cars", "--check-cap", "100000"]
    with io.open(log, "w", encoding="utf-8") as fh:
        fh.write("$ %s\n" % " ".join(cmd)); fh.flush()
        rc = subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT)
    return cell, rc, round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--cells", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    os.makedirs(LOGS, exist_ok=True)
    cells = [c.strip() for c in a.cells.split(",")] if a.cells else list(CELLS)
    todo, done = [], []
    for c in cells:
        r = cut(c)
        (done if (r and r.get("proven")) else todo).append(c)
    # longest first, by the solo base wall where we have one
    todo.sort(key=lambda c: -( (base(c) or {}).get("secs") or 0 ))
    print("%s  integer-car batch: %d cells, %d already proven (%s), %d to run, %d workers"
          % (time.strftime("%H:%M"), len(cells), len(done), ",".join(done) or "-", len(todo), a.workers), flush=True)
    print("  order: %s" % " ".join(todo), flush=True)
    if a.dry_run:
        print("  --dry-run; nothing launched."); return 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for cell, rc, secs in ex.map(one, todo):
            r = cut(cell); b = base(cell)
            if r and r.get("proven"):
                print("%s  %-6s PROVEN %.1f -> composed %.1f (was %.1f, %+.2f%%) | cuts %s | %.0f s co-tenanted"
                      % (time.strftime("%H:%M"), cell, r["lp_street"], r["composed"], (b or {}).get("composed", float("nan")),
                         100.0 * (r["composed"] / b["composed"] - 1) if b else float("nan"),
                         [c["cut"] for c in r.get("int_car_cuts", [])], secs), flush=True)
            else:
                print("%s  %-6s NO PROVEN CUT VALUE (rc %d, %.0f s) -- uncut bound stands" % (time.strftime("%H:%M"), cell, rc, secs), flush=True)
    # ---- summary and the pre-registered reading
    rows, fam = [], {}
    for c in cells:
        b, r = base(c), cut(c)
        if not b:
            continue
        f = "RC" if c.startswith("RC") else c[0]
        ok = bool(r and r.get("proven"))
        row = dict(cell=c, family=f, composed_base=b["composed"], composed_cut=(r["composed"] if ok else None),
                   street_base=b["lp_street"], street_cut=(r["lp_street"] if ok else None),
                   N_base=b["N"], N_cut=(r["N"] if ok else None), cuts=[x["cut"] for x in (r or {}).get("int_car_cuts", [])],
                   proven=ok, secs=(r or {}).get("secs"), cotenanted=a.workers)
        if ok and r["lp_street"] < b["lp_street"] - 1e-6:
            print("  DEFECT: %s cut value %.2f BELOW the uncut %.2f -- a cut cannot lower a bound" % (c, r["lp_street"], b["lp_street"]), flush=True)
            row["defect"] = True
        rows.append(row); fam.setdefault(f, []).append(row)
    print("\n%s  family means (composed):" % time.strftime("%H:%M"))
    verdicts = {}
    for f, rs in sorted(fam.items()):
        bmean = sum(x["composed_base"] for x in rs) / len(rs)
        cmean = sum((x["composed_cut"] or x["composed_base"]) for x in rs) / len(rs)
        rise = 100.0 * (cmean / bmean - 1)
        verdicts[f] = dict(base=bmean, cut=cmean, rise_pct=rise, proven=sum(1 for x in rs if x["proven"]), n=len(rs))
        print("  %-3s %8.1f -> %8.1f  (%+.2f%%), proven with cuts on %d of %d" % (f, bmean, cmean, rise, verdicts[f]["proven"], len(rs)))
    verdict = ("ADOPT" if all(v["rise_pct"] >= 2.0 for v in verdicts.values())
               else "ADOPT PER FAMILY" if any(v["rise_pct"] >= 2.0 for v in verdicts.values()) else "NOT ADOPTED")
    print("  VERDICT (audit section 3): %s   [%.1f h, %d workers]" % (verdict, (time.time() - t0) / 3600, a.workers))
    json.dump(stamped(dict(rows=rows, families=verdicts, verdict=verdict, workers=a.workers,
                           walls_are_cotenanted=True, wall_h=round((time.time() - t0) / 3600, 2)),
                      "analysis/tep_intcars_batch.py", "analysis/tep_cg_bound.py"),
              io.open(os.path.join(ORACLE, "tep_intcars_batch.json"), "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote runs/oracle/tep_intcars_batch.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
