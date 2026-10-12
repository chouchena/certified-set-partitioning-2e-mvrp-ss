"""Replicability gate for any run whose output may reach the paper.

USER REQUIREMENT (2026-09-10): "Full provenance data and replicability is an ABSOLUTE
REQUIREMENT for any future published result, including seed, committed code release etc."

A result is replicable only if a third party can recover BOTH halves: the exact code, and the
exact settings. This project has already lost a campaign to the first half (a mid-run edit to
fixopt.py silently changed code_hash between the treatment and its control), so the gate is
mechanical rather than a habit.

WHAT THIS REFUSES
1. A DIRTY WORKING TREE. `git_sha` identifies a commit; if the tree is dirty the sha does not
   identify the code that actually ran, and no one can check the artifact out and re-run it.
   A campaign must start from a committed state. `--allow-dirty` exists for smoke runs only and
   stamps allow_dirty=True into the manifest so such artifacts can never be mistaken for
   publishable ones.
2. CO-TENANCY, when the caller asks for it -- a wall-clock time limit makes every truncated
   bound a function of machine load, so a second solver on the box changes the numbers.

WHAT IT RECORDS -- runs/releases/<sha>_<ts>.json, the manifest a replicator would need:
commit sha, tree cleanliness, code_hash over the solver sources, seed, CPLEX/docplex versions,
host and platform, thread count, PYTHONHASHSEED, and the exact argv.

WHY THE SEED MATTERS HERE SPECIFICALLY. We report truncated dual bounds as valid LBs (proof
Step 0). A PROVEN optimum is seed-independent in value; a TRUNCATED bound is whatever the
search reached, so it moves with the seed, the thread count and the parallel mode. Those are
now pinned (randomseed fixed, parallel=1 deterministic, threads fixed) and det_ticks is logged
per solve so a replicator can substitute dettimelimit for the wall-clock limit and reproduce
the value exactly on different hardware.
"""
from __future__ import annotations
import hashlib, json, os, platform, subprocess, sys, time
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# WIDENED 2026-09-21. This covered only crossfeed/* and build_instance.py, so a change to
# a MODEL BUILDER or to the primal ENGINE did not move code_hash -- and CLAUDE.md calls
# code_hash "the reproducibility anchor". The (26) encoding was replaced in both builders
# that day and ten banked grid cells would have been silently accepted as current by
# run_full_grid's resume check, which compares exactly this hash.
SRC = ("crossfeed/block_a.py", "crossfeed/easy_reduction.py", "crossfeed/blockA_cpsat.py",
       "crossfeed/easy_reduction_descend.py", "crossfeed/bound_tracer.py",
       "build_instance.py", "joint_model_cplex.py", "joint_model_gurobi.py",
       "solver/engines/fixopt.py")


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=15).stdout.strip()
    except Exception:
        return ""


def code_hash():
    h = hashlib.sha256()
    for rel in SRC:
        fp = os.path.join(ROOT, rel)
        if os.path.exists(fp):
            h.update(open(fp, "rb").read())
    return h.hexdigest()[:8]


def solver_versions():
    out = {}
    try:
        import docplex.mp
        out["docplex"] = docplex.mp.__version__
    except Exception:
        out["docplex"] = None
    try:
        import cplex
        out["cplex"] = cplex.__version__
    except Exception:
        out["cplex"] = None
    return out


def live_solvers():
    o = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                        "Where-Object { $_.CommandLine -like '*easy_reduction*' -or "
                        "$_.CommandLine -like '*fixopt.py*' }).Count"],
                       capture_output=True, text=True).stdout.strip()
    try:
        return int(o or 0)
    except ValueError:
        return -1


# The six domains every launch must answer BEFORE it runs (user, 2026-09-10). These are the
# places this project has actually failed, one field each:
#   sample_choice   -- lb_campaign ran C201/R201/RC201 first: the three EASIEST cells
#   sample_position -- the n100 probe used C201, gap 0/0, the easiest instance in the dataset
#   design          -- k_cap=14 vs k_hi=15; tl vs cell_budget; ten cells lost
#   replicability   -- seed pinning alone left truncated bounds irreproducible
#   rt              -- "time to beat K" and "time to exhaust the descend" were conflated
#   rules           -- pre-mortems asked "is the design right?", never "does the output look right?"
ATTEST = ("sample_choice", "sample_position", "design", "replicability", "rt", "rules")


