"""The UNIFORM-GRID per-instance table at |C| in {10,20,30}. Our side is the FROZEN uniform primal
variant run as the banked pu_ng* corpus -- one `tep_solve ... --submission` per cell per ng, one
code_hash, one seed. Per cell we take the ng-UNION: the best verifier3-clean incumbent OV over the
banked ng values, with the LOWER BOUND taken from the ng=10 run ONLY. This supersedes the earlier
prim_ens single-run reader and tep_n{10,20,30}_best_of.json as the manuscript corpus (author rule,
d684: "we keep only the last generated grid from the uniform variant"; the best_of assembly globbed
seven separate arm directories and composed a two-grain LB -- retired, d682/d683/d684).

  our OV  = min over banked ng of the verifier3-clean incumbent `ov` (the ng-union, a SAFE
            tightening: a min over verified feasible values, FN-free by construction, d702)
  our LB  = the ng=10 run's `lb` ALWAYS (the frozen DEFAULT-delta dual composed with the K-water
            bound, d678). ng>10 changes the primal search, not the certified bound; the finer-width
            max(default, d=5) composition is retired, d683/d684.
  K side  = k_targets_small.json (`proven`, `k_bound`) + k_comparison.k_best_incumbent (the better of
            their joint/lbbd incumbents)

Same ROW SCHEMA and the same DEFECT GUARDS as tep_n30_best_of.py, so every downstream reader is
drop-in. PROVEN cells (K prove the optimum) are attainment; OPEN cells are competition; the two are
never pooled (author rule). Read-only unless --write, which stamps the artifact -- and stamp.py will
REFUSE unless this generator is committed first (ProvenanceError, no override).

    python analysis/tep_uniform_grid.py --size 30            # print only, verify
    python analysis/tep_uniform_grid.py --size 30 --write    # stamp + write runs/oracle/tep_uniform_n30.json
"""
import argparse
import glob
import io
import json
import os
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from k_comparison import k_best_incumbent

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])


def pu_union(cell, size):
    """The ng-union row for one cell: best verified OV over the banked pu_ng* runs, ng=10 LB.

    Globs the per-cell pu_ng<g> artifacts, keeps the min OV among those with a verified incumbent,
    and ALWAYS takes the lower bound from the ng=10 run (the frozen dual leg, d678). Returns a
    prim_ens-shaped dict -- the baseline ng=10 record with ov/nCars overwritten by the union winner
    and `_best_ng`/`_ng_banked` added -- or None when no ng=10 artifact exists for the cell.
    """
    byng = {}
    for p in glob.glob(os.path.join(ROOT, "runs", "oracle",
                                    "tep_solve_pu_ng*_%s_n%d.json" % (cell, size))):
        m = re.search(r"pu_ng(\d+)_%s_n%d\.json$" % (cell, size), os.path.basename(p))
        if not m:
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        r = d.get("rows", [d])
        byng[int(m.group(1))] = r[0] if isinstance(r, list) else r
    base = byng.get(10)
    if base is None or base.get("ov") is None:
        return None
    cand = {g: r for g, r in byng.items() if r.get("ov") is not None}
    best_ng = min(cand, key=lambda g: cand[g]["ov"])
    br = cand[best_ng]
    row = dict(base)                       # carry provenance/story/lb from the ng=10 baseline
    row["ov"] = float(br["ov"])            # OV is the union winner
    row["nCars"] = br.get("nCars")
    row["lb"] = base.get("lb")             # LB is the ng=10 frozen dual, ALWAYS
    row["_best_ng"] = best_ng
    row["_ng_banked"] = sorted(cand)
    return row


def build(size):
    ktp = os.path.join(ROOT, "runs", "oracle", "k_targets_small.json")
    kt = {r["cell"]: r for r in json.load(io.open(ktp, encoding="utf-8"))["n%d" % size]["rows"]}
    rows = []
    for c in CELLS:
        r = pu_union(c, size)
        if r is None or r.get("ov") is None:
            continue
        kb, kw = k_best_incumbent(c, size)
        k = kt.get(c, {})
        rows.append(dict(
            cell=c, best=float(r["ov"]), cfg="pu_ng%d" % r["_best_ng"], cars=int(r.get("nCars") or 0),
            floor=None, ceil=None, theirs=kb, which=kw,
            proven=bool(k.get("proven")), ng_banked=r.get("_ng_banked"),
            their_lb=(float(k["k_bound"]) if k.get("k_bound") is not None else None),
            our_lb=(float(r["lb"]) if r.get("lb") is not None else None),
            lb_width=None, lb_class=(r.get("lb_source") or None)))
    return rows


