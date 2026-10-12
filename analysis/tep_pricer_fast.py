"""TEP dual leg, piece 1: an EXACT trip pricer (labeling with load and time; elementary or ng-route).

A trip column = an ordered customer sequence of any length with load <= Q, time-window feasible
from its earliest start, entered from the depot or a satellite and exited to a satellite (the
hub of its transfer). Given duals pi[c] on the customer covering rows and per-customer entry /
exit leg values (already carrying the car-flow duals, see tep_cg_bound), the pricer returns the
trips of most negative reduced cost
  rc(r) = entry[first] + scale * intra + exit[last] - sum_{c in r} pi[c].
Labels: (cost, time, load, seq) at a last customer; state key (last, S) with S the visited set
(elementary, ng=None) or the ng-memory (ng=k: the visited customers still remembered, i.e. those
in the neighbourhood of the current customer -- Baldacci et al.'s ng-route relaxation, whose
column set is a SUPERSET of the elementary one, so the bound built on it is valid, weaker).
Dominance: same key, one label no worse on cost, time and load.  Pure Python, no solver.

Pruning (elementary and ng alike, valid): a label is extended only if cost + exit[last] +
future_lb < rc_cut, where future_lb = -(G - sum_{j in seq} gain[j]) and gain[j] = max(0, pi[j] -
scale * min_in[j]) is the most any further customer can lower the reduced cost.
Memory guard: `label_cap` labels -> the run stops and reports exhausted=True (no bound then).

Self-test (no duals): must reproduce spp_lp_bound.enumerate_sets' minimum cost per set on the
<= 4-customer sets, and find every longer feasible trip the cap hid.
"""
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V

Q = 50.0


