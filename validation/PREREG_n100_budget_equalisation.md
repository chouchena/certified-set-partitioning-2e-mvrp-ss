# PREREG — re-run the budget-limited n100 cells at 9000 s

Written 2026-09-15, **before any re-run**, because this re-run will move reported numbers and its
result direction is predictable and favourable to us. That is the exact situation pre-registration
exists for.

**NOT LAUNCHED.** S2k holds the machine, and nothing runs concurrently.

---

## 1. The defect

Per-cell budgets were never equalised across sizes:

| size | cell budget | cells ≥90% of budget | over budget | max utilisation |
|---|---|---|---|---|
| n20 | 5400 s | 0 / 27 | 0 | 37% |
| n30 | 5400 s ×10, 9000 s ×17 | 0 / 27 | 0 | 40% |
| n50 | 9000 s | 0 / 27 | 0 | 26% |
| **n100** | **2400 s** | **10 / 27** | **7** | **132%** |

The largest instances received the smallest budget — a quarter of n50's. Any claim that the bound
degrades with size is therefore **partly a claim about budget**, and the two are confounded in
every figure and number that spans sizes.

## 2. Why only n100, and only ten of its cells

**Only n100 binds.** At n20, n30 and n50 no cell reaches 90% of its budget and the maxima are
37%, 40% and 26%. Raising those budgets cannot change a run that never approached its cap, so
re-running them would consume days and reproduce the same numbers.

**At n100 only ten cells bind.** The other seventeen finished below 90% of 2400 s, which means the
budget check — `if cumulative_wall >= cell_budget: break` — never fired for them; they exited on
the descent's own stop rule, either `k` reaching 0 or two consecutive non-certifying solves. A
larger cap cannot alter a loop that did not exit on the cap.

**Scope: these ten cells, at 9000 s.**

```
R202  R203  R205  R206  R208  R209  R210  RC202  RC204  RC205
```

9000 s is not a new number: it is the budget n50 already received, so this **equalises** rather
than escalates. The other seventeen n100 cells are **not** re-run and their artifacts stand.

**Estimated cost: ≤ 25 h** (10 × 9000 s worst case), less where a cell's descent completes first.

## 3. Primary outcome — fixed now, before any informative data

**Per-cell block_relax at 9000 s versus the banked value at 2400 s, on these ten cells only.**

Reported as: the number of the ten whose bound **improves**, and the median relative improvement
over the ten. Both denominators are **ten**, fixed here, and neither is to be recomputed over a
subset chosen after seeing the results.

**Secondary, and re-derived rather than re-decided:** `ab-crossovers-by-size.n100`,
`milp-over-kbk-by-family-n100`, F2's n100 point and F4. These move mechanically if the primary
outcome moves; they are consequences, not additional outcomes.

## 4. The direction is predictable, and that is the danger

More budget produces a better-or-equal bound. **It cannot get worse** — the descent only records
additional certified or truncated values, and the estimator is a max. So:

* **a favourable result is guaranteed in direction** and only its magnitude is in question;
* the improvement will shrink the apparent degradation with size, which flatters the leg the
  paper leads with;
* a referee who sees n100 alone re-run at a raised budget, after the original result was
  published internally, is entitled to ask what prompted it.

**The answer must be the one in §1 and must be in the paper**: the budgets were unequal, we found
it while compiling run-time descriptives, and we equalised to the budget the next size down
already had. That sentence goes in the computational study whatever the result, and it is the
reason this file exists.

**Registered now:** if the bound does not improve on any of the ten, that is reported too, and it
is a *stronger* result — it would show the n100 degradation is not a budget artifact.

## 5. What must NOT happen

* **No re-running of n20, n30 or n50** on this rationale. They do not bind; §2 is the evidence.
* **No budget above 9000 s.** That would escalate rather than equalise and would re-open the same
  objection one level up.
* **No re-selection of the ten.** The list in §2 is fixed by a mechanical criterion — wall ≥ 90%
  of budget — evaluated before the run and recorded above.
* **No quiet replacement of the banked artifacts.** The 2400 s records stay; the 9000 s records
  are new files, and both are reported.

## 6. Adverse audit

1. **The cheaper alternative is disclosure alone**, and it is defensible: one sentence saying
   n100 ran at 2400 s against 9000 s at n50. It costs nothing and is honest. It is rejected
   because it leaves a known confound inside the paper's central degradation claim, and because
   a referee would reasonably ask why we did not simply equalise when it costs 25 h.
2. **Equal wall budget is itself a choice.** Larger instances are harder, so equal budget means
   less effective effort per customer. It is the right choice here because it is K's own
   protocol — they gave every size 14400 s — and because the alternative, scaling budget with
   size, would be a design we invented after seeing our own results.
