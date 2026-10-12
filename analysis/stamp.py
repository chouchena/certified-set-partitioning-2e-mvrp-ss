"""Full provenance and real runtime on every result, or the result is not written at all.

THE AUTHOR'S RULE: whatever cannot be wired to its full provenance should be erased and checked
again. That is stricter than "record what you can" and it is the right way round -- a number
whose producing code cannot be named is not evidence, it is a rumour with a filename.

WHY IT WAS NEEDED. On 2026-09-20 an audit found 22 of 24 result files recorded NOTHING about the
code that made them. CLAUDE.md has required `code_hash` as the reproducibility anchor since long
before, and release-gate G6 enforces it -- over exactly one glob,
`crossfeed/easy_reduction_descend_*_n20.json`. Every oracle result written since walked around
the rule, not because the rule was absent but because the enforcement was never widened. Two
arbiter defects were then fixed without anyone being able to say which results predated them.

WHY IT REFUSES, since 2026-09-29. Recording a defect is not enforcing against it. This module
wrote `git_dirty: true` onto 96 of 96 banked bound artifacts and onto every one of an eight-cell,
six-hour n50 batch, and nothing stopped. The batch was then audited, found unreproducible, and
its seven results deleted -- they had bought zero LP value, only a `proven` flag, for 4.2 hours.
The audit was a postmortem where it should have been a precondition. A stamp that reports
dirtiness is a receipt for crap. This one raises:

  * `ProvenanceError` -- a value-determining source is uncommitted. Not "the tree is dirty":
    dirty logs and dirty artifacts never block. The named sources, plus every repository module
    actually imported into this process, must be clean and tracked. An UNTRACKED source is worse
    than a modified one and is refused the same way.
  * `RuntimeRecordError` -- the payload declares a budget (`max_secs`, `det_tl`, `time_limit`...)
    and records no runtime actually consumed, or no deterministic tick count. A cap is what we
    allowed, not what we spent; "not only cap" is the author's phrasing. Anything that declares a
    budget is a solver run, and a solver run reproduces on deterministic ticks, not on wall time
    (CLAUDE.md section 1). Read-only analyses declare no budget and are not asked for ticks.

There is no override flag and no environment escape. The remedy for a refusal is to commit the
code and re-run, or to pass the runtime you measured. That is the whole point.

USE. Wrap the payload at the point of writing:

    from analysis.stamp import stamped
    json.dump(stamped(payload, __file__, "joint_model_gurobi.py"), f, indent=1)

and for anything that ran under a budget, hand over what it spent:

    stamped(payload, __file__, det=model.getAttr("Work"), wall=secs)

`_provenance` then carries the sha256 of every named source, the global `code_hash`, the git sha
and dirty flag, python, host, platform, solver versions and the timestamp; `_rt` carries the
runtime measured by this module and whatever the caller measured itself. G23 recomputes the
source hashes and reports any result whose producing code has since changed.

NAME SOURCES BY PATH, not by nickname. An earlier version keyed on labels like "builder", which
cannot be resolved back to a file, so the gate reported drift on two results that had none.
"""
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Process start, as close as this module can get to it. A script imports stamp near the top, so
# these are the run's own clock; a long-lived interpreter must pass `wall=` explicitly.
_T0_WALL = time.time()
_T0_CPU = time.process_time()

# A payload carrying any of these declared a BUDGET -- what we ALLOWED.
CAP_KEYS = ("max_secs", "maxsecs", "time_limit", "timelimit", "tl", "det_tl", "cap_s",
            "max_seconds", "secs_cap", "budget_s", "lb_cell_seconds")
# A payload carrying any of these with a number recorded what it SPENT. This is the trigger:
# anything that reports seconds is reporting a runtime, and a runtime must reproduce.
RT_KEYS = ("secs", "seconds", "wall_s", "wall_secs", "runtime_s", "elapsed", "elapsed_s",
           "secs_total", "rt_s", "time_s", "cg_secs", "total_secs", "solve_s", "descent_s",
           "total_s", "build_s", "bound_s", "lookup_s", "price_s", "solver_s", "ab4_s")
# A payload carrying any of these recorded a DETERMINISTIC clock. Deliberately narrow: an
# iteration or label count is a progress counter, not a clock, and admitting `iters` here would
# have let every banked bound artifact through -- they all carry one.
DET_KEYS = ("det_ticks", "det", "work", "work_units", "ticks", "deterministic_ticks",
            "det_work", "gurobi_work")


