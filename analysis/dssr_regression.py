"""REGRESSION TEST for d635: the DSSR certificate must not depend on the pool it starts from.

The claim DSSR writes is "no elementary column prices out at the final duals over an
elementary-only pool", which implies the restricted LP IS LP(R_e) -- a quantity that does not
depend on which columns happened to be in the pool when DSSR started. So starting DSSR from
pools of different quality must give the SAME value. The wall-capped run B1 gave a higher one,
once, and would not reproduce; varying the CG iteration count makes the poorer pool on purpose.

THE SUSPECT IS d427, INHERITED. ng dominance can hide a variant-feasible elementary column
behind a cheaper label whose completions the master rejects, so "the ng pricer found nothing" is
not a proof that nothing exists. DSSR is supposed to escape that by growing C* whenever a FOUND
column repeats a customer -- but a column that is never found cannot grow C*, and the loop then
terminates. Where the pool already contains the hidden columns (a fully converged CG) the LP is
right anyway and the defect is invisible. Where it does not, the certificate would be false.

Reference value, three runs out of three from the full pool: 1216.866234486718.
"""
import os
import sys
import time

ROOT = r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

import tep_cg_bound as T
from k_comparison import k_proximity
from dssr_certify import dssr, is_elementary

CELL, SIZE, EPS = "R206", 50, 1e-6
prox = k_proximity(SIZE)
TRUE = 1216.866234486718

bad = 0
print("%-6s %8s %8s %9s %18s %18s %7s %6s %8s  %s"
      % ("iters", "cols", "elem", "ngLP", "poolLP", "DSSR lp", "rounds", "|C*|", "labels", "verdict"))
for iters in (6, 10, 16, 400):
    t0 = time.time()
    r = T.run(CELL, 20.0, iters, ["prio", "ts"], 10, 1000, False, 3_000_000, size=SIZE,
              proximity=prox, start_states=True, elem_pass=False, return_master=True, threads=4)
    M = r.pop("master")
    off = 0
    for k, v in M.cols.items():
        if not is_elementary(k[0]):
            v.UB = 0.0
            off += 1
    M.solve()
    pool_lp = M.m.ObjVal
    ok, rounds, Cstar, labels, added, lp = dssr(M, 10, 3_000_000, 4, lambda m: None)
    slack = sum(v.X for v in M.slack.values())
    cert = bool(ok and slack < 1e-6)
    if not cert:
        verdict = "did not certify"
    elif lp > TRUE + 1e-9:
        verdict = "*** CERTIFIED ABOVE LP(R_e) by %+.9f -- FALSE CERTIFICATE" % (lp - TRUE)
    elif lp < TRUE - 1e-9:
        verdict = "below the reference by %+.9f" % (lp - TRUE)
    else:
        verdict = "matches"
    bad += verdict.startswith("***")
    print("%-6d %8d %8d %9.4f %18.9f %18.9f %7d %6d %8d  %s"
          % (iters, len(M.cols), len(M.cols) - off, r["lp_street"], pool_lp, lp, rounds,
             len(Cstar), labels, verdict), flush=True)
    del M

print("")
print("FAILURES: %d  (any non-zero means the certificate has become pool-dependent again)" % bad)
sys.exit(1 if bad else 0)