3. **The seventeen untouched cells make the n100 row heterogeneous**: ten at 9000 s, seventeen at
   2400 s. This is disclosed rather than hidden, and it is preferable to spending a further day
   reproducing seventeen numbers that cannot change.
4. **`det_tl` does not survive a code change** (Stage 1, 2026-09-15). These re-runs will execute
   at a later `code_hash` than the originals, so the comparison is bound-to-bound at different
   code states, not a reproduction. Both `code_hash` values are recorded and the difference is
   stated.

## 7. Gate

Runs only after S2k completes and the machine is idle. The tenancy gate in
`analysis/rt_fair_pipeline.py` was blind to current solvers until 2026-09-15; whatever launches
this must use a guard that can see `s2k_exact_closure.py` and `redump_incumbents.py`.

---

## AMENDMENT 1 — 2026-09-15, appended before any run

The author's point: **we do not need to re-run the sizes whose budget went unused — we can
compare sizes on the cells where the budget did not affect the result.** That costs nothing and
it answers the question the re-run was meant to answer. Measured now, before spending 25 h:

Our MILP bound as a share of K's best-known:

| set | n | mean | median |
|---|---|---|---|
| **n50** (0 of 27 binding) | 27 | **0.578** | 0.584 |
| **n100, budget-free** | 17 | **0.367** | 0.398 |
| n100, budget-binding | 10 | 0.247 | 0.229 |
| n100, as reported | 27 | 0.322 | — |

### What this settles, and what it does not

**Settled: the degradation with size is NOT a budget artifact.** On cells where the budget never
bound at either size, the share still falls 0.578 → 0.367 from n50 to n100. The paper's central
degradation claim survives without any re-run, and it now survives *on a subset chosen by a
mechanical criterion fixed before the comparison*.

**Also settled: the reported n100 figure is pessimistic.** 0.322 against 0.367 on the budget-free
cells. We are under-reporting our own bound at n100 by roughly 0.045 because ten cells were cut
short.

**NOT settled, and this is the trap:** the binding cells are not a random sample. A cell binds
because it is **hard**, and a hard cell would score worse than average even with unlimited
budget. So the 0.247-versus-0.367 gap **cannot be attributed to budget** — it is budget and
difficulty confounded, and no amount of staring at these numbers separates them.

### Consequence for this pre-registration

**The re-run is downgraded from necessary to informative, and its question is now sharper.** It
is no longer "is the degradation a budget artifact" — that is answered, and the answer is no. It
is: **of the binding cells' shortfall, how much is budget and how much is difficulty?** Only the
re-run can decompose it, because it holds difficulty fixed and varies only the budget.

The primary outcome in §3 stands unchanged and is exactly the right measurement for that
question. What changes is the **priority**: the paper can be drafted and defended without this
run, so it is optional, and should be scheduled only if the decomposition is judged worth 25 h.

### What must be reported whether or not it runs

Both the stratified comparison above **and** the fact that n100 ran at 2400 s against 9000 s at
n50. Reporting the unstratified 0.322 alone would be under-claiming our own result while
concealing why; reporting 0.367 alone would be quoting a subset chosen after the fact. Both, with
the criterion stated, or neither.

---

## AMENDMENT 2 — 2026-09-15, appended before any run. THE RUN IS ON.

**Author's rationale, which supersedes Amendment 1's downgrade.** The purpose is not to decompose
budget from difficulty. It is to obtain a **budget-free n100 at full scope**, so that the
cross-size comparison is 27 cells against 27 cells rather than n50's complete 27 against a
difficulty-selected 17.

That is a better reason than the one this file was opened with, and it dissolves the objection
Amendment 1 raised against itself. The confound in "0.247 versus 0.367" was that the binding
cells are selected by difficulty. **Re-running them removes the selection entirely** — there is
no subset left to be selected, because every cell is budget-free. The comparison stops being
"n50 complete versus n100 partial" and becomes like-for-like on the whole benchmark.

### Revised primary outcome — registered before any data

**n100's full-scope, budget-free mean bound as a share of K's best-known, over all 27 cells,
against n50's 0.578 over its 27.** Denominators are 27 and 27, fixed here.

Retained from §3 and still reported: how many of the ten improve, and the median relative
improvement over the ten. Those are now secondary.

### The rule for a cell that STILL binds at 9000 s — registered now, not after

A re-run cell may reach 90% of 9000 s. If any do:

* **the full-scope claim is not made.** We report "budget-free on 27 − *m* cells" with *m* named,
  and the like-for-like comparison uses the budget-free set at both sizes with both denominators
  stated.
* **the budget is not raised again.** Escalating until the cells stop binding is the fishing
  expedition this file exists to prevent. 9000 s equalises with n50 and that is the whole
  justification; a third budget would have none.

### Configuration — everything held constant except the budget

Read from the banked n100 records, so the re-run differs in exactly one parameter:

