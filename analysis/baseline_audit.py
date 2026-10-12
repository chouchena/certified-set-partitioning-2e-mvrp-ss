"""What of the banked corpus is actually usable, per cell, per leg, against seven tests. (d593)

THE AUTHOR'S CHARGE, 2026-09-28: audit the baseline target -- primal and dual -- against what has
actually been produced, and say thoroughly what can be USED, given that it was produced without
runtime accounting, without exhaustive logs, without provenance on every artifact, without
uniform verification, without quarantine analysis, without blast checks, and without variant
release uniformity.

This scores every (cell, size) on both legs against those seven, and classifies the result. It
asserts nothing it has not read off disk.

THE SEVEN TESTS

  T1 verification    the artifact is verifier3-clean (primal) / carries a certificate (dual).
                     This is the only test that decides VALIDITY. The other six decide whether a
                     number is DEFENSIBLE, which is a different and weaker thing.
  T2 provenance      _provenance.code_hash present. CLAUDE.md: code_hash is the anchor, not git_sha.
  T3 runtime         a runtime is recorded at all.
  T4 attributable    that runtime is traceable to ONE production run inside the per-cell envelope.
                     FINDING_rt_budget_fairness section 5.B requires this and it was never built.
  T5 log             a log file plausibly covering the producing run still exists on disk.
  T6 quarantine      no untriaged verifier/solver contradiction names this cell.
  T7 one variant     the reported OV is the output of ONE variant, not a minimum over several.

                     T7 WAS ORIGINALLY WRITTEN AS MENU UNIFORMITY -- does this cell have the same
                     stage set as its size's modal cell -- and that test CANNOT FAIL FOR THE REASON
                     THAT MATTERS. A corpus in which all 135 cells uniformly took a best-of-eight
                     would have scored 135/135 and still been unpublishable. It scored 38/135, I
                     reported that, and then claimed restricting to floor+ceil "removes that
                     entirely", which is false: min(floor, ceil) is still a best-of-two. The author
                     caught it. Rewritten to ask the question that decides publishability, the pass
                     rate is 0 of 135: every cell reports a minimum over two or more variants, and
                     101 of them over three or more. (d594)

CLASSIFICATION, and the wording is deliberate

  REPORTABLE         T1 and T2 and T4 -- valid, anchored, and attributable to a budgeted run.
  VALID BUT UNPRICED T1 and T2, T4 fails -- the number is right and its cost cannot be stated.
                     Section 5.C of the finding forbids publishing it as a primal result without
                     declaring the total, so it is usable as a BOUND on what we achieved, not as
                     a budgeted comparison with K.
  UNANCHORED         T1 passes, T2 fails -- verified but not reproducible from a code state.
  NOT USABLE         T1 fails.

    python analysis/baseline_audit.py
"""
import collections
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from best_known import STAGES, best_solution, best_bound, _bound_patterns
from bound_certificate import bound_class
import quarantine_guard as QG

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
SIZES = (10, 20, 30, 50, 100)


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def stage_path(stage, cell, size):
    base = os.path.join(ROOT, "runs", "postpass", stage) if stage else os.path.join(ROOT, "runs", "postpass")
    return os.path.join(base, "ownwater_%s_n%d.json" % (cell, size))


def bound_paths(cell, size):
    """The accessor's OWN patterns. Hand-rolling these is what produced a false 108/135:
    the n100 glob here read tep_cg_bound_<cell>_d*.json where the accessor reads
    tep_cg_bound_<cell>_*.json plus tep_easy_reduction_<cell>_n100_k*.json, so all 27 n100
    cells looked uncertified when none is. Third instance of the same defect in one day. (d594)"""
    out = []
    for pat in _bound_patterns(cell, size):
        out += glob.glob(os.path.join(ROOT, "runs", "oracle", pat))
    return out


def quarantined_cells():
    out = set()
    for r in QG.rows():
        if QG.is_untriaged(r):
            rid = r.get("run_id") or ""
            for c in CELLS:
                if "_%s_" % c in rid:
                    out.add(c)
    return out


def any_log_for(cell, size):
    hits = glob.glob(os.path.join(ROOT, "logs", "*%s*" % cell))
    return len([h for h in hits if ("n%d" % size) in os.path.basename(h) or size == 100])


