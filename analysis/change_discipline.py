"""A commit that changes BEHAVIOUR must say so in its message. Enforced, not requested.

    python analysis/change_discipline.py            # check the staged diff (pre-commit uses this)
    python analysis/change_discipline.py --range A..B

THE PATTERN THIS EXISTS TO STOP, identified by the author on 2026-09-30 after eight tagged
variants in one day: "code variant trajectory becomes erratic by your silent change of
unrelated parameters."

Measured over those eight tags, THREE carried a behaviour change the title did not name:

  90ca524  "the uniform LB solver..."        also: --start-states default OFF -> ON
                                             also: valid_bound gained a start_states requirement
  9573cb4  "AB4 floor, width ladder, RT"     also: deciding budget wall -> labels
                                             also: a det_budget break added to cg_loop
                                             also: census made opt-in
                                             also: MIN_RUNG 20.0 s -> MIN_RUNG_LABELS 2000
  3f92c26  "all five verification points"    also: the candidate-scan truncation REMOVED

WHY IT MATTERS MORE THAN TIDINESS. Each variant is supposed to be a controlled step, so that a
difference in output is attributable to the one thing that moved. A variant that moves four
things and names one turns the trajectory into guesswork -- and on 2026-09-30 exactly that
produced three wrong attributions in a row: a 25x slowdown pinned on start-state pricing, a
"the Master changed" claim, and a cost-exponent scare. All three were withdrawn. None of them
would have been possible if each step had moved one thing.

MIN_RUNG is the clearest case and the reason NAME ALONE IS NOT ENOUGH: same name, same
position, same stated role, and the UNIT changed from seconds to labels and back across three
variants. A reader diffing constants sees three values of one parameter, not two different
parameters.

WHAT COUNTS AS BEHAVIOUR. Module-level constants, argparse defaults, and function-signature
defaults. These are the things that change what the code computes without changing its shape,
and they are exactly what a title like "add logging" hides. Comments, docstrings and pure
additions are not behaviour and are never flagged.

HOW TO SATISFY IT. Name each changed symbol in the commit message. That is the whole rule: the
check does not judge whether the change is wise, only whether the message admits it. A commit
that legitimately changes five constants passes by listing five constants.
"""
import argparse
import ast
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(*a):
    return subprocess.run(["git"] + list(a), cwd=ROOT, capture_output=True, text=True).stdout


def constants(src):
    """{name: repr} for module-level constants, argparse defaults and signature defaults."""
    out = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    try:
                        out["const:" + t.id] = ast.unparse(node.value)
                    except Exception:
                        out["const:" + t.id] = "<expr>"
    for node in ast.walk(tree):
        # function-signature defaults: a default IS behaviour for every caller that omits it
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            pos = args.posonlyargs + args.args
            for arg, dflt in zip(pos[len(pos) - len(args.defaults):], args.defaults):
                try:
                    out["default:%s(%s)" % (node.name, arg.arg)] = ast.unparse(dflt)
                except Exception:
                    pass
            for arg, dflt in zip(args.kwonlyargs, args.kw_defaults):
                if dflt is not None:
                    try:
                        out["default:%s(%s)" % (node.name, arg.arg)] = ast.unparse(dflt)
                    except Exception:
                        pass
        # argparse defaults
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            flag = None
            for a_ in node.args:
                if isinstance(a_, ast.Constant) and isinstance(a_.value, str) and a_.value.startswith("-"):
                    flag = a_.value
            for kw in node.keywords:
                if kw.arg in ("default", "action") and flag:
                    try:
                        out["cli:%s.%s" % (flag, kw.arg)] = ast.unparse(kw.value)
                    except Exception:
                        pass
    return out


