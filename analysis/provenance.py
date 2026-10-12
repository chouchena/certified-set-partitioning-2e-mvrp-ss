"""provenance.py -- reproducibility stamp for EVERY logged result.

Answers "which code + config produced this number?": git SHA + branch + a DIRTY flag,
a content-hash of the actually-loaded code (robust to an uncommitted/dirty tree -- the
load-bearing key when git_dirty is True), the SEED, the CORE count, the solver+version,
platform, and an optional instance hash. Wired into runlog.RunLogger and
analysis.ledger.emit so no result is logged without it.

Design notes (hostile-audited 2026-09-06, see validation/provenance_design.md):
- The expensive parts (code hash, git, solver versions) are computed ONCE per process and
  cached (@lru_cache); only seed/cores/solver/ts vary per record -> emit() stays cheap.
- code_hash is authoritative when git_dirty (we edit mid-campaign); the SHA alone is not.
- Reproducibility bound: same {code_hash, seed, cores, solver, deterministic} reproduces a
  result UP TO solver parallel non-determinism (parallel MIP differs across core counts even
  at a fixed seed) -- hence `cores` and `deterministic` are recorded, not just `seed`.
- Import is fail-open at the call sites: a provenance failure must never break logging.
"""
from __future__ import annotations
import functools, hashlib, os, platform, socket, subprocess, sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root (parent of analysis/)


@functools.lru_cache(maxsize=1)
def _git() -> dict:
    def run(args):
        try:
            return subprocess.run(["git", "-C", _ROOT] + args, capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        except Exception:
            return ""
    sha = run(["rev-parse", "HEAD"]) or None
    return {"git_sha": (sha[:12] if sha else None),
            "git_full_sha": sha,
            "git_branch": (run(["rev-parse", "--abbrev-ref", "HEAD"]) or None) if sha else None,
            "git_dirty": (bool(run(["status", "--porcelain"])) if sha else None)}


@functools.lru_cache(maxsize=1)
def _code_hash() -> tuple:
    """sha256 over the CONTENTS of every loaded module whose file is under the project root
    -- the true code state of the running process (catches uncommitted edits a git SHA misses).
    Cached: modules loaded after the first call are not re-hashed (all harness code is loaded
    before the first log; acceptable)."""
    files = set()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if not f:
            continue
        try:
            rp = os.path.relpath(os.path.abspath(f), _ROOT)
        except Exception:
            continue
        if not rp.startswith("..") and rp.endswith(".py"):
            files.add(rp)
    h = hashlib.sha256()
    for rp in sorted(files):
        try:
            with open(os.path.join(_ROOT, rp), "rb") as fh:
                h.update(rp.encode()); h.update(b"\0"); h.update(fh.read()); h.update(b"\0")
        except Exception:
            continue
    return h.hexdigest()[:16], len(files)


@functools.lru_cache(maxsize=1)
def _cpu() -> str:
    """The CPU's marketing name, e.g. 'Intel(R) Core(TM) Ultra 7 258V'.

    RECORDED FROM 2026-09-14. Provenance captured `host` (a machine NAME) and `platform` (the OS
    string) but NOT the processor. validation/RT_LEG_DESIGN.md lists a host manifest as required
    for any hardware-normalised runtime claim to be POSSIBLE later; without the CPU model there
    is no record of what the runs actually ran on, so the comparison against Karademir et al.'s
    Xeon Gold 5218 could not be reconstructed from our own artifacts.

    Best-effort and never raises: an unknown CPU is recorded as None rather than blocking a run.
    """
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            try:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
            finally:
                winreg.CloseKey(k)
        if sys.platform == "darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True, timeout=5).stdout.strip() or None
        for line in open("/proc/cpuinfo", encoding="utf-8", errors="replace"):
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or None


@functools.lru_cache(maxsize=1)
def _solvers() -> dict:
    out = {}
    try:
        import cplex; out["cplex"] = str(cplex.__version__)
    except Exception:
        pass
    try:
        import gurobipy
        try:
            out["gurobi"] = ".".join(map(str, gurobipy.gurobi.version()))
        except Exception:
            out["gurobi"] = str(getattr(gurobipy, "__version__", "?"))
    except Exception:
        pass
    try:
        import ortools; out["ortools"] = str(ortools.__version__)
    except Exception:
        pass
    return out


@functools.lru_cache(maxsize=1)
def _static() -> tuple:
    g = _git()
    ch, nfiles = _code_hash()
    d = dict(g)
    d.update(code_hash=ch, code_nfiles=nfiles, solvers=_solvers(),
             py=platform.python_version(), platform=platform.platform(),
             host=socket.gethostname(), cpu=_cpu(),
             logical_cores=os.cpu_count())
    # return an immutable-ish snapshot; callers copy before mutating
    return tuple(sorted(d.items()))


def _file_hash(path) -> str | None:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except Exception:
        return None


def stamp(seed=None, cores=None, solver=None, deterministic=None, instance_file=None) -> dict:
    """Per-record provenance. Static parts cached; only run-specific fields vary."""
    rec = dict(_static())
    rec["seed"] = seed
    rec["cores"] = cores
    rec["solver"] = solver
    rec["deterministic"] = deterministic
    if instance_file:
        rec["instance_hash"] = _file_hash(instance_file)
    rec["complete"] = (rec.get("git_sha") is not None and seed is not None and cores is not None)
    return rec


def one_line(prov: dict) -> str:
    """Compact human string for a run header / sanity line."""
    if not prov:
        return "provenance: UNAVAILABLE"
    dirty = "+dirty" if prov.get("git_dirty") else ""
    return (f"code={prov.get('code_hash')}({prov.get('code_nfiles')}f) "
            f"git={prov.get('git_sha')}{dirty} seed={prov.get('seed')} "
            f"cores={prov.get('cores')} solver={prov.get('solver')} "
            f"complete={prov.get('complete')}")


if __name__ == "__main__":
    import json
    p = stamp(seed=1, cores=4, solver="cplex")
    print(json.dumps(p, indent=2))
    print(one_line(p))
