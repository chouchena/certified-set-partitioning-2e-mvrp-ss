# Validation report — formulation and implementation

This report accompanies the manuscript as supplementary material. It lets a reviewer assess the
certification and feasibility claims directly, rather than relying on an assurance that checks were
run. Every check is produced by a released script on the committed artifacts; the per-area detail
documents and the raw instruments are listed below, and the exact release is identified at the end.

Scope: this reports the evidence that supports the **final results**, not the development history.
The checks fall in seven areas, following the acceptance framework agreed with the authors.

**Revised after two rounds of referee-style review (findings #1–#8, decisions d798–d804; round-2
corrections d806).** The corrections:

- The **certificate proofs** were rewritten twice. The ε\|C\| proof now bounds z^s via the image
  x\* of the optimal street solution and, in round 2, **dualizes the finite variable upper bounds**
  (the transfer arcs obey 0≤z≤1): a variable at its upper bound may have negative structural reduced
  cost, so the duals carry an extra η≤0 term and L\_rmp = π·1 + σ·1 + η·u. The ng proof narrows the
  ordering LP(R\_ng) ≤ LP(R\_e) to the **complete** LP optima and states that recovering the
  elementary value means solving the elementary master, not altering the pricer
  (`A1_proofs.tex`, `04_bounding.tex`, `07_conclusions.tex`).
- The **displayed lower bounds are rounded down** to a valid lower bound: each is the certified value
  less its ε\|C\| dual correction, floored to one decimal, so no printed figure exceeds the certified
  value (the per-cell appendix table; `analysis/tab_percell_grid.py`).
- The **production numba FastPricer** is checked against the independent enumeration with the
  completion-bound prune ON and OFF, ABSOLUTE tolerance, exhausted searches treated as failures, ng
  universes strictly larger than elementary (R205), and duals driven to the −ε threshold
  (`AREA4_FASTPRICER_AUDIT.md`), not only the Python pricer.
- The floor check witnesses the relaxation on **real continuous-time incumbents**
  (`AREA4_FLOOR_RELAXATION.md`), superseding the earlier within-model LP≤IP note
  (`AREA2_FLOOR_MAPPING.md`); the certificate audit is relabelled a **stored-state consistency**
  audit, not an independent re-solve, with full-precision records in `certificate_records.json`; the
  reported incumbents are linked to their source artifacts in `incumbent_manifest.json`; and the
  **set-partitioning / covering** terminology is reconciled (the covering relaxation is a valid
  relaxation of the set-partitioning integer model).

Two items are the authors': hand-checking the rewritten proofs, and minting the release identifiers.

---

## 1. Master formulation — displayed model vs. implemented model

The displayed master (manuscript §4, eq. (1)–(6)) was reconciled line by line against the
implementation (`analysis/tep_cg_bound.py`). Every row, arc and column of the displayed model maps
to a named construction in the code; the correspondence is tabulated in
[`EQ_TO_CODE.md`](EQ_TO_CODE.md). The only differences found were in the **presentation**, corrected
in the manuscript, not in the code (so no number changes):

- the post-layer flow equation omitted the outgoing satellite-trip departure term (present in the
  code at `add_column`); and
- the covering coefficient was written as a membership indicator `i∈r`, whereas the code (and the
  ng-route theory) use the **visit count** `a_{ir}` — the displayed constraint now reads
  `Σ_r a_{ir} λ_r ≥ 1`.

## 2. Relaxation validity (floor model)

`analysis/floor_map_check.py`. On sub-instances small enough to enumerate the whole trip space, the
full master is solved as an all-integer floor schedule; the floor LP ≤ the floor IP (the LP relaxes
a realizable integer schedule) and the integer optimum's trips partition the customers. Detail:
[`AREA2_FLOOR_MAPPING.md`](AREA2_FLOOR_MAPPING.md). The end-to-end relaxation property (floor LP ≤
feasible street cost) holds grid-wide: the reported lower bound is ≤ the reported incumbent on every
cell (area 6 and the release gate).

## 3. Ceil restriction and joint feasibility

The ceil model is used for **primal selection only** — it is never a lower bound (manuscript §4.6,
Appendix A1). A ceil selection is turned into a candidate timetable and re-timed in continuous time;
whether a candidate is actually realizable is **verified per solution, not asserted** for every ceil
selection. The precise transfer-arc admissibility condition is that the bucket *start* meet the
earliest admissible transfer time; the code uses the more permissive bucket-*interval*-overlap test.
That can only change which candidates the primal search considers, not the validity of what is
reported: every reported incumbent is independently re-verified as a feasible joint schedule (area 6),
so an over-permissive candidate that is not in fact realizable is rejected there rather than reported.

## 4. Pricing correctness (independent enumeration)