def defects(rows):
    """The same three invariants tep_n30_best_of.py checks every run; a hit means DO NOT WRITE."""
    out = []
    for r in rows:
        if r["theirs"] and r["proven"] and r["best"] < r["theirs"] - 0.05:
            out.append(r["cell"] + "(below PROVEN optimum %.1f < %.1f)" % (r["best"], r["theirs"]))
        if r.get("our_lb") is not None and r["our_lb"] > r["best"] + 1e-6:
            out.append(r["cell"] + "(our LB %.1f > our primal %.1f: INVALID BOUND)" % (r["our_lb"], r["best"]))
        if r["proven"] and r.get("our_lb") is not None and r["theirs"] and r["our_lb"] > r["theirs"] + 1e-6:
            out.append(r["cell"] + "(our LB %.1f > their PROVEN optimum %.1f: INVALID BOUND)" % (r["our_lb"], r["theirs"]))
    return out


def report(size, rows):
    pv = [100.0 * (r["best"] / r["theirs"] - 1) for r in rows if r["theirs"] and r["proven"]]
    op = [100.0 * (r["best"] / r["theirs"] - 1) for r in rows if r["theirs"] and not r["proven"]]
    print("n%d uniform grid (pu_ng union), %d cells" % (size, len(rows)))
    if pv:
        print("  PROVEN %2d -- ATTAINMENT: mean %+.2f%%  median %+.2f%%  worst %+.2f%%  within1%%: %d"
              % (len(pv), st.mean(pv), st.median(pv), max(pv), sum(1 for g in pv if g <= 1.0)))
    if op:
        print("  OPEN   %2d -- COMPETITION: mean %+.2f%%  median %+.2f%%  worst %+.2f%%"
              % (len(op), st.mean(op), st.median(op), max(op)))
    ob = [r for r in rows if r.get("our_lb") and not r["proven"]]
    if ob:
        og = sorted(100.0 * (1 - r["our_lb"] / r["best"]) for r in ob)
        both = [r for r in ob if r.get("their_lb") and r.get("theirs")]
        tg = sorted(100.0 * (1 - r["their_lb"] / r["theirs"]) for r in both)
        print("  OPEN bracket (OV-LB)/OV: ours median %.1f%%  vs theirs %.1f%% (%d cells with both)"
              % (st.median(og), st.median(tg) if tg else -1, len(both)))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=30, choices=(10, 20, 30))
    ap.add_argument("--write", action="store_true", help="stamp and write the artifact (generator must be committed)")
    ap.add_argument("--supersede", action="store_true",
                    help="deliberately replace a prior-variant tep_uniform_n*.json (cross-hash "
                         "overwrite). Use ONLY when re-sourcing to a new frozen variant: the prior "
                         "artifact is reproducible from its code_hash in git and the keep-better "
                         "union dominates it (ng10 reproduces the prior run, union = min over ng).")
    a = ap.parse_args(argv[1:])
    rows = build(a.size)
    if len(rows) != 27:
        print("REFUSING: expected 27 cells, built %d" % len(rows))
        return 2
    report(a.size, rows)
    dfx = defects(rows)
    if dfx:
        print("  *** DEFECT -- NOT WRITING: %s ***" % ", ".join(sorted(set(dfx))))
        return 1
    print("  no defects.")
    if a.write:
        from stamp import stamped
        p = os.path.join(ROOT, "runs", "oracle", "tep_uniform_n%d.json" % a.size)
        json.dump(stamped(dict(size=a.size, variant="pu_union", rows=rows), __file__, path=p,
                          supersede=a.supersede),
                  io.open(p, "w", encoding="utf-8"), indent=1, default=str)
        print("  wrote %s" % os.path.relpath(p, ROOT))
    else:
        print("  (print-only; pass --write to stamp the artifact)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
