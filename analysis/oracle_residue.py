"""oracle-residue-open: the automated check I said could not exist.

THE REGISTERED CLAIM. "A constraint in K's ARTICLE but absent from BOTH their code and our
transcription is invisible to every layer of the oracle." Its registered falsifier is "an
automated check that detects a constraint absent from both sources", marked NOT RUN, with the
sufficiency note "No sample can settle it; that is the claim. Only a human reading the article
closes it."

WHY THAT WAS TOO QUICK. verifier3.completeness() already proves every NUMBERED constraint (1)-(30)
is accounted for. The residue is therefore not a missing number -- it is a requirement K state in
PROSE and never number. That IS mechanically findable: extract the model section, find every
sentence carrying an obligation ("must", "cannot", "at most", "exactly one", "is not allowed",
"ensures that"), and require each to be DISPOSED of -- mapped to a numbered constraint, or
explicitly recorded as narrative.

WHAT THIS IS AND IS NOT. It does not read the mathematics; it finds the places where an
obligation is asserted and forces each into the open. An obligation K state in a form this misses
-- inside a figure caption, or implied by a symbol's definition and never written as a sentence --
still escapes. So this CONVERTS an unfalsifiable claim into a checklist with a denominator. It
does not prove the residue is empty; it makes an unexamined obligation visible instead of absent.

The disposition file is validation/K_prose_obligations.json -- each sentence mapped by hand to a
numbered constraint or to NARRATIVE. Sentences with no entry FAIL, so a new one cannot be ignored
by doing nothing.

    python analysis/oracle_residue.py [--dump]
"""
import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

PDF = os.path.join(ROOT, "paper", "karademir2025-EJOR.pdf")
DISPO = os.path.join(ROOT, "validation", "K_prose_obligations.json")
OUT = os.path.join(ROOT, "runs", "oracle")

# Obligation markers. Deliberately broad: a false positive costs one line in the disposition
# file, a false negative is the thing this exists to prevent.
OBLIG = re.compile(
    r"\b(must|cannot|can not|may not|is not allowed|are not allowed|not permitted|"
    r"at most|at least|exactly one|exactly|only if|only one|ensure[sd]?|enforce[sd]?|"
    r"guarantee[sd]?|prohibit|forbid|require[sd]?|it is assumed|we assume|has to|have to)\b",
    re.I)

# The modelling section. K's formulation lives here; the computational study does not state model
# requirements, and sweeping it in would bury the signal.
SECTION_START = re.compile(r"problem\s+(description|definition)|mathematical\s+(model|formulation)",
                           re.I)
SECTION_END = re.compile(r"\b(solution\s+(method|approach)|logic[- ]based\s+benders|"
                         r"computational\s+(study|experiments|results))\b", re.I)


def pdf_text():
    try:
        import fitz
        doc = fitz.open(PDF)
        return "\n".join(p.get_text() for p in doc)
    except Exception:
        pass
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(PDF).pages)


def model_section(txt):
    """The formulation section, or the whole text when the headings cannot be located."""
    s = SECTION_START.search(txt)
    if not s:
        return txt, "WHOLE DOCUMENT (section heading not located)"
    e = SECTION_END.search(txt, s.end())
    return txt[s.start():(e.start() if e else len(txt))], "model section"


def sentences(block):
    block = re.sub(r"-\n", "", block)                 # de-hyphenate across line breaks
    block = re.sub(r"\s+", " ", block)
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])", block) if len(s.strip()) > 25]


