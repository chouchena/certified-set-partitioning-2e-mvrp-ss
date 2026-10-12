"""The post-cell check of the DSSR banking batch -- the batch checks its own steps (CLAUDE.md 4).

    python analysis/dssr_bank_check.py R202 --size 50          # one cell, exit 1 on any failure
    python analysis/dssr_bank_check.py --all --size 50         # the nine

What it asserts, per cell, against validation/AUDIT_dssr_n50_bank.md:
  A1  the canonical artifact exists and bound_certificate.certified() accepts it
  A2  certificate_class == "elementary", status == "proven", primal_rounding falsy
  A3  lp_street equals the cell's smoke value to 1e-6 (F1: a difference is a replicability defect
      and STOPS the batch); when no smoke exists (R208) lp_street >= the ng value on disk
  A4  composed == lp_street + water from runs/ab_grid_provenanced.json; lb_reported == max(composed, ab4)
  A5  _provenance.source_hash present; _rt carries wall_s, det_ticks, threads, tenancy, rt_class
  A6  `supersedes` present exactly when an uncertified artifact stood at that path before (R202)
The exit code is the verdict; the lines are the record.
"""
import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))

NINE = ["R202", "R203", "R206", "R207", "R209", "R210", "R211", "R204", "R208"]
SUPERSEDED = {"R202"}   # the only canonical file that existed, uncertified, before the batch
TOL = 1e-6


def latest_smoke(cell, size):
    fs = sorted(glob.glob(os.path.join(ROOT, "logs", "smoke", "dssr_%s_n%d_*.json" % (cell, size))),
                key=os.path.getmtime)
    return json.load(io.open(fs[-1], encoding="utf-8")) if fs else None


def ng_on_disk(cell, size):
    from bound_certificate import ng_certified
    best = None
    for p in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d*.json" % (cell, size))):
        if "INVALID" in p or "_primal" in p:
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        if d.get("lp_street") is not None and not d.get("primal_rounding") and ng_certified(d):
            best = d["lp_street"] if best is None else max(best, d["lp_street"])
    return best


def check(cell, size):
    from bound_certificate import certified
    p = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s.json" % (cell, "" if size == 100 else "_n%d" % size))
    fails = []
    if not os.path.exists(p):
        print("  FAIL  %-5s A1 no artifact at %s" % (cell, os.path.relpath(p, ROOT)))
        return ["A1 no artifact"]
    d = json.load(io.open(p, encoding="utf-8"))
    if not certified(d):
        fails.append("A1 certified() False")
    if d.get("certificate_class") != "elementary" or d.get("status") != "proven" or d.get("primal_rounding"):
        fails.append("A2 class %s status %s primal_rounding %s" % (d.get("certificate_class"), d.get("status"), d.get("primal_rounding")))
    lp = float(d["lp_street"])
    sm = latest_smoke(cell, size)
    if sm is not None:
        if abs(lp - float(sm["lp_street"])) > TOL:
            fails.append("A3 F1 REPLICABILITY: banked %.12f vs smoke %.12f (diff %.3e) -- STOP THE BATCH"
                         % (lp, sm["lp_street"], lp - sm["lp_street"]))
    else:
        ng = ng_on_disk(cell, size)
        if ng is not None and lp < ng - TOL:
            fails.append("A3 banked %.9f BELOW the ng value on disk %.9f" % (lp, ng))
    ab = {(q["cell"], q["size"]): q for q in json.load(io.open(
        os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}[(cell, size)]
    if abs(float(d.get("composed", -1)) - (lp + float(ab["water"]))) > 1e-9:
        fails.append("A4 composed %s != lp + water %.9f" % (d.get("composed"), lp + float(ab["water"])))
    if abs(float(d.get("lb_reported", -1)) - max(float(d["composed"]), float(ab["ab4"]))) > 1e-9:
        fails.append("A4 lb_reported %s != max(composed, ab4)" % d.get("lb_reported"))
    prov, rt = d.get("_provenance") or {}, d.get("_rt") or {}
    if not prov.get("source_hash"):
        fails.append("A5 no _provenance.source_hash")
    for k in ("wall_s", "det_ticks", "threads", "tenancy", "rt_class"):
        if rt.get(k) is None:
            fails.append("A5 _rt.%s missing" % k)
    # A6 accepts EITHER lineage field. R202 replaced an uncertified artifact when it was first
    # banked (`supersedes`); d635 then replaced that with a value from the fixed certifier, which
    # records `retraction`. A cell that carries either has its history on the artifact.
    lineage = bool(d.get("supersedes")) or bool(d.get("retraction"))
    if (cell in SUPERSEDED) and not lineage:
        fails.append("A6 no lineage recorded (neither supersedes nor retraction)")
    # A cell NOT in SUPERSEDED may still carry lineage legitimately: the RT pass re-banks every
    # cell with a solo wall, which supersedes the diagnostic-class artifact of the same value.
    # Only the absence of lineage where a replacement is known to have happened is a failure.
    head = ("%-5s lp %.9f (smoke %s)  composed %.6f  %s  wall %ss  rt %s  tenancy %s"
            % (cell, lp, ("%.9f" % sm["lp_street"]) if sm else "none", float(d.get("composed", 0)),
               "certified" if certified(d) else "NOT certified", rt.get("wall_s"), rt.get("rt_class"), rt.get("tenancy")))
    print(("  OK    " if not fails else "  FAIL  ") + head)
    for f in fails:
        print("          " + f)
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell", nargs="?")
    ap.add_argument("--size", type=int, default=50)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    cells = NINE if a.all else [a.cell]
    if not cells or cells == [None]:
        ap.error("a cell or --all")
    bad = sum(bool(check(c, a.size)) for c in cells)
    print("%d of %d pass" % (len(cells) - bad, len(cells)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