```
--size 100  --proximity 0.1  --k-hi 67  --k-cap 72  --tl 900
--det-tl 450000  --workers 4  --bounder cplex  --seed 20260910
--cell-budget 9000            <-- the only change, was 2400
```

### Artifacts are written to a NEW path, and the analysis is taught to ignore it

Output goes to `crossfeed/easy_reduction_descend_<cell>_n100_b9000.json`. The 2400 s artifacts are
untouched.

**`b9000` is added to the artifact-exclusion lists in `analysis/manuscript_numbers.py` and
`analysis/rt_leg_descriptives.py` BEFORE the run.** Without that, `_cells(100)` and `_frontier`
would glob the new files and silently mix two budgets into one number — the "stale artifacts
outliving their headline" failure, pre-empted rather than discovered. The comparison script reads
the new artifacts by explicit path only.

---

## AMENDMENT 3 — 2026-09-15. Escalation on re-binding. SUPERSEDES §5's "no budget above 9000 s"

The author directs: if a cell binds again at 9000 s, re-run it with a larger budget. **Amendment 2
and §5 forbade exactly this, and they were wrong.** The reasoning that replaces them:

**Equal budget is not equal constraint.** n50 never exceeded 26% of its 9000 s — it was already
unconstrained. If an n100 cell still binds at 9000 s, matching n50's number has equalised nothing;
that cell is still the only one being cut short. The condition the comparison actually requires is
**budget-free at both sizes**, and "equal budget" was a proxy that fails precisely where it
matters.

**The escalation is outcome-blind, which is what separates it from fishing.** The stopping
criterion is *"the budget check stopped firing"* — a property of the run's termination, not of the
value it produced. The bound is **not consulted** in deciding whether to escalate. That is
registered here so that it cannot later be softened.

### The escalation rule — fixed now

```
budget := 9000
repeat:
    run the cell at `budget`
    if total wall < budget:  cell is BUDGET-FREE, stop        <- outcome-blind criterion
    budget := budget * 2                                       <- 9000 -> 18000 -> 36000
until budget > 36000
```

* **Doubling**, so the schedule is fixed in advance and no per-cell judgement enters it.
* **Hard cap 36000 s per cell** (10 h), at most two escalations. Worst case for all ten is
  10 × (9000 + 18000 + 36000) = 175 h, but only cells that keep binding escalate, and each
  escalation is entered only by a cell that demonstrably exhausted the previous budget.
* **A cell still binding at 36000 s is reported as such**, with its value at 36000 s, and the
  full-scope budget-free claim is then made over 27 − *m* cells with *m* named — the §Amendment 2
  rule, unchanged.

### What must be disclosed, and the answer to the obvious objection

n100 cells may end up with more budget than n50's 9000 s. **A referee can reasonably ask whether
n100 was favoured.** The answer, which belongs in the paper:

> n50 used at most 26% of its budget, so it was unconstrained at 9000 s. Additional budget was
> given only to n100 cells that exhausted theirs, and only until they stopped exhausting it. The
> comparison is between two unconstrained sets, not two equally-budgeted ones, because equal
> budget does not imply equal constraint.

**Recorded as mandatory:** the per-cell final budget is reported for every escalated cell. Burying
"some cells got 36000 s" inside a mean would be the concealment this whole file exists to avoid.

### The primary outcome is unchanged

n100's full-scope budget-free mean share over 27 cells against n50's 0.578 over its 27. The
escalation changes how *budget-free* is reached, not what is measured.

---

## AMENDMENT 4 — 2026-09-15. The trajectory log makes the budget choice post-hoc, and that is legitimate

**The author's point, and it reverses the cap-at-14400 proposal I was about to make.** Every
descent record carries `lb_curve`, a list of `(elapsed, bound)` pairs offset onto a common
per-cell timeline by `BoundTracer(offset=cumulative_wall)`. Verified on `R202_n100`: 827
trajectory points across 5 records.

So for any `T` **not exceeding the run's actual length**, the bound we held at time `T` is
recoverable as the running maximum over all curve points with `elapsed <= T`. And that value is a
**valid lower bound**, because every recorded value is one by Lemma 3 (Step 0) and the estimator
is a max. Reading it off is therefore not an approximation of what a `T`-second run would have
produced — it is exactly what a `T`-second run would have produced.

**Consequence: run LONG, present at whatever budget the claim requires.** A longer run subsumes
every shorter one. Capping at 14400 s to protect the against-K comparison would have thrown away
the budget-free measurement for no gain; running to 36000 s and truncating the curve gives both
from one run.

### The presentation rule — registered NOW, before any curve is seen

This is the whole discipline of this amendment. Choosing `T` after looking at the curves would be
picking the budget that flatters us. So:

