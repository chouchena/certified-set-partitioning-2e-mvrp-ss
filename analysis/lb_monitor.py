"""One monitor for the whole LB leg, at K's OWN granularity per size.

K does not publish the same granularity at every size, so a single per-cell watcher cannot
serve the campaign:
  |C| <= 30  Table 3  PER-INSTANCE             -> mode "cell"
  |C| = 50   Table 4  ONE pooled avg over 27   -> mode "pooled"
  |C| = 100  Table 6  PER-FAMILY avg, prox 0.1 -> mode "family"
  |C| = 40   no table at all                   -> no comparison possible; refuses to run.

TWO RULES THIS ENFORCES, both from failures already paid for:
1. NO PARTIAL AGGREGATES. A pooled or per-family mean is printed only when EVERY cell in the
   group has a completed artifact. A mean over the finished half of a family is a different
   statistic that happens to look like the target one -- the aggregate form of reading results
   early. Until the group closes this prints coverage only, never a ratio.
2. BOTH SIDES CARRY THE SIZE. K's reference and our bound are looked up by the same (size,
   family) key. Fixing only the numerator once turned a 1.49x into a reported 2.38x.

JENSEN CAVEAT (n50 and n100 only). K publishes mean(BK) and mean(Gap%) separately, so the only
derivable reference is mean(BK) x (1 - mean(Gap)), whereas the wanted quantity is
mean_i(BK_i x (1 - Gap_i)). They differ by -cov(BK, Gap), whose sign is unrecoverable from
published data. Every aggregate line prints APPROX so the caveat travels with the number
instead of living in a footnote.
"""
import argparse, glob, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAMS = ("C", "R", "RC")

# Table 4, WLS 1:10, proximity 0, pooled over all 27 instances (paper/paper-reference-data.md).
# SAME UB FIX as K_N100: Table 4's Gap% 58.0 is the JOINT MILP gap against Joint BK
# 1989.3, not against LBBD's better 1941.8. With the Joint BK the derived gap reproduces
# the published 58.0% exactly; with LBBD's it read 57.0%.
K_N50 = dict(lb=1989.3 * (1 - 0.580), ub=1989.3, ub_best=1941.8, n=27)
# Table 6, WLS 1:10, proximity 0.1, per family (paper/paper-reference-data.md).
# UB CONVENTION -- FIXED 2026-09-10 after audit. `ub` MUST be the JOINT zIP, not the (better)
# LBBD zIP, because K's published Gap% is defined against the Joint incumbent and because
# Table 3 at n<=30 is parsed the same way. Using LBBD zIP here silently made K's OptGap% read
# 55.8/71.6/74.0 instead of its published 60.1/74.6/77.0, so the n100 row was not comparable
# with the n20/n30 rows it was being plotted against. With the Joint zIP the derived gap
# reproduces the published number EXACTLY in all three families -- a checkable anchor.
# `ub_best` is retained only for falsification checks (a bound above a FEASIBLE value is
# invalid), never as a denominator.
K_N100 = {"C":  dict(lb=4271.3 * (1 - 0.601), ub=4271.3, ub_best=3857.2, n=8),
          "R":  dict(lb=4158.9 * (1 - 0.746), ub=4158.9, ub_best=3720.9, n=11),
          "RC": dict(lb=5432.5 * (1 - 0.770), ub=5432.5, ub_best=4810.6, n=8)}


def fam(cell):
    return "RC" if cell.startswith("RC") else cell[0]


def k_table3(size):
    """Per-instance (LB, gap%, BK) from Table 3. Only |C| <= 30.

    |C|=10 is laid out in THREE cell-columns per row (`| C201 | 365.5 | | R204 | 351.4 | ...`)
    with no Gap column, because every n10 instance is solved to optimality. The single-column
    regex below cannot read it, which made this function silently return {} for size=10 --
    a vacuous empty result, not an error. Handled explicitly first.
    """
    if size == 10:
        out, sec = {}, False
        for l in open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8"):
            if l.startswith("### |C|"):
                sec = "= 10" in l
                continue
            if not sec:
                continue
            for m in re.finditer(r"\|\s*((?:RC|C|R)\d{3})\s*\|\s*(\d+\.\d+)\s*\|", l):
                # gap is 0 for every n10 instance, so the LB equals the optimum
                out[m.group(1)] = (float(m.group(2)), 0.0, float(m.group(2)))
        return out
    out, sec = {}, None
    for l in open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8"):
        if l.startswith("### |C|"):
            sec = l.strip()
        m = re.match(r"\|\s*((?:C|R|RC)\d{3})\s*\|\s*([\d.]+)\s*\|\s*([\d.+*−-]+)\s*\|", l)
        if m and sec and f"= {size}" in sec:
            try:
                bk = float(m.group(2))
                g = float(m.group(3).replace("*", "").replace("−", "-"))
                out[m.group(1)] = (bk * (1 - g / 100), g, bk)
            except ValueError:
                pass
    return out


