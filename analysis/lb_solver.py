"""THE UNIFORM LOWER-BOUND SOLVER. One recipe, one budget, every cell, and a page you can audit.

    python analysis/lb_solver.py --cells R201 --sizes 50 [--tag a]

THE RECIPE, identical on every cell: AB4 first as the arithmetic floor, then TEP down the width
ladder coarsest-first, each rung inside the cell's remaining budget. The reported bound is the
max of the floor and every rung that CERTIFIED.

WHAT THIS FILE OWES THE READER, and where each debt is discharged. An independent audit on
2026-09-29 put four questions to the previous version and answered no to all four. Each answer
is now a named structure on the artifact.

  1  WHEN DID THE BOUND IMPROVE, AND WHAT PRODUCED IT?      -> `improvements`
     The old version updated `lb` once per rung, AFTER the rung returned, so its timestamp was
     the rung's completion and not the improvement's -- a 1,200 s offset on a long rung. Every
     event inside a rung carried the PRE-rung bound, and nothing flagged that a gain had
     happened at all: it could only be recovered by differencing a column. `composed_h`, the
     per-iteration composed bound that would have fixed exactly this, was computed and thrown
     away on the next line.
     Now: every rise is a row carrying the wall second, BOTH deterministic clocks, the width,
     the pricing stage, the iteration and the size of the gain -- and whether it is PROVISIONAL
     (an LP value mid-rung, no certificate, never reportable: the fit-or-drop rule) or
     CERTIFIED (a converged rung that raised the reported bound).

  2  WHICH GATE FIRED, AND WHAT DID IT DECIDE?               -> `gates`
     The old version recorded a gate only WHEN IT FIRED, so a gate that permitted work left no
     trace and its silence could not be told from never having been reached. The cost
     projection -- the commonest stop -- did not even set a stop reason.
     Now: every gate evaluation appends a row with its inputs, its threshold and GO/NO-GO,
     whether or not it fired, and `ladder_stop_reason` is set on every exit path including
     running the ladder to the end.

  3  THE FULL CODE AND EVERY PARAMETER                       -> `params`, `_provenance`
     About twenty parameters that determine the result were unrecorded, `smooth` among them --
     and `bound_certificate.ng_certified` BRANCHES on `smooth` through a default, so the
     certificate rule was being decided against an assumed value. `code_hash` covers a fixed
     nine-file list containing none of this solver. One named source, "analysis/build_instance.py",
     does not exist and was dropped in silence, leaving the file that determines `ab4` and
     `water_ab` unhashed.
     Now: every call-site and default parameter is on the page, the source path is corrected,
     and `stamp` adds `source_hash` over the sources actually in play plus `sources_unresolved`
     so a repeat of that failure is visible rather than silent.

  4  COULD A THIRD PARTY REPRODUCE IT?                       -> `reproducible`, and NO
     The audit found the decisive obstacle: the budget is WALL SECONDS, and so is the cost
     projection that chooses the next rung, so a third party on different hardware does not get
     a slower version of the same run -- they get a DIFFERENT SEQUENCE OF RUNGS, hence
     potentially a different bound and a different certificate class.
     THIS RELEASE DOES NOT FIX THAT, BY INSTRUCTION. Fixing it means changing the units of the
     deciding budget, which is an ALGORITHM change, and only observability was authorised. What
     this release does is stop the artifact from concealing it: every cell carries
     `reproducible`, `bound_by` and the full `gates` record, so the irreproducibility is on the
     page as a measured property rather than an unstated one. A previous version of this file
     made the change unasked; it was reverted.

THE CERTIFICATE CAN BE RE-CHECKED, NOT MERELY TRUSTED. Each rung carries `cert_evidence` --
stage, exhausted, cand, added, mispriced, slack, best_rc -- the exact fields
`bound_certificate.ng_certified` reads, plus the `smooth` it was decided under. Storing the
verdict and discarding the evidence is what that module's own contract forbids.

NOTHING HERE TOUCHES THE BANKED CORPUS. `tep_cg_bound.main()` names its output from
cell/size/delta, so a CLI call would overwrite banked artifacts. This calls `run()` in process,
which returns the result and writes nothing, and writes `lb_cell_<cell>_n<size>.json`.
"""
import argparse
import io
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
import verifier3 as V
import tep_cg_bound as T
from build_instance import build
from crossfeed.fullset_bound import fullset_bound
from k_comparison import k_proximity, proven_cells
from best_known import best_solution
from bound_certificate import certified, ng_certified
from stamp import stamped
import bound_source as BS
from dssr_certify import dssr, is_elementary

# `build_instance.py` lives at the REPOSITORY ROOT, not under analysis/. The previous spelling
# resolved to nothing and stamp dropped it without a word.
SOURCES = ("analysis/lb_solver.py", "analysis/tep_cg_bound.py", "analysis/tep_pricer.py",
           "crossfeed/fullset_bound.py", "build_instance.py",
           "analysis/bound_certificate.py", "analysis/stamp.py",
           "analysis/dssr_certify.py")   # the class upgrade determines the reported certificate

WALL_BACKSTOP = 1500.0   # the author's hard cap. A BACKSTOP, not the deciding budget.
LABEL_CAP = 3_000_000    # d598: successes peaked at 6,375,451 labels; failures sat at 12M+
MIN_RUNG_SECS = 20.0     # do not start a rung with less than this left
# THE COST EXPONENT, as the 38-cell grid ran it: the MAX of 45 banked cross-width pairs
# measured in WALL SECONDS (mean 1.38, min 0.36, p90 1.99), applied to wall seconds. Domain
# consistent.
#
# RECORDED HERE BECAUSE IT WAS MEASURED AND THEN REVERTED, NOT BECAUSE IT IS IN USE: the same
# 45 pairs measured in LABELS give mean 0.26, min 0.05, max 0.67 -- an order of magnitude lower,
# because wall cost grows with the MASTER while the pricer's label count grows far more slowly.
# That measurement matters only if the deciding budget is ever moved to labels. It is NOT, here:
# the author did not authorise an algorithm change, and switching the budget's units IS one.
COST_EXPONENT = 2.74
COST_EXPONENT_BASIS = ("max of 45 banked cross-width pairs measured in WALL SECONDS and applied "
                       "to wall seconds -- domain consistent. Label-domain figures for the same "
                       "pairs, measured but NOT used: mean 0.26, max 0.67.")
