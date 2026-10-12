"""The ceil-rounded primal across the n30 grid, against the floor route and against K. (d459)

WHY. The forced-diversity sample was refuted on 2026-09-25 -- round 0 reproduced the banked value
exactly on 6 of 6 cells, so the floor route's selection was already its master's integer optimum and
the n30 tail is neither a ranking nor a pool problem. Decomposing the tail said what it is: C203
realised 1007.979 against their 843.6, a gap of 164.4 of which the third car costs 140.2. Water is
under 6% of the objective at n30 and cannot account for it. The tail gap is ONE EXTRA CAR.

Ceil-rounded arrival buckets are the recorded fix for the fleet undercount -- a RESTRICTION whose
integer solutions are timeable (d414), adopted at n10 and n20 and rejected at n100 (P5). It had
never been run at n30. The two-cell probe pre-registered in `validation/PREREG_ceil_at_n30.md`
passed all three gates: C203 1007.979 -> 840.860 and C206 1024.133 -> 875.054, both dropping from
three cars to two, both verifier3 clean.

WHAT THIS DRIVER ADDS over a shell loop, per CLAUDE.md section 4:
  * it checks each step's artifact exists and carries provenance before using it;
  * it HALTS on a solution below a PROVEN optimum, which would be a defect and not a win;
  * a failed cell is recorded and skipped, never silently absorbed into a mean;
  * the floor route's artifacts are never touched -- ceil banks under runs/postpass/ceil/.

    python analysis/tep_ceil_n30_batch.py            # all 27
    python analysis/tep_ceil_n30_batch.py --cells R201 R202
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
from k_comparison import k_best_incumbent
from stamp import stamped

_pre = argparse.ArgumentParser(add_help=False); _pre.add_argument("--size", type=int, default=30, choices=(10, 20, 30, 50, 100))
SIZE = _pre.parse_known_args()[0].size   # 2026-09-26 (d501): was hard-coded 30; the ceil route had never been chained at n10/n20
CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
PY = sys.executable


def ceil_path(cell):
    return os.path.join(ROOT, "runs", "postpass", "ceil", "ownwater_%s_n%d.json" % (cell, SIZE))


def floor_path(cell):
    return os.path.join(ROOT, "runs", "postpass", "ownwater_%s_n%d.json" % (cell, SIZE))


def sel_path(cell):
    # tep_cg_bound names n100 artifacts WITHOUT a size suffix (its default size); every other size carries _n<size>
    return os.path.join(ROOT, "runs", "oracle", ("tep_cg_bound_%s_ip_primal.json" % cell) if SIZE == 100 else ("tep_cg_bound_%s_n%d_ip_primal.json" % (cell, SIZE)))


def step(cmd, log):
    with io.open(os.path.join(ROOT, log), "w", encoding="utf-8", errors="replace") as fh:
        return subprocess.call(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="*", default=None)
    ap.add_argument("--ip-work", type=float, default=60.0)
    ap.add_argument("--redo", action="store_true", help="re-run cells that already have a ceil artifact")
    ap.add_argument("--size", type=int, default=SIZE, choices=(10, 20, 30, 50, 100))   # consumed by the pre-parser; declared so parse_args accepts it
    a = ap.parse_args()
    cells = a.cells or CELLS
    _kts = json.load(io.open(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json"), encoding="utf-8"))
    kt = {r["cell"]: r for r in _kts["n%d" % SIZE]["rows"]} if ("n%d" % SIZE) in _kts else {}   # n50/n100: K publish no per-cell value, so no per-cell gate; the family/pool tables compare
    rows, defects = [], []
    for c in cells:
        t0 = time.time()
        if a.redo or not os.path.exists(sel_path(c)):
            # n100 (2026-09-26, d516): mirror the FLOOR arm command exactly (600 s CG wall, 600 s IP wall, 1 thread) so the two roundings are symmetric legs
            cg_args = (["--ng", "10", "--start-states", "--ip", "--ip-threads", "1", "--ip-time", "600", "--max-secs", "600", "--primal-round"] if SIZE == 100
                       else ["--ip", "--primal-round", "--start-states", "--ip-work", str(a.ip_work)])
            rc = step([PY, "analysis/tep_cg_bound.py", c, "--size", str(SIZE)] + cg_args, ("logs/ceil30_cg_%s.out" % c) if SIZE == 30 else ("logs/ceil_n%d_cg_%s.out" % (SIZE, c)))
            if rc != 0 or not os.path.exists(sel_path(c)):
                rows.append(dict(cell=c, failed="ceil master/IP (exit %s)" % rc)); print("  %-6s FAILED at the master IP" % c, flush=True); continue
        if a.redo or not os.path.exists(ceil_path(c)):
            rc = step([PY, "analysis/tep_chain_own_water.py", c, "--size", str(SIZE), "--primal-round"],
                      ("logs/ceil30_chain_%s.out" % c) if SIZE == 30 else ("logs/ceil_n%d_chain_%s.out" % (SIZE, c)))
            if rc != 0 or not os.path.exists(ceil_path(c)):
                rows.append(dict(cell=c, failed="chaining or verifier (exit %s)" % rc)); print("  %-6s FAILED at chaining/verifier" % c, flush=True); continue
        d = json.load(io.open(ceil_path(c), encoding="utf-8"))
        if not d.get("_provenance", {}).get("code_hash"):
            rows.append(dict(cell=c, failed="artifact carries no code_hash")); continue
        fl = json.load(io.open(floor_path(c), encoding="utf-8")) if os.path.exists(floor_path(c)) else None
        kb, which = k_best_incumbent(c, SIZE)
        r = dict(cell=c, ceil=float(d["objVal"]), ceil_cars=int(d["nCars"]), ceil_vessels=int(d["nVessel"]),
                 floor=(float(fl["objVal"]) if fl else None), floor_cars=(int(fl["nCars"]) if fl else None),
                 theirs=kb, which=which, proven=bool(kt[c]["proven"]) if c in kt else False, their_lb=(float(kt[c]["k_bound"]) if c in kt else None),
                 secs=round(time.time() - t0))
        r["vs_theirs"] = 100.0 * (r["ceil"] / kb - 1) if kb else None
        r["vs_floor"] = 100.0 * (r["ceil"] / r["floor"] - 1) if r["floor"] else None
        if r["proven"] and r["ceil"] < kb - 0.05:
            defects.append(c)
        if r["their_lb"] is not None and r["ceil"] < r["their_lb"] - 0.05:
            defects.append(c + " (below their published bound)")
        rows.append(r)
        print("  %-6s ceil %9.3f (%d cars) vs floor %9s (%s cars) vs theirs %8s | %7s them, %+7.2f%% floor  [%ds]"
              % (c, r["ceil"], r["ceil_cars"], ("%.3f" % r["floor"]) if r["floor"] else "-",
                 r["floor_cars"] if r["floor_cars"] else "-", ("%.1f" % kb) if kb else "n/a", ("%+.2f%%" % r["vs_theirs"]) if r["vs_theirs"] is not None else "n/a", r["vs_floor"] or 0.0, r["secs"]), flush=True)
        if defects:
            print("\n  *** HALTING: %s is below a PROVEN optimum or a published bound -- a DEFECT, not a win ***"
                  % ", ".join(defects), flush=True)
            break
        json.dump(stamped(dict(size=SIZE, rows=rows)),
                  io.open(os.path.join(ROOT, "runs", "oracle", "tep_ceil_n%d_batch.json" % SIZE), "w", encoding="utf-8"),
                  indent=1, default=str)

    ok = [r for r in rows if not r.get("failed")]
    bad = [r for r in rows if r.get("failed")]
    print("\n  %d cell(s) run: %d produced a verified ceil solution, %d failed" % (len(rows), len(ok), len(bad)))
    for r in bad:
        print("    FAILED %-6s %s" % (r["cell"], r["failed"]))
    if ok:
        import statistics as st
        both = [r for r in ok if r["floor"]]
        better = [r for r in both if r["ceil"] < r["floor"] - 0.05]
        worse = [r for r in both if r["ceil"] > r["floor"] + 0.05]
        fewer = [r for r in both if r["ceil_cars"] < r["floor_cars"]]
        below = [r for r in ok if r["vs_theirs"] is not None and r["vs_theirs"] < 0]
        print("    ceil beats floor on %d of %d, loses on %d, uses FEWER CARS on %d"
              % (len(better), len(both), len(worse), len(fewer)))
        vt = sorted(r["vs_theirs"] for r in ok if r["vs_theirs"] is not None)
        if vt:
            print("    vs their best: median %+.2f%%, best %+.2f%%, worst %+.2f%% | BELOW them on %d of %d"
                  % (st.median(vt), vt[0], vt[-1], len(below), len(vt)))
        else:
            print("    no per-cell K value at n%d: compare in the family/pool tables" % SIZE)
        if both:
            vf = sorted(r["vs_floor"] for r in both)
            print("    vs the floor route: median %+.2f%%, best %+.2f%%" % (st.median(vf), vf[0]))
    if defects:
        print("    *** DEFECTS: %s ***" % ", ".join(defects))
    print("  wrote runs/oracle/tep_ceil_n%d_batch.json" % SIZE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
