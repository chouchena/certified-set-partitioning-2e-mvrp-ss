# Replicability of every reported quantity

**The rule: nothing in the manuscript is typed by hand.** Not a table cell, not a figure, and
**not a number embedded in a sentence.** Prose numbers are the ones that rot silently — a table
gets regenerated when the data changes, but *"R has the widest windows (0.397)"* sits inside a
paragraph for months while the artifact behind it is superseded twice.

Three mechanisms enforce this — numbers, figures, tables — and each one **fails a command**
rather than relying on care. All three are checked by `analysis/release_gate.py`.

---

## 1. Numbers — `analysis/manuscript_numbers.py`

Every manuscript number is a named entry computed from banked artifacts.

```
python analysis/manuscript_numbers.py            # recompute; write numbers.json + numbers.tex
python analysis/manuscript_numbers.py --check    # recompute and DIFF; non-zero exit if anything moved
```

Outputs:

| file | purpose |
|---|---|
| `paper/numbers.json` | value + unit + description + **the register claim that licenses it** |
| `paper/numbers.tex` | `\newcommand{\numID}{value}` — the manuscript writes `\numlbunprovenwins`, never `19 of 20` |

**Why `--check` diffs instead of silently regenerating.** Regeneration would hide that a number
*moved*. The diff is the point: when an artifact changes, the build fails and **a human decides
whether the sentence around the number still makes sense.** A number that moves can invalidate the
clause it sits in, and only a person can judge that.

Each entry records its `claim` id, so any number in the paper traces to the register entry that
licenses it and to the falsifier that could retire it.

**Naming trap, recorded because it cost a run:** this file must **not** be called `numbers.py`.
`analysis/` is on `sys.path`, and that name shadows the standard library's `numbers`, which
`decimal`, `fractions` and `statistics` import transitively.

Currently registered: **19 numbers, 0 errors.**

**The S3a entries call the ablation scripts; they do not re-derive the tests.** A second exact
Wilcoxon implementation inside the registry would be a second thing to get wrong, and the failure
mode it invites — the paper's p-value quietly disagreeing with the verdict script's — is exactly
what this registry exists to prevent. `s3a_significance.main` and `s3a_friedman_holm.main` return
their results; the registry consumes them.

## 2. Figures — `analysis/make_figures.py` + `analysis/figstyle.py`

Every figure is regenerated from artifacts and emits a **provenance sidecar** beside the artwork:

```
paper/figures/F2_closed_share_vs_size.pdf     vector, for submission
                                    .eps      vector, EPS preferred by the publisher
                                    .png      for quick viewing only
                                    .prov.json  ← provenance
```

The sidecar carries the generating script, the **`code_hash`** (a hash of the actual loaded module
bytes, so it identifies the code independently of any repository state), the commit, the font
actually used, the Python version, the UTC timestamp, and the **artifact globs consumed** — so a
reader can find the inputs without reverse-engineering the script.

`figstyle.apply()` also enforces the publisher's artwork requirements once, centrally: Helvetica or
Arial (matplotlib's default DejaVu Sans is neither), 8–12 pt lettering, vector output, 600 dpi, RGB,
no embedded title because captions belong in the manuscript text file. **If no compliant font is
found it warns loudly** rather than silently emitting non-conforming artwork.

### The figures, and the one command that rebuilds each

| | figure | the single claim it carries | command |
|---|---|---|---|
| **F1** | anytime dual bound vs wall time, normalised by the predecessors' published bound | we reach their bound level early and keep improving — **no cross-hardware claim is made** | `python analysis/make_figures.py f1` |
| **F2** | closed share of the closable gap vs \|C\| | the central result **and its honest decline** with size | `python analysis/make_figures.py f2` |
| **F3** | selection ablation, frontier and matched-`k` panels | the retention **policy** is what produces the bound, and the gain is bound quality rather than reach | `python analysis/make_figures.py f3` |
| **F4** | deepest proven \|H\|/\|C\| vs \|C\| | the **mechanism** behind F2's decline: truncation of the retained set, not a loosening relaxation | `python analysis/make_figures.py f4` |
| **F5** | arithmetic vs restriction carrier, per cell | the crossover is **per cell, not per family** | `python analysis/make_figures.py f5` |

`python analysis/make_figures.py` with no argument rebuilds all five.

**F3 imports its definitions from `analysis/s3a_ablation_compare.py`,** so the figure and the
ablation verdict cannot drift apart — the same discipline that ties T1 to F2. A figure that
re-implements the comparison it illustrates can disagree with it, silently, for a whole review
cycle.

## 3. Tables — `analysis/make_tables.py`

Same contract as figures: regenerated from artifacts, emitted as LaTeX, each with a
`.prov.json` sidecar.

| | table | what it is |
|---|---|---|
| **T1** | bound summary by size and family | the headline result in table form. F2 plots the closed share; T1 gives the magnitudes a reader needs to check it. **The two agree by construction, because both call the same functions.** |
| **T2** | instance-equivalence calibration | our objective against the exact method's proven optima. A **validation** table, not a performance one: on a proven-optimal instance, matching is the ceiling. |

Conventions are applied in the script and restated in each caption, so a referee does not have to
ask: the reference dual bound is derived as `BK x (1 - gap/100)` (verified to reproduce their
published gaps); closed share aggregates sums within a family rather than averaging per-instance
ratios; |C| = 10 is omitted because every instance is proved there and the closable gap is zero;
|C| = 50 is pooled because the exact method reports that size by cost ratio rather than by family.

---

## What the release gate enforces

`python analysis/release_gate.py` blocks publication on, among other things:

* `G11` every figure **and table** carries a `.prov.json` sidecar
* `G12` `paper/numbers.json` is current — i.e. `--check` passes

Both are blocking, because a stale number or an unprovenanced figure is exactly the defect that
survives review and surfaces after publication.

## The chain, end to end

```
solver run  ──►  artifact with full provenance      (code_hash, git_sha, seed, det_ticks,
     │            in crossfeed/ or runs/             threads, solver version, python, host)
     │
     ├──►  analysis/manuscript_numbers.py  ──►  numbers.json + numbers.tex  ──►  \num{} in the text
     │
     ├──►  analysis/make_figures.py        ──►  figure + .prov.json         ──►  \includegraphics
     │
     └──►  analysis/make_tables.py         ──►  table .tex + .prov.json      ──►  \input{}
```

`code_hash`, not `git_sha`, is the anchor: every n20 artifact carries `git_dirty=true`, so the
commit alone would not reconstruct the code state. A reader reconstructs `code_hash` by cloning the
release and running `fetch_karademir.py`, which restores the third-party files at a pinned commit
under SHA-256 verification. See `paper/RELEASE_DESIGN.md`.
