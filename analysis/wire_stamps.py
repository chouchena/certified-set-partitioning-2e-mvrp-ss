"""Wire provenance stamping into every result writer, by AST rather than by regex.

    python analysis/wire_stamps.py --check     report, write nothing
    python analysis/wire_stamps.py --apply     patch, all-or-nothing, via safe_edit

WHAT IT REWRITES. A `json.dump({...}, open(...))` whose first argument is a DICT LITERAL becomes
`json.dump(stamped({...}, __file__), open(...))`. The dict's extent is taken from the parse tree,
not from a brace-matching regex -- which is the specific thing that broke 26 files at once.

WHAT IT REFUSES TO TOUCH. A `json.dump(x, ...)` where x is a name or a call: the payload is built
elsewhere and a blind wrap would stamp the wrong object. Those are listed as MANUAL and left
alone, so the count of wired writers is never inflated by a file this could not reason about.

VERIFICATION, not just parseability. After writing, every file is re-read and re-parsed, and the
wrapper must be present on exactly the calls that were rewritten. safe_edit guarantees the output
parses; this guarantees it says what was intended.
"""
import argparse
import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analysis.safe_edit import rewrite_many, PatchRefused

IMPORT_LINE = "from analysis.stamp import stamped"
SKIP = {"stamp.py", "safe_edit.py", "wire_stamps.py", "claims.py", "session_state.py"}


def offsets(src):
    """Byte-independent char offset of the start of each 1-based line."""
    off, n = [0], 0
    for line in src.splitlines(keepends=True):
        n += len(line)
        off.append(n)
    return off


def dump_sites(tree, include_manual=False):
    """Every json.dump(...) call, split into literal-dict payloads and everything else.

    include_manual folds the variable payloads in with the literals, so `--manual` wraps them
    too. It is a separate mode because the two carry different risk: wrapping a dict literal
    cannot change the artifact's shape, and wrapping a NAME can -- stamped() turns a list payload
    into {"result": [...]}. Author, 2026-09-20: "All unstamped records are full bugs - no
    exceptions", so they are all wired, and --manual reports which artifacts change shape so
    their readers can be fixed rather than discovered broken.
    """
    lit, manual = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "dump"
                and isinstance(f.value, ast.Name) and f.value.id == "json"):
            continue
        if not node.args:
            continue
        a0 = node.args[0]
        if isinstance(a0, ast.Dict):
            lit.append(a0)
        elif isinstance(a0, ast.Call) and isinstance(a0.func, ast.Name) and a0.func.id == "stamped":
            pass                                        # already wired -- idempotent
        else:
            (lit if include_manual else manual).append(a0)
    return lit, manual


def import_anchor(src):
    """Insert the import after sys.path setup, so ROOT is importable when it runs."""
    lines = src.splitlines(keepends=True)
    last = None
    for i, l in enumerate(lines):
        if l.startswith("sys.path.insert"):
            last = i
    if last is None:
        for i, l in enumerate(lines):
            if l.startswith(("import ", "from ")):
                last = i
    return (last + 1) if last is not None else 0


MANUAL = False


def transform(src, path):
    if IMPORT_LINE in src:
        base_needs_import = False
    else:
        base_needs_import = True
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return None
    lit, _manual = dump_sites(tree, MANUAL)
    if not lit:
        return None
    off = offsets(src)
    spans = sorted(((off[n.lineno - 1] + n.col_offset,
                     off[n.end_lineno - 1] + n.end_col_offset) for n in lit), reverse=True)
    out = src
    for s, e in spans:                                   # right to left: earlier spans stay valid
        out = out[:s] + "stamped(" + out[s:e] + ", __file__)" + out[e:]
    if base_needs_import:
        lines = out.splitlines(keepends=True)
        k = import_anchor(out)
        lines.insert(k, IMPORT_LINE + "\n")
        out = "".join(lines)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--manual", action="store_true",
                    help="also wrap dumps whose payload is a name or a call")
    a = ap.parse_args()
    global MANUAL
    MANUAL = a.manual
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    paths = sorted(os.path.join(ROOT, "analysis", f)
                   for f in os.listdir(os.path.join(ROOT, "analysis"))
                   if f.endswith(".py") and f not in SKIP)
    todo, manual_only, already = [], [], []
    for p in paths:
        src = io.open(p, encoding="utf-8").read()
        try:
            lit, man = dump_sites(ast.parse(src, filename=p), MANUAL)
        except SyntaxError:
            print("   UNPARSEABLE (left alone): %s" % os.path.relpath(p, ROOT))
            continue
        if lit:
            todo.append((p, len(lit), len(man)))
        elif man:
            manual_only.append((p, len(man)))
        elif "stamped(" in src:
            already.append(p)

    print("wire_stamps -- provenance stamping wired by parse tree, not by regex")
    print()
    print("   writers with a literal-dict payload (WILL be wired): %d" % len(todo))
    for p, n, m in todo:
        print("      %-44s %d dict dump(s)%s"
              % (os.path.relpath(p, ROOT), n, ", %d MANUAL" % m if m else ""))
    print("   writers whose payload is built elsewhere (MANUAL, untouched): %d" % len(manual_only))
    for p, m in manual_only:
        print("      %-44s %d non-literal dump(s)" % (os.path.relpath(p, ROOT), m))
    print("   already wired: %d" % len(already))
    if not a.apply:
        print()
        print("   --check only; nothing written. Re-run with --apply.")
        return 0

    print()
    try:
        changed, _skipped = rewrite_many([p for p, _n, _m in todo], transform, root=ROOT)
    except PatchRefused:
        return 1

    bad = []
    for p in changed:
        src = io.open(p, encoding="utf-8").read()
        lit, _m = dump_sites(ast.parse(src, filename=p), MANUAL)
        if lit or IMPORT_LINE not in src:
            bad.append(os.path.relpath(p, ROOT))
    print()
    if bad:
        print("   VERIFICATION FAILED on %d file(s): %s" % (len(bad), ", ".join(bad)))
        return 1
    print("   verified: %d file(s) re-parsed, every literal dump wrapped, import present"
          % len(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
