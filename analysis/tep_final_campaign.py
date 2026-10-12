"""The final campaign: one variant provenance on both legs, every cell, every size. (d533; PREREG_uniform_pipeline.md Amendment 7)

A queue that checks its own steps (CLAUDE.md section 4). Each step is a list of commands over EXISTING drivers, run one at
a time, solo; the queue refuses to start a Gurobi step while the n100 ceil sweep is still writing; every command must exit 0;
after each step the queue asserts the step's summary artifact exists and carries _provenance.code_hash, writes a marker
runs/oracle/campaign/<step>.done, and appends the step record to runs/oracle/tep_final_campaign.json (stamped). A failed
command stops the queue: nothing derives from it. Re-running skips steps with a marker (resumable). The cell lists that
depend on artifacts (which cells still lack a select+chain artifact, which cells trigger the fleet cap) are computed at run
time from our own artifacts -- never from K's values (d505).

BUDGETS, fixed here and identical for every cell of a size (S5 of the PREREG, in seconds): refine wall 120; ALNS wall 1200
(iterations 3000, feasible-stall 600, surrogate scoring); select+chain cap 900 / work 600, pool = floor + ceil partitions
+ 45 LP-positive columns at n10-n50 and the two partitions only at n100 (the LP-column widening re-runs the CG master at
its 420 s wall twice per cell, which the n100 envelope cannot carry); master fleet cap on the K-blind trigger
cars(best primal) - N_LP >= 0.8, cap = cars - 1, rounds 6 / chain cap 600 at n10-n30 and rounds 3 / chain cap 300 /
chain work 150 at n50-n100. Bound legs: default width, --start-states, wall 900 (n50) / 300 (n10, n20).

    python analysis/tep_final_campaign.py --plan                 # print steps, their status and computed cell lists; launch nothing
    python analysis/tep_final_campaign.py --run --only S8a --cells C201    # the cheap test of the queue itself
    python analysis/tep_final_campaign.py --run                  # everything pending, in order
"""
import argparse
import glob
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
DIRS = ("", "ceil", "selchain", "forced", "refine", "alns", "masterip")
MARK = os.path.join(ROOT, "runs", "oracle", "campaign")
SUMMARY = os.path.join(ROOT, "runs", "oracle", "tep_final_campaign.json")


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def best_primal(cell, size):
    """(objVal, nCars) of the best verified primal over every production dir, or (None, None)."""
    best = None
    for sub in DIRS:
        d = load(os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, size)))
        if d and (best is None or float(d["objVal"]) < best[0]):
            best = (float(d["objVal"]), int(d["nCars"]))
    return best or (None, None)


def bound_path(cell, size):
    """The default-width bound artifact. At n50 the certified LP exists as a BY-PRODUCT of the primal selection runs
    (tep_cg_bound_<cell>_n50_ip.json, same run, --ip added), so it counts and the campaign does not re-run those cells."""
    base = os.path.join(ROOT, "runs", "oracle", ("tep_cg_bound_%s.json" % cell) if size == 100 else ("tep_cg_bound_%s_n%d.json" % (cell, size)))
    if os.path.exists(base):
        return base
    alt = os.path.join(ROOT, "runs", "oracle", ("tep_cg_bound_%s_ip.json" % cell) if size == 100 else ("tep_cg_bound_%s_n%d_ip.json" % (cell, size)))
    if os.path.exists(alt):
        d = load(alt)
        if not (d or {}).get("primal_rounding"):   # ceil-rounded artifacts are restrictions, not bounds (d414)
            return alt
    return base


def trigger_cells(size, thr=0.8):
    """K-blind fleet-cap trigger: cars of our best primal minus the LP fleet term N of our default-width bound >= thr."""
    out = []
    for c in CELLS:
        ov, cars = best_primal(c, size); b = load(bound_path(c, size))
        if ov is None or not b or b.get("N") is None or cars is None or cars < 2:
            continue
        if cars - float(b["N"]) >= thr:
            out.append((c, cars - 1))
    return out


