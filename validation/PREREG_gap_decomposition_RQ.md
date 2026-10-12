# Pre-registration: the research question, and whether it survives an a-priori test

Written 2026-09-12, **before any primal run at n30/n50/n100**. Records the order of events
honestly and states what may and may not be claimed as design rather than observation.

**User decision:** a post-hoc framing is acceptable *if and only if* the choice can be assessed
as an a-priori research question. This document runs that assessment adversarially and reports
the verdict, including the parts that FAIL and must be discarded.

---

## 1. The disclosure — what actually happened, in order

1. K's paper published 2025. Table 3 reports, per instance, whether their 4-hour run closed.
2. We ran the dual leg at n20/n30/n50/n100 and the primal leg at n20 only.
3. **2026-09-12**: measuring primal wins against K's BK, we noticed wins sit on cells K did not
   close and ties on cells K proved.
4. Only then was "target the unproved regime" proposed as a direction.

**Step 4 came after step 3.** That is the post-hoc part and it is disclosed, not hidden.
The question this document settles is whether the *justification* depends on step 3.

## 2. The test — three criteria a choice must pass to count as a-priori

A design choice is a-priori if it is derivable from information available before the
experiments, does not use our measurements in its own definition, and would have been made
identically had our results come out differently.

### Candidate A — partition cells by whether K PROVED optimality

| criterion | verdict | why |
|---|---|---|
| **derivable before our runs?** | **PASS** | K's Table 3 gap column is published. The 8/4/42 split (proved / near / unproved across n20+n30) was readable the day the paper appeared. |
| **independent of our measurements?** | **PASS** | Not one of our numbers enters the definition. The partition is entirely a property of K's experiment — their model, their 4-hour limit, their hardware. |
| **invariant to how our results came out?** | **PASS, and decisively** | On a proved cell, K's BK *is* the optimum, so a tie is the mathematical ceiling **for any method whatsoever**. That is true whether our solver is excellent or terrible. Had our OV been poor, the partition would be identical and only our score inside it would change. |

**Candidate A passes all three.** It is an a-priori partition that we happened to notice late.
Noticing late does not make it post-hoc; *depending on the observation* would, and it does not.

**Supporting a-priori grounds, none of which use our data:**

* It is the **default protocol of the field** — heuristic papers are routinely assessed as
  *match where optima are known, improve where exact methods do not close*. A referee will not
  read this as a choice at all, but as the expected structure.
* **K name the direction themselves** (section 6): *"LBBD has the potential to facilitate the
  development of further heuristics... future studies can exploit the underlying decomposition
  structures to develop metaheuristics."* Same move as the C7 finding — answering a question
  they posed.
* K built the partition into their own artifact by reporting per-cell proof status.

### Candidate B — partition at a gap threshold of 31%

| criterion | verdict |
|---|---|
| derivable before our runs? | **FAIL** — 31% is where *our* AB happened to stop beating their bound |
| independent of our measurements? | **FAIL** |
| invariant to our results? | **FAIL** |

**DISCARDED. The number 31% must not appear as a design parameter anywhere in the manuscript.**
It may appear once, as a *description* of where the C7 effect was observed, and never as a
criterion that selects anything.

## 3. The research question, stated a-priori

The a-priori form is not "where can our heuristic win". It is a question about K's published
table that could have been written the day the paper was read:

> K report a gap that grows with instance size — 0% at |C|=10, 26.2% at 20, 43.0% at 30,
> 58.0% at 50, and 60-77% at 100. **A gap has two sides. How much of it is dual-side slack,
> and how much is primal-side slack?**

This single question governs **both legs**, which is why they belong in one paper:

* **dual side** — a stronger lower bound closes the part of the gap that was bound weakness
  (the B1 refinement; C7 is its sharpest instance);
* **primal side** — a metaheuristic improving on their incumbent closes the part that was
  incumbent weakness.

The proof-status partition then **falls out of the question rather than being imposed on it**:
where K's gap is zero there is no slack on either side, so those cells cannot answer the
question and instead serve as the validation set. Nothing is selected; the arms are implied.

This is already the framing in `paper/FRAMING_broaden_refine.md` B1 ("A gap has two sides").
The primal leg is the second half of a decomposition we had already committed to — not a
separate contribution needing separate justification.

## 4. The three arms, and what each can claim

| arm | cells (n20+n30) | ceiling | claim permitted |
|---|---|---|---|
| **PROVED** | 8 | tie — fixed by arithmetic for every method | **NO contribution.** Pass/fail validation only. Currently 2/2 exact ties. |
| **NEAR** (0 < gap <= 10%) | 4 — R209 n20; C205, C206, R201 n30 | small but nonzero | the **falsification arm**. Improvement is possible and hard. Must be reported even when unflattering. |
| **UNPROVED** | 42 | open | the contribution zone. Claim rests on the **median** run, not best-of. |

**The PROVED arm is load-bearing, not a concession.** It is the only place a referee can check
us against ground truth. Claiming only where nobody can verify is the real exposure; this arm
answers it. That makes **n10 the cheapest credibility available** — K prove all 27 cells there
(*"LBBD converges within 1% of the optimal values"*), taking the validation set from 8 to ~35
for roughly 3 hours.

## 5. What this does NOT license — the parts that stay post-hoc

