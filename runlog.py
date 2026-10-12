"""
runlog.py -- structured run logging for the 2E-MVRP-SS solver work
(collaboration rule 4: maximum logging, the basis for stall / trigger
analysis and ablation).

Every run writes:
  * runs/<run_id>.jsonl   -- one JSON object per event, append-only
  * runs/summary.csv      -- one row per finished run (appended on close)

Logged per event: wall-clock (absolute + relative to run start), phase,
incumbent objective value (primal), best bound (dual), gap, the trigger
that produced the event, plus the run's fixed context (seed, instance,
config). Both primal and dual are first-class.

Rule 3 null-result rule: a run whose solution fails verifier.py is
QUARANTINED -- call `logger.quarantine(reason)` and its files move under
runs/invalid/ , excluded from runs/summary.csv. Nothing there is ever a
baseline or a cited number.

Quarantine is controlled by `close(run_valid=False)` -- a run is null ONLY
when the verifier REJECTED a solution, not merely when a bound was left
unproven (guard 2, 2026-09-01: block-A truncated-bound runs were being
wrongly quarantined). `verified=` is now metadata only.
Guard 1: a run whose best bound exceeds its best incumbent auto-quarantines
(structurally impossible for a valid minimisation -- e.g. the LBBD detour
double-count would have been caught automatically).
Guard 4: every quarantine appends a BLOCKING triage row to
runs/invalid/INDEX.md; `list_untriaged()` feeds the rules-auditor.

Usage:
    log = RunLogger("alns_C203_n20_s1", instance="C203", size=20,
                    config={"wls": 0.1, "tau": 20, "proximity": 0.0, "engine": "alns"},
                    seed=1)
    log.phase("construct")
    log.incumbent(742.1, trigger="initial_construction")
    log.phase("search")
    log.incumbent(731.4, trigger="operator:relocate")
    log.bound(705.0, trigger="lagrangian_rebound", extra={"n_subgrad_iters": 40})
    log.heartbeat()
    log.close(status="time_limit", verified=True)
"""
from __future__ import annotations

import csv
import json
import math
import os
import time
from datetime import datetime, timezone

try:                                    # fail-open: provenance must never break logging
    from analysis.provenance import stamp as _prov_stamp, one_line as _prov_one_line
except Exception:                       # pragma: no cover
    _prov_stamp = None
    _prov_one_line = None

_ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(_ROOT, "runs")
INVALID_DIR = os.path.join(RUNS_DIR, "invalid")
SUMMARY_CSV = os.path.join(RUNS_DIR, "summary.csv")
PROVENANCE_CSV = os.path.join(RUNS_DIR, "provenance.csv")   # sidecar, joined to summary by run_id
INVALID_INDEX = os.path.join(INVALID_DIR, "INDEX.md")
_PROV_FIELDS = ["run_id", "closed_at", "instance", "size", "seed", "cores", "solver",
                "code_hash", "git_sha", "git_dirty", "git_branch", "py", "platform",
                "host", "complete"]

# a bound above the incumbent by more than this (relative) is structurally
# impossible for a valid minimisation run -> auto-quarantine (guard 1).
# 1e-4 matches the solver mipgap so a proven-optimal rounding wobble
# (~-0.001 %) does not trip it.
_BOUND_OVER_INCUMBENT_RELTOL = 1e-4

_SUMMARY_FIELDS = [
    "run_id", "closed_at", "instance", "size", "seed", "engine",
    "wls", "tau", "proximity", "status", "verified",
    "final_incumbent", "final_bound", "final_gap_pct",
    "wall_s", "n_events", "n_incumbents", "n_bounds", "quarantined", "quarantine_reason",
    "config_json",
]


def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _gap_pct(incumbent, bound):
    """Relative optimality gap in %, minimisation: (inc - bound)/|inc|.
    Reported with the sign preserved so a bound above the incumbent
    (should never happen for a valid bound) shows up as negative."""
    if incumbent is None or bound is None:
        return None
    if incumbent == 0:
        return 0.0 if bound == 0 else None
    return round(100.0 * (incumbent - bound) / abs(incumbent), 6)


