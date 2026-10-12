"""ONE accessor for "the best verified thing we have for this cell". (d585)

WHY THIS EXISTS. Reader blindness has cost us twice in two days: nine ng-route certificates and
twenty-six verified master-IP solutions, all sitting in the repository while every table reported
something worse. Both times the cause was the same -- each reader carried its own hand-written list
of directories or filename patterns, and a result written somewhere new was invisible to all of
them. Eleven reader sites learned `masterip` by hand this week.

A list repeated in eleven places is a list that will be wrong in at least one. This module owns the
question instead:

    best_solution(cell, size) -> (objVal, stage, path) or None
    best_bound(cell, size)    -> (value, klass, path) or None

The rules live here and nowhere else:

  * a SOLUTION counts when it is banked under runs/postpass/<stage>/ and carries `_verified`;
  * a BOUND counts when `bound_certificate.bound_class` names a class -- which since 2026-09-28
    refuses a ceil-rounded artifact, because TEM-ceil is a restriction and its LP is not a bound;
  * the bound is composed (street + water) wherever the artifact carries the composition;
  * ties go to the earlier stage, so the answer is stable.

G27 in the release gate compares every table's own answer against this one. The readers are not
rewritten while a campaign is running; the gate reports the first divergence instead.

    python analysis/best_known.py [--size 50]
"""
import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from bound_certificate import bound_class

# the ONE list. floor is the unprefixed directory; the rest are stages added over the project's life
STAGES = ("", "ceil", "refine", "alns", "selchain", "masterip", "forced", "diverse")
CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
SIZES = (10, 20, 30, 50, 100)


def _load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def best_solution(cell, size):
    best = None
    for stage in STAGES:
        p = os.path.join(ROOT, "runs", "postpass", stage, "ownwater_%s_n%d.json" % (cell, size))
        d = _load(p)
        if not d or d.get("objVal") is None:
            continue
        if not d.get("_verified"):
            continue
        v = float(d["objVal"])
        if best is None or v < best[0] - 1e-9:
            best = (v, stage or "floor", os.path.relpath(p, ROOT))
    return best


def _bound_patterns(cell, size):
    """Glob patterns only. THESE ARE NOT SAFE ON THEIR OWN -- see bound_artifacts.

    At size 100 the artifacts carry no size suffix, so the wildcard
    `tep_cg_bound_<cell>_*.json` also matches every OTHER size: 13 of C201's 23 matches are
    n10/n20/n30/n50 files, and all 27 cells are affected. best_bound has always paired these
    patterns with a `(d["size"] or 100) != size` check, which is what makes them correct.
    A caller that globs them without that check reports another size's LP as this cell's bound.
    Use bound_artifacts instead; this stays for callers that already do their own filtering.
    """
    if size == 100:
        return ["tep_cg_bound_%s.json" % cell, "tep_cg_bound_%s_*.json" % cell,
                "tep_easy_reduction_%s_n100_k*.json" % cell]
    return ["tep_cg_bound_%s_n%d*.json" % (cell, size)]


def bound_artifacts(cell, size):
    """[(path, artifact)] that genuinely belong to THIS cell at THIS size.

    The pattern list plus the two filters that make it correct, in one place so no caller has to
    remember them: the artifact's own `size` field must match, and INVALID_ files are skipped.
    Added 2026-09-29 after tep_bound globbed the raw patterns and pulled n50 artifacts into
    every n100 cell.
    """
    out = []
    for pat in _bound_patterns(cell, size):
        for p in sorted(glob.glob(os.path.join(ROOT, "runs", "oracle", pat))):
            if "INVALID" in os.path.basename(p):
                continue
            d = _load(p)
            if not d or (d.get("size") or 100) != size:
                continue
            out.append((p, d))
    return out


def best_bound(cell, size):
    best = None
    for pat in _bound_patterns(cell, size):
        for p in glob.glob(os.path.join(ROOT, "runs", "oracle", pat)):
            if "INVALID" in os.path.basename(p):
                continue
            d = _load(p)
            if not d or (d.get("size") or 100) != size:
                continue
            k = bound_class(d)
            if not k:
                continue
            v = d.get("composed")
            if v is None:
                v = d.get("lp_composed")
            if v is None:
                continue
            v = float(v)
            if best is None or v > best[0] + 1e-9:
                best = (v, k, os.path.relpath(p, ROOT))
    return best


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--size", type=int, default=None); a = ap.parse_args()
    sizes = [a.size] if a.size else list(SIZES)
    print("BEST KNOWN per cell, from the single accessor\n")
    print("%-6s %5s %12s %-10s %12s %-11s" % ("cell", "size", "incumbent", "stage", "bound", "class"))
    for n in sizes:
        for c in CELLS:
            s, b = best_solution(c, n), best_bound(c, n)
            if not s and not b:
                continue
            print("%-6s %5d %12s %-10s %12s %-11s"
                  % (c, n, ("%.3f" % s[0]) if s else "-", s[1] if s else "-",
                     ("%.1f" % b[0]) if b else "-", b[1] if b else "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
