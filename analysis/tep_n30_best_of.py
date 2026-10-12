"""n30 per instance, taking the better of our two rounding configurations. (d459)

WHAT IS AND IS NOT BEING CLAIMED. Floor and ceil are two configurations of the SAME formulation and
the same three-stage route; both produce solutions verified by verifier3. Running both and keeping
the cheaper is an ordinary configuration choice, not a hybrid method and not a new model. It is
reported as such, and both legs are charged against the runtime envelope.

WHY BOTH ARE NEEDED, from tonight's grid: ceil rounding is a RESTRICTION (d414), so where the floor
route already found a two-car solution ceil can only match or lose it, and it loses by 0.2 to 4.9%.
Where the floor route was stuck on an extra car, ceil removes it and wins 12 to 17%. Neither
dominates, which is exactly why the choice is per cell.

`tep_n30_table.py` remains the record of the floor route alone and is not superseded by this file.

    python analysis/tep_n30_best_of.py
"""
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from k_comparison import k_best_incumbent
from stamp import stamped
from bound_certificate import certified, ng_certified, best_valid   # d519: readers require a certificate, not the flag;
# ng_certified is the second, weaker class added 2026-09-27 and it is always reported as its own class

import argparse as _ap
_p = _ap.ArgumentParser(add_help=False); _p.add_argument("--size", type=int, default=30, choices=(10, 20, 30, 50, 100))
SIZE = _p.parse_known_args()[0].size   # 2026-09-26: generalised from a hard-coded 30 so n10/n20 per-cell tables have generating code too


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    _kts = json.load(io.open(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json"), encoding="utf-8"))
    kt = {r["cell"]: r for r in _kts["n%d" % SIZE]["rows"]} if ("n%d" % SIZE) in _kts else {}   # n50/n100: K publish no per-cell value (2026-09-27)
    ab = {(r["cell"], r["size"]): r for r in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"),
                                                               encoding="utf-8"))["records"]}
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "runs", "postpass", "ownwater_*_n%d.json" % SIZE))):
        c = os.path.basename(f).split("_")[1]
        cand = []
        srcs = {"floor": f}
        for tag in ("ceil", "selchain", "forced", "refine", "alns", "masterip"):
            srcs[tag] = os.path.join(ROOT, "runs", "postpass", tag, "ownwater_%s_n%d.json" % (c, SIZE))
        got = {}
        for tag, p in srcs.items():
            d0 = load(p)
            if d0:
                got[tag] = d0
                cand.append((tag, float(d0["objVal"]), int(d0["nCars"])))
        if not cand:
            continue
        fl, ce = got.get("floor"), got.get("ceil")
        which_cfg, best, cars = min(cand, key=lambda x: x[1])
        kb, kwhich = k_best_incumbent(c, SIZE)
        # BEST-OF-BOUND (d464 -> grid): the max of valid lower bounds is a valid lower bound. Take the
        # PROVEN LP at the default width and at any finer width that also proved, and record which won.
        # An unproven finer LP is not a bound (the pricer may not have converged) and is never used.
        lb, lb_width, lb_class = None, None, None
        water = float(ab[(c, SIZE)]["water"])
        # TWO CERTIFICATE CLASSES, NEVER POOLED SILENTLY (2026-09-27). `certified` is the elementary
        # proof and is unchanged. `ng_certified` is the weaker, valid one: the ng-route class converged
        # at full length on the true duals with no candidate below the cut, so the LP is that class's
        # optimum and LP(ng) <= LP(elementary) <= OPT. The dual side takes the MAX of valid bounds
        # (settled 2026-09-13), so a cell reports the better of the two and carries the class of the
        # winner. Not refuted on the 43 ng-certified artifacts whose cells K prove optimal: no bound
        # above an optimum, tightest 1.9% below (n20 C201).
        cands_lb = []

        def offer(dd, width):
            if not dd or dd.get("lp_street") is None or dd.get("primal_rounding"):
                return
            k = "elementary" if certified(dd) else ("ng" if ng_certified(dd) else None)
            if k:
                cands_lb.append((float(dd["lp_street"]), width, k))

        # EVERY bound artifact for this cell, not a hand-written list of four names. The list would have
        # missed the integer-car runs (`_ip_intcars.json`) the moment they existed, leaving a valid and
        # much stronger bound on disk and unread -- the same failure as the ng certificates (d559). The
        # width comes from the file name, default 20; offer() still requires a certificate of either
        # class and still refuses the ceil restriction.
        import re as _re
        for f in sorted(glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d*.json" % (c, SIZE)))):
            base = os.path.basename(f)
            if "INVALID" in base or "_primal" in base:
                continue
            m = _re.search(r"_d(\d+)", base)
            offer(load(f), int(m.group(1)) if m else 20)
        if cands_lb:
            # AT EQUAL LP THE ELEMENTARY CERTIFICATE WINS (2026-09-30): max() over these tuples
            # fell through to the class string at a tie, and "ng" > "elementary". One rule for
            # every reader, in bound_certificate.best_valid.
            lp, lb_width, lb_class = best_valid(cands_lb, value=lambda t: t[0], klass=lambda t: t[2])
            lb = lp + water
        rows.append(dict(cell=c, best=best, cfg=which_cfg, cars=cars,
                         floor=(float(fl["objVal"]) if fl else None),
                         ceil=(float(ce["objVal"]) if ce else None),
                         theirs=kb, which=kwhich, proven=bool(kt[c]["proven"]) if c in kt else False,
                         their_lb=(float(kt[c]["k_bound"]) if c in kt else None), our_lb=lb, lb_width=lb_width, lb_class=lb_class))
    if not rows:
        print("nothing to report"); return 1

    print("n%d (27 cells), per instance, best over every production configuration; PROVEN cells are attainment, OPEN cells competition." % SIZE)
    print("'theirs' is the BETTER of their two published methods.\n")
    print("%-7s %9s %6s %5s %9s %9s %8s | %9s %3s %8s | %7s"
          % ("cell", "ours", "cfg", "cars", "floor", "ceil", "vs them", "our LB", "wdt", "vs them", "our gap"))
    below, defect = [], []
    for r in sorted(rows, key=lambda x: x["best"] / x["theirs"] if x["theirs"] else x["best"]):
        d = 100.0 * (r["best"] / r["theirs"] - 1) if r["theirs"] else None
        if d is not None and r["best"] < r["theirs"] - 0.05:
            (defect if r["proven"] else below).append(r["cell"])
        if r["their_lb"] is not None and r["best"] < r["their_lb"] - 0.05:
            defect.append(r["cell"] + "(<their bound)")
        # A LOWER BOUND ABOVE OUR OWN FEASIBLE SOLUTION IS INVALID -- the "relaxation vs feasible"
        # class in CLAUDE.md section 4. Checked ad hoc on 2026-09-26 (0 of 27); now checked every run.
        if r.get("our_lb") is not None and r["our_lb"] > r["best"] + 1e-6:
            defect.append(r["cell"] + "(our LB %.1f > our primal %.1f: INVALID BOUND)" % (r["our_lb"], r["best"]))
        if r["proven"] and r.get("our_lb") is not None and r["our_lb"] > r["theirs"] + 1e-6:
            defect.append(r["cell"] + "(our LB %.1f > their PROVEN optimum %.1f: INVALID BOUND)" % (r["our_lb"], r["theirs"]))
        og = 100.0 * (1 - r["our_lb"] / r["best"]) if r["our_lb"] else None
        print("%-7s %9.1f %6s %5d %9s %9s %8s | %9s %3s %7s | %6s"
              % (r["cell"], r["best"], r["cfg"], r["cars"],
                 ("%.1f" % r["floor"]) if r["floor"] else "-",
                 ("%.1f" % r["ceil"]) if r["ceil"] else "-", ("%+.2f%%" % d) if d is not None else "n/a",
                 ("%.1f" % r["our_lb"]) if r["our_lb"] else "-",
                 ("d%d%s" % (r["lb_width"], "" if r.get("lb_class") == "elementary" else "*")) if r.get("lb_width") else "-",
                 ("%.2fx" % (r["our_lb"] / r["their_lb"])) if (r["our_lb"] and r["their_lb"]) else "-",
                 ("%.1f%%" % og) if og else "-"))
    # PROVEN vs OPEN never pooled (author, 2026-09-26): attainment and competition are different quantities
    pv = [100.0 * (r["best"] / r["theirs"] - 1) for r in rows if r["theirs"] and r["proven"]]
    op = [100.0 * (r["best"] / r["theirs"] - 1) for r in rows if r["theirs"] and not r["proven"]]
    if pv:
        print("\n  PROVEN %d cell(s) -- ATTAINMENT to the optimum: median %+.2f%%, mean %+.2f%%, worst %+.2f%% (%s); within 1%%: %d"
              % (len(pv), st.median(pv), st.mean(pv), max(pv), max((r for r in rows if r["proven"]), key=lambda r: r["best"] / r["theirs"])["cell"], sum(1 for g in pv if g <= 1.0)))
    if op:
        print("  OPEN   %d cell(s) -- COMPETITION: median %+.2f%%, mean %+.2f%%, worst %+.2f%% (%s)"
              % (len(op), st.median(op), st.mean(op), max(op), max((r for r in rows if not r["proven"]), key=lambda r: r["best"] / r["theirs"])["cell"]))
    dd = [100.0 * (r["best"] / r["theirs"] - 1) for r in rows if r["theirs"]] or [0.0]   # n50/n100: no per-cell K, summary line is about coverage only
    haveceil = [r for r in rows if r["ceil"] is not None]
    won = [r for r in haveceil if r["cfg"] == "ceil"]
    print("\n  %d of 27 cells | median %+.2f%%, best %+.2f%%, worst %+.2f%%"
          % (len(rows), st.median(dd), min(dd), max(dd)))
    print("  BELOW their best on %d open cell(s): %s" % (len(below), ", ".join(sorted(below)) if below else "none"))
    print("  ceil is the chosen configuration on %d of %d cells where both ran" % (len(won), len(haveceil)))
    if defect:
        print("  *** DEFECT on %s -- below a PROVEN optimum or a published bound ***" % ", ".join(sorted(set(defect))))
    have = [r for r in rows if r["our_lb"] and not r["proven"]]   # a bracket against a PROVEN optimum is 0 by definition -- bounds only matter on OPEN cells
    if have:
        og = sorted(100.0 * (1 - r["our_lb"] / r["best"]) for r in have)
        # AT n50 AND n100 THE PREDECESSORS PUBLISH NO PER-CELL VALUE, so their side of the bracket does not
        # exist and the comparison is reported one-sided. (2026-09-27: this block divided by None and raised
        # AFTER the table had printed and BEFORE the artifact was written, so stdout showed bounds that never
        # reached disk -- the failure mode CLAUDE.md section 4 calls a stale artifact outliving its headline.)
        both = [r for r in have if r.get("their_lb") and r.get("theirs")]
        tg = sorted(100.0 * (1 - r["their_lb"] / r["theirs"]) for r in both)
        if tg:
            print("  bracket: ours median %.1f%% against theirs %.1f%% (%d cells with both) | finer-width bound used on %d"
                  % (st.median(og), st.median(tg), len(both), sum(1 for r in have if r.get("lb_width") not in (None, 20))))
        else:
            print("  bracket: ours median %.1f%% over %d cells; the predecessors publish no per-cell value at this size"
                  % (st.median(og), len(have)))
        tight = sorted(have, key=lambda r: 1 - r["our_lb"] / r["best"])[:3]
        print("  tightest brackets: %s" % ", ".join("%s %.1f%% (d%s)" % (r["cell"], 100 * (1 - r["our_lb"] / r["best"]), r.get("lb_width")) for r in tight))
    p = os.path.join(ROOT, "runs", "oracle", "tep_n%d_best_of.json" % SIZE)
    json.dump(stamped(dict(size=SIZE, rows=rows)), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
