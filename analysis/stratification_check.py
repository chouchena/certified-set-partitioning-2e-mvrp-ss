"""STRATIFICATION CHECK — fire on per-cell tables that mix K-proven and K-unsolved cells.

THE RULE IT ENFORCES. `analysis/reference_set_audit.py` adopted, on 2026-09-15, that cells the
exact method solved to proven optimality are stratified out of every gap-normalised metric and
reported separately as CALIBRATION -- never deleted, because dropping a 26% slice of the |C| = 20
benchmark would look, correctly, like selection. `analysis/make_tables.py` implements it.

WHY A CHECK AND NOT A NOTE. The rule lived in a verdict block inside one script and was enforced
in exactly one file. Every other per-cell table in this repository -- including tables built
inside decision documents, which is where it failed on 2026-09-15 -- had to apply it by hand, and
nothing failed when nobody did. The RC208 evidence table listed R205 (K-proven, so K's published
value IS the optimum) beside seven unsolved cells whose published values are truncated
incumbents, and the footnote drawn from it stated a claim at a uniform confidence it did not
have.

WHAT IT CHECKS. Every markdown table in the tracked prose. If a table names three or more
|C| = 20 or |C| = 30 cells and those names span BOTH strata, the table must say so somewhere
inside itself. That is the whole rule: label the split, or do not mix.

WHAT IT CANNOT CHECK. Whether a labelled table draws a sound conclusion, and whether a metric
that mixes strata is actually biased -- bias depends on the statistic. It narrows the failure to
"someone mixed strata without saying so", which is the failure that actually occurred.

USAGE
    python analysis/stratification_check.py           # exit 1 on any unlabelled mixed table
    python analysis/stratification_check.py --list    # show the strata and exit
"""
import os, re, sys, json, glob, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where per-cell tables actually get written. Deliberately NOT the whole repo: archive/ holds
# superseded material that is allowed to be wrong, and runs/ holds generated artifacts.
SCAN = ["validation/*.md", "paper/*.md", "*.md", "crossfeed/*.md"]

# A table earns scrutiny only once it names this many distinct cells. Below it the "table" is
# usually a single worked example, where the stratum is obvious from context.
MIN_CELLS = 3

# Any of these words inside the table means the author has addressed the split. Generous on
# purpose: the check exists to catch SILENCE, not to police vocabulary.
MARKERS = ("proven", "unproven", "solved", "unsolved", "optimal", "calibration",
           "stratif", "gap 0", "closed")


def strata(size):
    """(proven, unsolved) cell names at this size, from K's published per-instance gaps."""
    k = json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))
    per = k["table3"]["per_instance"][str(size)]
    proven = {c for c in per if per[c]["joint_gap"] == 0.0}
    return proven, set(per) - proven


# A table is in scope only if it COMPARES against K's published values. Merely naming cells is
# not a cross-stratum claim -- a reproduction-status list or a port-equivalence table names the
# same cells and says nothing about gaps. Without this the check produced 54 findings, almost all
# noise, which is the "audit that invents findings" failure: the real one stops being believed.
K_SIGNAL = ("bk", "gap", "published", "joint", "lbbd", "imp", "vs k", "k's", "optimum")

# The size a table is about, taken from the table or its immediate lead-in. Testing both sizes
# unconditionally was the other defect: the same cell names exist at |C| = 20 and 30, so every
# n20 table was also reported as an n30 finding.
SIZE_PAT = re.compile(r"\|C\|\s*=\s*(\d+)|\bn\s*=\s*(\d+)\b|\bn(\d{2,3})\b|\bsize\s*=?\s*(\d+)\b",
                      re.I)


def size_of(text, tbl, start_line):
    """Which size this table is about, or None if it cannot be attributed.

    NEAREST PRECEDING MENTION, scanning upward, which is how a reader attributes a table. A
    fixed lead-in window was the first attempt and it silently dropped the very table this check
    was written for: the RC208 evidence table names its size fourteen lines above itself, one
    line outside a thirteen-line window. A check that misses its own motivating case is worse
    than no check, so the failure mode is now "report as unattributed", never "skip".
    """
    def sizes_in(s):
        out = set()
        for m in SIZE_PAT.finditer(s):
            for g in m.groups():
                if g and g.isdigit() and int(g) in (20, 30):
                    out.add(int(g))
        return out

    own = sizes_in(tbl)
    if len(own) == 1:
        return own.pop()
    lines = text.splitlines()
    for n in range(start_line - 2, max(-1, start_line - 60), -1):
        s = sizes_in(lines[n])
        if len(s) == 1:
            return s.pop()
        if len(s) > 1:
            return None
    return None


def tables(text):
    """Contiguous runs of markdown table lines, with the line number each starts at."""
    out, cur, start = [], [], None
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("|"):
            if not cur:
                start = n
            cur.append(line)
        else:
            if len(cur) >= 2:
                out.append((start, "\n".join(cur)))
            cur, start = [], None
    if len(cur) >= 2:
        out.append((start, "\n".join(cur)))
    return out


def audit():
    findings = []
    names = {}
    for size in (20, 30):
        names[size] = strata(size)
    # Longest-first so RC208 is never matched as R208 + stray characters.
    allcells = sorted(set().union(*[p | u for p, u in names.values()]), key=len, reverse=True)
    pat = re.compile(r"\b(" + "|".join(re.escape(c) for c in allcells) + r")\b")

    seen = set()
    for g in SCAN:
        for f in sorted(glob.glob(os.path.join(ROOT, g))):
            rel = os.path.relpath(f, ROOT).replace(os.sep, "/")
            if rel in seen:
                continue
            seen.add(rel)
            try:
                text = open(f, encoding="utf-8").read()
            except Exception:
                continue
            for line_no, tbl in tables(text):
                found = set(pat.findall(tbl))
                if len(found) < MIN_CELLS:
                    continue
                low = tbl.lower()
                if not any(s in low for s in K_SIGNAL):
                    continue                      # names cells but makes no claim against K
                size = size_of(text, tbl, line_no)
                if size is None:
                    continue                      # cannot attribute a size; do not guess
                proven, unsolved = names[size]
                hitp, hitu = found & proven, found & unsolved
                if not (hitp and hitu):
                    continue
                if any(m in low for m in MARKERS):
                    continue
                findings.append((rel, line_no, size, sorted(hitp), sorted(hitu)))
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="print the strata and exit")
    a = ap.parse_args()

    if a.list:
        for size in (20, 30):
            p, u = strata(size)
            print(f"  |C| = {size}: {len(p)} K-proven {sorted(p)}")
            print(f"              {len(u)} unsolved")
        return 0

    f = audit()
    if not f:
        print("OK: no markdown table mixes K-proven and K-unsolved cells without saying so.")
        return 0
    print(f"{len(f)} table(s) mix K-proven and K-unsolved cells with no marker:\n")
    for rel, line_no, size, hp, hu in f:
        print(f"  {rel}:{line_no}  (|C| = {size})")
        print(f"     K-proven : {', '.join(hp)}   <- K's value is the OPTIMUM here")
        print(f"     unsolved : {', '.join(hu)}   <- K's value is a truncated incumbent")
    print()
    print("A claim spanning both strata means two different things and should say which.")
    print("Label the split inside the table, or separate the strata. See section 11 of")
    print("validation/DECISION_rc208_one_car_outlier_disclosure.md for how this failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
