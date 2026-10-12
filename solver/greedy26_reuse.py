"""greedy26 with vehicle REUSE: continue from the satellite whenever a customer is still reachable.

WHY. The production constructor lands at 2.2-3.3x the final objective and the chain spends a
median 164 s -- 22.6 percent of the n100 budget, up to 54.7 percent -- climbing down from it
(d301). greedy26 already implements the right pick (nearest customer reachable inside its window,
gated by _h_ok) and (26)-aware transfer scheduling (_transfer). It lands at 37-40 cars for ONE
reason, greedy26.py lines 176-186: at every forced transfer it tries last_in_route=True first and
closes the route whenever that succeeds. A car never continues from a satellite, so cars == trips.

WHAT CHANGES, AND WHAT DOES NOT. The pick, _h_ok, _transfer, the booking table, the objective and
the output format are inherited untouched. Only the decision to STOP changes: after a transfer
whose time satisfies the closing bound, the route continues if any unvisited customer is reachable
from that satellite with a fresh load; it closes when none is. A closing-valid u also satisfies
the non-closing bound (closing = non-closing plus the depot-return term), so continuing from it
commits nothing the scheduler did not already accept.

MEASURED CEILING (d303), street cost only: a time-aware route-first tour lands at a median 0.98x
final across six cells (C201 1.33x, RC201 1.26x, R208 0.92x, RC204 0.88x). This module is the
same idea with the water side and (26) actually scheduled, so its objective will sit above that.

SAFETY. build() returns None whenever the scheduler declines, exactly as greedy26 does; nothing is
patched. The harness below verifies every output through verifier3 and reports failures rather
than dropping them. Adoption is gated on 27 of 27 clean.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.join(_ROOT, "analysis") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "analysis"))

from greedy26 import Greedy26, TOL


class Greedy26Reuse(Greedy26):

    def _reachable_from_hub(self, p, u, unvisited):
        """Any unvisited customer servable from satellite p departing at u + tau, fresh load?"""
        nd, D, tau = self.nd, self.D, self.tau
        for c in unvisited:
            if nd[c].demand > self.cap + TOL:
                continue
            h = max(u + tau + D[p][c], nd[c].earliest)
            if self._h_ok(c, h):
                return True
        return False

    def build(self):
        nd, D, depot, CDC, tau = self.nd, self.D, self.depot, self.CDC, self.tau
        unvisited = set(self.inst.customers)
        arcs, transfers, hubs = [], [], []
        H, U = {}, {}
        n_cars = 0

        while unvisited:
            n_cars += 1
            cur = depot
            ready = float(nd[depot].earliest)
            from_hub = None
            load = 0.0
            route = []
            last_closing_ok = False          # the last committed transfer satisfies C-RETURN

            while True:
                cand = None
                origin = from_hub if from_hub is not None else cur
                extra = tau if from_hub is not None else (nd[cur].service if cur != depot else 0.0)
                for c in sorted(unvisited, key=lambda k: D[origin][k]):
                    if load + nd[c].demand > self.cap + TOL:
                        continue
                    h = max(ready + extra + D[origin][c], nd[c].earliest)
                    if self._h_ok(c, h):
                        cand = (c, h)
                        break
                if cand is None:
                    # THE RELOAD MOVE. Nothing fits the load that is left -- but if something is
                    # reachable with a FRESH load, transfer here (non-closing) and keep the car.
                    # Without this, over-capacity candidates are filtered out before selection,
                    # must_transfer never fires on capacity, and every car does exactly one load:
                    # measured 16-29 cars against production's 7-13 on the first harness run.
                    if (cur != depot and cur not in transfers and from_hub is None
                            and any(nd[c].demand <= self.cap + TOL for c in unvisited)):
                        res = self._transfer(cur, H[cur], last_in_route=False)
                        if res is not None:
                            p, u = res
                            if self._reachable_from_hub(p, u, unvisited):
                                U[cur] = u
                                transfers.append(cur)
                                hubs.append(p)
                                self.booked[p].append(u)
                                ready, from_hub, load = u, p, 0.0
                                last_closing_ok = False
                                continue
                    break

                c, h = cand
                nxt_load = load + nd[c].demand
                # transfer only when capacity forces it or this is the last customer overall
                must_transfer = (nxt_load > self.cap - TOL or len(unvisited) == 1)

                res, closing_ok = None, False
                if must_transfer:
                    res = self._transfer(c, h, last_in_route=True)
                    closing_ok = res is not None
                    if res is None:
                        res = self._transfer(c, h, last_in_route=False)
                        if res is None:
                            break            # cannot carry a transfer here: do not commit it

                H[c] = h
                arcs.append([cur, c])
                route.append(c)
                unvisited.discard(c)
                load = nxt_load
                cur = c

                if res is not None:
                    p, u = res
                    U[c] = u
                    transfers.append(c)
                    hubs.append(p)
                    self.booked[p].append(u)
                    ready, from_hub, load = u, p, 0.0
                    last_closing_ok = closing_ok
                    # THE ONE CHANGE: keep going if anything is reachable from this satellite
                    if closing_ok and not self._reachable_from_hub(p, u, unvisited):
                        arcs.append([c, depot])
                        break
                    if not closing_ok:
                        # non-closing time: may continue, but cannot legally end here as-is
                        continue
                else:
                    ready, from_hub = h, None
                    last_closing_ok = False

            if not route:
                n_cars -= 1
                break

            last = route[-1]
            if [last, depot] not in arcs:
                if last in transfers:
                    if not last_closing_ok:
                        # its u was scheduled non-closing; re-check the depot-return bound
                        p = hubs[transfers.index(last)]
                        if U[last] > nd[depot].latest - tau - D[p][depot] + TOL:
                            self.declined = 'C-RETURN on a non-closing last transfer'
                            return None
                    arcs.append([last, depot])
                else:
                    res = self._transfer(last, H[last], last_in_route=True)
                    # BACK OFF rather than decline: if the last customer cannot close the route,
                    # give it back and try to close at the one before. Measured on the first
                    # 27-cell run: C203 and C204 declined here, every other cell verified clean.
                    while res is None and len(route) > 1:
                        given_back = route.pop()
                        unvisited.add(given_back)
                        H.pop(given_back, None)
                        arcs[:] = [a for a in arcs if a[1] != given_back]
                        last = route[-1]
                        if last in transfers:
                            res = (hubs[transfers.index(last)], U[last])
                            if U[last] > nd[depot].latest - tau - D[hubs[transfers.index(last)]][depot] + TOL:
                                res = None
                                continue
                            arcs.append([last, depot])
                            break
                        res = self._transfer(last, H[last], last_in_route=True)
                    if res is None:
                        self.declined = 'cannot schedule the closing transfer'
                        return None
                    if [last, depot] in arcs:
                        continue
                    p, u = res
                    U[last] = u
                    transfers.append(last)
                    hubs.append(p)
                    self.booked[p].append(u)
                    arcs.append([last, depot])

        if unvisited or not transfers:
            self.declined = 'customers left unvisited: %d' % len(unvisited)
            return None

        h0 = float(nd[depot].earliest)
        hub_of = dict(zip(transfers, hubs))
        for r_last in {a[0] for a in arcs if a[1] == depot}:
            if r_last in hub_of:
                h0 = max(h0, U[r_last] + tau + D[hub_of[r_last]][depot])
            else:
                h0 = max(h0, H[r_last] + nd[r_last].service + D[r_last][depot])
        if h0 > nd[depot].latest + TOL:
            self.declined = 'depot return past horizon'
            return None
        H[0] = h0

        # VESSELS IN TIME ORDER, NOT SINGLETONS. Singletons (one CDC->t->CDC trip per transfer,
        # d17) are always feasible but cost nVessel = |transfers| ~ 33-41 vessels against a final
        # of 6-8: measured 897-1424 objective units per cell, 20-25 percent of the objective.
        # Chaining by NEAREST hub fails (20) water sequencing on every cell tried, because a
        # vessel visiting t1 then t2 needs u2 >= u1 + tau + travel. Assigning transfers in
        # increasing u to the first vessel that can reach them in time and has capacity
        # respects (20) by construction: verified clean on 6 of 6 cells, 7-10 vessels.
        pred = {b: a for a, b in arcs}
        tset = set(transfers)
        loads = {}
        for t in transfers:
            L = nd[t].demand
            c = pred.get(t, depot)
            while c != depot and c not in tset:
                L += nd[c].demand
                c = pred.get(c, depot)
            loads[t] = L
        Qw = float(getattr(self.inst, "vessel_capacity", 250.0) or 250.0)
        vessels = []                        # [tour, load, last_hub, last_u]
        for t in sorted(transfers, key=lambda x: U[x]):
            for v in vessels:
                if v[1] + loads[t] <= Qw + TOL and v[3] + tau + D[v[2]][hub_of[t]] <= U[t] + TOL:
                    v[0].append(t)
                    v[1] += loads[t]
                    v[2], v[3] = hub_of[t], U[t]
                    break
            else:
                vessels.append([[t], loads[t], hub_of[t], U[t]])
        yij = []
        for v in vessels:
            prev = CDC
            for t in v[0]:
                yij.append([prev, t])
                prev = t
            yij.append([prev, CDC])
        sol = {
            "xij": [list(a) for a in arcs],
            "vi": list(transfers),
            "hubs": list(hubs),
            "yij": yij,
            "nCars": n_cars,
            "nVessel": len(vessels),
            "hi": {str(k): float(v) for k, v in H.items()},
            "ui": {str(k): float(v) for k, v in U.items()},
        }
        sol["objVal"] = self._objective(sol, hub_of)
        return sol


def construct(inst, car_capacity=None):
    return Greedy26Reuse(inst, transfer_every=10 ** 9, car_capacity=car_capacity).build()


if __name__ == "__main__":
    import glob
    import io
    import json
    import re
    import statistics as st
    import verifier3 as V
    from greedy26 import construct as construct_base

    cells = sys.argv[1].split(",") if len(sys.argv) > 1 else sorted(
        os.path.basename(f).split("_")[1]
        for f in glob.glob(os.path.join(_ROOT, "runs", "grid", "g_*_n100_p0.1_s0.json")))
    print("greedy26 WITH REUSE vs WITHOUT, n100 proximity 0.1 -- every output through verifier3\n")
    print("  %-7s %9s %5s %9s %5s %9s %9s %-14s" %
          ("cell", "base obj", "cars", "reuse obj", "cars", "final", "reuse/fin", "verifier3"))
    ratios, clean = [], 0
    for cell in cells:
        inst = V.load_instance(cell, 100, 0.1)
        base = construct_base(inst)
        sol = construct(inst)
        log = os.path.join(_ROOT, "logs", "grid_%s_n100_p0.1_s0.out" % cell)
        fin = None
        if os.path.exists(log):
            m = re.findall(r"\+improve obj=([0-9.]+)", io.open(log, encoding="utf-8", errors="replace").read())
            fin = float(m[-1]) if m else None
        if sol is None:
            print("  %-7s %9s %5s %9s" % (cell, ("%.0f" % base["objVal"]) if base else "-",
                                          base["nCars"] if base else "-", "DECLINED"))
            continue
        run = V.verify_solution(inst, sol, cell=cell, size=100, proximity=0.1, label="reuse")
        bad = [f for f in run.findings if f.severity != "TOLERANCE"]
        ok = (not bad) and (not run.blocking)
        clean += ok
        if fin:
            ratios.append(sol["objVal"] / fin)
        print("  %-7s %9.0f %5d %9.0f %5d %9s %8s %-14s"
              % (cell, base["objVal"] if base else float("nan"), base["nCars"] if base else -1,
                 sol["objVal"], sol["nCars"], ("%.0f" % fin) if fin else "-",
                 ("%.2fx" % (sol["objVal"] / fin)) if fin else "-",
                 "PASS" if ok else "FAIL %d %s" % (len(bad), (bad[0].cls if bad else "block"))))
    print()
    print("  verifier3 clean: %d of %d" % (clean, len(cells)))
    if ratios:
        print("  reuse construction / production final: median %.2fx  (base constructor is ~2.75x)"
              % st.median(ratios))
