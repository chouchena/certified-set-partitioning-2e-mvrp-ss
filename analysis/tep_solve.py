"""ONE VARIANT, ONE INVOCATION, ONE OV -- Algorithm 1 lines 1-6 and 8-13 wired in a row. (C1/C2/C3)

WHY THIS EXISTS. `paper/TEP_FORMULATION.md` Algorithm 1 specifies a fourteen-line pipeline.
`tep_cg_bound.master_ip` implements lines 1-6 and stops. Lines 8-13 -- refine, ALNS, select+chain,
the fleet cap -- exist only as standalone scripts that each read a banked incumbent off disk and
write their own stage directory. Run that way they produce a BEST-OF over stages, which is exactly
what fails C1: measured, 0 of 135 cells carry a single-variant OV, and every cell carries more
than one verified stage.

Wiring them in a row, each fed the previous stage's incumbent, makes one invocation produce one
OV. That is the whole point; the stages themselves are unchanged.

THE BANKING RULE, from the formulation section 6 and enforced at every stage boundary here: a
stage may replace the incumbent ONLY with a verifier3-clean solution of strictly smaller
objective, and the objective is the verifier's recomputation, never the stage's own claim.
`refine` and `alns` already anchor on the incumbent and return None when nothing beat it, so the
guard is belt and braces rather than a new invention.

WHAT IS RECORDED, because C2 and C3 fail on the existing corpus for want of exactly this: a run
id, the per-cell envelope and every stage's cap, and the full stage-by-stage story -- what each
stage was handed, what it returned, whether it was accepted or rejected and why, and its wall
time. All of it into the artifact, not only into a log.

SWITCHES. Every stage after line 6 can be turned off independently, so the pipeline doubles as
its own ablation: `--no-refine --no-alns --no-select --no-fleetcap`.

K-FREE. No stage here reaches the predecessors' formulation; verified by static call graph and by
runtime sys.modules on R208 n30 (ef3c6f3).

    python analysis/tep_solve.py R201 --size 10
    python analysis/tep_solve.py C201 R201 RC201 --size 30 --no-alns
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
import verifier3 as V
import headroom as HR
import bound_certificate as BC
import quarantine_guard as QG
import tep_cg_bound as T
from k_comparison import k_proximity
from stamp import stamped

TOL = 1e-6


def envelope_for(cell, size):
    """K's cap on our machine, less our own bound leg's wall on this cell (d245/d246/d250)."""
    try:
        import run_full_grid as G
        e = G.envelope(size, G.HW_FACTOR_ENVELOPE, cell)
        return float(e) if e else None
    except Exception:
        return None


def verified_value(inst, sol, cell, size, prox, label):
    """(objective, ok, findings, objective_dict). The objective is the VERIFIER'S, never the
    stage's claim. The dict is returned as well so the headroom gate can decompose the incumbent
    from the SAME verification, without a second cost model and without reading any artifact."""
    if sol is None:
        return None, False, ["no solution"], None
    run = V.verify_solution(inst, sol, cell=cell, size=size, proximity=prox, label=label)
    bad = [f.cls for f in run.findings if f.severity != "TOLERANCE"]
    ok = (not bad) and (not run.blocking)
    o = getattr(run, "objective", None)
    return (o.get("recomputed") if o else sol.get("objVal")), ok, bad[:6], o


# D2: the artifacts carried `sources: {}` because stamped() was called with no source paths, so
# nothing pinned a result to a code state -- the same condition that made the 563-artifact corpus
# unrecoverable. Every module this solver's result actually depends on is named here, and the
# list is asserted non-empty before any write.
SOURCES = ("analysis/tep_solve.py", "analysis/headroom.py", "analysis/tep_cg_bound.py",
           "analysis/tep_pricer.py", "analysis/tep_pricer_njit.py", "analysis/precluster_trips.py",
           "analysis/tep_chain_own_water.py", "analysis/tep_select_chain.py",
           "analysis/tep_refine.py", "analysis/tep_alns.py", "analysis/tep_alns_v2.py", "analysis/tep_water_opt.py",
           "analysis/bound_certificate.py", "analysis/fleet_energetic_bound.py",
           "crossfeed/fullset_bound.py", "build_instance.py",
           "solver/verifier3.py")


# Algorithm 1 lines 7 and 9: B := E - (time already spent). The envelope E is
# 5760 - LB_wall(cell) (d245/d246/d250). Until now the caps were argparse constants with no
# relation to E at all -- measured at n10, stages finished in 1.0-1.8 s against a 1,920 s cap,
# 0.02% of the envelope, so nothing was ever budget-bound and C2 had no per-cell cap to record.
#
# THESE SHARES ARE DECLARED, NOT CALIBRATED. Phase 3 of the trajectory is what sets the numbers;
# phase 2 only wires the arithmetic, so that a cap exists, is derived from E, and is recorded.
# They are stated here rather than buried in argparse so that changing them is a visible act.
SHARES = {"1-6": 0.55, "8 refine": 0.05, "9 alns": 0.30, "11 select": 0.10}

# Line 10: how many LP-positive columns join the two IP partitions in the pool. wide_pool used
# 70; the trajectory's figure is 45. Capped because the chaining variables are pairwise.
POOL_LP_LIMIT = 45


def _switches(a):
    return dict(refine=not a.no_refine, alns=not a.no_alns, select=not a.no_select,
                ceil=not a.no_ceil, fleetcap=False, theta=a.theta)


def _write(path, payload, rt_class=None):
    """Stamped, atomic, per-cell. Atomic because a kill mid-write leaves a truncated artifact
    that reads as valid JSON often enough to be dangerous. rt_class='submission' asserts the wall
    is quotable (threads==4 and single tenancy, enforced in stamp/rt_class -- refuses if false)."""
    d = stamped(payload, *SOURCES, rt_class=rt_class)
    if not d.get("sources"):
        raise RuntimeError("refusing to write %s with an empty sources map (D2)" % path)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def _quarantine_new(before, spool=None):
    """Untriaged quarantine run_ids that were NOT there when this run started.

    is_untriaged is imported, never re-derived: re-implementing that predicate is what made
    quarantine_watch call all 67 rows untriaged when each carried a decision id.
    """
    try:
        now = {r.get("run_id") for r in QG.rows() if QG.is_untriaged(r)}
    except Exception as e:
        if spool:
            spool("    quarantine unreadable (%s): NOT treated as clean" % type(e).__name__)
        return set()
    return now - before


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="+")
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--delta", type=float, default=None)
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--iters", type=int, default=60)
    ap.add_argument("--cg-secs", type=float, default=300.0)
    ap.add_argument("--ip-work", type=float, default=150.0)
    ap.add_argument("--refine-wall", type=float, default=120.0)
    ap.add_argument("--alns-iters", type=int, default=3000)
    ap.add_argument("--alns-wall", type=float, default=600.0)
    ap.add_argument("--select-cap", type=float, default=900.0)
    ap.add_argument("--no-refine", action="store_true")
    ap.add_argument("--no-alns", action="store_true")
    ap.add_argument("--no-select", action="store_true")
    ap.add_argument("--no-fleetcap", action="store_true")
    ap.add_argument("--fleetcap-rounds", type=int, default=6,
                    help="line 13 (d685): master fleet-cap re-partition rounds when the incumbent "
                         "uses more cars than the cap (cap = nCars-1, a K-blind restriction)")
    ap.add_argument("--fleetcap-ng", type=int, default=25,
                    help="line 13 (d690): ng-route size of the fleet-cap re-partition CG. Wider than "
                         "the default so the basin cell's master holds a chainable low-car partition; "
                         "basin-scoped (fires only when cars>cap) and accept-gated, so it cannot regress")
    ap.add_argument("--fleetcap-max-cars", type=int, default=4,
                    help="line 13 (d694): fire the fleet cap only when the incumbent fleet is small "
                         "(cars <= this). No cheap integer fleet LB is tight enough to gate on at large "
                         "fleets; the cap only wins where ceil(N_LP) is achievable (small fleets). "
                         "Skips the blind, useless 5-6 car re-partitions at n50/n100 (0 wins there)")
    ap.add_argument("--fleetcap-secs", type=float, default=240.0,
                    help="line 13 (d691): hard wall budget for the fleet-cap re-partition. A FALSE basin "
                         "(ceil(N_LP) loose; no lower-car solution exists) otherwise searches fruitlessly "
                         "for hundreds of seconds; this aborts it. A real win (RC202 ~188s) finishes under it")
    ap.add_argument("--fast-pricer", action="store_true",
                    help="use the numba nopython pricer (d655, bit-exact drop-in); stamps numba version")
    ap.add_argument("--no-ceil", action="store_true",
                    help="run only the floor arm of Algorithm 1 line 1")
    ap.add_argument("--rule-b", action="store_true",
                    help="Rule B (d670/d671): grow-k ALNS (tep_alns_v2) + helpless-stage gating; "
                         "frozen v1 ALNS byte-untouched and used when this flag is off")
    ap.add_argument("--grow-max", type=int, default=5,
                    help="grow-k max kick rung (d671); 0 reproduces the v1 base kick {2,3,4}")
    ap.add_argument("--grow-step", type=int, default=100, help="grow-k: stall iters per rung")
    ap.add_argument("--alns-stall", type=int, default=600,
                    help="ALNS stall limit; v1 path hardcodes 600, --rule-b uses this (raise to let grow-k escalate)")
    ap.add_argument("--helpless-probe", type=int, default=200,
                    help="Rule B: abort ALNS if no feasible move in N iters (0 = off)")
    ap.add_argument("--surrogate", action="store_true", default=True)
    ap.add_argument("--theta", type=float, default=0.0,
                    help="skip a stage whose ceiling is at or below this %% of the incumbent "
                         "(analysis/headroom.py). DEFAULT 0.0 ON PURPOSE: at zero the gate skips "
                         "only what it can PROVE is a no-op, so no judgement call is buried in a "
                         "default. Any positive theta trades a provable skip for a guessed one "
                         "and must be justified per campaign. A ceiling that cannot be computed "
                         "always fires.")
    ap.add_argument("--tag", default="solve")
    ap.add_argument("--seed", type=int, default=1000,
                    help="ALNS rng seed (was hardcoded 1000); vary for the multi-seed primal trial")
    ap.add_argument("--envelope", type=float, default=None,
                    help="override the per-cell budget E (default 5760 - LB_wall via envelope_for); "
                         "set to the full 5760 to measure the primal leg's OV-vs-RT standalone")
    ap.add_argument("--no-bank", action="store_true",
                    help="skip the runs/oracle artifact write (measurement/trial run); the full "
                         "OV(t)+event trajectory is still spooled to logs/<run_id>.out, and the "
                         "quarantine-halt still fires -- only the banked artifact is skipped")
    ap.add_argument("--ws-only", action="store_true",
                    help="CG-FREE warm-start leg (P1): seed the incumbent from the greedy "
                         "construct_best_of portfolio and the line-11 pool from its own trips, "
                         "SKIP stage 1-6 (no column generation), then run 8/9/11. This leg reports "
                         "OV only -- the LB is the dual leg's job (two strong legs)")
    ap.add_argument("--dump-incumbent", default=None,
                    help="after the incumbent is final, also write it (solution+routing+schedule "
                         "only, NO runtime claim -- reproducible by seed+code_hash) to this path, "
                         "for the primal leg to inherit via --inherit. The CG pricer is wall-bound "
                         "Python with no deterministic clock, so this handoff carries provenance "
                         "but makes no reproducible-runtime claim")
    ap.add_argument("--inherit", default=None,
                    help="path to a --dump-incumbent handoff (the dual leg's master_ip incumbent). "
                         "In the --ws-only leg it is added as a second warm-start candidate and the "
                         "strong WS is the lower-OV of {greedy construct, inherited incumbent}")
    ap.add_argument("--threads", type=int, default=2,
                    help="Gurobi thread count for master_ip; also DECLARED on the artifact for the "
                         "d47 rt_class policy. Submission-grade (quotable wall) requires 4")
    ap.add_argument("--submission", action="store_true",
                    help="declare rt_class='submission' on the banked artifact (wall quotable beside "
                         "K). rt_class.classify REFUSES unless --threads 4 AND single tenancy, so a "
                         "false claim cannot be written. Requires the det clock (Gurobi Work), which "
                         "is banked automatically")
    a = ap.parse_args()

    print("TEP SOLVE -- one variant, one OV per cell. stages off: %s\n"
          % (", ".join(s for s, off in (("ceil", a.no_ceil), ("refine", a.no_refine), ("alns", a.no_alns),
                                        ("select", a.no_select), ("fleetcap", a.no_fleetcap)) if off)
             or "none"))
    # D6: snapshot the untriaged quarantine BEFORE anything runs, and refuse to start if it is
    # already dirty. A run launched on top of an untriaged contradiction produces results nobody
    # can disposition afterwards.
    try:
        _q0 = {r.get("run_id") for r in QG.rows() if QG.is_untriaged(r)}
    except Exception as e:
        print("REFUSING TO START: quarantine index unreadable (%s). An unreadable guard is not a "
              "clean guard." % type(e).__name__)
        return 2
    if _q0:
        print("REFUSING TO START: %d untriaged quarantine row(s) already present -- %s\n"
              "Triage them, or re-run once runs/invalid/INDEX.md is clean."
              % (len(_q0), ", ".join(sorted(x for x in _q0 if x))[:200]))
        return 2
    print("quarantine clean at start (0 untriaged rows)\n")

    out = []
    for cell in a.cells:
        run_id = "tep_solve_%s_n%d_%s" % (cell, a.size, uuid.uuid4().hex[:8])
        prox = k_proximity(a.size)
        inst = V.load_instance(cell, a.size, prox)
        env = a.envelope if a.envelope else envelope_for(cell, a.size)
        rec = dict(cell=cell, size=a.size, run_id=run_id, envelope_s=env, story=[],
                   proximity=prox, seed=a.seed,
                   caps=dict(cg_secs=a.cg_secs, ip_work=a.ip_work, refine_wall=a.refine_wall,
                             alns_iters=a.alns_iters, alns_wall=a.alns_wall,
                             select_cap=a.select_cap, delta=a.delta, ng=a.ng, iters=a.iters),
                   shares=dict(SHARES), pool_lp_limit=POOL_LP_LIMIT,
                   caps_derived={k: (round(v * env, 1) if env else None)
                                 for k, v in SHARES.items()})
        # EXHAUSTIVE SPOOL, one file per run. Every event is written and flushed as it happens,
        # never at the end -- a log that only appears on exit cannot be watched, and a run that
        # dies takes its story with it. The first line is `RUN_ID <id>`, matching the convention
        # the existing 570 logs use, so the same mining works on these. Improvements are emitted
        # as `+improve obj=N mode=STAGE t=Ns`, again the existing format.
        logp = os.path.join(ROOT, "logs", "%s.out" % run_id)
        lg = io.open(logp, "w", encoding="utf-8", newline="\n")
        t_run = time.time()

        def spool(line, also_print=True):
            s = "%s  %s" % (time.strftime("%H:%M:%S"), line)
            lg.write(s + "\n"); lg.flush()
            os.fsync(lg.fileno())
            if also_print:
                print(line, flush=True)

        lg.write("RUN_ID %s\n" % run_id); lg.flush()
        spool("%s n%d | envelope %s s | delta %s ng %s | caps %s"
              % (cell, a.size, ("%.0f" % env) if env else "unknown",
                 a.delta or "default", a.ng, json.dumps(rec["caps"])))
        # V_LB for the fleet-cap ceiling: computed from THE INSTANCE, not from any artifact, so
        # the gate stays K-blind and corpus-free.
        try:
            from fleet_energetic_bound import energetic_floor
            rec["v_lb"], rec["v_lb_witness"] = energetic_floor(inst)
        except Exception as e:
            rec["v_lb"] = None
            spool("    V_LB unavailable (%s): the fleet-cap ceiling will fail open"
                  % type(e).__name__, also_print=False)

        # `carry` holds auxiliary state a stage produced -- anything later stages consume that is
        # NOT the solution itself. It is committed ONLY when the stage's solution is accepted
        # (D1, 2026-09-28). The defect it replaces: `trips` was a nonlocal written by both
        # rounding arms unconditionally, and ceil runs second, so stage 11 read the LAST arm's
        # partition rather than the ACCEPTED one -- wrong on the 34 of 108 cells where floor wins.
        # Generic on purpose: a per-variable fix would let the next stage reintroduce the class.
        inc, inc_val, inc_obj, carry = None, None, None, {}

        # Line 10's POOL. Distinct from carry["trips"] and the distinction is the point:
        #   carry["trips"]  the ACCEPTED arm's partition -- the incumbent's own structure (D1)
        #   pool            a CANDIDATE SET: both arms' partitions plus the LP-positive columns
        # Taking columns from the rejected arm into a POOL is not the D1 defect. D1 was silently
        # substituting one arm's partition for another's; a pool is declared as a union and is
        # recorded as one. Keyed by the trip tuple so the union dedupes.
        pool, pool_src = {}, {}

        def pool_add(seqs, src):
            n0 = len(pool)
            for s_ in seqs or []:
                k_ = tuple(s_)
                if k_ not in pool:
                    pool[k_] = list(s_); pool_src[k_] = src
            return len(pool) - n0

        def budget_left():
            """Algorithm 1 line 7/9. None when the envelope is unknown -- and an unknown budget
            never gates a stage, same fail-open rule as the headroom ceiling."""
            return None if not env else env - (time.time() - t_run)

        def cap_for(name):
            """A stage's cap: its declared share of E, never more than what is actually left."""
            if not env:
                return None
            share = SHARES.get(name)
            if share is None:
                return None
            return max(0.0, min(share * env, budget_left() or 0.0))

        def live_ceilings():
            """Ceilings from THIS RUN's state only -- never from a banked artifact (C1)."""
            return HR.ceilings(HR.components(inst, inc_obj), inc_val,
                               lp_street=rec.get("lp_street"), water_ab=rec.get("water_ab"),
                               cars=(inc or {}).get("nCars"), v_lb=rec.get("v_lb"),
                               ip_gap_pct=rec.get("pool_gap_pct", rec.get("ip_gap_pct")))

        def stage(name, fn):
            """Run a stage, verify, accept only on a strictly better verified objective.

            GATED BY ITS OWN CEILING (2026-09-28). Before the stage runs, the maximum it could
            possibly win is computed from the current incumbent and this run's certified bound.
            Below --theta the stage is SKIPPED with the number that justified it. FAIL-OPEN: a
            ceiling that cannot be computed fires the stage, because absence of a bound is not
            a bound."""
            nonlocal inc, inc_val, inc_obj
            ceils = live_ceilings()
            aux = {}
            fire, why_gate = HR.gate(name, ceils, a.theta)
            c = (ceils or {}).get(name) or {}
            rec.setdefault("ceilings", []).append(
                dict(stage=name, pct=c.get("pct"), source=c.get("source"),
                     regime=c.get("regime"), fired=fire, reason=why_gate,
                     t_run=round(time.time() - t_run, 1)))
            # Line 7/9: a stage with no budget left does not run. Recorded separately from the
            # ceiling skip, because "provably cannot help" and "no time" are different facts.
            bl, cap = budget_left(), cap_for(name)
            rec.setdefault("budget", []).append(
                dict(stage=name, envelope_s=env, budget_left_s=None if bl is None else round(bl, 1),
                     cap_s=None if cap is None else round(cap, 1),
                     share=SHARES.get(name), t_run=round(time.time() - t_run, 1)))
            if bl is not None and bl <= 0:
                rec["story"].append(dict(stage=name, secs=0.0, accepted=False,
                                         why="SKIPPED: envelope exhausted (%.0f s of %.0f s used)"
                                             % (time.time() - t_run, env),
                                         in_val=inc_val, out_val=None, skipped_by_budget=True,
                                         t_run=round(time.time() - t_run, 1)))
                spool("stage %-11s SKIP   envelope exhausted" % name)
                return
            if not fire:
                rec["story"].append(dict(stage=name, secs=0.0, accepted=False,
                                         why="SKIPPED by ceiling: %s" % why_gate,
                                         in_val=inc_val, out_val=None, skipped_by_ceiling=True,
                                         t_run=round(time.time() - t_run, 1)))
                spool("stage %-11s SKIP   %s" % (name, why_gate))
                return
            spool("stage %-11s START  incumbent=%s  %s"
                  % (name, ("%.3f" % inc_val) if inc_val else "none", why_gate))
            t0 = time.time()
            try:
                # A stage may return `sol`, or `(sol, aux)` where aux is auxiliary state later
                # stages consume. aux is held aside and committed only if sol is ACCEPTED.
                out_ = fn()
                if isinstance(out_, tuple):
                    sol, aux = out_[0], (out_[1] or {})
                else:
                    sol = out_
                err = None
            except Exception as e:
                import traceback
                sol, err = None, "%s: %s" % (type(e).__name__, str(e)[:80])
                spool("stage %-11s RAISED %s" % (name, err), also_print=False)
                for ln in traceback.format_exc().splitlines()[-6:]:
                    spool("    %s" % ln, also_print=False)
            secs = round(time.time() - t0, 1)
            if sol is None:
                why = err or "stage returned nothing better than its anchor"
                rec["story"].append(dict(stage=name, secs=secs, accepted=False, why=why,
                                         in_val=inc_val, out_val=None,
                                         t_run=round(time.time() - t_run, 1)))
                spool("stage %-11s END    %7.1fs  no solution  %s" % (name, secs, why[:70]))
                return
            val, ok, bad, vobj = verified_value(inst, sol, cell, a.size, prox, name)
            better = inc_val is None or (val is not None and val < inc_val - TOL)
            acc = bool(ok and better)
            why = ("accepted" if acc else
                   ("FAILS verifier3: %s" % ",".join(bad)) if not ok else
                   "not better than %.3f" % inc_val)
            rec["story"].append(dict(stage=name, secs=secs, accepted=acc, why=why,
                                     in_val=inc_val, out_val=val, verified=ok,
                                     nCars=sol.get("nCars"), nVessel=sol.get("nVessel"),
                                     t_run=round(time.time() - t_run, 1)))
            spool("stage %-11s END    %7.1fs  verified=%-5s obj=%s cars=%s  %s"
                  % (name, secs, ok, ("%.3f" % val) if val is not None else "-",
                     sol.get("nCars"), why))
            if acc:
                spool("+improve obj=%.3f mode=%s verify=OK t=%ds"
                      % (val, name.split()[-1], int(time.time() - t_run)))
                inc, inc_val, inc_obj = sol, val, vobj
                if aux:
                    carry.update(aux)      # D1: auxiliary state follows the ACCEPTED arm
                    carry["_from"] = name  # and the artifact records which arm that was

        # ---- lines 1-6 : selection, chaining, water, verify
        def s16_arm(rounding):
            """One rounding arm of Algorithm 1 line 1. floor is the RELAXATION and gives the
            bound; ceil is the RESTRICTION whose integer solutions carry an exact timetable
            (L-TEP-relax / L-TEP-ceil). The line says `for rounding in {floor, ceil}` and the
            first version of this solver ran floor only, discarding half of stage 1."""
            delta = a.delta if a.delta else T.default_delta(inst)
            r = T.run(cell, delta, a.iters, ["prio", "ts"], a.ng, 1000, False, 3_000_000,
                      size=a.size, proximity=prox,
                      max_secs=(cap_for("1-6") or a.cg_secs),
                      start_states=True, return_master=True, primal=(rounding == "ceil"),
                      fast_pricer=a.fast_pricer)
            # Only the FLOOR arm yields a bound. Ceil is a restriction and its LP must never be
            # cited as one (d414), so the bound fields are written from the floor arm alone.
            if rounding == "floor":
                rec["lp_street"] = r.get("lp_street"); rec["proven"] = r.get("proven")
                if a.fast_pricer:
                    import numba as _nb, llvmlite as _lv
                    rec["fast_pricer"] = dict(on=True, numba=_nb.__version__, llvmlite=_lv.__version__)
                # bank the dual leg's validity flag and its LB(t) trajectory (per-iteration CG
                # history: lp/work/secs) -- the "both legs' full RT trajectory" requirement.
                rec["valid_bound"] = r.get("valid_bound")
                rec["lb_hist"] = r.get("hist")
                # D3: `proven` is the PRICER's flag, not a certificate. bound_certificate is the
                # single authority: certified() additionally refuses a ceil-rounded artifact
                # (a restriction's LP is not a lower bound, d414) and requires the elementary
                # pass to have converged with no slack; ng is a weaker class and NOT a proof
                # (d427). The class is recorded so a reader never has to infer it.
                rec["certificate"] = BC.bound_class(r)
                rec["certificate_why_not"] = None if rec["certificate"] else BC.why_not(r)
            # The composed bound is assembled in tep_cg_bound.MAIN, not in run(), so calling run()
            # directly returns lp_street with no water term and rec["lb"] came back None on the
            # first smoke. Same composition as tep_cg_bound.py:812: LP street + the AB water term.
                rec["lb"] = None
                try:
                    # THE WATER TERM IS RECOMPUTED, NOT READ (2026-09-28, author: "AB is
                    # arithmetic bound you can cheaply and easily reproduce"). It used to be
                    # looked up in runs/ab_grid_provenanced.json, which left the bound with two
                    # different provenances -- lp_street computed this run under a certificate,
                    # water_ab read from a corpus whose own provenance is unrecoverable.
                    # fullset_bound is deterministic arithmetic on instance data: no solver, no
                    # seed (ab_grid_build's own words, and its --verify mode exists precisely
                    # because a fresh driver must reproduce the stored values exactly).
                    # Checked before wiring: exact match on R206/R201 n10, C204 n30, RC207 n50,
                    # R204 n100, and no K module loads on the path. Cost 0.01-0.41 s.
                    from build_instance import build as _abuild
                    from crossfeed.fullset_bound import fullset_bound as _fsb
                    _t0ab = time.time()
                    _p = _abuild(cell, a.size, wls=0.1, tau="formula", proximity=prox,
                                 time_limit=60)
                    _b, _parts = _fsb(_p)
                    rec["water_ab"] = float(_parts["water"])
                    rec["water_ab_source"] = "recomputed in-run (crossfeed.fullset_bound)"
                    rec["water_ab_secs"] = round(time.time() - _t0ab, 2)
                    ab = {"water": rec["water_ab"]}
                    # AB4'S TOTAL IS ITSELF A VALID BOUND, and we were throwing it away
                    # (author, 2026-09-28: "using AB4?"). We took only its water component and
                    # composed it with our LP street part. But ab4 = fleet_term + travel_term +
                    # water (checked: exact on 162 of 162 records), and on 7 of 135 cells -- all
                    # n10 -- that total BEATS lp_street + water, by up to +69.8 on RC208
                    # (176.468 -> 246.241). Both are valid lower bounds, so the max is free.
                    # It also does not need a pricing certificate: AB4 is deterministic
                    # arithmetic, valid by construction, so it still supplies a bound on a cell
                    # whose LP is uncertified and therefore withheld by D3.
                    rec["ab4"] = float(_b)
                    # D3: the bound is published only behind a CERTIFICATE, never behind the raw
                    # flag. An uncertified LP is not a lower bound and is not reported as one.
                    if r.get("lp_street") is not None and rec.get("certificate"):
                        rec["lb_composed"] = r["lp_street"] + float(ab["water"])
                        rec["lb"] = max(rec["lb_composed"], rec["ab4"])
                        rec["lb_source"] = ("composed (LP street + AB water)"
                                            if rec["lb_composed"] >= rec["ab4"] else "AB4 total")
                        rec["lb_valid"] = True
                        if rec["lb"] > rec["lb_composed"] + 1e-9:
                            spool("    LB from AB4 TOTAL %.3f, above the composed %.3f (+%.3f)"
                                  % (rec["ab4"], rec["lb_composed"],
                                     rec["ab4"] - rec["lb_composed"]))
                    elif rec.get("ab4") is not None:
                        # No pricing certificate, so the composed bound is withheld -- but AB4
                        # is arithmetic and valid without one, so the cell still gets a bound.
                        rec["lb"] = rec["ab4"]
                        rec["lb_source"] = "AB4 total (LP uncertified, composed withheld)"
                        rec["lb_valid"] = True
                        spool("    LP UNCERTIFIED (%s): falling back to the AB4 arithmetic "
                              "bound %.3f" % (rec.get("certificate_why_not"), rec["ab4"]))
                    else:
                        rec["lb_valid"] = False
                        spool("    LB WITHHELD: no certificate (%s)"
                              % (rec.get("certificate_why_not") or "unknown"))
                except Exception as e:
                    spool("    composed bound unavailable: %s" % type(e).__name__, also_print=False)
            M = r.get("master")
            if M is None:
                return None
            # LINE 10, FIRST HALF, AND THE ORDER IS LOAD-BEARING. master_ip flips every column to
            # BINARY and re-optimises, so after it runs `v.X` is the IP value, not the LP one.
            # The LP-positive columns -- the fractional optimum's own support -- have to be
            # harvested HERE, before that call, or they are silently the wrong numbers.
            lp_cols = []
            for k_, v_ in M.cols.items():
                try:
                    xv = float(v_.X)
                except Exception:
                    continue
                if xv > 1e-6:
                    lp_cols.append((xv, list(k_[0])))
            lp_cols.sort(key=lambda t: -t[0])
            n_lp = pool_add([s_ for _, s_ in lp_cols[:POOL_LP_LIMIT]], "lp:" + rounding)
            spool("    line 10: %d LP-positive columns, %d new to the pool (pool %d)"
                  % (len(lp_cols), n_lp, len(pool)), also_print=False)
            ip = T.master_ip(M, cell, a.size, threads=a.threads, timelimit=1800.0, work=a.ip_work)
            # det clock: cumulative deterministic Gurobi Work over this arm's LP solves + its IP
            # (M.det_work, already tracked in tep_cg_bound). Accumulated across both rounding arms;
            # banked beside the wall as the reproducibility anchor (d: code_hash + det ticks).
            rec["det_work_total"] = rec.get("det_work_total", 0.0) + float(getattr(M, "det_work", 0.0) or 0.0)
            # the fixed-pool IP's own residual gap IS the ceiling for any re-partition of that
            # pool (d580, R2) -- recorded here so stage 11's gate has a real bound, not the
            # loose decomposition that cannot tell one street operator from another.
            if isinstance(ip, dict) and isinstance(ip.get("ip_gap"), (int, float)):
                rec["ip_gap_pct"] = 100.0 * float(ip["ip_gap"])
            # LINE 10, SECOND HALF: this arm's IP partition joins the POOL whether or not its
            # solution wins. That is not the D1 defect -- see the pool comment above.
            if ip.get("trips"):
                n_ip = pool_add(ip["trips"], "ip:" + rounding)
                spool("    line 10: %d IP trips, %d new to the pool (pool %d)"
                      % (len(ip["trips"]), n_ip, len(pool)), also_print=False)
            # D1: hand the partition back as AUX, do not publish it. stage() commits it only if
            # this arm's solution is the one accepted. Writing a nonlocal here is what let the
            # rejected arm feed stage 11.
            return ip.get("solution"), ({"trips": ip["trips"]} if ip.get("trips") else {})

        if a.ws_only:
            # CG-FREE WARM-START LEG (P1). No column generation on this leg: the LB is the DUAL
            # leg's job (two strong legs, d446/overnight-plan step 3), so this leg reports OV only
            # and rec["lb"] stays absent on purpose. The incumbent is the greedy PORTFOLIO
            # construction (construct_best_of, singleton_vessels=True per d17; ladder (1,3,5) per
            # the cost_aware_greedy measurement), and the pool for line 11 is seeded from THAT
            # incumbent's own trip partition -- the WS analogue of the CG arms' ip:floor/ip:ceil
            # trips -- so 8 refine / 9 alns / 11 select run exactly as they do on the CG path.
            def s0_ws():
                from solver.config import InstanceSpec
                from solver.problem import SolverProblem
                from cost_aware_greedy import construct_best_of
                cands = []
                sp = SolverProblem(InstanceSpec.for_k_comparison(cell, a.size))
                # hub_congestion 1.0 matches the banked n100 B0 census (cost_aware_greedy --help);
                # measured inert at small n, and it helps coverage on the congested n100 cells.
                g, go, gc, gt = construct_best_of(sp, a.seed, ladder=(1, 3, 5),
                                                  hub_congestion=1.0)
                spool("    ws construct: obj(sp)=%s cars=%s tries=%s"
                      % (("%.3f" % go) if go else None, gc, gt), also_print=False)
                if g is not None:
                    cands.append(("greedy", g))
                if a.inherit:
                    try:
                        isol = json.load(io.open(a.inherit, encoding="utf-8")).get("solution")
                    except Exception as e:
                        isol = None
                        spool("    inherit load failed (%s): %s" % (type(e).__name__, a.inherit),
                              also_print=False)
                    if isol is not None:
                        cands.append(("inherit", isol))
                # STRONG WS = lower verified OV of {greedy, inherited}. Each candidate is verified on
                # THIS run's instance (verifier3), never trusted on its claimed objVal.
                best = None
                for nm, sol in cands:
                    val, ok, bad, _o = verified_value(inst, sol, cell, a.size, prox, "ws:" + nm)
                    spool("    ws cand %-7s verified=%-5s obj=%s %s"
                          % (nm, ok, ("%.3f" % val) if val is not None else "-",
                             ("" if ok else "findings=%s" % bad)), also_print=False)
                    if ok and val is not None and (best is None or val < best[0]):
                        best = (val, sol, nm)
                if best is None:
                    return None
                spool("    ws chosen: %s obj=%.3f" % (best[2], best[0]), also_print=False)
                return best[1]
            stage("0 ws", s0_ws)
            if inc is not None:
                import tep_refine as _R
                _ch, _ = _R.decode(inst, inc)
                _trips = [t for chain in _ch for t in chain]
                n_ws = pool_add(_trips, "ws:greedy")
                spool("    ws pool seed: %d trips from the WS incumbent (pool %d)"
                      % (n_ws, len(pool)), also_print=False)
        else:
            # Line 1 runs BOTH arms and the banking rule picks between them, exactly as for any
            # other stage: strictly better, verifier-clean, objective from the verifier.
            stage("1-6 floor", lambda: s16_arm("floor"))
            if not a.no_ceil:
                stage("1-6 ceil", lambda: s16_arm("ceil"))

        # ---- line 8 : refine
        if not a.no_refine and inc is not None:
            def s8():
                import tep_refine as R
                ch, hb = R.decode(inst, inc)
                _v, sol, st = R.refine(inst, ch, hb, 10 ** 6, 200,
                                       (cap_for("8 refine") or a.refine_wall),
                                       incumbent_val=inc_val, surrogate=a.surrogate)
                spool('    refine stats %s' % json.dumps(st, default=str)[:300], also_print=False)
                return sol
            stage("8 refine", s8)

        # ---- line 9 : ALNS
        if not a.no_alns and inc is not None:
            def s9():
                import tep_refine as R
                ch, hb = R.decode(inst, inc)
                if a.rule_b:                                   # Rule B / grow-k (d671), flag-gated
                    import tep_alns_v2 as A2
                    _v, sol, st = A2.alns_growk(inst, ch, hb, inc_val, a.alns_iters, a.alns_stall,
                                                (cap_for("9 alns") or a.alns_wall),
                                                a.seed, list(inst.satellites), surrogate=a.surrogate,
                                                grow_max=a.grow_max, grow_step=a.grow_step,
                                                helpless_probe=a.helpless_probe)
                else:                                          # frozen v1 ALNS, byte-untouched
                    import tep_alns as A
                    _v, sol, st = A.alns(inst, ch, hb, inc_val, a.alns_iters, 600,
                                         (cap_for("9 alns") or a.alns_wall),
                                         a.seed, list(inst.satellites), surrogate=a.surrogate)
                spool('    alns stats %s' % json.dumps(st, default=str)[:300], also_print=False)
                return sol
            stage("9 alns", s9)

        # ---- line 11 : select+chain over the pool
        # LINE 11 now searches the POOL, not one arm's partition. THE CEILING CHANGES WITH IT:
        # d580 bounds a re-partition of a FIXED pool by THAT pool's IP optimum. Once the pool is
        # strictly wider than the arm's master pool, the arm's ip_gap is no longer a bound on
        # what stage 11 can reach, so it must not be used as one. Clearing it makes the headroom
        # gate fail open and run the stage -- the conservative direction, and the reason stage 11
        # stopped being skipped at 0.000%.
        _own = set(map(tuple, carry.get("trips") or []))
        _wider = len(set(pool) - _own)
        rec["pool_n"] = len(pool)
        rec["pool_beyond_incumbent"] = _wider
        rec["pool_sources"] = {v: sum(1 for x in pool_src.values() if x == v)
                               for v in sorted(set(pool_src.values()))}
        if _wider:
            rec["ip_gap_pct_arm"] = rec.pop("ip_gap_pct", None)
            spool("line 10 pool: %d trips, %d beyond the incumbent partition %s -- the arm's "
                  "ip_gap is NOT a ceiling for a wider pool"
                  % (len(pool), _wider, rec["pool_sources"]))
            # ...so compute the ceiling the WIDER pool actually admits. pool_master_lp restricts
            # the floor-bucketed TEP master to the pool trips: floor bucketing relaxes continuous
            # time (d414) and the fleet term stays continuous, so no selection+chaining over this
            # pool can cost less than its value. That is a valid lower bound over exactly the set
            # stage 11 searches, which is what d580 asks for. It returns None when a customer no
            # pool variant can cover leaves slack -- then there is no bound and the gate fails
            # open, which is the same rule as everywhere else.
            try:
                import tep_select_chain as _S
                _t0p = time.time()
                _plb = _S.pool_master_lp(inst, list(pool.values()))
                rec["pool_lb"] = _plb
                rec["pool_lb_secs"] = round(time.time() - _t0p, 1)
                if _plb is not None and inc_val:
                    rec["pool_gap_pct"] = 100.0 * max(0.0, inc_val - _plb) / inc_val
                    spool("line 10 pool LB %.3f (%.1fs) -> stage 11 ceiling %.3f%%"
                          % (_plb, rec["pool_lb_secs"], rec["pool_gap_pct"]))
                else:
                    spool("line 10 pool LB unavailable (slack, or no incumbent): stage 11 "
                          "fails open")
            except Exception as _e:
                rec["pool_lb"] = None
                spool("line 10 pool LB raised %s: stage 11 fails open" % type(_e).__name__)
        if not a.no_select and pool:
            def s11():
                # select_chain returns dict(trips=..., cars=..., street=...), NOT a solution.
                # The first smoke passed that dict straight to verifier3 and got six A-FIELD
                # findings and obj 0.000. Its trips have to go through the same admissible route
                # as line 4-5 before anything can be verified.
                import tep_select_chain as S
                from tep_chain_own_water import admissible_solution
                res = S.select_chain(inst, list(pool.values()),
                                     cap=(cap_for("11 select") or a.select_cap),
                                     work=None, seed=0)
                if not res or not res.get("trips"):
                    spool("    select_chain returned %s" % (list(res) if res else None), also_print=False)
                    return None
                sol, info = admissible_solution(inst, [list(t) for t in res["trips"]],
                                                cap=a.select_cap)
                spool("    select_chain -> %d trips, %s cars | admissible: %s"
                      % (len(res["trips"]), res.get("cars"), info.get("why")), also_print=False)
                return sol
            stage("11 select", s11)

        # ---- line 13 : master fleet cap, WIRED (d685). If the incumbent uses more cars than one
        # fewer could, cap N at nCars-1 (a K-blind RESTRICTION of our own formulation) and
        # re-partition. The cap can only fail to find a solution, never produce an invalid one
        # (d461); and the returned solution is re-verified here through the SAME verified_value()
        # gate every stage uses, so no invalid or worse incumbent is ever accepted. This is the arm
        # that drops the fleet-basin cells (RC202/R201 n30) from 3 cars to 2 inside the one run.
        # BASIN GATE (d690/d691 salvage): fire only on a GENUINE excess-car basin -- the incumbent
        # uses more cars than the LP fleet floor ceil(N_LP) AND has at least 3 cars, so the cap stays
        # >= 2. We NEVER attempt cap=1: one vehicle cannot serve 20+ time-windowed customers (0/5 of
        # the cap=1 attempts found anything, and they were the ~800 s hangs). This fires only on true
        # 3+car basins (RC202 and the larger-n basins); accept-if-verified-better guards the result;
        # the re-partition CG is wall-bounded (cg_secs) so even a false 3+car basin aborts fast.
        import math as _math
        _h = rec.get("lb_hist") or []
        _nlp = _h[-1].get("N") if (_h and isinstance(_h[-1], dict) and _h[-1].get("N") is not None) else None
        _cars = inc.get("nCars") if inc else None
        # SMALL-FLEET gate (d694): fire only when 3 <= cars <= fleetcap_max_cars. No cheap integer
        # fleet LB is tight enough to gate on (arithmetic=1, energetic=2, conflict=1-2 vs a true
        # ~6-car fleet at n100), so we cannot prune false basins by a bound. But the fleet cap only
        # wins where the LP floor ceil(N_LP) is ACHIEVABLE -- which empirically is small fleets
        # (RC202 n30: 3->2). At larger fleets (n50/n100's 5-6 car cells) the floor is loose and the
        # re-partition fires blind, finds nothing (0/3 n100 cells) and wastes ~240 s. Capping at
        # cars <= 4 skips exactly those useless runs (0 wins lost) and keeps the productive ones.
        _basin = bool(_cars and 3 <= _cars <= a.fleetcap_max_cars
                      and (_nlp is None or _cars > _math.ceil(_nlp - 1e-6)))
        if not a.no_fleetcap and inc is not None and _basin:
            cars = _cars; cap = cars - 1; t0 = time.time()
            import tep_master_fleet_cap as FC
            spool("stage 13 fleetcap START  incumbent=%.3f cars=%d  capping N <= %d"
                  % (inc_val, cars, cap))
            fc = None
            try:
                fc = FC.cap_solve(inst, cell, a.size, prox, cap, rounds=a.fleetcap_rounds,
                                  ng=a.fleetcap_ng, budget_s=a.fleetcap_secs,
                                  cap_chain=120.0, work_chain=120.0,
                                  kb=None, log=lambda m: spool(m, also_print=False))
            except Exception as e:
                spool("stage 13 fleetcap RAISED %s" % str(e)[:80])
            if fc is None:
                rec["story"].append(dict(stage="13 fleetcap", secs=round(time.time() - t0, 1),
                                         accepted=False, why="no verified partition at N<=%d" % cap,
                                         in_val=inc_val, out_val=None,
                                         t_run=round(time.time() - t_run, 1)))
                rec["fleetcap_trigger"] = dict(cars=cars, cap=cap, fired=True, accepted=False,
                                               why="no verified partition at N<=%d" % cap)
                spool("stage 13 fleetcap END    no verified partition at N <= %d" % cap)
            else:
                val, ok, bad, vobj = verified_value(inst, fc[1], cell, a.size, prox, "13 fleetcap")
                better = inc_val is None or (val is not None and val < inc_val - TOL)
                acc = bool(ok and better)
                rec["story"].append(dict(stage="13 fleetcap", secs=round(time.time() - t0, 1),
                                         accepted=acc, verified=ok, in_val=inc_val, out_val=val,
                                         nCars=fc[1].get("nCars"),
                                         why=("accepted" if acc else
                                              ("FAILS verifier3: %s" % ",".join(bad)) if not ok else
                                              "not better than %.3f" % inc_val),
                                         t_run=round(time.time() - t_run, 1)))
                spool("stage 13 fleetcap END    verified=%-5s obj=%s cars=%s cap<=%d  %s"
                      % (ok, ("%.3f" % val) if val is not None else "-", fc[1].get("nCars"), cap,
                         "accepted" if acc else "rejected"))
                if acc:
                    spool("+improve obj=%.3f mode=fleetcap verify=OK t=%ds" % (val, int(time.time() - t_run)))
                    inc, inc_val, inc_obj = fc[1], val, vobj
                    # d697: the fleet cap is the LAST stage, so its fewer-car output is UN-REFINED --
                    # it misses the local-search chain the banked 2-car arms had (RC202 n30: fleet cap
                    # 1492 vs selchain->refine->alns 1421.7). Re-run refine+alns on the reduced-fleet
                    # incumbent to close the routing residual WITHIN the new fleet. Accept-gated (can
                    # only improve), and affordable given the RT headroom under K-budget/2.5.
                    if not a.no_refine:
                        stage("13b refine", s8)
                    if not a.no_alns:
                        stage("13c alns", s9)
                rec["fleetcap_trigger"] = dict(cars=cars, cap=cap, fired=True, accepted=acc,
                                               out_val=inc_val, cars_after=inc.get("nCars") if inc else None)
        elif not a.no_fleetcap:
            rec["fleetcap_trigger"] = dict(cars=_cars, nlp=_nlp, fired=False,
                                           why="at/below LP fleet floor ceil(N_LP) -- not a basin, or no incumbent")

        rec["carry_from"] = carry.get("_from")
        rec["carry_trips_n"] = len(carry["trips"]) if carry.get("trips") else None
        rec["carry_trips_fp"] = (hashlib.sha256(
            json.dumps(carry["trips"], sort_keys=True, default=str).encode()).hexdigest()[:12]
            if carry.get("trips") else None)
        rec["ov"] = inc_val
        rec["nCars"] = inc.get("nCars") if inc else None
        rec["solution"] = inc
        # --dump-incumbent: a SOLUTION-ONLY handoff for the other leg to inherit. No wall_s / secs
        # on this payload ON PURPOSE -- the CG pricer is wall-bound Python with no deterministic
        # clock, so the handoff carries provenance (reproducible by seed+code_hash) but makes no
        # reproducible-runtime claim (stamp.py would rightly refuse one). Written even under
        # --no-bank: it is an input to a measurement, not the measurement's reported result.
        if a.dump_incumbent and inc is not None:
            _write(a.dump_incumbent,
                   dict(cell=cell, size=a.size, proximity=prox, ov=inc_val,
                        nCars=inc.get("nCars"), solution=inc, tag=a.tag,
                        kind="incumbent_handoff",
                        note="dual-leg master_ip incumbent; reproducible by seed+code_hash; "
                             "NO runtime claim (CG pricer is wall-bound Python, not a det clock)"))
            print("  dumped incumbent handoff -> %s" % a.dump_incumbent)
        # D4: this project's gap is measured AGAINST THE BOUND -- (OV - LB)/LB, the same
        # denominator as analysis/tep_gap_to_bound.py:30. Dividing by OV understates it
        # (12.73% against 14.59% on R201 n10) and is not comparable with anything we report.
        rec["gap_pct"] = (100.0 * (inc_val - rec["lb"]) / rec["lb"]
                          if inc_val and rec.get("lb") else None)
        accepted = [s["stage"] for s in rec["story"] if s["accepted"]]
        rec["log"] = os.path.relpath(logp, ROOT)
        rec["wall_s"] = round(time.time() - t_run, 1)
        # d47 / citability: DECLARE the thread count on the artifact (rt_class policy reads it) and
        # bank the deterministic Gurobi Work clock beside the wall (reproducibility anchor; also
        # what lets stamp.py accept a wall figure). `work` numeric for det-detection, `det_ticks`
        # structured. Submission-grade (quotable wall) is asserted at bank time via rt_class.
        _W = round(rec.get("det_work_total", 0.0), 6)
        rec["threads"] = a.threads
        rec["work"] = _W
        rec["det_ticks"] = dict(gurobi_work=_W)
        spool("final best (verified) = %s   wall=%ds   stages that moved it: %s"
              % (("%.3f" % inc_val) if inc_val else "NONE", int(time.time() - t_run),
                 ", ".join(accepted) or "none"))
        lg.close()
        print("  => OV %s | LB %s | gap %s | stages that moved it: %s\n"
              % (("%.3f" % inc_val) if inc_val else "NONE",
                 ("%.3f" % rec["lb"]) if rec.get("lb") else "-",
                 ("%.2f%%" % rec["gap_pct"]) if rec.get("gap_pct") else "-",
                 ", ".join(accepted) or "none"))
        out.append(rec)

        # D5: WRITE AFTER EVERY CELL, not once at the end. The previous version wrote a single
        # artifact after the whole cell list, so a kill at cell 26 of 27 lost all 26. Each cell
        # also gets its own file, so one cell's result never depends on the run completing.
        if not a.no_bank:
            _rtc = "submission" if a.submission else None
            _write(os.path.join(ROOT, "runs", "oracle",
                                "tep_solve_%s_%s_n%d.json" % (a.tag, cell, a.size)),
                   dict(rows=[rec], switches=_switches(a), threads=a.threads), rt_class=_rtc)
            _write(os.path.join(ROOT, "runs", "oracle",
                                "tep_solve_%s_n%d.json" % (a.tag, a.size)),
                   dict(rows=out, switches=_switches(a), threads=a.threads), rt_class=_rtc)

        # D6: re-check quarantine AFTER each cell. A contradiction banked mid-run must stop the
        # run, not be discovered afterwards in an artifact that already looks finished.
        _q = _quarantine_new(_q0, spool)
        if _q:
            print("HALTED after %s: %d new untriaged quarantine row(s) -- %s"
                  % (cell, len(_q), ", ".join(sorted(_q))[:200]))
            if not a.no_bank:
                _write(os.path.join(ROOT, "runs", "oracle",
                                    "tep_solve_%s_n%d.json" % (a.tag, a.size)),
                       dict(rows=out, switches=_switches(a), complete=False,
                            halted_on=cell, halted_why="new untriaged quarantine rows",
                            quarantine_new=sorted(_q)))
            return 3

    if not a.no_bank:
        _write(os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_n%d.json" % (a.tag, a.size)),
               dict(rows=out, switches=_switches(a), complete=True))
        print("wrote runs/oracle/tep_solve_%s_n%d.json (%d cells)" % (a.tag, a.size, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
