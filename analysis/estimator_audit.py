#!/usr/bin/env python
"""One quantity, one definition. Fails when a second estimator appears.

The direct analogue of `analysis/notation_audit.py`, which enforces "one letter, one meaning"
for symbols. Estimators have the same failure mode and had no enforcer until 2026-09-16, which
is how `frontier()` came to exist in three files at once -- identical when written, already
drifted (`k` versus `kf`) by the time anyone looked.

Proposal P2 of validation/AUDIT_estimator_specification.md. Decision:
validation/DECISION_reported_bound_estimator.md.

WHAT IT FLAGS. Any reduction of a record list to a single bound outside `lb_estimator.py` --
`max(... block_relax ...)` and friends. That is the operation the decision reserves.

WHY PAPER-PRODUCING MODULES ARE HELD TO A HIGHER STANDARD THAN MONITORS. A monitor that prints
the best bound it has seen so far is not making a claim; it is a progress display, and requiring
it to route through the registry's estimator would be ceremony. A module that writes
paper/numbers.tex, paper/tables/ or paper/figures/ IS making a claim. The two lists below encode
that distinction explicitly, so that moving a script from one category to the other is a visible
edit rather than an accident.

AN AUDIT THAT INVENTS FINDINGS STOPS BEING BELIEVED -- recorded in this project on 2026-09-15
after notation_audit.py produced 54 of them. This one is deliberately narrow: it matches the
reduction operation on the one field that carries a bound, and it ships with a negative control
(`--self-test`) asserting that it fires on a planted violation and stays silent on the monitors.

Usage:
    python analysis/estimator_audit.py              # report
    python analysis/estimator_audit.py --check      # exit 1 on any violation
    python analysis/estimator_audit.py --self-test  # negative control
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS = os.path.join(ROOT, "analysis")

# The single permitted home for the reduction, plus this file -- whose PATTERNS necessarily
# SPELL the thing being banned. An audit that reports itself is the "invents findings" failure in
# its purest form, and it fired on the first run.
CANONICAL = "lb_estimator.py"
EXEMPT = {CANONICAL, "estimator_audit.py"}

# Modules that produce paper artifacts. A second estimator here is a defect, not a convenience.
PAPER_PRODUCING = {
    "manuscript_numbers.py",
    "make_tables.py",
    "make_figures.py",
    "release_gate.py",
    "n100_budget_forward_check.py",
    "rt_leg_descriptives.py",
    # S3a IS paper-producing: it is section 7.3, the ablation the venue decision rested on.
    "s3a_ablation_compare.py",
    "s3a_significance.py",
    "s3a_friedman_holm.py",
}

# Monitors, probes and one-off campaign scripts. They print progress; they do not make claims.
# Listed rather than inferred, so that a script graduating to paper-producing is a visible edit.
DIAGNOSTIC = {
    "cellreport.py", "lb_campaign.py", "lb_crossing_samehw.py", "lb_monitor.py",
    "lb_n100_probe.py", "lb_n20_reprov.py", "lb_n30.py", "lb_repair_n30.py",
    "lb_reprov.py", "lb_verdict_watch.py", "n30_rollup.py", "reference_set_audit.py",
    "replay_verify.py", "rt_normalize.py", "rt_fair_pipeline.py",
}

# The reduction, on the one field that carries a bound. Narrow on purpose.
PATTERNS = [
    (re.compile(r"\bmax\s*\([^)]*block_relax"), "max(... block_relax ...)"),
    (re.compile(r"\bblock_relax[^\n]*\bmax\s*\("), "block_relax ... max("),
    (re.compile(r"\bsorted\s*\([^)]*block_relax[^\n]*\)\s*\[-1\]"), "sorted(...)[-1] on block_relax"),
]

# A SECOND DEFINITION OF THE FRONTIER IS THE SAME DEFECT BY ANOTHER NAME. The proved frontier
# lives in lb_estimator; a local `def frontier` is a copy, and copies drift -- three of them
# already had.
DEF_PATTERN = re.compile(r"^\s*def\s+_?frontier\s*\(")

# The reduction split across lines: a list built from block_relax, reduced a line or two later.
# This is what the single-line patterns missed, and it missed three paper-producing modules.
BIND_PATTERN = re.compile(r"^\s*(\w+)\s*=\s*\[[^\]]*block_relax")
REDUCE_PATTERN = re.compile(r"\b(?:max|sorted)\s*\(\s*(\w+)")
WINDOW = 4


def scan_text(text, fname):
    """Violations in one file's source, as (lineno, line, why)."""
    out = []
    lines = text.splitlines()
    pending = {}                          # varname -> lineno where it was bound from block_relax
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue                      # a comment describing the rule is not a violation
        hit = None
        for rx, why in PATTERNS:
            if rx.search(line):
                hit = why
                break
        if hit is None and DEF_PATTERN.match(line):
            # A WRAPPER THAT DELEGATES IS NOT A SECOND DEFINITION. manuscript_numbers,
            # make_tables and make_figures each keep a thin `frontier(cell, size)` that opens
            # the artifact and hands it to lb_estimator -- that is the intended shape, and
            # flagging it would be the false positive that gets an audit switched off.
            body = "\n".join(lines[i:i + 14])
            if "lb_estimator." not in body:
                hit = "a second definition of frontier() that does not delegate"
        if hit is None:
            m = REDUCE_PATTERN.search(line)
            if m and m.group(1) in pending and i - pending[m.group(1)] <= WINDOW:
                hit = "max(%s) where %s was built from block_relax" % (m.group(1), m.group(1))
        b = BIND_PATTERN.match(line)
        if b:
            pending[b.group(1)] = i
        if hit:
            out.append((i, stripped, hit))
    return out


