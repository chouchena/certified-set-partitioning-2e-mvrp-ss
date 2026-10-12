"""AB4 candidates over the full cell x size grid. Standalone: imports only, edits
no tracked source, so code_hash is unchanged and the live campaign is unaffected.

AB4a' (forced-terminal assignment) is the only candidate that survived the n100
spot check. Its validity argument, stated here so it travels with the code:

  Every customer has exactly one successor (the literal next node in its route)
  and exactly one predecessor, so successors are distinct among customers.
  Each trip is satellite -> customers -> satellite, except the last trip of each
  vehicle which ends at the depot; so the number of customer->(satellite|depot)
  arcs equals the number of trips, which is >= trips_lb = ceil(demand/Q).
  Pricing a terminal arc at min(min_s D[i][s], D[i][0]) and a customer arc at
  D[i][j] EXACTLY means no triangle inequality is needed -- unlike the clique
  term, this is safe at proximity 0.1 where D is not metric.
  The LP relaxation of that program is a valid LB on its integer optimum, so a
  fractional solution costs validity nothing.

Resumable: appends to JSON, skips completed (cell,size) pairs.
"""
import sys, os, json, time, math
sys.path.insert(0, ".")
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix, csgraph
from build_instance import build
from crossfeed.check_cuts import cut_bounds
from crossfeed.fullset_bound import assignment_dist_lb, fullset_bound

# ARG CHECK FIRST, before any indexing -- otherwise a bare invocation dies with an IndexError
# instead of the message that tells the caller what is missing.
if len(sys.argv) < 4:
    sys.exit("usage: ab4_grid.py OUT SIZES PROXIMITY\n"
             "  PROXIMITY is REQUIRED, and which value is comparable depends on the EXHIBIT:\n"
             "    0.0          Tables 3 and 4 (|C| = 10/20/30/50)  -- basis INFERRED\n"
             "    0.1          Table 6 (|C| = 100), Fig. 5 (10-50) -- basis STATED\n"
             "    0.2/0.3/0.4  Fig. 4 proximity sweep, |C| = 50 ONLY\n"
             "  See validation/AMBIGUITY_REGISTER.md A3. An earlier version of this message said\n"
             "  0.1 must NEVER be compared against K. That was WRONG: Table 6 and Fig. 5 are\n"
             "  both at 0.1 and both are theirs.")

OUT = sys.argv[1]
SIZES = [int(x) for x in sys.argv[2].split(",")]

