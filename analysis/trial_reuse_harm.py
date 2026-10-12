"""Does the reuse constructor ever HURT, at the sizes where nobody has looked? (n=596)

WHY. `trial_F5_construct_reuse.json` already answers the harm question at n100 and answers it
cleanly: reuse worse on 0 of 6 cells, median -7.50 per cent, fleet reduced on 5 of 6. I told the
author twice that no base-versus-reuse pair was banked anywhere, which was wrong -- the artifact
was in the first listing I printed and the claims register states the 6-of-6 result in words.

What is genuinely unmeasured is the OTHER FOUR SIZES. n=308 records that the constructor is an
n100 lever specifically: the climb it shortens is 22.6 per cent of the budget at n100 and about 1
per cent at n20. A lever worth ~1 per cent can still do harm, and C1 -- one variant, uniform over
all 135 cells -- needs to know that it does not.

WHAT IS COMPARED, and it is deliberately narrow. Base constructor against reuse constructor, same
cell, same instance, construction objective only, both through verifier3. No search runs. That is
the quantity the harm question is about: whether starting from reuse ever leaves the chain worse
off than starting from base. Both constructors are deterministic, so there is no seed and no
replication -- the paired difference is exact.

  HARM      reuse construction objective strictly worse than base, beyond 0.05
  INFEASIBLE  reuse fails to build or fails verifier3 where base succeeds -- also harm, and worse

    python analysis/trial_reuse_harm.py --sizes 10 20 30 50
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
import instance_view
import verifier3
import greedy26
import greedy26_reuse
from k_comparison import k_proximity
from stamp import stamped

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])


def build(inst, which, cell, size, prox):
    """(objective, verdict) or (None, reason)."""
    try:
        sol = greedy26.construct(inst) if which == "base" else greedy26_reuse.construct(inst)
    except Exception as e:
        return None, "raised %s" % type(e).__name__
    if sol is None:
        return None, "no seed"
    run = verifier3.verify_solution(inst, sol, cell=cell, size=size, proximity=prox,
                                    label="reuse-harm-%s" % which)
    if run.verdict() != verifier3.ACCEPT:
        return None, "verifier3 %s" % run.verdict()
    o = getattr(run, "objective", None)
    return (o["recomputed"] if o else sol.get("objVal")), "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50])
    a = ap.parse_args()
    print("REUSE CONSTRUCTOR -- the harm test at the sizes nobody measured\n")
    print("  %-6s %-5s %12s %12s %10s  %s" % ("cell", "size", "base", "reuse", "change", "note"))
    rows, harm, infeas = [], [], []
    import statistics as st
    for size in a.sizes:
        prox = k_proximity(size)
        for cell in CELLS:
            try:
                inst = instance_view.VInstance(cell, size, wls=0.1,
                                               tau=verifier3.tau_for(verifier3.raw_for(cell), size),
                                               proximity=prox)
            except Exception:
                inst = verifier3.load_instance(cell, size, prox)
            b, bn = build(inst, "base", cell, size, prox)
            r, rn = build(inst, "reuse", cell, size, prox)
            note, pct = "", None
            if b is None and r is None:
                note = "both fail (base %s, reuse %s)" % (bn, rn)
            elif r is None:
                note = "REUSE FAILS where base builds (%s)" % rn; infeas.append((cell, size, rn))
            elif b is None:
                note = "reuse builds where base fails (%s)" % bn
            else:
                pct = 100.0 * (r - b) / b
                if r > b + 0.05:
                    note = "HARM"; harm.append((cell, size, b, r, pct))
            print("  %-6s n%-4d %12s %12s %10s  %s"
                  % (cell, size, "%.3f" % b if b is not None else "-",
                     "%.3f" % r if r is not None else "-",
                     "%+.2f%%" % pct if pct is not None else "-", note), flush=True)
            rows.append(dict(cell=cell, size=size, base=b, reuse=r, pct=pct,
                             base_note=bn, reuse_note=rn))
    print()
    for size in a.sizes:
        p = [x["pct"] for x in rows if x["size"] == size and x["pct"] is not None]
        if p:
            print("  n%-4d %2d paired | median %+.2f%% | worse on %d | best %+.2f%%"
                  % (size, len(p), st.median(p), sum(1 for v in p if v > 0.05), min(p)))
    print()
    print("  HARM (reuse strictly worse): %d cell(s)" % len(harm))
    for c, s, b, r, p in harm[:8]:
        print("    %-6s n%-4d %.3f -> %.3f (%+.2f%%)" % (c, s, b, r, p))
    print("  REUSE INFEASIBLE where base builds: %d cell(s)" % len(infeas))
    for c, s, why in infeas[:8]:
        print("    %-6s n%-4d %s" % (c, s, why))
    ok = not harm and not infeas
    print("\n  VERDICT: %s" % ("no harm found at any tested size -- reuse may be adopted uniformly"
                               if ok else
                               "HARM FOUND -- reuse does not qualify for uniform adoption as it stands"))
    p = os.path.join(ROOT, "runs", "oracle", "trial_reuse_harm.json")
    json.dump(stamped(dict(rows=rows, harm=harm, infeasible=infeas, sizes=a.sizes, clean=ok)),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