def scan_repo():
    findings = {}
    for fname in sorted(os.listdir(ANALYSIS)):
        if not fname.endswith(".py") or fname in EXEMPT:
            continue
        path = os.path.join(ANALYSIS, fname)
        with open(path, "r", encoding="utf-8") as fh:
            hits = scan_text(fh.read(), fname)
        if hits:
            findings[fname] = hits
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 on any paper-producing violation")
    ap.add_argument("--self-test", action="store_true", help="negative control")
    args = ap.parse_args()

    if args.self_test:
        planted = "def f(recs):\n    return max(r['block_relax'] for r in recs)\n"
        clean = "def f(recs):\n    return lb_estimator.cell_bound(recs)\n"
        commented = "# we used to write max(x['block_relax'] ...) here\nx = 1\n"
        ok = True
        if not scan_text(planted, "planted.py"):
            print("SELF-TEST FAIL: did not fire on a planted reduction"); ok = False
        if scan_text(clean, "clean.py"):
            print("SELF-TEST FAIL: fired on a correct call"); ok = False
        if scan_text(commented, "commented.py"):
            print("SELF-TEST FAIL: fired on a comment"); ok = False
        print("SELF-TEST PASS" if ok else "SELF-TEST FAILED")
        return 0 if ok else 1

    findings = scan_repo()
    hard, soft, unknown = {}, {}, {}
    for fname, hits in findings.items():
        (hard if fname in PAPER_PRODUCING
         else soft if fname in DIAGNOSTIC
         else unknown)[fname] = hits

    print("=" * 74)
    print("ESTIMATOR AUDIT -- one quantity, one definition")
    print("canonical: analysis/%s" % CANONICAL)
    print("=" * 74)

    if hard:
        print("\nVIOLATIONS -- paper-producing modules. These must call lb_estimator.")
        for fname, hits in sorted(hard.items()):
            for ln, src, why in hits:
                print("  analysis/%s:%d  %s" % (fname, ln, why))
                print("      %s" % src[:100])
    else:
        print("\nNo paper-producing module computes its own bound.")

    if unknown:
        print("\nUNCLASSIFIED -- not in either list. Classify before the gate can pass.")
        for fname, hits in sorted(unknown.items()):
            print("  analysis/%s  (%d)" % (fname, len(hits)))

    if soft:
        print("\nAllowed (diagnostics, %d modules): %s"
              % (len(soft), ", ".join(sorted(soft))))

    if args.check:
        if hard or unknown:
            print("\nFAIL: %d paper-producing and %d unclassified module(s)."
                  % (len(hard), len(unknown)))
            return 1
        print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
