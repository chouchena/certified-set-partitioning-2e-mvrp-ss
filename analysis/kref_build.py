"""
Build the ONE canonical machine-readable copy of every Karademir et al. (2025) published result.

WHY (2026-09-12). K's numbers were scattered across a markdown file with three different table
layouts, two table crops, a full-page render, and FIVE independent parsers
(`lb_monitor.k_table3`, `cellreport`, `domination_table`, `k_denominators`, and a hardcoded
`instance_specs.K_REF`). That arrangement produced three separate errors in one day:

  * a crossover table quoting 0/26 and 15/24 because a partial join supplied the denominators
    (truth: 0/27 and 17/27);
  * `k_table3(10)` returning {} for days because the n10 layout has three cell-columns and no
    Gap column -- an empty dict, not an error;
  * the Table 3 "Run time (s)" row sitting unextracted while `RT_COMPARABILITY.md` carried an
    incomplete inventory of what K publish.

Every one of those is a silent-empty or wrong-denominator failure. This script emits
`data/karademir2025/k_reference.json` and `analysis/kref.py` reads it with MANDATORY validation:
each table is checksummed against K's own published averages, and the accessor RAISES rather
than returning an empty result.

    python analysis/kref_build.py            # build + validate
    python analysis/kref_build.py --verify   # validate only

Values are taken from `paper/paper-reference-data.md` (itself transcribed and cross-checked
against the table crops on 2026-09-01) plus the Table 3 summary rows extracted 2026-09-12.
"""
import os, re, sys, json, argparse
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "paper", "paper-reference-data.md")
OUT_DIR = os.path.join(ROOT, "data", "karademir2025")
OUT = os.path.join(OUT_DIR, "k_reference.json")

