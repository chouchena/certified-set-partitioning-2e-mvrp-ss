"""THE MAXIMUM AN OPERATOR CAN WIN, COMPUTED BEFORE IT RUNS.

THE QUESTION (author, 2026-09-28): "good maths tool to measure max headroom any operator aims
toward". This generalises two instruments we already built for single cases -- the cut waiver
(d580, a ceiling for cuts) and step_value_preflight (d585, a ceiling for three campaign steps) --
to any operator, and says plainly where no ceiling exists.

THE TOOL. An operator O at state s searches a neighbourhood N_O(s). Its headroom is

    H_O(s)  =  f(s)  -  min { f(s') : s' in N_O(s) }

so measuring headroom IS solving the neighbourhood, and bounding headroom is bounding it from
below. Four regimes, each with a standard method:

  R1  N_O searchable exactly in polynomial time  -> H is EXACT and free.
      Very Large-Scale Neighborhood Search: Ahuja, Ergun, Orlin & Punnen (2002), Discrete Applied
      Mathematics 123(1-3) 75-102. Ours: reload placement is a DAG shortest path (d272, O(L^2),
      reproduces the MILP cut set on 176 of 255 routes).

  R2  N_O is a MIP restriction  -> the sub-MIP's DUAL BOUND is a valid ceiling at ANY truncation.
      You never have to solve it. Local branching: Fischetti & Lodi (2003), Mathematical
      Programming 98 23-47, adds Delta(x, xbar) <= k and hands back exactly this, parametric in k.
      RINS: Danna, Rothberg & Le Pape (2005), Mathematical Programming 102 71-90, for the
      LP-agreement fixing. Ours: d580 is the k = 0 case -- a cut on a FIXED pool cannot beat that
      pool's IP optimum, so the residual MIP gap is the ceiling. Every _freeze_* operator (d312)
      is an R2 operator whose ceiling nobody ever computed.

  R3  N_O not expressible -- randomised destroy-and-repair  -> NO ceiling exists.
      The statistical substitute is to fit the sample minimum to a 3-parameter Weibull and read
      the location parameter as the estimated optimum. The family is surveyed and criticised in
      Hooker/Rardin-style terms by "Statistical optimum estimation techniques for combinatorial
      optimization problems: a review and critique", Journal of Heuristics (2014),
      doi:10.1007/s10732-014-9243-4. A 2022 study -- "Can the global optimum of a combinatorial
      optimization problem be reliably estimated through extreme value theory?",
      doi:10.1016/j.swevo.2022.101166 -- reports that the estimate becomes inviable precisely
      when the algorithm is CONSISTENT, because a low-variability sample carries no tail to fit.
      NOTE ON SOURCING: that second paper is behind a paywall and was NOT read here; the finding
      is taken from its published abstract, so it is reported, not verified by us. It matches our
      own ALNS, which is consistent (0 degradations in 279 runs), so we do not fit it -- but the
      decision rests on our own measurement, not on the borrowed one.

  R4  THE FALLBACK THAT ACTUALLY COVERS R3 HERE. If the objective decomposes, f = sum_c f_c, and
      O can only move components C, then

          H_O(s)  <=  sum_{c in C} [ f_c(s) - LB_c ]

      which is valid, free, and tighter than the whole gap whenever O touches a proper subset.
      We have both halves already on disk: tep_cost_decomposition.json carries four components
      per cell, and the composed bound is LB = lp_street + water_ab (tep_cg_bound.py:812).

      WHAT IS PROVEN HERE AND WHAT IS NOT -- the load-bearing caveat of this whole file.
      The SUM h_street + h_water = OV - (lp_street + water_ab) is provably a valid ceiling on
      any operator whatsoever: it is the gap to a certified bound. The SPLIT is not proven.
      Certifying `composed <= OV` does NOT certify `water_ab <= water` and `lp_street <= street`
      separately -- a bound can be valid in total while over-charging one side and under-
      charging the other, and water_ab comes from AB4, a different model. So each per-component
      ceiling is an ASSUMPTION, monitored: this file re-tests it on every run and prints the
      result. Measured 2026-09-28 on the full grid: 0 violations of either side on 131 of 135
      certified cells (4 carry no water_ab). Zero violations is not a proof; if a violation ever
      appears, the split ceilings for that cell are void and only the sum survives.

THE TRAP, AND WE HAVE A SCAR FOR IT. d316 computed a 6.14% re-sequencing ceiling with per-trip
capacity OMITTED; d317 withdrew it; d318 measured what the constrained version actually realises
-- a median 0.30%, inside the noise floor, breaking vessel loads on 10 of 27 cells. A ceiling
taken over a RELAXED neighbourhood is a valid bound and a worthless forecast. So every row below
declares which constraints were dropped to obtain it, and a row with anything dropped is reported
as an upper bound only and NEVER as value "on the table".

REFUSALS. A ceiling built on an uncertified bound is not a ceiling: bound_certificate.certified()
gates every LB used here (d519), and a cell without one is reported as NO CEILING rather than
given a number from a raw `proven` flag.

    python analysis/operator_headroom.py                 # all sizes
    python analysis/operator_headroom.py --size 30       # one
"""
import argparse
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from bound_certificate import bound_class
from best_known import _bound_patterns, best_solution
from stamp import stamped

