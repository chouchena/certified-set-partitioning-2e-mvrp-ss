"""Harvest the verified master-IP solutions that were never banked. (d582)

WHAT HAPPENED. `master_ip` decodes its selection, re-times it exactly and verifies it with verifier3,
and stores the whole solution inside the bound artifact under `ip.solution`. Every primal reader in
the project looks in `runs/postpass/<stage>/ownwater_*.json` and nowhere else. So a verified solution
produced by the bound run is invisible to the pipeline that is supposed to keep the best one, and 31
of them are better than the incumbent their cell currently reports -- by up to 7.34 per cent
(RC208 at |C| = 100, 3585.471 against 3322.251).

This is the second instance today of the same failure: a valid result on disk that no reader picks
up. The first was the ng-route certificates (d559). The lesson recorded there applies here -- a
reader that enumerates a hand-written list of places will miss whatever is written somewhere new.

WHAT THIS DOES. For every `_ip` artifact carrying a verified solution, compare against the banked
best for that cell and size, and where it is better by more than K's published precision:

  1. RE-VERIFY FROM THE STORED SOLUTION, not from the stored flag. verifier3 recomputes the
     objective and every constraint; anything that does not reproduce is refused and printed.
  2. Refuse a solution below an optimum K PROVE -- that is a defect, not a win.
  3. Refuse a solution below our own certified lower bound for the cell, which would mean one of
     the two is wrong.
  4. Bank the survivor under `runs/postpass/masterip/`, carrying the source artifact, the rounding
     direction it came from, the objective it supersedes and the seconds the IP spent.

Nothing is recomputed: this reads what the grid already paid for.

    python analysis/tep_harvest_master_ip.py --dry-run
    python analysis/tep_harvest_master_ip.py
"""
import argparse
import glob
import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from bound_certificate import bound_class
from k_comparison import k_best_incumbent, k_proximity
from stamp import stamped

DIRS = ("", "ceil", "selchain", "forced", "refine", "alns", "masterip")
TOL = 0.05          # K publish one decimal; a difference below this is not a difference
DST = os.path.join(ROOT, "runs", "postpass", "masterip")


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def banked_best(cell, size):
    best = None
    for sub in DIRS:
        d = load(os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, size)))
        if d and (best is None or float(d["objVal"]) < best[0]):
            best = (float(d["objVal"]), sub or "floor")
    return best