class ProvenanceError(RuntimeError):
    """A value-determining source is uncommitted. Refused before anything is written."""


class RuntimeRecordError(RuntimeError):
    """A budgeted run recorded no runtime consumed, or no deterministic clock."""


class CrossHashOverwriteError(RuntimeError):
    """A result from one code release would silently replace a result from another."""


def assert_no_cross_hash_overwrite(prov, path, supersede=False):
    """REFUSE to replace an artifact that a DIFFERENT code release produced.

    WHY. A run writes to a path derived from the cell and size, never from the code that
    produced it, so two releases collide silently on one filename. On 2026-09-30 a single
    diagnostic invocation -- `tep_cg_bound.py R202 --size 30` -- overwrote the 2026-09-25 corpus
    artifact for that cell: `code_hash e24bcc52` replaced by `26b414c6`, same path, no warning,
    no prompt. The values happened to agree to all 16 digits, and it was recoverable only
    because that particular file was tracked. Most are not: all 65 `tep_cg_banked_*` artifacts
    are untracked (d621), so the same accident there is unrecoverable.

    THE TEST IS ON `source_hash`, not `git_sha` and not `code_hash`. `git_sha` does not
    reconstruct a dirty tree -- the whole banked corpus carries `git_dirty: true`. `code_hash`
    is repro_preflight's fixed nine-file list, which contains none of lb_solver, tep_cg_bound,
    tep_pricer, fullset_bound or bound_certificate, so two runs with completely different
    column-generation code produce a byte-identical one. `source_hash` covers the sources that
    actually determined the value, which is the only hash that answers "is this the same code".

    A matching hash overwrites freely: that is a re-run of the same code and is what
    reproducibility means. A differing hash raises, and the caller either passes
    `supersede=True` deliberately or writes beside it -- `sidecar_path` gives the name.
    """
    if supersede or not path or not os.path.exists(path):
        return
    try:
        old = json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return                      # unreadable or not ours: the guillotine's problem, not this
    if isinstance(old, list):
        old = old[0] if old and isinstance(old[0], dict) else {}
    op = (old or {}).get("_provenance") or {}
    old_h, new_h = op.get("source_hash"), (prov or {}).get("source_hash")
    if not old_h or not new_h or old_h == new_h:
        return
    raise CrossHashOverwriteError(
        "REFUSING TO WRITE: %s was produced by a DIFFERENT code release and this write would "
        "replace it.\n  on disk : source_hash %s   (%s)\n  writing : source_hash %s\n"
        "A result is evidence for the code that produced it. Write beside it -- %s -- or pass "
        "supersede=True if you mean to destroy the older result and can say why."
        % (os.path.relpath(path, ROOT).replace("\\", "/"), old_h, op.get("when", "when unknown"),
           new_h, os.path.basename(sidecar_path(path, new_h))))


def sidecar_path(path, source_hash):
    """`runs/x/a.json` -> `runs/x/a__<hash8>.json`, so two releases coexist instead of racing."""
    base, ext = os.path.splitext(path)
    return "%s__%s%s" % (base, (source_hash or "nohash")[:8], ext)


def _sha(path):
    try:
        return hashlib.sha256(io.open(path, "rb").read()).hexdigest()[:16]
    except Exception:
        return None


def _git(*args):
    try:
        r = subprocess.run(["git"] + list(args), capture_output=True, text=True, cwd=ROOT)
        return (r.stdout or "").strip()
    except Exception:
        return None


def _cpu():
    """CPU model, physical and logical cores -- AOR asks for wall time with threads stated, and the runtime
    comparison with the predecessors (their 4 CPUs Intel Xeon Gold 5218) needs the machine on the artifact,
    not only in a design document (2026-09-27: no banked artifact carried it)."""
    out = {}
    try:
        out["model"] = platform.processor() or None
        import multiprocessing as _mp
        out["logical"] = _mp.cpu_count()
    except Exception:
        pass
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$c=Get-CimInstance Win32_Processor; $c.Name + '|' + $c.NumberOfCores + '|' + $c.NumberOfLogicalProcessors"],
                           capture_output=True, text=True, timeout=20)
        parts = (r.stdout or "").strip().split("|")
        if len(parts) == 3:
            out["model"] = parts[0].strip(); out["cores"] = int(parts[1]); out["logical"] = int(parts[2])
    except Exception:
        pass
    return out or None


