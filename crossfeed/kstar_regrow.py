"""
kstar_regrow.py -- wiser E at frontier cardinality, evaluation-based.

Proxy rankings (in-route detour, cheapest-insertion) misrank -- kstar_swap's
first RC208 candidate went the wrong way. Instead:

  1. E+ = greedy_E U {cheapest kept customer}   (|E+| = k*+1, smaller H+, proves fast)
  2. solve block-A(C\\E+) -> H+ routing
  3. leave-one-out over E+: for each c in E+, bring c back to H (|E| = k*),
     warm-started from H+ + cheapest-insert c, solve.
     z_A(H+ u {c})* is the true bound for that composition.
  4. best = the c-removal giving the highest PROVEN block_relax.

The marginal z_A(H+ u {c})* - z_A(H+)* is c's real serve-cost -- exact, not a
proxy. Bringing back the highest-marginal c maximises z_A(H)* at |E| = k*.
"""
from __future__ import annotations
import argparse, sys, time
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE


def solve(p, drop, tl, workers, ws=None):
    ba = BlockA(p, integral=True, timing_mode="bigM", drop=set(drop))
    try:
        ba.m.parameters.threads = workers
    except Exception:
        pass
    return ba.solve(time_limit=tl, track_progress=False, mip_start_x=ws)


def routes(xs):
    succ = {}
    for (i, j), v in (xs or {}).items():
        if v == 1:
            succ.setdefault(i, []).append(j)
    out = []
    for s in list(succ.get(0, [])):
        r, cur, seen = [], s, set()
        while cur != 0 and cur not in seen:
            r.append(cur); seen.add(cur)
            nx = [x for x in succ.get(cur, []) if x != cur]
            cur = nx[0] if nx else 0
        out.append(r)
    return out


def run(name, size, kstar, *, workers=8, tl=600):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=tl)
    D, nd = p.DistMatrix, p.nodes
    s, wts, ctx = scarcity_and_weights(p)
    _e = easiness(ctx, wts)
    order = sorted(_e, key=lambda c: -_e[c])
    wlb = water_lb_scaled(p)[0] / SCALE
    Eg = order[:kstar]
    Hg = [c for c in p.customers if c not in set(Eg)]
    print(f"\n=== {name}  k*-regrow  k*={kstar}  greedy E={sorted(Eg)}  wlb={wlb:.1f} ===", flush=True)

    # greedy baseline (for comparison only)
    gf = solve(p, Eg, tl, workers)
    gbr = round((gf["value"] or 0) + wlb, 2) if gf["value"] else None
    print(f"greedy k*: zA={gf['value']} proven={gf['proven']} block_relax={gbr}", flush=True)

    # 1. add cheapest kept customer -> E+
    ws0 = gf.get("xij_sol")
    det = {}
    for r in routes(ws0):
        seq = [0] + r + [0]
        for a in range(1, len(seq) - 1):
            i, c, j = seq[a - 1], seq[a], seq[a + 1]
            det[c] = D[i][c] + D[c][j] - D[i][j] + nd[c].serviceTime
    cheapest_kept = min(Hg, key=lambda c: det.get(c, 1e9))
    Eplus = list(Eg) + [cheapest_kept]
    print(f"E+ = E u {{{cheapest_kept}}}  (cheapest kept, detour {det.get(cheapest_kept):.1f})", flush=True)

    # 2. solve H+
    rp = solve(p, Eplus, tl, workers, ws=ws0)
    if not rp.get("proven"):
        print(f"H+ did NOT prove ({rp['value']}) -- fall back to tl*1.5", flush=True)
        rp = solve(p, Eplus, int(tl * 1.5), workers, ws=ws0)
    zp = rp["value"]
    wsp = rp.get("xij_sol")
    print(f"H+ (|E|={kstar+1}): zA={zp} proven={rp['proven']} "
          f"block_relax={round((zp or 0)+wlb,2) if zp else None}", flush=True)

    # 3. leave-one-out over E+ : bring c back
    best = (gbr, sorted(Eg), "greedy")
    results = []
    for c in Eplus:
        Ec = [x for x in Eplus if x != c]           # size k*
        ws = dict(wsp) if wsp else {}
        if ws:  # cheapest-insert c
            used = [(i, j) for (i, j), v in ws.items() if v == 1]
            arc = min(used, key=lambda ij: D[ij[0]][c] + D[c][ij[1]] - D[ij[0]][ij[1]],
                      default=None)
            if arc:
                i, j = arc
                ws[(i, j)] = 0; ws[(i, c)] = 1; ws[(c, j)] = 1
            else:
                ws[(0, c)] = 1; ws[(c, 0)] = 1
        t0 = time.time()
        r = solve(p, Ec, tl, workers, ws=ws or None)
        br = round((r["value"] or 0) + wlb, 2) if r["value"] else None
        marg = (r["value"] - zp) if (r["value"] and zp) else None
        results.append((c, br, r.get("proven"), marg))
        mark = ""
        if r.get("proven") and br and best[0] and br > best[0]:
            best = (br, sorted(Ec), f"bringback[{c}]"); mark = "  <<< NEW BEST"
        print(f"  bring back {c:2}  E={sorted(Ec)}  zA={r['value']} "
              f"proven={r['proven']} block_relax={br}  marg={marg and round(marg,1)}  "
              f"{time.time()-t0:.0f}s{mark}", flush=True)

    print(f"\n{name}: k*-regrow best = {best[0]}  E={best[1]}  ({best[2]})  vs greedy {gbr}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--kstar", type=int, required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tl", type=int, default=600)
    a = ap.parse_args()
    run(a.cell, a.size, a.kstar, workers=a.workers, tl=a.tl)
