"""Full validation of stage three: the two consolidation choices, across the grid (d450).

Audit: `validation/runaudits/TEP_stage3_validation.md`. The gates are fixed there; this driver only
runs the arms and reports what the audit asks for.

THREE ARMS per cell, all deterministic -- no seed, no restart, so a difference between arms is
exact and no noise floor applies:

  production   street=online  water=tours       both choices on
  naive-street street=firstfit water=tours      trips taken in list order instead of probed
  naive-water  street=online  water=singleton   one vessel per transfer instead of tours

REFERENCE per size, because what we can compare against differs:
  n10   K prove all 27 optimal -- the comparison is against TRUTH
  n20   7 proven, 20 open -- against their published incumbent
  n30   1 proven, 26 open -- against their published incumbent
  n100  no per-cell publication -- against our own best-known

Every output goes through `verifier3`; an arm that fails verification contributes nothing but a
failure count. An arm that DECLINES is recorded with the trip that declined, because a trip that
cannot be scheduled alone is a SELECTION defect and not a stage-three defect.

    python analysis/tep_stage3_validation.py --size 10
"""
import argparse
import io
import json
import os
import subprocess
import statistics as st
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
ARMS = (("production", "online", "tours"),
        ("naive_street", "firstfit", "tours"),
        ("naive_water", "online", "singleton"))


def reference(cell, size):
    """What this size can be compared against, and what kind of thing it is."""
    p = os.path.join(ROOT, "runs", "oracle", "k_targets_small.json")
    if size in (10, 20, 30) and os.path.exists(p):
        d = json.load(io.open(p, encoding="utf-8")).get("n%d" % size)
        for r in (d or {}).get("rows", []):
            if r["cell"] == cell:
                return float(r["k_inc"]), ("proven optimum" if r["proven"] else "K incumbent")
    try:
        sys.path.insert(0, os.path.join(ROOT, "analysis"))
        import bks_n100 as B
        v = [x["obj"] for x in B.scan(False) if x["cell"] == cell]
        if v:
            return float(min(v)), "our best-known"
    except Exception:
        pass
    return None, None


def run_arm(cell, size, arm, street, water, logdir):
    log = os.path.join(logdir, "s3_%s_%s_n%d.out" % (arm, cell, size))
    tag = "" if arm == "production" else "_" + arm
    with io.open(log, "w", encoding="utf-8") as lg:
        rc = subprocess.call([sys.executable, os.path.join(ROOT, "analysis", "tep_guided_construct.py"),
                              cell, "--size", str(size), "--street", street, "--water", water,
                              "--tag", tag], stdout=lg, stderr=subprocess.STDOUT, cwd=ROOT)
    p = os.path.join(ROOT, "runs", "postpass", "guided%s_%s_n%d.json" % (tag, cell, size))
    txt = io.open(log, encoding="utf-8").read()
    if rc != 0 or not os.path.exists(p):
        why = "declined" if "DECLINED" in txt else ("verifier FAIL" if "verifier3 FAIL" in txt else "rc %d" % rc)
        return dict(ok=False, why=why)
    s = json.load(io.open(p, encoding="utf-8"))
    return dict(ok=True, obj=float(s["objVal"]), cars=int(s["nCars"]), vessels=int(s["nVessel"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--cells", default=None)
    ap.add_argument("--arms", default="production,naive_street,naive_water")
    a = ap.parse_args()
    cells = a.cells.split(",") if a.cells else CELLS
    arms = [x for x in ARMS if x[0] in a.arms.split(",")]
    logdir = os.path.join(ROOT, "logs", "stage3")
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    # cells whose selection artifact is missing cannot be run and are reported as such
    def have_sel(c):
        return os.path.exists(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s_ip.json"
                                           % (c, "" if a.size == 100 else "_n%d" % a.size)))
    missing = [c for c in cells if not have_sel(c)]
    cells = [c for c in cells if have_sel(c)]
    print("n%d: %d cells with a selection, %d without (%s), %d arms"
          % (a.size, len(cells), len(missing), ",".join(missing) if missing else "-", len(arms)), flush=True)

    rows = {}
    t0 = time.time()
    for c in cells:
        ref, kind = reference(c, a.size)
        rec = dict(cell=c, reference=ref, reference_kind=kind, arms={})
        for arm, st, wt in arms:
            rec["arms"][arm] = run_arm(c, a.size, arm, st, wt, logdir)
        rows[c] = rec
        pr = rec["arms"].get("production", {})
        print("  %-6s ref %-9s %s" % (c, ("%.1f" % ref) if ref else "-",
              ("prod %.1f (%d cars, %d vessels)%s" % (pr["obj"], pr["cars"], pr["vessels"],
               ("  %+.2f%% vs ref" % (100.0 * (pr["obj"] / ref - 1))) if (pr.get("ok") and ref) else "")
               ) if pr.get("ok") else "prod FAILED: %s" % pr.get("why")), flush=True)
    print("\n  finished in %.0f s" % (time.time() - t0), flush=True)

    # ---- the audit's table ---------------------------------------------------------
    ok = [r for r in rows.values() if r["arms"].get("production", {}).get("ok")]
    print("\n  production verified on %d of %d cells run" % (len(ok), len(rows)))
    for arm, _, _ in arms:
        good = [r for r in rows.values() if r["arms"].get(arm, {}).get("ok")]
        print("    %-13s verified %2d of %2d" % (arm, len(good), len(rows)))
    both = [r for r in ok if all(r["arms"].get(x[0], {}).get("ok") for x in arms)]
    if both and len(arms) > 1:
        print("\n  ABLATION over the %d cells where every arm succeeded (deterministic, no noise floor):" % len(both))
        base = [r["arms"]["production"]["obj"] for r in both]
        for arm, _, _ in arms:
            if arm == "production":
                continue
            alt = [r["arms"][arm]["obj"] for r in both]
            d = [100.0 * (x / b - 1) for x, b in zip(alt, base)]
            worse = sum(1 for x in d if x > 1e-9)
            print("    turning off %-13s costs a median %+.2f%% and is worse on %d of %d cells"
                  % (arm.replace("naive_", ""), st.median(d), worse, len(d)))
    withref = [r for r in ok if r["reference"]]
    if withref:
        g = sorted(100.0 * (r["arms"]["production"]["obj"] / r["reference"] - 1) for r in withref)
        print("\n  production against the reference (%s): median %+.2f%%, best %+.2f%%, worst %+.2f%%"
              % (withref[0]["reference_kind"], st.median(g), g[0], g[-1]))
        beat = [r["cell"] for r in withref if r["arms"]["production"]["obj"] < r["reference"] - 0.05]
        if beat:
            print("  BELOW the reference on: %s" % ", ".join(beat))
    out = os.path.join(ROOT, "runs", "oracle", "tep_stage3_validation_n%d.json" % a.size)
    json.dump(stamped(dict(size=a.size, cells=rows, missing_selection=missing)),
              io.open(out, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main()