def lacking(size, sub):
    return [c for c in CELLS if not os.path.exists(os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (c, size)))]


def lacking_bound(size):
    """Cells with no CERTIFIED default-width bound. Existence is not enough: at n50 nine R cells carry a
    by-product artifact whose elementary pass exhausted its label cap (status elem_exhausted), so the
    value is not a bound and no reader uses it. Checking os.path.exists alone made step S4 report
    nothing to do while the n50 bound leg was 18 of 27 (found 2026-09-27 while censusing the grid)."""
    from bound_certificate import certified
    out = []
    for c in CELLS:
        d = load(bound_path(c, size))
        if not (d and certified(d) and not d.get("primal_rounding")):
            out.append(c)
    return out


def sweep_done():
    log = os.path.join(ROOT, "logs", "ceil_n100_sweep.out")
    return os.path.exists(log) and ("cell(s) run:" in io.open(log, encoding="utf-8", errors="replace").read())


def cmds_polish(size, tag):
    return [[PY, "analysis/tep_refine.py"] + CELLS + ["--size", str(size), "--surrogate", "--wall", "120", "--tag", tag],
            [PY, "analysis/tep_alns.py"] + CELLS + ["--size", str(size), "--surrogate", "--iters", "3000", "--stall", "600", "--wall", "1200", "--tag", tag]]


def cmds_selchain(size, cells):
    wide = "0" if size == 100 else "45"
    return [[PY, "analysis/tep_select_chain.py"] + cells + ["--size", str(size), "--wide", wide, "--cap", "900", "--work", "600"]] if cells else []


def cmds_fleetcap(size):
    out = []
    extra = ["--rounds", "3", "--cap-chain", "300", "--work-chain", "150"] if size >= 50 else []
    for c, cap in trigger_cells(size):
        out.append([PY, "analysis/tep_master_fleet_cap.py", c, "--size", str(size), "--cap-cars", str(cap)] + extra)
    return out


def cmds_bounds(size, cells, wall):
    return [[PY, "analysis/tep_cg_bound.py", c, "--size", str(size), "--start-states", "--max-secs", str(wall)] for c in cells]


