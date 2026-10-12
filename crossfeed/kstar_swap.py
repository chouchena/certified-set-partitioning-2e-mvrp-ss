"""
kstar_swap.py -- wiser E at the frontier cardinality.

k* is where block-A(C\\E) proves. Keep |E| = k* (so it still proves), but change
WHICH k* customers are dropped to raise z_A(H_k*)*.

Ranking from the greedy block-A(H_k*)* solution:
  swap-in-to-E  (H -> E):  H_k* customer with the LOWEST in-route detour
                           d_ic + d_cj - d_ij + service_c  -- genuinely cheap
  swap-out-of-E (E -> H):  E member with the HIGHEST cheapest-insertion cost
                           into H_k*'s routes -- wrongly dropped

Try the top 1-swaps and 2-swaps; each a warm-started 700s block-A(H') solve;
keep if proven AND block_relax > greedy. Monotone doesn't apply across
different same-size E's, so every candidate must be verified proven.
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


def routes_from(xs):
    succ = {}
    for (i, j), v in xs.items():
        if v == 1:
            succ.setdefault(i, []).append(j)
    routes = []
    for s in list(succ.get(0, [])):
        r, cur, seen = [], s, set()
        while cur != 0 and cur not in seen:
            r.append(cur); seen.add(cur)
            nx = [x for x in succ.get(cur, []) if x != cur]
            cur = nx[0] if nx else 0
        routes.append(r)
    return routes


def run(name, size, kstar, *, workers=8, tl=700, n_swaps=4):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=tl)
    D, nd = p.DistMatrix, p.nodes
    s, wts, ctx = scarcity_and_weights(p)
    _e = easiness(ctx, wts)
    order = sorted(_e, key=lambda c: -_e[c])
    wlb = water_lb_scaled(p)[0] / SCALE
    Eg = order[:kstar]
    Hg = [c for c in p.customers if c not in set(Eg)]
    print(f"\n=== {name}  k*-swap  k*={kstar}  greedy E={sorted(Eg)}  wlb={wlb:.1f} ===", flush=True)

    gf = solve(p, Eg, tl, workers)
    if not gf.get("proven"):
        print(f"greedy k* did NOT prove ({gf['value']}) -- abort", flush=True)
        return
    gbr = round(gf["value"] + wlb, 2)
    ws = gf.get("xij_sol")
    print(f"greedy k*: zA={gf['value']} block_relax={gbr}  (baseline)", flush=True)

    # in-route detour for each kept customer
    rts = routes_from(ws or {})
    detour = {}
    for r in rts:
        seq = [0] + r + [0]
        for a in range(1, len(seq) - 1):
            i, c, j = seq[a - 1], seq[a], seq[a + 1]
            detour[c] = D[i][c] + D[c][j] - D[i][j] + nd[c].serviceTime
    for c in Hg:
        detour.setdefault(c, 1e9)
    # cheapest-insertion cost of each E member into the greedy routes
    ins = {}
    arcs = [(i, j) for (i, j), v in (ws or {}).items() if v == 1]
    for e in Eg:
        best = min((D[i][e] + D[e][j] - D[i][j] for (i, j) in arcs), default=1e9)
        ins[e] = best + nd[e].serviceTime

    swap_in = sorted(Hg, key=lambda c: detour[c])[:n_swaps]        # cheapest kept
    swap_out = sorted(Eg, key=lambda c: -ins[c])[:n_swaps]         # priciest dropped
    print(f"swap-in  (H->E, low detour): {[(c, round(detour[c],1)) for c in swap_in]}", flush=True)
    print(f"swap-out (E->H, high insert): {[(c, round(ins[c],1)) for c in swap_out]}", flush=True)

    best = (gbr, list(Eg), "greedy")
    cands = []
    for a in range(min(n_swaps, len(swap_out))):
        for b in range(min(n_swaps, len(swap_in))):
            E1 = [c for c in Eg if c != swap_out[a]] + [swap_in[b]]
            cands.append((f"1swap[{swap_out[a]}->{swap_in[b]}]", E1))
    # a couple of 2-swaps
    if len(swap_out) >= 2 and len(swap_in) >= 2:
        E2 = [c for c in Eg if c not in swap_out[:2]] + swap_in[:2]
        cands.append((f"2swap[{swap_out[:2]}->{swap_in[:2]}]", E2))

    for tag, E in cands:
        E = list(dict.fromkeys(E))
        if len(E) != kstar:
            continue
        t0 = time.time()
        r = solve(p, E, tl, workers, ws=ws)
        br = round((r["value"] or 0) + wlb, 2) if r["value"] else None
        mark = ""
        if r.get("proven") and br and br > best[0]:
            best = (br, sorted(E), tag); mark = "  <<< NEW BEST"
        print(f"  {tag:26} E={sorted(E)}  zA={r['value']} proven={r['proven']} "
              f"block_relax={br}  {time.time()-t0:.0f}s{mark}", flush=True)

    print(f"\n{name}: k*-swap best = {best[0]}  E={best[1]}  ({best[2]})  vs greedy {gbr}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--kstar", type=int, required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tl", type=int, default=700)
    ap.add_argument("--n-swaps", type=int, default=4)
    a = ap.parse_args()
    run(a.cell, a.size, a.kstar, workers=a.workers, tl=a.tl, n_swaps=a.n_swaps)
