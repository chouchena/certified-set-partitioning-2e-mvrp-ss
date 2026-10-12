"""The K-free TEP pair on a 15-cell sample: 3 families x 5 sizes, against what we already hold.

VARIANT, declared before the run:
  dual    tep_cg_bound.run, DELTA default, ng=10, start-state pricing, elementary certificate
  primal  tep_cg_bound.master_ip -> tep_chain_own_water.admissible_solution
Both are K-free on the call path, verified by static call graph and by runtime sys.modules on
R208 n30 (ef3c6f3). Neither loads joint_model_cplex, fixopt or lagrangian_subproblem.

SAMPLE, by a rule fixed before any value was seen: the lowest-numbered cell of each family that
carries both an OV and an LB at all five sizes -> C201, R201, RC201.

WHAT THE COMPARISON IS, and is not. The banked values came from a code state that cannot be
recovered (git_dirty True on all 563, 1 of 7 recorded source hashes findable in history). So a
difference measures NEW AGAINST WHAT WE HOLD, not new against the old variant. It cannot
attribute a change to the variant switch.

    python analysis/tep_sample15.py --sizes 10 20 30
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
import verifier3 as V
import tep_cg_bound as T
from k_comparison import k_proximity
from best_known import best_solution, best_bound
from bound_certificate import bound_class
from stamp import stamped

CELLS = ["C201", "R201", "RC201"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100])
    ap.add_argument("--cells", nargs="*", default=CELLS)
    ap.add_argument("--iters", type=int, default=60)
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--cg-secs", type=float, default=240.0)
    ap.add_argument("--ip-work", type=float, default=120.0)
    a = ap.parse_args()

    print("TEP K-FREE PAIR -- %d cells x %d sizes | ng %s | cg wall %.0f s | ip work %.0f\n"
          % (len(a.cells), len(a.sizes), a.ng, a.cg_secs, a.ip_work))
    print("  %-6s %-5s %10s %10s %9s %10s %10s %9s  %s"
          % ("cell", "size", "LB new", "LB held", "dLB%", "OV new", "OV held", "dOV%", "note"))
    rows = []
    for size in a.sizes:
        prox = k_proximity(size)
        for cell in a.cells:
            t0 = time.time()
            rec = dict(cell=cell, size=size)
            try:
                inst = V.load_instance(cell, size, prox)
                r = T.run(cell, T.default_delta(inst), a.iters, ["prio", "ts"], a.ng, 1000, False,
                          3_000_000, size=size, proximity=prox, max_secs=a.cg_secs,
                          start_states=True, return_master=True, primal=False)
                rec["lp_street"] = r.get("lp_street")
                rec["proven"] = r.get("proven")
                rec["lb_new"] = r.get("composed") if r.get("composed") is not None else r.get("lp_composed")
                if rec["lb_new"] is None:
                    rec["lb_new"] = r.get("lp_street")
                M = r.get("master")
                ip = T.master_ip(M, cell, size, threads=2, timelimit=1800.0, work=a.ip_work) if M else {}
                rec["ov_new"] = ip.get("objVal")
                rec["ov_verified"] = ip.get("verified")
                rec["chain_status"] = ip.get("chain_status")
                rec["route"] = ip.get("route")
            except Exception as e:
                rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:70])
            bb = best_bound(cell, size); bs = best_solution(cell, size)
            rec["lb_held"] = bb[0] if bb else None
            rec["ov_held"] = bs[0] if bs else None
            rec["secs"] = round(time.time() - t0, 1)
            dlb = (100.0 * (rec.get("lb_new") - rec["lb_held"]) / rec["lb_held"]
                   if rec.get("lb_new") and rec["lb_held"] else None)
            dov = (100.0 * (rec.get("ov_new") - rec["ov_held"]) / rec["ov_held"]
                   if rec.get("ov_new") and rec["ov_held"] else None)
            rec["d_lb_pct"], rec["d_ov_pct"] = dlb, dov
            note = rec.get("error") or ("proven" if rec.get("proven") else "unproven")
            if rec.get("ov_new") and not rec.get("ov_verified"):
                note += " | OV NOT VERIFIED"
            print("  %-6s n%-4d %10s %10s %8s %10s %10s %8s  %s"
                  % (cell, size,
                     "%.2f" % rec["lb_new"] if rec.get("lb_new") else "-",
                     "%.2f" % rec["lb_held"] if rec["lb_held"] else "-",
                     "%+.2f%%" % dlb if dlb is not None else "-",
                     "%.2f" % rec["ov_new"] if rec.get("ov_new") else "-",
                     "%.2f" % rec["ov_held"] if rec["ov_held"] else "-",
                     "%+.2f%%" % dov if dov is not None else "-", note), flush=True)
            rows.append(rec)
    p = os.path.join(ROOT, "runs", "oracle", "tep_sample15.json")
    json.dump(stamped(dict(rows=rows, cells=a.cells, sizes=a.sizes, ng=a.ng,
                           cg_secs=a.cg_secs, ip_work=a.ip_work)),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
