"""Execute the falsifiers whose inputs are ALREADY on disk. Zero solver time. (d586)

WHY THIS EXISTS. `analysis/claims.py check` reports 25 claims carrying a falsifier that has never
been executed. That is not 25 missing experiments: for several of them the experiment was RUN --
the F7 deterministic panel and the F8 n50 paired trial are banked in `runs/oracle/` -- and nobody
ever went back and read the answer out of the artifact. The claim kept its original evidence and
the register kept saying NOT RUN, which is the honest state but not the cheap one.

So this battery does the cheap half: every falsifier that can be decided from banked artifacts is
decided here, in seconds, and the verdict is printed next to the exact rule it applied.

WHAT A VERDICT MEANS, and the wording is deliberate:

  REFUTES        the observation the claim named as fatal was observed. The claim is wrong.
  does not refute  the observation was looked for and not found, in THIS test only. This is not
                 validation and is never to be written up as one; a falsification test can only
                 ever refute (CLAUDE.md section 2).
  no data        the artifact the falsifier names does not exist. An honest answer, not a pass.

THE HARNESS PRE-CHECK RUNS FIRST AND CAN VOID EVERYTHING BELOW IT. Every F7/F8 contrast is an
`exact difference` between two arms stopped on the same deterministic budget. The panel carries a
second control, `ctl2`, run identically to `ctl`. If ctl and ctl2 disagree by more than a rounding
epsilon then the deterministic stop is not exact on this machine, the paired differences are noise,
and no arm contrast below is admissible. That check is cheap and it gates the rest.

    python analysis/falsifier_battery.py
    python analysis/falsifier_battery.py --write-register   # record outcomes onto the claims

Register writes are OFF by default: a falsifier outcome changes a claim's standing, and that is the
author's call, not a side effect of running a report.
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))

EPS = 0.05          # currency epsilon: objectives are printed to 3 decimals
REG = os.path.join(ROOT, "validation", "claims.json")


def load(name):
    p = os.path.join(ROOT, "runs", "oracle", name)
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def majority(n_true, n_total):
    """'a majority of the six cells' -- strictly more than half, decided before any number was seen."""
    return n_total > 0 and n_true * 2 > n_total


def arm_contrast(rows, arm, base="ctl", worse_is_higher=True):
    """Per-cell exact difference arm - base. Returns (worse, better, tied, detail lines)."""
    worse, better, tied, lines = [], [], [], []
    for r in rows:
        a, b = r.get(arm), r.get(base)
        if a is None or b is None:
            continue
        d = float(a) - float(b)
        tag = "tied"
        if d > EPS:
            worse.append(r["cell"]); tag = "worse"
        elif d < -EPS:
            better.append(r["cell"]); tag = "better"
        else:
            tied.append(r["cell"])
        lines.append("      %-6s %-10s %10.3f  vs %-5s %10.3f   %+8.3f  %s"
                     % (r["cell"], arm, float(a), base, float(b), d, tag))
    return worse, better, tied, lines


# ---------------------------------------------------------------- the pre-check

def harness_exact(d, label):
    """ctl vs ctl2: the same arm twice on the same deterministic budget. Must agree exactly."""
    if d.get("admissible") is False:                       # the driver already refused it (d587)
        print("  %-26s the driver flagged this panel INADMISSIBLE: %s"
              % (label, d.get("admissible_why") or "no reason recorded"))
        return False
    rows = d.get("rows") or []
    bad = [(r["cell"], float(r["ctl"]), float(r["ctl2"]))
           for r in rows if r.get("ctl") is not None and r.get("ctl2") is not None
           and abs(float(r["ctl"]) - float(r["ctl2"])) > EPS]
    ok = not bad and any(r.get("ctl2") is not None for r in rows)
    print("  %-26s %s" % (label, "ctl == ctl2 on all %d cells -- paired differences are exact"
                          % len(rows) if ok else
                          ("NOT EXACT on %d cell(s): %s -- contrasts from this panel are NOT admissible"
                           % (len(bad), ", ".join("%s %.3f/%.3f" % t for t in bad[:3]))
                           if bad else "no ctl2 column: exactness UNTESTED, treat contrasts as unpaired")))
    return ok


# ---------------------------------------------------------------- the falsifiers

def f_arm_worse_on_majority(d, arm, base, claim_id, rule):
    rows = d.get("rows") or []
    worse, better, tied, lines = arm_contrast(rows, arm, base)
    n = len(worse) + len(better) + len(tied)
    hit = majority(len(worse), n)
    return dict(claim=claim_id, rule=rule,
                verdict="REFUTES" if hit else "does not refute",
                detail="%s worse than %s on %d of %d cells (better %d, tied %d)"
                       % (arm, base, len(worse), n, len(better), len(tied)),
                lines=lines)


def f_stack_beats_construct_on_c204(d):
    rows = [r for r in (d.get("rows") or []) if r.get("cell") == "C204"]
    if not rows or rows[0].get("stack") is None or rows[0].get("construct") is None:
        return dict(claim="f6-constructor-c-family-null", rule="det stack better than det construct on C204",
                    verdict="no data", detail="C204 stack/construct absent from the panel", lines=[])
    r = rows[0]
    d_ = float(r["stack"]) - float(r["construct"])
    return dict(claim="f6-constructor-c-family-null",
                rule="the det stack arm better than the det construct arm on C204",
                verdict="REFUTES" if d_ < -EPS else "does not refute",
                detail="C204 stack %.3f vs construct %.3f (%+.3f)" % (float(r["stack"]), float(r["construct"]), d_),
                lines=[])


def f_lever_passes_at_n50(d):
    """levers-are-n100-levers: refuted if EITHER lever passes in the n50 production-config trial."""
    rows = d.get("rows") or []
    out = []
    for arm in ("construct", "rotation", "stack"):
        if not any(r.get(arm) is not None for r in rows):
            continue
        worse, better, tied, _ = arm_contrast(rows, arm, "ctl")
        n = len(worse) + len(better) + len(tied)
        out.append((arm, len(better), n, majority(len(better), n)))
    if not out:
        return dict(claim="levers-are-n100-levers", rule="either lever passes at n50 (F8)",
                    verdict="no data", detail="no lever arm in the F8 det artifact", lines=[])
    passed = [o for o in out if o[3]]
    return dict(claim="levers-are-n100-levers",
                rule="a production-configuration paired trial at n50 in which either lever passes",
                verdict="REFUTES" if passed else "does not refute",
                detail="; ".join("%s better on %d of %d%s" % (a, b, n, " PASSES" if p else "") for a, b, n, p in out),
                lines=[])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-register", action="store_true",
                    help="record outcomes onto the claims (author's call; off by default)")
    a = ap.parse_args()

    print("FALSIFIER BATTERY -- the falsifiers whose inputs are already banked\n")
    det = load("trial_F7_stacked_det.json")
    f8 = load("trial_F8_n50_paired_det.json")

    print("  PRE-CHECK: is the deterministic stop exact on this machine?")
    ok_det = harness_exact(det, "F7 det panel (n100)") if det else False
    if not det:
        print("  %-26s no data -- runs/oracle/trial_F7_stacked_det.json absent" % "F7 det panel (n100)")
    ok_f8 = harness_exact(f8, "F8 det panel (n50)") if f8 else False
    if not f8:
        print("  %-26s no data -- runs/oracle/trial_F8_n50_paired_det.json absent" % "F8 det panel (n50)")
    print()

    results = []
    if det and ok_det:
        results.append(f_arm_worse_on_majority(
            det, "rotation", "ctl", "f4-rotation-paired-n100-one-seed",
            "the F7 det rotation-versus-ctl contrast worse than control on a majority of the six cells"))
        results.append(f_arm_worse_on_majority(
            det, "construct", "ctl", "f5-constructor-paired-n100-one-seed",
            "the F7 det construct-versus-ctl contrast worse than control on a majority of the six cells"))
        results.append(f_arm_worse_on_majority(
            det, "rotation", "ctl", "operator-yield-n100",
            "a det-stopped schedule contrast (rotation vs ctl) worse than control on a majority"))
        r = f_arm_worse_on_majority(
            det, "stack_nofl", "stack", "warmup-unmeasured-at-n100",
            "the stack_nofl arm NO BETTER than the stack arm on a majority")
        # 'no better' is >= , not > : a tie counts toward the falsifier
        rows = det.get("rows") or []
        worse, better, tied, lines = arm_contrast(rows, "stack_nofl", "stack")
        n = len(worse) + len(better) + len(tied)
        hit = majority(len(worse) + len(tied), n)
        r.update(verdict="REFUTES" if hit else "does not refute",
                 detail="stack_nofl no better than stack on %d of %d cells (worse %d, tied %d, better %d)"
                        % (len(worse) + len(tied), n, len(worse), len(tied), len(better)),
                 lines=lines)
        results.append(r)
        results.append(f_stack_beats_construct_on_c204(det))
    elif det:
        print("  every F7 contrast is INADMISSIBLE: the exactness pre-check failed above.\n")
    if f8 and ok_f8:
        results.append(f_lever_passes_at_n50(f8))
    elif f8:
        print("  the F8 lever falsifier is INADMISSIBLE: the exactness pre-check failed above.\n")

    for r in results:
        print("  %-42s %-16s %s" % (r["claim"], r["verdict"], r["detail"]))
        print("      rule: %s" % r["rule"])
        for line in r["lines"]:
            print(line)
        print()

    ref = [r for r in results if r["verdict"] == "REFUTES"]
    nod = [r for r in results if r["verdict"] == "no data"]
    print("  %d falsifier(s) executed from banked artifacts | %d REFUTE their claim | %d had no data"
          % (len(results), len(ref), len(nod)))
    if ref:
        print("\n  THESE CLAIMS ARE REFUTED AND MUST BE RETRACTED OR RESTATED:")
        for r in ref:
            print("    %s -- %s" % (r["claim"], r["detail"]))
    print("\n  Wording note: a claim not refuted here is NOT validated. This is one test each.")

    p = os.path.join(ROOT, "runs", "oracle", "falsifier_battery.json")
    from stamp import stamped
    json.dump(stamped(dict(results=results, f7_exact=ok_det, f8_exact=ok_f8)),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))

    if a.write_register and results:
        rows = json.load(io.open(REG, encoding="utf-8"))
        idx = {r.get("id"): r for r in rows}
        n = 0
        for r in results:
            c = idx.get(r["claim"])
            if not c or r["verdict"] == "no data":
                continue
            c["falsifier_run"] = ("RUN %s by analysis/falsifier_battery.py: %s -- %s"
                                  % ("(REFUTED)" if r["verdict"] == "REFUTES" else "(not refuted)",
                                     r["rule"], r["detail"]))
            n += 1
        json.dump(rows, io.open(REG, "w", encoding="utf-8"), indent=2)
        print("  recorded %d falsifier outcome(s) onto the register" % n)
    elif results:
        print("  register NOT written (pass --write-register; an outcome changes a claim's standing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
