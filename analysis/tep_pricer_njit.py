"""Pricer nopython kernel (investigation II, d652). General elementary+ng path: scale, start-states
(inits, pre-pruned in Python), time-aware exit_fn (inlined via sufmax + bucket), nonzero duals.

Visited/ng-memory set packed into ONE int64 (ids <128 = 7 bits, <=maxlen slots, sorted, 0-term =>
canonical; d644). Key = last<<(7*maxlen) | packed. Flat label pool + parent-pointers rebuild
sequences in Python. Dominance = typed.Dict[int64 -> slot] + fixed-K Pareto (14.6x, d652). All
arithmetic mirrors tep_pricer.Pricer, incl. forward-order gain/pi sums for bit-exactness."""
import math
import numpy as np
from numba import njit, types
from numba.typed import Dict

Q = 50.0


@njit(cache=True)
def _member(packed, j, maxlen):
    for s in range(maxlen):
        v = (packed >> (7 * s)) & 127
        if v == 0:
            return False
        if v == j:
            return True
    return False


@njit(cache=True)
def _insert(packed, j, maxlen):
    new = 0; out = 0; inserted = False
    for s in range(maxlen):
        v = (packed >> (7 * s)) & 127
        if v == 0:
            break
        if (not inserted) and j < v:
            new |= j << (7 * out); out += 1; inserted = True
        new |= v << (7 * out); out += 1
    if not inserted:
        new |= j << (7 * out)
    return new


@njit(cache=True)
def _ng_newmem(packed, j, maxlen, nbr_arr, nbr_cnt):
    """(mem & nbr[j]) | {j}, packed. mem members kept iff in j's ng-neighbourhood."""
    new = 0; out = 0; inserted = False
    nc = nbr_cnt[j]
    for s in range(maxlen):
        v = (packed >> (7 * s)) & 127
        if v == 0:
            break
        inn = False
        for q in range(nc):
            if nbr_arr[j, q] == v:
                inn = True; break
        if not inn:
            continue
        if (not inserted) and j < v:
            new |= j << (7 * out); out += 1; inserted = True
        new |= v << (7 * out); out += 1
    if not inserted:
        new |= j << (7 * out)
    return new


@njit(cache=True)
def _exitval(last, t, sats, D, sufmax, tc, H0, dl, nb, primal, exit0_last):
    best = 1e18
    for si in range(sats.shape[0]):
        p = sats[si]
        x = (t + D[last, p] - H0) / dl
        if primal:
            ba = int(math.ceil(x - 1e-9))
        else:
            ba = int(math.floor(x + 1e-9))
        if ba < 0:
            ba = 0
        if ba <= nb - 1:
            v = tc * D[last, p] - sufmax[si, ba]
            if v < best:
                best = v
    return best


