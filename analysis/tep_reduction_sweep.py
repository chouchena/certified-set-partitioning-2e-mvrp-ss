"""Does the easy-reduction mimic generalise -- across cells and across sizes? (d448)

AUDIT. The lemma is `validation/LEMMA_reduced_street_plus_water.md`; the code path was validated
against pricer-free ground truth on 2026-09-25 (C201, R208, RC208 at n100 reduced to 18 customers,
exact 1340.4500 / 772.0123 / 870.9287, reproduced to four decimals by both pricers with zero
negative reduced costs). This driver adds no new modelling, only a sweep.

THE PROTOCOL, which is the descent's own. `LP_TEP(H) + w(C)` is a valid bound for ANY subset H,
and it RISES as fewer customers are dropped, because removing covering rows can only lower the
master. So the best valid bound is at the smallest drop that still converges. We sweep the drop
downward and keep the last converged value. A run that does not converge yields no bound and is
recorded as such, never as a number.

TWO COLUMNS, AND ONLY ONE IS A BOUND.
  LP(H) + w(C)   converged linear value -- a VALID bound under the lemma
  IP(H) + w(C)   integer optimum over the PRICED POOL -- NOT a bound, an estimate of what
                 branch-and-price would deliver, always optimistic

    python analysis/tep_reduction_sweep.py --size 100 --cells C201,R208,R211,RC208 --drops 60,48,36,24
"""
import argparse
import io
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped


def run_one(cell, size, drop, max_secs, ip_time, logdir):
    log = os.path.join(logdir, "red_%s_n%d_k%d.out" % (cell, size, drop))
    with io.open(log, "w", encoding="utf-8") as lg:
        rc = subprocess.call([sys.executable, os.path.join(ROOT, "analysis", "tep_easy_reduction.py"),
                              cell, "--size", str(size), "--drop", str(drop),
                              "--max-secs", str(max_secs), "--ip-time", str(ip_time)],
                             stdout=lg, stderr=subprocess.STDOUT, cwd=ROOT)
    p = os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_%s_n%d_k%d.json" % (cell, size, drop))
    if rc != 0 or not os.path.exists(p):
        return dict(cell=cell, size=size, drop=drop, failed=True, rc=rc)
    return json.load(io.open(p, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--cells", default="C201,C202,R208,R211,RC207,RC208")
    ap.add_argument("--drops", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-secs", type=float, default=600.0)
    ap.add_argument("--ip-time", type=float, default=300.0)
    a = ap.parse_args()
    if a.drops:
        drops = [int(x) for x in a.drops.split(",")]
    else:
        n = a.size
        drops = [int(round(n * f)) for f in (0.60, 0.48, 0.36, 0.24, 0.12)]
    cells = a.cells.split(",")
    logdir = os.path.join(ROOT, "logs", "reduction")
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    jobs = [(c, d) for c in cells for d in drops]
    print("n%d: %d cells x %d drops = %d runs, %d workers, drops %s"
          % (a.size, len(cells), len(drops), len(jobs), a.workers, drops), flush=True)

    lock = threading.Lock(); todo = list(jobs); done = []

    def worker():
        while True:
            with lock:
                if not todo:
                    return
                c, d = todo.pop(0)
            r = run_one(c, a.size, d, a.max_secs, a.ip_time, logdir)
            with lock:
                done.append(r)
                if r.get("failed"):
                    print("  %-6s k=%-3d FAILED (rc %s)" % (c, d, r.get("rc")), flush=True)
                else:
                    print("  %-6s k=%-3d kept %3d  LP+w %9.2f %s  IP+w %s  (%.0fs)"
                          % (c, d, r["kept"], r["lp_composed"], "valid" if r["proven"] else "UNCONVERGED",
                             ("%9.2f" % r["ip_composed"]) if r.get("ip_composed") else "        -",
                             r["secs"]), flush=True)

    ths = [threading.Thread(target=worker) for _ in range(a.workers)]
    t0 = time.time()
    for t in ths: t.start()
    for t in ths: t.join()
    print("\n  sweep finished in %.0f s" % (time.time() - t0), flush=True)

    # ---- per cell: the best VALID bound, and the best estimate --------------------------
    print("\n%-7s %6s %11s %11s %11s %11s %9s %s"
          % ("cell", "best k", "LP+w valid", "IP+w est", "descent", "arithmetic", "vs desc", "vs arith"))
    summary = {}
    for c in cells:
        rs = [r for r in done if r.get("cell") == c and not r.get("failed") and r.get("proven")]
        if not rs:
            print("%-7s %6s %11s" % (c, "-", "no converged run")); continue
        best = max(rs, key=lambda r: r["lp_composed"])
        est = max((r for r in rs if r.get("ip_composed")), key=lambda r: r["ip_composed"], default=None)
        de, ar = best["descent"], best["arithmetic"]
        print("%-7s %6d %11.2f %11s %11.2f %11.2f %8.3fx %8.3fx"
              % (c, best["drop"], best["lp_composed"],
                 ("%.2f" % est["ip_composed"]) if est else "-", de, ar,
                 best["lp_composed"] / de, best["lp_composed"] / ar))
        summary[c] = dict(best_drop=best["drop"], lp_composed=best["lp_composed"],
                          ip_composed=(est["ip_composed"] if est else None),
                          descent=de, arithmetic=ar,
                          vs_descent=best["lp_composed"] / de, vs_arith=best["lp_composed"] / ar)
    if summary:
        wa = sum(1 for v in summary.values() if v["vs_arith"] > 1)
        wd = sum(1 for v in summary.values() if v["vs_descent"] > 1)
        print("\n  the VALID reduced bound beats the arithmetic bound on %d of %d cells, and the "
              "(excluded) descent on %d" % (wa, len(summary), wd))
    p = os.path.join(ROOT, "runs", "oracle", "tep_reduction_sweep_n%d.json" % a.size)
    json.dump(stamped(dict(size=a.size, drops=drops, runs=done, summary=summary)),
              io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