def our_bound(cell, size):
    """max_k block_relax over ALL records -- a truncated dual bound is a valid LB (proof Step 0)."""
    fs = (glob.glob(os.path.join(ROOT, "crossfeed",
                                 f"easy_reduction_descend_{cell}_n{size}.json"))
          or glob.glob(os.path.join(ROOT, "crossfeed", f"easy_reduction_{cell}_n{size}.json")))
    if not fs:
        return None
    try:
        r = json.load(open(fs[0], encoding="utf-8"))
    except Exception:
        return None
    r = r if isinstance(r, list) else [r]
    r = [x for x in r if isinstance(x, dict) and x.get("block_relax") is not None]
    if not r:
        return None
    b = max(r, key=lambda x: x["block_relax"])
    # ARITHMETIC BOUND IN THE ESTIMATOR (2026-09-10). The reported LB is
    # max(block_relax, fullset_bound) -- both are valid lower bounds (proof Step 0 and
    # validation/fullset_bound_proof.md), so taking the larger is free and always correct.
    # It matters: across 57 cells with a descend artifact the arithmetic bound WINS on 14 --
    # 0/27 at n20, 4/26 at n30 (all against k_cap-damaged runs), and 10/14 at n100 on
    # correctly-run cells, by 3% to 32%. Every completed R cell at |C|=100 loses to it.
    # Computed here rather than in the descend because easy_reduction_descend.py is inside
    # _provenance()'s hash list: editing it mid-campaign would make running cells stamp a
    # code_hash that does not match the code they are executing. This file is not hashed.
    # The bound is closed-form + one assignment (~10 ms) and fully deterministic, so
    # recomputing on read is equivalent to storing it.
    arith, arith_src = None, "milp"
    try:
        from build_instance import build as _build
        from crossfeed.fullset_bound import fullset_bound as _fs
        _p = _build(cell, size, wls=0.1, tau="formula",
                    proximity=(0.1 if size == 100 else 0.0), time_limit=60)
        arith = _fs(_p)[0]
    except Exception:
        arith = None
    # STEP-2 ROUNDING CORRECTION (added 2026-09-10, after re-verifying F9 rather than citing it).
    # Step 2 of easy_reduction_bound_proof.md needs d(p,s) <= d(p,e) + d(e,s) to shortcut a
    # dropped customer e without increasing cost. Distances live on a 0.01 grid, and at
    # proximity 0.1 that rounding breaks the triangle inequality on a few triples: 18 per R
    # cell and 8 per RC cell have CUSTOMERS on both ends (C cells: none; prox 0.0: none at all).
    # Each of the k shortcuts can therefore inflate z_A(H) by at most one grid unit, so
    # z_A(H)* <= z_A(full)* + max_excess * k and the MILP value must be reduced by that much
    # to stay a valid lower bound. At n100 with k~67 the correction is <= 0.67 on bounds of
    # 840-2413 -- under 0.08% -- but it is not zero, and a proof does not get to ignore it.
    milp_raw = b["block_relax"]
    step2_corr = 0.0
    try:
        if size == 100:
            from crossfeed.fullset_bound import max_triangle_excess
            from build_instance import build as _b2
            _pp = _b2(cell, size, wls=0.1, tau="formula", proximity=0.1, time_limit=60)
            exc = max(0.0, max_triangle_excess(_pp))
            step2_corr = exc * (b.get("k") or 0)
    except Exception:
        step2_corr = 0.0
    milp_corrected = milp_raw - step2_corr
    best_val, arith_src = milp_corrected, "milp"
    if arith is not None and arith > best_val:
        best_val, arith_src = arith, "arithmetic"
    curve = []
    for x in sorted(r, key=lambda y: y.get("t_start") or 0):
        curve.extend(x.get("lb_curve") or [])
    return dict(best=best_val, milp=milp_corrected, milp_raw=milp_raw,
                step2_corr=round(step2_corr, 4), arith=arith, source=arith_src,
                k=b.get("k"), proven=bool(b.get("proven")),
                n_proven=sum(1 for x in r if x.get("proven")), n_total=len(r),
                wall=sum(x.get("wall") or 0 for x in r),
                improves=sum(x.get("n_improve") or 0 for x in r),
                prox=b.get("proximity"), threads=b.get("threads"), code=b.get("code_hash"),
                curve=curve)