LABEL_DOMAIN_EXPONENT_MEASURED = dict(mean=0.26, min=0.05, max=0.67, p95=0.54, pairs=45,
                                      used=False,
                                      note="relevant only under a label budget, which is not in use")
DIVISORS = (60, 30, 20, 15, 10, 5, 2, 1)
THREADS = 4              # RT comparability: solo, 4 cores available, 4 free
AB4_BUILD = dict(wls=0.1, tau="formula", time_limit=60)   # recorded, not silently hard-coded
# The DSSR class-upgrade stage. The projection is the LARGEST banked DSSR wall at |C| = 50
# (R203, 50.3 s; the nine ran 7.9 to 50.3), used only until this run has measured one of its own.
REFUTE_TOL = 1e-6        # a bound above the incumbent by more than this is refuted, not rounded
# A SINGLE RUNG MAY NOT EAT THE ENVELOPE. Measured on RC204 n100, 2026-10-01: the first rung was
# handed the whole remaining budget, ran 1,518 s without converging, produced NO certificate, and
# the cell fell back to AB4 alone -- 1400.37 where the same cell had reached 2673.89 twenty
# minutes earlier when that rung happened to converge at 1,091 s. A 39 per cent run-to-run
# slowdown turned a good bound into none. So while rungs of ANOTHER KIND remain (the subset
# rungs, which are cheaper by construction because they solve a smaller customer set), the
# current kind is capped and the remainder is held for them.
RUNG_RESERVE_FRACTION = 0.25
# tep_cg_bound checks max_secs BETWEEN iterations (tep_cg_bound.py:529), so a rung overshoots by
# at most one iteration -- 50 to 138 s on RC204 n100. The margin reduces that overshoot; it
# cannot abolish it, and G5 still records a breach when one happens.
RUNG_MARGIN_S = 60.0
# THE K-LADDER: how many of the easiest customers the subset rung drops. Descending, so the
# cheapest and weakest rung runs first, exactly as the width ladder does. Derived from the size,
# never chosen per cell. The values are the ones the banked corpus used at |C| = 100.
K_LADDER = (48, 36, 24)
K_LADDER_MIN_SIZE = 100  # below this the whole instance is affordable and a subset adds nothing
# PER SIZE, because the stage does not cost the same everywhere: measured 7.9 to 50.3 s at
# |C| = 50 over nine cells, and 227 to 426 s at |C| = 100 over two (RC204 |C*|=1, 15,075 labels,
# 227 s; R211 |C*|=4, 65,971 labels, 426 s). A single n50-derived constant applied at n100 would
# wave the stage through at a fourth to an eighth of its true cost, which is how a budget is
# overrun. Unmeasured sizes inherit the largest figure, because OVER-estimating a projection
# makes the gate skip and under-estimating makes it overrun.
# THE AUTHOR'S GAIN GATE (2026-10-01): "if ng is a validated bound and DSSR cannot gain more
# than 1 unit, skip it." One unit of street cost, against bounds of 1,100 to 2,700, so the gate
# forgoes at most ~0.09 per cent of a cell and in the measured set at most 0.025 per cent.
DSSR_MIN_CEILING = 1.0
DSSR_SANDWICH_TOL = 1e-6   # below this the ceiling proves LP(R_e) == LP(R_ng); recorded, not used
DSSR_PROJECTION_BY_SIZE = {10: 10.0, 20: 20.0, 30: 30.0, 50: 50.0, 100: 450.0}
DSSR_PROJECTION_DEFAULT = 450.0
DSSR_PROJECTION_BASIS = ("per size: max observed DSSR wall -- 50.3 s over nine cells at |C| = 50 "
                         "(d631), 426 s over two at |C| = 100 (RC204 227 s, R211 426 s, "
                         "2026-10-01); an unmeasured size takes the largest, since over-estimating "
                         "makes the gate skip and under-estimating makes it overrun. Replaced by "
                         "this run's own measurement after the first upgrade")


def width_ladder(tau, default_delta):
    """Every admissible width at or below the default, coarsest first. Admissible means it
    divides tau exactly -- Master asserts it. Derived from the instance, not chosen per cell,
    so two cells with the same tau get the same ladder whatever their difficulty."""
    out = [d for d in DIVISORS
           if d <= default_delta + 1e-9 and abs(tau / d - round(tau / d)) < 1e-9]
    return out or [default_delta]


def ab4_floor(cell, size, prox):
    """Stage 0. The arithmetic floor, computed fresh so this solver charges what IT spends.
    A looked-up value would carry somebody else's runtime and nobody's code hash."""
    t0 = time.time()
    p = build(cell, size, proximity=prox, **AB4_BUILD)
    b, parts = fullset_bound(p)
    return dict(ab4=float(b), water=float(parts["water"]),
                fleet_term=float(parts["fleet_term"]), travel_term=float(parts["travel_term"]),
                secs=round(time.time() - t0, 3))