`analysis/enum_price_check.py` enumerates the entire feasible trip space by its own recursion,
independent of the pricer's labelling, and checks on tractable sub-instances: full-enumeration LP =
column-generation LP; the pricer's most negative reduced cost = the exhaustive minimum to within
1e-6; the pricer agrees with the completion-bound prune disabled as well (`no_prune`), the label
dominance remaining enabled, so neither form of pruning discards an improving column **on the tested
cases** (the general guarantee rests on the labelling algorithm's correctness); the ng LP ≤ the
elementary LP, with ng enumerated over its own walk universe on cases where it differs from the
elementary one (a strict gap is exhibited, R205). Detail: [`AREA4_PRICING_AUDIT.md`](AREA4_PRICING_AUDIT.md).

The grid actually ran the **production numba `FastPricer`**, so `analysis/fastpricer_check.py`
compares it (and the Python `Pricer`) against the same independent enumeration, with the
completion-bound prune ON and OFF (so neither it nor the always-on label dominance discards an
improving column), with **absolute** `1e-6` agreement, treating an exhausted search as a failure
rather than a pass, over ng universes strictly larger than the elementary one (R205), and over duals
shifted so the minimum reduced cost straddles the `−ε` certificate threshold. Detail:
[`AREA4_FASTPRICER_AUDIT.md`](AREA4_FASTPRICER_AUDIT.md).

## 5. Bound certification (per cell)

`analysis/cert_audit.py` (read-only over the frozen-grid artifacts) emits, for every reported cell,
the record that establishes a safe bound: street LP, water term, arithmetic bound AB4, composed
LP+water, the reported `max(LP+water, AB4)`, the carrying member, the certificate class, and the
closing evidence of the certifying pass (columns added, label budget not exhausted, zero
covering/artificial slack), with the deterministic Work and code hash. Every cell satisfies the
invariants; the arithmetic bound carries the eleven smallest cells (matching the registered
portfolio count), the certified relaxation carries the rest. Detail:
[`AREA5_CERTIFICATE_AUDIT.md`](AREA5_CERTIFICATE_AUDIT.md).

The dual (numerical) correction applied to a certified bound is the Lagrangian term `L_rmp − ε|C|`
with `ε = 1e-6`; at `|C| ≤ 100` it is below `1e-4`. The per-cell appendix table displays the bound
**floored to one decimal after this correction**, so the printed figure is itself a valid lower bound
(rounding to nearest could print a value above the certified one, e.g. `355.559 → 355.6`); the
displayed gap is computed from the floored figure (manuscript Appendix A1, proof of the certificate
lemma; `analysis/tab_percell_grid.py`).

## 6. Feasible solutions (joint re-verification)

`analysis/reverify_reported.py` runs the independent joint verifier (`analysis/verifier3.py`:
street routing and timing, vessel routing and windows, street–vessel coincidence at transfers,
satellite spacing, fleet) over exactly the reported incumbents, and recomputes each objective. Every
reported incumbent is feasible with a recomputed cost matching the reported value. Detail and the
per-incumbent table: [`AREA6_INCUMBENT_REVERIFY.md`](AREA6_INCUMBENT_REVERIFY.md).

## 7. Arithmetic bound (formula and components)

`analysis/ab_formula_check.py` documents the reported arithmetic bound,
`AB4 = penaltyCars·V_LB + travelcoststreet·Dist_LB + water`, with `Dist_LB = max(assignment, MST,
forced-terminal)` and `V_LB = max(routes_lb_time, ⌈work/H⌉, clique)` (the clique gated on the
triangle inequality so a non-metric distance cannot inflate it). It reproduces the bound per cell
from its components and matches the frozen-grid value on every cell. Detail and the per-cell
component table: [`AREA7_ARITHMETIC_BOUND.md`](AREA7_ARITHMETIC_BOUND.md).

---

## Reproducing the checks

From the release root (deterministic; no external network):

```
python analysis/enum_price_check.py --cell C201 --size 10 --n-cust 6 --ng 5      # area 4 (enumeration)
python analysis/fastpricer_check.py                                              # area 4 (production FastPricer; defaults to R205)
python analysis/floor_relax_check.py --cells C201,R201,RC201,C204,R205 --size 10 # area 4 (floor relaxation on real incumbents)
python analysis/floor_map_check.py  --cells C201,R201,RC201 --size 10 --n-cust 6 # area 2 (floor LP<=IP)
python analysis/cert_audit.py                                                    # area 5
python analysis/reverify_reported.py                                             # area 6
python analysis/ab_formula_check.py                                              # area 7
python analysis/tab_percell_grid.py                                              # per-cell appendix (floored bounds)
```

Each writes its `validation/AREA*.md` evidence file and exits nonzero on any violation. The joint
verifier is `analysis/verifier3.py`; the instance loader and parameters are
`analysis/verifier3.load_instance` / `analysis/build_instance.build` (`wls=0.1`, `tau="formula"`,
proximity per `analysis/k_comparison.k_proximity`). Per-instance certificates and decoded joint
solutions are the `runs/oracle/tep_solve_frzdual2_*.json` artifacts (the `solution` and `lb_hist`
fields).

## Release identifier

The results in the submitted manuscript are produced at the release recorded in the Data
Availability statement (repository URL + archive DOI, with the commit on branch `v2-fast-pricer`
carrying these validation instruments and the frozen-grid artifacts). Decisions d786–d795 in
`validation/DECISIONS.jsonl` record what each check established and what would reopen it.
