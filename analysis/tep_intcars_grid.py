"""The integer-car cut across the grid, in the order fixed by the pre-registration. (d565)

WHAT IT RUNS. For each eligible cell, `tep_cg_bound.py <cell> --size N --start-states --ip
--int-cars`, which proves the LP, then adds N >= ceil(N_LP) and re-prices to proof, repeating while
the proven car count keeps crossing an integer. The cut is valid because the LP's car count bounds
the cars of every feasible solution from below and cars are integer. Output goes to
`tep_cg_bound_<cell>_n<N>_ip_intcars.json` -- a separate name -- so a production bound is never
overwritten.

ELIGIBILITY IS A THEOREM, THE ORDER IS AN ESTIMATE, AND THE TWO ARE KEPT APART (amendment 2).
A cell is eligible when it has a certified bound (either class) whose proven car count is NOT an
integer. That is the only skip carrying a proof: a cut the current optimum already satisfies cannot
change the LP, because that optimum remains feasible and optimal. The ORDER is the expected lift per
minute, which is an estimate and is never used to skip -- measured on 23 cells it ran 0.32x to 1.24x
the realised gain. The plan is written to `runs/oracle/tep_intcars_grid_plan.json` once and re-read,
so it cannot be resorted into a friendlier sequence. See `validation/PREREG_intcars_grid.md`.

THE STOPPING RULE FIRES BY ITSELF. After the first 10 cells, if the median lift is below 0.5 per
cent of the bound, the runner stops and says so. That is a pre-registered negative result, not a
failure.

    python analysis/tep_intcars_grid.py --plan          # print the order, run nothing
    python analysis/tep_intcars_grid.py --run [--limit K]

SOLO. It is wall-bounded and every second is charged to the envelope, so it must not share the
machine with the campaign or with any other timed run.
"""
import argparse
import glob
import io
import json
import math
import os
import statistics as st
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from bound_certificate import bound_class
from stamp import stamped

PY = sys.executable
PLAN = os.path.join(ROOT, "runs", "oracle", "tep_intcars_grid_plan.json")
OUT = os.path.join(ROOT, "runs", "oracle", "tep_intcars_grid.json")
WALL = {10: 300, 20: 300, 30: 600, 50: 900, 100: 1200}
SIZE_ORDER = (20, 30, 50, 100, 10)
STOP_AFTER = 10
STOP_PCT = 0.5


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def artifacts(size):
    pats = ["tep_cg_bound_*_n%d*.json" % size] if size != 100 else ["tep_cg_bound_*.json", "tep_easy_reduction_*_n100_k*.json"]
    for pat in pats:
        for p in glob.glob(os.path.join(ROOT, "runs", "oracle", pat)):
            d = load(p)
            if d and (d.get("size") or 100) == size and not d.get("primal_rounding"):
                yield p, d


def eligible(size):
    """Cells with a certified bound whose proven car count is fractional, best artifact per cell."""
    best = {}
    for p, d in artifacts(size):
        if not bound_class(d) or "intcars" in os.path.basename(p):
            continue
        # THE ARTIFACT FIELD, NOT THE LAST HISTORY ROW (amendment 2). hist stores N rounded to 3 dp and
        # the master is re-optimised after the pricing loop, so the two differ by up to 0.28 cars on 20
        # artifacts. No queued cell was affected, but the field is the value the cut will actually see.
        v = d.get("composed") if d.get("composed") is not None else d.get("lp_composed")
        if v is None:
            v = d.get("lp_street")
        if d.get("N") is None or v is None:
            continue
        N = float(d["N"]); frac = N - math.floor(N + 1e-9)
        c = d.get("cell")
        # THE ONLY PROVABLE SKIP: a cut the current optimum already satisfies cannot change the LP,
        # because that optimum stays feasible and stays optimal. For N >= ceil(N_LP) that is exactly
        # "N_LP is integral". The old band also excluded frac > 0.95 on the theory that a small step
        # buys little -- which is an ESTIMATE, not a proof, and it skipped 8 cells for no reason. A
        # 0.269-car step on C208 at |C|=10 bought 15.1 cost units.
        if frac <= 1e-6:
            continue
        # THE SECOND PROVABLE SKIP, learned the expensive way (d579). The cut is conditioned on the
        # ELEMENTARY certificate, so a cell whose best bound is ng-class cannot fire it -- the run
        # simply re-derives the same ng bound. Phase B proved that at n50: nine R cells, all
        # elem_exhausted, all returning +0.00 per cent, 4.1 hours between them, with R208 alone
        # spending 5527 seconds. The n100 refusal in tep_cg_bound caught the same thing one size up;
        # this catches it wherever it occurs. Lift it when the gate accepts an ng-converged LP.
        if bound_class(d) != "elementary":
            continue
        if c not in best or float(v) > best[c]["bound"]:
            best[c] = dict(cell=c, size=size, N=N, frac=frac, bound=float(v),
                           klass=bound_class(d), source=os.path.basename(p),
                           secs=float(d.get("secs") or 0) or 1.0)
    return list(best.values())