| claim | budget at which it is read |
|---|---|
| **anything compared against K's published dual bound** | **T = 14400 s**, K's own limit |
| **the cross-size budget-free comparison** (n50 vs n100, the §Amendment 2 primary outcome) | the **terminal** value of a budget-free run |
| anything else | **no other `T` is quoted.** Two values per cell, both named above |

### The other sizes are already valid at T = 14400 s, with no re-run

At n20, n30 and n50 **no cell binds**, and the longest run at any of those sizes is 3567 s. Every
one terminated on the descent's own stop rule far inside 14400 s, so the bound each holds at
T = 14400 s **is** its terminal bound. The against-K comparison at K's budget is therefore already
supported by the banked artifacts at those sizes. Only n100 needed a longer run, and only its ten
binding cells.

### What this settles

* **The cap stays at 36000 s.** It is no longer a fairness question, because the against-K claim
  is read at 14400 s regardless of how long the run continued.
* **The escalation rule is unchanged** and still outcome-blind: escalate while the budget check
  fires, read total wall only.
* **Both numbers are reported per escalated cell** — the value at 14400 s and the budget-free
  terminal value — along with the final budget. A reader can see the whole trajectory decision.

### The one thing that must be checked when the runs land

`lb_curve` must be populated in the new artifacts. It comes from a progress listener, and
`_bound_ws` installs it as a **pure observer** with `track_progress=False`, deliberately, because
passing `True` would install a `StallStopper` that aborts on plateau and would change `proven`. If
a future edit drops the tracer, the trajectory vanishes and this amendment's whole basis goes with
it. **Verify point counts are non-zero before relying on any T-truncated value.**

---

## AMENDMENT 5 — 2026-09-16. A forward prediction, and a defect in the primary outcome's estimator

Three cells have run (R202, R203 done; R205 in flight). Seven have not started. This amendment is
appended **before those seven run** so the per-cell prediction below stands as a prediction. It
also records a defect I found while constructing it, which matters more than the prediction does.

Generating code for every number here: `analysis/n100_budget_forward_check.py`.

### 5.1 What I reported earlier, and the correction

I reported "R202, R203, R205 done, with deltas +0.00, +0.00, −0.57". Two errors.

* **R205 was not done.** It started 02:04:08Z and is still running. The descent rewrites its JSON
  after *every* record, so the artifact existing proves only that a record was written. The
  driver log is the witness, and it has no "R205 ... done" line. Its −0.57 was read off a partial
  artifact of 4 records and is not a final value. `_complete()` in the check script now reads the
  driver log rather than testing for the file.
* **"6 of 7 cells cannot improve" overstated the mechanism.** See 5.2.

### 5.2 The prediction, stated at the strength the mechanism actually supports

`easy_reduction_descend` has two phases. Phase 1 escalates *k* upward while solves fail to
certify; phase 2 descends, and runs **only after a solve certifies**. So a cell whose banked
records are all `proven=False` has never entered phase 2, and extra budget buys further
escalation records at higher *k*.

Under monotone nesting (L-nest) the relaxation value is non-increasing in *k*, so the added
records are **expected** to be weaker than the incumbent maximum, and the estimator — a max over
all records — is expected to be unchanged.

**It is not "cannot improve", and I registered it that way first.** The recorded values are
*truncated* dual bounds, not the relaxation optima, so nesting does not order them. R205's own
banked records run 1070.27 at *k*=67 then **1074.85 at *k*=68**: the truncated value rose with
*k*. An added record can exceed the incumbent max. The prediction is directional only.

| cell | certifies? | status at registration | prediction |
|---|---|---|---|
| R202 | no | done | escalation only — no improvement expected |
| R203 | no | done | escalation only — no improvement expected |
| R205 | no | **in flight, 4 records seen** | escalation only — no improvement expected |
| R206 | no | not started | escalation only — no improvement expected |
| R208 | no | not started | escalation only — no improvement expected |
| R209 | no | not started | escalation only — no improvement expected |
| R210 | no | not started | escalation only — no improvement expected |
| RC202 | no | not started | escalation only — no improvement expected |
| RC204 | no | not started | escalation only — no improvement expected |
| **RC205** | **yes, at k=71** | not started | **phase 2 can descend — improvement possible** |

**Nine of ten are escalation-only. RC205 alone can descend.** The prediction basis is the banked
2400 s artifacts, which existed before any re-run, so it is derivable pre-run for all ten. It is
**blind** only for the seven not started: R202 and R203 have landed and I have seen four of
R205's records. That distinction is recorded rather than smoothed over.

**Falsifier.** A nonzero improvement on any of the nine escalation-only cells. That would not
refute validity or nesting — it would refute the word *expected*, and would mean truncation noise
dominates the ordering, which is itself reportable.

### 5.3 The defect: the primary outcome's estimator is contaminated by wall-clock nondeterminism