def control_flow(src):
    """Every branch TEST and loop-exit in the file, as text, keyed by function and position.

    WHY THIS IS HERE AND CONSTANTS ARE NOT ENOUGH. The first version of this check looked only
    at constants and defaults. Audited against the three commits it exists to catch, it MISSED
    the worst one: 3f92c26 removed `and time.time() - t_chk > check_secs` from a candidate-scan
    test, changing which columns enter the master, and that is a branch condition, not a
    constant. It equally missed the `det_budget` break added to cg_loop in 9573cb4. A check
    that catches the easy half and misses the dangerous half is worse than none, because it
    licenses confidence.
    """
    out = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    fn = [None]

    class W(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            prev, fn[0] = fn[0], node.name
            self.generic_visit(node)
            fn[0] = prev
        visit_AsyncFunctionDef = visit_FunctionDef

        def _test(self, node, kind):
            try:
                out["%s:%s@%d:%s" % (kind, fn[0], node.lineno, kind)] = ast.unparse(node.test)
            except Exception:
                pass

        def visit_If(self, node):
            self._test(node, "if"); self.generic_visit(node)

        def visit_While(self, node):
            self._test(node, "while"); self.generic_visit(node)
    W().visit(tree)
    # a set of normalised test strings per function -- position-independent, so inserting a
    # line does not report every later test as changed
    norm = {}
    for k, v in out.items():
        f = k.split(":")[1].split("@")[0]
        norm.setdefault(f, set()).add(v)
    return norm


def changed(old_src, new_src):
    """Symbols whose VALUE moved. A symbol that only appeared or vanished is reported too."""
    a, b = constants(old_src), constants(new_src)
    moved = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            moved.append((k, a.get(k, "<absent>"), b.get(k, "<absent>")))
    ca, cb = control_flow(old_src), control_flow(new_src)
    for f in sorted(set(ca) | set(cb)):
        gone = (ca.get(f, set()) - cb.get(f, set()))
        new = (cb.get(f, set()) - ca.get(f, set()))
        for t in sorted(gone):
            moved.append(("branch:%s" % f, t, "<removed>"))
        for t in sorted(new):
            moved.append(("branch:%s" % f, "<added>", t))
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", default=None, help="A..B instead of the staged diff")
    ap.add_argument("--message", default=None, help="commit message file; default .git/COMMIT_EDITMSG")
    a = ap.parse_args()

    if a.range:
        base, head = a.range.split("..")
        files = [f for f in _git("diff", "--name-only", a.range).split() if f.endswith(".py")]
        get_old = lambda f: _git("show", "%s:%s" % (base, f))
        get_new = lambda f: _git("show", "%s:%s" % (head, f))
        msg = _git("log", "--format=%B", a.range)
    else:
        files = [f for f in _git("diff", "--cached", "--name-only").split() if f.endswith(".py")]
        get_old = lambda f: _git("show", "HEAD:%s" % f)
        get_new = lambda f: open(os.path.join(ROOT, f), encoding="utf-8").read() \
            if os.path.exists(os.path.join(ROOT, f)) else ""
        p = a.message or os.path.join(ROOT, ".git", "COMMIT_EDITMSG")
        msg = open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    undeclared, total, skipped_new = [], 0, 0
    for f in files:
        old = get_old(f)
        if not old.strip():
            skipped_new += 1        # newly added file: nothing silent about it
            continue
        for sym, before, after in changed(old, get_new(f)):
            total += 1
            bare = sym.split(":", 1)[1].split("(")[0].strip("-")
            name = re.split(r"[.(]", bare)[0]
            if name and name not in msg:
                undeclared.append((f, sym, before, after))

    print("change discipline: %d behaviour-affecting change(s) in %d modified file(s); %d new file(s) skipped"
          % (total, len(files) - skipped_new, skipped_new))
    if not undeclared:
        if total:
            print("  all declared in the message")
        return 0
    print("  REFUSED -- %d not named in the commit message:" % len(undeclared))
    for f, sym, before, after in undeclared:
        print("    %-34s %-30s %s -> %s" % (f, sym, before, after))
    print("\n  A commit that changes behaviour must say which behaviour. Name each symbol above")
    print("  in the message. The check does not judge the change, only that the message admits")
    print("  it -- see the module docstring for the three commits that made this necessary.")
    return 3


if __name__ == "__main__":
    sys.exit(main())
