"""The 4-thread / single-tenancy rule (d47), moved OUT of a driver and INTO the artifact.

WHY THIS FILE EXISTS. d47 (2026-09-17) settled it: "Any run whose output will feed a REPORTED
RUNTIME requires single tenancy AND a fixed thread count regardless of det budgets... requires 4
threads and single tenancy." d48 verified the banked RTs against it. `RT_LEG_DESIGN.md:235`
states the four threads match K's four CPUs.

It was implemented in exactly ONE PLACE -- `analysis/run_full_grid.py`, `--threads` default 4
plus its one-cell-at-a-time loop -- and enforced by that driver's construction. On 2026-09-30 I
wrote a second driver, `banked_grid.py`, calling `tep_cg_banked.py`, which exposes no --threads
flag at all and hardcodes threads=1. Fifty-five artifacts were produced at one thread and their
walls went into a runtime comparison. FOUR LAYERS MISSED IT:

  artifact_guard   (write-time)  -- no thread check
  artifact_gate    (output sweep) -- no thread check
  banked_grid.verify (per cell)  -- eleven provenance fields, six RT fields, threads in neither
  release_gate G6                -- requires the KEY, over a crossfeed n20 glob that never
                                    reads runs/oracle, and tests PRESENCE not VALUE, so
                                    threads=1 satisfies it

A rule embedded in a driver does not travel to the next driver. This file is the rule as a
property of the ARTIFACT, so every writer inherits it whether or not its author knew d47.

THE HARDER HALF: d47's trigger is "any run whose output will FEED a reported runtime", and
nothing can evaluate that at write time. The grid was born `valid_bound: false` -- not citable --
so on its face the trigger did not apply; it applied later, when I put those walls in a
comparison table, which the sealed artifact could not know about. So the trigger is inverted
here: every artifact reporting seconds is classified AT WRITE TIME, and the default is the safe
one.

  submission  its wall may be quoted. REFUSED unless threads == 4 and tenancy == 1.
  diagnostic  its wall may never be quoted. Carries the reason why, in the artifact.

Absent a declaration the artifact is stamped `diagnostic` with a reason saying the writer never
classified it. Nothing breaks, and nothing becomes quotable by omission -- which is exactly how
`threads: 1` became quotable the first time.
"""
import os
import subprocess

# K ran on 4 CPUs Intel Xeon Gold 5218 (RT_LEG_DESIGN.md:235). Any wall figure we set beside
# theirs is produced at this thread count and no other. Changing it invalidates every banked RT.
SUBMISSION_THREADS = 4

# Where a writer may record its thread count. Searched at payload top level and inside `params`.
THREAD_KEYS = ("threads", "thread_count", "nthreads", "n_threads", "Threads")

SUBMISSION = "submission"
DIAGNOSTIC = "diagnostic"
UNDECLARED_REASON = ("the writer declared no rt_class, so this wall was never certified against "
                     "d47 (4 threads, single tenancy) and is not quotable")


class ThreadPolicyError(RuntimeError):
    """A run claiming its wall is quotable was not produced under d47's conditions."""


def thread_count(payload):
    """The thread count a payload records, or None when it records none."""
    if not isinstance(payload, dict):
        return None
    for holder in (payload, payload.get("params") if isinstance(payload.get("params"), dict) else {}):
        for k in THREAD_KEYS:
            v = holder.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and v > 0:
                return int(v)
    return None


def tenancy():
    """How many python processes are alive right now, this one included.

    A wall time measured beside another solver is a wall time of the pair, not of the run --
    d47's "single tenancy". Measured, because on 2026-09-30 a controlled solo re-run showed a
    3.6x slowdown from co-tenancy at identical LP values. Returns None when it cannot be
    measured, and an unmeasurable tenancy is treated as a failure for submission class, never
    as a pass.
    """
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True, timeout=15)
        n = len([ln for ln in (r.stdout or "").splitlines() if ln.strip().startswith('"python')])
        return n or None
    except Exception:
        return None


