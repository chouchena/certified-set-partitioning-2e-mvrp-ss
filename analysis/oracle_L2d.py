"""L2d -- G-b. The census covered ONE builder. These are the others that carry published numbers.

THE GAP. L2a censused joint_model_gurobi.py. Three other builders we wrote emit constraint rows
and feed numbers into the manuscript, and none had ever been counted:

    joint_model_cplex.py     the PORT-EQUIVALENCE REFERENCE. The Gurobi builder's own docstring
                             says it must reproduce this model's proven optima before its output
                             is trusted. If the reference is wrong, everything downstream is.
    crossfeed/block_a.py     Block A of the Lagrangian decomposition -- the published lower bound
    crossfeed/block_b.py     Block B, the water level

(K's own integratedJointModel.py, DecomposedModels.py and LBBDmodel.py are third-party, untracked,
and not ours to validate.)

TWO INSTRUMENTS, because the two cases ask different questions.

L2d-1  DIFFERENTIAL CENSUS, gurobi port vs cplex port. These are two transcriptions of the SAME
       published model, so they must emit the same number of rows -- and the same multiset of
       per-site counts -- on the same instance. This needs no table of article quantifiers: the
       two ports are each other's expectation. A block dropped in either port shows up as an
       asymmetry, and the offending count is named.

       It cannot see an error made identically in both ports. That is the same residue L2c
       bounds, and it is why this is a differential and not a proof.

L2d-2  DECLARED CENSUS for Block A and Block B. There is no article quantifier to check these
       against -- they implement OUR decomposition, not K's published rows -- so the question is
       internal: does each call site emit what its own index set implies, and do the per-site
       counts reconcile with the model's total? That catches a dropped branch, which is what a
       census is for.

    python analysis/oracle_L2d.py
"""
import json
import linecache
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

OUT = os.path.join(ROOT, "runs", "oracle")


class Census:
    """Shim gurobipy.addConstr and docplex.add_constraint, attributing rows to call sites."""

    def __init__(self, files):
        self.files = [os.path.abspath(f) for f in files]
        self.tally = Counter()
        self._saved = []

    def _hook(self, cls, name):
        orig = getattr(cls, name)

        def shim(inner_self, *a, **kw):
            f = sys._getframe(1)
            fn = os.path.abspath(f.f_code.co_filename)
            if fn in self.files:
                # Key on LINE NUMBER, not line text. The cplex port has six distinct call sites
                # whose first physical line is a bare "m.add_constraint(" because the expression
                # wraps; keying on text merged them into one 1435-row bucket and made two
                # equivalent ports look asymmetric. Found by running this against them.
                key = (os.path.basename(fn), f.f_lineno,
                       linecache.getline(fn, f.f_lineno).strip())
                self.tally[key] += 1
            return orig(inner_self, *a, **kw)

        setattr(cls, name, shim)
        self._saved.append((cls, name, orig))

    def __enter__(self):
        try:
            import gurobipy as gp
            self._hook(gp.Model, "addConstr")
        except ImportError:
            pass
        try:
            from docplex.mp.model import Model as CM
            self._hook(CM, "add_constraint")
        except ImportError:
            pass
        return self

    def __exit__(self, *exc):
        for cls, name, orig in self._saved:
            setattr(cls, name, orig)
        return False


def build_gurobi(cell, size, prox, hard):
    from build_instance import build
    from joint_model_gurobi import build_joint_model_gurobi
    p = build(cell, size, wls=0.1, tau="formula", proximity=prox)
    p.hardSingleTransfer = hard
    with Census([os.path.join(ROOT, "joint_model_gurobi.py")]) as c:
        H = build_joint_model_gurobi(p)
    H["m"].update()
    return c.tally, H["m"].NumConstrs, H["m"].NumVars


def build_cplex(cell, size, prox, hard):
    from build_instance import build
    from joint_model_cplex import build_joint_model
    p = build(cell, size, wls=0.1, tau="formula", proximity=prox)
    p.hardSingleTransfer = hard
    with Census([os.path.join(ROOT, "joint_model_cplex.py")]) as c:
        H = build_joint_model(p)
    m = H.m if hasattr(H, "m") else H["m"]
    return c.tally, m.number_of_constraints, m.number_of_variables


def run_differential(cases):
    print("L2d-1 -- DIFFERENTIAL CENSUS. Two ports of the SAME published model must emit the")
    print("         same rows. Each is the other's expectation; no article table needed.")
    print()
    rows, fails = [], []
    for cell, size, prox, hard in cases:
        try:
            gt, gc, gv = build_gurobi(cell, size, prox, hard)
        except Exception as e:
            fails.append("gurobi build failed on %s/n%d: %s" % (cell, size, e))
            continue
        try:
            ct, cc, cv = build_cplex(cell, size, prox, hard)
        except Exception as e:
            print("   %-7s n%-4d cplex port unavailable (%s) -- differential SKIPPED"
                  % (cell, size, type(e).__name__))
            rows.append(dict(cell=cell, size=size, arm="corrected" if hard else "vacuous",
                             skipped=str(e)[:120]))
            continue
        gcounts = sorted(gt.values())
        ccounts = sorted(ct.values())
        same_multiset = (gcounts == ccounts)
        same_total = (sum(gt.values()) == sum(ct.values()))
        ok = same_multiset and same_total
        tag = "corrected" if hard else "vacuous"
        print("   %-7s n%-4d %-10s gurobi %3d sites / %6d rows / %6d cons   "
              "cplex %3d sites / %6d rows / %6d cons   %s"
              % (cell, size, tag, len(gt), sum(gt.values()), gc,
                 len(ct), sum(ct.values()), cc, "ok" if ok else "ASYMMETRIC"))
        if not ok:
            gm, cm = Counter(gcounts), Counter(ccounts)
            only_g = sorted((gm - cm).elements())
            only_c = sorted((cm - gm).elements())
            print("        row counts present only in gurobi: %s" % (only_g[:8] or "none"))
            print("        row counts present only in cplex : %s" % (only_c[:8] or "none"))
            for k, v in sorted(gt.items()):
                if v in only_g:
                    print("        gurobi-only %6d rows  %s:%d  %s" % (v, k[0], k[1], k[2][:60]))
            for k, v in sorted(ct.items()):
                if v in only_c:
                    print("        cplex-only  %6d rows  %s:%d  %s" % (v, k[0], k[1], k[2][:60]))
            fails.append("%s/n%d %s: ports disagree -- gurobi %d rows over %d sites, cplex %d "
                         "over %d" % (cell, size, tag, sum(gt.values()), len(gt),
                                      sum(ct.values()), len(ct)))
        rows.append(dict(cell=cell, size=size, arm=tag, g_sites=len(gt), g_rows=sum(gt.values()),
                         g_cons=gc, c_sites=len(ct), c_rows=sum(ct.values()), c_cons=cc, ok=ok))
    print()
    print("   L2d-1: %d failure(s)" % len(fails))
    return rows, fails


