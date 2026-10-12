"""Verbatim-overlap check against the predecessor paper. A LOCAL PROXY, not iThenticate.

WHAT THIS IS AND IS NOT, because the distinction decides how much it is worth trusting.

  IT IS     a shingling check: it normalises our manuscript prose and their full text to bare
            word sequences and finds every run of >= N consecutive words occurring in both.
            That is the same primitive commercial detectors are built on, so a passage this
            flags would very likely be flagged there too.

  IT IS NOT iThenticate. That service compares against tens of millions of documents: the
            published literature, the web, and other submissions. This compares against the
            THREE CORPORA WE HOLD LOCALLY:
              * the predecessors' paper, full text               (~18,500 words)
              * comments and docstrings in their released code    (~1,800 words)
              * THE AUTHORS' OWN SRPS MANUSCRIPT, under review    (~7,700 words)
            A passage taken from a third paper sails straight through.
            **A pass is not a clearance.**

WHY THESE THREE. This is a continuation paper: it restates the predecessors' problem, model
and notation, and their authors may referee it, so their paper is the highest-probability
source of an embarrassing match. Their CODE COMMENTS are the second and are easy to overlook
-- describing someone's model means reading their source closely, and the sentences nearest to
hand while doing so are the ones they wrote beside it. The third is SELF-plagiarism, which
journals treat as seriously as the other kind and which no amount of checking against the
predecessors can detect; the authors have a manuscript under review that shares this project's
certification machinery, and the methods sections of consecutive papers by the same authors
are exactly where reuse happens.

THE SRPS TEXT IS UNPUBLISHED AND CONFIDENTIAL. It is gitignored, denied by
analysis/export_release.py, and checked by release_gate G1d, so it cannot reach a release
tree. It is held for this check alone.

WHY SOME OVERLAP IS CORRECT, and why the check must not simply minimise. The problem's name is
theirs. The instance names are theirs. Standard phrases of the field are nobody's. A check that
punished those would push the text toward paraphrase-for-its-own-sake, which reads worse and
serves no one -- and a manuscript that renames the problem to avoid a match is a worse paper.
So UNAVOIDABLE is a first-class category here, whitelisted explicitly, and everything else is
reported for a human to judge.

THE FILE IT READS IS PUBLISHER COPYRIGHT and is excluded from the release (release_gate G1b).
In a release tree it is absent, and this script says so and exits 0 rather than failing: a
replicator cannot run this and should not be told their checkout is broken.
"""
import os, re, sys, json, argparse, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCE = os.path.join(ROOT, "paper", "karademir2025-fulltext-layout.txt")
MANUSCRIPT = os.path.join(ROOT, "paper", "manuscript")
# The authors' own SRPS manuscript, under review elsewhere. Gitignored, export-denied, G1d.
OWN_PRIOR = os.path.join(ROOT, "paper", "srps-submitted-fulltext.txt")

# Runs at or above this length are reported. 8 words is the usual shingle size in detectors.
DEFAULT_N = 8
# A run this long is very unlikely to be coincidence in technical prose.
BLOCK_AT = 12

# Phrases whose overlap is CORRECT. Each needs a reason; "it's common" is not one.
UNAVOIDABLE = [
    "two echelon multi trip vehicle routing problem with synchronization",  # their problem name
    "two echelon multi trip vehicle routing problem",
    "vehicle routing problem with time windows",                            # field-standard
    "integrated water and land based transportation system",                # their title
    "city distribution centre", "city distribution center",
    "logic based benders decomposition",                                    # named method
    "lower bound", "upper bound", "time window", "time windows",
]


def normalise(text):
    """Bare lowercase word sequence: the form a detector actually compares."""
    text = re.sub(r"%.*?$", " ", text, flags=re.M)              # LaTeX comments
    text = re.sub(r"\$[^$]*\$", " ", text)                      # inline maths
    text = re.sub(r"\\begin\{equation\}.*?\\end\{equation\}", " ", text, flags=re.S)
    text = re.sub(r"\\begin\{algorithmic\}.*?\\end\{algorithmic\}", " ", text, flags=re.S)
    text = re.sub(r"\\[a-zA-Z]+\s*(\[[^\]]*\])?", " ", text)    # LaTeX commands
    text = re.sub(r"[^a-zA-Z\s]", " ", text)                    # digits and punctuation
    return re.sub(r"\s+", " ", text).lower().strip()


def words(text):
    return normalise(text).split()


def shingles(ws, n):
    return {" ".join(ws[i:i + n]): i for i in range(len(ws) - n + 1)}


