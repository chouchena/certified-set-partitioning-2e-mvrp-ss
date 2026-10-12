# PRE-REGISTRATION — the |C| = 20 street-fleet total, and a two-phase fleet-first variant

2026-09-16. Written before any run. **Nothing launches while M6 holds the machine.**

---

## 1. The question, and the provisional state that motivates it

K's published |C| = 20 street fleet is a mean of **1.59** cars over 27 instances. That mean is
printed to two decimals, and **exactly one integer total is consistent with it: 43** (43/27 =
1.5926 -> 1.59; 42 gives 1.56, 44 gives 1.63). Joint and LBBD both report 1.59, so there is no
comparator ambiguity at this size.

Our own per-cell car counts, assembled from `runs/fleet_subset_infeasibility.json` and the stored
solution set, **provisionally total 42**.

**This is not a result and must not be reported as one.** Of the 27 cells, **14 carry a car count
with no backing solution file**, and four of those claim **one** car:

> **R206, R209, R210, RC204**

Those four carry the entire margin. If one of them is actually a two-car solution the total is 43
and there is no finding; if two are, it is 44 and we are behind. A number that exists only in an
unbacked field is exactly what the R1 re-dump was run to eliminate
(`incumbents-not-artifact-backed`), and `CLAUDE.md` §4 requires witnesses to be recomputed before
anything that looks like a proof is banked.

**So the experiment is not "run 27 cells and hope". It is "re-derive and verify 14 cells, of which
four decide the outcome."**

## 2. The arithmetic, fixed now

| tier | cells | n | cars | status |
|---|---|---|---|---|
| **floor-locked** | C201 C202 C203 C205 C206 C207 | 6 | 2 each = **12** | one car **proven impossible** (`fleet_subset_infeasibility.json`) |
| **backed one-car** | R203 R204 R205 R207 R208 R211 RC203 RC208 | 8 | 1 each = **8** | stored solutions exist |
| **backed two-car, headroom open** | C204 R201 RC202 | 3 | 2 each = **6** | one car NOT excluded |
| **UNBACKED one-car claims** | **R206 R209 R210 RC204** | 4 | 1 each = **4** | **decisive; no solution file** |
| **UNBACKED two-car claims** | C208 R202 RC201 RC205 RC206 RC207 | 6 | 2 each = **12** | no solution file |
| | **total** | **27** | **42** | against K's **43** |

**Primary threshold: a verified 27-cell total of ≤ 42.** Registered before running.

Sensitivity, registered so it cannot be reinterpreted later: the margin is **one car**. The result
survives only if **all four** unbacked one-car claims verify, or if a Tier-3 cell (C204, R201,
RC202) reaches one car and compensates.

## 3. Cell priority — a priori, and outcome-blind by construction

The order below is derived from our **own proven fleet certificate** and from **which files exist**.
Neither depends on any objective value, so it cannot be outcome-driven.

1. **R206, R209, R210, RC204** — decisive. Re-derive and verify first.
2. **C208, R202, RC201, RC205, RC206, RC207** — needed to make a 27-cell total legitimate.
3. **C204, R201, RC202** — the only cells where a one-car solution is neither held nor excluded.
   These are the two-phase variant's real targets and the only source of additional margin.
4. **C201 C202 C203 C205 C206 C207** — excluded from the headroom search. One car is **proven
   impossible**, so they sit at their floor and no search can improve them. They are re-derived
   only to back their two-car counts.

**Prioritising Tier 3 for the variant is a design choice made from a proof, not from results**, and
it is registered here rather than decided after seeing what the re-derivation returns.

## 4. Arms

Both arms, same cells, same seeds, same budget, **interleaved and serial**:

* **baseline** — `fixopt` as shipped.
* **two-phase** — Phase 1 minimises cars (fleet constraint, MIP emphasis 4, **no warm start** from
  a higher-fleet incumbent, per `fixopt.py:414`); Phase 2 warm-starts from the Phase 1 solution
  with `nofCars` **capped at the achieved level** and optimises travel.

Running both is not optional. `CLAUDE.md` §3 states the OV corpus cannot select a variant and that
*"any claim of the form 'variant X is better' needs a fresh paired design, not the corpus."* A
single-arm run would have nothing legitimate to compare against.

**Budget:** `route-drop-zero-for-126-v2` diagnoses the existing fleet-reduction move as failing
from an **~11x resource shortfall, not infeasibility** — 20-40 s at default emphasis against a
measured ~421 s at emphasis 4, and that 421 s was measured at tau = 0, so it is a **lower bound**.
Phase 1 therefore gets **>= 600 s per fleet attempt at emphasis 4**. Registered now so that a later
failure cannot be attributed to budget after the fact.

