"""Minimum vehicles to cover a solution's OWN trips, holding every trip's schedule fixed.

THE DECOMPOSITION. Once trips are formed, the fleet question is not routing -- it is
Stern & Ceder's problem: cover a fixed timetable with fewest vehicles. Trip i can precede trip j
on one vehicle iff the vehicle can finish i, reach j's satellite, transfer, and reach j's first
customer by the time j's first service is scheduled to start:

    end(i) + D[last_i][sat_j] + U + D[sat_j][first_j]  <=  start(j)

Minimum vehicles = |trips| - (maximum matching on that DAG).  Polynomial.

SOUNDNESS CHECK BUILT IN. The solution's own assignment is a valid cover, so the computed minimum
must be <= the solution's nCars on every cell. If it ever exceeds nCars, the trip extraction or
the compatibility test is wrong and every number here is void. That check fired on 24 of 27 cells
in the first implementation, which paired `hubs[k]` with a sorted `vi` rather than with chain
order -- the reason it is built in rather than run once.

NOTHING IS CLAIMED FROM A REDUCTION ALONE. A smaller cover says the fleet was reducible WITHOUT
changing any route; turning that into a solution still requires re-emitting and re-verifying it.

WHY THIS IS IN analysis/ RATHER THAN A SCRATCHPAD. Its result -- 0 of 27 reducible -- is the
decisive null cited by `validation/DESIGN_B_trip_based_primal.md` section 1 as the reason to change
formulation rather than to tune the search. A result carrying that much weight cannot have its
generating code live in a temp directory. Banked 2026-09-17 with the logic unchanged, so the
published figure reproduces.
"""
import argparse, glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from build_instance import build                                  # noqa: E402


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def trips_of(sol):
    """Split each vehicle's chain at transfer points. `vi` lists customers followed by a reload.

    Returns [(customer_sequence, satellite_or_None), ...].

    THE HUB PAIRING IS BY SORTED `vi`, NOT BY CHAIN ORDER, and getting this wrong is what the
    soundness check exists to catch. In the stored representation `vi` is ascending -- e.g. C201
    has `vi = [1, 4, 6, 8, 12, 13, 14, 15]` -- and `hubs` carries one satellite per `vi` entry in
    that same order. Consuming `hubs` sequentially while walking the vehicle chains therefore
    attaches the wrong satellite to almost every trip, which inflates the deadhead in the
    compatibility test, destroys the matching, and drives the computed cover ABOVE the solution's
    own `nCars` -- 24 of 27 cells when it was done that way.
    """
    succ = {}
    for a, b in sol["xij"]:
        succ.setdefault(a, []).append(b)
    vi = list(sol.get("vi") or [])
    hubs = list(sol.get("hubs") or [])
    # PAIRED IN STORED ORDER, matching verifier.py:317 exactly -- it is the independent authority
    # on this representation and its docstring states "hubs: satellite per transfer, parallel to
    # vi". `vi` happens to be ascending in all 385 stored solutions, so sorting it would agree
    # today, but agreeing with the verifier by COINCIDENCE rather than by construction is how the
    # two drift apart later.
    hub_of = dict(zip(vi, hubs))
    trans = set(vi)
    trips = []
    for s in list(succ.get(0, [])):
        cur, seq = s, []
        seen = 0
        while cur != 0 and seen < 500:
            seen += 1
            seq.append(cur)
            if cur in trans:
                trips.append((seq, hub_of.get(cur)))
                seq = []
            nxt = succ.get(cur)
            if not nxt:
                break
            cur = nxt[0]
        if seq:
            trips.append((seq, None))
    return [t for t in trips if t[0]]


def min_cover(cell, size):
    g = glob.glob(os.path.join(ROOT, "published_artifacts/solutions/best_%s_n%d.json" % (cell, size)))
    if not g:
        return None
    sol = json.load(open(g[0], encoding="utf-8"))
    p = build(cell, size, tau="formula")
    nd, D, U = p.nodes, p.DistMatrix, p.TransferDuration
    hi = {int(k): v for k, v in sol["hi"].items()}
    T = trips_of(sol)
    if not T:
        return None
    win = []
    for seq, hub in T:
        first, last = seq[0], seq[-1]
        if first not in hi or last not in hi:
            return None
        win.append((hi[first], hi[last] + nd[last].serviceTime, first, last, hub))
    n = len(win)
    adj = [[] for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            _si, ei, _fi, li, hub_i = win[i]
            sj, _ej, fj, _lj, _hj = win[j]
            # THE RELOAD BETWEEN TRIP i AND TRIP j HAPPENS AT TRIP i's HUB, not at trip j's.
            # `vi[k]` is a customer FOLLOWED BY a reload and `hubs[k]` is the satellite for THAT
            # reload, so the satellite is designated by the transfer that ENDS trip i. Using
            # trip j's hub instead made the deadhead wrong and drove the computed cover above the
            # solution's own nCars on 24 of 27 cells. Measured on R211, which one vehicle covers:
            # the j-hub rule fails 3 of 6 consecutive pairs, the i-hub rule passes all six, four
            # of them at exact equality -- the schedule is built tight against this rule.
            #
            # A trip whose hub is None ends a vehicle's chain: there is no reload after it, so it
            # cannot precede anything.
            if hub_i is None:
                continue
            if ei + D[li][hub_i] + U + D[hub_i][fj] <= sj + 1e-6:
                adj[i].append(j)
    matchR = [-1] * n

    def try_k(u, vis):
        for v in adj[u]:
            if not vis[v]:
                vis[v] = True
                if matchR[v] < 0 or try_k(matchR[v], vis):
                    matchR[v] = u
                    return True
        return False

    m = 0
    for u in range(n):
        if try_k(u, [False] * n):
            m += 1
    return n, n - m, sol["nCars"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    # default follows --size; a fixed n20 name would file n30 results under an n20 label.
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    import analysis.manuscript_numbers as M
    if a.out is None:
        a.out = "runs/path_cover_n%d.json" % a.size
    cells = sorted(M._cells(a.size))
    print("%-7s %7s %10s %8s %s" % ("cell", "trips", "min cover", "nCars", ""))
    bad, red, rows = [], [], []
    for c in cells:
        r = min_cover(c, a.size)
        if r is None:
            print("   %-6s  (trip extraction failed)" % c)
            rows.append(dict(cell=c, status="extraction_failed"))
            continue
        T, mc, nc = r
        flag = ""
        if mc > nc:
            flag = "*** UNSOUND: cover > nCars ***"
            bad.append(c)
        elif mc < nc:
            flag = "REDUCIBLE %d -> %d" % (nc, mc)
            red.append((c, nc, mc))
        rows.append(dict(cell=c, trips=T, min_cover=mc, nCars=nc,
                         status="unsound" if mc > nc else ("reducible" if mc < nc else "tight")))
        print("   %-6s %7d %10d %8d  %s" % (c, T, mc, nc, flag))
    print()
    print("unsound cells: %s" % (bad or "none"))
    print("reducible without changing any route: %s" % (red or "none"))
    print("  -> %d of %d cells reducible" % (len(red), len(cells)))
    json.dump(stamped(dict(size=a.size, unsound=bad, reducible=red, rows=rows), __file__),
              open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("\nwrote %s" % a.out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
