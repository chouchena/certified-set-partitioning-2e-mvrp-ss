"""Per-cell v2 full-leg comparison -- RT / LB / derived OV vs v1 banked and K's BK.
Run SINGLE-TENANT (after the solve python has exited), so it does not perturb a citable run."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from k_comparison import k_best_incumbent

cell = sys.argv[1]
size = int(sys.argv[2]) if len(sys.argv) > 2 else 100


def rec(tag):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n%d.json" % (tag, cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d])
    return r[0] if isinstance(r, list) else r


def ov(handoff):
    p = os.path.join(ROOT, "handoff", handoff)
    if not os.path.exists(p):
        return None
    h = json.load(open(p, encoding="utf-8"))
    return h.get("ov") if isinstance(h, dict) else None


v1 = rec("frzdual"); v2 = rec("frzdual2")
v1_ov = ov("dualinc_%s_n%d.json" % (cell, size)); v2_ov = ov("dualinc2_%s_n%d.json" % (cell, size))
import k_comparison as K
FAM = "RC" if cell.startswith("RC") else cell[0]
kinc = None
try:
    v = k_best_incumbent(cell, size)
    kinc = v[0] if isinstance(v, (tuple, list)) else v
except Exception:
    pass
kinc_fam = klb_fam = None
if kinc is None:   # K publishes NO per-instance incumbent at n>=50; use the Table-6 FAMILY mean
    try:
        row = K._kref()["table6"][FAM]
        kinc_fam = min(row["joint"]["zIP"], row["lbbd"]["zIP"])
        klb_fam = row["joint"]["zIP"] * (1.0 - row["gap_joint"] / 100.0)
    except Exception:
        pass


def g(d, k):
    return (d.get(k) if d else None)


def pct(a, b):
    return ("%+.1f%%" % (100.0 * (a / b - 1.0))) if (a and b) else "n/a"


print("=== V2 full-leg vs v1(banked) vs BK | %s n%d ===" % (cell, size))
print("  LB(certified) : v2=%s cert=%s | v1=%s cert=%s(AB4) | v2 vs v1 %s"
      % (g(v2, "lb"), g(v2, "certificate"), g(v1, "lb"), g(v1, "certificate"), pct(g(v2, "lb"), g(v1, "lb"))))
print("  derived OV    : v2=%s | v1=%s | per-cell BK=%s" % (v2_ov, v1_ov, kinc))
if kinc_fam is not None:
    print("  vs K FAMILY-%s mean (no per-cell at n>=50): K_inc=%.1f (v2 OV %s) | K_LB=%.1f (v2 LB %s)"
          % (FAM, kinc_fam, pct(v2_ov, kinc_fam), klb_fam, pct(g(v2, "lb"), klb_fam)))
if g(v2, "lb") and v2_ov:
    print("  v2 gap (OV-LB)/LB = %.1f%%" % (100.0 * (v2_ov - v2["lb"]) / v2["lb"]))
print("  RT(full leg)  : v2=%ss | v1=%ss | %s"
      % (g(v2, "wall_s"), g(v1, "wall_s"), pct(g(v2, "wall_s"), g(v1, "wall_s"))))
print("  fast_pricer stamp: %s" % g(v2, "fast_pricer"))