def _claims_gate():
    """A claim marked MEASURED whose falsifier was NEVER RUN is asserting evidence we did not
    collect. That blocks. ASSUMED claims do NOT block -- honest uncertainty is not malpractice,
    and a gate that punishes it would just get routed around."""
    try:
        rows = json.load(open(os.path.join(ROOT, "validation", "claims.json"), encoding="utf-8"))
    except Exception:
        return []
    bad = [r["id"] for r in rows
           if r.get("status") == "STANDING" and r.get("evidence") == "MEASURED"
           and not (r.get("falsifier_run") or "").strip()]
    return bad


# Paths whose modification does NOT change what code runs. The dirty-tree gate exists to make
# git_sha identify the CODE; run OUTPUTS are not inputs to it. Without this exclusion the gate
# is self-defeating in a chain: a campaign writes an artifact per completed cell, so by the time
# it finishes the tree is dirty with its own results and the NEXT stage refuses to launch --
# which would have silently killed the chained n30 repair overnight on 2026-09-10.
_DATA_SUFFIX = (".json", ".csv", ".log", ".out", ".jsonl")
_DATA_DIRS = ("runs/", "crossfeed/", "validation/")


def _code_dirty():
    """Porcelain lines that represent SOURCE changes, ignoring run outputs."""
    out = []
    for line in _git("status", "--porcelain").splitlines():
        path = line[3:].strip().strip('"')
        if path.endswith(_DATA_SUFFIX) and path.startswith(_DATA_DIRS):
            continue
        out.append(line)
    return out


def preflight(campaign, *, seed, threads, allow_dirty=False, require_single_tenant=True,
              extra=None, attest=None):
    """Gate + manifest. Returns the manifest dict; exits the process on refusal."""
    _cd = _code_dirty()
    dirty = bool(_cd)
    sha = _git("rev-parse", "HEAD")
    if dirty and not allow_dirty:
        changed = "\n".join(_cd)
        sys.exit(
            "REFUSING to launch campaign '%s': the working tree is DIRTY, so git_sha %s does "
            "not identify the code that would run and the result could not be replicated by "
            "anyone.\nCommit first (or pass --allow-dirty for a NON-PUBLISHABLE smoke run).\n"
            "Uncommitted:\n%s" % (campaign, sha[:8], changed))
    if require_single_tenant:
        n = live_solvers()
        if n > 0:
            sys.exit("REFUSING to launch campaign '%s': %d solver process(es) already live. "
                     "The time limit is wall-clock, so a co-tenant changes every truncated "
                     "bound." % (campaign, n))
    bad = _claims_gate()
    if bad:
        sys.exit(f"REFUSING to launch '{campaign}': these claims are marked MEASURED but their "
                 f"falsifier was never run -- that is asserting evidence we did not collect: "
                 f"{bad}. Run the falsifier or downgrade the claim to INFERRED/ASSUMED.")
    attest = attest or {}
    missing = [k for k in ATTEST if not str(attest.get(k, "")).strip()]
    if missing:
        sys.exit(f"REFUSING to launch '{campaign}': the pre-launch attestation is "
                 f"incomplete. Missing {missing}.\n"
                 f"Each field is a place this project has actually FAILED; answer them "
                 f"BEFORE burning compute, not in the post-mortem.")
    man = dict(campaign=campaign, attest=attest, git_sha=sha, git_dirty=dirty, allow_dirty=bool(allow_dirty),
               code_hash=code_hash(), seed=seed, threads=threads,
               host=platform.node(), platform=platform.platform(),
               python=platform.python_version(),
               pythonhashseed=os.environ.get("PYTHONHASHSEED"),
               cplex_parallel="deterministic(1)",
               ts=time.strftime("%Y-%m-%dT%H:%M:%S"), argv=sys.argv)
    man.update(solver_versions())
    if extra:
        man.update(extra)
    d = os.path.join(ROOT, "runs", "releases")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{campaign}_{sha[:8]}_{time.strftime('%Y%m%d-%H%M%S')}.json")
    json.dump(stamped(man, __file__), open(path, "w"), indent=2)
    print(f"[preflight] {campaign}: sha={sha[:8]} clean={not dirty} code_hash={man['code_hash']} "
          f"seed={seed} threads={threads} cplex={man.get('cplex')} -> "
          f"{os.path.relpath(path, ROOT)}", flush=True)
    return man


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="manual")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--no-tenancy-check", action="store_true")
    A = ap.parse_args()
    preflight(A.campaign, seed=A.seed, threads=A.threads, allow_dirty=A.allow_dirty,
              require_single_tenant=not A.no_tenancy_check)