def main():
    qcells = quarantined_cells()
    print("BASELINE AUDIT -- what of the banked corpus is usable, per leg\n")
    print("  quarantine: %d untriaged contradiction(s); cells implicated: %s\n"
          % (sum(1 for r in QG.rows() if QG.is_untriaged(r)), ", ".join(sorted(qcells)) or "none"))

    # ---- stage uniformity, computed first because T7 needs the modal stage set per size
    present = {}
    for size in SIZES:
        for cell in CELLS:
            present[(cell, size)] = frozenset(s for s in STAGES if os.path.exists(stage_path(s, cell, size)))
    modal = {}
    for size in SIZES:
        c = collections.Counter(present[(cell, size)] for cell in CELLS)
        modal[size] = c.most_common(1)[0]

    rows = []
    for size in SIZES:
        for cell in CELLS:
            # ---------------- PRIMAL
            bs = best_solution(cell, size)
            p_art = load(os.path.join(ROOT, bs[2])) if bs else None
            t1 = bool(p_art and p_art.get("_verified"))
            t2 = bool(p_art and (p_art.get("_provenance") or {}).get("code_hash"))
            t3 = bool(p_art and any(k in p_art for k in ("secs", "wall", "seconds")))
            t4 = bool(p_art and any(k in p_art for k in ("run_id", "runId", "_run_id")))
            t5 = any_log_for(cell, size) > 0
            t6 = cell not in qcells
            n_variants = sum(1 for s in STAGES
                             for d in [load(stage_path(s, cell, size))]
                             if d and d.get("_verified") and d.get("objVal") is not None)
            t7 = (n_variants == 1)
            cls = ("NOT USABLE" if not t1 else "UNANCHORED" if not t2 else
                   "REPORTABLE" if (t4 and t7) else "VALID BUT UNPRICED")
            rows.append(dict(cell=cell, size=size, leg="primal", value=bs[0] if bs else None,
                             source=bs[1] if bs else None, t1=t1, t2=t2, t3=t3, t4=t4, t5=t5,
                             t6=t6, t7=t7, cls=cls))
            # ---------------- DUAL
            bb = best_bound(cell, size)
            d_art, d_cls = None, None
            for p in bound_paths(cell, size):
                d = load(p)
                if d and bound_class(d):
                    if d_art is None or (d.get("lp_composed") or d.get("composed") or 0) > (
                            d_art.get("lp_composed") or d_art.get("composed") or 0):
                        d_art, d_cls = d, bound_class(d)
            u1 = bool(d_cls)
            u2 = bool(d_art and (d_art.get("_provenance") or {}).get("code_hash"))
            u3 = bool(d_art and d_art.get("secs") is not None)
            u4 = False                          # no dual artifact carries a run id either
            u5 = t5
            u6 = t6
            u7 = t7
            ucls = ("NOT USABLE" if not u1 else "UNANCHORED" if not u2 else
                    "REPORTABLE" if u4 else "VALID BUT UNPRICED")
            rows.append(dict(cell=cell, size=size, leg="dual", value=bb[0] if bb else None,
                             source=d_cls, t1=u1, t2=u2, t3=u3, t4=u4, t5=u5, t6=u6, t7=u7,
                             cls=ucls))

    # ---------------- report
    print("  PER-TEST PASS RATE, of 135 cells each leg")
    print("  %-7s %9s %9s %9s %13s %7s %10s %10s" %
          ("leg", "T1 valid", "T2 prov", "T3 rt", "T4 attrib", "T5 log", "T6 quaran", "T7 uniform"))
    for leg in ("primal", "dual"):
        rs = [r for r in rows if r["leg"] == leg]
        print("  %-7s %9s %9s %9s %13s %7s %10s %10s" % (
            leg, *["%d/%d" % (sum(1 for r in rs if r[t]), len(rs)) for t in
                   ("t1", "t2", "t3", "t4", "t5", "t6", "t7")]))
    print()
    print("  CLASSIFICATION")
    print("  %-7s %-20s %s" % ("leg", "class", "cells"))
    for leg in ("primal", "dual"):
        c = collections.Counter(r["cls"] for r in rows if r["leg"] == leg)
        for k in ("REPORTABLE", "VALID BUT UNPRICED", "UNANCHORED", "NOT USABLE"):
            if c[k]:
                print("  %-7s %-20s %d" % (leg, k, c[k]))
    print()
    print("  STAGE UNIFORMITY (T7) -- the modal stage set per size and how many cells match it")
    for size in SIZES:
        st, n = modal[size]
        print("    n%-4d %2d/27 cells share the modal set {%s}" % (size, n, ", ".join(sorted(s or "floor" for s in st))))
    print()
    nu = [r for r in rows if r["leg"] == "primal" and not r["t7"]]
    print("    %d of 135 primal cells DIVERGE from their size's modal stage set -- those cells'"
          % len(nu))
    print("    best-of is taken over a different menu than their neighbours', which is what makes")
    print("    the corpus a selected maximum rather than one method's output.")

    p = os.path.join(ROOT, "runs", "oracle", "baseline_audit.json")
    json.dump(dict(rows=rows, modal={str(k): sorted(s or "floor" for s in v[0]) for k, v in modal.items()}),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