class RunLogger:
    def __init__(self, run_id, *, instance, size, config, seed=None,
                 cores=None, solver=None, deterministic=None):
        os.makedirs(RUNS_DIR, exist_ok=True)
        self.run_id = str(run_id)
        self.instance = instance
        self.size = size
        self.seed = seed
        self.config = dict(config)
        self.engine = self.config.get("engine")
        # seed + core count are first-class provenance (rule R13 / reproducibility)
        self.cores = cores if cores is not None else (
            self.config.get("cores") or self.config.get("threads") or self.config.get("workers"))
        self.solver = solver if solver is not None else self.config.get("solver")
        self.prov = None
        if _prov_stamp is not None:
            try:
                self.prov = _prov_stamp(seed=seed, cores=self.cores, solver=self.solver,
                                        deterministic=deterministic)
            except Exception:
                self.prov = None
        self._t0 = time.time()
        self._path = os.path.join(RUNS_DIR, f"{self.run_id}.jsonl")
        self._fh = open(self._path, "a", encoding="utf-8", buffering=1)  # line-buffered
        self._n_events = 0
        self._n_incumbents = 0
        self._n_bounds = 0
        self._best_incumbent = None
        self._best_bound = None
        self._cur_phase = None
        self._closed = False
        self._quarantined = False
        self._quarantine_reason = None
        self.event("run_start", trigger="init",
                   extra={"instance": instance, "size": size, "seed": seed,
                          "cores": self.cores, "solver": self.solver,
                          "config": self.config, "provenance": self.prov})

    # -- core ---------------------------------------------------------
    def event(self, phase, *, incumbent=None, bound=None, trigger=None, extra=None):
        if self._closed:
            raise RuntimeError("RunLogger already closed")
        if incumbent is not None:
            if self._best_incumbent is None or incumbent < self._best_incumbent:
                self._best_incumbent = incumbent
            self._n_incumbents += 1
        if bound is not None:
            if self._best_bound is None or bound > self._best_bound:
                self._best_bound = bound
            self._n_bounds += 1
        if phase is not None:
            self._cur_phase = phase
        now = time.time()
        rec = {
            "seq": self._n_events,
            "ts": _utcnow(),
            "wall_s": round(now - self._t0, 4),
            "phase": self._cur_phase,
            "trigger": trigger,
            "incumbent": incumbent,
            "bound": bound,
            "best_incumbent": self._best_incumbent,
            "best_bound": self._best_bound,
            "gap_pct": _gap_pct(self._best_incumbent, self._best_bound),
            "instance": self.instance,
            "size": self.size,
            "seed": self.seed,
        }
        if extra:
            rec["extra"] = extra
        self._fh.write(json.dumps(rec, default=str) + "\n")
        self._n_events += 1
        return rec

    # -- conveniences ----------------------------------------------
    def phase(self, name, *, trigger=None, extra=None):
        return self.event(name, trigger=trigger or f"phase:{name}", extra=extra)

    def incumbent(self, value, *, trigger, extra=None):
        return self.event(None, incumbent=float(value), trigger=trigger, extra=extra)

    def bound(self, value, *, trigger, extra=None):
        return self.event(None, bound=float(value), trigger=trigger, extra=extra)

    def heartbeat(self, *, extra=None):
        return self.event(None, trigger="heartbeat", extra=extra)

    def note(self, message, *, extra=None):
        e = {"message": message}
        if extra:
            e.update(extra)
        return self.event(None, trigger="note", extra=e)

    # -- termination ---------------------------------------------
    def quarantine(self, reason):
        """Rule 3 null-result rule: move this run's log under runs/invalid/."""
        self._quarantined = True
        self._quarantine_reason = reason
        self.event(None, trigger="quarantine", extra={"reason": reason})

    def _bound_exceeds_incumbent(self):
        b, i = self._best_bound, self._best_incumbent
        if b is None or i is None:
            return None
        if i <= 0:
            return b > i + 1e-6
        return b > i * (1.0 + _BOUND_OVER_INCUMBENT_RELTOL)

    def close(self, *, status, verified=None, run_valid=None,
              final_incumbent=None, final_bound=None):
        """
        `verified`  : metadata only -- did this run produce a verifier-clean
                      result (has a verified incumbent, port-equivalent, ...).
                      Written to summary.csv; does NOT by itself quarantine.
        `run_valid` : the quarantine control (guard 2). False -> the run is a
                      null result (verifier REJECTED a solution) -> quarantine.
                      None -> infer: a run is invalid only if the verifier
                      rejected something; a merely-unproven bound stays valid.
                      (Legacy callers that pass only `verified=False` and mean
                      "reject" still quarantine -- preserved below.)
        Guard 1: a run whose best bound exceeds its best incumbent (beyond
        solver tolerance) is structurally impossible and auto-quarantines
        regardless of the flags.
        """
        if self._closed:
            return
        if final_incumbent is not None:
            self._best_incumbent = final_incumbent
        if final_bound is not None:
            self._best_bound = final_bound
        wall = round(time.time() - self._t0, 3)

        bound_bug = self._bound_exceeds_incumbent()
        if bound_bug:
            self._quarantined = True
            self._quarantine_reason = (
                f"bound {self._best_bound} exceeds incumbent {self._best_incumbent} "
                f"(> {_BOUND_OVER_INCUMBENT_RELTOL:.0e} rel) -- invalid bound or unsound decomposition")

        # legacy compat: a caller passing only verified=False (no run_valid)
        # historically meant "reject". Keep that, but a caller that passes
        # run_valid explicitly controls it.
        reject = (run_valid is False) or (run_valid is None and verified is False)

        self.event("closed", trigger=f"close:{status}",
                   extra={"status": status, "verified": verified,
                          "run_valid": run_valid, "reject": reject,
                          "bound_exceeds_incumbent": bound_bug, "wall_s": wall})
        self._fh.close()
        self._closed = True
        self._write_provenance_row(status)   # every closed run -> one provenance.csv row

        if self._quarantined or reject:
            os.makedirs(INVALID_DIR, exist_ok=True)
            dest = os.path.join(INVALID_DIR, os.path.basename(self._path))
            try:
                os.replace(self._path, dest)
            except OSError:
                pass
            self._path = dest
            self._write_triage_stub(status, verified,
                                    reason=self._quarantine_reason
                                    or ("verifier rejected a solution" if reject else "quarantined"))
            return  # quarantined runs are NOT written to summary.csv

        self._append_summary(status, verified, wall)

    def _write_triage_stub(self, status, verified, *, reason):
        """Guard 4: every quarantine leaves a BLOCKING triage entry. The
        engine that produced it must not feed a claim until the root-cause
        defect is identified and this entry marked triaged."""
        os.makedirs(INVALID_DIR, exist_ok=True)
        new = not os.path.exists(INVALID_INDEX)
        with open(INVALID_INDEX, "a", encoding="utf-8") as fh:
            if new:
                fh.write("# Quarantined runs — triage log\n\n"
                         "Each row is a run where the solver and the independent verifier "
                         "**disagreed**, or a structurally invalid bound. That is a defect "
                         "in the solver or the verifier — more informative than any passing "
                         "run. **BLOCKING**: the engine that produced it cannot feed a "
                         "published claim until the root cause is found and `triaged` is set.\n\n"
                         "| when | run_id | engine | reason | incumbent | bound | status | triaged? |\n"
                         "|---|---|---|---|---|---|---|---|\n")
            fh.write(f"| {_utcnow()} | `{self.run_id}` | {self.engine} | {reason} | "
                     f"{self._best_incumbent} | {self._best_bound} | {status} | **NO** |\n")

    def _write_provenance_row(self, status):
        """Non-destructive sidecar: one provenance row per run, joined to summary.csv by
        run_id. Kept separate so adding provenance never rewrites/ corrupts summary.csv."""
        p = self.prov or {}
        row = {"run_id": self.run_id, "closed_at": _utcnow(), "instance": self.instance,
               "size": self.size, "seed": self.seed, "cores": self.cores, "solver": self.solver,
               "code_hash": p.get("code_hash"), "git_sha": p.get("git_sha"),
               "git_dirty": p.get("git_dirty"), "git_branch": p.get("git_branch"),
               "py": p.get("py"), "platform": p.get("platform"), "host": p.get("host"),
               "complete": p.get("complete")}
        try:
            new = not os.path.exists(PROVENANCE_CSV)
            with open(PROVENANCE_CSV, "a", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=_PROV_FIELDS)
                if new:
                    w.writeheader()
                w.writerow(row)
        except Exception:
            pass                         # fail-open

    def _append_summary(self, status, verified, wall):
        row = {
            "run_id": self.run_id,
            "closed_at": _utcnow(),
            "instance": self.instance,
            "size": self.size,
            "seed": self.seed,
            "engine": self.engine,
            "wls": self.config.get("wls"),
            "tau": self.config.get("tau"),
            "proximity": self.config.get("proximity"),
            "status": status,
            "verified": verified,
            "final_incumbent": self._best_incumbent,
            "final_bound": self._best_bound,
            "final_gap_pct": _gap_pct(self._best_incumbent, self._best_bound),
            "wall_s": wall,
            "n_events": self._n_events,
            "n_incumbents": self._n_incumbents,
            "n_bounds": self._n_bounds,
            "quarantined": self._quarantined,
            "quarantine_reason": self._quarantine_reason,
            "config_json": json.dumps(self.config, default=str),
        }
        new = not os.path.exists(SUMMARY_CSV)
        with open(SUMMARY_CSV, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=_SUMMARY_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)

    # -- context manager ------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self._closed:
            self.close(status="exception" if exc_type else "unclosed",
                       verified=None)
        return False


