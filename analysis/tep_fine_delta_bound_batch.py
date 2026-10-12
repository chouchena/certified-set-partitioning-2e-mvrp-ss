"""The finer-bucket BOUND leg across the n30 grid, checking its own steps. (d464 -> grid)

WHY. Floor bucketing is a RELAXATION, so a finer grid relaxes less and the proven LP rises. On three
cells at n30, halving the default width (20 -> 10) lifted the proven bound +3.4 to +3.5 percent and
quartering it (-> 5) lifted it +4.6 to +5.2 percent, every artifact `proven: true` (d464, confirmed
from the JSON not the log). Grid-wide that moves the n30 bracket from 18.7 toward ~15.7 percent
against the predecessors' 46.8. It is the DUAL leg only: the same cells' primal was unchanged or
worse at the finer width, and this driver does not chain anything.

WHAT IT CHECKS, per CLAUDE.md section 4 ("a queue must check its own steps"):
  * a cell is skipped if its d=5 artifact already exists AND is proven -- resumable;
  * a cell whose artifact comes back UNPROVEN is recorded as such and its value is NOT used: an
    unproven LP at a finer width is not a bound (the pricer may not have converged), so the cell
    keeps its default-width proven bound and is listed for a longer re-run;
  * each artifact must carry `_provenance.code_hash` or the step is a failure;
  * the composed bound is max(default proven, d=5 proven) per cell -- the max of valid lower bounds
    is a valid lower bound -- and the table prints which width won.

WHEN TO RUN. Only when no wall-bounded job is live (d415). This leg has a --max-secs safety wall
of its own, so it is itself wall-bounded and must go solo; its stop is deterministic ONLY if the
artifact says proven, which is exactly what the check above enforces.

    python analysis/tep_fine_delta_bound_batch.py --delta 5
    python analysis/tep_fine_delta_bound_batch.py --size 20 --delta 5   # 2026-09-26: size generalised (d500)
"""
import argparse
import io
import json
import os
import statistics as st
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped
from bound_certificate import certified   # d519: readers require the elementary certificate, not the flag

_pre = argparse.ArgumentParser(add_help=False); _pre.add_argument("--size", type=int, default=30, choices=(10, 20, 30, 50, 100))
SIZE = _pre.parse_known_args()[0].size   # 2026-09-26: was hard-coded 30; n20 has 20 open cells whose bracket sits on the d20 default only
CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
PY = sys.executable