@njit(cache=True)
def _price(cust, D, e, l, sv, dem, pi, gain, G, scale, entry, exit0, min_exit,
           succ_flat, succ_ptr, maxlen, rc_cut, label_cap, no_prune,
           ng, nbr_arr, nbr_cnt,
           use_exitfn, sats, sufmax, tc, H0, dl, nb, primal,
           in_c, in_cost, in_t, in_tag, n_in,
           par_cost, par_time, par_load, par_pix, par_next, head, p_cost, p_time, p_load, p_last, p_par, p_tag, p_key, p_depth,
           found_rc, found_pix):
    SHIFT = 1 << (7 * maxlen)
    store = Dict.empty(types.int64, types.int64)
    nslot = 0; np_ = 0; nf = 0; nlab = 0; pe = 0
    frontier = np.empty(p_cost.shape[0], dtype=np.int64); nfr = 0
    stk = np.empty(maxlen + 1, dtype=np.int64)
    exhausted = False
    # ---- start labels (unbounded linked-list Pareto store per key: head[s] -> par_next chain)
    if n_in > 0:
        for r in range(n_in):
            c = in_c[r]
            packed = c; key = c * SHIFT + packed
            p_cost[np_] = in_cost[r]; p_time[np_] = in_t[r]; p_load[np_] = dem[c]
            p_last[np_] = c; p_par[np_] = -1; p_tag[np_] = in_tag[r]; p_key[np_] = packed; p_depth[np_] = 1
            if key in store:
                s = store[key]
            else:
                s = nslot; store[key] = s; head[s] = -1; nslot += 1
            par_cost[pe] = p_cost[np_]; par_time[pe] = p_time[np_]; par_load[pe] = p_load[np_]
            par_pix[pe] = np_; par_next[pe] = head[s]; head[s] = pe; pe += 1
            frontier[nfr] = np_; nfr += 1; np_ += 1; nlab += 1
    else:
        for ci in range(cust.shape[0]):
            c = cust[ci]
            if e[c] > l[c]:
                continue
            packed = c; key = c * SHIFT + packed
            p_cost[np_] = entry[c] - pi[c]; p_time[np_] = e[c] + sv[c]; p_load[np_] = dem[c]
            p_last[np_] = c; p_par[np_] = -1; p_tag[np_] = -1; p_key[np_] = packed; p_depth[np_] = 1
            s = nslot; store[key] = s; head[s] = -1; nslot += 1
            par_cost[pe] = p_cost[np_]; par_time[pe] = p_time[np_]; par_load[pe] = p_load[np_]
            par_pix[pe] = np_; par_next[pe] = head[s]; head[s] = pe; pe += 1
            frontier[nfr] = np_; nfr += 1; np_ += 1; nlab += 1
    while nfr > 0 and not exhausted:
        nxt = np.empty(p_cost.shape[0], dtype=np.int64); nnx = 0
        for fi in range(nfr):
            i = frontier[fi]
            cost = p_cost[i]; t = p_time[i]; load = p_load[i]; last = p_last[i]
            packed = p_key[i]; depth = p_depth[i]
            if use_exitfn:
                xv = _exitval(last, t, sats, D, sufmax, tc, H0, dl, nb, primal, exit0[last])
            else:
                xv = exit0[last]
            rc = cost + xv
            if rc < rc_cut and nf < found_rc.shape[0]:
                found_rc[nf] = rc; found_pix[nf] = i; nf += 1
            if depth >= maxlen:
                continue
            if not no_prune:
                # gsum = sum gain over seq in FORWARD order (bit-exact w/ Python)
                d = 0; w = i
                while w != -1:
                    stk[d] = p_last[w]; d += 1; w = p_par[w]
                gs = 0.0
                for q in range(d - 1, -1, -1):
                    gs += gain[stk[q]]
                if cost - (G - gs) + min_exit >= rc_cut:
                    continue
            a0 = succ_ptr[last]; a1 = succ_ptr[last + 1]
            for a in range(a0, a1):
                j = succ_flat[a]
                if _member(packed, j, maxlen) or load + dem[j] > Q:
                    continue
                arr = e[j]; tj = t + D[last, j]
                if tj > arr:
                    arr = tj
                if arr > l[j]:
                    continue
                if ng > 0:
                    npacked = _ng_newmem(packed, j, maxlen, nbr_arr, nbr_cnt)
                else:
                    npacked = _insert(packed, j, maxlen)
                key = j * SHIFT + npacked
                ncost = cost + scale * D[last, j] - pi[j]
                ntime = arr + sv[j]; nload = load + dem[j]
                if key in store:
                    s = store[key]
                else:
                    if nslot >= head.shape[0]:
                        exhausted = True; break
                    s = nslot; store[key] = s; head[s] = -1; nslot += 1
                # dominated by any existing label at this key?
                pe_c = head[s]; dom = False
                while pe_c != -1:
                    if par_cost[pe_c] <= ncost + 1e-9 and par_time[pe_c] <= ntime + 1e-9 and par_load[pe_c] <= nload + 1e-9:
                        dom = True; break
                    pe_c = par_next[pe_c]
                if dom:
                    continue
                # unlink entries dominated BY the new label
                prev = -1; pe_c = head[s]
                while pe_c != -1:
                    nxe = par_next[pe_c]
                    if ncost <= par_cost[pe_c] and ntime <= par_time[pe_c] and nload <= par_load[pe_c]:
                        if prev == -1:
                            head[s] = nxe
                        else:
                            par_next[prev] = nxe
                    else:
                        prev = pe_c
                    pe_c = nxe
                if np_ >= p_cost.shape[0] or pe >= par_cost.shape[0]:
                    exhausted = True; break
                p_cost[np_] = ncost; p_time[np_] = ntime; p_load[np_] = nload
                p_last[np_] = j; p_par[np_] = i; p_tag[np_] = p_tag[i]; p_key[np_] = npacked; p_depth[np_] = depth + 1
                par_cost[pe] = ncost; par_time[pe] = ntime; par_load[pe] = nload
                par_pix[pe] = np_; par_next[pe] = head[s]; head[s] = pe; pe += 1
                nlab += 1
                nxt[nnx] = np_; nnx += 1; np_ += 1
                if nslot > label_cap:          # Python caps on distinct KEYS (tep_pricer:131), not labels
                    exhausted = True; break
            if exhausted:
                break
        frontier = nxt[:nnx]; nfr = nnx
    return nf, nlab, exhausted, np_, nslot