def key_of(s):
    """Stable short key for a sentence, so the disposition file survives re-extraction."""
    import hashlib
    norm = re.sub(r"[^a-z0-9 ]", "", s.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha256(norm.encode()).hexdigest()[:12]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true",
                    help="write every undisposed obligation into the disposition file as TODO")
    a = ap.parse_args()

    if not os.path.exists(PDF):
        print("K's PDF is not present at %s -- it is fetched on demand and never committed."
              % os.path.relpath(PDF, ROOT))
        return 2
    txt = pdf_text()
    block, where = model_section(txt)
    sents = [s for s in sentences(block) if OBLIG.search(s)]
    dispo = {}
    if os.path.exists(DISPO):
        dispo = json.load(io.open(DISPO, encoding="utf-8"))

    print("oracle-residue -- every OBLIGATION K state in prose must map to a numbered constraint")
    print("                  or be recorded as narrative. Scope: %s" % where)
    print()
    print("   obligation sentences found: %d   dispositions on file: %d"
          % (len(sents), len(dispo)))
    print()

    import verifier3
    numbered = set(verifier3.PUBLISHED)
    undisposed, bad_ref, mapped = [], [], {}
    for s in sents:
        k = key_of(s)
        d = dispo.get(k)
        if not d:
            undisposed.append((k, s))
            continue
        tgt = d.get("maps_to")
        if tgt == "NARRATIVE":
            mapped.setdefault("NARRATIVE", []).append(k)
            continue
        try:
            n = int(tgt)
        except (TypeError, ValueError):
            bad_ref.append((k, s, tgt))
            continue
        if n not in numbered:
            bad_ref.append((k, s, tgt))
            continue
        mapped.setdefault(n, []).append(k)

    if a.dump:
        for k, s in undisposed:
            dispo[k] = {"sentence": s[:400], "maps_to": "TODO", "note": ""}
        os.makedirs(os.path.dirname(DISPO), exist_ok=True)
        json.dump(dispo, io.open(DISPO, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("   wrote %d TODO entries to %s" % (len(undisposed),
                                                  os.path.relpath(DISPO, ROOT)))
        print("   Each needs a numbered constraint or NARRATIVE. TODO entries FAIL this check.")
        return 1

    todo = [k for k, d in dispo.items() if d.get("maps_to") == "TODO"]
    print("   mapped to a numbered constraint: %d"
          % sum(len(v) for kk, v in mapped.items() if kk != "NARRATIVE"))
    print("   recorded as narrative:           %d" % len(mapped.get("NARRATIVE", [])))
    print("   UNDISPOSED (no entry at all):    %d" % len(undisposed))
    print("   still marked TODO:               %d" % len(todo))
    print("   mapped to a constraint that does not exist: %d" % len(bad_ref))
    print()
    for k, s in undisposed[:12]:
        print("   UNDISPOSED %s  %s" % (k, s[:104]))
    for k, s, t in bad_ref[:6]:
        print("   BAD REF    %s -> %r  %s" % (k, t, s[:84]))

    covered = sorted(kk for kk in mapped if kk != "NARRATIVE")
    silent = sorted(numbered - set(covered))
    print()
    print("   numbered constraints an obligation sentence points at: %s" % (covered or "none"))
    print("   numbered constraints no prose sentence points at:      %d of 30" % len(silent))
    print("   (silence there is expected -- K state most constraints as mathematics, not prose)")

    fails = len(undisposed) + len(todo) + len(bad_ref)
    print()
    print("oracle-residue: %d obligation(s) unaccounted for" % fails)
    if not fails and sents:
        print()
        print("   Every obligation K state in prose in the %s is disposed of: mapped to a" % where)
        print("   numbered constraint, or recorded as narrative. The claim is no longer")
        print("   unfalsifiable -- it has a denominator and a file that fails on a new sentence.")
        print()
        print("   IT IS STILL NOT A PROOF THAT THE RESIDUE IS EMPTY. An obligation carried by a")
        print("   figure caption, a table header, or a symbol definition rather than a sentence")
        print("   escapes this scan. What it removes is the ability for an obligation to go")
        print("   unexamined by default.")
    json.dump(stamped({"found": len(sents), "undisposed": [[k, s[:300]] for k, s in undisposed],
               "todo": todo, "bad_ref": [[k, t] for k, _s, t in bad_ref],
               "scope": where, "fails": fails}, __file__),
              open(os.path.join(OUT, "residue.json"), "w"), indent=1, default=str)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