def solve_cell(cell, size, wall_backstop=WALL_BACKSTOP,
               ng=10, iters=400, seed_cols=("prio", "ts"), per_iter=1000):
    """AB4, then the width ladder, inside one DETERMINISTIC budget. Returns the row.

    START-STATE PRICING IS FIXED ON, NOT A PARAMETER. d436 measured the alternative against
    ground truth -- tep_exact_small, no pricer, full enumeration: the original pricer is
    REFUTED ON 14 OF 27 CELLS at |C| = 10, over-stating by up to 1.141 per cent WHILE PRINTING
    PROVEN True. A uniform solver must not expose a switch that silently decides validity.
    """
    prox = k_proximity(size)
    t_start = time.time()
    events, gates, improvements, rungs = [], [], [], []

    def clk():
        return round(time.time() - t_start, 3)

    def gate(name, fired, decision, **kw):
        """Every gate evaluation, fired or not, with its inputs and its GO/NO-GO."""
        gates.append(dict(gate=name, t=clk(), fired=bool(fired), decision=decision, **kw))

    def ev(stage, lb, work, labels, lp=None, note=None):
        events.append(dict(t=clk(), stage=stage, lb=round(lb, 6), work=round(work, 6),
                           labels=int(labels), lp=(round(lp, 6) if lp is not None else None),
                           note=note))

    def improve(kind, new, old, work, labels, **who):
        """A rise in the bound, timestamped on all three clocks and attributed to its producer."""
        improvements.append(dict(kind=kind, t=clk(), work=round(work, 6), labels=int(labels),
                                 lb_from=round(old, 6), lb_to=round(new, 6),
                                 gain=round(new - old, 6), **who))

    row = dict(cell=cell, size=size, proximity=prox, ng=ng,
               threads=None, solo=True, start_states=True, elem_pass=False)
    row["params"] = dict(wall_backstop_s=float(wall_backstop),
                         label_cap=LABEL_CAP, min_rung_secs=MIN_RUNG_SECS,
                         cost_exponent=COST_EXPONENT, cost_exponent_basis=COST_EXPONENT_BASIS,
                         divisors=list(DIVISORS), threads=THREADS, ng=int(ng),
                         iters_cap=int(iters), seed_cols=list(seed_cols), per_iter=int(per_iter),
                         ab4_build=dict(AB4_BUILD), start_states=True, elem_pass=False,
                         census=False, int_cars=False, primal=False)

    ab = ab4_floor(cell, size, prox)
    row.update(ab4=ab["ab4"], ab4_s=ab["secs"], water_ab=ab["water"],
               ab4_fleet_term=ab["fleet_term"], ab4_travel_term=ab["travel_term"])
    lb, carrier, cert = ab["ab4"], "ab4", None
    ev("ab4", lb, 0.0, 0, note="arithmetic floor, closed form")
    improve("floor", lb, 0.0, 0.0, 0, operator="ab4:fullset_bound", delta=None, iteration=None,
            certified=True, note="AB4 is deterministic arithmetic; valid by construction")

    # THE INCUMBENT IS FETCHED BEFORE THE LADDER, not after it, so the refutation gate can test
    # every reported value as it is produced instead of being a footnote on the finished row.
    ov = best_solution(cell, size)
    row["ov"] = float(ov[0]) if ov else None
    row["ov_source"] = (ov[2] if ov else None)
    gate("G10_incumbent_lookup", fired=(ov is None), decision=("NO-GO" if ov is None else "GO"),
         ov=row["ov"], source=row["ov_source"],
         note="best_solution requires a _verified primal; a null ov means none was found, so the "
              "refutation gate cannot run on this cell and says so rather than passing silently")
    refuted = {"hit": False}

    def refutes(value, where):
        """A lower bound above a feasible solution is refuted. Returns True when it fires."""
        if row["ov"] is None or value is None:
            gate("G12_refutation", fired=False, decision="GO", where=where, value=value,
                 note="no verified incumbent for this cell: the falsifier could not be run")
            return False
        bad = value > row["ov"] + REFUTE_TOL
        gate("G12_refutation", fired=bad, decision=("NO-GO" if bad else "GO"), where=where,
             value=round(float(value), 6), ov=row["ov"], source=row["ov_source"],
             margin=round(row["ov"] - float(value), 6),
             note=("REFUTED: a lower bound cannot exceed a verified feasible solution; either this "
                   "bound or that incumbent is wrong" if bad else
                   "bound below the incumbent, as a lower bound must be"))
        if bad:
            refuted["hit"] = True
            refuted["witness"] = dict(where=where, value=float(value), ov=row["ov"],
                                      ov_source=row["ov_source"],
                                      excess=float(value) - row["ov"])
        return bad

    inst = V.load_instance(cell, size, prox)
    dflt = T.default_delta(inst)
    # THE CHEAPEST FALSIFIER FIRST. If the arithmetic floor already exceeds a verified feasible
    # solution then the floor or that incumbent is wrong, no rung can repair either, and the
    # ladder is not entered at all rather than spending the budget before saying so.
    ladder = [] if refutes(lb, "ab4") else width_ladder(float(inst.tau), dflt)
    # ONE LADDER, TWO KINDS OF RUNG. A rung is (width, customer set, label); the subset rungs
    # solve the same master over the kept customers and compose with the SAME full-set water
    # term, so nothing downstream distinguishes them.
    rung_specs = [(d, None, "tep:d%g" % d) for d in ladder]
    if ladder and size >= K_LADDER_MIN_SIZE:
        try:
            from tep_easy_reduction import easiest_first
            order = easiest_first(cell, size)
            for k in K_LADDER:
                keep = sorted(set(order[k:]))
                if 0 < len(keep) < len(order):
                    rung_specs.append((dflt, keep, "sub:k%d" % k))
        except Exception as e:
            gate("G13_subset_unavailable", fired=True, decision="NO-GO",
                 error="%s: %s" % (type(e).__name__, str(e)[:160]),
                 note="the subset rungs could not be built; the width ladder stands alone")
    row["rung_specs"] = [(d, (len(c) if c else None), t) for d, c, t in rung_specs]
    row.update(tau=float(inst.tau), default_delta=dflt, ladder=ladder)

    work_cum, labels_cum = 0.0, 0
    dssr_seen = None          # this run's own largest DSSR wall, once it has measured one
    prev_delta, prev_secs = None, None
    stop_reason = ("REFUTED at the AB4 floor: the arithmetic bound exceeds the verified "
                   "incumbent" if refuted["hit"] else "ladder exhausted")
    bound_by, reproducible = "converged", True

    prev_kind = None
    # A KIND IS ABANDONED, NOT RE-TRIED. Rungs of one kind get strictly dearer down the list, so
    # once one is refused on cost or fails to certify, every later rung of that kind is worse.
    # The previous spelling set prev_kind = None and continued, which did NOT skip the kind -- it
    # retried the very next rung of the SAME kind with the cost history wiped, so its projection
    # collapsed to MIN_RUNG_SECS. Measured on RC204 n100 at backstop 900: d20 was refused after
    # 627.9 s, d10 was then projected at 20 s instead of ~4,200 s, was waved through, and ran
    # 431.7 s -- putting the cell 162 s over its envelope with no bound to show for it.
    abandoned = set()
    for delta, customers, tag in rung_specs:
        kind = "sub" if customers else "tep"
        if kind in abandoned:
            rungs.append(dict(delta=delta, rung=tag, status="skipped: kind abandoned", secs=0.0))
            continue
        if kind != prev_kind:
            # the projection compares widths on one customer set; it says nothing across a
            # change of set, so the first rung of a new kind is charged like any first rung
            prev_delta, prev_secs = None, None
            prev_kind = kind
        left = wall_backstop - (time.time() - t_start)
        wall_left = left
        # GATE G1 -- the cost projection, in WALL SECONDS as the 38-cell grid ran it. Halving
        # delta at least doubles the bucket count, so a rung is charged a projected
        # (prev/delta)^e x prev_secs and is not STARTED unless that fits. The CHANGE here is not
        # the arithmetic, which is unaltered, but that every evaluation is recorded -- the
        # previous version left no trace whenever it PERMITTED a rung, so a gate that allowed
        # work was indistinguishable from one never reached.
        need = MIN_RUNG_SECS
        if prev_secs is not None:
            need = max(MIN_RUNG_SECS, ((prev_delta / float(delta)) ** COST_EXPONENT) * prev_secs)
        go = left >= need
        gate("G1_cost_projection", fired=(not go), decision=("GO" if go else "NO-GO"),
             delta=delta, rung=tag, projected_s=round(need, 1), secs_left=round(left, 1),
             exponent=COST_EXPONENT, prev_delta=prev_delta,
             prev_secs=(None if prev_secs is None else round(prev_secs, 1)))
        if not go:
            rungs.append(dict(delta=delta, rung=tag, status="skipped on cost", secs=0.0,
                              projected_s=round(need, 1), secs_left=round(left, 1)))
            ev(tag, lb, work_cum, labels_cum,
               note="skipped on cost: projected %.0f s, %.0f s left" % (need, left))
            stop_reason = ("cost projection at %s: projected %.0f s against %.0f s left"
                           % (tag, need, left))
            # A COST REFUSAL MUST NOT ABANDON THE OTHER KIND OF RUNG. Width rungs get dearer as
            # delta falls, so the projection refuses them long before the envelope is spent --
            # and the SUBSET rungs behind them are cheaper by construction, because they solve a
            # smaller customer set. Breaking here is why the subset instrument had never once
            # executed: on RC204 n100 the ladder stopped at d10 (7,288 s projected) with 408 s
            # still in hand and three affordable subset rungs untried. Skip to the next rung of
            # a different kind and stop only when none remains.
            abandoned.add(kind)
            continue

        t1 = time.time()
        base_t = round(t1 - t_start, 3)
        # GATE G14 -- the rung's own budget, not the whole remainder. Held back while another
        # kind of rung is still queued, because an unconverged rung yields NOTHING and the
        # cheaper kind behind it may yet certify.
        others_left = any(("sub" if c else "tep") not in abandoned | {kind}
                          for _d, c, _t in rung_specs)
        reserve = (RUNG_RESERVE_FRACTION * wall_backstop) if others_left else 0.0
        margin = min(RUNG_MARGIN_S, 0.10 * max(wall_left, 0.0))
        rung_budget = wall_left - reserve - margin
        # NO FLOOR ON THE GRANT. max_secs is only tested BETWEEN iterations, so granting less
        # than a rung's first iteration costs does not stop it -- it guarantees an overrun of
        # that iteration's length. On RC204 n100 a 20 s grant produced a 431.7 s rung. If the
        # budget will not cover a sensible rung, the rung is not started at all.
        if rung_budget < MIN_RUNG_SECS:
            gate("G14_rung_budget", fired=True, decision="NO-GO", delta=delta, rung=tag,
                 secs_left=round(wall_left, 1), would_grant=round(rung_budget, 1),
                 reserved_s=round(reserve, 1), margin_s=round(margin, 1),
                 note="below MIN_RUNG_SECS after reserve and margin; starting it would overrun "
                      "by its first iteration, since max_secs is only checked between iterations")
            rungs.append(dict(delta=delta, rung=tag, status="skipped: budget below the minimum",
                              secs=0.0, secs_left=round(wall_left, 1)))
            stop_reason = "budget below the minimum at %s" % tag
            abandoned.add(kind)
            continue
        gate("G14_rung_budget", fired=(rung_budget < wall_left - 1e-9),
             decision="GO", delta=delta, rung=tag, secs_left=round(wall_left, 1),
             granted_s=round(rung_budget, 1), reserved_s=round(reserve, 1),
             margin_s=round(margin, 1), others_left=bool(others_left),
             note="a rung that does not converge produces no certificate, so the remainder is "
                  "kept for the cheaper kind still queued rather than spent here")
        try:
            r = T.run(cell, delta, iters, list(seed_cols), ng, per_iter, False, LABEL_CAP,
                      size=size, proximity=prox, max_secs=max(rung_budget, 1.0),
                      start_states=True, elem_pass=False, census=False,
                      threads=THREADS, return_master=True, customers=customers)
            M_rung = r.pop("master", None)   # gurobipy model: popped at once, never serialised
        except Exception as e:
            secs = round(time.time() - t1, 2)
            rungs.append(dict(delta=delta, secs=secs,
                              status="ERROR %s: %s" % (type(e).__name__, str(e)[:200])))
            gate("G9_exception", fired=True, decision="NO-GO", delta=delta, rung=tag,
                 error="%s: %s" % (type(e).__name__, str(e)[:200]))
            ev(tag, lb, work_cum, labels_cum, note="ERROR %s" % type(e).__name__)
            stop_reason = "exception at %s" % tag
            break

        secs = round(time.time() - t1, 2)
        # THE COST HISTORY IS RECORDED FOR ANY RUNG THAT RAN, certified or not. It was previously
        # set only at the very bottom of the body, which every early exit skips -- so a rung that
        # failed to certify left the next rung with no projection at all. That is how d10 came to
        # be projected at MIN_RUNG_SECS after d20 had just spent 627.9 s.
        prev_delta, prev_secs = float(delta), secs
        row["threads"] = r.get("threads")          # read BACK from the run, not asserted here
        det = r.get("det_ticks") or {}
        cls = "elementary" if certified(r) else ("ng" if ng_certified(r) else None)
        if r.get("bound_by") == "wall":
            bound_by, reproducible = "wall", False

        # Expand the rung's history: one event per CG iteration, and a PROVISIONAL improvement
        # row wherever the composed value rose. This is where `composed_h` was discarded before.
        w0, l0, run_labels, prov = work_cum, labels_cum, 0, lb
        for h in (r.get("hist") or []):
            run_labels += int(h.get("labels") or 0)     # hist labels are PER-ITERATION
            labels_cum = l0 + run_labels
            work_cum = w0 + float(h.get("work") or 0.0)  # hist work IS cumulative
            composed_h = (float(h["lp"]) + ab["water"]) if h.get("lp") is not None else None
            events.append(dict(
                t=round(base_t + float(h.get("secs") or 0.0), 3),
                stage=tag, lb=round(lb, 6),
                lb_provisional=(round(composed_h, 6) if composed_h is not None else None),
                work=round(work_cum, 6), labels=int(labels_cum),
                lp=(round(float(h["lp"]), 6) if h.get("lp") is not None else None),
                note="it %s stage %s%s" % (h.get("it"), h.get("stage"),
                                           " EXHAUSTED" if h.get("exhausted") else "")))
            if composed_h is not None and composed_h > prov + 1e-9:
                improve("provisional", composed_h, prov, work_cum, labels_cum,
                        operator="%s:stage%s" % (tag, h.get("stage")),
                        delta=delta, iteration=h.get("it"), certified=False,
                        note="LP value mid-rung; NOT reportable without a certificate")
                prov = composed_h
        work_cum = w0 + float(det.get("gurobi_work") or 0.0)
        labels_cum = l0 + int(det.get("pricer_labels") or run_labels)

        # GATE G3 -- the certificate, recorded WITH the evidence it was decided on, so a reader
        # can re-run bound_certificate against the artifact instead of trusting a string.
        gate("G3_certificate", fired=True, decision=("GO" if cls else "NO-GO"), delta=delta,
             certificate=cls, evidence=r.get("cert_evidence"), smooth=r.get("smooth"))

        # STAGE: DSSR CLASS UPGRADE (d631). An ng-class rung states LP(R_ng) <= LP(R_e) <= OPT and
        # may not be called elementary. DSSR grows a critical set with the SAME ng pricer over a
        # pool whose non-elementary columns are switched off, so termination certifies LP(R_e) --
        # riding on the converged master rather than redoing the search, which is what made the
        # old elementary pass unaffordable.
        lp_rung = r.get("lp_street")
        if cls == "ng" and M_rung is not None:
            left_d = wall_backstop - (time.time() - t_start)
            need_d = (dssr_seen if dssr_seen is not None
                      else DSSR_PROJECTION_BY_SIZE.get(size, DSSR_PROJECTION_DEFAULT))
            go_d = left_d >= need_d
            gate("G6_dssr_cost", fired=(not go_d), decision=("GO" if go_d else "NO-GO"),
                 delta=delta, projected_s=round(need_d, 1), secs_left=round(left_d, 1),
                 basis=(DSSR_PROJECTION_BASIS if dssr_seen is None else "this run's own DSSR wall"))
            if go_d:
                t_d = time.time()
                off = 0
                for key, var in M_rung.cols.items():
                    if not is_elementary(key[0]):
                        var.UB = 0.0
                        off += 1
                M_rung.solve()
                # GATE G6d -- THE A-PRIORI CEILING. The pool is elementary-only, so pool is a
                # subset of R_e and LP_pool >= LP(R_e); and R_e is a subset of R_ng, so
                # LP(R_e) >= LP(R_ng). DSSR's gain is therefore at most LP_pool - LP(R_ng),
                # known now, from the solve just performed. An inequality, not an estimate.
                pool_lp = float(M_rung.m.ObjVal)
                pool_slack = sum(v.X for v in M_rung.slack.values())
                ceiling = max(0.0, pool_lp - float(lp_rung)) if lp_rung is not None else None
                sandwich = (ceiling is not None and ceiling < DSSR_SANDWICH_TOL
                            and pool_slack < 1e-6)
                # SLACK VOIDS THE CEILING, so it must force the stage to RUN, never to skip.
                # With covering slack active the pool LP carries a penalty term and is no longer
                # the optimum of a restriction of R_e, so LP_pool >= LP(R_e) is not established
                # and the ceiling bounds nothing. Unmeasured in the 11 cells (slack was 0 on all),
                # which is exactly why it must fail safe rather than be assumed away.
                worth = (ceiling is None or pool_slack >= 1e-6
                         or ceiling >= DSSR_MIN_CEILING)
                gate("G6d_dssr_gain_ceiling", fired=(not worth),
                     decision=("GO" if worth else "NO-GO"), delta=delta, rung=tag,
                     ceiling=(None if ceiling is None else round(ceiling, 9)),
                     threshold=DSSR_MIN_CEILING, pool_lp=round(pool_lp, 9),
                     ng_lp=lp_rung, pool_slack=pool_slack,
                     sandwich_elementary=sandwich,
                     note="LP(R_ng) <= LP(R_e) <= LP_pool, so the gain cannot exceed "
                          "LP_pool - LP(R_ng); skipping forgoes at most that. The rung keeps its "
                          "ng-class bound, which ng_certified already accepts. `sandwich_elementary` "
                          "records that a ceiling below tolerance PROVES LP(R_e) == LP(R_ng) and the "
                          "class could be upgraded for free -- recorded only, it sets nothing")
                if not worth:
                    dssr_rec = dict(ran=False, ceiling=ceiling, threshold=DSSR_MIN_CEILING,
                                    pool_lp=pool_lp, pool_slack=pool_slack,
                                    sandwich_elementary=sandwich,
                                    why="a-priori ceiling %.9f below the %.1f unit threshold; the "
                                        "validated ng bound stands" % (ceiling or 0.0, DSSR_MIN_CEILING))
                    M_rung = None
                    composed = ((float(lp_rung) + ab["water"]) if (cls and lp_rung is not None) else None)
                    rungs.append(dict(delta=delta, rung=tag, kept=(len(customers) if customers else None),
                                      status=r.get("status"), secs=secs, lp_street=lp_rung,
                                      lp_street_ng=r.get("lp_street"), dssr=dssr_rec,
                                      certificate=cls, composed=composed,
                                      lp_at_ng_convergence=r.get("lp_at_ng_convergence"),
                                      cols=r.get("cols"), iters_run=r.get("iters"),
                                      gurobi_work=det.get("gurobi_work"),
                                      pricer_labels=det.get("pricer_labels"),
                                      bound_by=r.get("bound_by"), reproducible=r.get("reproducible"),
                                      cert_evidence=r.get("cert_evidence"), smooth=r.get("smooth"),
                                      run_params=r.get("params")))
                    gained = composed is not None and composed > lb + 1e-9
                    if gained:
                        improve("certified", composed, lb, work_cum, labels_cum, operator=tag,
                                delta=delta, iteration=r.get("iters"), certified=True,
                                certificate=cls, note="ng-class rung; DSSR skipped by G6d")
                        lb, carrier, cert = composed, tag, cls
                        if refutes(lb, tag):
                            stop_reason = "REFUTED at %s: bound above the verified incumbent" % tag
                            break
                    ev(tag, lb, work_cum, labels_cum, lp=lp_rung,
                       note="%s / ng (DSSR skipped: ceiling %.6f < %.1f)"
                            % (r.get("status"), ceiling or 0.0, DSSR_MIN_CEILING))
                    prev_delta, prev_secs = float(delta), secs
                    continue
                ok_d, rounds_d, Cstar, labels_d, added_d, lp_d = dssr(
                    M_rung, ng, LABEL_CAP, THREADS, lambda m: ev("dssr:d%g" % delta, lb, work_cum,
                                                                 labels_cum, note=m))
                slack_d = sum(v.X for v in M_rung.slack.values())
                secs_d = round(time.time() - t_d, 2)
                dssr_seen = max(dssr_seen or 0.0, secs_d)
                labels_cum += int(labels_d)
                work_cum += float(M_rung.det_work) - float((r.get("det_ticks") or {}).get("gurobi_work") or 0.0)
                secs += secs_d
                upgraded = bool(ok_d and slack_d < 1e-6)
                # G6b: a stronger certificate cannot LOWER a bound. Below the rung's own ng value
                # is a defect in this stage, not a weaker bound, and it is refused.
                regressed = upgraded and lp_rung is not None and lp_d < float(lp_rung) - 1e-6
                gate("G6b_dssr_monotone", fired=regressed,
                     decision=("NO-GO" if regressed else "GO"), delta=delta,
                     ng_lp=lp_rung, dssr_lp=lp_d,
                     note="R_e subset of R_ng(C*) subset of R_ng, so LP(R_e) >= LP(R_ng): a lower "
                          "value refutes the stage, and the ng-class bound is kept instead")
                dssr_rec = dict(ran=True, secs=secs_d, certified=upgraded, rounds=rounds_d,
                                critical_set=sorted(Cstar), critical_set_size=len(Cstar),
                                labels=int(labels_d), columns_added=int(added_d), slack=slack_d,
                                non_elementary_switched_off=off, ng_lp=lp_rung, dssr_lp=lp_d,
                                regressed=regressed)
                if upgraded and not regressed:
                    cls, lp_rung = "elementary", lp_d
                    gate("G6c_dssr_upgrade", fired=True, decision="GO", delta=delta,
                         ng_lp=dssr_rec["ng_lp"], dssr_lp=lp_d,
                         gain=(lp_d - float(dssr_rec["ng_lp"])) if dssr_rec["ng_lp"] is not None else None,
                         critical_set_size=len(Cstar), secs=secs_d)
                else:
                    gate("G6c_dssr_upgrade", fired=False, decision="NO-GO", delta=delta,
                         note=("DSSR did not converge; the ng-class bound stands as the interim "
                               "result" if not upgraded else "refused by G6b"))
            else:
                dssr_rec = dict(ran=False, why="skipped on cost: projected %.0f s, %.0f s left"
                                               % (need_d, left_d))
        else:
            dssr_rec = dict(ran=False, why=("rung certified elementary already" if cls == "elementary"
                                            else "no ng certificate to upgrade"))
        M_rung = None

        composed = ((float(lp_rung) + ab["water"])
                    if (cls and lp_rung is not None) else None)
        rungs.append(dict(delta=delta, rung=tag, kept=(len(customers) if customers else None),
                          status=r.get("status"), secs=secs,
                          lp_street=lp_rung, lp_street_ng=r.get("lp_street"), dssr=dssr_rec,
                          certificate=cls, composed=composed,
                          lp_at_ng_convergence=r.get("lp_at_ng_convergence"),
                          cols=r.get("cols"), iters_run=r.get("iters"),
                          gurobi_work=det.get("gurobi_work"),
                          pricer_labels=det.get("pricer_labels"),
                          bound_by=r.get("bound_by"), reproducible=r.get("reproducible"),
                          cert_evidence=r.get("cert_evidence"), smooth=r.get("smooth"),
                          run_params=r.get("params")))

        gained = composed is not None and composed > lb + 1e-9
        if gained:
            improve("certified", composed, lb, work_cum, labels_cum,
                    operator=tag, delta=delta, iteration=r.get("iters"),
                    certified=True, certificate=cls,
                    note="converged rung; this is the reportable bound")
            lb, carrier, cert = composed, tag, cls
            if refutes(lb, tag):
                stop_reason = "REFUTED at %s: bound above the verified incumbent" % tag
                ev(tag, lb, work_cum, labels_cum, note=stop_reason)
                break
        ev(tag, lb, work_cum, labels_cum, lp=r.get("lp_street"),
           note="%s / %s" % (r.get("status"), cls or "NO CERTIFICATE"))

        # GATE G2 -- stop on a rung that gained nothing. Recorded whether or not it fires.
        stop_now = (not gained) and cls is not None
        gate("G2_no_gain", fired=stop_now, decision=("NO-GO" if stop_now else "GO"),
             delta=delta, composed=composed, lb_now=round(lb, 6), gained=bool(gained),
             note="HEURISTIC: L-TEP-width gives monotonicity, not that a zero step implies "
                  "every later step is zero. It can only forgo gain, never invalidate a bound, "
                  "because what is reported is the floor and the best rung that certified.")
        if cls is None:
            # NO CERTIFICATE ON THIS RUNG. Under one ladder this must not abandon the rest:
            # a width rung that fails to certify says nothing about a subset rung, which solves a
            # smaller problem. Skip to the next rung of a DIFFERENT kind; stop only if none remains.
            gate("G4_certificate_stop", fired=True, decision="NO-GO", delta=delta, rung=tag,
                 status=r.get("status"),
                 note="skipping the rest of this kind; another kind of rung may still certify")
            stop_reason = "no certificate at %s (%s)" % (tag, r.get("status"))
            abandoned.add(kind)
            continue
        if stop_now:
            ev(tag, lb, work_cum, labels_cum, note="stop: rung gained nothing")
            stop_reason = "no gain at %s (heuristic)" % tag
            break

    row.update(rungs=rungs, events=events, gates=gates, improvements=improvements,
               lb=lb, lb_carrier=carrier, certificate=cert,
               refuted=bool(refuted["hit"]),
               refutation_witness=refuted.get("witness"),
               valid_bound=(not refuted["hit"]),
               lb_reported=(None if refuted["hit"] else lb),
               total_s=round(time.time() - t_start, 2),
               ladder_stop_reason=stop_reason, bound_by=bound_by, reproducible=reproducible)

    # GATE G5 -- the wall backstop. Recorded always; a cell the wall bound is NOT reproducible.
    over = row["total_s"] > wall_backstop
    gate("G5_wall_backstop", fired=over, decision=("NO-GO" if over else "GO"),
         total_s=row["total_s"], backstop_s=wall_backstop, bound_by=bound_by)
    row["cap_respected"] = not over
    row["det_ticks"] = dict(gurobi_work=round(work_cum, 6), pricer_labels=int(labels_cum))

    # the incumbent was fetched before the ladder (G10 above); only the derived figures here
    row["headroom"] = (row["ov"] - lb) if row["ov"] is not None else None
    row["headroom_pct"] = ((100.0 * row["headroom"] / row["ov"])
                           if row["ov"] is not None else None)
    refutes(lb, "final")

    tv, ts, why = BS.tep_bound(cell, size)
    try:
        bab = float((BS._ab(cell, size) or {}).get("ab4"))
    except Exception as e:
        bab, why = None, "%s; ab4 lookup raised %s" % (why, type(e).__name__)
    cands = [x for x in (tv, bab) if x is not None]
    bank = max(cands) if cands else None
    row["banked_best"] = bank
    row["banked_why"] = why            # previously computed and discarded
    row["delta_vs_banked"] = (lb - bank) if bank is not None else None
    gate("G11_banked_lookup", fired=(bank is None), decision=("NO-GO" if bank is None else "GO"),
         tep_bound=tv, ab4_bound=bab, reason=why)
    return row