Every record stops on one of two limits and names it in `limit_hit`: the deterministic tick budget
(`det`, `--det-tl 450000`) or the wall clock (`wall`, `--tl 900`). The descent is passed **both**,
and `--tl` wins whenever it binds first. CLAUDE.md fixes `det_tl` "wherever a result must
reproduce"; it does not hold here, because a second limit was left in place beside it.

**11 of the 51 banked records across the ten selected cells stopped on the wall clock.**

A wall-stopped record is not reproducible by construction — the tick count at which it stops
depends on machine load. The re-run re-solves the same *k* values the baseline solved, so any
wall-stopped record re-solves to a *different* value, and that drift enters the reported delta
alongside the budget effect.

Measured on the matched *k* values, where the **only** intended difference is `--cell-budget` — a
parameter that controls how many records are run and can have no effect whatever on the value of a
record both runs share:

| pairs | n | drifted | largest |
|---|---|---|---|
| both stopped on `det` | 7 | **0** | — |
| either stopped on `wall` | 6 | **6** | R203 *k*=71, **+6.82** |

The separation is total in both directions, which is as clean a negative control as this project
has produced. **`det_tl` reproduces exactly when it binds.** The wall limit is the whole defect.

**Consequence for the registered primary outcome.** The per-cell delta of §3 is a difference of
two maxima taken across two runs, and on any cell with a wall-stopped record it mixes a budget
effect with a drift of up to ±6.82 — larger than any budget effect observed so far (the three
landed cells: +0.00, +0.00, and an in-flight −0.57 that is *entirely* matched-*k* drift, since
R205's re-run has added no record exceeding its banked max).

### 5.4 The fix — a within-run estimator, registered now

**The primary outcome of Amendment 2 is unchanged**: n100's full-scope budget-free mean share over
27 cells against n50's 0.578. That statistic is a terminal value per cell and does not difference
two runs.

What is repaired is the §3 retained secondary — "how many of the ten improve". It is re-specified
to a contrast taken **entirely inside the re-run**, where no cross-run drift can enter:

```
budget_effect(cell) = max over ALL re-run records
                    − max over re-run records at k values the BANKED run also reached
```

This asks exactly the intended question — *what did the extra records buy* — and asks it of one
run, so every value on both sides came out of the same solve sequence. No `wall`/`det` mixture can
contaminate it.

* Denominator remains **ten**, as fixed in §3. Not to be recomputed on a subset.
* Valid because each phase-1 record is solved **cold** (`warm=False` on every record of the nine
  escalation-only cells; `solve_k` warm-starts only in phase 2). For RC205, phase-2 records are
  warm-started from *k*+1 and therefore chained — the contrast is still within one run and still
  drift-free, and the chaining is disclosed.
* The cross-run delta of §3 is **still reported**, alongside its `limit_hit` census, so a reader
  can see both the contaminated and the clean figure and why they differ.

### 5.5 What is NOT done about it

**`--tl 900` is not raised, and the seven remaining cells are not reconfigured.** Amendment 2 fixes
every flag but `--cell-budget`; changing `--tl` mid-batch would make the last seven cells
incomparable to the first three and would void the primary outcome outright. The defect is
disclosed and estimated, not patched under the running batch.

**Registered for the next batch that uses this solver:** pass `--tl` large enough that `--det-tl`
always binds, or drop `--tl` entirely. A run carrying two limits reproduces only when the
deterministic one wins the race, and 11 of 51 times here it did not.

---

## AMENDMENT 6 — 2026-09-16. The reported bound excludes wall-stopped records

Registered while the batch is running: R202, R203, R205 have landed, R206 is executing, six cells
have not started. **This is not blind, and §6.4 below states exactly what had been seen.**

Canonical implementation: `analysis/lb_estimator.py`. Measured by
`analysis/n100_budget_forward_check.py`.

### 6.1 The change

The per-cell reported dual bound becomes

```
reported_bound(cell) = max{ block_relax(r) : record r did NOT stop on the wall clock }
```

replacing the max over all records. The test is `limit_hit == "wall"`. A record whose `limit_hit`
is neither `det` nor `wall` terminated on the solver's own optimality proof — those are the best
records and are **kept**. (An earlier pricing of this change excluded them and undercounted
RC205; recorded so the error is not repeated.)

### 6.2 Why

Amendment 5 established that the descent carries two per-record limits, `--det-tl 450000` and
`--tl 900`, and that whichever binds first wins. The separation is total:

| matched-k pairs | n | reproduced | drifted |
|---|---|---|---|
| both stopped on `det` | 7 | **7** — bound *and tick count*, to the decimal | 0 |
| either stopped on `wall` | 6 | 0 | **6**, up to +6.82 |

A wall-stopped record cannot be re-derived, because the tick count at which the clock ran out is
a function of machine load. Rule 1 of `CLAUDE.md` is that replicability is absolute and every
reported number has generating code; generating code that returns a different number each time
does not satisfy it. **Excluding these records buys exact reproducibility of the reported bound.**

### 6.3 Validity is unaffected, and the change can only run against us

Every record is a valid lower bound (L-block, L-restrict, L-step0), so the maximum over any
**subset** is also a valid lower bound. The new estimator is a max over a subset of the old one's
domain, hence weakly dominated by it:

> **The exclusion can only lower the reported bound. It cannot inflate any result.**

That is the property that makes it safe to adopt on partial sight, and it is why this amendment
is not the fishing expedition the file guards against — the direction of the change is against
our own interest, fixed by construction rather than by inspection.

### 6.4 What had been seen when this was registered — stated because it matters

Three of ten re-runs had landed and I had priced the change on them and on all 27 banked n100
artifacts. Concretely, I knew:

| | cells losing anything | mean loss | worst |
|---|---|---|---|
| banked n100, 27 cells | **1 of 27** (R205) | 0.139 % | 3.77 % |
| landed re-runs | R205 only; R202 and R203 lose 0.00 | — | **0.62 %** |

**The justification is the principle in §6.2, not that price.** Had the cost come out at five per
cent the change would still be correct, because a number that does not reproduce is not reportable
under this project's first rule. The price is recorded so a reader can see it was not the reason.

### 6.5 The rule is uniform across sizes, and that is the test of good faith

An estimator adopted only where it happens to be cheap is a result chosen after the fact. This one
applies at every size, and is a **no-op at three of the four**:

| size | cells | records | wall-stopped | cells affected | mean loss |
|---|---|---|---|---|---|
| n20 | 27 | 206 | **0** | 0 | 0.000 % |
| n30 | 27 | 176 | **0** | 0 | 0.000 % |
| n50 | 27 | 325 | **0** | 0 | 0.000 % |
| n100 | 27 | 180 | 11 | 1 | 0.139 % |

Zero wall-stopped records exist below n100. The rule binds only where the two-limit race was
actually lost, which is the behaviour a rule should have.

### 6.6 What is reported

**Both numbers, per cell, with the census.** `analysis/lb_estimator.py:cell_bound_pair` returns
the pair and `wall_census` returns the `limit_hit` counts. Reporting only the reproducible number
would conceal that a stronger valid bound was observed; reporting only the larger would be the
irreproducible figure. The paper leads with the reproducible one and names the other where they
differ — which, on present evidence, is one cell out of 108 across all four sizes.

The primary outcome of Amendment 2 — n100's full-scope budget-free mean share over 27 cells
against n50's 0.578 — is computed on the **reproducible** estimator. n50 is unaffected (zero
wall-stopped records), so the comparison does not change definition between the two sides.

