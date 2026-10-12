# PREREG M7 — the matched-budget reproduction at |C| = 30. Written BEFORE it runs.

2026-09-16, 23:55. Nothing of M7 has been run. `analysis/rt_fair_pipeline.py` is parameterised and
committed (`aeae50d`) but has never been invoked at `--size 30`.

---

## 1. Why this run exists

It is the **registered falsifier of a STANDING claim**. `beats-both-k-bounds-v3` carries:

> *"An LBBD reproduction at |C|=30 or |C|=100 at matched budget where our margin against the
> reproduced LBBD bound collapses relative to our margin against the published Joint bound."*

`python analysis/claims.py check` currently lists it under **FALSIFIER-NOT-RUN**. A claim whose
falsifier is never executed is a claim the register cannot defend, and this one supports the
paper's central dual-bound comparison.

## 2. Arm, fixed here

**The same 12 instance ids as M6, one size up**: C203, C204, R203, R204, R207, R208, R211, RC201,
RC202, RC203, RC204, RC208. All twelve have a K per-instance row at |C| = 30 and a descend
artifact.

That criterion is **mechanical and pre-existing** — the same instances, not a selection on |C| = 30
outcomes — and it makes the n20/n30 comparison **paired**, which a fresh 12 would not.

**Rejected alternatives, recorded so the choice is not re-litigated favourably later:**

* *the cheapest 12 of 27 by IncT* (6.5 h) — runtime correlates with instance difficulty, so
  selecting on it biases the arm toward easy cells. This is the "dressing a choice as a
  constraint" failure already in `CLAUDE.md` §4.
* *all 27* (27.6 h, 10 cells at the cap) — unbiased and preferable on the merits, but it is twice
  the compute and the paired 12 answers the falsifier. Recorded as the better run we did not do.

**Budget follows M6 unchanged**: `min(5400, max(900, 1.5 × K's own per-cell LBBD IncT))`, 4
threads. Unchanged *so the two arms are comparable*; re-tuning it at n30 would make the sizes
incommensurable. **14.0 h**, 5 of 12 cells at the 5400 s cap.

## 3. Primary outcome — fixed now

The falsifier is about a **relative** collapse, so the outcome is a pair, over the 12 cells,
denominator 12:

* `R_lbbd` = mean ratio of our bound to the matched-budget reproduced LBBD bound;
* `R_joint` = mean ratio of our bound to K's published Joint dual bound.

**The claim is REFUTED if `R_lbbd / R_joint < 0.85`** at |C| = 30.

At |C| = 20 that quantity is `1.586 / 1.58 = 1.004`. The threshold of 0.85 is **a choice**, not a
derivation, and is recorded as one: a 15 % relative shortfall would mean the margin genuinely
depends on which comparator is used, which is exactly what the attack v3 defends against asserts.
Anything smaller is not distinguishable from noise in a 12-cell mean.

**Secondary, reported regardless of the primary:** the status distribution and the master-solve
counts. M6 found the reproduced bound *insensitive to budget* at n20 (1.3×–11× more master solves,
mean ratio moved 0.004). Whether that survives at n30 is the interesting question and it is **not**
predictable from M6 — n30 instances are harder and the decomposition may be in a different regime.

## 4. Committed before seeing anything

* **If `R_lbbd / R_joint < 0.85`, `beats-both-k-bounds-v3` is RETRACTED**, naming M7, and the
  manuscript's dual-results subsection is rewritten to report the collapse.
* **If the arm does not complete all 12**, it is reported as INCOMPLETE and **not scored**. The
  denominator is 12 and no subset is substituted — `analysis/m6_score.py` already refuses partial
  sets and the M7 scorer will inherit that.
* **No re-tuning of the budget rule after seeing results.** It is M6's rule, fixed above.
* **No dropping of RC201**, which is the sole n20 loss and stays in the n30 denominator too.
* **This is a fresh arm**: no |C| = 30 LBBD reproduction exists, so nothing is overwritten. The
  backup added in `aeae50d` will report "none present -- fresh arm", which is the expected and
  correct message.

## 5. Adverse audit

1. **The threshold is chosen, not derived.** Stated in §3. The alternative — no threshold — is
   worse, because then any n30 result could be described after the fact as consistent with the
   claim.
2. **12 of 27, at one size.** Every figure must be reported as "12 of 27 cells at |C| = 30", never
   as a grid result — the same constraint M6 carries.
3. **The comparator is still ours.** M7 inherits every caveat of M6: it is our re-implementation,
   on our hardware, and if it again converges 0 of 12 then `rt_normalize.py`'s caution that a
   time-limited reproduction is not "K's method on our machine" applies unchanged.
4. **14 hours is a real commitment** and the machine is otherwise idle overnight, which is the
   only reason the paired 12 is preferred over a smaller, biased arm.
5. **A favourable result proves less than it appears to.** If the margin holds, that is the
   *absence* of a refutation, and the register requires it be written as "not refuted", never as
   "confirmed" or "validated".