def _resolve(s):
    """A named source to its repo-relative posix path, or None if it is outside the repo."""
    p = s if os.path.isabs(s) else os.path.join(ROOT, s)
    if not os.path.exists(p):
        p = os.path.join(ROOT, "analysis", os.path.basename(s))
    if not os.path.exists(p):
        return None
    try:
        rp = os.path.relpath(os.path.abspath(p), ROOT)
    except ValueError:
        return None
    return None if rp.startswith("..") else rp.replace("\\", "/")


def _worktree_status():
    """{repo-relative posix path: porcelain code} for everything git does not consider clean,
    UNTRACKED FILES INCLUDED. Untracked is the more dangerous state: a modified source at least
    has a committed ancestor to diff against; an untracked one has nothing."""
    out = {}
    txt = _git("status", "--porcelain=v1", "--untracked-files=all")
    if not txt:
        return out
    for line in txt.splitlines():
        if len(line) < 4:
            continue
        code, p = line[:2], line[3:].strip()
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        if " -> " in p:                       # a rename: the destination is what exists now
            p = p.split(" -> ")[-1]
        out[p.replace("\\", "/")] = code.strip() or "?"
    return out


def code_in_play(sources):
    """Every repository .py that could have determined this value.

    The named sources, PLUS every repository module already imported into this process. The
    second half is what makes this enforcement rather than paperwork: a writer that names only
    its own file cannot narrow the check to its own file, because the solver it called is in
    sys.modules and will be caught there.
    """
    files = set()
    for s in sources:
        rp = _resolve(s)
        if rp:
            files.add(rp)
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if not f or not str(f).endswith(".py"):
            continue
        try:
            rp = os.path.relpath(os.path.abspath(f), ROOT)
        except (ValueError, OSError):
            continue
        if not rp.startswith(".."):
            files.add(rp.replace("\\", "/"))
    return files


def assert_clean_sources(sources):
    """Raise ProvenanceError naming every uncommitted file that helped determine this value."""
    status = _worktree_status()
    if not status:
        return
    offenders = sorted((p, status[p]) for p in code_in_play(sources) if p in status)
    if not offenders:
        return
    lines = ["  %-5s %s" % ("??" if c == "?" else c, p) for p, c in offenders]
    raise ProvenanceError(
        "REFUSING TO WRITE: %d value-determining source(s) are uncommitted, so this result "
        "could never be reproduced from its git_sha.\n%s\n"
        "Commit them and re-run. There is no override: a result whose code cannot be named is "
        "not evidence (CLAUDE.md section 1; the seven n50 artifacts deleted 2026-09-29)."
        % (len(offenders), "\n".join(lines)))


def _first_num(payload, keys):
    """The first key present anywhere in the payload -- top level, or inside a `rows`/`cells`
    list -- carrying a real number. Batch drivers put the per-run figures one level down."""
    def num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    for k in keys:
        if num(payload.get(k)):
            return k, payload[k]
    for holder in ("rows", "cells", "results", "runs", "per_cell"):
        seq = payload.get(holder)
        if isinstance(seq, list):
            for row in seq:
                if isinstance(row, dict):
                    for k in keys:
                        if num(row.get(k)):
                            return "%s[].%s" % (holder, k), row[k]
        elif isinstance(seq, dict):
            for row in seq.values():
                if isinstance(row, dict):
                    for k in keys:
                        if num(row.get(k)):
                            return "%s{}.%s" % (holder, k), row[k]
    return None, None


def det_present(payload, det=None):
    """Is a deterministic clock recorded? Shared by the write-time check and the output gate so
    there is one definition, not two that can drift.

    A clock may be a NUMBER under a DET_KEY, or a non-empty MAPPING of named components. The
    mapping form exists because this solver has two deterministic costs in different units --
    Gurobi work units on the master LP and labels generated in the pricer -- and adding them
    would produce a figure that means nothing. They are recorded side by side and neither is
    summed into the other.
    """
    def ok(v):
        if isinstance(v, dict):
            return bool(v)
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if ok(det):
        return True
    if not isinstance(payload, dict):
        return False
    rt = payload.get("_rt")
    if isinstance(rt, dict) and ok(rt.get("det_ticks")):
        return True
    for k in DET_KEYS:
        if ok(payload.get(k)):
            return True
    for holder in ("rows", "cells", "results", "runs", "per_cell"):
        seq = payload.get(holder)
        rows = seq if isinstance(seq, list) else (list(seq.values()) if isinstance(seq, dict) else [])
        for row in rows:
            if isinstance(row, dict) and any(ok(row.get(k)) for k in DET_KEYS):
                return True
    return False