### 6.7 What must happen next, and what must not

* `analysis/manuscript_numbers.py` imports `lb_estimator` rather than computing a max inline.
  Any inline `max(block_relax)` left in the analysis is a defect once this lands.
* **The running batch is not reconfigured.** `--tl` stays 900 for the remaining six cells;
  Amendment 5 registered that changing a flag mid-batch would void the one-parameter comparison.
  This amendment changes how banked records are *read*, never how they are produced.
* **No re-running to convert wall-stopped records.** Re-running R205's three wall-stopped records
  under a raised `--tl` until they stop on ticks would be escalating until a number improves, and
  it is forbidden here for the same reason Amendment 3's escalation had to be made outcome-blind.
* For the **next** batch: `--det-tl` is the only limit permitted to bind, per Amendment 5.

### 6.8 Falsifier

`analysis/release_gate.py` must fail if any number quoted in the manuscript traces to a record
with `limit_hit == "wall"`. Without that check this amendment is an intention rather than a rule.

### 6.9 THIS AMENDMENT CHANGES THE OUTCOME OF AMENDMENT 5'S REGISTERED PREDICTION

Found while verifying §6.1 against the landed artifacts, **before committing this amendment**, and
recorded here rather than in a later file so that the interaction is visible at the point it was
created. It is the most important paragraph in this amendment.

Amendment 5 registered: *nine of ten cells are escalation-only, so extra budget buys only records
at higher k, which under nesting are expected to be weaker than the incumbent maximum; no
improvement expected.* On R205 the two estimators disagree about whether that held:

