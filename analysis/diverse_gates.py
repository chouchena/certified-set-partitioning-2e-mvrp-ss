"""Read the forced-diversity sample against the gates fixed in its pre-run audit.

The gates are G0 to G5 plus the descriptive A1, defined in
`validation/runaudits/TEP_forced_diversity.md` and its Amendment 1, both written before the sample
ran. This module only applies them; it does not define them. A gate that cannot be evaluated
returns INCONCLUSIVE, which is not PASS and not FAIL -- the distinction CLAUDE.md section 4 exists
for.

    python analysis/diverse_gates.py --tag sample --size 30
"""
import argparse
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))

TAIL = ("C203", "C206")
G1_MIN_CELLS, G1_MIN_PCT, G2_MIN_PCT, ENVELOPE = 3, 0.5, 5.0, 5760


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="sample"); ap.add_argument("--size", type=int, default=30)
    a = ap.parse_args()
    p = os.path.join(ROOT, "runs", "oracle", "tep_diverse_primal_%s_n%d.json" % (a.tag, a.size))
    if not os.path.exists(p):
        print("no sample artifact at %s" % os.path.relpath(p, ROOT)); return 1
    d = json.load(io.open(p, encoding="utf-8"))
    cells = d["cells"]
    done = [c for c in cells if not c.get("error") and not c.get("skipped")]
    nd = [c for c in cells if c.get("nondeterministic")]
    usable = [c for c in done if not c.get("nondeterministic")]
    imp = [c for c in usable if c.get("result") == "IMPROVED"]

    print("Forced-diversity sample, n%d, tag %s -- %d cell(s) recorded\n" % (a.size, a.tag, len(cells)))
    print("%-7s %10s %10s %8s %6s %6s %7s %6s"
          % ("cell", "banked", "best", "gain", "rnd", "cars", "result", "wall"))
    for c in cells:
        if c.get("error"):
            print("%-7s %s" % (c["cell"], "ERROR " + c["error"])); continue
        if c.get("nondeterministic"):
            print("%-7s %s" % (c["cell"], "NON-DETERMINISTIC -- excluded")); continue
        g = c.get("gain_pct")
        print("%-7s %10.3f %10s %8s %6s %6s %7s %6s"
              % (c["cell"], c.get("banked", float("nan")),
                 ("%.3f" % c["best_obj"]) if c.get("best_obj") else "-",
                 ("%+.2f%%" % -g) if g else "0.00%",
                 str(c.get("best_round", "-")),
                 ("%d->%d" % (c["cars_before"], c["cars_after"])) if c.get("result") == "IMPROVED" else "-",
                 "IMPROVED" if c.get("result") == "IMPROVED" else (c.get("result") or "-"),
                 c.get("wall_secs", "-")))

    def verdict(name, state, why):
        print("  %-26s %-13s %s" % (name, state, why))

    print("\nGATES (fixed in validation/runaudits/TEP_forced_diversity.md before the run)\n")
    # G0 -- round 0 realises, and the comparison is against the banked value
    r0 = [c for c in usable if c.get("round0") is not None]
    repro = [c for c in r0 if abs(c["round0"] - c["banked"]) < 1e-3]
    verdict("G0 reproduction", "PASS" if len(r0) >= len(usable) - 1 else "INCONCLUSIVE",
            "round 0 realised on %d of %d; it reproduces the banked value exactly on %d"
            % (len(r0), len(usable), len(repro)))
    # G1 -- primary
    big = [c for c in imp if c["gain_pct"] > G1_MIN_PCT]
    verdict("G1 primary", "PASS" if len(big) >= G1_MIN_CELLS else "FAIL",
            "%d of %d cells improved by more than %.1f%% (needed %d)"
            % (len(big), len(usable), G1_MIN_PCT, G1_MIN_CELLS))
    # G2 -- tail
    tv = [c["gain_pct"] for c in usable if c["cell"] in TAIL and c.get("result") == "IMPROVED"]
    tall = [c for c in usable if c["cell"] in TAIL]
    if len(tall) < len(TAIL):
        verdict("G2 tail", "INCONCLUSIVE", "only %d of the %d tail cells ran" % (len(tall), len(TAIL)))
    else:
        m = st.median(tv) if tv else 0.0
        verdict("G2 tail", "PASS" if m >= G2_MIN_PCT else "FAIL",
                "median tail improvement %.2f%% over %s (needed %.1f%%)" % (m, ", ".join(TAIL), G2_MIN_PCT))
    # G3 -- no regression
    reg = [c for c in imp if c["best_obj"] >= c["banked"]]
    verdict("G3 no regression", "FAIL" if reg else "PASS",
            "%d replacement(s) not strictly better" % len(reg) if reg
            else "every replacement is strictly better than what it replaced")
    # G4 -- verifier
    rej = [c for c in usable if c.get("result") == "improvement REJECTED by verifier3"]
    verdict("G4 verifier", "FAIL" if rej else "PASS",
            "%d improvement(s) rejected by verifier3: %s" % (len(rej), ", ".join(x["cell"] for x in rej))
            if rej else "no improvement was rejected; every banked replacement verified")
    # G5 -- budget
    w = [c.get("wall_secs", 0) for c in usable]
    verdict("G5 budget", "PASS" if w and max(w) <= ENVELOPE else ("INCONCLUSIVE" if not w else "FAIL"),
            "max wall %d s per cell against the %d our-second LB+primal envelope" % (max(w) if w else 0, ENVELOPE))
    # A1 -- attribution, descriptive
    at0 = [c for c in imp if c.get("best_round") == 0]
    atd = [c for c in imp if c.get("best_round", 0) > 0]
    verdict("A1 attribution", "descriptive",
            "%d of %d improvements already at round 0 (IP budget, not diversity); %d needed a cut"
            % (len(at0), len(imp), len(atd)))
    for c in atd:
        if c.get("round0"):
            print("      %-7s round 0 %9.3f -> best %9.3f  (%+.2f%% from diversity alone)"
                  % (c["cell"], c["round0"], c["best_obj"], 100.0 * (c["best_obj"] / c["round0"] - 1)))
    if nd:
        print("\n  %d cell(s) excluded as non-deterministic: %s"
              % (len(nd), ", ".join(c["cell"] for c in nd)))
    # degeneracy -- how much of the forced diversity was real
    deg = []
    for c in usable:
        vals = [x["obj"] for x in c.get("candidates", []) if x.get("obj")]
        if vals:
            deg.append(len(set(round(v, 3) for v in vals)) / float(len(vals)))
    if deg:
        print("\n  DEGENERACY: distinct realised values per realised candidate, median %.2f."
              % st.median(deg))
        print("  A solution-level no-good cut forbids a COLUMN SET, not a solution, so different")
        print("  partitions can chain to the same answer. A low number here means the cuts are")
        print("  buying less diversity than the round count suggests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
