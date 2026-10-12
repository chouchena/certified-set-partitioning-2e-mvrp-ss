"""TRANSCRIPTION AUDIT: is verifier3's reading of K's (1)-(30) corroborated by sources that are
NOT my reading?

Design: validation/DESIGN_transcription_audit.md
Design audit: validation/AUDIT_design_transcription.md  (five mandated changes, all applied below)

THE GAP THIS ADDRESSES. verifier3 checks K's published constraints AS I TRANSCRIBED THEM from a
rendered PDF page. If my reading is wrong, verifier3 is wrong identically, and every ACCEPT it has
issued inherits the error.

WHY THIS IS NOT A FOURTH VERIFIER. One written by me, from the same reading, would reproduce my
errors and then AGREE with verifier3 -- confidence manufactured, nothing tested. The only
defensible verifier4 is one transcribed from a DIFFERENT SOURCE, and that is exactly what verify2
was: its classes came from joint_model_cplex, itself transcribed from K's code weeks before I read
the article. That differential already ran -- identical verdicts on 17 |C|=100 dumps -- so
rebuilding it would re-derive a result in hand. What it lacked was POWER: 15 of those 17 rejected
on C26, and a dump that fails early exercises nothing else.

THREE LEGS, each against a source that is not my reading:

  A  the PDF's own GLYPHS, extracted mechanically (pypdf recovers U+1D4xx math italics)
  B  K's FOUR released encodings -- integratedJointModel, DecomposedModels,
     subproblem_bounded_cplex, LBBDmodel
  C  the 59 verified incumbents, which bound OVER-strictness only

AND AN IRREDUCIBLE RESIDUE, stated up front: a constraint in the ARTICLE but absent from BOTH the
glyph extraction AND K's code cannot be detected here -- both sides are silent. That class is not
hypothetical: (26) is in the article and vacuous in their code. Only a human reading the article
closes it. This audit NARROWS the gap and NAMES the residue; it does not eliminate it.

    python analysis/transcription_audit.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

import verifier3

PDF = os.path.join(ROOT, "paper", "karademir2025-EJOR.pdf")
OUT = os.path.join(ROOT, "runs", "transcription_audit")

# CHANGE 2 (audit A2): Leg B spans ALL FOUR of K's encodings, not one. DecomposedModels posts MORE
# rows than the joint model and is a genuinely separate encoding; a constraint I omitted is far
# likelier to be caught against several of their files than against one.
K_ENCODINGS = ["integratedJointModel.py", "DecomposedModels.py",
               "subproblem_bounded_cplex.py", "LBBDmodel.py"]

# My transcription, as verifier3 holds it. The audit asks whether each is corroborated.
# `symbols` is the multiset of variable/parameter symbols the ARTICLE's equation should contain,
# written from my transcription -- Leg A compares it against what the PDF actually renders.
TRANSCRIPTION = {
    1:  dict(sym=["beta", "x", "c", "f", "y"], rel=["min"],
             kcode=["zObj", "setObjective"], note="objective (1)"),
    2:  dict(sym=["x"], rel=["=", "="], kcode=["Const2"], note="degree 1 per customer"),
    3:  dict(sym=["x", "K"], rel=["=", "<="], kcode=["Const3"], note="LEFV fleet"),
    4:  dict(sym=["phi", "x"], rel=[">="], kcode=["Const4"], note="final transfer"),
    5:  dict(sym=["m", "q", "Q", "x", "phi"], rel=[">="], kcode=["Const5"], note="LEFV capacity"),
    6:  dict(sym=["h", "tau", "f", "U", "phi", "M", "x"], rel=["<="], kcode=["Const8"],
             note="street arc timing"),
    7:  dict(sym=["f", "t", "x", "phi"], rel=[">="], kcode=["Const9"], pat=r"arcStreetCost\[i,\s*j\]\s*>=", note="f^s definition"),
    8:  dict(sym=["x"], rel=["in"], kcode=[], note="x binary"),
    9:  dict(sym=["phi"], rel=["in"], kcode=[], note="phi binary"),
    10: dict(sym=["v", "phi"], rel=["="], kcode=["Const12"], pat=r"vip\[i,\s*p\].*for p in Satellites\)\s*==\s*vi\[i\]",
             note="one satellite iff transfer"),
    11: dict(sym=["u", "h", "tau", "t", "v"], rel=[">="], kcode=["Const13"],
             note="transfer start"),
    12: dict(sym=["u", "U", "t", "v", "h", "M", "x"], rel=["<="], kcode=["Const14"],
             note="departure after transfer"),
    13: dict(sym=["a", "t", "v", "u", "b", "U"], rel=["<=", "<="], kcode=["Const15"],
             note="vessel window on u"),
    14: dict(sym=["f", "t", "x", "v"], rel=[">="], kcode=["Const14"], note="f^s at a transfer"),
    15: dict(sym=["v"], rel=["in"], kcode=[], note="v binary"),
    16: dict(sym=["y", "v"], rel=["=", "="], kcode=["Const18"], note="vessel degree"),
    17: dict(sym=["y", "K"], rel=["=", "<="], kcode=["Const19"], note="vessel fleet"),
    18: dict(sym=["m", "l", "Q"], rel=["<=", "<="], kcode=["Const20"], note="vessel capacity"),
    19: dict(sym=["l", "m", "Q", "y"], rel=[">="], kcode=["Const21"], note="vessel load acc"),
    20: dict(sym=["u", "U", "f", "M", "y"], rel=["<="], kcode=["Const22"], note="vessel seq"),
    21: dict(sym=["f", "t", "y", "v"], rel=[">="], kcode=["Const23"], note="f^w depot leg"),
    22: dict(sym=["f", "t", "y", "v"], rel=[">="], kcode=["Const23"], note="f^w return leg"),
    23: dict(sym=["f", "t", "y", "v"], rel=[">="], kcode=["Const24"], note="f^w hub-to-hub"),
    24: dict(sym=["f"], rel=[">="], kcode=[], note="f^w >= 0"),
    25: dict(sym=["y"], rel=["in"], kcode=[], note="y binary"),
    26: dict(sym=["u", "U", "v"], rel=[">="], kcode=["singleTransfer"], note="(26) separation"),
    27: dict(sym=["u", "r"], rel=["<="], kcode=["singleTransfer"], note="lin of (26)"),
    28: dict(sym=["u", "r"], rel=["<="], kcode=["singleTransfer"], note="lin of (26)"),
    29: dict(sym=["r"], rel=["="], kcode=["singleTransfer"], note="lin of (26)"),
    30: dict(sym=["r", "U", "v"], rel=[">="], kcode=["singleTransfer"], note="lin of (26)"),
}

# Unicode math italics -> the ASCII symbol name my transcription uses.
GLYPH = {
    "\U0001d465": "x", "\U0001d466": "y", "\U0001d462": "u", "\U0001d45a": "m",
    "\U0001d459": "l", "\U0001d461": "t", "\U0001d45e": "q", "\U0001d44e": "a",
    "\U0001d44f": "b", "\U0001d443": "P", "\U0001d436": "C", "\U0001d440": "M",
    "\U0001d444": "Q", "\U0001d43e": "K", "\U0001d453": "f", "\U0001d448": "U",
    "\U0001d463": "v", "\U0001d461̅": "t",
    "\U0001d719": "phi", "\U0001d70f": "tau", "\U0001d6fd": "beta", "\U0001d45f": "r",
    "ϕ": "phi", "τ": "tau", "β": "beta",
    "\U0001d450": "c", "ℎ": "h", "\U0001d45d": "p", "\U0001d456": "i",
    "\U0001d457": "j",
}
RELS = ["<=", ">=", "≤", "≥", "=", "∈", "min"]


def extract_glyphs():
    """Leg A. Mechanical: no reading by me. Returns {eq_number: raw string}."""
    import pypdf
    r = pypdf.PdfReader(PDF)
    eqs = {}
    for pno in (5, 6, 7, 8):
        pg = r.pages[pno]
        out = []

        def visit(text, cm, tm, font, size, _o=out):
            if text.strip():
                _o.append((round(tm[5], 1), round(tm[4], 1), text))
        pg.extract_text(visitor_text=visit)
        out.sort(key=lambda z: (-z[0], z[1]))
        lines = []
        for y, x, t in out:
            if lines and abs(lines[-1][0] - y) < 3.0:
                lines[-1][1].append((x, t))
            else:
                lines.append([y, [(x, t)]])
        rendered = [("".join(t for _x, t in sorted(parts))).strip() for _y, parts in lines]
        for idx, s in enumerate(rendered):
            m = re.search(r"\((\d{1,2})\)\s*$", s)
            if not m:
                continue
            n = int(m.group(1))
            if not (1 <= n <= 30) or n in eqs:
                continue
            # REJECT A PROSE CROSS-REFERENCE. Found by the code audit: (12) captured
            # "...while constraints (12)" -- a citation, not the equation. Its PARTIAL 0/7 was
            # the symptom and the verdict logic let it through because kcode was present.
            if re.search(r"(constraints?|Constraints?|equations?|see)\s*$",
                         s[:m.start()].strip()[-14:]):
                continue
            # MERGE THE BAND. Equations span lines -- (6) and (7) were captured as fragments.
            # Take the two preceding rendered lines with the marker line.
            band = " ".join(rendered[max(0, idx - 2):idx + 1])
            # REQUIRE MATH. A line with no relational operator and no math italics is prose.
            if not any(r in band for r in ("≤", "≥", "=")):
                continue
            dens = sum(1 for ch in band if ch in GLYPH) / max(1, len(band))
            if dens < 0.03:
                continue
            eqs[n] = band
    return eqs


def glyph_symbols(raw):
    """Symbols and relations present in a rendered equation."""
    syms, rels = set(), []
    for ch in raw:
        if ch in GLYPH:
            syms.add(GLYPH[ch])
    for r in ("≤", "≥", "∈"):
        if r in raw:
            rels.append({"≤": "<=", "≥": ">=", "∈": "in"}[r])
    if "=" in raw:
        rels.append("=")
    return syms, rels


def kcode_rows():
    """Leg B1. Which of K's four encodings carries each marker, and how many rows each posts.

    LABELLED HONESTLY (audit A3): this is TWO READINGS THAT MUST AGREE, not an independent check.
    Locating 'the rows for (5)' in their code and judging operand equivalence is me reading again.
    It raises the cost of an error from one misreading to two consistent ones -- real, but not
    mechanical.
    """
    found = {}
    for f in K_ENCODINGS:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        src = io.open(p, encoding="utf-8", errors="replace").read()
        found[f] = {"markers": set(re.findall(r"#\s*(Const\d+)", src)),
                    "rows": src.count("addConstr") + src.count("add_constraint"),
                    "singleTransfer": "singleTransfer" in src}
    return found


def corpus_exercise():
    """Leg C. Which verifier3 classes the 59 verified incumbents actually evaluated.

    Bounds OVER-strictness only: if I had invented or tightened a constraint, those solutions
    would have failed. It is SILENT on omission -- a missing constraint produces no failure.
    """
    ex = {}
    log = os.path.join(ROOT, "logs", "verifier3.jsonl")
    if os.path.exists(log):
        for line in io.open(log, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            for k, v in (r.get("checks_run") or {}).items():
                ex[k] = ex.get(k, 0) + v
    return ex


def main():
    os.makedirs(OUT, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    eqs = extract_glyphs()
    kc = kcode_rows()
    ex = corpus_exercise()

    print("TRANSCRIPTION AUDIT -- is verifier3's reading corroborated by sources that are not mine?")
    print()
    # CHANGE 1 (audit A1): report 15/30 honestly and name the missing half.
    got = sorted(eqs)
    missing = sorted(set(range(1, 31)) - set(got))
    print("LEG A -- mechanical glyph extraction from the PDF")
    print("   extracted %d/30 : %s" % (len(got), got))
    print("   NOT EXTRACTED   : %s" % missing)
    print("   The missing half includes (26) itself and its linearization (27),(28),(30), plus")
    print("   the objective (1). Multi-line equations, large operators and the two-column split")
    print("   defeat the extractor. Leg A is corroboration for the half it reaches, nothing more.")
    print()
    print("LEG B -- K's four released encodings (two readings that must agree, NOT independent)")
    for f, d in kc.items():
        print("   %-30s %3d rows   markers %s%s"
              % (f, d["rows"],
                 ",".join(sorted(m[5:] for m in d["markers"])) or "none",
                 "   +singleTransfer" if d["singleTransfer"] else ""))
    print()
    print("LEG C -- the 59 verified incumbents: bounds OVER-strictness only, silent on omission")
    print("   %d classes exercised, %d evaluations" % (len(ex), sum(ex.values())))
    print()

    rows = []
    hdr = "%-4s %-22s %-11s %-9s %-9s %s" % ("(n)", "constraint", "glyphs", "kcode", "corpus",
                                             "verdict")
    print(hdr)
    print("-" * 86)
    for n in range(1, 31):
        t = TRANSCRIPTION[n]
        # Leg A
        if n in eqs:
            syms, rels = glyph_symbols(eqs[n])
            want = set(t["sym"])
            hit = want & syms
            glyph = "MATCH" if len(hit) >= max(1, len(want) - 1) else "PARTIAL %d/%d" % (len(hit),
                                                                                         len(want))
        else:
            glyph = "not-extr"
        # Leg B1
        if t["kcode"]:
            present = any(any(m in d["markers"] or (m == "singleTransfer" and d["singleTransfer"])
                              for m in t["kcode"]) for d in kc.values())
            # MARKERS ARE INCOMPLETE in K's code -- it carries no Const9 or Const12 comment even
            # where the rows exist. A marker-only test reports ABSENT for a constraint that IS
            # implemented, which would understate corroboration. Fall back to a source pattern.
            if not present and t.get("pat"):
                present = any(re.search(t["pat"], io.open(os.path.join(ROOT, f),
                                                          encoding="utf-8", errors="replace").read())
                              for f in K_ENCODINGS if os.path.exists(os.path.join(ROOT, f)))
                if present:
                    kcode = "pattern"
                else:
                    kcode = "ABSENT"
            else:
                kcode = "present" if present else "ABSENT"
        else:
            kcode = "n/a"
        # Leg C
        classes = verifier3.PUBLISHED[n][1]
        corpus = "yes" if any(ex.get(c, 0) > 0 for c in classes) else "no"

        legs = sum([glyph.startswith("MATCH"), kcode == "present", corpus == "yes"])
        if glyph.startswith("PARTIAL") and kcode == "ABSENT":
            verdict = "CONTRADICTED"
        elif legs >= 1:
            verdict = "CORROBORATED (%d leg%s)" % (legs, "" if legs == 1 else "s")
        else:
            verdict = "UNCORROBORATED"
        rows.append(dict(constraint=n, note=t["note"], glyphs=glyph, kcode=kcode,
                         corpus=corpus, legs=legs, verdict=verdict,
                         classes=classes, raw=eqs.get(n)))
        print("%-4d %-22s %-11s %-9s %-9s %s" % (n, t["note"][:22], glyph, kcode, corpus, verdict))

    # CHANGE 5 (audit A5): count UNCORROBORATED prominently. 20/30 uncorroborated is a FAILED
    # audit, not a pass.
    unc = [r for r in rows if r["verdict"] == "UNCORROBORATED"]
    con = [r for r in rows if r["verdict"] == "CONTRADICTED"]
    print()
    # DO NOT LUMP 1-LEG WITH 3-LEG. "30/30 corroborated" would hide that some rest on a single
    # leg -- and Leg C alone bounds only OVER-strictness, which is the weak direction.
    for k in (3, 2, 1):
        ns = [r["constraint"] for r in rows if r["legs"] == k]
        print("  corroborated by %d leg%s : %2d/30  %s" % (k, " " if k == 1 else "s", len(ns), ns))
    print("  UNCORROBORATED                      : %d/30  %s"
          % (len(unc), [r["constraint"] for r in unc]))
    print("  CONTRADICTED                        : %d/30  %s"
          % (len(con), [r["constraint"] for r in con]))
    print()
    if con:
        print("  BLOCKING: a CONTRADICTED constraint is a finding about verifier3 and therefore")
        print("  about every ACCEPT it has issued.")
    print("  RESIDUE, NOT CLOSED BY ANY LEG: a constraint present in the ARTICLE but absent from")
    print("  BOTH the glyph extraction AND K's code is invisible here -- both sides are silent.")
    print("  That class is not hypothetical: (26) is in the article and vacuous in their code.")
    print("  Only a human reading the article closes it.")

    io.open(os.path.join(OUT, "report.json"), "w", encoding="utf-8").write(
        json.dumps({"legA_extracted": got, "legA_missing": missing,
                    "legB_encodings": {k: {"rows": v["rows"],
                                           "markers": sorted(v["markers"]),
                                           "singleTransfer": v["singleTransfer"]}
                                       for k, v in kc.items()},
                    "legC_classes_exercised": len(ex),
                    "rows": rows}, ensure_ascii=False, indent=1, default=str))
    io.open(os.path.join(OUT, "legA_glyphs.txt"), "w", encoding="utf-8").write(
        "\n".join("(%d)  %s" % (n, eqs[n]) for n in got))
    print()
    print("  -> %s" % os.path.relpath(OUT, ROOT))
    return 1 if con else 0


if __name__ == "__main__":
    sys.exit(main())
