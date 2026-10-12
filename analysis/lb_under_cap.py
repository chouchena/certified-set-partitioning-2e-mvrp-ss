"""What lower bound is still PROVABLE if the dual leg is capped at T seconds per cell.

WHY (author, 2026-09-29): "state out of these runs the LB minimum provable value if we had
capped the total RT to say 1500s".

THE RULE THAT SHAPES THE ANSWER, and it is not the obvious one. The TEP column-generation value
is NOT truncatable. Its tracked `lp` falls toward the true LP FROM ABOVE, so every intermediate
value is an upper bound on the relaxation, not a lower bound on the problem (d427). Capping it
therefore does not buy a weaker bound -- it buys NO bound from that instrument. Fit or drop.

The other two behave differently and that is the whole story:
  AB4      0.023 s median. Always fits. Needs no certificate.
  descent  its dual bound is valid AT ANY TRUNCATION POINT (easy_reduction_bound_proof step 0:
           CPLEX best_bound is valid for a minimisation at any truncation). So in principle a
           partial descent still yields a bound -- but WE DID NOT RECORD ITS TRAJECTORY, only
           its final value and its wall. So this file can only say whether the descent FITS; it
           cannot say what a truncated descent would have returned. That is a measurement gap,
           stated rather than papered over with an assumption.

TWO READINGS of "total RT", both reported because they differ a lot:
  A  the cap applies to the TEP CG run only (descent already banked, charged separately)
  B  the cap applies to the WHOLE LB leg -- descent + TEP + AB4 -- which is what the envelope
     rule actually charges (d245/d246/d250)

Under both, the reported value is max over the instruments that FIT. Nothing is extrapolated.

    python analysis/lb_under_cap.py --caps 600 1500 3600
"""
import argparse
import collections
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
from stamp import stamped


def load(p):
    return json.load(io.open(os.path.join(ROOT, "runs", "oracle", p), encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caps", nargs="*", type=float, default=[1500.0])
    a = ap.parse_args()

    grid = {(r["cell"], r["size"]): r for r in load("lb_grid.json")["rows"]}
    prof = {(r["cell"], r["size"]): r for r in load("lb_time_profile.json")["rows"]}

    print("LOWER BOUND STILL PROVABLE UNDER A PER-CELL DUAL CAP\n")
    print("  The TEP value is fit-or-drop: an unconverged master's LP is an upper bound on the")
    print("  relaxation, so a truncated CG run yields NO bound, not a smaller one.\n")
    out = []
    for cap in a.caps:
        for reading, label in (("A", "cap on the TEP CG run only"),
                               ("B", "cap on the whole LB leg (descent + TEP + AB4)")):
            rows = []
            for k, g in sorted(grid.items()):
                p = prof.get(k)
                tep_s = (p or {}).get("total_s")
                if tep_s is None:
                    tep_s = g.get("solver_s")
                desc_s, ab_s = g.get("descent_s") or 0.0, g.get("ab4_s") or 0.0
                if reading == "A":
                    tep_fits = tep_s is not None and tep_s <= cap
                    desc_fits = True                      # already banked, charged elsewhere
                else:
                    # AB4 first (it is free), then descent, then TEP with what is left
                    rem = cap - ab_s
                    desc_fits = desc_s <= rem
                    rem -= desc_s if desc_fits else 0.0
                    tep_fits = tep_s is not None and tep_s <= rem
                live = {"ab4": g.get("ab4")}
                if desc_fits:
                    live["descent"] = g.get("descent")
                if tep_fits:
                    live["tep"] = g.get("solver")
                live = {n: v for n, v in live.items() if v is not None}
                val = max(live.values()) if live else None
                who = max(live, key=live.get) if live else None
                rows.append(dict(cell=k[0], size=k[1], cap=cap, reading=reading,
                                 capped_value=val, capped_carrier=who,
                                 uncapped_value=g.get("reported"),
                                 uncapped_carrier=g.get("carrier"),
                                 tep_fits=bool(tep_fits), descent_fits=bool(desc_fits),
                                 tep_s=tep_s, descent_s=desc_s, ab4_s=ab_s,
                                 loss=(None if val is None or g.get("reported") is None
                                       else g["reported"] - val)))
            ok = [r for r in rows if r["capped_value"] is not None]
            lost = [r for r in ok if r["loss"] and r["loss"] > 1e-6]
            keptfull = len(ok) - len(lost)
            print("  cap %5.0f s  reading %s -- %s" % (cap, reading, label))
            print("     cells with a bound %3d/135 | unchanged %3d | weaker %3d | TEP survives %3d"
                  % (len(ok), keptfull, len(lost), sum(1 for r in rows if r["tep_fits"])))
            if lost:
                rel = [100.0 * r["loss"] / r["uncapped_value"] for r in lost]
                print("     loss on the weakened cells: median %.1f (%.1f%%)  max %.1f (%.1f%%)"
                      % (statistics.median([r["loss"] for r in lost]), statistics.median(rel),
                         max(r["loss"] for r in lost), max(rel)))
            for r in sorted(lost, key=lambda x: -(x["loss"] or 0))[:6]:
                print("        %-7s n%-4d %8.1f -> %8.1f  (%+.1f)  carrier %s -> %s   "
                      "tep %s s %s"
                      % (r["cell"], r["size"], r["uncapped_value"], r["capped_value"],
                         -r["loss"], r["uncapped_carrier"], r["capped_carrier"],
                         ("%.0f" % r["tep_s"]) if r["tep_s"] else "-",
                         "fits" if r["tep_fits"] else "DROPPED"))
            bysize = collections.Counter(r["size"] for r in lost)
            if bysize:
                print("     weakened by size: %s" % dict(sorted(bysize.items())))
            tot_un = sum(r["uncapped_value"] for r in ok if r["uncapped_value"])
            tot_cap = sum(r["capped_value"] for r in ok)
            print("     grid total: %.0f capped against %.0f uncapped (%.2f%% of the bound kept)"
                  % (tot_cap, tot_un, 100.0 * tot_cap / tot_un if tot_un else 0))
            # the wall must follow the READING: under A the descent is not capped, under B the
            # whole leg is. The first version used one formula for both and so reported
            # reading B's wall twice.
            if reading == "A":
                secs = sum((r["descent_s"] or 0) + (r["ab4_s"] or 0)
                           + (min(cap, r["tep_s"]) if r["tep_s"] else 0) for r in rows)
            else:
                secs = sum(min(cap, (r["descent_s"] or 0) + (r["tep_s"] or 0)
                               + (r["ab4_s"] or 0)) for r in rows)
            print("     dual wall under the cap: %.1f h against 58.5 h charged today\n"
                  % (secs / 3600.0))
            out += rows

    p = os.path.join(ROOT, "runs", "oracle", "lb_under_cap.json")
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(stamped(dict(rows=out, caps=a.caps), "analysis/lb_under_cap.py",
                          "analysis/lb_grid.py", "analysis/lb_time_profile.py"),
                  f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