# BOILERPLATE DECLARATIONS. A SEPARATE category from UNAVOIDABLE, deliberately.
#
# The first run against the authors' own prior paper flagged two runs, 48 and 26 words: the
# funding statement and the competing-interests declaration. Both are correct as they stand.
# The funding sentence names the same funder and the same grant-free relationship -- rewording
# it would make it LESS accurate, not more original. The competing-interests sentence is
# publisher boilerplate that appears near-identically in thousands of papers, and similarity
# services exclude exactly this class of match.
#
# Kept apart from UNAVOIDABLE (which is about the PROBLEM'S NAME) for two reasons. It is a
# different justification, and a reader of the report should see which one applies. And the
# patterns are narrow -- anchored on the declaration's own opening words -- so that a genuine
# overlap elsewhere in the same section cannot hide behind a blanket "declarations" exemption.
BOILERPLATE = [
    "the authors declare that they have no known competing financial interests",
    "this work was supported by the sapir applied science institute",
    "the funder had no role in the study design",
    "not applicable this study involves no human participants",
]


def is_unavoidable(phrase):
    return any(u in phrase for u in UNAVOIDABLE)


def is_boilerplate(phrase):
    return any(b in phrase for b in BOILERPLATE)


def extend(a_words, b_words, i, j, n):
    """Grow a matched run in both directions to its true length."""
    start_i, start_j, end = i, j, i + n
    while start_i > 0 and start_j > 0 and a_words[start_i - 1] == b_words[start_j - 1]:
        start_i -= 1; start_j -= 1
    while end < len(a_words) and (end - start_i + start_j) < len(b_words) \
            and a_words[end] == b_words[end - start_i + start_j]:
        end += 1
    return start_i, end


def their_code_prose():
    """Comments and docstrings from THEIR source files -- a second, real leak path.

    Not hypothetical: describing someone's model means reading their code closely, and the
    sentences nearest to hand while doing that are the ones they wrote beside it. 1805 words
    of prose sit in the manifest files, and none of it is in their paper -- so the paper-only
    check could not see any of it.

    Present only in a development tree; the release fetches these files rather than shipping
    them, so this source is simply absent there.
    """
    mf = os.path.join(ROOT, "third_party_manifest.json")
    if not os.path.exists(mf):
        return ""
    out = []
    for f in json.load(open(mf))["files"]:
        p = os.path.join(ROOT, f)
        if not (f.endswith(".py") and os.path.exists(p)):
            continue
        src = open(p, encoding="utf-8", errors="replace").read()
        out.extend(re.findall(r"#(.*)$", src, re.M))
        out.extend(re.findall(r'"""(.*?)"""', src, re.S))
    return "\n".join(out)


def sources():
    """Every corpus we can compare against, named so a reader knows what is NOT here."""
    out = []
    if os.path.exists(REFERENCE):
        out.append(("their paper", open(REFERENCE, encoding="utf-8",
                                        errors="replace").read()))
    code = their_code_prose()
    if len(code.split()) > 50:
        out.append(("their code comments", code))
    # THE AUTHORS' OWN PRIOR WORK -- self-plagiarism, which journals treat as seriously as
    # the other kind, and which no amount of checking against the predecessors can catch.
    # Supplied 2026-09-15. Unpublished and under review: gitignored, export-denied, G1d.
    if os.path.exists(OWN_PRIOR):
        out.append(("our own SRPS paper", open(OWN_PRIOR, encoding="utf-8",
                                               errors="replace").read()))
    return out


def our_prose():
    """Every .tex we wrote, concatenated. Comments are stripped by normalise()."""
    out, files = [], []
    for root, _dirs, fs in os.walk(MANUSCRIPT):
        if "submission" in root:
            continue                        # generated; identical content, would double-count
        for f in sorted(fs):
            if f.endswith(".tex") and not f.startswith("sn-"):
                p = os.path.join(root, f)
                out.append(open(p, encoding="utf-8", errors="replace").read())
                files.append(os.path.relpath(p, ROOT))
    return "\n".join(out), files


