"""greedy26.py -- A CONSTRUCTIVE PRIMAL, BUILT FROM SCRATCH, WITH CONSTRAINT (26) EMBEDDED.

AUTHOR, 2026-09-19: *"Create FROM SCRATCH a greedy generator whe C26 is fully embedded."*

Replaces feasible_construct.py, which was DESTROYED. Two things were wrong with it and only one
of them was (26).

  1. IT NEVER COMMITTED A TIMETABLE. It computed h_i in its route walk and u_i in try_transfer,
     both as LOCAL VARIABLES, and returned only (arcList, transferSet, hubs). Its docstring said
     the hubs were "informational; the subproblem re-optimizes hub choice itself". So it proved a
     feasible schedule EXISTED and threw the witness away, leaving the MILP to pick real times --
     and the MILP's model could not represent (26). Nothing in that chain ever checked a timetable
     it intended to keep.

  2. (26) WAS A PREFERENCE, NOT A CONSTRAINT. `hub_congestion` steered transfers toward
     less-loaded satellites and never refused one, so two transfers could land at the same
     satellite less than tau apart.

     Author, 2026-09-19: *"I dont want to resolve a routing which has been generated without
     validating its schedule apriori - it's patching crap."*

WHAT THIS FILE DOES INSTEAD. It commits (h, u) as it builds, and every commitment is checked
against the constraint that will later be verified -- there is no gap between what is constructed
and what is claimed. A candidate that cannot be scheduled is REFUSED at the moment of choice, not
discovered downstream.

SATELLITE BOOKING IS THE MECHANISM FOR (26). `booked[p]` holds the u values already committed at
satellite p. A new transfer at p must find a slot at least tau from every one of them; the slot is
pushed forward past conflicts, and if the push breaks the CDC window or the depot return, that
satellite is refused and the next is tried. If none survives, the transfer does not happen there.

IT BUILDS AGAINST THE VERIFIER'S OWN INSTANCE (instance_view.VInstance), not instanceGenerator's.
The two are meant to agree, but "meant to" is how this project got here: building against the
object that will do the checking removes the question entirely.

NO SOLVER. NO SEARCH. NO REPAIR. It is a greedy: it commits, and if it cannot commit feasibly it
declines. It never produces a solution it has not itself verified constraint by constraint.

Vessel routing is SINGLETON (one vessel per transfer, CDC -> p -> CDC). That is deliberate and it
is not free: it maximises nVessel and therefore the objective. It buys the property that matters
here -- C-VESSEL-SEQ has no consecutive pairs to satisfy, so vessel sequencing cannot interact
with (26) and a feasibility result is unambiguous. d17 records singleton_vessels=True as what
every production caller already uses.
"""
from __future__ import annotations

import instance_view
from instance_view import VInstance, LEFV_CAPACITY, VESSEL_CAPACITY

TOL = 1e-6


def _slot(booked_p, lb, tau):
    """Earliest u >= lb at a satellite that clears every booking there by >= tau.

    Bookings are points; the exclusion around each is the open interval (b - tau, b + tau). Sweep
    the sorted bookings once, jumping past each conflict: after jumping to b + tau the value only
    increases, so an earlier booking can never conflict again.
    """
    if tau <= 0:
        return lb
    u = lb
    for b in sorted(booked_p):
        if b - tau + TOL < u < b + tau - TOL:
            u = b + tau
    return u


