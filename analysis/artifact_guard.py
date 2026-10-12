"""THE GUILLOTINE. An artifact without provenance and a reproducible runtime cannot be written.

Not "is reported". Not "is caught by a gate someone remembers to run". Cannot be written: the
file is deleted and the process dies with a traceback pointing at the line that tried.

    python analysis/artifact_guard.py --install     # arm it for every python process
    python analysis/artifact_guard.py --uninstall
    python analysis/artifact_guard.py --status

WHY THIS AND NOT THE OTHER THREE DESIGNS. Audited 2026-09-29, after the author observed --
correctly -- that provenance and runtime tracking had failed repeatedly, and that the two layers
built that morning were still not a guillotine.

  A. stamp.py refuses          Guards only writers that call stamped(). An AST sweep found 40
     (built, kept)             modules that json.dump something else. A rule enforced where
                               writers opt in is enforced nowhere. NECESSARY, NOT SUFFICIENT.

  B. artifact_gate.py sweeps   Post-hoc. It has to be RUN. The seven deleted artifacts would
     (built, kept)             have passed six hours of compute and then failed a sweep nobody
                               was obliged to run. A smoke alarm with a manual test button.

  C. pre-commit hook           Catches what reaches a commit, which is hours too late and misses
     (built, kept as backstop) everything never committed. Cheap, so it is installed anyway.

  D. INTERCEPT THE WRITE       <- this file. Wraps open/os.replace/os.rename at the interpreter,
                               below every library and every writer. A module that never heard
                               of stamp.py is stopped at the same place as one that did.

D is installed as a `.pth` in site-packages, which CPython executes at EVERY interpreter start,
whatever the launch style -- `python analysis/x.py`, `python -c`, a subprocess, a notebook. A
`sitecustomize.py` in the repo would not: sys.path[0] is the SCRIPT's directory, not the working
directory, so `python solver/x.py` would never see one placed in analysis/.

IT IS INERT OUTSIDE THIS REPOSITORY. The hooks compare against a hardcoded ROOT and return the
real function's result untouched for every other path, so installing it cannot affect unrelated
work on this machine. Uninstalling is deleting one file.

WHAT IT STILL DOES NOT CATCH, stated because a guillotine that is sold as total is worse than
one whose gaps are known:
  * writes from outside python -- a shell redirect, `git checkout`, a text editor. Design C is
    the backstop for those, and `artifact_gate.py` finds them on the next sweep.
  * a writer that deliberately unhooks the guard. Nothing defends against that, and nothing in
    this project needs to.
  * artifacts outside `runs/`. Deliberate: `paper/`, `validation/` and `logs/` are prose and
    spool, not results.
"""
import argparse
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARDED = os.path.join(ROOT, "runs") + os.sep

# Captured at import, before arm() replaces builtins.open and io.open. The guard must
# read files without going through itself.
_REAL_IO_OPEN = io.open
PTH_NAME = "zzz_artifact_guard.pth"
_FLAG = "_2e_mvrp_artifact_guard_armed"
_CREATED = set()   # every guarded path this process opened for writing


def armed():
    """Is the guillotine up in THIS interpreter? The flag lives on builtins, not on this
    module: `import artifact_guard` and `import analysis.artifact_guard` are two module objects
    with two module globals, and a per-module flag would let require_armed() report False while
    the hooks were in fact installed -- or worse, True when they were not."""
    import builtins
    return bool(getattr(builtins, _FLAG, False))


class ArtifactRefused(RuntimeError):
    """A write under runs/ carried no provenance, or no reproducible runtime."""


def _guarded(path):
    """True for a .json under this repository's runs/ tree. Everything else is none of our
    business -- that is what makes installing this machine-wide safe."""
    try:
        p = os.path.abspath(str(path))
    except Exception:
        return False
    return p.lower().endswith(".json") and p.startswith(GUARDED)


def _verdict(raw):
    """(codes, detail) for the bytes about to become an artifact. Empty codes means it may live.

    Delegates to artifact_gate.violations so there is ONE definition of the rule. Imported
    lazily: this module is executed at interpreter startup, before anything is importable.
    """
    try:
        d = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except Exception as e:
        return ["P1"], "not readable as JSON (%s)" % type(e).__name__
    if not isinstance(d, (dict, list)):
        return ["P1"], "not an object"
    if isinstance(d, list):
        return [], ""                      # a bare list carries no result contract
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    from artifact_gate import violations, NAMES
    v = violations(d)
    return v, "; ".join("%s (%s)" % (c, NAMES[c]) for c in v)