## 5. Outcomes, fixed in advance

| outcome | reading |
|---|---|
| verified total **<= 42** | K's published |C| = 20 fleet total is **not minimal**. Existence claim; we cannot name which cell, and will not try. |
| verified total **= 43** | tie. Reported as a tie. No claim either way. |
| verified total **>= 44** | our fleet is worse. Reported. |
| **two-phase < baseline on cars**, paired | a variant result, **independent of K** and valid at any size |
| two-phase = baseline on cars | the variant does not move the fleet; reported as a null |

The paired arm comparison is scored **whatever the K comparison does**. They are separate claims
and neither is contingent on the other.

## 6. Adverse audit, written before launch

* **The provisional 42 is the most suspicious number here.** It appeared instantly, from an
  unbacked field, and it beats the target by exactly one. Every prior instance of this shape in
  this project was wrong. It is treated as a hypothesis to be tested, not a finding to be
  confirmed, and §1 says so.
* **Verification asymmetry runs against us and that is deliberate.** Re-derivation can only raise a
  car count relative to an unbacked claim (a cell claiming 1 may turn out to need 2; a cell
  claiming 2 can also reach 1 only if the search finds it). The likelier direction is that the
  total rises above 42.
* **Objective must be recorded for every solution and reported beside the fleet.** Fewer cars
  bought with much worse travel is not a win. R208 already shows the trade-off: one car at 550.356
  against K's 549.9.
* **`fixopt` is wall-clocked** (`primal-harness-blocking-defects` defect 4), so these runs are not
  reproducible in the Amendment 5 sense. That is acceptable **only** because the claim is an
  existence claim backed by published solution files: a reader re-costs the solution rather than
  re-running the search. No mean, and no median-vs-best statistic, may be built on this data.
* **`calib_run.py:81` discards stderr**, so a crashed run writes an empty row indistinguishable
  from a legitimate no-incumbent — the khi_probe fabrication pattern. **Capturing stderr is a
  prerequisite, not a nicety**, because Tier 1's whole question is whether a one-car solution is
  really there.
* **Serial execution** is required: results are attached to runs by file mtime within 2 s
  (defect 3), which binds the wrong run under concurrency.
* **Every solution through `verifier.py`**, which shares no imports with the inherited model. A car
  count read off an unverified solution is worth exactly what the current unbacked fields are worth.

## 7. What may never be claimed from this

* **No per-cell comparison with K.** They publish no per-instance fleet at |C| = 20. The claim is a
  total, and the pigeonhole names no cell.
* **No statement that K erred.** Their objective contains both fleet and travel; a lower-fleet
  solution at equal or worse objective shows the trade-off admits points they did not reach, which
  is a property of the problem and not a mistake of theirs.
* **No extension to n50/n100** from this run. Those totals (100, and 60/95/70 by family) are
  separate targets requiring their own registration.
* **No re-opening of the objective negative.** `ov-median-vs-bestof-gap` stands; this registers a
  fleet claim and a paired variant claim, neither of which is an objective-margin claim.

---

## AMENDMENT 1 — 2026-09-16. Cell-priority rules, and one correction to a premise

Appended, never edited in place. Written before any run.

### A1.1 CORRECTION: there are no per-cell K car counts, at any size

The author asked whether n20 needs the pooled mean at all, given that per-cell data exists there.
**It does need it.** K's Table 3 is per-instance at |C| = 10, 20 and 30, but its only fields are
`joint_bk`, `joint_gap`, `joint_inc_time`, `lbbd_bk`, `lbbd_imp`, `lbbd_inc_time` — **objective,
gap and time. There is no fleet field.** Checked directly against `data/karademir2025/
k_reference.json`; the strings `fleet_sl`, `nCars` and `vehicle` do not occur anywhere in Table 3.

The complete fleet granularity K publishes:

| source | sizes | fleet granularity |
|---|---|---|
| Table 3 | 10, 20, 30 | **none** |
| Table 4 | 10, 20, 50 | **pooled** over 27 instances |
| Table 6 | 100 | **per family** (C / R / RC) |
| — | 30, 40 | **none at any granularity** |

So the author's rule 5 — *adapt to family granularity where per-cell counts are not disclosed* —
**is not a fallback. It is the only available mode**, and true family granularity exists only at
|C| = 100. At n20 and n50 the pooled total is all there is, which is why the pigeonhole over the
27-cell total is the only route to a fleet claim at those sizes.

