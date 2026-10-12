# PREREG M6 — the matched-budget reproduction of K's LBBD. Written BEFORE it runs.

2026-09-16, written while the n100 budget equalisation is on cell 7 of 10. **M6 is already armed**:
`run_m6_after_n100.sh` waits on a file marker and fires unattended when that batch writes
`ALL TEN DONE`, roughly three hours from now. This file exists because it would otherwise have
fired with no outcome, threshold or denominator fixed in advance.

**Found by an adverse audit, not by the checklist.** `grep -l M6 validation/PREREG_*.md` returns
nothing across 22 pre-registrations. The run was designed, armed and chained without one.

---

## 1. What M6 is, and why it is not optional

`analysis/rt_fair_pipeline.py` re-runs the 12 n20 reproduction cells that back the STANDING claim
`beats-both-k-bounds-v2`:

> *n20, 12 cells: mean 1.58× vs Joint, 1.59× vs reproduced LBBD; 11/12 wins vs LBBD, sole loss
> RC201 0.99× on a cell K proves optimal.*

That claim currently rests on a comparator we ourselves call unfair. The existing reproduction gave
K's LBBD **900 s at 8 threads**; 13 of 13 such runs converged 0 of 13 and 11 hit the time limit,
and `analysis/rt_normalize.py` states plainly that a time-limited reproduction *"must not be
presented as K's method on our machine"*. Most managed three master solves in 900 s against K's own
n20 LBBD average of 9192 s.

M6 gives each cell **1.5 × K's own per-cell IncT** (floor 900 s, cap 5400 s) at **4 threads**,
which is K's own four CPUs. That is a fairness correction to our own comparator, not a new
experiment — and it is owed regardless of which way it moves.

## 2. The direction is genuinely two-sided, which is exactly when a threshold must be fixed first

This is not a run whose result we can predict:

* on cells where K's IncT is **low** (as little as 168 s) the budget stays at the 900 s floor while
  the thread count **halves**, 8 → 4. Those cells get a *weaker* comparator and our margin **grows**;
* on cells where K's IncT is **high**, 1.5 × IncT is up to a six-fold increase. Those cells get a
  *stronger* comparator and our margin **shrinks**.

Both directions are live within the same 12-cell arm, and the aggregate could move either way.

## 3. Primary outcome — fixed now, before any M6 cell runs

**The mean ratio of our bound to the matched-budget reproduced LBBD bound, over the same 12 cells,
and the win count out of 12.** Denominator **12**, fixed here, and not to be recomputed over a
subset chosen after seeing results.

Reported against the current values — **1.59× and 11 of 12** — with both the old and new comparator
settings printed beside them (900 s / 8 threads versus 1.5 × IncT / 4 threads).

**Secondary, and re-derived rather than re-decided:** any manuscript sentence citing
`beats-both-k-bounds-v2`. It moves mechanically if the primary moves.

## 4. The commitment `RT_COMPARABILITY.md` §8.4 asks for, given explicitly

> *"If the matched-budget result is unflattering at some size, it ships anyway — confirm that
> before running it, not after."*

**Confirmed. It ships anyway.** Concretely, and so that this cannot be softened later:

* **If the mean ratio falls below 1.0**, the claim that our bound beats their reproduced LBBD is
  **retracted** and reported as retracted, naming M6 as the cause.
* **If the win count falls below 7 of 12**, the "11 of 12" phrasing is withdrawn and replaced by
  the measured count, whatever it is.
* **If the result is mixed by cell**, the per-cell table is reported in full. No subset is selected.
* **The fairer comparator supersedes the unfair one in all cases.** We do not keep the flattering
  900 s number on the grounds that it was measured first. `beats-both-k-bounds-v2` is superseded by
  the M6 result whichever way it goes.

**A worse number is the expected price of a fair comparison, and paying it is the point.** Our own
`rt_normalize.py` already forbids presenting the time-limited reproduction as their method; having
said so, we cannot then prefer its output because it flatters us.

## 5. What must NOT happen

* **No re-tuning of the budget rule after seeing results.** `min(5400, max(900, 1.5 × IncT))` is
  fixed here. If it produces an uncomfortable number, that is the number.
* **No dropping of RC201.** It is the existing sole loss, on a cell K prove optimal, and it stays in
  the denominator.
* **No comparison against the 900 s reproduction as though both were valid.** One supersedes the
  other; they are not two measurements of the same thing.
* **No claim that the reproduction IS K's method.** Even at 1.5 × IncT it is our re-implementation
  on our hardware, and `rt_normalize.py`'s caution survives M6 in full.

## 6. Adverse audit

1. **A pre-registration may be the wrong instrument.** M6 corrects a comparator we already concede
   is unfair; formalising a methodological fix as a hypothesis test can read as defensive. The
   answer is that §3's numbers *are* in the manuscript and *will* move — and once a number can
   move, the register's rules apply whatever we call the run.
2. **1.5× is a choice.** Not 1.0×, not 2×. It was chosen to exceed K's own incumbent time with
   headroom while staying inside a night's compute; the cap of 5400 s and floor of 900 s are the
   practical bounds. It is recorded as a choice rather than defended as optimal, and the per-cell
   budget is reported so a reader can see it.
3. **12 cells, not 27.** The arm is the existing reproduction set; extending it is a different and
   larger run. Every ratio must therefore be reported as "12 of 27 n20 cells", never as a grid
   result.
4. **4 threads is K's hardware, not ours.** Matching their CPU count makes the comparator fair to
   them and slightly unfair to us on a machine with more cores. That asymmetry is deliberate and
   runs against us, which is the right direction for a comparison we are reporting.

## 7. Gate

M6 fires automatically on `ALL TEN DONE`. **This file must be committed before that marker is
written.** If it is not, the waiter is to be disarmed and M6 relaunched afterwards — the running
batch is never stopped for it.