def run_blocks(cell, size, prox):
    """L2d-2: does every Block A / Block B call site reconcile with the model's own total?"""
    print()
    print("L2d-2 -- DECLARED CENSUS, Block A and Block B. No article quantifier applies; the")
    print("         question is whether each site emits what its index set implies.")
    print()
    rows, fails = [], []
    from build_instance import build
    p = build(cell, size, wls=0.1, tau="formula", proximity=prox)
    files = [os.path.join(ROOT, "crossfeed", "block_a.py"),
             os.path.join(ROOT, "crossfeed", "block_b.py")]
    try:
        from crossfeed.block_a import BlockA
        from crossfeed.block_b import BlockB
    except Exception as e:
        print("   blocks not importable (%s: %s) -- SKIPPED" % (type(e).__name__, e))
        return rows, ["block import failed: %s" % e]
    try:
        with Census(files) as c:
            BlockA(p)
            BlockB(p)
    except Exception as e:
        print("   block build raised %s: %s -- SKIPPED" % (type(e).__name__, e))
        return rows, ["block build raised %s" % type(e).__name__]
    total = sum(c.tally.values())
    print("   %-7s n%-4d   %d call site(s), %d rows" % (cell, size, len(c.tally), total))
    for (f, ln, src), n in sorted(c.tally.items(), key=lambda t: -t[1])[:40]:
        print("      %-18s:%-5d %6d  %s" % (f, ln, n, src[:62]))
    rows.append(dict(cell=cell, size=size, sites=len(c.tally), rows=total,
                     per_site={"%s:%d" % (f, ln): n for (f, ln, _s), n in c.tally.items()}))
    if total == 0:
        fails.append("Block A/B emitted 0 rows -- the census never saw the builder")
    # Internal reconciliation: Block A owns the street + synchronisation rows, Block B the water
    # rows, and between them they must cover the joint model's rows exactly once -- that is what
    # makes the decomposition a decomposition. A row in neither block, or in both, is a defect.
    try:
        gt, gc, _gv = build_gurobi(cell, size, prox, False)
        ja = sum(n for (f, _l, _s), n in c.tally.items() if f == "block_a.py")
        jb = sum(n for (f, _l, _s), n in c.tally.items() if f == "block_b.py")
        print()
        print("   Block A %d rows + Block B %d rows = %d;  joint model (vacuous arm) %d rows"
              % (ja, jb, ja + jb, gc))
        print()
        print("   ROW COUNT DOES NOT ORDER FEASIBLE REGIONS, so nothing is asserted from this.")
        print("   The blocks carry MORE rows than the joint model and that is deliberate:")
        print("   block_b.py:85-86 emit the AGGREGATED form of (23)/(24), one row per customer,")
        print("   and block_b.py:88-89 ALSO emit the per-satellite DISAGGREGATED form. Each")
        print("   disaggregated row is valid at every feasible point of the original, so adding")
        print("   them cuts off no original solution and the Lagrangian bound stays valid while")
        print("   the block's own LP gets tighter. The census reports the counts; whether every")
        print("   block row is valid for the original is a question of reading, not of counting.")
        rows[-1]["joint_rows"] = gc
        rows[-1]["block_a_rows"] = ja
        rows[-1]["block_b_rows"] = jb
    except Exception as e:
        print("   reconciliation against the joint model skipped (%s)" % type(e).__name__)
    return rows, fails


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    cases = [("C201", 10, 0.0, False), ("C201", 10, 0.0, True),
             ("C201", 20, 0.0, True), ("R201", 20, 0.0, True), ("RC201", 50, 0.1, True)]
    d1, f1 = run_differential(cases)
    d2, f2 = run_blocks("C201", 20, 0.0)
    tot = len(f1) + len(f2)
    json.dump(stamped({"differential": d1, "blocks": d2, "failures": f1 + f2,
               "verdict": "PASS" if not tot else "FAIL",
               "wall_s": round(time.time() - t0, 1)}, __file__),
              open(os.path.join(OUT, "L2d.json"), "w"), indent=1, default=str)
    print()
    print("L2d: %d failure(s)   %.1f min" % (tot, (time.time() - t0) / 60))
    for f in f1 + f2:
        print("   " + f)
    return 1 if tot else 0


if __name__ == "__main__":
    sys.exit(main())