def score(r):
    """Expected lift per minute of machine time. AMENDMENT 1 to the pre-registration (d566).

    THE LIFT IS THE ROUNDING STEP, NOT THE FRACTION. Adding N >= ceil(N_LP) raises the fleet term by
    (ceil(N) - N) cars, so a cell whose LP car count is 0.95 has almost nothing to gain and one at
    1.05 has almost a whole car. The first plan ordered by the fractional part and therefore put the
    WORST cells first. Caught before a single cell ran.

    Calibrated on the one measured case, R204 at |C| = 50: step 0.585 cars x penalty 170.0 = 99.4
    predicted against 87.3 observed, so the LP recovered 12 per cent by re-optimising. The 0.88
    factor is that realisation, and it is a single observation -- it orders the queue, it is not a
    result.
    """
    import verifier3 as _V
    from k_comparison import k_proximity as _kp
    key = (r["cell"], r["size"])
    if key not in _PEN:
        _PEN[key] = float(_V.load_instance(r["cell"], r["size"], _kp(r["size"])).penalty_cars)
    step = math.ceil(r["N"] - 1e-9) - r["N"]
    # ORDERING ONLY. This is NOT a bound on what the cut buys and must never be used to skip one:
    # measured on 23 cells the observed gain ran 0.32x to 1.24x this figure and EXCEEDED it on six,
    # because N is fixed by the src equality -- the LP cannot buy a car, it must restructure chains,
    # and that can cost more than the car itself (amendment 2).
    est = 100.0 * step * _PEN[key] / r["bound"] * 0.88
    p_ok = 1.0 if r["klass"] == "elementary" else 0.5
    p_ok *= 0.5 if r["secs"] > 600 else (0.8 if r["secs"] > 120 else 1.0)
    r["step"], r["est_lift"], r["p_ok"] = step, est, p_ok
    r["score"] = est * p_ok / (max(r["secs"], 1.0) / 60.0)
    return r["score"]


_PEN = {}


def build_plan():
    """Three phases, fixed here and written to disk once (AMENDMENT 1, d566).

    A. VALIDATION -- the 10 cells with the highest expected lift per minute, wherever they sit. The
       author's instruction was to sequence so the highest odds come first, and this is that: it puts
       the device's own stopping rule against its best candidates, which makes a negative result
       decisive rather than merely discouraging.
    B. PAPER VALUE -- |C| = 50 and 100 next, in score order, because that is where the bound is the
       claim. Highest odds first is the right way to TEST the device; it is not the right way to
       SPEND it once it is shown to work.
    C. THE REST, in score order.
    """
    allc = []
    for n in SIZE_ORDER:
        allc += eligible(n)
    for r in allc:
        score(r)
    allc.sort(key=lambda r: -r["score"])
    phase_a = allc[:STOP_AFTER]
    rest = [r for r in allc if r not in phase_a]
    phase_b = [r for r in rest if r["size"] in (50, 100)]
    phase_c = [r for r in rest if r["size"] not in (50, 100)]
    for r, ph in [(r, "A") for r in phase_a] + [(r, "B") for r in phase_b] + [(r, "C") for r in phase_c]:
        r["phase"] = ph
    plan = phase_a + phase_b + phase_c
    json.dump(stamped(dict(order=plan, wall=WALL, stop_after=STOP_AFTER, stop_pct=STOP_PCT,
                           prereg="validation/PREREG_intcars_grid.md")),
              io.open(PLAN, "w", encoding="utf-8"), indent=1, default=str)
    return plan


def plan_rows():
    d = load(PLAN)
    return d["order"] if d else build_plan()