# ======== production drop-in: FastPricer (same interface as tep_pricer.Pricer) ========
import time as _time          # noqa: E402
import tep_pricer as _P       # noqa: E402

_MAXP = 6_000_000; _MAXS = 2_000_000; _MAXF = 2_000_000
_B = None


def _bufs():
    global _B
    if _B is None:
        _B = dict(par_cost=np.zeros(_MAXP), par_time=np.zeros(_MAXP), par_load=np.zeros(_MAXP),
                  par_pix=np.zeros(_MAXP, dtype=np.int64), par_next=np.zeros(_MAXP, dtype=np.int64),
                  head=np.zeros(_MAXS, dtype=np.int64),
                  p_cost=np.zeros(_MAXP), p_time=np.zeros(_MAXP), p_load=np.zeros(_MAXP),
                  p_last=np.zeros(_MAXP, dtype=np.int64), p_par=np.zeros(_MAXP, dtype=np.int64),
                  p_tag=np.zeros(_MAXP, dtype=np.int64), p_key=np.zeros(_MAXP, dtype=np.int64),
                  p_depth=np.zeros(_MAXP, dtype=np.int64),
                  found_rc=np.zeros(_MAXF), found_pix=np.zeros(_MAXF, dtype=np.int64))
    return _B


def run_njit(pr, pi, maxlen=None, keep=200, rc_cut=-1e-9, entry=None, exit=None,
             label_cap=3_000_000, exit_fn=None, no_prune=False, inits=None):
    """Marshal a tep_pricer.Pricer + its price() kwargs into the nopython kernel; return
    (found, n_labels, exhausted) exactly like tep_pricer.Pricer.price."""
    C = list(pr.C); D = np.asarray(pr.D, dtype=np.float64); N = D.shape[0]
    scale = float(pr.scale)
    ea = np.zeros(N); la = np.zeros(N); sv = np.zeros(N); dem = np.zeros(N)
    for c in C:
        ea[c] = pr.e[c]; la[c] = pr.l[c]; sv[c] = pr.sv[c]; dem[c] = pr.dem[c]
    piv = np.zeros(N)
    for c in C:
        piv[c] = pi.get(c, 0.0)
    gain = np.zeros(N); G = 0.0
    for c in C:
        g = piv[c] - scale * pr.min_in[c]
        if g < 0.0:
            g = 0.0
        gain[c] = g; G += g
    entry = entry or pr.entry0; exit = exit or pr.exit0
    en = np.zeros(N); ex = np.zeros(N)
    for c in C:
        en[c] = entry[c]; ex[c] = exit[c]
    min_exit = min(exit[c] for c in C)
    flat = []; ptr = np.zeros(N + 1, dtype=np.int64)
    for i in range(N):
        if i in pr.succ:
            for j in pr.succ[i]:
                flat.append(j)
        ptr[i + 1] = len(flat)
    succ_flat = np.array(flat, dtype=np.int64)
    ml = maxlen if maxlen else 12
    ng = pr.ng or 0
    if ng:
        ngmax = max(len(pr.nbr[i]) for i in C)
        nbr_arr = np.full((N, ngmax), -1, dtype=np.int64); nbr_cnt = np.zeros(N, dtype=np.int64)
        for i in C:
            xs = list(pr.nbr[i]); nbr_cnt[i] = len(xs)
            for q, x in enumerate(xs):
                nbr_arr[i, q] = x
    else:
        nbr_arr = np.zeros((1, 1), dtype=np.int64); nbr_cnt = np.zeros(N, dtype=np.int64)
    use_exitfn = 0; sats = np.zeros(1, dtype=np.int64); sufmax = np.zeros((1, 1)); tc = 1.0; H0 = 0.0; dl = 1.0; nb = 1; primal = False
    if exit_fn is not None:
        fv = exit_fn.__code__.co_freevars
        cell = {nm: c.cell_contents for nm, c in zip(fv, exit_fn.__closure__)}
        M = cell["self"]; sufmax_d = cell["sufmax"]
        sats = np.array(list(M.sats), dtype=np.int64); tc = float(M.tc); H0 = float(M.H0); dl = float(M.delta); nb = int(M.nb); primal = bool(M.primal)
        sufmax = np.zeros((sats.shape[0], nb))
        for si in range(sats.shape[0]):
            arr = sufmax_d[M.sats[si]]
            for bb in range(nb):
                sufmax[si, bb] = arr[bb]
        use_exitfn = 1
    tagmap = {}; tags = []
    in_c = []; in_cost = []; in_t = []; in_tag = []
    if inits is not None:
        for c, cands in inits.items():
            keep_lab = []
            for cost0, t0, tag in sorted(cands):
                if any(a0 <= cost0 + 1e-9 and t0_ <= t0 + 1e-9 for a0, t0_, _ in keep_lab):
                    continue
                keep_lab = [x for x in keep_lab if not (cost0 <= x[0] and t0 <= x[1])]
                keep_lab.append((cost0, t0, tag))
            for cost0, t0, tag in keep_lab:
                if tag not in tagmap:
                    tagmap[tag] = len(tags); tags.append(tag)
                in_c.append(c); in_cost.append(cost0); in_t.append(t0); in_tag.append(tagmap[tag])
    in_c = np.array(in_c, dtype=np.int64); in_cost = np.array(in_cost); in_t = np.array(in_t)
    in_tag = np.array(in_tag, dtype=np.int64); n_in = in_c.shape[0]
    b = _bufs()
    custs = np.array(C, dtype=np.int64)
    nf, nlab, exh, npool, nslot = _price(
        custs, D, ea, la, sv, dem, piv, gain, G, scale, en, ex, float(min_exit),
        succ_flat, ptr, ml, rc_cut, label_cap, no_prune, ng, nbr_arr, nbr_cnt,
        use_exitfn, sats, sufmax, tc, H0, dl, nb, primal,
        in_c, in_cost, in_t, in_tag, n_in,
        b["par_cost"], b["par_time"], b["par_load"], b["par_pix"], b["par_next"], b["head"], b["p_cost"], b["p_time"], b["p_load"],
        b["p_last"], b["p_par"], b["p_tag"], b["p_key"], b["p_depth"], b["found_rc"], b["found_pix"])
    out = []
    for fi in range(nf):
        pix = b["found_pix"][fi]; seq = []; w = pix
        while w != -1:
            seq.append(int(b["p_last"][w])); w = b["p_par"][w]
        seq = tuple(reversed(seq))
        cost = b["found_rc"][fi] + sum(piv[c] for c in seq)
        tg = tags[b["p_tag"][pix]] if (n_in > 0 and b["p_tag"][pix] >= 0) else None
        out.append((b["found_rc"][fi], cost, seq, tg))
    out.sort()
    return out[:keep], nlab, bool(exh)


class FastPricer(_P.Pricer):
    """Drop-in for tep_pricer.Pricer (d655): identical interface, nopython njit kernel, bit-exact."""
    def price(self, pi, maxlen=None, keep=200, rc_cut=-1e-9, entry=None, exit=None,
              label_cap=3_000_000, exit_fn=None, no_prune=False, inits=None):
        return run_njit(self, pi, maxlen=maxlen, keep=keep, rc_cut=rc_cut, entry=entry, exit=exit,
                        label_cap=label_cap, exit_fn=exit_fn, no_prune=no_prune, inits=inits)
