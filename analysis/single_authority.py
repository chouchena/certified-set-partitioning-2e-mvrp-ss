"""One lookup, one authority. Fails the commit when a module writes a second copy of one. (d591)

WHY. Twice in one morning I re-implemented a lookup that already existed, and both copies silently
disagreed with the original:

  * the triaged predicate, copied into quarantine_watch.py, called all 67 quarantine rows untriaged
    when every one of them carries the decision id that disposes of it;
  * the banked best-known lookup, copied into tep_bk_in_column_space.py, returned a WORSE solution
    on 2 of 22 live cells and -- the part that mattered -- never checked `_verified`, so it could
    have seeded the master IP with an unverified solution's trips.

Neither was a hard bug to see once looked at. The problem is that nothing looked. This does.

A SECOND COPY IS THE DEFECT, not the disagreement. The copy is written correct and drifts later,
so reviewing the copy when it is written proves nothing. The only durable check is at the import:
a module that needs the banked best-known imports `best_known`, and a module that needs the
triaged rule imports `quarantine_guard`.

RATCHET, NOT BIG BANG. Six modules re-derive the best-known across stage directories today. All
six were checked and NONE feeds a number in `paper/numbers.tex` or the reproduction index, so the
exposure is latent rather than realised, and rewriting them now would be a large change landing on
top of a running grid. They are listed in KNOWN below with that finding recorded. The gate fails on
any module NOT in that list, so the class cannot grow while the list is worked down. Removing a
name from KNOWN is the fix; adding one requires saying why here.

KNOWN BLIND SPOT, recorded because it has already bitten once. A module that IMPORTS the
authority and ALSO hand-rolls part of the same lookup passes this gate. baseline_audit.py did
exactly that -- it imported best_known for best_solution and then wrote its own bound glob, whose
narrower n100 pattern reported a false "dual 108/135" to the author when the true figure is
135/135.

Three attempts were made to close it by requiring "imports AND does not re-derive", and all three
produced noise: the first flagged 23 files for reading a `proven` field, the second flagged six
including this file twice (its own rule table contains every string it searches for) and both
correct callers of is_untriaged, because "is_untriaged" contains "triaged"; the third flagged 26
by matching any postpass path construction. A gate that fails on correct delegation stops being
read, which is the failure it exists to prevent. The narrow, mutation-tested gate is kept and the
hole is written down instead. Closing it needs a parse-tree check for a min/best over stages, not
a regex. (d598)

    python analysis/single_authority.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AN = os.path.join(ROOT, "analysis")

# (authority module, what it owns, files exempt because they ARE the authority,
#  a signal that the caller touches this data, a signal that it re-derives rather than asks)
RULES = [
    dict(authority="best_known",
         owns="the banked best-known incumbent and bound across postpass stages",
         exempt={"best_known.py"},
         touches=re.compile(r"ownwater_"),
         rederives=re.compile(r"postpass[\"'/, ]*\*|STAGES|\"ceil\",\s*\"refine\"|refine.*alns.*selchain")),
    dict(authority="quarantine_guard",
         owns="whether a quarantine row is triaged",
         exempt={"quarantine_guard.py"},
         touches=re.compile(r"runs/invalid|INDEX\.md"),
         rederives=re.compile(r"triaged")),
    # ADDED 2026-09-28, after bound_source.tep_bound was found blind on 85 of 135 cells. It
    # built ONE path, tep_cg_bound_<cell>[_n<size>].json, while the real artifacts carry _ip,
    # _d20, _d10 and _d5 suffixes -- so it saw nothing whatsoever at n50 and n100. Its readers
    # (release_gate, free_falsifiers, tep_n100_family_table) under-reported the dual leg on two
    # entire sizes. baseline_audit had the SAME defect earlier the same day, reporting "dual
    # 108/135" against a true 135/135, and fixing that one site without sweeping is why this
    # one survived.
    #
    # THE SIGNAL IS A RE-DERIVED DECISION, not a word -- the discipline the removed third rule
    # failed. Building a tep_cg_bound path is not by itself an offence: plenty of modules
    # legitimately open one named variant (_ip_primal, _intcars) they wrote themselves. The
    # offence is building the path AND reading a bound value out of it, which is precisely
    # "answering 'what is this cell's bound?' without asking the authority".
    # tep_cg_bound.py is exempt because it is the PRODUCER: it writes these artifacts and the
    # lp_street field in them. Reading back what you wrote is not re-deriving a lookup. Checked
    # rather than assumed -- it is the only one of the fourteen the rule flagged that writes a
    # tep_cg_bound path (5 write sites; every other flagged module has 0).
    dict(authority="best_known",
         owns="which artifacts hold a bound for a cell (_bound_patterns)",
         exempt={"best_known.py", "bound_source.py", "tep_cg_bound.py"},
         touches=re.compile(r'tep_cg_bound_%s'),
         rederives=re.compile(r'\[["\']lp_street["\']\]|get\(["\']lp_street["\']\)'
                              r'|\[["\']composed["\']\]|get\(["\']composed["\']\)')),
]
# A THIRD RULE WAS WRITTEN AND REMOVED THE SAME MINUTE. It aimed at bound_certificate and fired on
# any module reading a `proven` field -- 23 files, including tep_cg_bound.py, which WRITES that
# field. Reading a field is not re-implementing a lookup. A gate with 23 false positives is worse
# than no gate: it gets skimmed, then bypassed, and then it protects nothing, which is the exact
# failure this file exists to stop. Two precise rules beat three where one is noise. If the
# certificate lookup ever needs guarding, the signal has to be a re-derived DECISION -- something
# shaped like `proven and not primal_rounding` -- not the presence of the word.

# Modules that re-derive the best-known today. Measured 2026-09-28: none of the six is referenced
# by analysis/manuscript_numbers.py, analysis/reproduction_index.py or paper/numbers.tex, so no
# reported number depends on them. The list only shrinks.
KNOWN = {
    "best_known": {"campaign_dry_audit.py", "tep_ablation_table.py", "tep_chain_own_water.py",
                   "tep_incumbent_ledger.py", "tep_insights.py", "tep_runtime_vs_k.py"},
    "quarantine_guard": set(),
    "bound_certificate": set(),
}
# The bound-lookup offenders as of 2026-09-28, when the rule was added. THE LIST ONLY SHRINKS.
# Measured before listing them: none is referenced by manuscript_numbers.py, make_tables.py,
# release_gate.py, supervision.py or claims.py, so no reported number depends on any of them --
# which is why they are tracked rather than rewritten in one sweep. Two grades of offence:
#   GLOBBING   builds its own pattern list but does glob, so it is a duplicate authority and
#              not blind: tep_cut_phase0, tep_harvest_master_ip, tep_n30_best_of.
#   BLIND      builds ONE path and takes its absence as final -- the defect that cost
#              bound_source 85 of 135 cells: the rest.
# dual_vs_k is listed for its main() diagnostic only; its live lb_frontier/lb_maxrec path,
# the one bound_source.descent_bound actually calls, does not build these paths.
KNOWN["best_known"] |= {
    "cg_family_verdict.py", "cg_necessary_check.py", "dual_vs_k.py", "envelope_with_cg.py",
    "tep_cg_batch.py", "tep_coverage_map.py", "tep_cut_phase0.py",
    "tep_fine_delta_bound_batch.py", "tep_harvest_master_ip.py", "tep_intcars_batch.py",
    "tep_intcars_grid.py", "tep_n30_best_of.py", "tep_n30_table.py",
}


def scan():
    new, known_seen = [], []
    for fn in sorted(os.listdir(AN)):
        if not fn.endswith(".py"):
            continue
        try:
            src = io.open(os.path.join(AN, fn), encoding="utf-8").read()
        except Exception:
            continue
        # Comments and docstrings name these modules constantly -- this file's own docstring names
        # both authorities. Stripping only `#` lines let a module mentioning `quarantine_guard` in
        # its docstring pass as though it imported it, which the mutation test caught.
        code = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", src)
        code = "\n".join(l for l in code.splitlines() if not l.lstrip().startswith("#"))
        for r in RULES:
            if fn in r["exempt"]:
                continue
            if r["authority"] in code:          # it asks the authority: fine
                continue
            if not (r["touches"].search(code) and r["rederives"].search(code)):
                continue
            row = (r["authority"], fn, r["owns"])
            (known_seen if fn in KNOWN.get(r["authority"], set()) else new).append(row)
    return new, known_seen


def main():
    new, known_seen = scan()
    print("SINGLE AUTHORITY -- one lookup, one implementation\n")
    for auth, fn, owns in sorted(known_seen):
        print("  known   %-22s re-derives %s" % (fn, owns))
    if known_seen:
        print("          (%d frozen; none feeds a reported number, measured 2026-09-28. The list only shrinks.)\n"
              % len(known_seen))
    for auth, fn, owns in sorted(new):
        print("  NEW     %-22s re-derives %s" % (fn, owns))
        print("          import %s and ask it, or add %s to KNOWN with a reason." % (auth, fn))
    stale = []
    for auth, names in KNOWN.items():
        seen = {fn for a, fn, _ in known_seen if a == auth}
        for fn in sorted(names - seen):
            stale.append((auth, fn))
    for auth, fn in stale:
        print("  FIXED   %-22s no longer re-derives %s -- remove it from KNOWN" % (fn, auth))
    print()
    if new:
        print("  %d NEW duplicate authority(ies). This is the class that cost two wrong lookups in one\n"
              "  morning; it fails the commit rather than being noticed later." % len(new))
        return 1
    print("  no new duplicate authorities%s" % ("; %d still frozen" % len(known_seen) if known_seen else ""))
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