1. **"Our advantage concentrates in the loose regime" is NOT a finding.** It is substantially
   arithmetic: AB <= optimum by validity, and on a proved cell K's bound equals the optimum, so
   AB *cannot* beat it there. The same holds on the primal side — K's BK is the optimum on a
   proved cell, so nobody beats it. Presenting the localisation as convergent empirical evidence
   from two independent legs would be an overclaim. **State it as forced, then move on.**
2. **Direction is not selection.** All 27 cells per size get reported, including the R203 and
   R208 losses and every tie.
3. **Run-count imbalance is ours, not design.** Existing cells carry 4 to 37 runs. The reported
   comparison must use one frozen configuration and an equal budget on every cell, or the
   OneAlgo claim fails. Calibrating on target cells is legitimate; reporting only on them is not.
4. **Magnitudes are results, never justification.** The -4.70% mean in the unproved arm is
   reported as an outcome; it is not evidence that the partition was well chosen.

## 6. The pre-registered prediction, testable out of sample

Primal runs at **n30, n50 and n100 have not happened**, so they are genuinely held out.
Registered now, before them:

* **P1** — in the PROVED arm, the frozen configuration matches K's optimum on **>= 90%** of
  cells. Failure here is a reliability finding against us and gets reported as one.
* **P2** — in the UNPROVED arm, the **median** run beats K's BK on more cells than it loses.
  *(Current n20 evidence: 5/12 on the median against 9/12 best-of. P2 is NOT currently met, and
  that is the honest baseline this prediction is measured against.)*
* **P3** — the NEAR arm behaves between the two. If it tracks the PROVED arm, the direction is
  about proof status; if it tracks UNPROVED, it is about difficulty. **Either outcome is
  reportable and we do not have a preferred one.**

**P2 is the binding one.** A claim to work where exact methods fail requires reliability, not a
best-of statistic. On present evidence it fails, which is why variance reduction ranks ahead of
target selection in the OV programme.

## 7. Verdict

**The direction can be stated as an a-priori research choice.** Candidate A passes all three
criteria, is the field's default protocol, and is named as future work by K themselves. The
research question in section 3 is answerable from K's published table alone and needs none of
our results to be posed.

**Conditions carried:** section 5 items 1-4 and the section 6 predictions. The 31% threshold is
discarded. The order of events in section 1 is disclosed in the manuscript's experimental
design, not buried.

---

## AMENDMENT 1 — 2026-09-16. P2's out-of-sample sizes were abandoned, and this file never said so

Appended after an adverse audit found that this pre-registration carried **no amendment of any kind**
while the prediction it registers had been substantially re-scoped elsewhere. CLAUDE.md §2 requires
amendments to be appended here and dated; that did not happen, and the audit trail was broken for
two days.

### 1.1 What §6 registered

> Primal runs at **n30, n50 and n100 have not happened**, so they are genuinely held out.

P2 was registered against those three sizes. That "genuinely held out" is the whole evidential value
of the registration: a prediction tested on data that did not exist when it was written.

### 1.2 What actually happened

* `validation/PREREG_S2g_p2_coverage.md` re-framed P2 as an **n20** prediction and scored it there.
* The claim `primal-coverage-scoped-to-n20` records that n30/n50/n100 are **skipped**, on four
  grounds: the venue review says not to run the n30 primal under an LB-first framing; the primal is
  already a negative and extending a negative cannot change it; `primal-margin-decays-dual-improves-
  with-size` predicts it worsens with size; and the cost is prohibitive.
* Measured coverage: n10 26/27, n20 27/27, **n30 5/27, n50 2/27, n100 0/27**.

Those grounds are defensible and the decision is not reopened here. **What was missing is that this
file, where the commitment was made, never recorded it.**

### 1.3 Registered now

* **P2 is scored at n20 only**, on the complete 20-cell unproved arm, per
  `PREREG_S2g_p2_coverage.md` and its Amendment 1 of 2026-09-16.
* **The out-of-sample property registered in §6 is therefore NOT claimed.** P2 was scored on the one
  size where primal data already existed when it was re-framed. Any description of P2 as an
  out-of-sample test is withdrawn, and the manuscript must not describe it as one.
* **Every primal claim carries its size scope**, per `primal-coverage-scoped-to-n20`, whose
  falsifier is *"a primal claim in the manuscript that implies coverage at a size where fewer than
  27 cells were run"*. n30 primal rests on 5 of 27 cells and is a selection, not a grid.

### 1.4 P3 has no result and is not quietly dropped

P3, the NEAR arm, has no result document and no claim-register entry. It is recorded here as
**UNSCORED**, not as passed or failed. Related: `analysis/p2_full_arm.py` selects the arm by
`joint_gap > 0`, which folds the NEAR cell **R209** into the UNPROVED arm, contrary to the three-arm
table in §6 of this file. R209 is scored as a TIE in the n20 tally either way, so no reported number
moves — but the arm definition in the code does not match the arm definition here, and that is
recorded rather than silently tolerated.

### 1.5 The honest summary for the manuscript

P1 and P2 were registered as out-of-sample predictions across three unrun sizes. Those sizes were
not run, for reasons recorded and defensible. **P2 was scored in-sample at n20 and failed.** The
failure is reported; the out-of-sample framing is not.