def plan(only_cells=None):
    """Ordered steps: (id, description, commands or callable producing commands, summary artifact to assert)."""
    L10, L20, L30 = lacking(10, "selchain"), lacking(20, "selchain"), lacking(30, "selchain")
    B10, B20, B50 = lacking_bound(10), [c for c in lacking_bound(20)], lacking_bound(50)
    if only_cells:
        f = lambda cs: [c for c in cs if c in only_cells]
        L10, L20, L30, B10, B20, B50 = f(L10), f(L20), f(L30), f(B10), f(B20), f(B50)
    return [
        ("S1", "wait for the n100 ceil sweep to finish (no Gurobi step shares the machine with it)", "WAIT_SWEEP", None),
        ("S2", "n100 refine + ALNS, surrogate, all 27", cmds_polish(100, "final"), "runs/oracle/tep_alns_final_n100.json"),
        ("S3", "n100 cars-first select+chain, all 27 (pool = floor + ceil partitions)", cmds_selchain(100, CELLS if not only_cells else [c for c in CELLS if c in only_cells]), "runs/oracle/tep_select_chain_n100.json"),
        ("S3b", "n100 master fleet cap on trigger cells (computed at run time)", lambda: cmds_fleetcap(100), None),
        ("S4", "n50 default-width bound, certified, on %d cells lacking one" % len(B50), cmds_bounds(50, B50, 900), None),
        ("S5", "n50 refine + ALNS, surrogate, all 27", cmds_polish(50, "final"), "runs/oracle/tep_alns_final_n50.json"),
        ("S6", "n50 cars-first select+chain, all 27 (+45 LP columns)", cmds_selchain(50, CELLS if not only_cells else [c for c in CELLS if c in only_cells]), "runs/oracle/tep_select_chain_n50.json"),
        ("S6b", "n50 master fleet cap on trigger cells", lambda: cmds_fleetcap(50), None),
        ("S8a", "n10 bound on %d cells and n20 bound on %d cells lacking one" % (len(B10), len(B20)), cmds_bounds(10, B10, 300) + cmds_bounds(20, B20, 300), None),
        ("S7", "n10/n20/n30 select+chain on cells lacking one (%d / %d / %d)" % (len(L10), len(L20), len(L30)), cmds_selchain(10, L10) + cmds_selchain(20, L20) + cmds_selchain(30, L30), None),
        ("S7b", "n10/n20/n30 master fleet cap on trigger cells", lambda: cmds_fleetcap(10) + cmds_fleetcap(20) + cmds_fleetcap(30), None),
        # UNIFORM WIDTH GRID (2026-09-27): the certified bounds were at MIXED bucket widths per cell (n10 9 cells at delta 60
        # and 21 at 20; n20 13/35; n30 15/38; n50 8/10), so "the bound" was not one instrument. Every size now runs the same
        # width set and the reported bound stays the max PROVEN width per cell, with the set disclosed: n10/n20/n30 {60,20,5},
        # n50 {60,20}. n100 keeps the subset instrument (tep_easy_reduction), which has its own uniform protocol.
        ("S8b", "n20 d=5 over the grid (uniform width set)", [[PY, "analysis/tep_fine_delta_bound_batch.py", "--size", "20", "--delta", "5", "--max-secs", "900"]], "runs/oracle/tep_fine_delta_bound_n20_d5.json"),
        ("S8d", "n10 d=20 and d=5 over the grid (uniform width set)", [[PY, "analysis/tep_fine_delta_bound_batch.py", "--size", "10", "--delta", w, "--max-secs", "300"] for w in ("20", "5")], "runs/oracle/tep_fine_delta_bound_n10_d5.json"),
        ("S8e", "n20 d=20 over the grid (the 13 cells whose default artifact is at delta 60)", [[PY, "analysis/tep_fine_delta_bound_batch.py", "--size", "20", "--delta", "20", "--max-secs", "600"]], "runs/oracle/tep_fine_delta_bound_n20_d20.json"),
        ("S8f", "n30 d=20 over the grid (same reason)", [[PY, "analysis/tep_fine_delta_bound_batch.py", "--size", "30", "--delta", "20", "--max-secs", "900"]], "runs/oracle/tep_fine_delta_bound_n30_d20.json"),
        ("S8g", "n50 d=20 over the grid", [[PY, "analysis/tep_fine_delta_bound_batch.py", "--size", "50", "--delta", "20", "--max-secs", "900"]], "runs/oracle/tep_fine_delta_bound_n50_d20.json"),
        ("S8c", "n30 C207 and R208 at d=5, 1800 s wall, solo", [[PY, "analysis/tep_cg_bound.py", c, "--size", "30", "--start-states", "--delta", "5", "--max-secs", "1800"] for c in ("C207", "R208")], None),
        ("S9", "commit: re-verify every banked artifact; regenerate every table, ablation, gap table, coverage map, numbers; release gate",
         [[PY, "analysis/tep_reverify_all.py"]] + [[PY, "analysis/tep_n30_best_of.py", "--size", str(n)] for n in (10, 20, 30, 50, 100)]
         + [[PY, "analysis/tep_incumbent_ledger.py"], [PY, "analysis/verify_incumbent.py", "--all"]]
         + [[PY, "analysis/tep_n100_family_table.py"]] + [[PY, "analysis/tep_ablation_table.py", "--size", str(n)] for n in (10, 20, 30, 50, 100)]
         + [[PY, "analysis/tep_gap_to_bound.py"], [PY, "analysis/tep_coverage_map.py"], [PY, "analysis/manuscript_numbers.py"], [PY, "analysis/release_gate.py"]],
         "runs/oracle/tep_reverify_all.json"),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true"); ap.add_argument("--run", action="store_true")
    ap.add_argument("--only", default=None); ap.add_argument("--cells", nargs="*", default=None)
    a = ap.parse_args()
    os.makedirs(MARK, exist_ok=True)
    steps = plan(set(a.cells) if a.cells else None)
    rec = load(SUMMARY) or {"steps": []}
    if a.plan or not a.run:
        print("FINAL CAMPAIGN -- plan (nothing launched). sweep done: %s" % sweep_done())
        for sid, desc, cmds, art in steps:
            done = os.path.exists(os.path.join(MARK, sid + ".done"))
            n = "wait" if cmds == "WAIT_SWEEP" else ("runtime" if callable(cmds) else str(len(cmds)))
            print("  %-4s %-6s %-4s cmd(s)  %s" % (sid, "DONE" if done else "pending", n, desc))
            if callable(cmds):
                for c in cmds()[:6]: print("         %s" % " ".join(c[1:])[:120])
        return 0
    for sid, desc, cmds, art in steps:
        if a.only and sid != a.only: continue
        marker = os.path.join(MARK, sid + ".done")
        if os.path.exists(marker) and not a.only:
            print("  %s DONE (marker), skipping" % sid, flush=True); continue
        if cmds == "WAIT_SWEEP":
            while not sweep_done():
                time.sleep(120)
            print("  S1: sweep finished %s" % time.strftime("%H:%M:%S"), flush=True); io.open(marker, "w").write("done\n"); continue
        if callable(cmds): cmds = cmds()
        print("== %s (%d command(s)) %s -- %s" % (sid, len(cmds), time.strftime("%H:%M:%S"), desc), flush=True)
        t0 = time.time(); ok = True; ran = []
        for i, cmd in enumerate(cmds):
            log = os.path.join(ROOT, "logs", "campaign_%s_%02d.out" % (sid, i))
            t1 = time.time()
            with io.open(log, "w", encoding="utf-8", errors="replace") as fh:
                rc = subprocess.call(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
            ran.append(dict(cmd=" ".join(os.path.basename(x) if x == PY else x for x in cmd)[:400], rc=rc, secs=round(time.time() - t1), log=os.path.relpath(log, ROOT)))
            print("   %s cmd %d/%d rc=%d %ds  %s" % (sid, i + 1, len(cmds), rc, time.time() - t1, " ".join(cmd[1:4])[:60]), flush=True)
            if rc != 0:
                ok = False; break
        if ok and art:
            d = load(os.path.join(ROOT, art))
            if not d or not (d.get("_provenance") or {}).get("code_hash"):
                ok = False; print("   %s summary artifact missing or unstamped: %s" % (sid, art), flush=True)
        rec["steps"] = [s for s in rec["steps"] if s.get("id") != sid] + [dict(id=sid, desc=desc, ok=ok, secs=round(time.time() - t0), started=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)), commands=ran)]
        json.dump(stamped(rec), io.open(SUMMARY, "w", encoding="utf-8"), indent=1, default=str)
        if ok and not a.only and cmds:
            io.open(marker, "w").write("done %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        elif ok and not a.only and not cmds:
            # d552: an EMPTY step writes NO marker, so the next run re-evaluates it. The plan is built
            # once at start-up, so a step whose cell list was empty then -- or wrong, as S4 was while
            # lacking_bound tested existence instead of certification -- would otherwise be recorded
            # as done having run nothing, freezing the gap shut.
            print("   %s had no commands: no marker written, it will be re-evaluated next run" % sid, flush=True)
        elif ok and a.only:
            print("   (--only run: no marker written; the full run re-executes this step and skips cells already done by their drivers)")
        if not ok:
            print("!! %s FAILED -- queue stopped; nothing derives from it. See the log above." % sid, flush=True); return 1
        print("   %s ok in %.0f s" % (sid, time.time() - t0), flush=True)
    print("CAMPAIGN COMPLETE %s" % time.strftime("%H:%M:%S"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
