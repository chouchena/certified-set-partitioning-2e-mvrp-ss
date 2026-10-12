#!/usr/bin/env python
"""One home per fact. Fails when a document restates a status that lives somewhere machine-readable.

WHY THIS EXISTS, measured rather than asserted. On 2026-09-16 an audit pass found ~20 defects in
this repository and roughly 60% of them were the SAME defect: a prose document still asserting a
state the code had left behind. The false permission sentence, the AI disclosure ticked as placed
while absent from the manuscript, "Queued, not taken" for work adopted four days earlier in TWO
files, "11 ledger-only incumbents" in FIVE, a stale C7 threat row, the registry reading a
superseded AB artifact, and 14 of 28 registry entries pointing at superseded or non-existent
claims.

THE STRUCTURAL CAUSE, also measured: **61 of 202 markdown documents assert status** -- a tick, a
DONE, a BLOCKING, a "queued" -- and one fact typically lives in **four to six of them**. There
were eleven checkers and none of them looked across documents. So a fact changed in code and five
prose homes went on asserting the old state indefinitely, each of them looking authoritative.

THE RULE THIS ENFORCES: a status that can be derived belongs in exactly one machine-readable
place, and prose REFERENCES it rather than restating it. Where prose does restate -- sometimes it
must, for readability -- the restatement must agree, and this check is what makes that true rather
than hoped.

PRECISION OVER COVERAGE, deliberately. `analysis/notation_audit.py` once produced 54 findings and
had to be rewritten twice, and this repository's own rule is that an audit which invents findings
stops being believed. So every check here fires only on an UNAMBIGUOUS contradiction: a document
naming a registry id and giving a different value, a claim id that is not STANDING, a gate verdict
asserted in prose that the gate itself contradicts. Anything requiring a judgement call is left
out rather than guessed at.

Usage:
    python analysis/status_audit.py            # report
    python analysis/status_audit.py --check    # exit 1 on any contradiction
    python analysis/status_audit.py --self-test
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Documents that are HISTORICAL RECORDS and are supposed to preserve what was true when written.
# Correcting these would destroy the audit trail, which is the opposite of the point.
HISTORICAL = ("validation/claims.json", "CLAIMS.md", "SESSION_", "AUDIT_", "FINDING_",
              "RESULT_", "PREREG_", "DECISION_", "GAP_", "DEFECT_", "BACKUP_LOG")


def _is_historical(rel):
    base = os.path.basename(rel)
    return any(h in rel or base.startswith(h) for h in HISTORICAL)


def _docs():
    out = []
    for pat in ("paper/*.md", "validation/*.md", "*.md", "paper/manuscript/*.md"):
        out.extend(glob.glob(os.path.join(ROOT, pat)))
    return sorted(set(os.path.relpath(p, ROOT).replace("\\", "/") for p in out))


def _registry():
    p = os.path.join(ROOT, "paper", "numbers.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def _claims():
    p = os.path.join(ROOT, "validation", "claims.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    recs = d if isinstance(d, list) else d.get("claims", d)
    it = recs if isinstance(recs, list) else [dict(v, id=k) for k, v in recs.items()]
    return {r.get("id"): r for r in it if r.get("id")}


# ---------------------------------------------------------------- S1
def s1_registry_claims_standing(reg, claims):
    """Every registry entry's claim id must exist and be STANDING.

    Caught 14 of 28 on its first run, including all seven S3a entries -- the paper's central
    defence -- and `s2k-closure`, which feeds five \\num{} calls in the only drafted subsection of
    the computational study. No existing gate saw this: claims.py validates the register
    internally and never reads numbers.json, and g10_claims_gate is non-blocking.
    """
    bad = []
    for nid, meta in sorted(reg.items()):
        cid = meta.get("claim")
        if not cid:
            continue
        r = claims.get(cid)
        if r is None:
            bad.append((nid, cid, "DOES NOT EXIST"))
        elif r.get("status") != "STANDING":
            bad.append((nid, cid, r.get("status")))
    return bad


# ---------------------------------------------------------------- S2
def s2_prose_contradicts_registry(reg):
    """A document that NAMES a registry id and then gives a value it does not have.

    Precise by construction: it fires only where prose explicitly cites the id, so it cannot
    misread an unrelated number that happens to collide. This is the STORY_ARC Beat 3 case --
    the paragraph named `ab-crossovers-by-size`, asserted "agrees with paper/numbers.tex", and
    gave 7 of 27 where the registry said 6. It then instructed, in the same breath, that these
    digits "must be \\num{...}, never retyped".
    """
    flat = {}
    for nid, meta in reg.items():
        v = meta.get("value")
        if isinstance(v, dict):
            for k, kv in v.items():
                flat[f"{nid}.{k}"] = str(kv)
        else:
            flat[nid] = str(v)
    bad = []
    for rel in _docs():
        if _is_historical(rel):
            continue
        try:
            text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        except Exception:
            continue
        for nid in sorted(reg):
            if not re.search(r"`%s[.`]" % re.escape(nid), text):
                continue
            vals = {v for k, v in flat.items() if k == nid or k.startswith(nid + ".")}
            # Only "<n> of <m>" values, and only where the DENOMINATOR matches one the entry
            # uses. Scoped to the whole document, not a window after the id: the STORY_ARC case
            # names the id in a footnote 16 lines BELOW the sentence carrying the wrong digits,
            # and a forward window missed it entirely on the first run of this check.
            dens = {v.split(" of ")[1] for v in vals if " of " in v}
            if not dens:
                continue
            for m in re.finditer(r"\b(\d+) of (\d+)\b", text):
                cnt, den = m.group(0), m.group(2)
                if den in dens and cnt not in vals:
                    # A document may legitimately cite ANOTHER entry with the same denominator.
                    # Suppress when some other registry entry carries this exact value.
                    if any(cnt == v for k, v in flat.items()
                           if not (k == nid or k.startswith(nid + "."))):
                        continue
                    bad.append((rel, nid, cnt, tuple(sorted(vals)[:6])))
    return sorted(set(bad))


# ---------------------------------------------------------------- S3
def s3_gate_verdict_restated(gate_status):
    """A document asserting a gate FAILS when the gate passes, or vice versa.

    `paper/RELEASE_DESIGN.md` carried "| **FAIL** | G8 every quoted incumbent artifact-backed |"
    after G8 had been cleared, in the document that describes how the release is produced.
    """
    if not gate_status:
        return []
    bad = []
    for rel in _docs():
        if _is_historical(rel):
            continue
        try:
            text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        except Exception:
            continue
        for line in text.splitlines():
            m = re.search(r"\b(G\d+[a-z]?)\b", line)
            if not m:
                continue
            gid = m.group(1)
            if gid not in gate_status:
                continue
            says_fail = re.search(r"\*\*FAIL\*\*|\bFAIL\b", line)
            says_pass = re.search(r"\*\*PASS\*\*|\bPASS\b", line)
            live = gate_status[gid]
            if says_fail and not says_pass and live == "PASS":
                bad.append((rel, gid, "prose says FAIL, gate says PASS", line.strip()[:88]))
            elif says_pass and not says_fail and live == "FAIL":
                bad.append((rel, gid, "prose says PASS, gate says FAIL", line.strip()[:88]))
    return bad


def _gate_status():
    """Live gate verdicts, if the gate can be run cheaply. Returns {} when unavailable."""
    p = os.path.join(ROOT, "analysis", "release_gate.py")
    if not os.path.exists(p):
        return {}
    try:
        r = subprocess.run([sys.executable, p], cwd=ROOT, capture_output=True,
                           text=True, timeout=900)
    except Exception:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        m = re.match(r"\s*\[\s*(\*\*)?(PASS|FAIL|warn)(\*\*)?\s*\]\s*(G\d+[a-z]?)\b", line)
        if m:
            out[m.group(4)] = "PASS" if m.group(2) == "PASS" else ("FAIL" if m.group(2) == "FAIL" else "warn")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-gate", action="store_true", help="skip S3 (does not run release_gate)")
    args = ap.parse_args()

    if args.self_test:
        ok = True
        reg = {"x-id": {"claim": "nope", "value": "6 of 27"}}
        if not s1_registry_claims_standing(reg, {}):
            print("SELF-TEST FAIL: S1 missed a non-existent claim id"); ok = False
        if s1_registry_claims_standing({"y": {"claim": "c", "value": "1"}},
                                       {"c": {"status": "STANDING"}}):
            print("SELF-TEST FAIL: S1 fired on a STANDING claim"); ok = False
        print("SELF-TEST PASS" if ok else "SELF-TEST FAILED")
        return 0 if ok else 1

    reg, claims = _registry(), _claims()
    print("=" * 76)
    print("STATUS AUDIT -- one home per fact")
    print("=" * 76)

    problems = 0

    b1 = s1_registry_claims_standing(reg, claims)
    print("\nS1  registry entries whose claim is missing or not STANDING")
    if b1:
        for nid, cid, st in b1:
            print("    %-32s -> %-44s %s" % (nid, cid, st))
        problems += len(b1)
    else:
        print("    none of %d entries" % len(reg))

    b2 = s2_prose_contradicts_registry(reg)
    print("\nS2  prose naming a registry id and giving a value it does not have")
    if b2:
        for rel, nid, cnt, vals in b2:
            print("    %s: cites `%s` then says %r; registry has %s" % (rel, nid, cnt, vals))
        problems += len(b2)
    else:
        print("    none")

    if args.no_gate:
        print("\nS3  skipped (--no-gate)")
    else:
        gs = _gate_status()
        b3 = s3_gate_verdict_restated(gs)
        print("\nS3  prose asserting a gate verdict the gate contradicts  (%d gates read)" % len(gs))
        if b3:
            for rel, gid, why, line in b3:
                print("    %s [%s] %s" % (rel, gid, why))
                print("        %s" % line)
            problems += len(b3)
        else:
            print("    none")

    print()
    if args.check:
        if problems:
            print("FAIL: %d contradiction(s). A status with two homes is a status that will "
                  "disagree with itself." % problems)
            return 1
        print("OK: no document contradicts a machine-readable status.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