def done_path(cell, size):
    return os.path.join(ROOT, "runs", "oracle",
                        "tep_cg_bound_%s%s_ip_intcars.json" % (cell, "" if size == 100 else "_n%d" % size))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true"); ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--sizes", nargs="*", type=int, default=None)
    # A run that shares the machine with another job has TIMINGS THAT DO NOT REPRODUCE. The bound values are
    # unaffected -- they are LP optima under a cut -- but the seconds are, so they are flagged at the source
    # and must never enter the runtime ledger (validation/RT_LEG_DESIGN.md).
    ap.add_argument("--shared-machine", action="store_true", help="record that the timings are contaminated")
    ap.add_argument("--force-n100", action="store_true", help="run n100 anyway; the cut cannot fire there until G4 is fixed")
    a = ap.parse_args()
    rows = plan_rows()
    # G4 GUARD (2026-09-27): at |C| = 100 the cut cannot fire. tep_cg_bound gates it on `int_cars and
    # proven`, and `proven` is the ELEMENTARY certificate, which no n100 cell has, so an n100 run only
    # re-derives the ng bound already adopted -- ten minutes a cell for nothing. The phase-B run of
    # 2026-09-27 spent that before the gate was found. Skipped until the condition also accepts an
    # ng-converged LP, which is valid and is frozen-code work; --force-n100 overrides deliberately.
    if not a.force_n100:
        n100 = [r for r in rows if r["size"] == 100]
        rows = [r for r in rows if r["size"] != 100]
        if n100:
            print("  skipping %d n100 cell(s): the cut cannot fire there (OPEN_GAPS G4); --force-n100 overrides" % len(n100))
    if a.sizes:
        rows = [r for r in rows if r["size"] in a.sizes]
    if a.limit:
        rows = rows[:a.limit]
    if not a.run:
        print("INTEGER-CAR GRID -- plan only, nothing launched. %d eligible cell(s).\n" % len(rows))
        # the sort key is the FRACTIONAL PART, so it is printed: a reader must be able to check the order
        print("%-4s %-2s %-6s %5s %6s %6s %9s %8s %5s %8s" %
              ("#", "ph", "cell", "size", "N_LP", "step", "bound", "est lift", "P", "score/min"))
        for i, r in enumerate(rows, 1):
            print("%-4d %-2s %-6s %5d %6.2f %6.2f %9.1f %7.2f%% %5.2f %8.1f"
                  % (i, r.get("phase", "-"), r["cell"], r["size"], r["N"], r.get("step", 0),
                     r["bound"], r.get("est_lift", 0), r.get("p_ok", 0), r.get("score", 0)))
        print("\n  stopping rule: after %d cells, median lift below %.1f%% ends the grid (pre-registered)" % (STOP_AFTER, STOP_PCT))
        return 0

    res = (load(OUT) or {}).get("rows", [])
    seen = {(x["cell"], x["size"]) for x in res}
    for i, r in enumerate(rows, 1):
        key = (r["cell"], r["size"])
        if key in seen:
            continue
        out = done_path(r["cell"], r["size"])
        cmd = [PY, "analysis/tep_cg_bound.py", r["cell"], "--size", str(r["size"]),
               "--start-states", "--ip", "--int-cars", "--max-secs", str(WALL[r["size"]])]
        log = os.path.join(ROOT, "logs", "intcars_%s_n%d.out" % (r["cell"], r["size"]))
        t0 = time.time()
        with io.open(log, "w", encoding="utf-8", errors="replace") as fh:
            rc = subprocess.call(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
        secs = time.time() - t0
        d = load(out)
        after = None
        if d:
            after = d.get("composed") if d.get("composed") is not None else d.get("lp_street")
        klass = bound_class(d) if d else None
        lift = (100.0 * (after / r["bound"] - 1)) if (after and klass) else None
        row = dict(cell=r["cell"], size=r["size"], rc=rc, secs=round(secs), secs_reproducible=not a.shared_machine, before=r["bound"],
                   after=after, klass_after=klass, lift_pct=lift, N_before=r["N"],
                   cuts=(d or {}).get("int_car_cuts"), status=(d or {}).get("status"), log=os.path.relpath(log, ROOT))
        res.append(row); seen.add(key)
        json.dump(stamped(dict(rows=res, prereg="validation/PREREG_intcars_grid.md", shared_machine=bool(a.shared_machine))),
                  io.open(OUT, "w", encoding="utf-8"), indent=1, default=str)
        print("  %2d/%2d %-6s n%-4d rc=%d %5.0fs | before %9.1f -> %s | %s"
              % (i, len(rows), r["cell"], r["size"], rc, secs, r["bound"],
                 ("%9.1f (%s)" % (after, klass)) if after and klass else "no certified bound (%s)" % (d or {}).get("status"),
                 ("%+.2f%%" % lift) if lift is not None else "-"), flush=True)
        lifts = [x["lift_pct"] for x in res if x["lift_pct"] is not None]
        if len(res) >= STOP_AFTER and lifts and st.median(lifts) < STOP_PCT:
            print("\n  STOPPING RULE FIRED: %d cells run, median lift %.2f%% < %.1f%%. This is the pre-registered"
                  % (len(res), st.median(lifts), STOP_PCT))
            print("  negative result -- the integer-car cut does not pay for its runtime. n50/n100 are not run.")
            break
    lifts = [x["lift_pct"] for x in res if x["lift_pct"] is not None]
    print("\n  cells run %d | certified after the cut %d | median lift %s | total %.0f s"
          % (len(res), len(lifts), ("%.2f%%" % st.median(lifts)) if lifts else "n/a", sum(x["secs"] for x in res)))
    print("  wrote %s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