def time_to(cell, size, target):
    """Cell-global seconds at which the ANYTIME bound first exceeds `target`.

    Reads lb_curve, so it is None for artifacts written before the 2026-09-10 repair --
    reported as 'n/a', never silently as a wall-clock total, which would be a different
    quantity (time to FINISH the descend, not time to BEAT K).
    """
    ob = our_bound(cell, size)
    if not ob or not ob["curve"]:
        return None
    best = None
    for (t, v) in ob["curve"]:
        if best is None or v > best:
            best = v
            if v > target:
                return t
    return None


def time_to_best(cell, size):
    """Cell-global seconds at which the final reported bound was first reached."""
    ob = our_bound(cell, size)
    if not ob or not ob["curve"]:
        return None
    best, t_at = None, None
    for (t, v) in ob["curve"]:
        if best is None or v > best:
            best, t_at = v, t
    return t_at


def completed(size, logs):
    done = set()
    for name in logs:
        p = os.path.join(ROOT, "runs", name)
        if not os.path.exists(p):
            continue
        for l in open(p, encoding="utf-8", errors="replace"):
            m = re.search(r"^\[[\d:]+\]\s+((?:C|R|RC)\d{3})\s+done in", l)
            if m:
                done.add(m.group(1))
    return done


def cell_line(cell, size, K):
    ob = our_bound(cell, size)
    if not ob or cell not in K:
        return None
    klb, g, _bk = K[cell]
    r = ob["best"] / klb
    tb = time_to(cell, size, klb)
    tbest = time_to_best(cell, size)
    return (f"VERDICT n{size} {cell:6} Kgap={g:4.0f}% bound={ob['best']:8.2f} vs K {klb:7.1f} "
            f"-> {r:5.2f}x {'WIN ' if r > 1 else 'LOSS'} | k={ob['k']} proven={ob['proven']} "
            f"({ob['n_proven']}/{ob['n_total']} recs) wall={ob['wall']:.0f}s "
            f"t2beat={('%.1fs' % tb) if tb is not None else 'n/a'} "
            f"t2best={('%.1fs' % tbest) if tbest is not None else 'n/a'} "
            f"improv={ob['improves']} prox={ob['prox']} code={ob['code']}"
            + ("  [K PROVED OPTIMAL]" if g == 0 else ""))


def protocol_split(size, cells):
    """Disclose a MIXED protocol in the roll-up itself, per validation/PREREG_n30_repair_decision.md.

    n30 is NOT a single-protocol family: 16 undamaged cells ran k_hi=15 and the 10 k_cap-damaged
    cells were repaired at k_hi=20 with a recalibrated det_tl. Rule 4 of the pre-registration
    requires that to be disclosed in EVERY n30 roll-up. Reading it off the artifacts rather than
    hardcoding it means the disclosure cannot drift out of date, and cannot be forgotten by
    whoever prints the table next.
    """
    seen = {}
    for c in cells:
        fs = glob.glob(os.path.join(ROOT, "crossfeed", f"easy_reduction_descend_{c}_n{size}.json"))
        if not fs:
            continue
        try:
            r = json.load(open(fs[0], encoding="utf-8"))
        except Exception:
            continue
        for x in (r if isinstance(r, list) else [r]):
            if isinstance(x, dict) and x.get("block_relax") is not None:
                # A MISSING k_hi is its own protocol, not a value to skip. The pre-provenance
                # n30 runs stamp no k_hi at all, so skipping None made the split invisible --
                # the disclosure failed silently in exactly the case it exists for.
                seen.setdefault(x.get("k_hi"), []).append(c)
                break
    if len(seen) <= 1:
        return []
    lab = lambda k: ("unstamped/pre-provenance (k_hi=15 per night_batch)" if k is None
                     else f"k_hi={k}")
    parts = ", ".join(f"{lab(k)}: {len(set(v))} cells"
                      for k, v in sorted(seen.items(), key=lambda kv: (kv[0] is not None, kv[0])))
    return [f"n{size} PROTOCOL SPLIT -- {parts}. This family mean mixes protocols and must NOT be "
            f"presented as single-protocol (PREREG_n30_repair_decision.md rule 4)."]


