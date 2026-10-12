"""IN-FLIGHT status of S2g, under its own pre-committed reporting rule.

PREREG_S2g_p2_coverage sec 4.1 commits, BEFORE the run, to:
  * report each cell's median WITH its win count (e.g. "4/6")
  * treat any cell at 2/6-4/6 as UNRESOLVED, not as a win or a loss

This script reports ONLY cells whose full seed set has landed. Partial cells are
listed separately and excluded from every count -- folding in-flight cells into
an aggregate is an error this project has already made once.

It deliberately does NOT compute the P2 verdict: P2 is defined on the 20-cell
arm, and stating it before the arm is complete would be the same selection error
the prereg exists to avoid.
"""
import sys, os, re, json, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis.stamp import stamped

SEEDS = [0, 2, 3, 4, 5, 6]          # prereg sec 2
UNRESOLVED_LO, UNRESOLVED_HI = 2, 4  # prereg sec 4.1
DEADBAND = 0.05                      # K publish to 1 dp; below this is not a win


def k_best(rec):
    """K's BEST incumbent across BOTH their methods.

    Required by AUDIT_comparator_asymmetry (2026-09-13): comparing the primal
    against joint_bk alone silently scores us against K's WEAKER method. It is
    too easy on 9 of the 20 unproved n20 cells -- by 84.7 on R211.
    NOTE: analysis/s2_close.py:91 still has this defect."""
    return min(rec["joint_bk"], rec["lbbd_bk"])


def parse(logpath):
    """-> {cell: {seed: best}}; tolerates the spool-fallback lines."""
    out, cur = {}, None
    for ln in open(logpath, encoding="utf-8", errors="replace"):
        m = re.match(r"\[calib\]\s+(\S+)\s+n(\d+)\s+(\S+)\s+s(\d+)", ln)
        if m:
            cur = (m.group(1), int(m.group(4)))
            continue
        m = re.search(r"->\s*best=([0-9.]+)", ln)
        if m and cur:
            out.setdefault(cur[0], {})[cur[1]] = float(m.group(1))
            cur = None
    return out


def median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="runs/s2g.log")
    ap.add_argument("--size", type=int, default=20)
    a = ap.parse_args()

    kref = json.load(open("data/karademir2025/k_reference.json"))
    per = kref["table3"]["per_instance"][str(a.size)]
    data = parse(a.log)

    done, partial = {}, {}
    for c, sd in data.items():
        (done if len(sd) >= len(SEEDS) else partial)[c] = sd

    print(f"S2g IN FLIGHT -- {len(done)} cells complete, {len(partial)} partial, "
          f"of 14 planned\n")
    print(f"{'cell':8s} {'K BK':>8s} {'median':>9s} {'best':>9s} {'delta med':>10s} "
          f"{'w/t/l':>8s} status")

    tally = {"BEAT": 0, "TIE": 0, "UNRESOLVED": 0, "LOSE": 0}
    rows = []
    for c in sorted(done):
        v = list(done[c].values())
        kbk = k_best(per[c])
        med, bst = median(v), min(v)
        w = sum(1 for x in v if x < kbk - DEADBAND)
        lo = sum(1 for x in v if x > kbk + DEADBAND)
        ti = len(v) - w - lo
        if ti >= 4:                       # most seeds reproduce K's value exactly
            st = "TIE"
        elif w > UNRESOLVED_HI:
            st = "BEAT"
        elif w >= UNRESOLVED_LO:
            st = "UNRESOLVED"
        else:
            st = "LOSE"
        tally[st] += 1
        rows.append(dict(cell=c, k_best=kbk, joint_bk=per[c]["joint_bk"],
                         lbbd_bk=per[c]["lbbd_bk"], median=med, best=bst,
                         win=w, tie=ti, lose=lo, n=len(v), status=st))
        print(f"{c:8s} {kbk:8.1f} {med:9.1f} {bst:9.1f} {med - kbk:+10.1f} "
              f"{w}/{ti}/{lo:<3} {st}")

    if partial:
        print("\nPARTIAL (excluded from all counts):")
        for c in sorted(partial):
            print(f"  {c:8s} {len(partial[c])}/{len(SEEDS)} seeds")

    print(f"\nAmong COMPLETE cells only: {tally['BEAT']} beat, {tally['TIE']} tie, "
          f"{tally['UNRESOLVED']} unresolved, {tally['LOSE']} lose")
    print("\nP2 verdict NOT computed -- P2 is defined on the full 20-cell arm.")
    json.dump(stamped(dict(rows=rows, partial={c: len(s) for c, s in partial.items()},
                   tally=tally), __file__), open("runs/s2g_status.json", "w"), indent=1)