def machine_cores():
    """(physical, logical) for this host, or (None, None)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$c=Get-CimInstance Win32_Processor;"
                            "$c.NumberOfCores.ToString() + '|' + $c.NumberOfLogicalProcessors"],
                           capture_output=True, text=True, timeout=15)
        a, b = (r.stdout or "").strip().split("|")[:2]
        return int(a), int(b)
    except Exception:
        try:
            return None, os.cpu_count()
        except Exception:
            return None, None


def regime(threads, tenants, wall_s=None, cpu_s=None):
    """The CORES REGIME this run actually executed under, for the artifact AND the log.

    Requested threads is an intention; `cores_used` is what the machine granted, measured as
    cpu_s / wall_s. The two disagreed on 2026-09-30 -- `params.threads: 1` with cpu/wall 0.95 on
    the long cells, which is one core saturated and confirms the flag rather than trusting it.
    A run whose requested threads and measured cores disagree is the case worth seeing, so both
    are recorded and neither is inferred from the other.
    """
    cores, logical = machine_cores()
    used = None
    try:
        if wall_s and cpu_s is not None and float(wall_s) > 0:
            used = round(float(cpu_s) / float(wall_s), 3)
    except Exception:
        pass
    return {"threads_requested": threads, "cores_used_measured": used,
            "tenancy": tenants, "machine_cores": cores, "machine_logical": logical,
            "policy_threads": SUBMISSION_THREADS, "policy": "d47"}


def banner(reg, rt_class):
    """One line for the LOG, so the regime is visible at launch and not only after the fact."""
    return ("CORES REGIME  threads=%s  tenancy=%s  machine=%s/%s (phys/logical)  "
            "policy d47 wants %d  ->  rt_class=%s%s"
            % (reg.get("threads_requested"), reg.get("tenancy"), reg.get("machine_cores"),
               reg.get("machine_logical"), SUBMISSION_THREADS, rt_class,
               "" if rt_class == SUBMISSION else "  (wall NOT quotable)"))


def classify(payload, rt_class, threads, tenants):
    """The rt_class block for `_rt`, or ThreadPolicyError when submission is claimed falsely.

    Refuses rather than downgrades. A run launched as a submission run at the wrong thread count
    is a mistake to be corrected before it burns the compute, not a run to be quietly relabelled
    diagnostic -- relabelling is how the author's "backpatching" pattern starts.
    """
    if rt_class is None:
        return {"rt_class": DIAGNOSTIC, "rt_not_comparable": UNDECLARED_REASON,
                "threads": threads, "tenancy": tenants, "policy": "d47", "declared": False}
    if rt_class == DIAGNOSTIC:
        return {"rt_class": DIAGNOSTIC, "rt_not_comparable": "declared diagnostic by the writer",
                "threads": threads, "tenancy": tenants, "policy": "d47", "declared": True}
    if rt_class != SUBMISSION:
        raise ThreadPolicyError("rt_class must be %r or %r, got %r"
                                % (SUBMISSION, DIAGNOSTIC, rt_class))
    why = []
    if threads != SUBMISSION_THREADS:
        why.append("threads = %s, and d47 requires %d (K's four Xeon Gold 5218 CPUs; "
                   "RT_LEG_DESIGN.md:235)" % (threads, SUBMISSION_THREADS))
    if tenants is None:
        why.append("tenancy could not be measured, and an unmeasured tenancy is not single tenancy")
    elif tenants > 1:
        why.append("%d python processes alive, so this wall is the wall of a shared machine; "
                   "d47 requires single tenancy" % tenants)
    if why:
        raise ThreadPolicyError(
            "REFUSING TO WRITE: this run declares rt_class='submission', meaning its wall may be "
            "quoted beside K's. It was not produced under d47's conditions:\n  - %s\n"
            "Re-run at %d threads with nothing else on the machine, or declare "
            "rt_class='diagnostic' and accept that this wall can never be quoted."
            % ("\n  - ".join(why), SUBMISSION_THREADS))
    return {"rt_class": SUBMISSION, "threads": threads, "tenancy": tenants,
            "policy": "d47", "declared": True}


def quotable(artifact):
    """(True, None) if this artifact's wall may be quoted; (False, reason) otherwise."""
    rt = (artifact or {}).get("_rt") or {}
    cls = rt.get("rt_class")
    if cls == SUBMISSION:
        t = rt.get("threads")
        if t != SUBMISSION_THREADS:
            return False, "rt_class=submission but threads=%s" % t
        return True, None
    if cls is None:
        return False, ("no rt_class on the artifact: predates the policy or was written by a "
                       "writer that does not classify")
    return False, rt.get("rt_not_comparable") or "rt_class=%s" % cls