def assert_runtime_recorded(payload, det, wall):
    """An artifact that reports a runtime must report one that reproduces, and a cap is not one.

    TWO TRIGGERS, and the first is the one that matters.

    (a) The payload REPORTS SECONDS. Then it is reporting a runtime, and a wall figure alone does
        not reproduce: it is the machine, the load and the day. It must carry a deterministic
        clock beside it. This fires on every solver artifact we write, because every one of them
        carries `secs`.

    (b) The payload declares a BUDGET and reports nothing spent. A cap is what we allowed, not
        what we spent -- the author's "not only cap".

    An analysis that reports no seconds at all is held to neither; `_rt` still records what this
    process spent, so no artifact leaves here without a runtime.

    WHY (a) AND NOT ONLY (b). The first version of this check triggered on (b) alone and would
    have passed all seven deleted artifacts untouched: `max_secs` is an argument to run() and is
    never written to the artifact, so no banked bound artifact declares a budget at all. A rule
    whose trigger never fires is decoration. Found by reading the keys of a real artifact rather
    than the keys I assumed it had.
    """
    if not isinstance(payload, dict):
        return
    cap_key, cap_val = _first_num(payload, CAP_KEYS)
    rt_key, rt_val = _first_num(payload, RT_KEYS)
    has_det = det_present(payload, det)
    if cap_key is not None and rt_key is None and wall is None:
        raise RuntimeRecordError(
            "REFUSING TO WRITE: the payload declares a budget (%s = %s) and records no runtime "
            "consumed. A cap is what we allowed, not what we spent. Put one of %s on the payload "
            "or pass wall= to stamped()." % (cap_key, cap_val, ", ".join(RT_KEYS[:5])))
    if (rt_key is not None or wall is not None) and not has_det:
        raise RuntimeRecordError(
            "REFUSING TO WRITE: the payload reports a runtime (%s = %s) with no deterministic "
            "clock beside it, so that runtime does not reproduce -- it is this machine on this "
            "day. CLAUDE.md section 1: deterministic tick budgets, not wall-clock, wherever a "
            "result must reproduce. Pass det= to stamped(), or put one of %s on the payload. "
            "Gurobi's model.getAttr('Work') is the clock; an iteration or label count is a "
            "progress counter and is NOT accepted here."
            % (rt_key if rt_key else "wall=", rt_val if rt_key else wall, ", ".join(DET_KEYS[:4])))


def runtime_record(det=None, wall=None, cpu=None, payload=None, rt_class=None):
    """What this process actually spent. Measured here, not taken on trust from the caller.

    Also carries the d47 thread/tenancy classification, so a wall figure cannot become quotable
    by nobody having asked the question. See `analysis/rt_class.py` for why that lives on the
    artifact instead of in a driver.
    """
    out = {"wall_s": round(time.time() - _T0_WALL, 3) if wall is None else round(float(wall), 3),
           "wall_measured_by": "analysis/stamp.py" if wall is None else "caller",
           "process_wall_s": round(time.time() - _T0_WALL, 3),
           "cpu_s": round(time.process_time() - _T0_CPU, 3) if cpu is None else round(float(cpu), 3),
           "det_ticks": det,
           "clock": "time.time / time.process_time since analysis.stamp import"}
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    import rt_class as _rtc
    _th, _ten = _rtc.thread_count(payload), _rtc.tenancy()
    out.update(_rtc.classify(payload, rt_class, _th, _ten))
    out["cores_regime"] = _rtc.regime(_th, _ten, out["wall_s"], out["cpu_s"])
    # The regime goes to the LOG as well as the artifact. An artifact is read after the run; a
    # log line is visible while it is still cheap to kill the run.
    try:
        print(_rtc.banner(out["cores_regime"], out["rt_class"]), flush=True)
    except Exception:
        pass
    return out


_TOL_CACHE = [None]