def read_run(run_id):
    """Load a run's events back as a list of dicts (for analysis)."""
    for base in (RUNS_DIR, INVALID_DIR):
        p = os.path.join(base, f"{run_id}.jsonl")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
    raise FileNotFoundError(run_id)


def list_untriaged():
    """Rows in runs/invalid/INDEX.md still marked '**NO**' for triaged.
    The rules-auditor calls this at each phase boundary — any hit blocks
    claims from the engine that produced it (guard 4)."""
    if not os.path.exists(INVALID_INDEX):
        return []
    out = []
    for line in open(INVALID_INDEX, encoding="utf-8"):
        if line.startswith("|") and "**NO**" in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 7:
                out.append({"when": cells[0], "run_id": cells[1].strip("`"),
                            "engine": cells[2], "reason": cells[3],
                            "incumbent": cells[4], "bound": cells[5], "status": cells[6]})
    return out


if __name__ == "__main__":
    # smoke test
    import tempfile
    with RunLogger("smoke_test", instance="C203", size=20,
                   config={"wls": 0.1, "tau": 20, "proximity": 0.0, "engine": "demo"},
                   seed=1) as log:
        log.phase("construct")
        log.incumbent(742.1, trigger="initial_construction")
        log.phase("search")
        log.bound(705.0, trigger="lagrangian_rebound", extra={"iters": 40})
        log.incumbent(731.4, trigger="operator:relocate")
        log.incumbent(720.0, trigger="operator:2opt")
        log.heartbeat()
        log.close(status="time_limit", verified=True)
    ev = read_run("smoke_test")
    print(f"{len(ev)} events logged")
    for e in ev:
        print(f"  seq={e['seq']:2} {e['wall_s']:>7.3f}s  phase={e['phase']!s:12} "
              f"trig={e['trigger']!s:24} inc={e['best_incumbent']} "
              f"bnd={e['best_bound']} gap%={e['gap_pct']}")
    print(f"\nsummary.csv exists: {os.path.exists(SUMMARY_CSV)}")
