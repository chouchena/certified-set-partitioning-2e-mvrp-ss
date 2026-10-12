"""n100 feasibility probe against K Table 6 -- CHEAPEST DECISIVE TEST FIRST.

WHY n100 IS THE HIGHEST-VALUE SIZE. K's Joint MILP gaps there are 60.1 / 74.6 / 77.0 % for
C / R / RC (Table 6 caption) versus 28-49 % at n30. Their bound is at its weakest exactly
where ours is structurally cheapest, because the easy-reduction bound

    block_relax = z_A(H)  +  w(FULL demand)

splits into a part that shrinks with the retained set H and a part that does NOT depend on k
at all. w(full) is a water-level bound over all 100 customers however many are dropped.

STAGE A THEREFORE COMES FIRST, AND IT IS ALMOST FREE.
Evaluate w(full) alone -- one small water LB per cell, no block-A MILP anywhere. Since
z_A(H) >= 0, w(full) is ALREADY a valid lower bound on z_joint* (proof Step 0 plus
non-negativity of the street-level objective). If the family means of w(full) alone already
exceed K's derived Table 6 bounds (C 1704.3, R 1056.4, RC 1249.5), the n100 result is settled
before a single expensive solve is scheduled. If it does not, Stage A still tells us exactly
how much z_A(H) has to contribute, which is what sizes Stage B.

Every previous result that got invalidated in this project came from running the expensive
thing first; both banked results came from a cheap test run before an expensive one.

STAGE B -- k_hi calibration, only if Stage A is not already decisive.
The binding quantity for provability is |H|, NOT the drop fraction. Evidence: |H|=11 proved
in 1.4 s at n20; |H|=15 failed at a 450 s wall on ten n30 cells. So n100 wants k_hi ~ 85-88
(|H| = 12-15), NOT the ~50 that "keep the drop fraction comparable" would suggest. Stage B
tests a small ladder of |H| on ONE cell and reports which prove, so the batch k_hi is chosen
from measurement rather than from the n30 analogy.

PROXIMITY 0.1 IS MANDATORY (Table 6 caption). Comparing an n100 bound computed at proximity
0.0 against Table 6 compares two different problems -- the satellites sit elsewhere. This
script hard-codes 0.1 and stamps it into every artifact.

TENANCY. Runs strictly one solve at a time and refuses to start while another solver is live;
the n30 primal campaign was invalidated by co-tenancy on this 4P+4LPE part.
"""
import argparse, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _det_env():
    """PYTHONHASHSEED pinned: set/dict iteration order can otherwise vary
    between runs, and the easiness ranking that selects WHICH customers are
    dropped is built from dict traversal. Cheap insurance for replicability."""
    e = dict(os.environ)
    e["PYTHONHASHSEED"] = "0"
    return e
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
PY = sys.executable
PROX = 0.1                      # Table 6. Not a parameter on purpose.
SEED = 20260910
LOG = os.path.join(ROOT, "runs", "lb_n100_probe.log")

# K Table 6 derived bounds (see paper/paper-reference-data.md; JENSEN-APPROX).
K100 = {"C":  dict(lb=4271.3 * (1 - 0.601), ub=3857.2, n=8),
        "R":  dict(lb=4158.9 * (1 - 0.746), ub=3720.9, n=11),
        "RC": dict(lb=5432.5 * (1 - 0.770), ub=4810.6, n=8)}
FAMS = ("C", "R", "RC")
CELLS = ([f"C2{i:02d}" for i in range(1, 9)]
         + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC2{i:02d}" for i in range(1, 9)])


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def live_solvers():
    o = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                        "Where-Object { $_.CommandLine -like '*easy_reduction*' -or "
                        "$_.CommandLine -like '*fixopt.py*' -or "
                        "$_.CommandLine -like '*lb_repair*' }).Count"],
                       capture_output=True, text=True).stdout.strip()
    try:
        return int(o or 0)
    except ValueError:
        return -1


def require_single_tenancy():
    n = live_solvers()
    if n > 0:
        sys.exit(f"REFUSING to start: {n} solver process(es) already live. The n100 probe must "
                 f"run single-tenant (co-tenancy invalidated the n30 primal campaign). "
                 f"Wait for the running batch to finish.")


