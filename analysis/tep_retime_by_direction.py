"""The rounding direction, measured where it bites hardest: does the selection survive exact re-timing? (d577)

WHAT THIS IS. L-TEP-ceil says an integer solution of the upward-rounded master admits an exact street
timetable; the downward-rounded master is a relaxation and carries no such guarantee. Both statements
are about the implementation as much as the mathematics, and both are testable on artifacts we
already have: every `--ip` run records whether the selection it produced could be re-timed by
`assemble_precluster.retime` (K's joint model with the street frozen) and verified by verifier3.

This counts that, split by rounding direction and by size. It is a census over every banked master-IP
run, not a sample, and it needs no solver.

WHY IT IS AN EXHIBIT AND NOT A DIAGNOSTIC. The gap between the two directions is the discretisation
error made visible in the one currency that matters to a practitioner: whether the plan can be
executed. A referee can recompute it from the released artifacts in seconds.

THE EXCEPTIONS ARE PART OF THE RESULT. A handful of ceil selections fail, and the reason is scope,
not a broken lemma: the TEP master carries no vessel variables -- the water part is bounded
separately -- while re-timing solves the joint model, vessels included. A ceil street selection can
be street-feasible and admit no vessel schedule. The script prints those cells and checks whether the
production ceil stage nevertheless found a verified solution for them, which is what separates
"the direction is wrong" from "the master does not model that side".

    python analysis/tep_retime_by_direction.py
"""
import collections
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

SIZES = (10, 20, 30, 50, 100)


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def main():
    tab = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    fails = []
    for p in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_*_ip*.json")):
        d = load(p)
        ip = (d or {}).get("ip")
        if not isinstance(ip, dict) or ip.get("retime_status") is None:
            continue
        n = d.get("size") or 100
        arm = "ceil" if d.get("primal_rounding") else "floor"
        tab[n][arm][1] += 1
        if ip.get("verified"):
            tab[n][arm][0] += 1
        elif arm == "ceil":
            stage = load(os.path.join(ROOT, "runs", "postpass", "ceil", "ownwater_%s_n%d.json" % (d.get("cell"), n)))
            fails.append(dict(cell=d.get("cell"), size=n, retime=str(ip.get("retime_status")),
                              secs=ip.get("retime_secs"), decode_ok=ip.get("decode_ok"),
                              ip_status=ip.get("ip_status"),
                              stage_verified=bool(stage and stage.get("_verified")),
                              stage_obj=(stage or {}).get("objVal")))
    print("DOES THE SELECTION SURVIVE EXACT RE-TIMING? every banked master-IP run, by rounding direction\n")
    print("%-6s %26s %26s" % ("size", "ceil (restriction)", "floor (relaxation)"))
    rows = []
    for n in SIZES:
        if n not in tab:
            continue
        c, f = tab[n]["ceil"], tab[n]["floor"]
        rows.append(dict(size=n, ceil_ok=c[0], ceil_n=c[1], floor_ok=f[0], floor_n=f[1]))
        print("%-6d %26s %26s"
              % (n, "%3d of %3d  (%3.0f%%)" % (c[0], c[1], 100.0 * c[0] / c[1]) if c[1] else "-",
                 "%3d of %3d  (%3.0f%%)" % (f[0], f[1], 100.0 * f[0] / f[1]) if f[1] else "-"))
    tc = [sum(tab[n]["ceil"][i] for n in tab) for i in (0, 1)]
    tf = [sum(tab[n]["floor"][i] for n in tab) for i in (0, 1)]
    print("%-6s %26s %26s" % ("all", "%3d of %3d  (%3.0f%%)" % (tc[0], tc[1], 100.0 * tc[0] / tc[1]),
                              "%3d of %3d  (%3.0f%%)" % (tf[0], tf[1], 100.0 * tf[0] / tf[1])))
    print("\n  the ceil exceptions, and whether the production stage recovered the cell:")
    for r in sorted(fails, key=lambda x: (x["size"], x["cell"])):
        print("    n%-4d %-6s %-20s in %ss | decode ok %s | production ceil stage verified: %s%s"
              % (r["size"], r["cell"], r["retime"], r["secs"], r["decode_ok"], r["stage_verified"],
                 (" (obj %.3f)" % r["stage_obj"]) if r["stage_obj"] else ""))
    if fails and all(r["stage_verified"] for r in fails):
        print("    every failing cell has a verified ceil solution from the production stage, so the direction")
        print("    is not what failed: the master carries no vessel variables and re-timing includes them.")
    out = dict(by_size=rows, totals=dict(ceil_ok=tc[0], ceil_n=tc[1], floor_ok=tf[0], floor_n=tf[1]),
               ceil_exceptions=fails)
    p = os.path.join(ROOT, "runs", "oracle", "tep_retime_by_direction.json")
    json.dump(stamped(out), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
