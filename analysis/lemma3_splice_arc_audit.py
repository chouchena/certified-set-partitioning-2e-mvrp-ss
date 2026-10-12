"""LEMMA 3 audit: does the SPLICED arc always exist in the reduced model?

THE GAP. validation/easy_reduction_bound_proof.md Step 2 deletes customer e from a route
and reconnects p -> s, then argues cost/time/capacity all behave. It never checks that the
arc (p,s) EXISTS. It must: block_a.py:80 prunes arcs by a time-window filter

    (i,j) in arcset   <=>   e_i + s_i + D[i][j] <= l_j

so a spliced arc outside arcset is simply not a variable, and the constructed solution would
not be representable in the reduced model. The monotonicity proof would have a hole.

THE ARGUMENT (why it is nonetheless safe). Let the route use p -> e -> s in a feasible
block-A solution. Timing (block_a.py:108, Const8) gives

    h_p + s_p + aS[p,e] <= h_e   and   h_e + s_e + aS[e,s] <= h_s ,

with aS >= D (block_a.py:131). Chaining and dropping s_e >= 0:

    h_p + s_p + D[p][e] + D[e][s] <= h_s <= l_s .

The triangle inequality gives D[p][s] <= D[p][e] + D[e][s], and h_p >= e_p (the h lower
bound, block_a.py:71), so

    e_p + s_p + D[p][s] <= l_s ,   i.e. (p,s) IS in arcset.  QED

Boundary cases: p = 0 uses e_0 + D[0][i] <= h_i (block_a.py:100) and needs s_0 = 0;
s = 0 uses h_p <= l_0 - D[p][0] - s_p - TD (block_a.py:101), which is stronger by TD.

THIS SCRIPT verifies the conclusion EXHAUSTIVELY rather than trusting the derivation.

!! CORRECTED 2026-09-14. The first version quantified over every triple with (p,e) and (e,s)
in arcset, and reported 5699 "missing" arcs out of 134712. That test was WRONG, not the lemma:
arc membership is the weak condition e_i + s_i + D[i][j] <= l_j, which admits triples that no
feasible route can ever use. The splicing argument assumes p -> e -> s occurs in a FEASIBLE
solution, so the precondition must be TIME-FEASIBILITY of the two-leg chain:

    h_p = e_p,  h_e = max(e_e, h_p + s_p + D[p][e]) <= l_e,
                h_s = max(e_s, h_e + s_e + D[e][s]) <= l_s

(earliest-start is the most permissive choice, so this is exactly "some feasible timing exists").
Under that precondition the derivation above forces (p,s) in arcset, and the check below is a
verification of the algebra over every splice the descent could ever perform, at every k.
"""
import sys, os, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from build_instance import build          # noqa: E402

CELLS = ("C201,C202,C203,C204,C205,C206,C207,C208,R201,R202,R203,R204,R205,R206,R207,"
         "R208,R209,R210,R211,RC201,RC202,RC203,RC204,RC205,RC206,RC207,RC208").split(",")


def audit(cell, size):
    p = build(cell, size, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
    nd, D = p.nodes, p.DistMatrix
    SetCd = [0] + list(p.customers)
    ok = lambda i, j: nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest  # noqa: E731
    arcs = {(i, j) for i in SetCd for j in SetCd if i != j and ok(i, j)}
    depot_svc = nd[0].serviceTime
    bad, triples, skipped = [], 0, 0
    for e in p.customers:
        for pnode in SetCd:
            if pnode == e or (pnode, e) not in arcs:
                continue
            for s in SetCd:
                if s in (e, pnode) or (e, s) not in arcs:
                    continue
                # PRECONDITION: the chain p -> e -> s must be TIME-FEASIBLE, i.e. some
                # feasible timing exists. Earliest start is the most permissive choice.
                h_p = nd[pnode].earliest
                h_e = max(nd[e].earliest, h_p + nd[pnode].serviceTime + D[pnode][e])
                if h_e > nd[e].latest:
                    skipped += 1; continue
                h_s = max(nd[s].earliest, h_e + nd[e].serviceTime + D[e][s])
                if h_s > nd[s].latest:
                    skipped += 1; continue
                triples += 1
                if (pnode, s) not in arcs:
                    bad.append((pnode, e, s))
    # triangle inequality, the other premise
    tv = 0
    for i in SetCd:
        for j in SetCd:
            for k in SetCd:
                if i != j and j != k and i != k and D[i][k] > D[i][j] + D[j][k] + 1e-9:
                    tv += 1
    return triples, bad, tv, depot_svc, skipped


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--cells", default="")
    a = ap.parse_args()
    cells = [c.strip() for c in a.cells.split(",") if c.strip()] or CELLS
    tot, allbad, alltv, svc = 0, 0, 0, []
    for c in cells:
        t, bad, tv, ds, sk = audit(c, a.size)
        tot += t; allbad += len(bad); alltv += tv; svc.append(ds)
        flag = "OK" if not bad and not tv and ds == 0 else "**FAIL**"
        print(f"{c:7s} n{a.size}  feasible triples {t:7d} (skipped {sk:6d} time-infeasible)  "
              f"missing arcs {len(bad):3d}  triangle viol {tv:3d}  {flag}")
        for b in bad[:3]:
            print("     missing:", b)
    print(f"\nTOTAL splice triples checked: {tot}")
    print(f"missing spliced arcs: {allbad}")
    print(f"triangle-inequality violations: {alltv}")
    print(f"nonzero depot service times: {sum(1 for x in svc if x != 0)}")
    print("VERDICT:", "PASS -- every splice the descent could perform stays representable"
          if allbad == 0 and alltv == 0 and not any(x != 0 for x in svc) else "FAIL")