def _gurobi_tolerances():
    """The numerical tolerances a Gurobi model gets here, recorded so a result can be reproduced.

    WHY, and the author had to correct me to get here. Asked whether FeasibilityTol could be
    tightened project-wide I argued against it, on the ground that changing it would move LP
    values in the last digits and make the banked corpus non-reproducible. Author: "I challenge
    your push back of finer Gurobi range. it should simply be recorded in artifacts parameter."

    That is right and my argument was inverted. Measured: of 399 artifacts under runs/oracle,
    ZERO record any solver tolerance. Every banked result was produced under the 1e-6 default
    and none of them says so, so they are ALREADY not reproducible with respect to a parameter
    nobody wrote down. Recording it does not create the exposure, it reveals it -- and once the
    value is on the artifact, changing it is an ordinary tracked release, which the cross-release
    overwrite guard already handles.

    These are the DEFAULTS in force for a fresh model. A writer that overrides them on its own
    model must put its values in `params`; the arbiter does. Cached, because it costs an
    environment to read.
    """
    if _TOL_CACHE[0] is not None:
        return _TOL_CACHE[0]
    out = {}
    try:
        import gurobipy as gp
        m = gp.Model()
        m.Params.OutputFlag = 0
        for k in ("FeasibilityTol", "IntFeasTol", "OptimalityTol", "MIPGap", "NumericFocus"):
            try:
                out[k] = m.getParamInfo(k)[2]        # the value currently in force
            except Exception:
                pass
        out["source"] = "gurobipy defaults for a fresh model"
        m.dispose()
    except Exception as e:
        out = {"error": "%s: %s" % (type(e).__name__, e)}
    _TOL_CACHE[0] = out
    return out


def provenance(*sources):
    """Everything needed to say which code, solver and machine produced a result."""
    src = {}
    for s in sources:
        rp = _resolve(s)
        if rp:
            src[rp] = _sha(os.path.join(ROOT, rp))
    # TWO notions of dirty, and only the second is load-bearing. `git_dirty` is the blunt
    # worktree flag and is true whenever an untracked LOG sits in the tree, which cannot affect
    # reproducibility; it is kept because every banked artifact carries it. `sources_dirty` is
    # the set that actually determined this value -- the named sources plus every repository
    # module imported into this process -- and is what the gate tests. They disagreed the first
    # time a compliant write was attempted after the rule was adopted: the sources were clean,
    # `git status` was not, and the guillotine refused a legitimate artifact.
    dirty_sources = sorted(p for p in code_in_play(sources) if p in _worktree_status())
    out = {"sources": src, "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "git_sha": _git("rev-parse", "--short=12", "HEAD"),
           "git_dirty": bool(_git("status", "--porcelain")),
           "sources_dirty": dirty_sources,
           "python": platform.python_version(), "host": platform.node(),
           "platform": platform.platform(), "cpu": _cpu()}
    # SOURCE_HASH: a code_hash over the sources THAT ACTUALLY DETERMINED THIS VALUE.
    # `code_hash` below is repro_preflight's, over a FIXED nine-file list that contains none of
    # lb_solver, tep_cg_bound, tep_pricer, fullset_bound or bound_certificate -- so two runs
    # with completely different column-generation code produce a byte-identical code_hash
    # (audit, 2026-09-29). It is kept for continuity with the banked corpus; this is the one
    # that pins the code in play. `unresolved` names any source that could not be found on
    # disk, which previously vanished in silence.
    _h = hashlib.sha256()
    unresolved = []
    for s_ in sources:
        rp = _resolve(s_)
        if rp is None:
            unresolved.append(s_)
        else:
            _h.update(rp.encode("utf-8")); _h.update((_sha(os.path.join(ROOT, rp)) or "").encode("utf-8"))
    out["source_hash"] = _h.hexdigest()[:16]
    out["sources_unresolved"] = unresolved

    # CODE IN PLAY: the named sources PLUS every repository module actually imported into this
    # process, each hashed, and the whole set hashed. This is the "full code" anchor.
    #
    # WHY IT IS NEEDED. `code_hash` above is repro_preflight's, over a FIXED nine-file list --
    # crossfeed/block_a, easy_reduction, blockA_cpsat, easy_reduction_descend, bound_tracer,
    # build_instance, joint_model_cplex, joint_model_gurobi, solver/engines/fixopt. It contains
    # NONE of the LB solver, so two releases with entirely different column-generation code
    # produce a byte-identical code_hash; it could not tell lb-banked-1.2 from 1.3. CLAUDE.md
    # names code_hash "the reproducibility anchor", and for the dual leg it is not one.
    #
    # code_hash IS NOT CHANGED, deliberately: 2,962 banked artifacts carry it and altering the
    # file list would make every one of them incomparable with everything written afterwards
    # for a reason that is not a code change. The legacy value is kept and this is recorded
    # beside it.
    #
    # `source_hash` above is narrower -- only the sources a writer thought to NAME. A writer
    # that forgets one gets a clean-looking source_hash; this set is derived from sys.modules
    # and cannot be under-declared.
    play = sorted(code_in_play(sources))
    _p = hashlib.sha256()
    files = {}
    for rp in play:
        sh = _sha(os.path.join(ROOT, rp))
        files[rp] = sh
        _p.update(rp.encode("utf-8")); _p.update((sh or "").encode("utf-8"))
    out["code_in_play_hash"] = _p.hexdigest()[:16]
    out["code_in_play_n"] = len(play)
    out["code_in_play"] = files
    # repro_preflight.code_hash skips a SRC entry that is not on disk WITHOUT SAYING SO, so a
    # renamed file silently narrows the anchor. Name the absentees.
    try:
        from repro_preflight import SRC as _SRC
        out["code_hash_missing"] = [x for x in _SRC if not os.path.exists(os.path.join(ROOT, x))]
        out["code_hash_covers"] = list(_SRC)
    except Exception:
        out["code_hash_missing"] = None
    try:
        sys.path.insert(0, os.path.join(ROOT, "analysis"))
        from repro_preflight import code_hash, solver_versions
        out["code_hash"] = code_hash()
        out["solver_versions"] = solver_versions()
    except Exception as e:
        out["code_hash_error"] = "%s: %s" % (type(e).__name__, e)
    try:
        import gurobipy as gp
        out["gurobi"] = ".".join(str(x) for x in gp.gurobi.version())
    except Exception:
        pass
    out["solver_tolerances"] = _gurobi_tolerances()
    return out