class Pricer:
    def __init__(self, inst, scale=1.0, table1=False, ng=None, customers=None):
        """scale: street cost per distance unit (travelcoststreet) so costs are in objective units.
        table1: tighten windows by K's Table 1 (h_i >= a_g + t_gi, h_i <= b_g - t_ig - tau_i - U).
        ng: None for elementary, else the ng-neighbourhood size (k nearest customers)."""
        self.inst = inst
        nd, D = inst.nodes, inst.D
        g, U = inst.depot, float(inst.tau)
        self.C = list(inst.customers) if customers is None else [c for c in inst.customers if c in set(customers)]
        self.e = {c: float(nd[c].earliest) for c in self.C}
        self.l = {c: float(nd[c].latest) for c in self.C}
        if table1:
            H0, H1 = float(nd[g].earliest), float(nd[g].latest)
            for c in self.C:
                self.e[c] = max(self.e[c], H0 + D[g][c])
                self.l[c] = min(self.l[c], H1 - D[c][g] - float(nd[c].service) - U)
        self.sv = {c: float(nd[c].service) for c in self.C}
        self.dem = {c: float(nd[c].demand) for c in self.C}
        self.scale = float(scale)
        self.entry0 = {c: self.scale * min([D[g][c]] + [D[p][c] for p in inst.satellites]) for c in self.C}
        self.exit0 = {c: self.scale * min(D[c][p] for p in inst.satellites) for c in self.C}
        self.D = D
        self.min_in = {c: min(D[i][c] for i in self.C if i != c) for c in self.C}
        self.succ = {i: [j for j in self.C if j != i and self.e[i] + self.sv[i] + D[i][j] <= self.l[j]] for i in self.C}
        self.ng = ng
        # FAST VARIANT (dependency-free, bit-exact): visited sets are Python int bitmasks instead of
        # frozensets -- O(1) bit ops, no per-candidate allocation/hashing, which is where the pure
        # label-setting loop spent its interpreter time. bit[c] is c's bit; set-ops map exactly:
        # frozenset & -> int &, | -> |, membership -> & bit. All arithmetic (costs, gain/pi sums,
        # dominance) is computed IDENTICALLY to tep_pricer.Pricer so output is bit-for-bit the same.
        self.bit = {c: 1 << i for i, c in enumerate(self.C)}
        if ng:
            self.nbr = {i: frozenset(sorted((j for j in self.C if j != i), key=lambda j: D[i][j])[:ng]) for i in self.C}
            self.nbrbit = {i: sum(self.bit[j] for j in self.nbr[i]) for i in self.C}

    def price(self, pi, maxlen=None, keep=200, rc_cut=-1e-9, entry=None, exit=None, label_cap=3_000_000, exit_fn=None, no_prune=False, inits=None):
        """Return (found, n_labels, exhausted): up to `keep` trips (rc, cost, seq) with rc < rc_cut,
        most negative first; cost is the trip's street cost with the SAME entry/exit values
        (rc + sum pi).  pi: dict customer -> dual (0 for the plain enumeration).
        exit_fn(last, t): optional time-aware exit value at a label whose earliest completion is t
        (must be >= exit[last], the per-customer minimum, which the completion bound keeps using)."""
        D, e, l, sv, dem, sc = self.D, self.e, self.l, self.sv, self.dem, self.scale
        entry = entry or self.entry0; exit = exit or self.exit0
        # piv caches pi.get(c,0.0) once per customer; every use below reads piv[c] (c in self.C),
        # so the emitted cost (sum piv over seq) and gain are computed from the SAME values in the
        # SAME order as tep_pricer.Pricer -> bit-for-bit identical floating point.
        piv = {c: pi.get(c, 0.0) for c in self.C}
        gain = {c: max(0.0, piv[c] - sc * self.min_in[c]) for c in self.C}
        G = sum(gain.values())
        ng = self.ng
        bit = self.bit
        nbrbit = self.nbrbit if ng else None
        succ = self.succ
        min_exit = self._min_exit(exit)
        labels = {}
        frontier = []
        if inits is None:
            # legacy start: the cheapest conceivable entry leg, a MINIMUM over every start node,
            # which underestimates the reduced cost by as much as 188 units (d436). 6th label field
            # is the visited (elementary) / ng-memory bitmask; start = just this customer's bit.
            for c in self.C:
                if e[c] > l[c]:
                    continue
                lab = (entry[c] - piv[c], e[c] + sv[c], dem[c], (c,), None, bit[c])
                labels[(c, bit[c])] = [lab]
                frontier.append(lab)
        else:
            # START-STATE PRICING (d437): one label per (real start node, bucket, first customer),
            # carrying that start's own dual, so the reduced cost is EXACT rather than an
            # underestimate. Pareto-pruned per first customer before the search begins.
            for c, cands in inits.items():
                keep_lab = []
                for cost0, t0, tag in sorted(cands):
                    if any(a0 <= cost0 + 1e-9 and t0_ <= t0 + 1e-9 for a0, t0_, _ in keep_lab):
                        continue
                    keep_lab = [x for x in keep_lab if not (cost0 <= x[0] and t0 <= x[1])]
                    keep_lab.append((cost0, t0, tag))
                for cost0, t0, tag in keep_lab:
                    lab = (cost0, t0, dem[c], (c,), tag, bit[c])
                    labels.setdefault((c, bit[c]), []).append(lab)
                    frontier.append(lab)
        found = []
        nlab = len(labels)
        exhausted = False
        while frontier and not exhausted:
            nxt = []
            for cost, t, load, seq, tag, m in frontier:
                last = seq[-1]
                rc = cost + (exit_fn(last, t) if exit_fn else exit[last])
                if rc < rc_cut:
                    found.append((rc, rc + sum(piv[c] for c in seq), seq, tag))
                if maxlen and len(seq) >= maxlen:
                    continue
                # valid completion bound: no extension can gain more than the gains still
                # available, and no exit leg is cheaper than the cheapest exit value
                if not no_prune and cost - (G - sum(gain[c] for c in seq)) + min_exit >= rc_cut:
                    continue
                # m is the carried bitmask: for elementary it is set(seq); for ng it is the bitmask
                # of _memory(seq), built by the same (m & nbrbit[j]) | bit[j] fold -> same key class.
                Dlast = D[last]
                for j in succ[last]:
                    bj = bit[j]
                    if (m & bj) or load + dem[j] > Q:   # m & bj  <=>  (j in mem) / (j in seq)
                        continue
                    arr = max(e[j], t + Dlast[j])
                    if arr > l[j]:
                        continue
                    nseq = seq + (j,)
                    nm = ((m & nbrbit[j]) | bj) if ng else (m | bj)
                    nl = (cost + sc * Dlast[j] - piv[j], arr + sv[j], load + dem[j], nseq, tag, nm)
                    key = (j, nm)
                    lst = labels.get(key)
                    if lst is None:
                        lst = labels[key] = []
                        nlab += 1
                        if nlab > label_cap:
                            exhausted = True
                            break
                    if any(a[0] <= nl[0] + 1e-9 and a[1] <= nl[1] + 1e-9 and a[2] <= nl[2] + 1e-9 for a in lst):
                        continue
                    lst[:] = [a for a in lst if not (nl[0] <= a[0] and nl[1] <= a[1] and nl[2] <= a[2])]
                    lst.append(nl)
                    nxt.append(nl)
                if exhausted:
                    break
            frontier = nxt
        found.sort()
        return found[:keep], nlab, exhausted

    def _memory(self, seq):
        """ng memory of a partial path: visited customers still in the neighbourhood chain."""
        mem = frozenset()
        for c in seq:
            mem = (mem & self.nbr[c]) | frozenset((c,))
        return mem

    def _min_exit(self, exit):
        v = getattr(self, "_min_exit_cache", None)
        if v is None or v[0] is not exit:
            self._min_exit_cache = (exit, min(exit.values()))
        return self._min_exit_cache[1]


