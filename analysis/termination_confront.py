"""Confront the termination-rule discussion with ALL logged fixopt trajectories (n10/n20/n30).
Per trace: time-to-beat-K, post-beat grind vs post-beat improvement (the 'useless runs after
beating K' claim), CONJUNCTIVE stop (beat-K AND gap<=eps) fire time, LB-looseness (does the primal
trace even carry a valid bound?), inter-improvement gaps (late-escape risk). K_min = min(Joint,LBBD)
parsed from paper/paper-reference-data.md (n10 all obvious; n20/n30 obvious iff Joint Gap%==0).
n50/n100 have NO per-cell K (pooled) -> beat-K = N/A there. Read-only; no re-run."""
import glob, json, os, re
from statistics import median

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "paper", "paper-reference-data.md")


def _num(s):
    return float(s.replace("*", "").replace("−", "-").strip())


def parse_kmin(path):
    KMIN, OBV = {}, {}
    size = None
    for line in open(path, encoding="utf-8"):
        m = re.search(r"\|C\|\s*=\s*(\d+)", line)
        if m:
            size = int(m.group(1)); continue
        if size is None or "|" not in line:
            continue
        toks = [t.strip() for t in line.split("|")]
        if size == 10:                       # compact: repeated (Inst, BK) pairs
            for j in range(len(toks) - 1):
                if re.fullmatch(r"[CR]C?\d{3}", toks[j]):
                    try:
                        KMIN[(toks[j], 10)] = _num(toks[j + 1]); OBV[(toks[j], 10)] = True
                    except ValueError:
                        pass
        else:                                # full: Inst|JointBK|Gap|IncT|LBBD BK|Imp|IncT
            if len(toks) >= 7 and re.fullmatch(r"[CR]C?\d{3}", toks[1]):
                try:
                    jbk, gap, lbk = _num(toks[2]), _num(toks[3]), _num(toks[5])
                    KMIN[(toks[1], size)] = min(jbk, lbk)
                    OBV[(toks[1], size)] = (gap == 0)
                except (ValueError, IndexError):
                    pass
    return KMIN, OBV


KMIN, OBV = parse_kmin(REF)


def load(f):
    inc, bnd = [], []
    for l in open(f, encoding="utf-8"):
        if not l.strip():
            continue
        try:
            r = json.loads(l)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(r, dict):
            continue
        w = r.get("wall_s")
        v = r.get("best_incumbent") if r.get("best_incumbent") is not None else r.get("incumbent")
        if isinstance(w, (int, float)) and isinstance(v, (int, float)):
            inc.append((w, v))
        b = r.get("best_bound") if r.get("best_bound") is not None else r.get("bound")
        if isinstance(w, (int, float)) and isinstance(b, (int, float)):
            bnd.append((w, b))
    return inc, bnd


def bound_at(bnd, t):
    v = None
    for w, b in bnd:
        if w <= t + 1e-6:
            v = b
    return v


def analyze(f):
    m = re.search(r"fixopt_([A-Z0-9]+)_n(\d+)_", os.path.basename(f))
    if not m:
        return None
    cell, size = m.group(1), int(m.group(2))
    inc, bnd = load(f)
    if not inc:
        return None
    inc.sort()
    best, bs = [], None
    for w, v in inc:
        bs = v if bs is None else min(bs, v)
        best.append((w, bs))
    rt, ov = best[-1][0], best[-1][1]
    K = KMIN.get((cell, size))
    obv = OBV.get((cell, size))
    t_beat = next((w for w, v in best if K is not None and v <= K), None)
    ov_at_beat = next((v for w, v in best if K is not None and v <= K), None)
    post_grind = (rt - t_beat) if t_beat is not None else None
    post_gain_pct = (100 * (ov_at_beat - ov) / ov_at_beat) if (t_beat is not None and ov_at_beat) else None
    fb = bound_at(bnd, rt)
    final_gap = (100 * (ov - fb) / ov) if fb else None
    def conj(eps):
        for w, v in best:
            if K is not None and v <= K:
                b = bound_at(bnd, w)
                if b and (v - b) / v <= eps:
                    return w
        return None
    imps = [w for i, (w, v) in enumerate(best) if i == 0 or v < best[i - 1][1] - 1e-9]
    gaps = [imps[i] - imps[i - 1] for i in range(1, len(imps))]
    return dict(cell=cell, size=size, rt=rt, ov=ov, K=K, obvious=obv, t_beat=t_beat,
                post_grind=post_grind, post_gain_pct=post_gain_pct, final_gap=final_gap,
                conj5=conj(0.05), max_gap=(max(gaps) if gaps else 0.0),
                last_imp=(imps[-1] if imps else 0.0))