def stamped(payload, *sources, **kw):
    """The payload with `sources`, `_provenance` and `_rt` attached -- or an exception.

    Raises ProvenanceError if any value-determining source is uncommitted, and
    RuntimeRecordError if a budgeted run recorded no runtime consumed or no deterministic clock.
    Both fire BEFORE the payload is touched, so a refused write leaves nothing behind.

    Keywords: det= deterministic ticks, wall= seconds consumed, cpu= cpu seconds.

    A payload that ALREADY carries a `sources` map keeps it: the writer's own census is merged
    with, not replaced by, the file named here. oracle_L2 hashes the builder and both model files
    it audits; wrapping it must not narrow that to the script itself. On a key collision the
    payload's own hash wins, because it was taken at the moment the source was actually read.
    """
    det, wall, cpu = kw.pop("det", None), kw.pop("wall", None), kw.pop("cpu", None)
    rt_class = kw.pop("rt_class", None)
    path = kw.pop("path", None)              # where this will be written, for the cross-hash guard
    supersede = kw.pop("supersede", False)   # deliberate replacement of another release result
    if kw:
        raise TypeError("stamped() got unexpected keyword(s): %s" % ", ".join(sorted(kw)))
    # The guillotine must be UP before anything is stamped. Checked here rather than at module
    # import so that `artifact_gate.py` -- which imports this module -- stays runnable when the
    # guard is down, which is exactly when someone needs it to diagnose why.
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    from artifact_guard import require_armed
    require_armed("this writer")
    assert_clean_sources(sources)
    assert_runtime_recorded(payload, det, wall)
    prov = provenance(*sources)
    assert_no_cross_hash_overwrite(prov, path, supersede)
    if supersede and path:
        # tell the interpreter-level guillotine this one replacement is deliberate; it
        # consumes the permission once, so a second write is refused again.
        from artifact_guard import allow_supersede
        allow_supersede(path)
    rt = runtime_record(det, wall, cpu, payload=payload, rt_class=rt_class)
    if not isinstance(payload, dict):
        return {"result": payload, "sources": prov["sources"], "_provenance": prov, "_rt": rt}
    out = dict(payload)
    merged = dict(prov["sources"])
    own = payload.get("sources")
    if isinstance(own, dict):
        merged.update(own)
    out["sources"] = merged                 # G23 reads this key directly
    prov["sources"] = merged
    out["_provenance"] = prov
    out["_rt"] = rt
    return out


def load_result(path):
    """Read a stamped result, returning the PAYLOAD whatever shape it was written in.

    stamped() wraps a non-dict payload as {"result": ...} so that provenance has somewhere to
    live. That changes the artifact's shape, and a reader written against the bare list breaks on
    it. This is the one place that knows about the wrapper, so readers do not each have to.

    Accepts an unstamped legacy file unchanged -- those are being regenerated, and a reader that
    refused them would fail on artifacts it is supposed to help replace.
    """
    import io as _io
    import json as _json
    d = _json.load(_io.open(path, encoding="utf-8"))
    if isinstance(d, dict) and "result" in d and "_provenance" in d:
        return d["result"]
    return d
