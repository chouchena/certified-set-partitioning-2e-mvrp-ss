# PREREG S3a — does the RETAINED-SET POLICY earn its place? Written BEFORE the run.

2026-09-14. **This is the experiment that decides the venue**, not just the framing. Both independent
venue reviews converged on the same requirement, from different evidence:

> *"Can an editor delete every mention of Karademir et al. from the abstract and still identify a
> reusable methodological contribution?"* (review A)
> *"Reviewers may still ask 'why does this need a new paper' absent a procedural novelty story."*
> (review B)

The bound's validity argument is elementary and both reviews say so. **The only place novelty can
live is the procedure** — how the retained set H is selected, how its size is scheduled, and the warm
descent. If those components do not measurably matter, there is no procedure to claim, and the
target drops from C&OR to AOR.

## 1. THE QUESTION

Our shipped policy drops the **k easiest** customers, ranked by an easiness score over scarcity
weights. Does that ranking do any work, or would any subset of the same size do?

## 2. ARMS

| arm | `--selection` | status |
|-----|---------------|--------|
| **easiness** | shipped policy | **ALREADY BANKED** — 27/27 artifacts, no rerun |
| **random** | uniform shuffle, seeded | to run |
| **reverse** | drop the HARDEST first — adversarial | to run |

`reverse` matters: random is a weak control that could look bad by luck, while reverse is the
strongest available adversary. If easiness beats random but ties reverse, the ranking is doing
something other than what we claim.

## 3. PROTOCOL — identical to the banked baseline, verified

All 27 banked artifacts share one protocol; the arms use exactly it:

    k_hi 9   k_cap 14   tl 1800   cell_budget 5400   det_tl 653400
    seed 20260910   threads 4   proximity 0.0   bounder cplex   tau formula

* **Complete grid, 27 cells, no selection.** This project has had two selection-bias errors; a
  subset here would invite a third.
* **STRICTLY SEQUENTIAL.** The machine has 8 logical cores and each arm uses 4. Two concurrent arms
  would contend and corrupt every wall time in both — which is exactly what happened earlier today
  when a probe ran alongside S2t.
* **Artifacts to distinct paths** (`crossfeed/ablation_<arm>_<cell>_n20.json`). The descent's
  overwrite guard refuses to clobber, but distinct paths mean it never has to.

## 4. PRIMARY OUTCOME — exact, and budget-independent

**Compare `block_relax` at the LARGEST k that BOTH arms prove.**

A *proven* record is an exact optimum of the sub-instance, so it does **not** depend on the time
limit, the machine, or load. That makes the comparison immune to every timing artifact that has
bitten this project. Unproven records are reported but carry no weight.

Secondary: the deepest k each arm reaches, and `det_ticks` to reach it (machine-independent cost).
Wall time is recorded but explicitly **not** a primary measure.

## 5. PRE-COMMITTED DECISION RULE

Let `w` = cells where easiness gives a strictly better proven bound than the arm, `l` = worse,
over the cells where both prove.

| outcome | reading | consequence |
|---------|---------|-------------|
| easiness beats **random** on >= 70% of comparable cells, with a material mean margin | the selection policy is doing real work | **the procedure is the contribution. Target C&OR.** |
| easiness beats random but **ties or loses to reverse** | the ranking direction is not what makes it work — size or structure is | report honestly; the claim becomes weaker and more specific |
| easiness ties random (within noise) | **any subset of that size would do.** There is no selection contribution | **target AOR**; drop selection from the novelty claim entirely |
| easiness loses to random | our policy is actively harmful | a finding against us; report it and fix the policy |

**No threshold is chosen after seeing data.** The 70% figure is set now because the comparison is
deterministic — there is no sampling noise to argue about afterwards.

## 6. ADVERSE AUDIT

1. **A single smoke point already exists and favours us** — C203 at k=9, both proven,
   easiness 601.04 vs random 364.05 (random 39% weaker). **That is n=1 and must not anchor the
   reading.** Three of today's five retractions came from generalising off one cell.
2. **`random` is one draw.** With a fixed seed there is exactly one random ordering per cell, not a
   distribution. A fair test would average several draws; we run one, which is a real limitation and
   will be stated. `reverse` partly compensates by being adversarial rather than lucky.
3. **Cells where neither arm proves anything** contribute nothing and must not be silently dropped
   from the denominator.
4. **Deeper k is not automatically better** — a truncated bound at low k can beat a proven bound at
   high k. Compare at matched k, which is why the primary outcome is defined that way.
5. **This cannot rescue the inequality's novelty.** Even a decisive result makes the *procedure* the
   contribution; the bound remains elementary, exactly as both reviews say.

## 7. COST

One arm over 27 cells measured at **7.16 h** from the banked artifacts (mean 955 s/cell). Two arms,
sequential: **~14.3 h**.

