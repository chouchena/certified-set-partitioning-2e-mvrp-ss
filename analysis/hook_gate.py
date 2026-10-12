"""hook_gate.py -- PreToolUse hook body. Reads the hook JSON on stdin; if the
Bash/PowerShell command is a SOLVER LAUNCH lacking a fresh preflight token, DENIES it
(so a run cannot start without passing analysis.preflight -> flaws A/D/E). Any
non-solver command is allowed. FAIL-OPEN on every error path -- a hook bug must never
lock the operator out of ordinary commands.
"""
import sys, json, os, re, hashlib, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKDIR = os.path.join(ROOT, "runs", "audit_tokens")
SOLVER_KW = re.compile(          # substring (no \b: keywords are embedded, e.g. phase5_lb_broad)
    r"(block_a|lbbd|easy_reduction|lb_portfolio|joint_model|dual_bound|portfolio|"
    r"fixopt|_lb_worker|phase\d|overnight_|discriminating_|bench_primal|multikick|"
    r"subproblem_bounded|lagrangian)", re.I)
FRESH_S = 3600


def _target_of(argtail: str):
    """The script path or -m module a python invocation actually RUNS -- not strings embedded in
    later args. Skips interpreter flags (-O,-u,-W...); returns None for `-c` inline code."""
    toks = argtail.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "-c":
            return None                      # inline code, not a harness launch
        if t == "-m":
            return toks[i + 1] if i + 1 < len(toks) else None
        if t.startswith("-"):
            i += 1; continue                 # interpreter flag
        return t                             # first non-flag token = the script path
    return None


def _is_solver_launch(cmd: str) -> bool:
    """True ONLY if a pipeline stage runs python on a solver HARNESS -- matched on the TARGET
    script/module token, not on strings embedded in args. So a MENTION (cat/grep/echo of a
    harness name) and, critically, `python -m analysis.preflight --cmd "python solver/lbbd.py"`
    (the GATE itself, naming a harness in an arg) are NOT launches -- otherwise preflight could
    never authorize a solver run (chicken-and-egg). Exempts -c inline and analysis.* tooling."""
    for stage in re.split(r"&&|\|\||\||;", cmd):
        s = stage.strip().lstrip("(").strip()
        m = re.match(r'(?:\S*[/\\])?"?python[\w.]*"?\s+(.+)', s, re.I)
        if not m:
            continue
        tgt = _target_of(m.group(1))
        if tgt and SOLVER_KW.search(tgt):
            return True
    return False


def _norm(c): return re.sub(r"\s+", " ", (c or "").strip())
def _h(c): return hashlib.sha256(_norm(c).encode()).hexdigest()[:16]


def _allow(): sys.exit(0)


def _deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        _allow()
    cmd = ((data.get("tool_input") or {}).get("command")) or ""
    if not cmd or not _is_solver_launch(cmd):
        _allow()                       # not a solver launch
    try:
        now = time.time()
        for fn in os.listdir(TOKDIR):
            if not fn.endswith(".json"):
                continue
            fp = os.path.join(TOKDIR, fn)
            if now - os.path.getmtime(fp) > FRESH_S:
                continue
            tok = json.load(open(fp, encoding="utf-8"))
            tc = tok.get("cmd", "")
            if tc and (tc in _norm(cmd) or _h(cmd) == tok.get("hash")):
                _allow()               # a fresh token covers this launch
    except Exception:
        _allow()                       # fail-open on any token-check error
    _deny("SOLVER LAUNCH BLOCKED (R-GATE): no fresh preflight token. Run "
          "`python -m analysis.preflight --cmd \"<command>\" --cells <c> --size <n> "
          "--adversary-id <hostile-audit id>` first. Enforces flaws A (result-on-disk), "
          "D (logging), E (audit-before-launch).")


if __name__ == "__main__":
    main()
