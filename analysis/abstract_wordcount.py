"""Resolve the abstract's macros and count its words the way the publisher will (d556).

AOR allows 150-250 words (paper/VENUE_AOR_REQUIREMENTS.md line 52, publisher-verified). The draft in
paper/ABSTRACT_AND_STORY.md is written in macros, so its length cannot be read off the page: a macro
stands for a number the referee will see. This script reads the block-quoted draft out of that file,
substitutes the values from paper/numbers.tex, prints the resolved paragraph and counts it.

It is also the check that the abstract contains no typed number and no dangling macro: every
\\num{...} must resolve, and a bare numeral inside the quoted draft is reported. Run it whenever the
abstract or the numbers change.

    python analysis/abstract_wordcount.py            # the committed draft
    python analysis/abstract_wordcount.py FILE       # any file with the draft as a "> " block

Exit 1 if a macro does not resolve or the count leaves the band.
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LO, HI = 150, 250
DEFAULT = os.path.join(ROOT, "paper", "ABSTRACT_AND_STORY.md")
# the draft is the first block quote that starts with the predecessors' names
OPEN = "> Karademir, Beirigo and Atasoy"


def values():
    out = {}
    for line in io.open(os.path.join(ROOT, "paper", "numbers.tex"), encoding="utf-8"):
        m = re.match(r"\\expandafter\\def\\csname snum@([^\\]+)\\endcsname\{(.*)\}\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def draft(path):
    s = io.open(path, encoding="utf-8").read()
    i = s.index(OPEN)
    lines = []
    for line in s[i:].splitlines():
        if not line.startswith("> "):
            break
        lines.append(line[2:])
    return " ".join(lines)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    vals, txt, missing = values(), draft(path), []

    def sub(m):
        k = m.group(1)
        if re.fullmatch(r"[0-9.]+", k):      # a literal like \num{2.5}: a constant of the design, not a result
            return k
        if k not in vals:
            missing.append(k)
            return "??"
        return vals[k]

    res = re.sub(r"\\num\{([^}]*)\}", sub, txt)
    n = len(res.split())
    # a citation year -- (2025) -- is not a result and needs no macro; every other numeral does
    words = re.sub(r"\\num\{[^}]*\}", " ", txt).split()
    typed = [w for w in words if re.fullmatch(r"\(?[0-9][0-9.,]*%?\)?", w) and not re.fullmatch(r"\((19|20)[0-9]{2}\)", w)]
    print(res)
    print()
    print("WORDS: %d   (AOR band %d-%d)" % (n, LO, HI))
    print("unresolved macros: %s" % (sorted(set(missing)) or "none"))
    print("numbers typed rather than macro-resolved: %s" % (typed or "none"))
    for s_ in [x.strip() for x in re.split(r"(?<=[.?]) +", res) if x.strip()]:
        print("   %3d  %s" % (len(s_.split()), s_))
    bad = bool(missing) or bool(typed) or not (LO <= n <= HI)
    print("VERDICT: %s" % ("FAIL" if bad else "ok -- resolves, no typed number, inside the band"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
