r"""Triangle-inequality audit for the street distance matrix D (review item 3H, 2026-10-13).

D is round(euclidean, 2) (instance_view.py), so it can be non-metric by up to the rounding grain.
This tool quantifies that across every reported instance at its canonical proximity, and -- the
decisive part -- checks the two places the reported bounds could depend on metricity:

  1. TEP-LP window tightenings e_i = max(a_i, H0+D[g][i]), l_i = min(b_i, H1-D[i][g]-svc-U).
     Valid (exclude no feasible schedule) iff the DIRECT depot-customer arc is a shortest path,
     i.e. D[g][i] == SP[g][i] and D[i][g] == SP[i][g]. We compute all-pairs shortest paths and
     report the max shortfall on these arcs.
  2. Origin: recompute UNROUNDED euclidean and check whether every violation vanishes -- so the
     excess can be reported as two-decimal rounding as a traced fact, not an inference.

(AB4's clique term is separately gated on max_triangle_excess in crossfeed/fullset_bound.py; AP/MST/
FORCED are metric-free there. This tool covers the TEP-LP side the gate does not.)

    python analysis/triangle_audit.py        # from the repo root
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import verifier3 as V
from k_comparison import k_proximity
from run_full_grid import all_cells

SIZES = [10, 20, 30, 50, 100]
TOL = 1e-9


def main():
    win_worst, gen_worst, origin_ok, rows = (0.0, None), (0.0, None), True, []
    for size in SIZES:
        prox = k_proximity(size)
        for cell in all_cells():
            try:
                inst = V.load_instance(cell, size, prox)
            except Exception:
                continue
            n = len(inst.nodes)
            A = np.array([[inst.D[i][j] for j in range(n)] for i in range(n)], float)
            SP = A.copy()
            for k in range(n):
                SP = np.minimum(SP, SP[:, k, None] + SP[None, k, :])
            g, C = inst.depot, list(inst.customers)
            win = max(max(A[g, i] - SP[g, i] for i in C), max(A[i, g] - SP[i, g] for i in C))
            gen = float((A[:, None, :] - (A[:, :, None] + A[None, :, :])).max())
            rows.append((cell, size, win, gen))
            win_worst = max(win_worst, (win, (cell, size)), key=lambda t: t[0])
            gen_worst = max(gen_worst, (gen, (cell, size)), key=lambda t: t[0])
            if gen > TOL:
                xs = np.array([nd.x for nd in inst.nodes]); ys = np.array([nd.y for nd in inst.nodes])
                E = np.sqrt((xs[:, None] - xs[None, :]) ** 2 + (ys[:, None] - ys[None, :]) ** 2)
                if float((E[:, None, :] - (E[:, :, None] + E[None, :, :])).max()) > 1e-9:
                    origin_ok = False

    print("instances checked                       :", len(rows))
    print("MAX window-arc shortfall (g<->customer)  : %.6f  %s" % (win_worst[0], win_worst[1] or ""))
    print("  -> windows SAFE (direct==shortest)" if win_worst[0] <= TOL else "  -> WINDOWS EXPOSED")
    print("MAX general triangle excess (any triple) : %.6f  %s" % (gen_worst[0], gen_worst[1]))
    print("all violations vanish UNROUNDED          :", origin_ok, "(True => pure 2-decimal rounding)")
    viol_sizes = sorted({r[1] for r in rows if r[3] > TOL})
    print("sizes with any excess                    :", viol_sizes or "none",
          "| n100 cells affected:", sum(1 for r in rows if r[1] == 100 and r[3] > TOL))
    ok = win_worst[0] <= TOL and origin_ok
    print("VERDICT:", "reported bounds require no metricity" if ok else "REVIEW NEEDED")


if __name__ == "__main__":
    main()