def selftest(cell="R204", n_cust=40):
    """Memory-light self-test (d376): the pricer with zero duals on a REDUCED customer set
    (the first n_cust customers), <= 4 customers, against the DFS enumeration on the same set.
    The full pricer is exercised only inside column generation, where the duals prune."""
    from spp_lp_bound import enumerate_sets
    inst = V.load_instance(cell, 100, 0.1)
    keep = set(list(inst.customers)[:n_cust])

    class Sub:
        pass
    sub = Sub(); sub.nodes = inst.nodes; sub.D = inst.D; sub.depot = inst.depot; sub.satellites = inst.satellites; sub.tau = inst.tau
    sub.customers = [c for c in inst.customers if c in keep]
    t0 = time.time(); sets4 = enumerate_sets(sub, 4); t4 = time.time() - t0
    pr = Pricer(sub)
    t0 = time.time(); trips, nlab, exh = pr.price({}, maxlen=4, keep=10 ** 9, rc_cut=1e18); tp = time.time() - t0
    best = {}
    for rc, cost, seq, _tag in trips:
        k = frozenset(seq)
        if cost < best.get(k, 1e18): best[k] = cost
    mism = sum(1 for k, v in sets4.items() if abs(best.get(k, 1e18) - v) > 1e-6)
    print("%s, %d customers, <= 4: DFS %d sets (%.1f s) | pricer %d sets, %d labels (%.1f s) | cost mismatches %d | missing %d | exhausted %s"
          % (cell, n_cust, len(sets4), t4, len(best), nlab, tp, mism, sum(1 for k in sets4 if k not in best), exh))
    # ng relaxation: its column set is a superset of the elementary one, so for any duals its
    # most negative reduced cost is <= the elementary one (equal when its argmin is elementary)
    import random
    rng = random.Random(7)
    fails = 0
    for trial in range(5):
        pi = {c: rng.uniform(0.0, 60.0) for c in sub.customers}
        te, nle, _ = pr.price(pi, maxlen=5, keep=1, rc_cut=-1e-9, label_cap=1_000_000)
        tn, nln, _ = prn_price(sub, pi)
        if not te or not tn:
            print("  ng=8 trial %d: no negative column (elementary %d, ng %d) -> skipped" % (trial, len(te), len(tn)))
            continue
        me, mn = te[0][0], tn[0][0]
        elem_argmin = len(set(tn[0][2])) == len(tn[0][2])
        ok = mn <= me + 1e-9 and (not elem_argmin or abs(mn - me) < 1e-6)
        fails += 0 if ok else 1
        print("  ng=8 trial %d: elementary min rc %.3f (%d labels) | ng min rc %.3f (%d labels, argmin %s) -> %s"
              % (trial, me, nle, mn, nln, "elementary" if elem_argmin else "non-elementary", "OK" if ok else "FAIL"))
    print("  ng self-test failures: %d (must be 0)" % fails)


def prn_price(sub, pi):
    return Pricer(sub, ng=8).price(pi, maxlen=5, keep=1, rc_cut=-1e-9, label_cap=1_000_000)


if __name__ == "__main__":
    selftest(sys.argv[1] if len(sys.argv) > 1 else "R204", int(sys.argv[2]) if len(sys.argv) > 2 else 40)
