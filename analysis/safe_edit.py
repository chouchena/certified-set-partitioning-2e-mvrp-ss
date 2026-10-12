"""Apply a source transform to many files WITHOUT the possibility of writing a broken one.

WHY THIS EXISTS. On 2026-09-20 a two-line regex was applied to every writer in analysis/ to wire
provenance stamping. It reported "wired (26)". It had in fact destroyed the dict literal in all 26
files -- the opening brace was consumed into the call and the closing brace replaced -- and every
one of them failed to import. The queue scripts that invoke them were live at the time. Nothing
between the transform and the disk noticed, because nothing looked.

THE RULE THIS ENFORCES. A transform that cannot produce parseable Python never reaches disk, and a
batch is ALL-OR-NOTHING: if one file fails, none are written. A partially patched tree is worse
than an unpatched one, because the failure is then spread across files nobody is looking at.

    from analysis.safe_edit import rewrite_many
    rewrite_many(paths, fn)          # fn(src, path) -> src, or None to skip

Three checks, in this order, before anything is written:
  1. every output parses (ast.parse)
  2. every output differs from its input (a no-op transform is reported, not silently counted)
  3. the whole batch succeeded

DELIBERATELY NOT CHECKED: that the transform is semantically right. ast.parse catches the class of
failure that actually happened; it cannot catch a patch that parses and means the wrong thing.
That is what the caller's own verification is for -- see wire_stamps.py, which re-reads each
patched file and asserts the wrapper is present on every writer it claimed to wire.
"""
import ast
import io
import os


class PatchRefused(Exception):
    pass


def rewrite_many(paths, fn, root=None, verbose=True):
    """Transform every path with fn. Write nothing unless ALL outputs parse.

    Returns (changed, skipped). Raises PatchRefused if any output is not parseable Python,
    naming the file and the syntax error, having written nothing.
    """
    staged, skipped, broken = [], [], []
    for p in paths:
        src = io.open(p, encoding="utf-8").read()
        try:
            out = fn(src, p)
        except Exception as exc:                       # a transform that throws is a refusal too
            broken.append((p, "transform raised: %s" % exc))
            continue
        if out is None or out == src:
            skipped.append(p)
            continue
        try:
            ast.parse(out, filename=p)
        except SyntaxError as exc:
            broken.append((p, "line %s: %s" % (exc.lineno, exc.msg)))
            continue
        staged.append((p, out))

    if broken:
        if verbose:
            print("PATCH REFUSED -- nothing written. %d file(s) would not parse:" % len(broken))
            for p, why in broken:
                print("   %-52s %s" % (os.path.relpath(p, root or os.getcwd()), why))
            print("   %d file(s) were ready and have been discarded with them: a half-patched"
                  % len(staged))
            print("   tree hides the failure across files nobody is looking at.")
        raise PatchRefused("%d file(s) would not parse" % len(broken))

    for p, out in staged:
        io.open(p, "w", encoding="utf-8", newline="\n").write(out)
    if verbose:
        print("patched %d file(s), %d unchanged, 0 broken" % (len(staged), len(skipped)))
    return [p for p, _ in staged], skipped


def parses(path):
    try:
        ast.parse(io.open(path, encoding="utf-8").read(), filename=path)
        return True
    except SyntaxError:
        return False