DECOMP = os.path.join(ROOT, "runs", "oracle", "tep_cost_decomposition.json")

# name -> (regime, components it can move, what was relaxed, tight-bound provider, note)
#
# WHY A PROVIDER COLUMN. The R4 decomposition ceiling is the SAME for every operator that moves
# the same components, so on its own it cannot tell `cuts` from `fleetcap` from `11 select` --
# all three would read 14.53% median at n30 and fire together, which gates nothing. An R1 or R2
# operator has its own, much tighter ceiling; the decomposition is the FALLBACK, used only where
# no tighter one exists. `provider` names the function that supplies the tight one. Where an
# operator declares a provider and the provider has no value for that cell, the row reports
# NOT COMPUTED -- it does NOT silently fall back to the loose number, because substituting a
# 14.53% ceiling for a 0.00% one is exactly how a waived operator gets run.
OPERATORS = [
    ("9 alns",        "R4", ("STREET", "WATER"), (), None,
     "re-solves the exact water path cover per repaired candidate, so it moves both sides"),
    ("8 refine",      "R4", ("STREET",), (), None,
     "moves customers between trips; water is recomputed post hoc, never searched"),
    ("11 select",     "R2", ("STREET",), (), "pool_ip",
     "re-partitions a fixed trip pool: an IP restriction, ceiling is that IP's own dual bound"),
    ("water re-opt",  "R4", ("WATER",), (), None,
     "path cover over fixed chains; cannot touch the street side at all"),
    ("cuts on master IP", "R2", ("STREET",), (), "residual_mip_gap",
     "d580: on a FIXED pool a cut cannot beat the pool IP optimum -- residual MIP gap"),
    ("13 fleetcap",   "R2", ("STREET",), (), "fleet_floor",
     "restriction N <= cars-1; ceiling is zero whenever cars is already at the fleet floor"),
    ("re-sequencing (Held-Karp)", "R1", ("STREET",), ("per-trip capacity", "vessel load"), None,
     "d316/d317/d318: EXACT on the relaxed neighbourhood, realised 0.30% median once "
     "capacity and vessel load were restored. Upper bound only."),
]


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def _cut_waiver():
    """d580's residual MIP gap per cell, as a percent -- the ceiling on ANY cut over a fixed pool.

    Reads runs/oracle/tep_cut_waiver_ceil.json rather than recomputing it, so there is exactly
    one authority for this number.
    """
    d = load(os.path.join(ROOT, "runs", "oracle", "tep_cut_waiver_ceil.json"))
    if not d:
        return {}
    return {(x["cell"], x["size"]): float(x["cap_pct"])
            for x in d.get("rows", []) if isinstance(x.get("cap_pct"), (int, float))}


def _fleet_floor():
    """cars - V_LB per cell. The fleet cap is a RESTRICTION, so its ceiling is zero wherever the
    incumbent already sits at the floor (d585's argument, generalised)."""
    out = {}
    for p, size in (("fleet_energetic_n100.json", 100),):
        d = load(os.path.join(ROOT, "runs", "oracle", p))
        for x in (d or {}).get("rows", []):
            vlb = max([v for v in (x.get("global_floor"), x.get("windowed"), x.get("real"))
                       if isinstance(v, (int, float))] or [None])
            # best_solution returns (value, label, path); the car count is in the artifact.
            bs = best_solution(x["cell"], size)
            cars = None
            if bs and len(bs) > 2 and isinstance(bs[2], str):
                cars = (load(bs[2] if os.path.isabs(bs[2]) else os.path.join(ROOT, bs[2]))
                        or {}).get("nCars")
            if isinstance(vlb, (int, float)) and isinstance(cars, (int, float)):
                out[(x["cell"], size)] = max(0.0, cars - vlb)
    return out


