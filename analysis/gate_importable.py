"""G24 -- every analysis module's imports must RESOLVE, and no module may do work at import time.

WHY IT EXISTS. On 2026-09-20 a bulk patch inserted `from analysis.stamp import stamped` into 33
modules that never put ROOT on sys.path. All of them parsed. `safe_edit` passed them.
`python -m compileall` reported success on every one. Each died on its import line -- including
queue_run.py, the queue's own runner. Compilation is not import.

WHY IT NO LONGER EXECUTES ANYTHING. The first version of this gate checked importability by
exec'ing each module in a subprocess, reasoning that `main()` stays behind its `__main__` guard.
That reasoning was wrong, and it was wrong expensively: `captl_ctrl_runner.py` does its work in a
module-level loop, so the gate LAUNCHED four 2400-second calibration solves. Two sweeps launched
two sets. `master_sequence.py`, `scale_screen.py` and a `step1_validbigm` run followed from the
same cause -- a whole unrequested pipeline, contending for the machine's four threads with a live
campaign, writing into runs/ and validation/.

A gate that can start a job is not a gate. This one reads only.

    CHECK 1  IMPORTS RESOLVE.  Each top-level import name is resolved with importlib.util
             .find_spec, under the sys.path the script would actually have: its own directory
             first, then ROOT. find_spec locates a module; it does not execute the module under
             test. This catches exactly the failure that happened -- a name that cannot be found.

    CHECK 2  NO WORK AT IMPORT TIME.  A module whose top level contains a loop, a bare call to
             run/Popen/main, or an `if` that is not the `__main__` guard does real work the
             moment it is imported. That makes it unsafe for this gate, for any tooling that
             imports it, and for a plain `python -c "import x"`. It is reported as a DEFECT of
             the module, which is what it is.

WHAT IT DELIBERATELY CANNOT CATCH. A NameError or a crash in a module's top-level code. Finding
those requires running them, and running them is the thing that caused the incident. Check 2 is
the answer to that: a module with nothing but imports and constants at its top level has nothing
left to crash.

    python analysis/gate_importable.py
"""
import argparse
import ast
import glob
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# No exemption list. An exemption list is how the last backlog accumulated.
RUNNERS = {"run", "Popen", "call", "check_call", "check_output", "system", "main",
           "optimize", "parse_args", "kill_tree", "sleep"}

# find_spec runs in a subprocess so a package's __init__ cannot pollute this process, and so a
# module that is missing cannot take the gate down with it.
RESOLVER = r"""
import importlib.util, json, os, sys
front, names = json.loads(sys.argv[1]), json.loads(sys.argv[2])
# python -c puts the CWD on sys.path, and the CWD here is ROOT. Leaving it in made the
# "does not insert ROOT" model indistinguishable from the "inserts ROOT" one, and the
# control for this check passed when it should have failed.
cwd = os.getcwd()
tail = []
for p in sys.path:
    if p in front or p in ("", "."):
        continue
    try:
        if os.path.abspath(p) == cwd:
            continue
    except Exception:
        pass
    tail.append(p)
sys.path[:] = front + tail
out = {}
for n in names:
    try:
        out[n] = importlib.util.find_spec(n) is not None
    except Exception as e:
        out[n] = "%s: %s" % (type(e).__name__, e)
print(json.dumps(out))
"""


def inserts_root(tree):
    """Does this module put ROOT on sys.path before its own imports run?

    The gate must model the path the script ACTUALLY has, not a convenient one. Run as
    `python analysis/x.py`, sys.path[0] is analysis/ and ROOT is absent unless the script
    inserts it. Assuming ROOT is present would clear a module that imports `analysis.stamp`
    without the bootstrap -- exactly the failure this gate exists to catch, waved through by
    the gate itself.

    Spelling-matching was tried and it failed twice. It missed `sys.path.insert(0, ".")` and
    reported 14 working modules as broken; corrected, it then missed `sys.path.insert(0, R)`,
    where R is a local name for ROOT, and reported 3 more. Every module here that touches
    sys.path does it for one reason: to reach ROOT. So the rule is PRESENCE, not spelling.

    Deliberately permissive in one direction: a module that touches sys.path for some other
    purpose and still cannot import is missed. Nothing in this repository does that, and the
    alternative -- a gate that cried wolf 17 times in a row -- is the one that gets ignored.
    """
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("insert", "append")
                and isinstance(n.func.value, ast.Attribute)
                and n.func.value.attr == "path"):
            return True
    # A module whose own usage line says `python -m analysis.x` is run as a package member,
    # and -m puts the working directory -- ROOT -- on sys.path. ablation.py is the case.
    doc = ast.get_docstring(tree) or ""
    return "-m analysis." in doc or "-m crossfeed." in doc