**Nothing else runs while this does.**

---

# AMENDMENT 1 — 2026-09-14T20:3x UTC, written after 1 of 54 cells (a tie) and BEFORE any
# informative result. Two defects in the section-4/5 design, both found by inspection.

## A. The primary outcome was stated BACKWARDS

Section 4 said *"compare `block_relax` at the LARGEST k that BOTH arms prove"*. That is wrong.
`block_relax` is monotone **DECREASING** in k — k is the number of customers DROPPED, so a larger
k means a smaller retained set H and a **weaker** bound. The descent's own header states it:
`argmax_k [block_relax(k) : proven] == smallest provable k`. Comparing at the largest common k
would have compared the two arms' **weakest** bounds and thrown away the quantity the method
actually reports.

**Corrected primary outcome — the frontier bound.** For each arm, the reported output is
`block_relax` at its **frontier** = the SMALLEST k it can prove within budget. Compare arms on that.
It is the right measure because it captures both halves of the policy's merit at once: a better
retained-set policy should prove a **smaller** k (keep more customers) **and** therefore return a
**stronger** bound.

**Corrected secondary — matched-k.** `block_relax` at the smallest k that BOTH arms prove. This
controls for depth and isolates bound quality from reach. Reported alongside, not instead.

Monotonicity is not at risk in the ablation arms: for ANY fixed order, `H_k = C \ order[:k]` is
nested (`H_k` subset of `H_{k-1}`), so the decreasing property is order-independent and holds within
each arm separately.

## B. Six cells are TIED BY CONSTRUCTION and must leave the denominator

At k=0 the drop set is empty, so H is the **entire** customer set and `z_A(H)` does not depend on the
ordering at all. Every arm returns an identical bound, necessarily. These cells carry **zero**
information about the selection policy, and counting them as "ties" would silently dilute the
measured effect toward the null.

Confirmed empirically on the first completed cell: C201, easiness and random both frontier k=0,
both `block_relax = 684.62`, exactly equal.

From the banked baseline, the frontier-k=0 cells are:

    C201  C205  C206  C208  R201  RC201        (6 cells -- EXCLUDED, tied by construction)

leaving **21 informative cells** (frontier k >= 1) as the pre-committed denominator:

    C202 C203 C204 C207 R202 R203 R204 R205 R206 R207 R208 R209 R210 R211
    RC202 RC203 RC204 RC205 RC206 RC207 RC208

All 27 are still RUN — the 6 cost ~2 s each and their exact tie is itself a reported check that the
harness is sound. They are excluded from the **denominator**, not from the record.

**Caveat, pre-committed:** exclusion is defined by the BANKED arm's frontier. If an ablation arm
fails to reach k=0 on one of those 6, that is a real difference in REACH and will be reported as
such — it does not get quietly absorbed by the exclusion rule.

## C. The section-5 threshold is unchanged

The 70% rule now applies over the 21 informative cells, on the corrected frontier-bound measure. The
threshold itself is NOT revised — revising a threshold after seeing even one cell is exactly the
practice this register exists to prevent.

---

# AMENDMENT 2 — 2026-09-15. Limitation #1 was stated wrongly and is SUPERSEDED.

Section 6 item 2 conceded that *"`random` is one draw. With a fixed seed there is exactly one random
ordering per cell, not a distribution. A fair test would average several draws; we run one, which is
a real limitation."*

**That concession is incorrect, and conceding it invites a criticism that does not apply.** The
replication unit is the **cell**, not the seed. Under the null that the easiness score has no merit,
easiness and a uniformly random ordering are exchangeable on each cell, so `P(easiness wins) = 1/2`
there and each cell is one valid Bernoulli trial. One draw per cell is a correctly specified
**paired randomisation test across 21 instances** — the standard design (Demsar 2006), already used
in this project for the primal Wilcoxon. Extra seeds buy precision and power; they cannot buy a
validity that is not missing.

Measured on the complete `random` arm (`analysis/s3a_significance.py`): exact sign test
**p = 0.0036**; exact Wilcoxon signed-rank on log frontier ratios **W+ = 217, W- = 14, z = -3.53,
p = 0.000052**. The rule tolerates **2 flips**, only 2 cells sit within a 1% margin, and **13 of 21
sit at margins >= 5%** that reseeding cannot move.

**The threshold is NOT revised** — this amendment changes how the design is *described*, not what
counts as success. The 70% rule and the 21-cell denominator stand exactly as pre-committed.

**The caveat that survives:** cells within a family (C/R/RC) share structure, so independence across
the 21 is imperfect — the same limitation Demsar's framework carries, disclosed identically for the
primal comparison.

**Decision on compute:** do NOT run a full distribution. A targeted 3-4 extra draws on the six
sub-5% cells (~6-8 h) remains available as optional pre-emption, not remediation.