def our_bound(cell, size):
    """The best CERTIFIED bound for the cell, composed; a solution below it would be a contradiction."""
    best = None
    pats = ["tep_cg_bound_%s_n%d*.json" % (cell, size)] if size != 100 else \
           ["tep_cg_bound_%s*.json" % cell, "tep_easy_reduction_%s_n100_k*.json" % cell]
    for pat in pats:
        for p in glob.glob(os.path.join(ROOT, "runs", "oracle", pat)):
            d = load(p)
            if not d or (d.get("size") or 100) != size or not bound_class(d):
                continue
            v = d.get("composed") if d.get("composed") is not None else d.get("lp_composed")
            if v is not None and (best is None or float(v) > best):
                best = float(v)
    return best


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    cand = {}
    # The cut-at-the-tail smoke also produces verified master-IP solutions and exposes the better
    # of its two arms under the same `ip` key, so it harvests through this same path and the same
    # three refusals. Added after RC208 n30 gained 10.81 with the cut and had nowhere to go (d588).
    pats = ("tep_cg_bound_*_ip*.json", "tep_cut_tail_smoke_*.json")
    for p in sorted(sum([glob.glob(os.path.join(ROOT, "runs", "oracle", x)) for x in pats], [])):
        d = load(p)
        ip = (d or {}).get("ip")
        if not isinstance(ip, dict) or not ip.get("verified") or not ip.get("solution") or not ip.get("objVal"):
            continue
        key = (d.get("cell"), d.get("size") or 100)
        if key not in cand or ip["objVal"] < cand[key][0]["objVal"]:
            cand[key] = (ip, os.path.basename(p), bool(d.get("primal_rounding")))
    print("HARVEST: verified master-IP solutions against the banked incumbent\n")
    print("%-6s %5s %12s %12s %8s %-9s %s" % ("cell", "size", "banked", "IP", "gain", "source", "verdict"))
    banked, refused, rows = 0, 0, []
    for (cell, size), (ip, art, is_ceil) in sorted(cand.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        bb = banked_best(cell, size)
        if not bb or ip["objVal"] >= bb[0] - TOL:
            continue
        sol = ip["solution"]
        inst = V.load_instance(cell, size, k_proximity(size))
        run = V.verify_solution(inst, sol, cell=cell, size=size, proximity=k_proximity(size), label="harvest")
        bad = [x for x in run.findings if x.severity != "TOLERANCE"]
        rec = run.objective.get("recomputed")
        why = None
        if bad or run.blocking:
            why = "verifier3 rejects it (%d finding(s))" % len(bad)
        elif rec is None or abs(float(rec) - float(sol["objVal"])) > 1e-6:
            why = "objective does not reproduce (%s vs %s)" % (rec, sol.get("objVal"))
        else:
            kb, _ = k_best_incumbent(cell, size)
            kt = load(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json")) or {}
            prov = {r["cell"]: r for r in (kt.get("n%d" % size) or {}).get("rows", [])}
            if kb and prov.get(cell, {}).get("proven") and sol["objVal"] < kb - TOL:
                # the guard is on the enclosing `if`, which G23 cannot see; keeping it on the same
                # expression costs nothing and keeps the check honest rather than suppressed
                why = "BELOW a proven optimum (%s) -- a defect, not a win" % (("%.3f" % kb) if kb else "?")
            else:
                lb = our_bound(cell, size)
                if lb is not None and sol["objVal"] < lb - 1e-6:
                    why = "below our own certified bound %.3f -- one of the two is wrong" % lb
        gain = 100.0 * (1 - sol["objVal"] / bb[0])
        if why:
            refused += 1
            print("%-6s %5d %12.3f %12.3f %7.2f%% %-9s REFUSED: %s" % (cell, size, bb[0], sol["objVal"], gain, bb[1], why))
            rows.append(dict(cell=cell, size=size, banked=bb[0], ip=sol["objVal"], gain_pct=gain, refused=why, source=art))
            continue
        print("%-6s %5d %12.3f %12.3f %7.2f%% %-9s %s" % (cell, size, bb[0], sol["objVal"], gain, bb[1],
                                                          "banked" if not a.dry_run else "would bank"))
        rows.append(dict(cell=cell, size=size, banked=bb[0], ip=sol["objVal"], gain_pct=gain, source=art,
                         rounding=("ceil" if is_ceil else "floor"), refused=None))
        banked += 1
        if a.dry_run:
            continue
        if not os.path.isdir(DST):
            os.makedirs(DST)
        out = dict(sol)
        out["size"] = size; out["_proximity"] = k_proximity(size); out["_verified"] = True
        out["selection"] = "master-ip(%s)" % ("ceil" if is_ceil else "floor")
        out["superseded_objVal"] = bb[0]; out["superseded_from"] = bb[1]
        out["secs"] = ip.get("ip_secs"); out["source_artifact"] = art
        out["stage_detail"] = dict(ip_status=ip.get("ip_status"), ip_gap=ip.get("ip_gap"),
                                   ip_bound=ip.get("ip_bound"), rounding=("ceil" if is_ceil else "floor"))
        json.dump(stamped(out, "analysis/tep_harvest_master_ip.py"),
                  io.open(os.path.join(DST, "ownwater_%s_n%d.json" % (cell, size)), "w", encoding="utf-8"),
                  indent=1, default=str)
    print("\n  %d solution(s) %s, %d refused" % (banked, "would be banked" if a.dry_run else "banked under runs/postpass/masterip/", refused))
    p = os.path.join(ROOT, "runs", "oracle", "tep_harvest_master_ip.json")
    json.dump(stamped(dict(rows=rows, banked=banked, refused=refused, dry_run=bool(a.dry_run))),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
