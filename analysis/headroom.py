"""LIVE per-operator ceilings, computed from the RUN'S OWN STATE. The gate the solver calls.

WHY THIS IS A SECOND FILE AND NOT AN IMPORT OF operator_headroom.
`analysis/operator_headroom.py` answers the grid-level question -- what could each operator have
won on the 135 banked cells -- and to do that it reads banked artifacts: best_solution, the
decomposition dump, the cut-waiver dump. A SOLVER MUST NOT DO THAT. A stage that decides whether
to run by consulting the best banked artifact is the best-of-over-banked-artifacts contamination
C1 exists to prevent, and it is the same objection that keeps Algorithm 1 line 13 out of the
baseline. So this module reads NOTHING from disk. Everything it needs is passed in from the run
that is happening: the verifier's own objective for the current incumbent, and the bound this run
computed. Same mathematics, no corpus.

THE MATHEMATICS is recorded in operator_headroom.py and in the ledger (2026-09-28). In one line:
an operator O searching N_O(s) has headroom H = f(s) - min{f(s') : s' in N_O(s)}, and the four
regimes are R1 exact poly-time search, R2 sub-MIP dual bound, R3 no ceiling exists, R4 component
decomposition as the fallback.

FAIL-OPEN, ALWAYS. If a ceiling cannot be computed -- no bound yet, no incumbent yet, a component
missing -- the gate returns FIRE with the reason. A missing ceiling must never skip a stage: the
whole point of a ceiling is that skipping is justified by a bound, and absence of a bound is not
a bound. Every skip this module authorises is backed by a number it computed.

THE SPLIT IS AN ASSUMPTION, NOT A THEOREM. h_street + h_water = OV - (lp_street + water_ab) is
provably valid: it is the gap to a certified bound. Splitting it per component is not proven --
certifying composed <= OV does not certify each term against its own side, and water_ab comes
from AB4, a different model. Measured 0 violations on 131 of 135 certified cells (2026-09-28).
So `components()` re-tests the split on the state in front of it and marks the result; a gate
built on a violated split degrades to the SUM, which is always safe.
"""

# operator -> (regime, components it can move, constraints relaxed to get the ceiling)
SPEC = {
    "1-6 floor": ("R4", ("STREET", "WATER"), ()),
    "1-6 ceil": ("R4", ("STREET", "WATER"), ()),
    "8 refine": ("R4", ("STREET",), ()),
    "9 alns": ("R4", ("STREET", "WATER"), ()),
    "11 select": ("R2", ("STREET",), ()),
    "13 fleetcap": ("R2", ("STREET",), ()),
}


def components(inst, objective):
    """The four cost parts of ONE solution, from the verifier's own objective dict.

    `objective` is verifier3's run.objective -- it already carries n_cars, n_vessel, street and
    water, so nothing here re-implements the cost model. A second cost model is precisely the
    duplicate-authority defect analysis/single_authority.py exists to stop, and
    tep_cost_decomposition.py takes the same route for the offline case.
    """
    if not objective:
        return None
    try:
        fs = float(inst.penalty_cars) * objective["n_cars"]
        ts = float(inst.travelcoststreet) * objective["street"]
        fw = float(inst.penalty_vessels) * objective["n_vessel"]
        tw = float(inst.travelcostwater) * objective["water"]
    except (KeyError, TypeError, AttributeError):
        return None
    return dict(FleetStreet=fs, TravelStreet=ts, FleetWater=fw, TravelWater=tw,
                STREET=fs + ts, WATER=fw + tw)


def ceilings(parts, ov, lp_street=None, water_ab=None, cars=None, v_lb=None, ip_gap_pct=None):
    """Per-operator ceilings as a percent of `ov`, plus the evidence for each.

    Returns {operator: dict(pct, source, regime, upper_bound_only, why)}; pct None means the
    ceiling could not be computed, which the gate reads as FIRE.
    """
    out = {}
    sum_valid = None                       # OV - composed LB: valid for ANY operator
    h = {}
    split_ok = True
    if parts and ov:
        if lp_street is not None:
            h["STREET"] = parts["STREET"] - lp_street
            if lp_street > parts["STREET"] + 1e-9:
                split_ok = False
        if water_ab is not None:
            h["WATER"] = parts["WATER"] - water_ab
            if water_ab > parts["WATER"] + 1e-9:
                split_ok = False
        if lp_street is not None and water_ab is not None:
            sum_valid = ov - (lp_street + water_ab)

    for name, (regime, comps, relaxed) in SPEC.items():
        pct, src, why = None, None, None

        # --- R2: an operator-specific sub-MIP bound REPLACES the decomposition, never falls back
        if name == "13 fleetcap":
            if cars is not None and v_lb is not None:
                if cars - v_lb < 1:
                    pct, src = 0.0, "fleet floor"
                    why = "cars %s == V_LB %s: the cap is a restriction, so it cannot help" % (cars, v_lb)
                else:
                    src, why = "fleet floor + decomposition", "cars %s above V_LB %s" % (cars, v_lb)
            else:
                out[name] = dict(pct=None, source="fleet floor NOT COMPUTED", regime=regime,
                                 upper_bound_only=False,
                                 why="no V_LB for this run" if cars is not None else "no car count")
                continue
        elif name == "11 select":
            if ip_gap_pct is not None:
                pct, src = float(ip_gap_pct), "pool IP residual gap"
                why = "a re-partition of a fixed pool cannot beat that pool's IP optimum"
            else:
                out[name] = dict(pct=None, source="pool IP gap NOT COMPUTED", regime=regime,
                                 upper_bound_only=False, why="the master IP gap was not recorded")
                continue

        # --- R4: the decomposition fallback
        if pct is None:
            if not parts or not ov:
                why = "no incumbent to decompose"
            elif not split_ok and sum_valid is not None:
                pct, src = 100.0 * max(0.0, sum_valid) / ov, "SUM (split violated)"
                why = "the component split is contradicted on this state; degraded to the total gap"
            else:
                need = [c for c in comps if c not in h]
                if need:
                    why = "no bound for %s" % ", ".join(need)
                else:
                    pct = 100.0 * sum(max(0.0, h[c]) for c in comps) / ov
                    src = src or "decomposition"
                    why = why or ("%s gap to the certified bound" % "+".join(comps))
        out[name] = dict(pct=pct, source=src or "NOT COMPUTED", regime=regime,
                         upper_bound_only=bool(relaxed), why=why)
    return out


def gate(name, ceils, theta):
    """(fire, reason). FAIL-OPEN: an uncomputable ceiling fires."""
    c = (ceils or {}).get(name)
    if not c or c.get("pct") is None:
        return True, "no ceiling (%s) -- firing, absence of a bound is not a bound" % (
            (c or {}).get("why") or "not evaluated")
    if c["pct"] <= theta:
        return False, "ceiling %.3f%% <= theta %.2f%% [%s: %s]" % (
            c["pct"], theta, c["source"], c["why"])
    return True, "ceiling %.3f%% > theta %.2f%% [%s]" % (c["pct"], theta, c["source"])