def write_cell(row, rt_class="submission"):
    """Write the cell's artifact. SUBMISSION CLASS BY DEFAULT, which is a refusal, not a label.

    The target names a wall "measured on 4 cores with no co-tenant", so the grid's artifacts have
    to be quotable beside K's -- and rt_class.classify REFUSES to stamp submission unless threads
    == 4 and this is the only python process alive (d47). A cell run beside anything else
    therefore raises rather than quietly recording a wall that is the wall of a shared machine.
    Pass rt_class="diagnostic" deliberately for an exploratory run whose wall is not a claim.
    """
    p = os.path.join(ROOT, "runs", "oracle", "lb_cell_%s_n%d.json" % (row["cell"], row["size"]))
    d = stamped(dict(row), *SOURCES, det=row["det_ticks"], wall=row["total_s"],
                rt_class=rt_class, path=p)
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="+", required=True)
    ap.add_argument("--sizes", nargs="+", type=int, required=True)
    ap.add_argument("--wall-backstop", type=float, default=WALL_BACKSTOP)
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--tag", default="")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--rt-class", choices=("submission", "diagnostic"), default="submission",
                    help="submission (default): the wall may be quoted beside K's, and the write "
                         "is REFUSED unless 4 threads and single tenancy (d47). diagnostic: an "
                         "exploratory run whose wall is not a claim.")
    ap.add_argument("--all-cells", dest="k_unproven_only", action="store_false", default=True,
                    help="include cells K prove optimal. Calibration only: a bound there is not a claim.")
    a = ap.parse_args()

    print("UNIFORM LB SOLVER -- AB4 floor, then the width ladder")
    print("  DECIDING budget: %.0f s WALL. This is not reproducible across machines and every"
          % a.wall_backstop)
    print("  artifact says so in `reproducible` / `bound_by`; fixing it is an algorithm change.")
    print("  ng certificate (d596) | start-states ON (d436) | label cap %s (d598) | threads %d, solo"
          % ("{:,}".format(LABEL_CAP), THREADS))
    print("  %-6s %5s %10s %10s %9s %-6s %6s %8s %7s %9s"
          % ("cell", "size", "AB4", "LB", "carrier", "cert", "rungs", "tot s", "repro", "vs bank"))

    # THE ROSTER. A cell skipped by the K-proven filter or by --resume previously produced no
    # artifact and no record at all, so its absence could not be told from a crash or a refusal.
    roster, rows = [], []
    for size in a.sizes:
        skip = set(proven_cells(size)) if a.k_unproven_only else set()
        for cell in a.cells:
            done = os.path.join(ROOT, "runs", "oracle", "lb_cell_%s_n%d.json" % (cell, size))
            if cell in skip:
                roster.append(dict(cell=cell, size=size, ran=False, gate="G7_k_proven",
                                   decision="NO-GO",
                                   reason="K publish a gap of 0; a bound here is calibration, not a claim"))
                continue
            if a.resume and os.path.exists(done):
                roster.append(dict(cell=cell, size=size, ran=False, gate="G8_resume",
                                   decision="NO-GO", reason="artifact already present",
                                   path=os.path.relpath(done, ROOT)))
                print("  %-6s %5d  already banked, skipped" % (cell, size), flush=True)
                continue
            roster.append(dict(cell=cell, size=size, ran=True, gate=None, decision="GO"))
            r = solve_cell(cell, size, wall_backstop=a.wall_backstop, ng=a.ng)
            write_cell(r, rt_class=a.rt_class)
            rows.append(r)
            print("  %-6s %5d %10.2f %10.2f %9s %-6s %6d %8.1f %7s %9s"
                  % (r["cell"], r["size"], r["ab4"], r["lb"], r["lb_carrier"],
                     r["certificate"] or "-", len(r["rungs"]), r["total_s"],
                     "yes" if r["reproducible"] else "NO",
                     ("%+.2f" % r["delta_vs_banked"]) if r.get("delta_vs_banked") is not None else "-"),
                  flush=True)

    if not rows:
        print("  no cells ran"); return 0
    irr = [r for r in rows if not r["reproducible"]]
    tot = [r["total_s"] for r in rows]
    d = [r["delta_vs_banked"] for r in rows if r.get("delta_vs_banked") is not None]
    summary = dict(cells=len(rows),
                   irreproducible=["%s_n%d" % (r["cell"], r["size"]) for r in irr],
                   wall_s_mean=round(statistics.mean(tot), 1),
                   wall_s_min=min(tot), wall_s_max=max(tot),
                   wall_h_total=round(sum(tot) / 3600.0, 3),
                   vs_banked_mean=(round(statistics.mean(d), 4) if d else None),
                   vs_banked_min=(min(d) if d else None),
                   vs_banked_max=(max(d) if d else None),
                   improved=sum(1 for x in d if x > 1e-6),
                   equal=sum(1 for x in d if abs(x) <= 1e-6),
                   worse=sum(1 for x in d if x < -1e-6))
    print("\n  cells %d | irreproducible (wall-bound) %d | wall mean %.1f s max %.1f s"
          % (summary["cells"], len(irr), summary["wall_s_mean"], summary["wall_s_max"]))
    if d:
        print("  vs banked: mean %+.3f  min %+.3f  max %+.3f | improved %d equal %d worse %d"
              % (summary["vs_banked_mean"], summary["vs_banked_min"], summary["vs_banked_max"],
                 summary["improved"], summary["equal"], summary["worse"]))
    if irr:
        print("  *** %d cell(s) were stopped by the WALL backstop and are NOT reproducible: %s"
              % (len(irr), ", ".join(summary["irreproducible"])))

    det = dict(gurobi_work=round(sum(r["det_ticks"]["gurobi_work"] for r in rows), 6),
               pricer_labels=int(sum(r["det_ticks"]["pricer_labels"] for r in rows)))
    name = "lb_solver%s.json" % (("_" + a.tag) if a.tag else "")
    p = os.path.join(ROOT, "runs", "oracle", name)
    slim = [{k: v for k, v in r.items() if k not in ("events", "gates", "improvements")}
            for r in rows]
    payload = dict(rows=slim, roster=roster, summary=summary,
                   wall_backstop_s=a.wall_backstop,
                   algorithm="AB4 floor, then the width ladder inside one DETERMINISTIC label "
                             "budget; max over the floor and every certified rung",
                   certificate="ng (L-TEP-cert-ng); the elementary pass is dropped per d596",
                   deciding_clock="WALL SECONDS. Not reproducible across machines; every cell "
                                  "carries reproducible/bound_by so the limitation is on the page",
                   per_cell="runs/oracle/lb_cell_<cell>_n<size>.json carries events, gates, "
                            "improvements and cert_evidence")
    dd = stamped(payload, *SOURCES, det=det, wall=sum(tot))
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(dd, f, indent=1, default=str)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
    print("  wrote runs/oracle/%s and %d per-cell artifacts" % (name, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