def art(cell, delta):
    """The bound artifact at this width. The three probe cells were run with --ip and so carry _ip."""
    for suf in ("_ip", ""):
        p = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d_d%d%s.json" % (cell, SIZE, delta, suf))
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d_d%d.json" % (cell, SIZE, delta))


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delta", type=float, default=5.0)
    ap.add_argument("--max-secs", type=float, default=900.0, help="safety wall; a stop here yields UNPROVEN and is not used")
    ap.add_argument("--cells", nargs="*", default=None)
    ap.add_argument("--size", type=int, default=SIZE, choices=(10, 20, 30, 50, 100))   # consumed by the pre-parser above; declared so parse_args accepts it
    a = ap.parse_args()
    d = int(round(a.delta))
    if SIZE == 100:
        raise SystemExit("n100 bounds come from the subset instrument (tep_easy_reduction); this batch is for n10-n50")
    cells = a.cells or CELLS
    ab = {(r["cell"], r["size"]): r for r in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"),
                                                               encoding="utf-8"))["records"]}
    rows, unproven, failed = [], [], []
    print("Finer-bucket bound leg, n%d, delta %d (default 20). Solo run required (d415).\n" % (SIZE, d))
    for c in cells:
        t0 = time.time()
        p = art(c, d); prior = load(p)
        if not (prior and certified(prior)):
            log = os.path.join(ROOT, "logs", ("fine_d%d_cg_%s.out" % (d, c)) if SIZE == 30 else ("fine_d%d_n%d_cg_%s.out" % (d, SIZE, c)))   # n30 keeps its historical log names
            with io.open(log, "w", encoding="utf-8", errors="replace") as fh:
                rc = subprocess.call([PY, "analysis/tep_cg_bound.py", c, "--size", str(SIZE), "--start-states",
                                      "--delta", str(d), "--max-secs", str(a.max_secs)],
                                     cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
            p = art(c, d); cur = load(p)
            if rc != 0 or cur is None:
                failed.append(c); print("  %-6s FAILED (exit %s, no artifact)" % (c, rc), flush=True); continue
        else:
            cur = prior
        if not cur.get("_provenance", {}).get("code_hash"):
            failed.append(c); print("  %-6s FAILED: no code_hash" % c, flush=True); continue
        base = load(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d.json" % (c, SIZE)))
        if not base:   # the default-width LP can be a by-product of the primal selection run (2026-09-27); ceil artifacts are not bounds
            b2 = load(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d_ip.json" % (c, SIZE)))
            base = b2 if (b2 and not b2.get("primal_rounding")) else None
        b_lp = float(base["lp_street"]) if (base and certified(base)) else None
        water = float(ab[(c, SIZE)]["water"])
        if not certified(cur):
            unproven.append(c)
            print("  %-6s d%d UNPROVEN after %.0fs -- keeps default bound %s" % (c, d, time.time() - t0,
                  ("%.1f" % b_lp) if b_lp else "n/a"), flush=True)
            rows.append(dict(cell=c, d_lp=float(cur["lp_street"]), d_proven=False, base_lp=b_lp,
                             best_lp=b_lp, best_width=20, composed=(b_lp + water) if b_lp else None))
            continue
        d_lp = float(cur["lp_street"])
        best_lp, width = (d_lp, d) if (b_lp is None or d_lp >= b_lp) else (b_lp, 20)
        rows.append(dict(cell=c, d_lp=d_lp, d_proven=True, d_N=cur.get("N"), base_lp=b_lp, base_N=(base or {}).get("N"),
                         best_lp=best_lp, best_width=width, composed=best_lp + water, secs=round(time.time() - t0)))
        print("  %-6s d%-2d %9.1f (N %.3f) vs d20 %9s  %s  composed %.1f  [%.0fs]"
              % (c, d, d_lp, float(cur.get("N") or 0), ("%.1f" % b_lp) if b_lp else "-",
                 ("%+.2f%%" % (100 * (d_lp / b_lp - 1))) if b_lp else "  n/a  ", best_lp + water, time.time() - t0), flush=True)
        json.dump(stamped(dict(size=SIZE, delta=d, rows=rows, unproven=unproven, failed=failed)),
                  io.open(os.path.join(ROOT, "runs", "oracle", "tep_fine_delta_bound_n%d_d%d.json" % (SIZE, d)), "w",
                          encoding="utf-8"), indent=1, default=str)
    ok = [r for r in rows if r["d_proven"] and r["base_lp"]]
    print("\n  %d cells: %d proven at d%d, %d UNPROVEN (kept default), %d failed" % (len(rows), len(ok), d, len(unproven), len(failed)))
    if ok:
        g = sorted(100 * (r["d_lp"] / r["base_lp"] - 1) for r in ok)
        print("  lift over the default proven bound: median %+.2f%%, min %+.2f%%, max %+.2f%%" % (st.median(g), g[0], g[-1]))
        print("  finer width is the better bound on %d of %d" % (sum(1 for r in ok if r["best_width"] == d), len(ok)))
        neg = [r["cell"] for r in ok if r["d_lp"] < r["base_lp"] - 1e-6]
        if neg:
            print("  *** %d cell(s) LOWER at the finer width -- a relaxation cannot tighten downward; inspect: %s" % (len(neg), ", ".join(neg)))
    if unproven:
        print("  UNPROVEN at d%d (re-run solo with a longer wall): %s" % (d, ", ".join(unproven)))
    print("  wrote runs/oracle/tep_fine_delta_bound_n%d_d%d.json" % (SIZE, d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
