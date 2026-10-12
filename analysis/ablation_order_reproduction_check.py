"""Does the PATCHED code reproduce the banked drop sets exactly, on all 27 n20 cells?

The banked `easiness` artifacts were produced BEFORE --selection existed, so their
code_hash differs from the arms'. That is a provenance gap: it must be CLOSED BY
MEASUREMENT, not by reading the diff and asserting the branch is a no-op.

Each banked record stores drop = sorted(order[:k]). Recompute `order` with the patched
code and check every record of every cell. No solver runs.
"""
import sys, json, glob, os
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.easy_reduction import scarcity_and_weights, easiness

cells = "C201,C202,C203,C204,C205,C206,C207,C208,R201,R202,R203,R204,R205,R206,R207,R208,R209,R210,R211,RC201,RC202,RC203,RC204,RC205,RC206,RC207,RC208".split(",")
bad, checked, norec = [], 0, []
for c in cells:
    f = f"crossfeed/easy_reduction_descend_{c}_n20.json"
    rows = json.load(open(f))
    p = build(c, 20, wls=0.1, tau="formula", proximity=0.0, time_limit=1800)
    s, w, ctx = scarcity_and_weights(p)
    order = sorted(easiness(ctx, w), key=lambda x: -easiness(ctx, w)[x])
    n = 0
    for r in rows:
        if "drop" not in r or "k" not in r:
            continue
        if sorted(order[:r["k"]]) != sorted(r["drop"]):
            bad.append((c, r["k"], sorted(order[:r["k"]]), sorted(r["drop"])))
        n += 1; checked += 1
    if n == 0:
        norec.append(c)
    print(f"{c:7s} records={n:3d} {'MISMATCH' if any(b[0]==c for b in bad) else 'ok'}")

print(f"\nrecords checked: {checked} over {len(cells)} cells")
print(f"cells with no comparable record: {norec or 'none'}")
print(f"MISMATCHES: {len(bad)}")
for b in bad[:10]:
    print("  ", b)
print("VERDICT:", "PASS - patched code reproduces every banked drop set" if not bad else "FAIL - DO NOT LAUNCH")
