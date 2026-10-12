"""Necessary check for every proven TEP CG bound (TEP_cg_bound_27cells.md section 2): the LP
street part must not exceed the street part (FleetStreet + TravelStreet, i.e. car penalty plus
street travel) of ANY verified banked n100 solution of the cell. One violation refutes the
implementation on that cell. Scans the same directories as bks_n100.py.

    python analysis/cg_necessary_check.py
"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import bks_n100 as B


def min_street_parts():
    out = {}
    for d in B.DIRS:
        for f in glob.glob(os.path.join(ROOT, d, "*.json")):
            base = os.path.basename(f)
            m = re.search(r"(RC|R|C)(2\d\d)", base)
            if not m:
                continue
            cell = m.group(1) + m.group(2)
            try:
                a = json.load(io.open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(a, dict) or a.get("FleetStreet") is None or a.get("TravelStreet") is None:
                continue
            size = a.get("size") or a.get("_size") or (100 if "n100" in base else None)
            if size != 100:
                continue
            v = a.get("_verifier")
            verified = ((a.get("_verifier_recomputed") is not None) or (a.get("verify") == "PASS") or (a.get("_verify") == "PASS")
                        or (isinstance(v, str) and v.startswith("verifier3")))
            if base.startswith("chain_") and d == "analysis":
                probe = B.PROBE.get(cell) or {}
                verified = probe.get("verify") == "PASS" and abs(float(probe.get("s2_obj", -1)) - float(a["objVal"])) < 1e-6
            if not verified:
                continue
            sp = float(a["FleetStreet"]) + float(a["TravelStreet"])
            if cell not in out or sp < out[cell][0]:
                out[cell] = (sp, os.path.relpath(f, ROOT).replace("\\", "/"), int(a.get("nCars", -1)))
    return out


def main():
    mins = min_street_parts()
    bad = 0; n = 0
    print("%-6s %10s %10s %6s  %s" % ("cell", "cg_street", "min_banked", "ok", "cheapest banked (cars)"))
    for c in B.CELLS:
        f = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s.json" % c)
        if not os.path.exists(f):
            continue
        r = json.load(io.open(f, encoding="utf-8"))
        if not r.get("proven"):
            print("%-6s %10.1f %10s %6s  unproven (%s)" % (c, r["lp_street"], "-", "-", r.get("status"))); continue
        n += 1
        mb = mins.get(c)
        if mb is None:
            print("%-6s %10.1f %10s %6s  no verified banked solution with a street split" % (c, r["lp_street"], "-", "?")); continue
        ok = r["lp_street"] <= mb[0] + 1e-6
        bad += 0 if ok else 1
        print("%-6s %10.1f %10.1f %6s  %s (%d)" % (c, r["lp_street"], mb[0], "OK" if ok else "VIOLATION", mb[1], mb[2]))
    print("\n%d proven bounds checked, %d violations%s" % (n, bad, " -- IMPLEMENTATION REFUTED on those cells" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
