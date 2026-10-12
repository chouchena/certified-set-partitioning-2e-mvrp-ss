"""G23 -- extend the code-stamp requirement from ONE file pattern to every result.

THE RULE ALREADY EXISTED. CLAUDE.md line 54: "`code_hash` is the reproducibility anchor, NOT
`git_sha`". Release-gate G6 enforces full provenance -- and its glob is
`crossfeed/easy_reduction_descend_*_n20.json` and nothing else. Every result written under
runs/oracle since then has walked around it, not because the rule was absent but because the
enforcement was never widened.

WHAT THAT COST, on 2026-09-20. Two defects were found in the arbiter (an incomplete enumeration,
then missing Table 1 garage rows). The code was fixed and the blast radius was swept THROUGH
OTHER CODE -- never through RESULTS. The memory rule says "sweep for the same defect elsewhere
AND FOR WHAT IT INVALIDATES"; only the first half was done. Pre-fix results stayed in the tree
looking authoritative, and post-fix reruns silently OVERWROTE them, because the filenames carried
no configuration:

    FR1_arbiter_vs_milp.json   the |P|=2 run destroyed the |P|=1 run -- the big-M finding's basis
    arbiter_controls.json      the |P|=2 run destroyed the |P|=1 3200-point run
    v4smoke.json               the PASS destroyed the 19/19 FAIL reported to the author as "kept"

Nothing detected it: 22 of 24 result files record nothing about the code that made them, and
`runs/*` is gitignored so an overwrite leaves no diff to notice.

WHAT THIS CHECKS. Every result under runs/oracle must carry a stamp naming its producing code --
`sources` (file -> sha256 prefix, as oracle_L2 writes) or a `code_hash`. The stamp is then
recomputed against the code as it stands:

    CURRENT    the stamp matches the code now
    STALE      the producing code has CHANGED -- the result may predate a fix, and needs a rerun
               or an explicit note saying why the change cannot affect it
    UNSTAMPED  attributable to no code version at all; it cannot be defended, and no later fix
               can be known to have invalidated it

WHAT IT CANNOT DO. It cannot stamp anything retroactively. A file with no stamp stays
unattributable. It stops the NEXT one being unattributable and makes the existing backlog
visible rather than invisible.

    python analysis/gate_results_current.py
"""
import glob
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "runs", "oracle")


def sha(path):
    if not os.path.exists(path):
        return None
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()[:16]


def resolve(name):
    for c in (os.path.join(ROOT, name), os.path.join(ROOT, name + ".py"),
              os.path.join(ROOT, "analysis", name + ".py")):
        if os.path.exists(c):
            return c
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = sorted(glob.glob(os.path.join(RESULTS, "*.json")))
    print("G23 -- can each result be attributed to the code that produced it?")
    print("       (extends G6, whose glob covers only crossfeed/easy_reduction_descend_*_n20)")
    print()
    unstamped, stale, current = [], [], []
    for f in files:
        base = os.path.basename(f)
        try:
            d = json.load(io.open(f, encoding="utf-8"))
        except Exception as e:
            unstamped.append((base, "unreadable (%s)" % type(e).__name__))
            continue
        if not isinstance(d, dict):
            unstamped.append((base, "top level is not an object"))
            continue
        src = d.get("sources")
        if isinstance(src, dict) and src:
            drift = []
            for name, was in src.items():
                path = resolve(name)
                now = sha(path) if path else None
                if now is None:
                    drift.append("%s not found" % name)
                elif now != was:
                    drift.append("%s CHANGED" % name)
            (stale if drift else current).append((base, "; ".join(drift) or "stamp matches"))
        elif d.get("code_hash") or d.get("_code_hash"):
            current.append((base, "carries code_hash"))
        else:
            unstamped.append((base, "no sources, no code_hash"))

    for label, rows in (("CURRENT", current), ("STALE", stale), ("UNSTAMPED", unstamped)):
        if not rows:
            continue
        print("  %s (%d)" % (label, len(rows)))
        for b, why in rows:
            print("     %-40s %s" % (b, why))
        print()
    print("  totals: %d current | %d STALE | %d UNSTAMPED | %d files"
          % (len(current), len(stale), len(unstamped), len(files)))
    print()
    if stale:
        print("  STALE: produced by code that has since changed. Rerun, or write down why the")
        print("  change cannot affect the result.")
    # FIGURES too. Five were generated on 2026-09-16 by the pre-d243 solver and would
    # otherwise sit in paper/figures looking current. A marker nobody checks is no marker.
    import sys as _s
    _s.path.insert(0, os.path.join(ROOT, "analysis"))
    from repro_preflight import code_hash as _cur
    cur = _cur()
    figs_stale, figs_ok = [], []
    for f in sorted(glob.glob(os.path.join(ROOT, "paper", "figures", "*.prov.json"))):
        d = json.load(io.open(f, encoding="utf-8"))
        name = d.get("figure", os.path.basename(f))
        if d.get("code_hash") and d["code_hash"] != cur:
            figs_stale.append((name, "SUPERSEDED, marked" if d.get("superseded")
                               else "STALE AND UNMARKED"))
        else:
            figs_ok.append((name, "current"))
    print("  FIGURES")
    for nm, why in figs_ok + figs_stale:
        print("     %-40s %s" % (nm, why))
    unmarked = [n for n, w in figs_stale if "UNMARKED" in w]
    print()
    print("  figures: %d current | %d from superseded code (%d unmarked)"
          % (len(figs_ok), len(figs_stale), len(unmarked)))
    if figs_stale:
        print("  Figures from superseded code must be REGENERATED before publication -- the")
        print("  numbers behind them come from a model that did not enforce (26).")
    # UNSTAMPED IS A BUG, not a note. It was a note while 25 pre-stamping artifacts sat in the
    # backlog; the backlog was quarantined on 2026-09-20 and every writer wired, so there is
    # nothing left for a tolerance to cover. Author, 2026-09-20: "All unstamped records are full
    # bugs - no exceptions and no more crap."
    if unstamped:
        print()
        print("  EVERY UNSTAMPED RECORD IS A BUG. There is no tolerated case and no flag to")
        print("  wave one through -- a tolerated case is how 25 of them accumulated. Each one")
        print("  has a cause: a process that predates the fix, a writer nobody wired, or a")
        print("  writer added since. Find which, fix it, delete the file, re-run it.")
    return 1 if (stale or unmarked or unstamped) else 0


if __name__ == "__main__":
    sys.exit(main())