# PROXIMITY IS A REQUIRED ARGUMENT. It used to be `0.1 if size == 100 else 0.0`, hard-coded at the
# loop head, which silently produced an n100 grid that could not be compared with K's published
# tables -- their base scenario is proximity 0.0 (see section 3, "Fidelity of our reproduction").
# Every other size was comparable and n100 was not, and nothing anywhere said so. Requiring the
# value at the command line means the choice is always recorded in the invocation.
PROX = float(sys.argv[3])
K_BASE_PROXIMITY = 0.0
CELLS = [f"C20{i}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)] + \
        [f"RC20{i}" for i in range(1, 9)]
BIG = 1e7


def mst_lb(p, C):
    idx = [0] + list(C)
    D = np.asarray(p.DistMatrix, float)[np.ix_(idx, idx)]
    return float(csgraph.minimum_spanning_tree(D).toarray().sum())


def twofactor_lb(p, C):
    D = np.asarray(p.DistMatrix, float); ends = [0] + list(p.satellites)
    return sum(sorted(D[i][j] for j in list(C) + ends if j != i)[0] +
               sorted(D[i][j] for j in list(C) + ends if j != i)[1] for i in C) / 2.0


def forced_terminal_lb(p, C, T):
    D = np.asarray(p.DistMatrix, float); S = list(p.satellites); n = len(C)
    sub = D[np.ix_(C, C)].copy(); np.fill_diagonal(sub, BIG)
    term = np.array([min(min(D[i][s] for s in S), D[i][0]) for i in C])
    cost = np.concatenate([sub.ravel(), term])
    Aeq = lil_matrix((n, n * n + n)); beq = np.ones(n)
    for a in range(n):
        Aeq[a, a * n:(a + 1) * n] = 1; Aeq[a, n * n + a] = 1
    Aub = lil_matrix((n + 1, n * n + n)); bub = np.ones(n + 1)
    for j in range(n):
        Aub[j, [a * n + j for a in range(n)]] = 1
    Aub[n, n * n:] = -1; bub[n] = -T
    r = linprog(cost, A_ub=Aub.tocsr(), b_ub=bub, A_eq=Aeq.tocsr(), b_eq=beq,
                bounds=(0, 1), method="highs")
    if not r.success:
        return None, None
    frac = float(np.abs(r.x - np.round(r.x)).max())
    return float(r.fun), frac


res = json.load(open(OUT)) if os.path.exists(OUT) else {}

# TWO REFUSALS, and the first one exists because the second was written wrong and did real damage.
#
# This script writes a FLAT mapping {"CELL|nSIZE": record}. The frozen artifacts consumed by
# analysis/manuscript_numbers.py have a DIFFERENT shape, {"provenance": {...}, "records": [...]},
# produced by a separate provenancing step. An earlier version of this guard iterated
# `res.values()` looking for a "prox" field; against the provenanced shape that yields the
# provenance dict and the records LIST, neither of which carries "prox", so the guard silently
# passed and this script began writing flat keys into a frozen artifact. It was recoverable only
# because the damage happened to be additive. Refuse the shape outright instead.
if isinstance(res, dict) and "records" in res and "provenance" in res:
    sys.exit(f"REFUSING TO WRITE: {OUT} is a FROZEN PROVENANCED artifact "
             f"({{provenance, records}}), not a grid working file. This script writes a flat "
             f"mapping and would corrupt it. Write to a new path, then provenance that.")

# ONE ARTIFACT, ONE PROXIMITY. Appending a 0.0 record to a file that already holds 0.1 records is
# what makes a mixed artifact, and a mixed artifact is undetectable downstream because every
# record in it looks individually well formed.
_existing = {r.get("prox") for r in res.values() if isinstance(r, dict) and "prox" in r}
if _existing and _existing != {PROX}:
    sys.exit(f"REFUSING TO MIX PROXIMITIES: {OUT} already holds records at {sorted(_existing)} "
             f"and this run is at {PROX}. Write a separate file.")
if PROX != K_BASE_PROXIMITY:
    print(f"*** WARNING: proximity {PROX} != K's base {K_BASE_PROXIMITY}. Records from this run "
          f"are a SENSITIVITY arm and must not be compared against K's published tables.",
          flush=True)

for size in SIZES:
    prox = PROX
    for cell in CELLS:
        key = f"{cell}|n{size}"
        if key in res:
            continue
        t0 = time.time()
        try:
            p = build(cell, size, wls=0.1, tau="formula", proximity=prox, time_limit=60)
        except Exception as e:
            res[key] = {"error": str(e)[:200]}; json.dump(stamped(res, __file__), open(OUT, "w"), indent=1)
            print(f"{key}: BUILD FAIL {e}", flush=True); continue
        C = list(p.customers); nd = p.nodes
        cb = cut_bounds(p, C); T = cb["trips_lb"]
        Hz = nd[0].latest - nd[0].earliest
        svc = sum(nd[x].serviceTime for x in C)
        ap = assignment_dist_lb(p, C); ms = mst_lb(p, C); tf = twofactor_lb(p, C)
        ft, frac = forced_terminal_lb(p, C, T)
        ft = ft if ft is not None else 0.0
        best = max(ap, ms, tf, ft)
        Vold = cb["routes_lb_time"]
        Vnew = max(1, math.ceil((svc + best + T * p.TransferDuration) / Hz))
        # AB4b: forced satellite multiplicity
        cap = max(1, int(Hz // p.TransferDuration)) if p.TransferDuration > 0 else 10**9
        smin = max(1, math.ceil(T / cap))
        ab1, parts = fullset_bound(p)
        # AB4 bound = AB1 with max(V_LB, Vnew) and travel term on `best`
        Vfin = max(parts["V_LB"], Vnew)
        ab4 = Vfin * p.penaltyCars + p.travelcoststreet * best + parts["water"]
        res[key] = dict(cell=cell, size=size, prox=prox, T=T, H=round(Hz, 1),
                        svc=round(svc, 1), TD=p.TransferDuration,
                        ap=round(ap, 2), mst=round(ms, 2), twofac=round(tf, 2),
                        forced=round(ft, 2), lp_frac=round(frac, 9) if frac else 0.0,
                        best_travel=round(best, 2), which=max(
                            [("AP", ap), ("MST", ms), ("2FAC", tf), ("FORCED", ft)],
                            key=lambda z: z[1])[0],
                        V_ab1=parts["V_LB"], V_new=Vnew, V_final=Vfin,
                        sat_min=smin, penaltyCars=p.penaltyCars,
                        ab1=round(ab1, 2), ab4=round(ab4, 2),
                        gain=round(ab4 - ab1, 2),
                        gain_pct=round((ab4 - ab1) / ab1 * 100, 3) if ab1 else 0.0,
                        secs=round(time.time() - t0, 1))
        json.dump(stamped(res, __file__), open(OUT, "w"), indent=1)
        r = res[key]
        print(f"{key:12} T={T:>3} trav {ap:8.1f}->{best:8.1f} ({r['which']:>6}) "
              f"V {r['V_ab1']}->{r['V_final']}  AB1={ab1:9.1f} AB4={ab4:9.1f} "
              f"{r['gain_pct']:+6.2f}%  {r['secs']:.0f}s", flush=True)
print("AB4 GRID DONE", flush=True)