# Paths a writer has DELIBERATELY asked to replace across code releases. Populated only by
# stamp.stamped(path=..., supersede=True), consumed once. Not an env var and not a flag file:
# the request has to be written into the calling code, where it can be read in a diff.
_ALLOW_SUPERSEDE = set()


def allow_supersede(path):
    """Permit exactly one cross-release replacement of `path`. See stamp.stamped(supersede=)."""
    try:
        _ALLOW_SUPERSEDE.add(os.path.abspath(str(path)))
    except Exception:
        pass


def _assert_release_match(path, how):
    """REFUSE, BEFORE THE FILE IS TRUNCATED, to replace a result a different code release made.

    THE RULE, at the level the author asked for: not a convention a writer opts into by passing
    `path=`, but a property of writing to `runs/**.json` at all. Every writer inherits it,
    including the ones that never imported `stamp`.

    WHY IT IS HERE AND NOT IN `stamped()`. `stamped()` only sees what a caller hands it, and
    tonight's accident came from a caller that handed it nothing: `tep_cg_bound.py R202
    --size 30`, run as a one-line diagnostic, overwrote the 2026-09-25 corpus artifact --
    code_hash e24bcc52 replaced by 26b414c6, same path, no warning. Recoverable only because
    that file was tracked; the 65 tep_cg_banked_* artifacts are not (d621).

    WHY IT IS BEFORE `self.real(...)`. Opening with "w" truncates. A check after the open is a
    postmortem on a file that no longer exists -- the same mistake this project already recorded
    as "the audit was a postmortem where it should have been a precondition".

    THE TEST IS `_provenance.sources`, the writer-named files that DETERMINED the value, each
    re-hashed from disk now. Narrower than `code_in_play` on purpose: `code_in_play` covers every
    repository module imported into the process, so editing something unrelated would refuse an
    honest re-run. Wider than `git_sha`, which cannot reconstruct a dirty tree -- the whole
    banked corpus carries `git_dirty: true`. A legacy artifact with no `sources` cannot be
    judged and is allowed through; that is the debt, not a hole in the rule.
    """
    p = os.path.abspath(str(path))
    if p in _ALLOW_SUPERSEDE:
        _ALLOW_SUPERSEDE.discard(p)
        return
    if not os.path.exists(p):
        return
    try:
        old = json.loads(_REAL_IO_OPEN(p, "rb").read().decode("utf-8"))
    except Exception:
        return
    if isinstance(old, list):
        old = old[0] if old and isinstance(old[0], dict) else {}
    src = ((old or {}).get("_provenance") or {}).get("sources")
    if not isinstance(src, dict) or not src:
        return
    drift = []
    for rel, sha in src.items():
        f = os.path.join(ROOT, str(rel))
        try:
            cur = hashlib.sha256(_REAL_IO_OPEN(f, "rb").read()).hexdigest()[:16]
        except Exception:
            continue                       # source gone: cannot judge, do not block
        if sha and cur != sha:
            drift.append((rel, sha, cur))
    if not drift:
        return
    rel = os.path.relpath(p, ROOT).replace("\\", "/")
    raise ArtifactRefused(
        "ARTIFACT REFUSED -- CROSS-RELEASE OVERWRITE: %s\n"
        "  was produced by code that has since CHANGED, and this write would replace it:\n%s\n"
        "  written by: %s\n"
        "  the existing file is UNTOUCHED.\n"
        "A result is evidence for the code that produced it, and two releases must not share a\n"
        "filename. Write beside it -- %s -- or, if you mean to destroy the older result and can\n"
        "say why, call stamped(payload, ..., path=<path>, supersede=True)."
        % (rel,
           "\n".join("    %-44s %s -> %s" % (r, a, b) for r, a, b in drift[:6]),
           how, os.path.basename(_sidecar(p))))


def _sidecar(path):
    base, ext = os.path.splitext(path)
    return "%s__alt%s" % (base, ext)


