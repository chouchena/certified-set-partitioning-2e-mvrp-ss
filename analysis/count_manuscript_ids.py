# -*- coding: utf-8 -*-
"""Count \\num{...} ids cited in the manuscript section sources, and how many are
primal-fleet vs dual-leg. Written to a file because a bash heredoc collapses the
doubled backslash in the regex (CLAUDE.md section 4)."""
import re, glob, io, os
os.chdir(r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir")

PAT = re.compile(r"\\num\{([^}]+)\}")
ids = set()
files = sorted(glob.glob("paper/manuscript/sections/*.tex"))
for f in files:
    ids |= set(PAT.findall(io.open(f, encoding="utf-8", errors="replace").read()))

print("section source files: %d" % len(files))
print("distinct num ids on the page: %d" % len(ids))

fleet = sorted(i for i in ids if i.startswith("n20-fleet-total") or i in ("one-car-cells-n20",)
               or i.startswith("rc208-one-car") or i.startswith("r205-one-car")
               or i.startswith("fleet-certificate-coverage"))
print("\nsection 5's targets on the page: %d  %s" % (len(fleet), fleet))

GROUPS = ("lb-dual-wilcoxon", "gap-closed-by-family", "lb-time-to-exceed-k",
          "lb-over-kdual-n100", "ab-crossovers-by-size", "n50-ratio-vs-k",
          "lb-unproven-wins", "s2k-closure", "s3a-")
dual = sorted(i for i in ids if any(i.startswith(g) for g in GROUPS))
print("dual-leg ids on the page: %d" % len(dual))
for g in GROUPS:
    n = sum(1 for i in ids if i.startswith(g))
    if n:
        print("   %-24s %d" % (g, n))
print("\n=> section 5 claims to cover manuscript exposure and its targets appear %d times;"
      % len(fleet))
print("   the dual-leg groups appear %d times." % len(dual))
