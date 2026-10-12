"""Scope the unproven-cell sample for the coarse-grain harvested sweep: read the oracle best_of
files per n, report proven/unproven counts per family, and list the unproven cells (= LB solver
still has value). Prints only."""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fam(cell):
    return "RC" if cell.startswith("RC") else cell[0]


for size in (100, 50, 30, 20):
    p = os.path.join(ROOT, "runs", "oracle", "tep_n%d_best_of.json" % size)
    if not os.path.exists(p):
        print("n%-3d : (no best_of file)" % size); continue
    rows = json.load(io.open(p, encoding="utf-8"))["rows"]
    byfam = {}
    unproven = []
    for r in rows:
        f = fam(r["cell"])
        d = byfam.setdefault(f, [0, 0])
        if r.get("proven"):
            d[0] += 1
        else:
            d[1] += 1
            unproven.append(r["cell"])
    tot = len(rows); up = sum(d[1] for d in byfam.values())
    fam_s = " ".join("%s:%d/%d" % (f, byfam[f][1], byfam[f][0] + byfam[f][1]) for f in sorted(byfam))
    print("n%-3d : %2d cells, %2d unproven  [unproven/total per fam: %s]" % (size, tot, up, fam_s))
    print("        unproven: %s" % " ".join(unproven))
