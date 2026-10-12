"""HALT GUARD: a verifier/solver contradiction stops everything. Exits nonzero when one stands.

AUTHOR RULE, 2026-09-18, verbatim: *"I want to stop all runs after any quarantine except if
because no incumbent found by main solver ie. if verifier contradict main solver validity claim."*

THE DISTINCTION, and it is already clean in the data:
  * the solver finding NO INCUMBENT (`seed_infeasible`) is honest failure. Measured: 12 such runs
    live in runs/ and ZERO in runs/invalid/ -- they are never quarantined. Nothing here stops for
    them.
  * the verifier CONTRADICTING the solver's validity claim is a correctness failure. Every one of
    the 35 rows in runs/invalid/INDEX.md is exactly that: reason "verifier rejected a solution".

So `quarantine` and `verifier contradiction` are the same set, and the rule reduces to: any
untriaged row in INDEX.md halts new runs.

THIS POLICY ALREADY EXISTED AND WAS NEVER ENFORCED. runs/invalid/INDEX.md's own header reads:
"That is a defect in the solver or the verifier -- more informative than any passing run.
**BLOCKING**: the engine that produced it cannot feed a published claim until the root cause is
found and `triaged` is set." It was written, marked BLOCKING, and then 22 runs were quarantined on
13-14 September with no reaction for two weeks, because nothing read the file (d206). A silent
record only works if something forces it to be read. This is that something.

USE:
    python analysis/quarantine_guard.py            # report; exit 1 if any untriaged row
    python analysis/quarantine_guard.py --since 2026-09-17   # only rows on/after a date

Drivers call it BEFORE each batch and halt on a nonzero exit. release_gate calls it as a gate.
"""
import argparse, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "runs", "invalid", "INDEX.md")

# A data row starts with an ISO timestamp. See rows() for why this replaced a name-based header test.
ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def rows():
    """Parse INDEX.md into dicts. Columns: ts | run_id | engine | reason | obj | bound | status | triaged."""
    if not os.path.exists(INDEX):
        return []
    out, unparsed = [], []
    for ln in open(INDEX, encoding="utf-8"):
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 8:
            continue
        # P9: a data row starts with an ISO timestamp. The previous test named the header cell
        # "ts"/"timestamp"; INDEX.md's header cell actually reads "when", so the header survived and
        # every printed count was inflated by one. Requiring ISO fixes that -- but silently DROPPING
        # a row it cannot parse would turn an over-count into an under-count, and this is a HALT
        # guard, so unparseable rows are collected and reported rather than skipped.
        if set(cells[0]) <= set("-: "):
            continue                                   # separator row
        if not ISO_TS.match(cells[0]):
            if cells[0].lower() not in ("when", "ts", "timestamp"):
                unparsed.append(ln[:90])
            continue
        out.append(dict(ts=cells[0], run_id=cells[1].strip("`"), engine=cells[2],
                        reason=cells[3], obj=cells[4], status=cells[6],
                        triaged=cells[7].replace("*", "").strip()))
    if unparsed:
        print("  !! %d UNPARSEABLE row(s) in INDEX.md -- a halt guard must not skip them:"
              % len(unparsed))
        for u in unparsed:
            print("     %s" % u)
        raise SystemExit(2)
    return out


def is_untriaged(r):
    """THE one triaged test. A row is triaged when its last column names the decision that
    dispositions it (D-441, D-A, 'triaged 2026-09-21'); the writer stamps a fresh row **NO**,
    which rows() has already stripped to NO. Duplicating this test elsewhere is how the two
    copies drift, so callers import it rather than re-deriving it."""
    return (r.get("triaged") or "").strip().upper() in ("NO", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="only rows with ts >= this date")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    rs = rows()
    if a.since:
        rs = [r for r in rs if r["ts"][:10] >= a.since]

    # Honest failure -- the solver found nothing -- never reaches INDEX.md, so nothing to exclude
    # here. Kept explicit so a future change to that behaviour is caught rather than assumed.
    no_incumbent = [r for r in rs if "no incumbent" in r["reason"].lower()
                    or "seed_infeasible" in r["reason"].lower()]
    contradictions = [r for r in rs if r not in no_incumbent]
    untriaged = [r for r in contradictions if is_untriaged(r)]

    if not a.quiet:
        print("QUARANTINE GUARD -- runs/invalid/INDEX.md")
        print("  rows%s                         : %d"
              % ((" since " + a.since) if a.since else "", len(rs)))
        print("  solver found no incumbent (OK to continue) : %d" % len(no_incumbent))
        print("  VERIFIER CONTRADICTED THE SOLVER           : %d" % len(contradictions))
        print("  of those, UNTRIAGED                        : %d" % len(untriaged))
        if untriaged:
            print()
            by_engine = {}
            for r in untriaged:
                by_engine.setdefault(r["engine"], []).append(r)
            for eng, v in sorted(by_engine.items()):
                print("  engine %-10s %3d untriaged -- BLOCKED from feeding a published claim"
                      % (eng, len(v)))
            print()
            for r in untriaged[-6:]:
                print("    %s  %s" % (r["ts"][:19], r["run_id"][:58]))
            if len(untriaged) > 6:
                print("    ... and %d earlier" % (len(untriaged) - 6))
            print()
            print("  HALT. Author rule 2026-09-18: a verifier/solver contradiction stops all runs.")
            print("  A run whose validity claim the verifier contradicts means one of the two is")
            print("  wrong, and every result from that engine is suspect until it is known which.")
            print("  Set `triaged` in INDEX.md once the root cause is found.")
        else:
            print("\n  clear -- no untriaged contradiction. Runs may proceed.")
    return 1 if untriaged else 0


if __name__ == "__main__":
    sys.exit(main())
