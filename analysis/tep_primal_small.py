"""The TEP primal route at the small sizes, against K's published numbers (d439).

Audit: `validation/runaudits/TEP_primal_small_n.md`. The reading is fixed there; this driver only
runs the cells and reports what the audit asks for.

Per cell: column generation with start-state pricing, the master IP for the trip partition, exact
continuous-time chaining, exact re-timing, `verifier3`. At n10 every one of K's 27 cells is proven
optimal, so this is the only size where a primal method can be read against truth rather than
against a previous best-known.

    python analysis/tep_primal_small.py --size 10 --workers 4
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

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])


K_TOL = 0.05   # K publish objectives to one decimal; half a unit in the last place


def k_row(size, cell):
    p = os.path.join(ROOT, "runs", "oracle", "k_targets_small.json")
    if not os.path.exists(p):
        return None
    d = json.load(io.open(p, encoding="utf-8")).get("n%d" % size)
    if not d:
        return None
    for r in d["rows"]:
        if r["cell"] == cell:
            return r
    return None


def one(cell, size, ip_time, chain_cap, retime_cap, logdir, cg_secs=0.0, tag=""):
    """Selection then chaining, as two subprocesses so one cell cannot take the batch down."""
    log = os.path.join(logdir, "primal_%s_n%d.out" % (cell, size))
    with io.open(log, "w", encoding="utf-8") as lg:
        t0 = time.time()
        rc1 = subprocess.call([sys.executable, os.path.join(ROOT, "analysis", "tep_cg_bound.py"), cell,
                               "--size", str(size), "--ng", "10", "--start-states", "--ip",
                               "--ip-threads", "1", "--ip-time", str(ip_time)]
                              + (["--max-secs", str(cg_secs)] if cg_secs else []),
                              stdout=lg, stderr=subprocess.STDOUT, cwd=ROOT)
        lg.write("\n== selection exit %d after %.0fs ==\n" % (rc1, time.time() - t0)); lg.flush()
        if rc1 != 0:
            return dict(cell=cell, size=size, stage="selection", ok=False, rc=rc1)
        rc2 = subprocess.call([sys.executable, os.path.join(ROOT, "analysis", "tep_ip_chain.py"), cell,
                               "--size", str(size), "--cap", str(chain_cap),
                               "--retime-cap", str(retime_cap), "--work", "120"]
                              + (["--tag", tag] if tag else []),
                              stdout=lg, stderr=subprocess.STDOUT, cwd=ROOT)
        lg.write("\n== chaining exit %d, total %.0fs ==\n" % (rc2, time.time() - t0))
    return dict(cell=cell, size=size, stage="chain", ok=(rc2 == 0), rc=rc2, secs=round(time.time() - t0, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=10); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cells", default=None)
    ap.add_argument("--aggregate-only", action="store_true",
                    help="re-read the banked artifacts and re-apply the gate, solving nothing")
    ap.add_argument("--ip-time", type=float, default=None)
    ap.add_argument("--chain-cap", type=float, default=None)
    ap.add_argument("--retime-cap", type=float, default=None)
    ap.add_argument("--cg-secs", type=float, default=0.0,
                    help="cap the column generation; at n100 the pool is a POOL, not a proof (audit section 2)")
    ap.add_argument("--tag", default="", help="bank as ipchain<TAG>_<cell>_n<size>.json so a batch cannot overwrite a banked result")
    a = ap.parse_args()
    ip_time = a.ip_time if a.ip_time else (120.0 if a.size <= 10 else 300.0)
    chain_cap = a.chain_cap if a.chain_cap else (120.0 if a.size <= 10 else 300.0)
    retime_cap = a.retime_cap if a.retime_cap else (120.0 if a.size <= 10 else 240.0)
    cells = a.cells.split(",") if a.cells else list(CELLS)
    logdir = os.path.join(ROOT, "logs", "primal_small")
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    print("TEP primal route at n%d: %d cells, %d workers, caps ip %.0f chain %.0f retime %.0f"
          % (a.size, len(cells), a.workers, ip_time, chain_cap, retime_cap), flush=True)

    import threading
    lock = threading.Lock(); todo = list(cells); done = []

    def worker():
        while True:
            with lock:
                if not todo:
                    return
                c = todo.pop(0)
            r = one(c, a.size, ip_time, chain_cap, retime_cap, logdir, cg_secs=a.cg_secs, tag=a.tag)
            with lock:
                done.append(r)
                print("  %-6s %s (%s)" % (c, "ok" if r.get("ok") else "FAILED at " + r["stage"],
                                          ("%.0fs" % r["secs"]) if r.get("secs") else "-"), flush=True)

    if a.aggregate_only:
        print("  aggregate-only: nothing solved, re-reading the banked artifacts", flush=True)
    else:
        ths = [threading.Thread(target=worker) for _ in range(a.workers)]
        t0 = time.time()
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        print("\n  batch finished in %.0f s" % (time.time() - t0), flush=True)

    # ---- read against the audit's table ----------------------------------------------
    rows = []
    for c in cells:
        p = os.path.join(ROOT, "runs", "postpass", "ipchain%s_%s_n%d.json" % (a.tag, c, a.size))
        kr = k_row(a.size, c)
        if not os.path.exists(p):
            rows.append(dict(cell=c, verified=False, obj=None, k_inc=(kr or {}).get("k_inc"),
                             proven=(kr or {}).get("proven"))); continue
        sol = json.load(io.open(p, encoding="utf-8"))
        obj = float(sol["objVal"])
        ki = float(kr["k_inc"]) if kr and kr.get("k_inc") is not None else None
        rows.append(dict(cell=c, verified=True, obj=obj, cars=sol.get("nCars"), k_inc=ki,
                         k_bound=(float(kr["k_bound"]) if kr and kr.get("k_bound") is not None else None),
                         proven=bool(kr and kr.get("proven")),
                         pct=(100.0 * (obj / ki - 1) if ki else None)))
    print("\n%-7s %10s %6s %10s %8s %9s %s" % ("cell", "TEP obj", "cars", "K inc", "proven", "vs K %", "note"))
    below = at = above = 0
    defect = improve = contra = 0
    for r in rows:
        if not r["verified"]:
            print("%-7s %10s %6s %10s %8s %9s %s"
                  % (r["cell"], "-", "-", ("%.2f" % r["k_inc"]) if r["k_inc"] else "-",
                     r["proven"], "-", "NOT VERIFIED")); continue
        note = ""
        if r["pct"] is not None:
            # K publish to ONE DECIMAL, so nothing finer than half a unit in the last place is a
            # real difference. The first n10 batch flagged C204, R208 and RC206 as "below a proven
            # optimum" on margins of 0.031 to 0.042 -- pure rounding, and the gate was mine, set
            # finer than the data it compares against (d439).
            d = r["obj"] - r["k_inc"]
            if d < -K_TOL:
                if r["proven"]:
                    note = "BELOW A PROVEN OPTIMUM -- DEFECT"; defect += 1
                else:
                    note = "IMPROVES K's incumbent"; improve += 1
                    if r["k_bound"] is not None and r["obj"] < r["k_bound"] - 1e-6:
                        note += "  *** BUT BELOW K's OWN BOUND -- CONTRADICTION ***"; contra += 1
                below += 1
            elif abs(d) <= K_TOL:
                note = "attains (within K's 0.1 publication precision)"; at += 1
            else:
                above += 1
        print("%-7s %10.3f %6s %10.2f %8s %+8.3f%% %s"
              % (r["cell"], r["obj"], r["cars"], r["k_inc"] or float("nan"), r["proven"],
                 r["pct"] if r["pct"] is not None else float("nan"), note))
    nv = sum(1 for r in rows if r["verified"])
    print("\n  VERIFIED %d of %d cells" % (nv, len(rows)))
    print("  of those: attains K %d, above K %d, below K %d" % (at, above, below))
    print("    below splits into %d IMPROVEMENT(S) on an unproven incumbent and %d DEFECT(S) below a proven optimum"
          % (improve, defect))
    pos = [r for r in rows if r["verified"] and r["pct"] is not None and (r["obj"] - r["k_inc"]) > K_TOL]
    if pos:
        print("  above-K distribution: mean %+.3f%%, worst %+.3f%%"
              % (sum(r["pct"] for r in pos) / len(pos), max(r["pct"] for r in pos)))
        # the fleet term dominates at small n: report the excess in whole cars, which is what
        # separated the four outliers at n10 from the other eighteen
        try:
            import verifier3 as _V
            from k_comparison import k_proximity as _kp
            pen = float(_V.load_instance(pos[0]["cell"], a.size, _kp(a.size)).penalty_cars)
            hard = [r for r in pos if (r["obj"] - r["k_inc"]) / pen >= 0.8]
            if hard:
                print("  of those, %d cell(s) are excess >= 0.8 of one car penalty (%.1f): %s"
                      % (len(hard), pen, ", ".join(r["cell"] for r in hard)))
                soft = [r for r in pos if r not in hard]
                if soft:
                    print("  the remaining %d: mean %+.3f%%, worst %+.3f%%"
                          % (len(soft), sum(r["pct"] for r in soft) / len(soft), max(r["pct"] for r in soft)))
        except Exception as e:
            print("  (fleet-term split unavailable: %s)" % type(e).__name__)
    if defect:
        print("  *** %d cell(s) below a PROVEN optimum. Per the audit this is a DEFECT to diagnose, not a win. ***" % defect)
    if contra:
        print("  *** %d cell(s) below K's OWN PUBLISHED BOUND. That is a contradiction and a HARD STOP. ***" % contra)
    if improve and not defect and not contra:
        imp = [r for r in rows if r["verified"] and r["pct"] is not None and (r["obj"] - r["k_inc"]) < -K_TOL]
        print("  improvements on K's unproven incumbents: %s"
              % ", ".join("%s %+.2f%%" % (r["cell"], r["pct"]) for r in sorted(imp, key=lambda x: x["pct"])))
    out = os.path.join(ROOT, "runs", "oracle", "tep_primal_small_n%d.json" % a.size)
    from stamp import stamped
    json.dump(stamped(dict(size=a.size, rows=rows, verified=nv, attains=at, above=above, below=below,
                           defects=defect, improvements=improve, contradictions=contra,
                           ip_time=ip_time, chain_cap=chain_cap, retime_cap=retime_cap)),
              io.open(out, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main()