def guarded_imports(tree):
    """Imports inside a top-level try/except -- deliberately optional, not a defect."""
    names = set()
    for node in tree.body:
        if not isinstance(node, ast.Try):
            continue
        for n in ast.walk(node):
            if isinstance(n, ast.Import):
                for al in n.names:
                    names.add(al.name.split(".")[0] if "." not in al.name else al.name)
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                names.add(n.module)
    return names


def top_level_imports(tree):
    """Import names that resolve the moment the module is imported."""
    names = set()
    for node in tree.body:
        stack = [node]
        # a top-level try/except wrapping imports still runs at import time
        if isinstance(node, ast.Try):
            stack = list(node.body) + list(node.orelse) + list(node.finalbody)
            for h in node.handlers:
                stack += list(h.body)
        for n in stack:
            if isinstance(n, ast.Import):
                for a in n.names:
                    names.add(a.name.split(".")[0] if "." not in a.name else a.name)
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                names.add(n.module)
    return names


def work_at_import(tree):
    """Top-level statements that DO something when the module is imported."""
    found = []
    for n in tree.body:
        if isinstance(n, ast.If):
            t = n.test
            if isinstance(t, ast.Compare) and getattr(t.left, "id", "") == "__name__":
                continue
            found.append("if at line %d" % n.lineno)
        elif isinstance(n, (ast.For, ast.While)):
            found.append("%s loop at line %d" % (type(n).__name__.lower(), n.lineno))
        elif isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
            f = n.value.func
            nm = getattr(f, "attr", None) or getattr(f, "id", "")
            if nm in RUNNERS:
                found.append("%s() at line %d" % (nm, n.lineno))
    return found


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="analysis")
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(ROOT, a.dir, "*.py")))
    print("G24 -- imports must RESOLVE, and no module may do work at import time.")
    print("       This gate reads only. It never executes a module under test.")
    print()

    wanted, trees, unparseable = set(), {}, []
    for p in paths:
        try:
            t = ast.parse(io.open(p, encoding="utf-8").read(), filename=p)
        except SyntaxError as e:
            unparseable.append((p, "line %s: %s" % (e.lineno, e.msg)))
            continue
        trees[p] = t
        wanted |= top_level_imports(t)

    # Two path models, because a module only has ROOT if it puts it there itself.
    def resolve_under(paths_json):
        r = subprocess.run([sys.executable, "-c", RESOLVER, paths_json,
                            json.dumps(sorted(wanted))],
                           capture_output=True, text=True, cwd=ROOT)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}

    adir = os.path.join(ROOT, a.dir)
    with_root = resolve_under(json.dumps([adir, ROOT]))
    without_root = resolve_under(json.dumps([adir]))

    unresolved, doing_work = [], []
    for p, t in trees.items():
        rel = os.path.relpath(p, ROOT)
        resolved = with_root if inserts_root(t) else without_root
        optional = guarded_imports(t)
        missing = sorted(n for n in top_level_imports(t)
                         if resolved.get(n) is not True and n not in optional)
        if missing:
            unresolved.append((rel, missing + ([] if inserts_root(t)
                                               else ["(module does not put ROOT on sys.path)"])))
        w = work_at_import(t)
        if w:
            doing_work.append((rel, w))

    for p, why in unparseable:
        print("   UNPARSEABLE  %-44s %s" % (os.path.relpath(p, ROOT), why))
    for rel, missing in sorted(unresolved):
        print("   UNRESOLVED   %-44s %s" % (rel, ", ".join(missing)[:70]))
    print()
    print("   modules %d   unparseable %d   imports unresolved %d"
          % (len(paths), len(unparseable), len(unresolved)))
    print()
    print("   WORK AT IMPORT TIME -- these run the moment they are imported, so importing them")
    print("   is not a safe check. It is what launched four calibration solves on 2026-09-20.")
    for rel, w in sorted(doing_work):
        print("      %-44s %s" % (rel, "; ".join(w)[:70]))
    print()
    print("   modules doing work at import time: %d of %d" % (len(doing_work), len(paths)))

    fails = len(unparseable) + len(unresolved)
    if fails:
        print()
        print("   A module whose imports do not resolve cannot be run at all. No tolerated case.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
