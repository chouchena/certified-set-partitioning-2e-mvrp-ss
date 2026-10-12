"""Emit ONE unambiguous verdict line per cell, the moment its artifact appears.

WHY THIS EXISTS. Twice I read the aggregate counters in the coverage report ("cold 13/21 ->
14/22") and inferred which way the newest cell went. That inference is invalid: the counters
and the bounds I later queried came from DIFFERENT moments -- cells complete while the previous
report is still being read -- so a counter delta cannot be attributed to the cell named in the
log. Both times the actual bounds said the opposite (C207, R202).

The fix is not discipline, it is removing the cross-reference: every line this emits carries
the cell name AND its bounds AND its verdict together, so there is nothing to correlate.
Progress counters are not results and are deliberately not printed here.
"""
import glob, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# K's reference must be SIZE-AWARE too. lb_coverage.k_paper_lb parses only the "= 20" section,
# so pairing it with an n30 bound compared our n30 numbers against K's n20 LB -- C203 would have
# been reported at 2.38x instead of its true 1.49x. Same class of bug as the n20-hardcoded
# bounds lookup, one layer up: BOTH sides of a ratio must carry the size.
def k_paper_lb_size(size):
    out, sec = {}, None
    for l in open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8"):
        if l.startswith("### |C|"):
            sec = l.strip()
        m = re.match(r"\|\s*((?:C|R|RC)\d{3})\s*\|\s*([\d.]+)\s*\|\s*([\d.+*−-]+)\s*\|", l)
        if m and sec and f"= {size}" in sec:
            try:
                bk = float(m.group(2)); g = float(m.group(3).replace("*", "").replace("−", "-"))
                out[m.group(1)] = bk * (1 - g / 100)
            except ValueError:
                pass
    return out
# NOT lb_crossing_samehw.our_bounds -- that is hardcoded to _n20.json, so once lb_n30 began
# printing completion lines it re-emitted each cell's N20 numbers as if they were n30 results.
# Caught on C204 before it was reported. Size must be explicit.
import glob as _glob, json as _json


def our_bounds_size(cell, size):
    """max_k block_relax over ALL records (proof Step 0: a valid dual bound is a valid LB).
    Consistent return shape so callers cannot mis-destructure it."""
    fs = (_glob.glob(os.path.join(ROOT, "crossfeed", f"easy_reduction_descend_{cell}_n{size}.json"))
          or _glob.glob(os.path.join(ROOT, "crossfeed", f"easy_reduction_{cell}_n{size}.json")))
    if not fs:
        return None
    recs = _json.load(open(fs[0], encoding="utf-8"))
    recs = recs if isinstance(recs, list) else [recs]
    recs = [r for r in recs if isinstance(r, dict) and r.get("block_relax") is not None]
    if not recs:
        return None
    best = max(recs, key=lambda r: r["block_relax"])
    pv = [r for r in recs if r.get("proven")]
    return dict(best=best["block_relax"], k=best.get("k"), proven=bool(best.get("proven")),
                n_proven=len(pv), n_total=len(recs),
                wall=sum(r.get("wall") or 0 for r in recs))


def k_gaps(size=20):
    out, sec = {}, None
    for l in open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8"):
        if l.startswith("### |C|"):
            sec = l.strip()
        m = re.match(r"\|\s*((?:C|R|RC)\d{3})\s*\|\s*([\d.]+)\s*\|\s*([\d.+*−-]+)\s*\|", l)
        if m and sec and f"= {size}" in sec:
            try:
                out[m.group(1)] = float(m.group(3).replace("*", "").replace("−", "-"))
            except ValueError:
                pass
    return out


def cells_on_disk():
    out = set()
    for f in glob.glob(os.path.join(ROOT, "crossfeed", "easy_reduction*_n20.json")):
        b = os.path.basename(f).replace("easy_reduction_", "").replace("descend_", "")
        out.add(b.replace("_n20.json", ""))
    return out


def cells_completed(size=20):
    """Cells whose DESCEND HAS FINISHED, per the runner's own completion line.

    File existence is NOT completion: easy_reduction_descend writes incrementally and the
    bound KEEPS IMPROVING as it descends to lower k. Keying on file appearance emitted
    verdicts mid-descend and understated them -- R210 was reported argmax 0.98 LOSS and
    finished at 1.01 WIN once k=4 landed. That is the same read-too-early error as the
    counters, one level down. The runner prints '  <CELL> done in Ns' only after
    subprocess.run returns, so that is the real marker.
    """
    done = set()
    # read EVERY runner log that emits completion lines. Keying on one file meant the watcher
    # went silent the moment work moved to a different runner (night_batch), which would have
    # produced no verdicts at all overnight.
    # THE LOG SET MUST BE SIZE-EXCLUSIVE. master_sequence.out carries lb_coverage's n20
    # completions AND lb_n30's n30 ones, so reading it while watching n30 marked 10 of the 21
    # batch-1 cells as "already seen" from their n20 runs -- their n30 verdicts would never have
    # been emitted, and it would have looked like those cells simply had not finished.
    # The completion line does not carry a size, so the SOURCE has to guarantee it.
    logs = (("night_batch.log", "night_batch.out", "lb_n30.log") if size == 30
            else ("master_sequence.out",))
    for name in logs:
        p = os.path.join(ROOT, "runs", name)
        if not os.path.exists(p):
            continue
        for l in open(p, encoding="utf-8", errors="replace"):
            m = re.search(r"^\[[\d:]+\]\s+((?:C|R|RC)\d{3})\s+done in", l)
            if m:
                done.add(m.group(1))
    return done


def verdict(cell, K, G, size=20):
    """One self-contained line: cell, size, bound, K's bound, ratio, provenance.

    SIZE IS EXPLICIT because the previous version called lb_crossing_samehw.our_bounds, which
    is hardcoded to _n20.json. Once lb_n30 began printing completion lines it re-emitted each
    cell's n20 numbers as if they were n30 results -- twice (C204, C203), both caught before
    reporting. The bound is now max_k block_relax over ALL records, per proof Step 0.
    """
    ob = our_bounds_size(cell, size)
    kp, g = K.get(cell), G.get(cell)
    if not ob or not kp:
        return None
    r = ob["best"] / kp
    return (f"VERDICT n{size} {cell:6} Kgap={('%.0f%%' % g) if g is not None else '  ?':>4} "
            f"bound={ob['best']:8.2f} vs K {kp:7.1f} -> {r:5.2f}x "
            f"{'WIN ' if r > 1 else 'LOSS'} | k={ob['k']} proven={ob['proven']} "
            f"({ob['n_proven']}/{ob['n_total']} recs) wall={ob['wall']:.0f}s"
            + ("  [K PROVED OPTIMAL - unbeatable by construction]" if g == 0 else ""))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    A = ap.parse_args()
    K, G = k_paper_lb_size(A.size), k_gaps(A.size)
    seen = cells_completed(A.size)
    print(f"verdict watch armed for n{A.size}; {len(seen)} cells already COMPLETED",
          flush=True)
    for _ in range(1200):                 # 20h ceiling
        time.sleep(60)
        now = cells_completed(A.size)
        for cell in sorted(now - seen):
            v = verdict(cell, K, G, A.size)
            if v:
                print(v, flush=True)
        seen = now


if __name__ == "__main__":
    main()