def main():
    fs = sorted(glob.glob(os.path.join(ROOT, "runs", "fixopt_*.jsonl")))
    rows = [r for r in (analyze(f) for f in fs) if r]
    print(f"parsed {len(KMIN)} K_min cells; analyzed {len(rows)} traces\n")
    for size in sorted(set(r["size"] for r in rows)):
        S = [r for r in rows if r["size"] == size]
        haveK = [r for r in S if r["K"] is not None]
        nonobv = [r for r in haveK if r["obvious"] is False]
        obv = [r for r in haveK if r["obvious"] is True]
        beat_no = [r for r in nonobv if r["t_beat"] is not None]
        beat_ob = [r for r in obv if r["t_beat"] is not None]
        print(f"=== |C|={size}: {len(S)} traces ({len(haveK)} with K_min; "
              f"{len(nonobv)} non-obvious, {len(obv)} obvious) ===")
        print(f"  beat-K on NON-OBVIOUS: {len(beat_no)}/{len(nonobv)} traces"
              + (f"  cells={sorted(set(r['cell'] for r in beat_no))}" if beat_no else ""))
        print(f"  hit-optimum on obvious (tie): {len(beat_ob)}/{len(obv)}")
        if beat_no:
            print(f"    among non-obv beaters: median t_beat={median(r['t_beat'] for r in beat_no):.0f}s, "
                  f"median post-beat grind={median(r['post_grind'] for r in beat_no):.0f}s, "
                  f"median post-beat gain={median(r['post_gain_pct'] for r in beat_no):.2f}%")
        lateimp = sum(1 for r in S if r["last_imp"] > 0.5 * r["rt"] and r["rt"] > 0)
        print(f"  late-escape: {lateimp}/{len(S)} improve in back-half; "
              f"max inter-improve gap={max((r['max_gap'] for r in S), default=0):.0f}s")
    # corpus-wide claims
    allr = rows
    beaters = [r for r in allr if r["t_beat"] is not None and r["obvious"] is False]
    wasted = [r for r in beaters if (r["post_gain_pct"] or 0) <= 0.1 and (r["post_grind"] or 0) > 60]
    useful = [r for r in beaters if (r["post_gain_pct"] or 0) > 0.1]
    print(f"\n[CLAIM 1 useless-post-beat-grind] non-obv beaters={len(beaters)}; "
          f"WASTED grind (>60s, <=0.1% gain)={len(wasted)}; USEFUL grind (>0.1% gain)={len(useful)}")
    for r in sorted(beaters, key=lambda r: -(r["post_grind"] or 0))[:8]:
        print(f"    {r['cell']:6} n{r['size']} beat@{r['t_beat']:.0f}s ran+{r['post_grind']:.0f}s "
              f"gain={r['post_gain_pct'] or 0:.2f}%")
    print(f"[CLAIM 2 conjunctive-stop fires] {sum(1 for r in allr if r['conj5'] is not None)}/{len(allr)} traces")
    haveb = [r for r in allr if r["final_gap"] is not None]
    print(f"[CLAIM 3 primal trace carries a valid LB?] {len(haveb)}/{len(allr)} traces have a usable bound field")
    late = sum(1 for r in allr if r["last_imp"] > 0.5 * r["rt"] and r["rt"] > 0)
    print(f"[CLAIM 4 late-escapes] {late}/{len(allr)} traces improve in back-half; "
          f"corpus max inter-improve gap={max((r['max_gap'] for r in allr), default=0):.0f}s")


if __name__ == "__main__":
    main()
