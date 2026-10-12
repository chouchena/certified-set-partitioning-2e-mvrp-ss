# S2k — can our bound close a cell K left open? Pre-registered 2026-09-14, BEFORE any run

## 1. The question

K report optimality gaps of 36–65% on the unproved n20 cells after a 4-hour exact solve. Our
lower bound is calibrated at **2.1% from the optimum** where the optimum is known
([[FINDING_bound_calibration_and_real_headroom]]), and our incumbents are verifier-certified.

So for each cell we hold a far narrower interval than K attacked:

| cell | K's interval | width | our interval | width | ratio |
|------|--------------|-------|--------------|-------|-------|
| C202 | [529.4, 678.7] | 149.3 | [663.1, 678.7] | **15.5** | 9.6x narrower |
| C203 | [314.0, 676.3] | 362.3 | [648.2, 673.7] | **25.5** | 14.2x narrower |
| R202 | [721.2, 756.7] *(K dual 613.2)* | 143.5 | [721.2, 756.7] | **35.5** | 4.0x narrower |

**Question: handed that interval, does an exact solver close the cell?** A closed cell is an
optimum proved where K could not prove one — a categorically stronger result than a margin.

## 2. Design — PAIRED, with the control that makes it interpretable

For each cell, two arms on the same solver, same machine, same time limit:

* **Arm B (bound-injected):** build K's joint model and add the constraint `zObj >= our_LB`.
  **Nothing else.**
* **Arm C (control):** identical, without `zObj >= our_LB`.

**REVISED 2026-09-14, before any run.** The first draft also supplied our incumbent as a MIP
start in Arm B. Dropped, for attribution: a warm start would conflate the quality of our DUAL
bound with the quality of our PRIMAL incumbent, and a closure could then be credited to either.
Arm B now isolates exactly one thing -- the lower bound, which is the leg closing 73.7% of K's
gap and the stronger of the two. It also removes the need to map our dumped solution format onto
docplex MIP-start variables, which was an untested code path.

The cost is that Arm B is now a HARDER test than it needed to be: it must close the cell without
the benefit of our incumbent. If it closes anyway, the attribution is unambiguous.

`zObj >= our_LB` is a **valid** constraint: our LB is a proven lower bound, so it cannot exclude
the optimum. It raises the root LP bound directly, which is the quantity branch-and-bound prunes
on.

* Cells: **C202, C203, R202** — the three narrowest windows.
* Time limit **3600 s** per arm, MIP gap 0, threads 4.
* 3 cells x 2 arms x 3600 s = **6 h**.

## 3. Why the control arm is non-negotiable

We would run Gurobi 13.0.3 (or CPLEX 22.1.1) against K's published Gurobi 9.12 results. **If a
cell closes in Arm B, that alone does not show our bound did the work** — four major solver
generations could have. Arm C isolates it:

| outcome | reading |
|---------|---------|
| B closes, C does not | **our bound closed the cell.** The strong result. |
| B and C both close | the modern solver closed it; our bound is not needed. Honest, still publishable as "these cells are closable today", but it is NOT our contribution. |
| neither closes | no closure. Report the narrowed interval instead. |
| C closes, B does not | a bug in the injection. Investigate before anything else. |

## 4. Registered predictions

* C202 (2.3% window, our incumbent equals K's published BK) is the **most likely** to close.
* R202 is the least likely of the three despite a 4.7% window, because its absolute width (35.5)
  is the largest.
* I do **not** predict closure on all three, and a null on all three is a real possibility that
  gets reported as one.

## 5. ADVERSE AUDIT

1. **Cell selection is on a pre-measured quantity.** C202/C203/R202 were chosen for narrow
   windows, measured before this run and declared here. That is legitimate, but it means any
   closure rate must be reported as "3 cells chosen for narrow windows", never as a grid rate.
2. **Narrow windows do not guarantee closure.** MILP difficulty is combinatorial. K failed on
   these instances in 4 h; we hand a narrower interval but the same combinatorial core, and 3600 s
   is less time than they used.
3. **A closure may be credited to the solver, not to us.** This is exactly what Arm C tests, and
   without it the experiment is not worth running.
4. **Our LB must be valid or the result is worse than useless.** It has passed V2 on 521
   incumbents (no incumbent below it) and reproduces 34 known optima from below within 2.1-3.0%.
   If `zObj >= our_LB` ever renders a model infeasible, that is a **hard stop**: it would mean
   the bound is not valid, and it invalidates the entire dual leg, not just this run.
   **That check is the single most valuable output of this experiment even if nothing closes.**
5. **It costs 6 h and must wait for S2g** (wall-clock sensitive, ETA ~14:40).
6. **Solver choice matters.** Running CPLEX would keep the stack consistent with our own port;
   running Gurobi matches K's. Arm C absorbs either choice as long as both arms use the same one.
   Decision: use **CPLEX 22.1.1** via `joint_model_cplex.build_joint_model`, because that model
   is already port-equivalence validated (15/15 cells to <0.02) and exposes `zObj` directly.

## 6. What a null result still buys

Even with no closure, Arm B vs Arm C gives the first measurement of **how much our bound
accelerates an exact solve** — final gap, best bound at 3600 s, nodes explored. That is a
publishable quantification of the dual leg's practical value, and it is not available today.

---

## AMENDMENT — 2026-09-16. Arm naming, and what each arm actually measures

Recorded after the run, because it concerns **how the result is described**, not what was measured.
Nothing in the design, the outcome table or the registered predictions changes.

### There is no arm A

The labels "B" and "C" appear in this file and in `analysis/s2k_exact_closure.py` with no arm A
anywhere — orphaned from an earlier draft. They identify nothing to a reader.

**The artifact labels stay.** `validation/s2k_closure.csv` has an `arm` column carrying `B` and
`C`, the prereg was written with them, and renaming would break the audit trail for no gain.

**The manuscript does not use them.** The arms are named for what they are:

| artifact label | manuscript term | what it is |
|---|---|---|
| `B` | **with our bound** (bound-injected) | K's joint MILP **plus** `zObj >= our_LB`, nothing else |
| `C` | **without** (control) | the identical model, without that constraint |

### Why each arm exists, in one line each

* **With our bound:** handed a proven lower bound, can an exact solver prove optimality? The
  constraint is valid — our LB cannot exclude the optimum — and it raises the root LP bound,
  which is the quantity branch-and-bound prunes on. It is a cut, not a hint. It carries **no MIP
  start**, so a closure could be attributed to the dual bound alone.
* **Without:** what does the solver achieve unaided? We run CPLEX today; K ran **Gurobi 9.12**,
  four generations earlier. Without this arm a closure could be "solvers improved since 2021"
  rather than "our bound helped". It is what makes the other arm interpretable.

### THE TWO ARMS YIELD DIFFERENT INFORMATIVE QUANTITIES, and conflating them is easy

This was muddled in discussion on 2026-09-16 and is recorded so it is not muddled in the paper.

* **The bound-injected arm's `best_bound` is NOT a measurement.** It returned exactly the injected
  value on all three cells — 663.11, 648.18, 721.23 — because the constraint sets the floor and
  branch-and-bound never lifted it within the limit. Quoting it as "our bound under arm B" merely
  restates our own input. **What this arm informatively yields is the GAP**: how close the
  solver's own incumbent came to our bound.
* **The control arm's `best_bound` IS a measurement** — 487.14, 285.74, 419.60 — the solver's own
  dual progress in one hour on the same machine.

So the correct pairing to report is: **the control says what the solver's own bound is worth; the
bound-injected arm says what remains unproved once ours replaces it.**