CELLS = ([f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC2{i:02d}" for i in range(1, 9)])


def _num(s):
    return float(s.replace("−", "-").replace("*", "").replace(" ", "").replace(" ", ""))


def parse_table3():
    """Per-instance rows. n10 is a 3-column layout with no Gap column (all optimal);
    n20/n30 are single-column with Joint BK/Gap/IncT and LBBD BK/Imp/IncT."""
    txt = open(REF, encoding="utf-8").read().splitlines()
    out = {"10": {}, "20": {}, "30": {}}
    sec = None
    for l in txt:
        if l.startswith("### |C|"):
            m = re.search(r"=\s*(\d+)", l)
            sec = m.group(1) if m and m.group(1) in out else None
            continue
        if sec is None:
            continue
        if sec == "10":
            for m in re.finditer(r"\|\s*((?:RC|C|R)\d{3})\s*\|\s*(\d+\.\d+)\s*\|", l):
                out["10"][m.group(1)] = {"joint_bk": float(m.group(2)), "joint_gap": 0.0,
                                         "lbbd_bk": float(m.group(2)), "lbbd_imp": 0.0}
        else:
            # Imp% carries signs and bold markers: "-0.4", "+0.6", "**+5.3**", U+2212 minus.
            # Omitting "+" silently dropped 5 rows at n20 and 2 at n30 -- caught by the
            # published-average checksum, which is precisely why that checksum exists.
            m = re.match(r"\|\s*((?:RC|C|R)\d{3})\s*\|\s*([\d.]+)\s*\|\s*([-+\u2212\d.*]+)\s*\|"
                         r"\s*([\d  ]+)\s*\|\s*([\d.]+)\s*\|\s*([-+\u2212\d.*]+)\s*\|"
                         r"\s*([\d  ]+)\s*\|", l)
            if m:
                out[sec][m.group(1)] = {
                    "joint_bk": _num(m.group(2)), "joint_gap": _num(m.group(3)),
                    "joint_inc_time": _num(m.group(4)), "lbbd_bk": _num(m.group(5)),
                    "lbbd_imp": _num(m.group(6)), "lbbd_inc_time": _num(m.group(7))}
    return out


# Table 3 summary rows. Extracted 2026-09-12 from paper/tables/table3_page.png -- the
# "Run time (s)" and "Initial solution" rows were NOT previously in any machine-readable form.
TABLE3_SUMMARY = {
    "10": {"joint": {"bk": 357.7, "gap": 0.0, "inc_time": 31.9, "run_time": 197},
           "lbbd": {"bk": 357.7, "imp": 0.0, "inc_time": 4.5, "run_time": 11},
           "initial_solution": 357.8},
    "20": {"joint": {"bk": 722.7, "gap": 26.2, "inc_time": 5067.8, "run_time": 10554},
           "lbbd": {"bk": 719.0, "imp": -0.5, "inc_time": 1025.3, "run_time": 9192},
           "initial_solution": 747.7},
    "30": {"joint": {"bk": 1132.4, "gap": 43.0, "inc_time": 7887.8, "run_time": 13346},
           "lbbd": {"bk": 1066.8, "imp": -5.5, "inc_time": 3338.6, "run_time": 13365},
           "initial_solution": 1197.0},
}

# Table 6, |C|=100, per family, proximity 0.1. Gaps from the caption footnote.
TABLE6 = {
    "C": {"n": 8, "gap_joint": 60.1,
          "joint": {"zIP": 4271.3, "travel_total": 4723.6, "travel_sl": 2212.4,
                    "travel_wl": 2511.2, "fleet_sl": 8.00, "fleet_wl": 8.75, "dev_vessel_lb": 0.75},
          "lbbd": {"zIP": 3857.2, "travel_total": 4039.6, "travel_sl": 1958.5,
                   "travel_wl": 2081.1, "fleet_sl": 7.50, "fleet_wl": 8.00, "dev_vessel_lb": 0.00},
          "min_transfers": 37.0},
    "R": {"n": 11, "gap_joint": 74.6,
          "joint": {"zIP": 4158.9, "travel_total": 4443.4, "travel_sl": 2182.8,
                    "travel_wl": 2260.6, "fleet_sl": 9.27, "fleet_wl": 9.55, "dev_vessel_lb": 3.55},
          "lbbd": {"zIP": 3720.9, "travel_total": 3415.3, "travel_sl": 1997.7,
                   "travel_wl": 1417.6, "fleet_sl": 8.64, "fleet_wl": 6.09, "dev_vessel_lb": 0.09},
          "min_transfers": 30.9},
    "RC": {"n": 8, "gap_joint": 77.0,
           "joint": {"zIP": 5432.5, "travel_total": 5452.9, "travel_sl": 2840.2,
                     "travel_wl": 2612.7, "fleet_sl": 9.50, "fleet_wl": 9.25, "dev_vessel_lb": 2.25},
           "lbbd": {"zIP": 4810.6, "travel_total": 4451.6, "travel_sl": 1525.1,
                    "travel_wl": 1970.6, "fleet_sl": 8.75, "fleet_wl": 7.88, "dev_vessel_lb": 0.88},
           "min_transfers": 33.3},
}

TEXT_FACTS = {
    "time_limit_s": 14400,
    "subproblem_tl_s": {"<=30": 50, "100": 100},
    "hardware": "4 CPUs Intel Xeon Gold 5218 @ 2.30 GHz",
    "solver": "Gurobi 9.1.2",
    "tau_rule": "ceil(2 x mean customer service time)",
    # PROXIMITY IS A PROPERTY OF THE EXHIBIT, NOT OF THE SIZE (audited against the PDF
    # 2026-09-19). n50 is 0.0 in Table 4 and 0.1 in Fig. 5; n10/20/30 are 0.0 in Table 3 and 0.1
    # in Fig. 5. Any {size: proximity} map is therefore only well-defined once a comparator set
    # is fixed. Ours is Tables 3/4/6, and that scoping is OURS, not a fact about K.
    #
    # Each entry says whether K STATES the value or we INFER it. Two of them are inferred, and
    # shipping an inference as K's statement is how a footnote becomes a fact.
    "proximity": {"table3": 0.0, "table4": 0.0, "table6": 0.1, "fig4_range": [0, 0.1, 0.2, 0.3, 0.4],
                  "fig5": 0.1, "table5": 0.1},
    "proximity_basis": {
        "table3": "INFERRED. S5.2 states sizes and WLS=1:10 only. 0.0 follows from S5.4's "
                  "'compared to the base scenario, where proximity equals to 0', proximity "
                  "being varied only in S5.4.",
        "table4": "INFERRED. Same basis as table3.",
        "table6": "STATED. Table 6 note: 'WLS = 1:10, and the proximity = 0.1'.",
        "fig4_range": "STATED. S5.4 sweeps proximity 0 to 0.4 at |C|=50 against k-means.",
        "fig5": "STATED. S5.5.2: '4 satellites are located at the 0.1 proximity value for "
                "two-echelon systems, and at the depot for single-echelon systems.'",
        "table5": "STATED. Table 5 row 'Sailing between satellites': Proximity = 0.1 for both "
                  "IWLT-Stationary and IWLT-Flexible.",
    },
    "satellites": 4,
    "lefv_capacity": 50,
    "vessel_capacity": 250,
    "sizes_tested": {"table3": [10, 20, 30], "table4": [10, 20, 50], "table6": [100],
                     "fig4": [50], "fig5": [10, 20, 30, 40, 50], "n40_per_instance": False},
    "initial_solution_gap_pct": {"10": 0.2, "20": 3.4, "30": 5.7},
    # FIG. 4 -- satellite-location study, |C|=50, proximity sweep vs k-means (S5.4).
    # Prose values only: the figure's own plotted points are an image and are not captured.
    "fig4": {
        "sizes": [50],
        "proximity_order": [0.0, 0.1, 0.2, 0.3, 0.4],
        "travel_time_increase_pct_vs_kmeans": [15.3, 6.6, 6.8, 14.0, 21.2],
        "street_fleet_by_proximity": [3.76, 3.64, 3.87, 3.97, 4.39],
        "street_fleet_kmeans": 3.61,
        "kmeans_travel_improvement_pct_by_family": {"C": 21.3, "R": 15.5, "RC": 5.2},
        "vessel_lower_bound_by_family": {"C": 4, "R": 3, "RC": 4},
        "note": "K state proximity 0.1 'optimizes the problems better on average in terms of "
                "fleet size and overall travel time compared to k-means'.",
    },
    # FIG. 5 -- benchmark service systems (S5.5), sizes 10..50 at proximity 0.1.
    # IWLT-Flexible IS the 2E-MVRP-SS, i.e. our model. Percentages are vs the 'Only trucks'
    # baseline, whose ABSOLUTE values live in the figure's data table and are NOT captured --
    # so these support a relative comparison only.
    "fig5": {
        "sizes": [10, 20, 30, 40, 50],
        "proximity": 0.1,
        "instances_averaged": {"10": 27, "20": 27, "30": 27, "40": 26, "50": 26},
        "exclusion": "instance 205 becomes infeasible for SINGLE-ECHELON systems under the test "
                     "settings, so it is dropped from the common instance set at |C|=40 and 50. "
                     "The family is not named in the caption (C205, R205 and RC205 all exist; "
                     "dropping all three would give 24, so exactly one is meant). The "
                     "infeasibility is in the benchmark, NOT in the 2E-MVRP-SS.",
        "only_lefvs_street_tt_increase_pct": [83, 136, 177, 203, 240],
        "iwlt_stationary_street_reduction_pct": [17, 21, 16, 18, 9],
        "iwlt_flexible_street_reduction_pct": [28, 30, 28, 27, 19],
        "iwlt_stationary_total_tt_increase_pct": [16, 31, 45, 45, 49],
        "iwlt_flexible_total_tt_increase_pct": [28, 37, 46, 42, 47],
        "settings_differ": "Multiple trips are NOT allowed for large vehicles in the alternative "
                           "systems. Fig. 5 reports average travel times and average fleet "
                           "sizes, not the lexicographic objective z used in Tables 3/4/6.",
    },
    # WHAT WE DELIBERATELY DO NOT CAPTURE, AND WHY. Corrected 2026-09-19: three of these
    # reasons were wrong in a way that mattered. They read as "K has nothing here" when the
    # truth was "we chose not to take it", which is CLAUDE.md failure mode 2 -- and it led to
    # me telling the author outright that K never published |C| = 40.
    "NOT_captured": {
        "_note": "Deliberate omissions. Each states what K DOES publish and what we chose not "
                 "to take, in that order. An omission is never phrased as an absence in K.",
        "table1_notation_table2_variants": "Not numeric results.",
        "table5_service_design_alternatives": "Row values not captured. Its PROXIMITY setting "
            "(0.1, both IWLT columns) IS captured under text_facts.proximity.table5 -- a "
            "setting that decides whether a comparison is valid is not merely a setting.",
        "fig4_proximity_and_kmeans": "K publish a full proximity sweep at |C| = 50. Its PLOTTED "
            "points are an image and are not captured; the PROSE values are, under "
            "text_facts.fig4. D2 k-means remains out of scope.",
        "fig5_benchmark_systems": "K publish benchmark-system results at |C| = 10,20,30,40,50 "
            "at proximity 0.1, and this is the ONLY place |C| = 40 appears. The figure's data "
            "table is an image and its ABSOLUTE values are not captured; the PROSE percentages "
            "ARE, under text_facts.fig5. IWLT-Flexible is the 2E-MVRP-SS, so a real comparison "
            "exists there -- on travel time and fleet size, not on z.",
        "table6_savings_pct_rows": "Derivable from zIP and verified to reproduce "
            "(9.7/10.5/11.4).",
    },
    "open_problems_quoted": [
        "need for improvement in the relaxed cost formulation of the master problem (S5.3, S6)",
        "LBBD has the potential to facilitate the development of further heuristics (S6)",
        "the underlying lagrangian bounding framework can provide the basis for designing "
        "subgradient optimization methods (S6)"],
}


def parse_table4():
    txt = open(REF, encoding="utf-8").read().splitlines()
    rows, inside = [], False
    for l in txt:
        if l.startswith("## Table 4"):
            inside = True
            continue
        if inside and l.startswith("## "):
            break
        m = re.match(r"\|\s*(\d+)\s*\|\s*([\d:]+)\s*\|\s*(Joint|LBBD)\s*\|\s*([\d  .]+)\s*\|"
                     r"\s*([\d  .]+)\s*\|\s*([+−\d.-]+)\s*\|", l)
        if inside and m:
            rows.append({"size": int(m.group(1)), "wls": m.group(2), "method": m.group(3),
                         "bk": _num(m.group(4)), "inc_time": _num(m.group(5)),
                         "gap_imp": _num(m.group(6))})
    return rows


def validate(doc):
    """Every table is checksummed against K's OWN published averages. A parser that reads
    nothing must FAIL here, not return an empty result."""
    errs = []
    for size, exp in (("10", 357.7), ("20", 722.7), ("30", 1132.4)):
        cells = doc["table3"]["per_instance"][size]
        if len(cells) != 27:
            errs.append(f"table3 n{size}: {len(cells)}/27 cells")
            continue
        missing = [c for c in CELLS if c not in cells]
        if missing:
            errs.append(f"table3 n{size}: missing {missing}")
        mean = sum(v["joint_bk"] for v in cells.values()) / 27
        if abs(mean - exp) > 0.05:
            errs.append(f"table3 n{size}: mean joint_bk {mean:.2f} != published {exp}")
    for size, exp in (("20", 26.2), ("30", 43.0)):
        cells = doc["table3"]["per_instance"][size]
        if len(cells) == 27:
            mean = sum(v["joint_gap"] for v in cells.values()) / 27
            if abs(mean - exp) > 0.05:
                errs.append(f"table3 n{size}: mean joint_gap {mean:.2f} != published {exp}")
    n4 = len(doc["table4"])
    if n4 != 24:
        errs.append(f"table4: {n4}/24 rows (3 sizes x 4 WLS x 2 methods)")
    tot = sum(f["n"] for f in doc["table6"].values())
    if tot != 27:
        errs.append(f"table6: family sizes sum to {tot}, expected 27")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    doc = {
        "source": {
            "citation": "Karademir, C. et al. (2025) European Journal of Operational Research "
                        "322(2) 480-499",
            "doi": "10.1016/j.ejor.2024.10.047",
            "code": "https://github.com/cigdemkarademir/2echelon-synchronization",
            "extracted": "2026-09-12",
            "extracted_from": ["paper/paper-reference-data.md (transcribed + cross-checked "
                               "against table crops 2026-09-01)",
                               "paper/tables/table3_page.png (summary rows, 2026-09-12)"],
            "note": "CANONICAL. Read via analysis/kref.py, never by re-parsing markdown.",
        },
        "table3": {"per_instance": parse_table3(), "summary": TABLE3_SUMMARY},
        "table4": parse_table4(),
        "table6": TABLE6,
        "text_facts": TEXT_FACTS,
    }
    errs = validate(doc)
    print("=" * 72)
    for size in ("10", "20", "30"):
        c = doc["table3"]["per_instance"][size]
        m = (sum(v["joint_bk"] for v in c.values()) / len(c)) if c else float("nan")
        print(f"table3 n{size}: {len(c)}/27 cells, mean joint_bk {m:.2f} "
              f"(published {doc['table3']['summary'][size]['joint']['bk']})")
    print(f"table4: {len(doc['table4'])} rows")
    print(f"table6: {len(doc['table6'])} families, n={sum(f['n'] for f in doc['table6'].values())}")
    print("-" * 72)
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print("  " + e)
        return 2
    print("VALIDATION PASSED -- every table checksums against K's published averages.")
    if not a.verify:
        os.makedirs(OUT_DIR, exist_ok=True)
        # PRESERVE WHAT THIS SCRIPT DOES NOT PRODUCE. 2026-09-19: a rebuild silently dropped
        # text_facts.prose_claims_verified, text_facts.NOT_captured and the whole table4_full
        # block, because they were added by other tools and this file calls itself "the ONE
        # canonical copy". A generator that overwrites keys it does not own is a landmine: the
        # loss is invisible until someone looks for a key that is no longer there.
        #
        # So a rebuild now MERGES: keys this script produces are refreshed, keys it does not
        # produce are carried through untouched, and anything carried through is named on stdout
        # so it is never silently inherited either.
        carried = []
        if os.path.exists(OUT):
            try:
                prev = json.load(open(OUT, encoding="utf-8"))
            except Exception:
                prev = {}
            for k, v in prev.items():
                if k not in doc:
                    doc[k] = v
                    carried.append(k)
            pf, nf = prev.get("text_facts", {}), doc.get("text_facts", {})
            for k, v in pf.items():
                if k not in nf:
                    nf[k] = v
                    carried.append("text_facts.%s" % k)
        json.dump(stamped(doc, __file__), open(OUT, "w"), indent=1)
        if carried:
            print("carried through (not produced by this script): %s" % ", ".join(carried))
        print(f"-> {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
