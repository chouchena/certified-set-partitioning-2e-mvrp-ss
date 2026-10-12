"""v2 primal engine (variant TWO-LEGS v2, d647): a numba-compiled, BIT-EXACT drop-in for
tep_refine._pass -- the time-window forward-propagation that is ~88% of ALNS wall.

This is a NEW module; tep_refine.py (frozen v1) is NOT modified. `_pass` here returns the SAME
(a, u, tload) dicts (or None) as tep_refine._pass for identical inputs, so patching
tep_refine._pass = tep_refine_njit._pass makes ALNS do the SAME search faster -- a different
VARIANT only because the extra speed buys more iterations within a wall cap (see d647; adoption
needs a fresh paired v1-vs-v2 OV design, not the corpus).

Design: instance-constant arrays (D, earliest/latest/service/demand) are built ONCE per instance
and cached; only the varying chains/hub/floor are marshalled per call. The njit kernel mirrors
tep_refine._pass lines 82-109 exactly (same float ops, same checks, same order)."""
import numpy as np
from numba import njit

import tep_refine as R   # constants only (LEFV_CAPACITY, TOL); not modified


@njit(cache=True)
def _pass_kernel(trips_flat, trip_off, chain_start, D, earliest, latest, service, demand,
                 hub_arr, floor_arr, dep, CDC, tau, H1, cap, TOL):
    N = earliest.shape[0]
    a = np.full(N, -1.0)
    u = np.full(N, -1.0)
    tload = np.full(N, -1.0)
    H0 = earliest[dep]
    nchains = chain_start.shape[0] - 1
    for ci in range(nchains):
        t = H0
        prev = dep
        for ti in range(chain_start[ci], chain_start[ci + 1]):
            load = 0.0
            lo = trip_off[ti]
            hi = trip_off[ti + 1]
            for k in range(lo, hi):
                c = trips_flat[k]
                t = max(t + D[prev, c], earliest[c])
                if t > latest[c] + TOL:
                    return 0, a, u, tload
                if t > H1 - D[c, dep] - service[c] - tau + TOL:
                    return 0, a, u, tload
                a[c] = t
                t += service[c]
                load += demand[c]
                prev = c
            if load > cap + TOL:
                return 0, a, u, tload
            last = trips_flat[hi - 1]
            if hub_arr[last] < 0:
                return 0, a, u, tload
            p = hub_arr[last]
            ut = t + D[last, p]
            v2 = H0 + D[CDC, p]
            if v2 > ut:
                ut = v2
            if floor_arr[last] > ut:
                ut = floor_arr[last]
            if ut + tau + D[p, dep] > H1 + TOL or ut + tau + D[p, CDC] > latest[CDC] + TOL:
                return 0, a, u, tload
            u[last] = ut
            tload[last] = load
            t = ut + tau
            prev = p
    return 1, a, u, tload


_INST = {}


def _inst_arrays(inst):
    key = id(inst)
    c = _INST.get(key)
    if c is None:
        nd = inst.nodes
        N = len(nd)
        D = np.asarray(inst.D, dtype=np.float64)
        ea = np.array([float(nd[i].earliest) for i in range(N)])
        la = np.array([float(nd[i].latest) for i in range(N)])
        sv = np.array([float(nd[i].service) for i in range(N)])
        dm = np.array([float(nd[i].demand) for i in range(N)])
        c = (N, D, ea, la, sv, dm, int(inst.depot), int(inst.CDC), float(inst.tau),
             float(nd[inst.depot].earliest), float(nd[inst.depot].latest))
        _INST[key] = c
    return c


def _pass(inst, chains, hub, floor):
    """Bit-exact drop-in for tep_refine._pass. Returns (a, u, tload) dicts or None."""
    N, D, ea, la, sv, dm, dep, CDC, tau, H0, H1 = _inst_arrays(inst)
    # marshal the VARYING parts only
    trips_flat = []
    trip_off = [0]
    chain_start = [0]
    for ch in chains:
        for trip in ch:
            trips_flat.extend(trip)
            trip_off.append(len(trips_flat))
        chain_start.append(len(trip_off) - 1)
    hub_arr = np.full(N, -1, dtype=np.int64)
    for cc, p in hub.items():
        hub_arr[cc] = p
    floor_arr = np.full(N, H0, dtype=np.float64)
    for cc, v in floor.items():
        floor_arr[cc] = float(v)
    ok, a_arr, u_arr, tload_arr = _pass_kernel(
        np.array(trips_flat, dtype=np.int64), np.array(trip_off, dtype=np.int64),
        np.array(chain_start, dtype=np.int64), D, ea, la, sv, dm, hub_arr, floor_arr,
        dep, CDC, tau, H1, float(R.LEFV_CAPACITY), float(R.TOL))
    if ok == 0:
        return None
    # rebuild v1-identical dicts from the chain structure
    a, u, tload = {}, {}, {}
    for ch in chains:
        for trip in ch:
            for cc in trip:
                a[cc] = a_arr[cc]
            last = trip[-1]
            u[last] = u_arr[last]
            tload[last] = tload_arr[last]
    return a, u, tload
