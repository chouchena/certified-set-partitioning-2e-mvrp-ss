# FINDING — the street matrix is non-metric at n100 (two-decimal rounding), and no reported bound depends on metricity

2026-10-13. Raised in adverse review (item 3H): the manuscript asserted the travel times "satisfy the
triangle inequality ... (both hold on the benchmark)" (Lemma 1, `04_bounding.tex`), but the
preprocessing never established it. Audited with `python analysis/triangle_audit.py`.

## 1. The assertion is false, and the violation is traced to rounding

`D[i][j] = round(euclidean, 2)` (`instance_view.py`). The max triangle excess
`max_{i,j,k} D[i][k] - (D[i][j] + D[j][k])` is:

| size | excess | cells affected |
|---|---|---|
| n10, n20, n30, n50 | **0.000000** (exactly metric) | 0 / 27 |
| **n100** | **0.010000** | 19 / 27 (R-family + some) |

Recomputing the UNROUNDED euclidean distances from the node coordinates gives excess `<= 1e-9` on
**every** instance. So the n100 violations are **purely two-decimal rounding** (grain 0.01) — a traced
fact, not an inference from magnitude. The excess is size-triggered (appears only once the coordinate
range densifies at n100), not proximity-triggered; this matches `crossfeed/fullset_bound.py:213-220`.

## 2. No reported bound requires metricity — verified, not assumed

The reported LB is `max(TEP-LP, AB4)`.

* **TEP-LP window tightenings** `e_i = max(a_i, H0 + D[g][i])`, `l_i = min(b_i, H1 - D[i][g] - svc - U)`
  are valid relaxations (exclude no feasible schedule) iff the direct depot-customer arc is a shortest
  path. All-pairs shortest paths give `D[g][i] = SP[g][i]` and `D[i][g] = SP[i][g]` for **every
  customer on all 135 instances** — window-arc shortfall **exactly 0**. The non-metric triples never
  touch a depot-customer arc. Lemma 1 therefore holds without any triangle hypothesis; its
  constructive proof re-times existing routes (objective exactly `z^s`) and invokes no shortcutting.
* **AB4** components: `assignment` and `MST` are metric-free, and `FORCED` prices the literal next
  node at `D[i][j]` exactly (no shortcutting), per `crossfeed/fullset_bound.py`. The **clique** term is
  the only metric-dependent component and is **gated** on the measured excess (`metric_tol = 1e-9`): it
  is dropped on the n100 cells, where `routes_lb_time` dominates it anyway, so `V_LB` is unchanged.

## 3. Action taken

* Lemma 1 hypothesis "travel times satisfy the triangle inequality" **removed** (false and
  unnecessary); a sentence records that the windows use direct depot-customer travel, which is a
  shortest path on the benchmark, and that no reported bound requires metricity. `04_bounding.tex`.
* This audit is reproducible: `python analysis/triangle_audit.py` (VERDICT line asserts the two
  load-bearing facts: window-arc shortfall 0, and rounding-only origin).

## Reopen if
A benchmark instance shows a window-arc shortfall `> 1e-9` (a depot-customer arc that is shortcuttable),
or the unrounded euclidean is itself non-metric anywhere, or the AB4 clique gate is bypassed on a
non-metric cell.