# ---------------------------------------------------------------- stage A
def stage_a(cells, out_path):
    """w(FULL demand) only -- no block-A MILP. Valid LB on its own since z_A(H) >= 0."""
    from build_instance import build
    from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
    rows = {}
    if os.path.exists(out_path):
        rows = json.load(open(out_path, encoding="utf-8"))
    say(f"=== STAGE A: w(full demand) at n100, proximity {PROX}, {len(cells)} cells ===")
    for i, c in enumerate(cells, 1):
        if c in rows:
            continue
        t0 = time.time()
        try:
            p = build(c, 100, wls=0.1, tau="formula", proximity=PROX, time_limit=120)
            w = water_lb_scaled(p)[0] / SCALE
        except Exception as e:
            say(f"  [{i}/{len(cells)}] {c} FAILED: {e}")
            continue
        rows[c] = dict(w_full=round(w, 4), prox=PROX, size=100,
                       wall=round(time.time() - t0, 1), ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        json.dump(stamped(rows, __file__), open(out_path, "w"), indent=2)
        say(f"  [{i}/{len(cells)}] {c} w_full={w:9.2f}  ({time.time()-t0:.1f}s)")
    return rows


def stage_a_report(rows):
    say("")
    say("=== STAGE A VERDICT: w(full) ALONE vs K Table 6 (JENSEN-APPROX reference) ===")
    say(f"{'fam':4}{'n':>4}{'our w(full)':>13}{'K LB':>10}{'ratio':>8}"
        f"{'OptGap% ours':>14}{'K OptGap%':>11}")
    decisive = True
    for f in FAMS:
        got = [c for c in rows if fam(c) == f]
        if len(got) < K100[f]["n"]:
            say(f"{f:4}{len(got):>4}   coverage {len(got)}/{K100[f]['n']} -- WITHHELD "
                f"(no partial family means)")
            decisive = False
            continue
        m = sum(rows[c]["w_full"] for c in got) / len(got)
        kl, ub = K100[f]["lb"], K100[f]["ub"]
        say(f"{f:4}{len(got):>4}{m:>13.2f}{kl:>10.1f}{m/kl:>7.2f}x"
            f"{(ub-m)/ub*100:>13.1f}%{(ub-kl)/ub*100:>10.1f}%")
        if m <= kl:
            decisive = False
    say("")
    if decisive:
        say("STAGE A IS DECISIVE: w(full) alone dominates K's Table 6 bound in every family. "
            "The n100 LB result needs NO block-A solve. Stage B becomes an optional "
            "improvement, not a requirement.")
    else:
        say("STAGE A NOT DECISIVE on its own -- z_A(H) must contribute. Run stage B to "
            "calibrate k_hi, then the full batch.")
    return decisive


# ---------------------------------------------------------------- stage B
def stage_b(cell, hs, tl, workers, scratch, det_tl):
    """Which |H| proves within tl at n100? Reports, does not tune on the outcome."""
    say(f"=== STAGE B: k_hi calibration on {cell}, |H| in {hs}, tl={tl}s, prox={PROX} ===")
    for h in hs:
        k = 100 - h
        out = os.path.join(scratch, f"probe_{cell}_n100_H{h}.json")
        t0 = time.time()
        subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                        "--cells", cell, "--size", "100", "--tl", str(tl),
                        "--k-hi", str(k), "--k-cap", str(k + 1), "--workers", str(workers),
                        "--proximity", str(PROX), "--cell-budget", str(tl * 2.5),
                        "--seed", str(SEED), "--det-tl", str(det_tl),
                        "--out", out, "--allow-overwrite"],
                       cwd=ROOT, env=_det_env(), timeout=tl * 6 + 900,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        r = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
        r = [x for x in r if isinstance(x, dict) and x.get("block_relax") is not None]
        if not r:
            say(f"  |H|={h:>3} (k={k}) -> NO RECORD in {time.time()-t0:.0f}s")
            continue
        b = max(r, key=lambda x: x["block_relax"])
        kl = K100[fam(cell)]["lb"]
        say(f"  |H|={h:>3} (k={k}) -> block_relax={b['block_relax']:9.2f} "
            f"({b['block_relax']/kl:4.2f}x K's {kl:.0f}) proven={b['proven']} "
            f"limit={b.get('limit_hit')} wall={b['wall']:.1f}s ticks={b.get('det_ticks')} "
            f"improv={b.get('n_improve')} [{time.time()-t0:.0f}s total]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="a", choices=["a", "b", "ab"])
    ap.add_argument("--cells", default="", help="stage A subset; default all 27")
    ap.add_argument("--probe-cell", default="C201")
    ap.add_argument("--hs", default="13,20,30,45",
                    help="retained-set sizes to test. Stage A showed z_A(H) must supply ~1400 "
                         "at n100, far above what |H|=15 gave at n30, so the ladder reaches wide.")
    ap.add_argument("--det-tl", type=float, default=450000.0)
    ap.add_argument("--tl", type=int, default=1200, help="WALL BACKSTOP only")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="skip the tenancy check")
    A = ap.parse_args()
    if not A.force:
        require_single_tenancy()
    from analysis.repro_preflight import preflight
    preflight("lb_n100_probe", seed=SEED, threads=A.workers,
              allow_dirty=A.force, require_single_tenant=not A.force,
              extra=dict(proximity=PROX, size=100, stage=A.stage, tl=A.tl))

    scratch = os.path.join(ROOT, "runs", "n100_probe")
    os.makedirs(scratch, exist_ok=True)
    cells = [c.strip() for c in A.cells.split(",") if c.strip()] or CELLS

    if "a" in A.stage:
        rows = stage_a(cells, os.path.join(ROOT, "crossfeed", "wfull_n100_prox01.json"))
        decisive = stage_a_report(rows)
        if decisive and A.stage == "ab":
            say("Skipping stage B: stage A already settles the comparison.")
            return
    if "b" in A.stage:
        stage_b(A.probe_cell, [int(x) for x in A.hs.split(",")], A.tl, A.workers,
                scratch, A.det_tl)
    say("n100 PROBE COMPLETE")


if __name__ == "__main__":
    main()