def _refuse(path, codes, detail, how):
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    try:
        if os.path.exists(path):
            os.remove(path)
            gone = "the partial file has been DELETED"
        else:
            gone = "nothing was written"
    except Exception:
        gone = "the partial file could NOT be removed -- delete it by hand"
    raise ArtifactRefused(
        "ARTIFACT REFUSED: %s\n"
        "  violates: %s\n"
        "  written by: %s\n"
        "  %s.\n"
        "An artifact carries full provenance AND the runtime it actually consumed -- not the cap\n"
        "it was allowed -- or it is not written (CLAUDE.md section 1, adopted 2026-09-29).\n"
        "Wrap the payload: stamped(payload, __file__, det=<Gurobi Work units>, wall=<seconds>).\n"
        "There is no override." % (rel, detail, how, gone))


class _Sentinel(object):
    """Wraps a file object opened for writing under runs/. Validates at close, and if the
    content does not pass, deletes the file and raises. Validating at close rather than
    buffering in memory keeps a 200 MB artifact from doubling peak RSS -- which matters here,
    where the label cap is already bounded by RAM."""

    def __init__(self, fh, path, how):
        object.__setattr__(self, "_fh", fh)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_how", how)

    def __getattr__(self, k):
        return getattr(object.__getattribute__(self, "_fh"), k)

    def __setattr__(self, k, v):
        setattr(object.__getattribute__(self, "_fh"), k, v)

    def __iter__(self):
        return iter(object.__getattribute__(self, "_fh"))

    def __enter__(self):
        object.__getattribute__(self, "_fh").__enter__()
        return self

    def __exit__(self, *a):
        r = object.__getattribute__(self, "_fh").__exit__(*a)
        self._check(bool(a and a[0]))
        return r

    def close(self):
        object.__getattribute__(self, "_fh").close()
        self._check(False)

    def __del__(self):
        """The common idiom is `json.dump(payload, io.open(path, "w"))`, which never calls
        close() at all -- the handle is dropped and CPython's refcount closes it during garbage
        collection. Without this, the guillotine would only fire in the exit sweep, seconds or
        hours later, and the author asked for immediately.

        An exception raised in __del__ is swallowed by the interpreter, so this cannot raise and
        be believed. It kills the process instead: the artifact is deleted, the reason goes to
        stderr, and os._exit(3) makes certain nothing downstream consumes what was refused. That
        is the brutal half of the design, and it is deliberate -- a batch that writes one
        unreproducible artifact should stop, not carry on producing thirty more.
        """
        try:
            object.__getattribute__(self, "_fh").close()
        except Exception:
            pass
        try:
            self._check(False)
        except ArtifactRefused as e:
            sys.stderr.write(os.linesep + str(e) + os.linesep)
            sys.stderr.flush()
            os._exit(3)

    def _check(self, already_failing):
        path = object.__getattribute__(self, "_path")
        if already_failing or not os.path.exists(path):
            return                          # an exception is already unwinding; do not mask it
        try:
            raw = io.open(path, "rb").read()
        except Exception:
            return
        if not raw.strip():
            return                          # an empty file is not yet an artifact
        codes, detail = _verdict(raw)
        if codes:
            _refuse(path, codes, detail, object.__getattribute__(self, "_how"))


def require_armed(who="this run"):
    """Refuse to proceed unless the guillotine is up. THIS is the "always" half.

    A guard that can be absent is a guard that will be absent on the night it mattered. Every
    writer reaches this through `analysis/stamp.py`, which calls it at import, so a batch
    launched with the .pth removed dies in the first second instead of six hours later with an
    artifact nobody can reproduce.
    """
    if armed():
        return True
    raise ArtifactRefused(
        "REFUSING TO START: the artifact guillotine is not armed, so %s could write a result "
        "with no provenance and no reproducible runtime.\n"
        "  arm it:  python analysis/artifact_guard.py --install\n"
        "  check:   python analysis/artifact_guard.py --status\n"
        "It installs a .pth that every python process on this interpreter executes at startup, "
        "and it is inert outside %s. There is no override." % (who, ROOT))


def _sweep_on_exit():
    """Anything created under runs/ by this process and never validated -- a handle left open,
    a process that died mid-write -- is checked here, at the last moment we still control."""
    for path in sorted(_CREATED):
        try:
            if not os.path.exists(path):
                continue
            raw = io.open(path, "rb").read()
            if not raw.strip():
                continue
            codes, detail = _verdict(raw)
            if codes:
                sys.stderr.write(
                    "\nARTIFACT REFUSED AT EXIT: %s\n  violates: %s\n  DELETED. A handle was "
                    "left open or the writer died mid-write.\n"
                    % (os.path.relpath(path, ROOT).replace("\\", "/"), detail))
                os.remove(path)
        except Exception:
            pass


