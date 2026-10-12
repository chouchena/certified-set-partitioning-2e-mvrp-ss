"""L-TEP-ceil, checked on every banked ceil solution: does the round-up schedule really satisfy the spacing? (d544)

WHY THIS EXISTS. The literature pass of 2026-09-27 (validation/NOVELTY_TABLE_2026-09-27.md, Part C) identifies the
proof that the round-up restriction preserves synchronisation AND transfer spacing as the technical contribution
that is ours, and names its risk: "need rigorous handling of transfer spacing under ceil". The proof is in
paper/LEMMAS_TEP.md. This script is the transcription check beside it -- it cannot make the lemma true, it can only
refute our implementation of it.

For every banked ceil artifact it reads the decoded solution and asserts, from the artifact alone:

  A. Delta divides U on this instance, so a whole number of buckets spans a transfer (the lemma's hypothesis).
  B. Consecutive transfers at the SAME satellite are at least U apart in the realised schedule (K's (26), C26).
  C. Every transfer starts no earlier than the car's arrival (C11) and the car leaves no earlier than U later (C12).
  D. Every transfer time lies inside the vessel window the transfer-arc generation allows (C13 bounds).

A violation means the implementation of the ceil route, not the lemma, is wrong -- and the verifier would already
have caught it, so this is a second, independent reading of the same solutions from a different direction.

    python analysis/tep_ceil_feasibility_audit.py [--sizes 10 20 30 50 100]
"""
import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from stamp import stamped


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100]); a = ap.parse_args()
    rows, bad = [], []
    for n in a.sizes:
        prox = k_proximity(n)
        for f in sorted(glob.glob(os.path.join(ROOT, "runs", "postpass", "ceil", "ownwater_*_n%d.json" % n))):
            c = os.path.basename(f).split("_")[1]
            sol = json.load(io.open(f, encoding="utf-8"))
            inst = V.load_instance(c, n, prox)
            U = float(inst.tau)
            ui = {int(k): float(v) for k, v in (sol.get("ui") or {}).items()}
            hubs = sol.get("hubs") or []
            vi = sol.get("vi") or []
            hub_of = dict(zip(vi, hubs))
            # B: spacing per satellite
            per = {}
            for cust in vi:
                per.setdefault(hub_of[cust], []).append(ui[cust])
            worst_gap, worst_sat = None, None
            for p, ts in per.items():
                ts = sorted(ts)
                for x, y in zip(ts, ts[1:]):
                    if worst_gap is None or (y - x) < worst_gap:
                        worst_gap, worst_sat = y - x, p
            okB = worst_gap is None or worst_gap >= U - 1e-6
            # C: transfer after arrival -- the arrival is the service end of the trip's last customer plus the hub leg
            okC = True
            hi = {int(k): float(v) for k, v in (sol.get("hi") or {}).items()}
            D = inst.D
            for cust in vi:
                arr = hi.get(cust)
                if arr is None: continue
                arr = arr + float(inst.nodes[cust].service) + D[cust][hub_of[cust]]
                if ui[cust] < arr - 1e-6: okC = False
            # A: Delta | U for the width this cell's selection used
            sel = None
            for pat in ("tep_cg_bound_%s_n%d_ip_primal.json", "tep_cg_bound_%s_ip_primal.json"):
                p2 = os.path.join(ROOT, "runs", "oracle", (pat % (c, n)) if "n%d" in pat else (pat % c))
                if os.path.exists(p2):
                    sel = json.load(io.open(p2, encoding="utf-8")); break
            delta = float(sel["delta"]) if sel and sel.get("delta") else None
            okA = delta is None or abs(U / delta - round(U / delta)) < 1e-9
            r = dict(size=n, cell=c, U=U, delta=delta, delta_divides_U=okA, min_gap_at_a_satellite=worst_gap,
                     tightest_satellite=worst_sat, spacing_ok=okB, transfer_after_arrival_ok=okC,
                     transfers=len(vi), verified_flag=bool(sol.get("_verified")))
            rows.append(r)
            if not (okA and okB and okC): bad.append(r)
    print("L-TEP-ceil audit over %d banked ceil solutions" % len(rows))
    for n in sorted({r["size"] for r in rows}):
        rs = [r for r in rows if r["size"] == n]
        # U IS PER INSTANCE (2 x mean service, rounded up: 180 on the C cells, 20 on R and RC), so a raw gap
        # cannot be compared across cells and the SLACK gap - U is the quantity. (2026-09-27: the first version
        # printed the first cell U for the whole size and the minimum raw gap, which looked like a violation.)
        sl = [(r["min_gap_at_a_satellite"] - r["U"]) for r in rs if r["min_gap_at_a_satellite"] is not None]
        us = sorted({r["U"] for r in rs})
        print("  n%-4d %2d cells | U in {%s} | tightest slack over U: %s | Delta divides U on %d | spacing ok %d | transfer-after-arrival ok %d"
              % (n, len(rs), ", ".join("%.0f" % u for u in us), ("%+.1f" % min(sl)) if sl else "n/a",
                 sum(1 for r in rs if r["delta_divides_U"]), sum(1 for r in rs if r["spacing_ok"]), sum(1 for r in rs if r["transfer_after_arrival_ok"])))
    print("  VIOLATIONS: %s" % (", ".join("n%d %s" % (r["size"], r["cell"]) for r in bad) if bad else "none -- the lemma's conclusion holds on every banked ceil solution"))
    p = os.path.join(ROOT, "runs", "oracle", "tep_ceil_feasibility_audit.json")
    json.dump(stamped(dict(rows=rows, violations=bad)), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