*(Recorded in passing: `text_facts.proximity` in the same reference gives `{table3: 0.0,
table4: 0.0, table6: 0.1}` — the canonical confirmation of the per-size proximity mapping that
Section 3 of the manuscript was corrected to state on 2026-09-16, previously supported only by a
validation note. And `text_facts.hardware` reads "4 CPUs Intel Xeon Gold 5218", confirming the
four-thread fairness setting.)*

### A1.2 The priority rules, adopted

The author's rules, in force for this and every follow-on fleet run:

1. **Candidate iff reducible-in-principle.** A cell at `d` cars is a candidate only if `d − 1` is
   not proven impossible by the fleet certificate.
2. **Prefer a wide bound gap** — larger `(cars − our certified floor)`.
3. **Prefer a higher car count** — more cars in play.
4. **Where per-cell counts are undisclosed, apply at the coarsest granularity that exists.**

Rules 2 and 3 are **search heuristics, not evidence**. A wide gap does not indicate slack in K's
solution; it indicates that our bound does not exclude slack. That distinction is recorded here so
a wide gap is never later quoted as though it were a measurement.

### A1.3 Applying them at n20, with OUR counts in place of K's

Since no per-cell K count exists, rule 1 is applied to **our own** car count against **our own**
certified floor. That is legitimate and outcome-blind: both quantities are proofs or existing
artifacts, neither is an objective value.

| group | cells | n | cars | rule 1 |
|---|---|---|---|---|
| floor-locked | C201 C202 C203 C205 C206 C207 | 6 | 2 | **excluded** — one car proven impossible |
| at one car already | R203 R204 R205 R207 R208 R211 RC203 RC208 | 8 | 1 | nothing to gain |
| **unbacked one-car claims — AT RISK** | **R206 R209 R210 RC204** | 4 | 1 | each may revert to 2 |
| **HEADROOM — the search targets** | **C204 C208 R201 R202 RC201 RC202 RC205 RC206 RC207** | **9** | 2 | one car each is not excluded |

**This supersedes §3's Tier 3, which listed only C204, R201 and RC202.** That restriction was an
error of mine: I limited headroom to cells with a *backed* solution, but an unbacked two-car cell is
an equally valid target once re-derived — the backing status governs whether a count may be
**quoted**, not whether a cell may be **searched**.

### A1.4 The corrected arithmetic, and it is much better than §2 implied

```
floor-locked      6 x 2 = 12      (cannot improve)
at one car        8 x 1 =  8      (cannot improve)
at-risk           4 x 1 =  4      (can only worsen, to 8)
headroom          9 x 2 = 18      (can improve, to 9)
                        -------
current total            42       against K's 43
best case                33       all 9 headroom cells reach one car
worst case               46       all 4 at-risk cells revert
```

**The nine headroom cells are insurance against the four at-risk cells.** §2 stated that the result
"survives only if all four unbacked one-car claims verify". **That was wrong** — one headroom
success offsets one at-risk reversion exactly. The primary threshold of ≤ 42 is unchanged; what
changes is that it no longer rests on four numbers all holding.

### A1.5 Applying the rules at n100 — and this REVERSES my earlier recommendation

| family | K cars | our floor | gap (rule 2) | K cars (rule 3) |
|---|---|---|---|---|
| C | 7.50 | 5.00 | 2.50 — **last** | 7.50 — **last** |
| R | 8.64 | 2.09 | **6.55 — first** | 8.64 — second |
| RC | 8.75 | 2.62 | 6.12 — second | **8.75 — first** |

Rule 1 excludes nothing: every family's floor is far below `K − 1`.

**Both rules rank C last. I previously recommended C first, and the author's rules are right.** My
reason for C was that our bound is credible there (its floor scales with size, 1→2→3→5, where R and
RC sit near 2 from n20 onward) — so the *interval* is interpretable. But interval interpretability
matters for a **bound** claim. This is a **primal existence search**, and whether a car is removable
has nothing to do with whether our lower bound is tight. R and RC have more cars in play and
nothing excluded, so they are the better hunting ground.

**n100 order is therefore R, then RC, then C** — reversing §3's staging, which is superseded for
any n100 follow-on.

### A1.6 What does not change

The primary threshold (≤ 42), the paired two-arm design, the ≥ 600 s emphasis-4 Phase 1 budget, the
verification requirements, and every item in §6 and §7 stand as written.