def arm():
    """Wrap open / io.open / os.replace / os.rename. Idempotent."""
    import atexit
    import builtins
    if armed():
        return False
    real_open, real_io_open = builtins.open, io.open
    real_replace, real_rename = os.replace, os.rename

    class _Opener(object):
        """A CALLABLE OBJECT, deliberately not a function.

        `io.open` is a builtin, and builtins do not implement the descriptor protocol. A plain
        Python function does. `pathlib._NormalAccessor` holds `open = io.open` as a CLASS
        attribute and calls it as `self._accessor.open(self, mode, ...)`; replacing it with a
        function makes that access return a BOUND METHOD, so the accessor instance is inserted
        as the first argument and every argument shifts by one. Every `Path.read_text()` in the
        process then dies with "open() argument 'mode' must be str, not WindowsPath".

        An instance of a class that defines only `__call__` is not a descriptor, so attribute
        access returns it unbound and the call signature is preserved. Found 2026-09-29 by the
        LB solver's first smoke test, minutes after the guard was armed: sklearn -> scipy ->
        numpy.testing reads `direct_url.json` through pathlib during import.
        """

        def __init__(self, real, label):
            self.real, self.label = real, label

        def __call__(self, file, mode="r", *a, **kw):
            m = str(mode)
            if ("w" in m or "x" in m) and _guarded(file):
                _assert_release_match(file, self.label)   # BEFORE the open truncates it
            fh = self.real(file, mode, *a, **kw)
            if any(c in str(mode) for c in "wxa+") and _guarded(file):
                p = os.path.abspath(str(file))
                _CREATED.add(p)             # so the exit sweep sees a handle never closed
                return _Sentinel(fh, p, self.label)
            return fh

    def _wrap_open(real, label):
        return _Opener(real, label)

    class _Mover(object):
        """Also a callable object, for the same reason as _Opener: `pathlib._NormalAccessor`
        holds `rename = os.rename` and `replace = os.replace` as class attributes."""

        def __init__(self, real, label):
            self.real, self.label = real, label

        def __call__(self, src, dst, *a, **kw):
            if _guarded(dst):
                _assert_release_match(dst, self.label)
                try:
                    raw = real_io_open(src, "rb").read()
                except Exception:
                    raw = None
                if raw and raw.strip():
                    codes, detail = _verdict(raw)
                    if codes:
                        try:
                            os.remove(src)
                        except Exception:
                            pass
                        _refuse(os.path.abspath(str(dst)), codes, detail,
                                "%s from %s" % (self.label, os.path.basename(str(src))))
            return self.real(src, dst, *a, **kw)

    def _wrap_move(real, label):
        return _Mover(real, label)

    builtins.open = _wrap_open(real_open, "builtins.open")
    io.open = _wrap_open(real_io_open, "io.open")
    os.replace = _wrap_move(real_replace, "os.replace")
    os.rename = _wrap_move(real_rename, "os.rename")
    atexit.register(_sweep_on_exit)
    setattr(builtins, _FLAG, True)
    return True


def _pth_path():
    import site
    for d in site.getsitepackages():
        if os.path.isdir(d) and d.endswith("site-packages"):
            return os.path.join(d, PTH_NAME)
    return os.path.join(site.getsitepackages()[0], PTH_NAME)


def _pth_line():
    """A .pth line must be ONE line. Everything after `import ` is exec'd at startup. It is
    wrapped in try/except so a broken repository can never make python itself unusable."""
    a = os.path.join(ROOT, "analysis").replace("\\", "\\\\")
    return ("import sys, os; exec(\"try:\\n import sys, os\\n sys.path.insert(0, r'%s')\\n"
            " import artifact_guard as _g\\n _g.arm()\\nexcept Exception as _e:\\n"
            " pass\\n\")\n" % a.replace("\\\\", "\\\\"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    p = _pth_path()
    if a.install:
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(_pth_line())
        print("armed: %s" % p)
        print("  every python process on this interpreter now refuses an artifact under")
        print("  %s that lacks provenance or a deterministic runtime." % GUARDED)
        return 0
    if a.uninstall:
        if os.path.exists(p):
            os.remove(p); print("disarmed: removed %s" % p)
        else:
            print("was not armed (%s absent)" % p)
        return 0
    print("guard .pth : %s" % ("PRESENT " + p if os.path.exists(p) else "ABSENT (" + p + ")"))
    print("armed here : %s" % armed())
    print("guarding   : %s*.json" % GUARDED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
