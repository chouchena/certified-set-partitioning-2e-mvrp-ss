"""THE ARTIFACT GATE. No result is banked without provenance and a reproducible runtime.

    python analysis/artifact_gate.py              # fail on any post-adoption violation
    python analysis/artifact_gate.py --all        # include the frozen historical debt
    python analysis/artifact_gate.py --freeze     # re-cut the baseline (asks why, in writing)

THE RULE, adopted 2026-09-29 and not negotiable:

    An artifact carries full provenance AND the runtime it actually consumed -- not the cap it
    was allowed -- or it is not written, and if it was written it is deleted.

WHY TWO LAYERS. `analysis/stamp.py` refuses at the moment of writing, which covers the 178
modules that call `stamped()`. It is not a chokepoint: an AST sweep on the day of adoption found
40 modules that `json.dump` something which is not a `stamped()` call. Some of those are indexes
and registers rather than results, and some are results. A rule enforced only where writers
opted in is enforced nowhere. This gate checks the OUTPUT, under `runs/`, and so cannot be
walked around by a writer that never imported the stamp.

THE THREE CHECKS, in the order they catch things.

  P1  UNSTAMPED     no `_provenance`. The producing code cannot be named.
  P2  DIRTY         `_provenance.git_dirty` is true. The git sha does not reconstruct the code
                    state, so `code_hash` is the only anchor and it is not in the paper.
  R1  WALL-ONLY     the artifact reports seconds and carries no deterministic clock. The runtime
                    is this machine on this day; it does not reproduce. An iteration or label
                    count is a progress counter and does not satisfy this.
  R2  INCOHERENT    an event log whose clock DECREASES. Presence is not coherence, and a
                    column that runs backwards cannot anchor a runtime truncation.
  R3  UNCOMPARABLE  the artifact declares `_rt.rt_class = "submission"` -- its wall may be
                    quoted beside K's -- and was not produced at 4 threads in single tenancy
                    (d47). Added 2026-09-30 after 55 artifacts were written at one thread by a
                    driver that had never heard of d47, and their walls entered a comparison.

WHAT PROVOKED IT. An eight-cell, six-hour n50 batch on 2026-09-29 wrote seven artifacts from an
uncommitted tree with no deterministic clock anywhere. They were audited AFTER the fact, found
unreproducible, and deleted -- and they had bought zero LP value, only a `proven` flag, at a cost
of 4.2 hours. `stamp.py` had faithfully recorded `git_dirty: true` on every one of them and
nothing stopped. Recording a defect is not enforcing against it.

THE FROZEN DEBT. 2,891 artifacts predate the rule and almost all of them violate it. They are
counted, frozen by path in `validation/ARTIFACT_DEBT.json`, and excluded from the default run --
the same idiom `analysis/single_authority.py` uses for its 13 known offenders. A frozen path that
is REWRITTEN loses its exemption immediately: the new content must pass. So the debt can only
shrink, and any artifact this project touches from now on comes back clean or does not come back.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBT = os.path.join(ROOT, "validation", "ARTIFACT_DEBT.json")
ADOPTED = "2026-09-29"

sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import RT_KEYS, det_present       # one definition of what a clock is, not two
from rt_class import SUBMISSION_THREADS      # one definition of d47's thread count, not two


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _has(payload, keys):
    """The key present at top level or one level down in a rows/cells list, as stamp.py looks."""
    for k in keys:
        if _num(payload.get(k)):
            return k
    for holder in ("rows", "cells", "results", "runs", "per_cell"):
        seq = payload.get(holder)
        rows = seq if isinstance(seq, list) else (list(seq.values()) if isinstance(seq, dict) else [])
        for row in rows:
            if isinstance(row, dict):
                for k in keys:
                    if _num(row.get(k)):
                        return "%s.%s" % (holder, k)
    return None


def violations(payload):
    """The rule, applied to one loaded artifact. Returns a list of codes."""
    if not isinstance(payload, dict):
        return ["P1"]
    out = []
    prov = payload.get("_provenance")
    if not isinstance(prov, dict):
        out.append("P1")
    elif "sources_dirty" in prov:
        # The precise test: were the files that DETERMINED this value uncommitted? An untracked
        # log in the tree sets `git_dirty` and changes nothing about reproducibility.
        if prov["sources_dirty"]:
            out.append("P2")
    elif prov.get("git_dirty"):
        out.append("P2")          # legacy artifact: only the blunt flag exists, so use it
    if _has(payload, RT_KEYS) and not det_present(payload):
        out.append("R1")
    if trajectory_incoherent(payload):
        out.append("R2")
    if thread_policy_violated(payload):
        out.append("R3")
    return out


def thread_policy_violated(payload):
    """R3: the artifact says its wall is quotable and it was not produced under d47.

    d47 (2026-09-17) requires 4 threads and single tenancy of any run whose output feeds a
    reported runtime. Until 2026-09-30 that rule existed only inside `run_full_grid.py`'s
    argparse default, so a SECOND driver -- `banked_grid.py` -- produced 55 artifacts at one
    thread and none of the four gates noticed, because not one of them read a thread count.

    Only a SUBMISSION-class artifact fails here. A diagnostic one is compliant by saying so: it
    carries the reason its wall cannot be quoted, which is what makes the omission visible
    instead of silent. The check is on the VALUE, not on the key being present -- release_gate
    G6 already required the key, and `threads: 1` satisfied it.
    """
    rt = (payload or {}).get("_rt")
    if not isinstance(rt, dict) or rt.get("rt_class") != "submission":
        return False
    return rt.get("threads") != SUBMISSION_THREADS or (rt.get("tenancy") or 2) > 1


# WHICH COLUMNS ARE CLOCKS, PER HOLDER. A column is only checked where it is CUMULATIVE BY
# CONTRACT. The first version applied one list to every holder and fired on R206 n10 during the
# banked grid: `hist["labels"]` is the PER-ITERATION label count -- that is the solver's
# original format, not a defect -- and it legitimately falls when an iteration is cheaper than
# the last. `events["labels"]` IS cumulative, and that is the column R2 exists to protect.
# Checking a per-iteration counter as though it were a clock halts a correct run.
MONOTONE_BY_HOLDER = {
    "events": ("t", "work", "labels", "cum_labels", "cum_work"),
    "trajectory": ("t", "work", "labels", "cum_labels", "cum_work"),
    "spool": ("t", "work", "labels"),
    # hist is the solver's own per-iteration record: `secs` is elapsed and must rise; `labels`,
    # `cand`, `added` are per-iteration quantities and must NOT be treated as clocks.
    "hist": ("secs",),
}


def trajectory_incoherent(payload):
    """R2: an event log whose clocks run BACKWARDS is not a clock.

    WHY THIS EXISTS. On 2026-09-29 commit 9573cb4 shipped an event log whose `labels` column was
    the PER-ITERATION count, not a running total, so it fell whenever an iteration was cheaper
    than the last. The commit message and the module's own docstring both said "cumulative
    pricer labels". The code said otherwise and nothing noticed for 38 cells and four and a half
    hours of compute.

    The gate already required a deterministic clock to be PRESENT. Presence is not coherence: a
    column that decreases cannot anchor a runtime truncation, which is the only reason the
    trajectory is recorded at all. R1 asks whether there is a clock; R2 asks whether it is one.

    Only monotone-by-construction fields are checked, and only inside a list of event dicts. An
    LB column is deliberately NOT required to be monotone here -- it is checked in lb_solver's
    own invariants, where a decrease means something different.
    """
    if not isinstance(payload, dict):
        return False
    for holder, cols in MONOTONE_BY_HOLDER.items():
        seq = payload.get(holder)
        if not isinstance(seq, list) or len(seq) < 2:
            continue
        if not all(isinstance(e, dict) for e in seq):
            continue
        for k in cols:
            vals = [e.get(k) for e in seq]
            vals = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if len(vals) < 2 or len(vals) != len(seq):
                continue
            if any(vals[i] < vals[i - 1] - 1e-9 for i in range(1, len(vals))):
                return True
    return False


def scan(root="runs"):
    """Every .json under `root`, with its violations and a content hash."""
    base = os.path.join(ROOT, root)
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
        for f in sorted(fn):
            if not f.endswith(".json"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            try:
                raw = io.open(p, "rb").read()
                d = json.loads(raw.decode("utf-8"))
            except Exception as e:
                yield rel, ["P1"], None, "unreadable: %s" % type(e).__name__
                continue
            yield rel, violations(d), hashlib.sha256(raw).hexdigest()[:16], None


def load_debt():
    try:
        return json.load(io.open(DEBT, encoding="utf-8"))
    except Exception:
        return {"adopted": ADOPTED, "frozen": {}}


def freeze(reason):
    """Cut the baseline: every violating artifact that exists NOW, by path and content hash."""
    frozen = {}
    for rel, v, h, err in scan():
        if v:
            frozen[rel] = {"sha": h, "codes": v}
    out = {"adopted": ADOPTED, "frozen_on": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "reason": reason, "count": len(frozen), "frozen": frozen,
           "note": "A frozen path loses its exemption the moment its CONTENT changes: the sha is "
                   "part of the key. The debt can shrink and cannot grow."}
    with io.open(DEBT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    return out


NAMES = {"P1": "no provenance", "P2": "written from an uncommitted tree",
         "R1": "reports seconds with no deterministic clock",
         "R2": "an event-log clock runs BACKWARDS, so it cannot anchor a truncation",
         "R3": "declares its wall quotable but was not run at %d threads in single tenancy (d47)"
               % SUBMISSION_THREADS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="include the frozen historical debt")
    ap.add_argument("--freeze", metavar="REASON", help="re-cut the baseline; say why")
    a = ap.parse_args()

    if a.freeze:
        out = freeze(a.freeze)
        print("froze %d violating artifact(s) into %s" % (out["count"], os.path.relpath(DEBT, ROOT)))
        return 0

    debt = load_debt()
    frozen = debt.get("frozen") or {}
    live, thawed, exempt = [], [], 0
    for rel, v, h, err in scan():
        if not v:
            continue
        f = frozen.get(rel)
        if f is None:
            live.append((rel, v, "new"))
        elif f.get("sha") != h:
            thawed.append((rel, v, "REWRITTEN since the freeze -- exemption void"))
        else:
            exempt += 1

    bad = live + thawed
    print("ARTIFACT GATE -- provenance and reproducible runtime, adopted %s" % ADOPTED)
    print("  frozen historical debt      %5d  (exempt while unchanged)" % exempt)
    print("  NEW violations              %5d" % len(live))
    print("  REWRITTEN, exemption void   %5d" % len(thawed))
    if a.all:
        for rel, f in sorted(frozen.items()):
            print("    [debt] %-8s %s" % (",".join(f["codes"]), rel))
    for rel, v, why in sorted(bad):
        print("  *** %-10s %-58s %s" % (",".join(v), rel, why))
        for c in v:
            print("        %s: %s" % (c, NAMES[c]))
    if bad:
        print("\n  REFUSED. %d artifact(s) violate the rule adopted %s. Delete them, fix the "
              "writer, commit the code, and re-run. There is no override." % (len(bad), ADOPTED))
        return 3
    print("\n  clean: every artifact written since %s carries provenance and a reproducible "
          "runtime." % ADOPTED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
