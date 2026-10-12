"""ADVERSE CHECK on the 'formulation is the bottleneck' claim.

The raw LP relaxation is NOT what branch-and-bound works with: CPLEX adds
cut families at the root. If the root bound AFTER cuts is strong, then the
formulation is fine and BRANCHING is the bottleneck -- which would kill the
reformulation case. This measures it.
"""
import sys, os, json, argparse, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.stamp import stamped
from build_instance import build
from joint_model_cplex import build_joint_model


def root_bound(cell, size, tl):
    problem = build(cell, size, tau="formula")   # MUST match InstanceSpec; build() defaults to tau="code" (TD=0)
    H = build_joint_model(problem)
    m = H.m
    p = m.parameters
    p.timelimit = tl
    p.mip.limits.nodes = 1          # root node only
    p.threads = 4
    m.solve(log_output=False)
    d = m.solve_details
    return dict(cell=cell, size=size,
                root_after_cuts=d.best_bound,
                status=d.status, time=d.time)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C202,C203,R204,RC202")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--tl", type=float, default=600)
    ap.add_argument("--out", default="runs/root_after_cuts.json")
    a = ap.parse_args()

    raw = {r["cell"]: r["lp"] for r in json.load(open("runs/lp_anatomy.json"))}
    rows = []
    print(f"{'cell':8s} {'raw LP':>9s} {'root+cuts':>10s} {'our LB':>8s} {'incumb':>8s}  verdict")
    REF = {"C202": (663.1, 678.7), "C203": (648.2, 673.7),
           "R204": (525.9, 582.8), "RC202": (829.4, 900.6)}
    for c in a.cells.split(","):
        c = c.strip()
        r = root_bound(c, a.size, a.tl)
        rows.append(r)
        lb, inc = REF.get(c, (float("nan"), float("nan")))
        rc = r["root_after_cuts"]
        v = "cuts FIXED it" if rc and rc > 0.9 * inc else \
            ("cuts beat our LB" if rc and rc > lb else "still far below our LB")
        print(f"{c:8s} {raw.get(c, float('nan')):9.1f} {rc:10.1f} {lb:8.1f} {inc:8.1f}  {v}")
    os.makedirs("runs", exist_ok=True)
    json.dump(stamped(rows, __file__), open(a.out, "w"), indent=1)
    print("\nwrote", a.out)
