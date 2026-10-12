"""G-CLAIMS-PROSE: a document may not quote a registered claim while dropping its caveat.

WHY THIS EXISTS, AND WHY IT IS A GATE RATHER THAN A RESOLUTION. Five successive audits of the
transcription oracle each found the SAME defect shape: a claim broader than the evidence.

    v1  claimed the ARTICLE, tested the CODE
    v2  claimed attribution, omitted the distance matrix
    v3  claimed 27 independent tests, had one code path
    v4  claimed "cannot survive 27 exact matches", the detection rate is 10%
    v5  claimed "~94% confidence", the CI runs [6%, 100%]

v5's answer was to move claims into the claim register, where sufficiency must be argued and a
falsifier is mandatory. The v5 audit found that fix VOLUNTARY: the register is a parallel record,
nothing checks that a document's prose agrees with it, and v5 itself quoted its own registered
figure without the interval the register carries.

So the register only binds if something enforces it. This is that something.

THE RULE. A document that names a registered claim must also carry that claim's CAVEATS. Not its
value -- its limits. Concretely: for each registered claim a document cites, the claim's
`sufficiency` and `value` are scanned for caveat phrases (an interval, a "not", an "only", a
"nothing about"), and the document must contain at least one of them. Quoting a number while
leaving its boundary behind is precisely the failure above, and it is mechanically detectable.

WHAT IT CANNOT DO, stated so the gate is not over-read:
  * it cannot judge whether a claim is TRUE -- only whether a document repeats its limits;
  * it cannot parse arbitrary prose, so it works on documents that declare their claims in a
    `REGISTERED CLAIMS:` line;
  * a document can still overclaim about something it never registered. The register is the
    boundary of what this can police.

    python analysis/gate_claims_prose.py
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "validation", "claims.json")

# Phrases that mark a LIMIT rather than a result. A document citing a claim whose registered text
# contains one of these must carry the limit too.
CAVEAT_PATTERNS = [
    (r"\[[\d.]+\s*,\s*[\d.]+\]", "the confidence interval"),
    (r"\bNOT\b", "an explicit NOT"),
    (r"\bnot\s+(excluded|closed|independent|sufficient|covered)\b", "a 'not X' limit"),
    (r"\bonly\b", "an 'only' restriction"),
    (r"\bnothing about\b", "a 'nothing about' restriction"),
    (r"\bUNRESOLVED\b", "an UNRESOLVED disposition"),
    (r"\bone code path\b", "the single-code-path limit"),
    (r"\bspeed-selected\b|\bselected for (speed|runtime)\b", "the selection bias"),
]


def registered():
    if not os.path.exists(REG):
        return {}
    d = json.load(io.open(REG, encoding="utf-8"))
    rows = d if isinstance(d, list) else list(d.values())
    return {r["id"]: r for r in rows if isinstance(r, dict) and "id" in r}


def caveats_of(claim):
    """Caveat phrases present in a claim's registered text."""
    blob = " ".join(str(claim.get(k, "")) for k in ("value", "sufficiency", "claim"))
    out = []
    for pat, name in CAVEAT_PATTERNS:
        if re.search(pat, blob):
            out.append((pat, name))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    reg = registered()
    docs = sorted(set(
        [os.path.join(ROOT, "validation", f) for f in os.listdir(os.path.join(ROOT, "validation"))
         if f.startswith(("DESIGN_", "AUDIT_")) and f.endswith(".md")]))
    fails, checked = [], 0
    print("G-CLAIMS-PROSE -- a document may not quote a registered claim without its caveat")
    print("   register: %d claims   documents scanned: %d" % (len(reg), len(docs)))
    print()
    for path in docs:
        txt = io.open(path, encoding="utf-8", errors="replace").read()
        cited = [cid for cid in reg if cid in txt]
        if not cited:
            continue
        checked += 1
        name = os.path.basename(path)
        for cid in cited:
            cav = caveats_of(reg[cid])
            if not cav:
                print("   %-46s %-38s no registered caveat" % (name[:46], cid[:38]))
                continue
            present = [n for pat, n in cav if re.search(pat, txt)]
            if present:
                print("   %-46s %-38s ok (%s)" % (name[:46], cid[:38], present[0][:24]))
            else:
                print("   %-46s %-38s MISSING CAVEAT" % (name[:46], cid[:38]))
                fails.append("%s cites %s but carries none of its registered limits (%s)"
                             % (name, cid, ", ".join(n for _p, n in cav)))
    print()
    print("   documents citing a registered claim: %d" % checked)
    print("G-CLAIMS-PROSE: %d failure(s)" % len(fails))
    for f in fails:
        print("   " + f)
    if not fails:
        print()
        print("   PASS -- every document that cites a registered claim also carries its limits.")
        print("   THIS DOES NOT MEAN THE CLAIMS ARE TRUE. It means no document quotes a result")
        print("   while leaving its boundary behind, which is the defect five audits kept finding.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