PROVIDERS = {"residual_mip_gap": _cut_waiver, "fleet_floor": _fleet_floor, "pool_ip": lambda: {}}


def certified_bound(cell, size):
    """(lp_street, water_ab, class) from a CERTIFIED artifact, or (None, None, None).

    Uses best_known._bound_patterns so this file does not re-derive the glob -- the exact defect
    that made baseline_audit report 108 of 135 when the truth was 135 of 135.
    """
    best = None
    for pat in _bound_patterns(cell, size):
        for p in sorted(__import__("glob").glob(os.path.join(ROOT, "runs", "oracle", pat))):
            d = load(p)
            if not d:
                continue
            cls = bound_class(d)
            if not cls:
                continue
            ls, wa = d.get("lp_street"), d.get("water_ab")
            if ls is None:
                continue
            if best is None or ls > best[0]:
                best = (float(ls), float(wa) if wa is not None else None, cls)
    return best if best else (None, None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100])
    ap.add_argument("--theta", type=float, default=0.5,
                    help="fire the operator only if its ceiling exceeds this %% of the objective")
    a = ap.parse_args()

    dec = load(DECOMP)
    if not dec:
        print("FATAL: %s missing -- the decomposition is the tool's input" % DECOMP)
        return 2
    rows = {(x["cell"], x["size"]): x for x in dec["rows"]}
    prov_tables = {k: f() for k, f in PROVIDERS.items()}

    print("OPERATOR HEADROOM -- the maximum each operator can win, before it runs")
    print("theta %.2f%% of the objective | LB used only where bound_certificate.certified()\n" % a.theta)

    out, nocert = [], []
    for size in a.sizes:
        cells = sorted({c for (c, s) in rows if s == size})
        if not cells:
            continue
        print("  n%d" % size)
        print("    %-7s %9s %9s %9s %9s %9s  %s"
              % ("cell", "OV", "street", "water", "H_street", "H_water", "certificate"))
        per_op = {}
        for cell in cells:
            x = rows[(cell, size)]
            ov = float(x["recomputed"])
            street = float(x["FleetStreet"]) + float(x["TravelStreet"])
            water = float(x["FleetWater"]) + float(x["TravelWater"])
            ls, wa, cls = certified_bound(cell, size)
            if ls is None:
                nocert.append((cell, size))
                print("    %-7s %9.2f %9.2f %9.2f %9s %9s  NO CERTIFICATE -> no ceiling"
                      % (cell, ov, street, water, "-", "-"))
                out.append(dict(cell=cell, size=size, ov=ov, street=street, water=water,
                                lp_street=None, water_ab=None, certificate=None,
                                h_street=None, h_water=None, operators={}))
                continue
            h_street = street - ls
            h_water = (water - wa) if wa is not None else None
            print("    %-7s %9.2f %9.2f %9.2f %9.2f %9s  %s"
                  % (cell, ov, street, water, h_street,
                     "%.2f" % h_water if h_water is not None else "n/a", cls))
            ops = {}
            for name, regime, comps, relaxed, provider, note in OPERATORS:
                parts, unknown = 0.0, False
                for c in comps:
                    if c == "STREET":
                        parts += max(0.0, h_street)
                    elif c == "WATER":
                        if h_water is None:
                            unknown = True
                        else:
                            parts += max(0.0, h_water)
                fallback_pct = None if unknown else 100.0 * parts / ov
                # A tighter, operator-specific ceiling REPLACES the decomposition fallback; if the
                # operator declares one and it is missing, the row is NOT COMPUTED, never the
                # fallback -- see the note on OPERATORS.
                if provider:
                    tight = prov_tables[provider].get((cell, size))
                    if provider == "fleet_floor":
                        # cars - V_LB is a count, not a value: it gates at zero, and where it is
                        # positive the VALUE ceiling is still the street decomposition.
                        ceil_pct = (None if tight is None else
                                    (0.0 if tight <= 0 else fallback_pct))
                        src = "fleet floor (cars - V_LB)"
                    else:
                        ceil_pct = tight
                        src = provider
                    if ceil_pct is None:
                        ops[name] = dict(regime=regime, components=list(comps),
                                         relaxed=list(relaxed), ceiling_pct=None,
                                         source="%s NOT COMPUTED" % provider,
                                         upper_bound_only=bool(relaxed), fire=None)
                        per_op.setdefault(name, []).append(None)
                        continue
                else:
                    ceil_pct, src = fallback_pct, "decomposition"
                ops[name] = dict(regime=regime, components=list(comps),
                                 relaxed=list(relaxed), ceiling_pct=ceil_pct, source=src,
                                 fallback_pct=fallback_pct,
                                 upper_bound_only=bool(relaxed),
                                 fire=(ceil_pct is not None and ceil_pct > a.theta))
                per_op.setdefault(name, []).append(ceil_pct)
            out.append(dict(cell=cell, size=size, ov=ov, street=street, water=water,
                            lp_street=ls, water_ab=wa, certificate=cls,
                            h_street=h_street, h_water=h_water, operators=ops))
        print()
        print("    %-28s %-4s %9s %9s %9s  %s"
              % ("operator", "reg", "median%", "max%", "fires", "ceiling is"))
        for name, regime, comps, relaxed, provider, note in OPERATORS:
            allv = per_op.get(name, [])
            v = [p for p in allv if p is not None]
            if not v:
                if allv:
                    print("    %-28s %-4s %8s %8s %6s/%-3d %s NOT COMPUTED on all %d cells"
                          % (name[:28], regime, "-", "-", "-", len(allv), provider, len(allv)))
                continue
            fires = sum(1 for p in v if p > a.theta)
            kind = ("EXACT" if regime == "R1" and not relaxed else
                    "UPPER BOUND ONLY (relaxed: %s)" % ", ".join(relaxed) if relaxed else
                    "valid bound" if regime == "R2" else "valid bound (decomposition)")
            miss = len(allv) - len(v)
            print("    %-28s %-4s %8.2f%% %8.2f%% %6d/%-3d %s%s"
                  % (name[:28], regime, statistics.median(v), max(v), fires, len(v), kind,
                     "  (%d cells NOT COMPUTED)" % miss if miss else ""))
            if relaxed:
                print("    %-28s %s" % ("", "^ d318 measured the CONSTRAINED value at 0.30% "
                                            "median -- never quote the ceiling without it"))
        print()

    # THE SPLIT IS AN ASSUMPTION, SO IT IS RE-TESTED EVERY RUN (see the docstring caveat).
    cert = [r for r in out if r.get("lp_street") is not None]
    wr = [r for r in cert if r.get("water_ab") is not None]
    v_water = [r["cell"] for r in wr if r["water_ab"] > r["water"] + 1e-9]
    v_street = [r["cell"] for r in cert if r["lp_street"] > r["street"] + 1e-9]
    print("  SPLIT CHECK  water_ab > water on %d of %d | lp_street > street on %d of %d"
          % (len(v_water), len(wr), len(v_street), len(cert)))
    if v_water or v_street:
        print("  *** SPLIT VIOLATED on %s -- the per-component ceilings for those cells are VOID;"
              % sorted(set(v_water + v_street))[:10])
        print("      only the SUM (OV - composed LB) survives there.")
    else:
        print("  no violation: the split is not proven, but it is not contradicted on any cell")
    print("  cells with no certificate (no ceiling derivable): %d" % len(nocert))
    print("  NOTE regime R3 (randomised destroy-repair) has NO ceiling by construction. The")
    print("       Weibull/EVT substitute is REPORTED inviable for a consistent algorithm (2022")
    print("       abstract, paper not read here); ours IS consistent by our own measurement --")
    print("       0 degradations in 279 runs -- so R4 decomposition is the fallback, not EVT.")

    p = os.path.join(ROOT, "runs", "oracle", "operator_headroom.json")
    json.dump(stamped(dict(rows=out, theta=a.theta, sizes=a.sizes,
                           split_violations=dict(water=v_water, street=v_street),
                           operators=[dict(name=n, regime=r, components=list(c),
                                           relaxed=list(x), note=t)
                                      for n, r, c, x, _pv, t in OPERATORS]),
                      "analysis/operator_headroom.py", "analysis/bound_certificate.py",
                      "analysis/best_known.py"),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