def rollup(size, cells):
    """Aggregate ONLY when the group is closed. Prints coverage otherwise."""
    lines = list(protocol_split(size, cells))
    if size == 50:
        got = [c for c in cells if our_bound(c, size)]
        if len(got) < len(cells):
            return [f"n50 pooled: coverage {len(got)}/{len(cells)} -- aggregate withheld until "
                    f"the group closes (no partial means)"]
        mean = sum(our_bound(c, size)["best"] for c in got) / len(got)
        kl, ub = K_N50["lb"], K_N50["ub"]
        lines.append(f"n50 POOLED over {len(got)}: our mean LB {mean:8.2f} vs K APPROX {kl:7.1f} "
                     f"-> {mean / kl:5.2f}x | OptGap% ours {(ub - mean) / ub * 100:5.1f}% "
                     f"vs K {(ub - kl) / ub * 100:5.1f}% (shared UB {ub}) [JENSEN-APPROX]")
        return lines
    if size == 100:
        for f in FAMS:
            fc = [c for c in cells if fam(c) == f]
            got = [c for c in fc if our_bound(c, size)]
            if not fc:
                continue
            if len(got) < len(fc):
                lines.append(f"n100 {f:2}: coverage {len(got)}/{len(fc)} -- family mean withheld")
                continue
            mean = sum(our_bound(c, size)["best"] for c in got) / len(got)
            kl, ub = K_N100[f]["lb"], K_N100[f]["ub"]
            if mean > K_N100[f]["ub_best"]:
                lines.append(f"n100 {f:2} !! INVALID: mean LB {mean:.2f} EXCEEDS the best-known "
                             f"feasible {K_N100[f]['ub_best']} -- a component is wrong")
            lines.append(f"n100 {f:2} FAMILY over {len(got)}: our mean LB {mean:8.2f} vs K APPROX "
                         f"{kl:7.1f} -> {mean / kl:5.2f}x | OptGap% ours "
                         f"{(ub - mean) / ub * 100:5.1f}% vs K {(ub - kl) / ub * 100:5.1f}% "
                         f"(shared UB {ub}) [JENSEN-APPROX, prox 0.1]")
        return lines
    K = k_table3(size)
    tgt = [c for c in cells if c in K and K[c][1] > 0]
    for f in FAMS:
        fc = [c for c in tgt if fam(c) == f]
        got = [c for c in fc if our_bound(c, size)]
        if not fc:
            continue
        if len(got) < len(fc):
            lines.append(f"n{size} {f:2}: coverage {len(got)}/{len(fc)} -- family mean withheld")
            continue
        og = sum((K[c][2] - our_bound(c, size)["best"]) / K[c][2] for c in got) / len(got) * 100
        kg = sum(K[c][1] for c in got) / len(got)
        wins = sum(1 for c in got if our_bound(c, size)["best"] > K[c][0])
        ratio = (kg / og) if og else float("inf")
        lines.append(f"n{size} {f:2} FAMILY over {len(got)}: OptGap% ours {og:5.1f}% vs K "
                     f"{kg:5.1f}% -> delta {kg - og:+5.1f}pp, ratio {ratio:4.2f}x "
                     f"| per-inst wins {wins}/{len(got)}")
    return lines


def cell_universe(size):
    """The 27 Solomon class-2 cells. At |C|<=30 the target set is K's non-optimal subset;
    at 50/100 K averages over all 27, so the group is all 27."""
    sys.path.insert(0, ROOT)
    if size <= 30:
        from analysis.night_batch import k_targets
        return sorted(k_targets(size))
    base = k_table3(20) or k_table3(30)
    return sorted(base) if base else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--mode", default="auto", choices=["auto", "cell", "pooled", "family"])
    ap.add_argument("--logs", default="")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--hours", type=float, default=20.0)
    A = ap.parse_args()

    if A.size == 40:
        sys.exit("n40 has NO K table (T3=10/20/30, T4=10/20/50, T6=100). No comparison is "
                 "possible at this size; an n40 run can only be descriptive.")

    mode = A.mode if A.mode != "auto" else {50: "pooled", 100: "family"}.get(A.size, "cell")
    cells = cell_universe(A.size)
    logs = ([x.strip() for x in A.logs.split(",") if x.strip()]
            or ["lb_repair_n30.log", "night_batch.log", "lb_n30.log", "lb_big.log"])
    K = k_table3(A.size) if A.size <= 30 else {}

    if A.once:
        print(f"LB monitor ONCE: n{A.size} mode={mode} cells={len(cells)}", flush=True)
        if mode == "cell":
            for c in cells:
                l = cell_line(c, A.size, K)
                if l:
                    print(l, flush=True)
        for l in rollup(A.size, cells):
            print(l, flush=True)
        return

    seen = completed(A.size, logs)
    print(f"LB monitor: n{A.size} mode={mode} cells={len(cells)} logs={logs}; "
          f"{len(seen)} already complete", flush=True)
    for _ in range(int(A.hours * 60)):
        time.sleep(60)
        now = completed(A.size, logs)
        fresh = sorted(now - seen)
        if not fresh:
            continue
        for c in fresh:
            if mode == "cell":
                l = cell_line(c, A.size, K)
                if l:
                    print(l, flush=True)
        for l in rollup(A.size, cells):
            print("  " + l, flush=True)
        seen = now


if __name__ == "__main__":
    main()