class Greedy26:
    """Nearest-neighbour street routing with (26)-feasible transfer scheduling."""

    def __init__(self, inst: VInstance, transfer_every: int = 4, car_capacity=None):
        self.inst = inst
        self.transfer_every = transfer_every
        self.cap = LEFV_CAPACITY if car_capacity is None else car_capacity

        self.D = inst.D
        self.nd = inst.nodes
        self.depot = inst.depot
        self.CDC = inst.CDC
        self.sats = list(inst.satellites)
        self.tau = float(inst.tau)

        self.booked = {p: [] for p in self.sats}

    # ---------------------------------------------------------------- street feasibility
    def _h_ok(self, c, h):
        """Every bound leg C places on a committed h_c, checked before committing it."""
        nd, D, depot, tau = self.nd, self.D, self.depot, self.tau
        if h < nd[c].earliest - TOL:                                    # C-TW-lower
            return False
        if h > nd[c].latest + TOL:                                      # C-TW-upper
            return False
        if h < nd[depot].earliest + D[depot][c] - TOL:                  # C-DEPOT-REACH
            return False
        # C-DEPOT-UB: depot.latest - D[c][depot] - service_c - tau >= h
        if h > nd[depot].latest - D[c][depot] - nd[c].service - tau + TOL:
            return False
        return True

    # ---------------------------------------------------------------- (26)-aware transfer
    def _transfer(self, c, h_c, last_in_route):
        """Schedule a transfer after customer c. Returns (p, u) or None.

        EVERY constraint that will be verified on this u is enforced HERE:
          C-XFER-AFTER-SERVICE  u >= h_c + service_c + D[c][p]
          C-SYNC-lower          u >= CDC.earliest + D[CDC][p]
          C-SYNC-upper          u <= CDC.latest - tau - D[p][CDC]
          C-RETURN              u <= depot.latest - tau - D[p][depot]   (last transfer of a route)
          C26                   |u - b| >= tau for every b already booked at p
        """
        nd, D, CDC, depot, tau = self.nd, self.D, self.CDC, self.depot, self.tau
        best = None
        for p in self.sats:
            lb = max(h_c + nd[c].service + D[c][p], nd[CDC].earliest + D[CDC][p])
            ub = nd[CDC].latest - tau - D[p][CDC]
            if last_in_route:
                ub = min(ub, nd[depot].latest - tau - D[p][depot])
            if lb > ub + TOL:
                continue
            u = _slot(self.booked[p], lb, tau)        # (26): push past conflicts
            if u > ub + TOL:
                continue                              # the push broke a window -> refuse p
            key = (u, D[c][p] + D[p][CDC])            # earliest slot, then cheapest detour
            if best is None or key < best[0]:
                best = (key, p, u)
        if best is None:
            return None
        _, p, u = best
        return p, u

    # ---------------------------------------------------------------- driver
    def build(self):
        """Returns a COMPLETE solution dict, or None if no feasible construction was found."""
        nd, D, depot, CDC, tau = self.nd, self.D, self.depot, self.CDC, self.tau
        unvisited = set(self.inst.customers)

        arcs, transfers, hubs = [], [], []
        H, U = {}, {}
        n_cars = 0

        while unvisited:
            n_cars += 1
            cur = depot
            ready = float(nd[depot].earliest)   # time the vehicle can depart `cur`
            from_hub = None                     # satellite it is leaving, if it just transferred
            load = 0.0
            since_transfer = 0
            route = []

            while True:
                # --- choose the nearest feasible unvisited customer ----------------
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
                    break

                c, h = cand
                # --- decide whether this customer transfers ------------------------
                since_transfer += 1
                nxt_load = load + nd[c].demand
                must_transfer = (since_transfer >= self.transfer_every
                                 or nxt_load > self.cap - TOL
                                 or len(unvisited) == 1)

                # A route must END with a transfer, so if nothing else can follow, force one.
                res = self._transfer(c, h, last_in_route=True) if must_transfer else None
                if res is None and must_transfer:
                    # cannot close here; try a non-final transfer so the route may continue
                    res = self._transfer(c, h, last_in_route=False)
                    if res is None:
                        # this customer cannot carry a transfer at all -- do not commit it
                        break
                    closing = False
                elif res is not None:
                    closing = True
                else:
                    closing = False

                # commit the customer
                H[c] = h
                arcs.append([origin if origin == depot else cur, c] if cur == depot else [cur, c])
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
                    ready, from_hub = u, p
                    load = 0.0
                    since_transfer = 0
                    if closing:
                        arcs.append([c, depot])
                        break
                else:
                    ready, from_hub = h, None

            if not route:
                n_cars -= 1
                break                     # no progress possible -> stop rather than spin

            # every route must end with a transfer; if it did not, close it now
            if route[-1] not in transfers:
                last = route[-1]
                res = self._transfer(last, H[last], last_in_route=True)
                if res is None:
                    return None           # cannot legally close -> decline, never patch
                p, u = res
                U[last] = u
                transfers.append(last)
                hubs.append(p)
                self.booked[p].append(u)
                if [last, depot] not in arcs:
                    arcs.append([last, depot])

        if unvisited or not transfers:
            return None

        # --- C-DEPOT-TIME: h_0 must dominate every route's return ---------------
        h0 = float(nd[depot].earliest)
        hub_of = dict(zip(transfers, hubs))
        for r_last in {a[0] for a in arcs if a[1] == depot}:
            if r_last in hub_of:
                h0 = max(h0, U[r_last] + tau + D[hub_of[r_last]][depot])
            else:
                h0 = max(h0, H[r_last] + nd[r_last].service + D[r_last][depot])
        if h0 > nd[depot].latest + TOL:
            return None
        H[0] = h0

        # --- singleton vessels --------------------------------------------------
        yij = []
        for c in transfers:
            yij.append([CDC, c])
            yij.append([c, CDC])
        n_vessel = len(transfers)

        sol = {
            "xij": [list(a) for a in arcs],
            "vi": list(transfers),
            "hubs": list(hubs),
            "yij": yij,
            "nCars": n_cars,
            "nVessel": n_vessel,
            "hi": {str(k): float(v) for k, v in H.items()},
            "ui": {str(k): float(v) for k, v in U.items()},
        }
        sol["objVal"] = self._objective(sol, hub_of)
        sol["_posts_26"] = True
        sol["_timetable_source"] = "greedy26"
        return sol

    # ---------------------------------------------------------------- objective
    def _objective(self, sol, hub_of):
        """z = nCars*penaltyCars + nVessel*penaltyVessels + c_s*street + c_w*water.

        A street arc leaving a TRANSFER customer detours through that customer's satellite, so it
        costs D[i][p] + D[p][j], not D[i][j]. Water arcs are measured between HUBS, with the CDC
        mapping to itself.
        """
        D, CDC, inst = self.D, self.CDC, self.inst
        tset = set(sol["vi"])
        street = 0.0
        for i, j in sol["xij"]:
            if i in tset:
                p = hub_of[i]
                street += D[i][p] + D[p][j]
            else:
                street += D[i][j]
        water = 0.0
        for i, j in sol["yij"]:
            a = CDC if i == CDC else hub_of.get(i)
            b = CDC if j == CDC else hub_of.get(j)
            if a is None or b is None:
                return None
            water += D[a][b]
        return (sol["nCars"] * inst.penalty_cars + sol["nVessel"] * inst.penalty_vessels
                + inst.travelcoststreet * street + inst.travelcostwater * water)


def construct(inst: VInstance, transfer_every: int = 4, car_capacity=None):
    """Entry point. Returns a complete solution dict with a committed (h, u), or None."""
    return Greedy26(inst, transfer_every=transfer_every, car_capacity=car_capacity).build()