| estimator | banked | re-run | Δ |
|---|---|---|---|
| max over all records (Amendment 5's basis) | 1074.85 | 1074.28 | **−0.57** — matched-k drift, no budget effect |
| reproducible only (this amendment) | 1034.38 | **1067.67** | **+33.29** — a real budget effect |

**Both are correct; they measure different things.** R205's banked run stopped on the cell budget
after k=69 with only one det-stopped record (1034.38); its two stronger records were wall-stopped.
The re-run continued to k=70, 71, 72, and all three of those stopped on ticks, the best at 1067.67.

**The mechanism Amendment 5 reasoned about is incomplete, and in a direction that works against
its own prediction.** Higher k drops more customers, so the model is *easier*: it is more likely to
exhaust its tick budget before the wall. Extra budget therefore buys records that are weaker in
true relaxation value but **more likely to be reproducible**. Under a reproducible-only estimator,
extra budget can raise the reported bound on an escalation-only cell — exactly what R205 did.

Registered consequences, before the six unstarted cells land:

* **Amendment 5's prediction is retained as stated and scored on its own basis**, the all-records
  estimator. It is not rewritten to match this finding. On that basis R202 (+0.00), R203 (+0.00)
  and R205 (−0.57) are all consistent with it so far.
* **A second, separate prediction is registered here for the reproducible estimator**: on an
  escalation-only cell, the reproducible bound improves iff the extra budget produces a
  det-stopped record stronger than the banked run's best det-stopped record. Predicted to occur
  where the banked run has **few det-stopped records**, and not where it already has many.
  Per-cell, from the banked `limit_hit` census: improvement predicted for cells whose banked
  reproducible max came from a run with wall-stopped records above it — on present census that is
  **R205 alone** (the only cell of 27 whose max is wall-stopped, §6.5). For the six unstarted
  cells, **no reproducible-estimator improvement is predicted**, because their banked maxima are
  already det-stopped.
* **The denominator stays ten** and neither prediction is scored on a subset.
* **Falsifier:** a reproducible-estimator improvement on any cell whose banked maximum was already
  det-stopped would refute the mechanism above, not merely the word "expected".

This is the second time in two days that a stated mechanism has been found incomplete by measuring
it rather than reasoning about it. Both times the reasoning was directionally plausible and the
artifact disagreed.

---

## AMENDMENT 7 — 2026-09-16. Correcting §6.7 of Amendment 6, which was wrong

Appended rather than edited in place, per the standing rule. Amendment 6 stands as written; this
records what it got wrong and what was actually done.

### 7.1 The error

Amendment 6 §6.7 instructed:

> `analysis/manuscript_numbers.py` imports `lb_estimator` rather than computing a max inline. Any
> inline `max(block_relax)` left in the analysis is a defect once this lands.

**The manuscript was not computing a max.** It was computing `_frontier` — the proven record at the
smallest *k*, falling back to a max only when nothing was proven. Obeying §6.7 literally would have
replaced a different quantity with `cell_bound` and silently changed every n20, n30 and n50 number
in the paper, under an instruction that described the change as a refactor.

I wrote an amendment about estimator discipline while mis-stating the estimator in force. It is
recorded as finding E2 of `validation/AUDIT_estimator_specification.md`.

### 7.2 What was actually done, and under what authority

The author approved the substantive change on 2026-09-16. It is registered in
`validation/DECISION_reported_bound_estimator.md`, not here, because it governs all four sizes and
not only this pre-registration.

* The reported bound is `lb_estimator.cell_bound` — the strongest **reproducible** valid lower
  bound — at every size, replacing `_frontier`.
* The **proved frontier is retained as a separate named quantity**, `lb_estimator.frontier`,
  because it answers a different question and one figure genuinely plots it. It is now requested
  by name (`proved_frontier`) rather than obtained as a side effect of asking for a bound.
* `frontier()` existed in **three files** — `manuscript_numbers.py`, `make_tables.py`,
  `make_figures.py` — identical when written and **already drifted** (`k` versus `kf`) by the time
  anyone compared them. All three now import the one definition.
* `analysis/estimator_audit.py` fails the release gate if a second reduction to a bound appears in
  any paper-producing module. It ships with a negative control and it reported **itself** on its
  first run, which is fixed and recorded in its header.

### 7.3 What moved, measured across the change

| id | before | after |
|---|---|---|
| `ab-crossovers-by-size.n50` | 7 of 27 | **6 of 27** |
| `milp-over-kbk-by-family-n100.R` | 0.242 | 0.241 |
| `n50-ratio-vs-k` | 1.408 | 1.410 |

Nothing else in the registry changed. The n50 crossover count falls because the restriction bound
now beats the arithmetic bound on one more cell — a consequence of no longer discarding valid
records, and it runs **in our favour**, which is why it is named rather than absorbed.

### 7.4 What this does NOT change

* **Amendment 6 itself stands.** The reproducibility filter, its justification, its partial-sight
  disclosure in §6.4 and its uniformity across sizes in §6.5 are all unaffected — the filter was
  never the thing that was wrong.
* **Amendment 5's prediction and Amendment 6 §6.9's second prediction stand as registered**, each
  scored on its own stated basis. Neither is rewritten.
* **The running batch is not reconfigured.** R206 was executing when this was written and was not
  interrupted. Every change here concerns how banked records are read.

---

## AMENDMENT 8 — 2026-09-16, on `ALL TEN DONE`. Two registered predictions are REFUTED

Appended, never edited in place. The batch completed at 09:32:10Z; all ten cells reported
**BUDGET-FREE at 9000 s** and **no cell escalated**, so Amendment 3's escalation branch never
fired and S-B2 does not become blocking.

### 8.1 The primary outcome is confirmed, not moved

| | n50 | n100 | relative drop |
|---|---|---|---|
| banked artifacts | 0.5800 | 0.3192 | 45.0% |
| **budget-free re-run** | 0.5800 | **0.3194** | **44.9%** |

The headline moved by **+0.0002**, because the three movers nearly cancel (R205 +33.29,
R206 +8.03, RC202 −21.33 over 27 cells). **That is the result the batch existed to produce**: the
n100 bound was not budget-limited, so the cross-size degradation is a property of the problem and
not an artifact of unequal budgets.

### 8.2 Amendment 5's prediction — REFUTED

Registered: *nine of ten cells are escalation-only, so extra budget buys only records at higher k,
which under nesting are expected to be weaker than the incumbent maximum; no improvement
expected.* Scored on its own basis, the all-records estimator, over the registered denominator of
ten: **1 improved, 7 unchanged, 2 weaker.** The improver is **R206, +8.03**.

### 8.3 Amendment 6 §6.9's prediction — REFUTED BY ITS OWN FALSIFIER

Registered: on the reproducible estimator, improvement predicted for **R205 alone**, and
explicitly *not* for cells whose banked maximum was already det-stopped. Its falsifier read:

> a reproducible-estimator improvement on any cell whose banked maximum was already det-stopped
> would refute the mechanism above, not merely the word "expected".

**R205 improved by +33.29, exactly as predicted. R206 also improved, by +8.03, and R206's banked
maximum (896.90 at k=68) was det-stopped.** The falsifier has fired. The prediction is not
softened or re-scoped; it is recorded as refuted.

### 8.4 Why both failed, and it was already in our own register

R206's records, banked against re-run:

```
        k=67     k=68     k=69     k=70     k=71     k=72
banked  892.81   896.90   890.96   894.90    --       --
re-run  892.81   896.91   890.96   894.90   891.95   904.93   <- det-stopped, and the maximum
                                            (wall at k=69 in both runs)
```

Extra budget reached k=71 and k=72, and **k=72 is stronger than k=68 — dropping more customers
gave a higher truncated bound.** Both amendments assumed nesting makes higher k weaker. That holds
for PROVEN bounds and fails for TRUNCATED ones: a smaller model travels further up its own
convergence curve inside the same tick budget.

**`n100-truncated-interior-peak` is a STANDING claim stating precisely this** — *"Truncated bounds
have an INTERIOR optimal |H|, not a monotone preference"* — and neither amendment consulted it.
The refutation was available in our own register before either prediction was written. This is the
third time in three days that a reasoned mechanism has lost to a measurement, and the first where
the counter-evidence was already banked and standing.

### 8.5 A silent registry defect the marker exposed

`analysis/manuscript_numbers.py::_cells` excludes any filename containing `_bq`, added in
`13652b4` while Amendment 3 was drafted — a deliberate guard so a half-finished batch could not
contaminate the registry mid-flight. **It was never lifted when the batch completed.** The re-run
wrote `easy_reduction_descend_<cell>_n100_bq9000.json`, so after nine hours of compute every n100
number in the manuscript was still its 2026-09-11 banked value, and nothing failed or warned.

Fixed 2026-09-16: `_recs` now prefers the `_bq9000` artifact where one exists. The enumeration
guard stays, so cells are still counted once. Verified: all ten resolve to their re-run values,
the seventeen untouched cells resolve to their banked files, and both n50 and n100 still enumerate
27 cells.

**The repoint LOWERS one bound and that is correct.** RC202 falls 1572.55 → 1551.22, because its
re-run picked up an extra wall-stopped record under machine load. The banked value is still a
valid lower bound, but it did not come from a budget-free run and so is not the registered
quantity. Taking the weaker number is what this pre-registration requires, and it runs against us.

### 8.6 What is NOT done, and why

`paper/numbers.tex` is **not regenerated**. M6 fired automatically on the marker at 09:32:41Z and
is running; it writes into `runs/` and the registry reads `runs/summary.csv`. Regenerating against
artifacts that are being written is how `runs/n50_final.json` came to disagree with the live set
on 16 of 27 cells. Regeneration, the release gate, and the manuscript rebuild wait for M6. **Until
then every n100 number in `numbers.tex` is stale**, and that is a known, recorded state rather than
a silent one.
