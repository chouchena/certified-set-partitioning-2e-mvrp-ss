"""Drive `tep_arbiter_cell` over the grid and aggregate (d437).

Audit: `validation/runaudits/TEP_arbiter_panel_n10.md`. The reading is fixed there; this script
only runs the cells and prints what the audit asks for.

    python analysis/tep_arbiter_panel.py --size 10 --workers 4
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=10); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cells", default=None); ap.add_argument("--skip-done", action="store_true")
    a = ap.parse_args()
    cells = a.cells.split(",") if a.cells else list(CELLS)
    outdir = os.path.join(ROOT, "runs", "oracle", "arbiter")
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    logdir = os.path.join(ROOT, "logs", "arbiter")
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    todo = []
    for c in cells:
        p = os.path.join(outdir, "arb_%s_n%d.json" % (c, a.size))
        if a.skip_done and os.path.exists(p):
            continue
        todo.append(c)
    print("%d cells to run, %d workers, size n%d" % (len(todo), a.workers, a.size), flush=True)
    running = []
    t0 = time.time()
    while todo or running:
        while todo and len(running) < a.workers:
            c = todo.pop(0)
            lg = io.open(os.path.join(logdir, "arb_%s_n%d.out" % (c, a.size)), "w", encoding="utf-8")
            pr = subprocess.Popen([sys.executable, os.path.join(ROOT, "analysis", "tep_arbiter_cell.py"),
                                   c, "--size", str(a.size)], stdout=lg, stderr=subprocess.STDOUT, cwd=ROOT)
            running.append((c, pr, lg)); print("  started %s" % c, flush=True)
        time.sleep(3)
        for item in list(running):
            c, pr, lg = item
            if pr.poll() is not None:
                lg.close(); running.remove(item)
                print("  %-6s exit %d  (%.0fs elapsed)" % (c, pr.returncode, time.time() - t0), flush=True)
    # ---- aggregate -------------------------------------------------------------------
    rows = []
    for c in cells:
        p = os.path.join(outdir, "arb_%s_n%d.json" % (c, a.size))
        if not os.path.exists(p):
            print("  %-6s NO ARTIFACT" % c); continue
        rows.append(json.load(io.open(p, encoding="utf-8")))
    live = [r for r in rows if not r.get("skipped")]
    print("\n%-7s %6s %11s %11s %9s %6s %11s %9s %6s" %
          ("cell", "delta", "exact E", "old CG", "old-E %", "neg", "new CG", "new-E %", "neg"))
    ref_old = ref_new = 0
    for r in sorted(live, key=lambda x: x["cell"]):
        E = r["exact_elementary_lp"]; o, n = r["old"], r["new"]
        ref_old += bool(o["refuted"]); ref_new += bool(n["refuted"])
        print("%-7s %6.0f %11.4f %11.4f %+8.3f%% %6d %11.4f %+8.3f%% %6d%s%s" %
              (r["cell"], r["delta"], E, o["value"], 100.0 * (o["value"] / E - 1), o["negatives"],
               n["value"], 100.0 * (n["value"] / E - 1), n["negatives"],
               "  OLD-REFUTED" if o["refuted"] else "", "  NEW-REFUTED" if n["refuted"] else ""))
    skipped = [r["cell"] for r in rows if r.get("skipped")]
    print("\n  cells compared %d; skipped (enumeration too large) %d %s" % (len(live), len(skipped), skipped))
    print("  ORIGINAL pricer refuted on %d of %d cells; START-STATE pricer refuted on %d of %d"
          % (ref_old, len(live), ref_new, len(live)))
    if live:
        wo = max(100.0 * (r["old"]["value"] / r["exact_elementary_lp"] - 1) for r in live)
        wn = max(100.0 * (r["new"]["value"] / r["exact_elementary_lp"] - 1) for r in live)
        print("  largest over-statement: original %+.3f%%, start-state %+.3f%%" % (wo, wn))
        print("  mean seconds: exact %.0f, original %.0f, start-state %.0f"
              % (sum(r["exact_secs"] for r in live) / len(live),
                 sum(r["old"]["secs"] for r in live) / len(live),
                 sum(r["new"]["secs"] for r in live) / len(live)))
    summary = os.path.join(outdir, "panel_n%d.json" % a.size)
    json.dump(dict(size=a.size, cells=rows, refuted_old=ref_old, refuted_new=ref_new,
                   compared=len(live), skipped=skipped), io.open(summary, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(summary, ROOT))


if __name__ == "__main__":
    main()