def selftest(n, block_at):
    """Prove the detector fires. A check that has never failed is not evidence of anything.

    Lifts a window straight out of the reference text AT RUNTIME -- nothing of theirs is
    stored in this file -- and asserts it is caught. If this ever passes silently, the
    matcher is broken and every clean report it has produced is worthless.
    """
    if not os.path.exists(REFERENCE):
        print("  selftest skipped: reference text absent"); return 0
    theirs = words(open(REFERENCE, encoding="utf-8", errors="replace").read())
    # A window from the middle, long enough to exceed the blocking threshold.
    lifted = theirs[len(theirs) // 2: len(theirs) // 2 + block_at + 6]
    while lifted and is_unavoidable(" ".join(lifted)):
        lifted = theirs[len(theirs) // 3: len(theirs) // 3 + block_at + 6]
    theirs_sh, ours_sh = shingles(theirs, n), shingles(lifted, n)
    worst = 0
    for sh, i in ours_sh.items():
        j = theirs_sh.get(sh)
        if j is None:
            continue
        s, e = extend(lifted, theirs, i, j, n)
        worst = max(worst, e - s)
    ok = worst >= block_at
    print(f"  SELFTEST: lifted a {len(lifted)}-word passage from the reference; "
          f"detector found a {worst}-word run")
    print(f"  SELFTEST: {'PASS -- the detector fires' if ok else 'FAIL -- THE DETECTOR IS BROKEN'}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="prove the detector catches a passage lifted from the reference")
    ap.add_argument("-n", type=int, default=DEFAULT_N, help="shingle length")
    ap.add_argument("--block-at", type=int, default=BLOCK_AT,
                    help="run length at or above which the check FAILS")
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args()

    if a.selftest:
        return selftest(a.n, a.block_at)

    corpora = sources()
    if not corpora:
        print("  no reference corpus in this tree (their paper is publisher copyright and")
        print("  their code is fetched, not shipped). Nothing to compare; not a failure.")
        return 0

    ours_raw, files = our_prose()
    ours = words(ours_raw)
    print(f"SIMILARITY CHECK  (local proxy -- NOT iThenticate)")
    print(f"  our prose : {len(ours):6d} words over {len(files)} file(s)")
    print(f"  compared against {len(corpora)} local corpus/corpora, AND NOTHING ELSE:")
    for name, txt in corpora:
        print(f"      {name:22s} {len(words(txt)):6d} words")
    print(f"  NOT compared against: the literature, the web, the works in our own"
          f" bibliography,")
    print(f"      or the authors' earlier papers. A pass here is not a clearance.")
    if len(ours) < a.n:
        print("\n  too little prose written to compare. Re-run as the manuscript grows.")
        return 0

    hits, seen = [], set()
    for name, txt in corpora:
        theirs = words(txt)
        theirs_sh, ours_sh = shingles(theirs, a.n), shingles(ours, a.n)
        for sh, i in ours_sh.items():
            j = theirs_sh.get(sh)
            if j is None:
                continue
            s, e = extend(ours, theirs, i, j, a.n)
            if (s, name) in seen:
                continue
            seen.add((s, name))
            hits.append((e - s, " ".join(ours[s:e]) + f"   [{name}]"))
    hits.sort(reverse=True)

    flagged = [(L, p) for L, p in hits
               if not is_unavoidable(p) and not is_boilerplate(p)]
    excused = [(L, p) for L, p in hits if is_unavoidable(p)]
    boiler = [(L, p) for L, p in hits if is_boilerplate(p) and not is_unavoidable(p)]
    matched_words = sum(L for L, _ in flagged)
    pct = 100.0 * matched_words / max(1, len(ours))

    print(f"\n  shared runs of >= {a.n} words : {len(hits)}"
          f"   ({len(excused)} excused as unavoidable)")
    print(f"  flagged overlap              : {matched_words} words = {pct:.2f}% of our prose")
    if excused:
        print(f"\n  EXCUSED (overlap here is correct -- the problem's name is theirs):")
        for L, p in excused[:4]:
            print(f"    [{L:2d}] {p[:88]}")
    if boiler:
        print(f"\n  BOILERPLATE DECLARATIONS ({len(boiler)}) -- identical BY DESIGN. Rewording a")
        print(f"  funding statement or a competing-interests sentence makes it less accurate,")
        print(f"  not more original, and similarity services exclude this class of match:")
        for L, p in boiler[:4]:
            print(f"    [{L:2d}] {p[:88]}")
    if flagged:
        print(f"\n  FLAGGED, longest first:")
        for L, p in flagged[:a.show]:
            mark = "  <-- FAILS" if L >= a.block_at else ""
            print(f"    [{L:2d}] {p[:88]}{mark}")

    worst = max([L for L, _ in flagged], default=0)
    if worst >= a.block_at:
        print(f"\n  FAIL: a {worst}-word verbatim run is not coincidence in technical prose.")
        print(f"  Rewrite it in our own words, or quote it explicitly with a citation.")
        return 1
    print(f"\n  PASS: longest flagged run is {worst} words (threshold {a.block_at}).")
    print(f"  REMEMBER: {len(corpora)} local corpus/corpora only, so this is not a clearance.")
    names = ", ".join(n for n, _ in corpora)
    print(f"  Corpora: {names}.")
    print("  The literature, the web, and the works in our own bibliography remain")
    print("  unchecked here and are caught only at submission.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
