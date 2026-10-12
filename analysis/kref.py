"""
THE accessor for every Karademir et al. (2025) published number.

Rule: nothing in this repo re-parses K's markdown, table crops or PDF. Everything reads
`data/karademir2025/k_reference.json` through this module, which validates on load and
**raises rather than returning an empty result**.

    from kref import table3, derived_lb, table6, summary, fact

    table3(20)              -> {cell: {joint_bk, joint_gap, joint_inc_time, lbbd_bk, ...}}
    derived_lb(20)          -> {cell: BK * (1 - gap/100)}   K's implied per-instance LB
    derived_lb(100)         -> {family: mean zIP * (1 - family gap/100)}  + JENSEN CAVEAT
    summary(20)["joint"]["run_time"]   -> 10554
    table6("R")["lbbd"]["fleet_sl"]    -> 8.64
    fact("time_limit_s")               -> 14400

WHY THIS EXISTS. Five modules used to parse K's numbers independently, and on 2026-09-12 that
produced three errors in one day: a crossover table with wrong denominators, `k_table3(10)`
silently returning {} for days, and the "Run time (s)" row unextracted while a validation doc
asserted an incomplete inventory. The common shape is a lookup that fails by returning nothing.
Every accessor here raises instead.
"""
import os, json, functools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "karademir2025", "k_reference.json")

CELLS = ([f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC2{i:02d}" for i in range(1, 9)])
PER_INSTANCE_SIZES = (10, 20, 30)


class KRefError(RuntimeError):
    """Raised instead of returning an empty or partial result."""


@functools.lru_cache(maxsize=1)
def _doc():
    if not os.path.exists(PATH):
        raise KRefError(f"{PATH} missing -- run: python analysis/kref_build.py")
    d = json.load(open(PATH, encoding="utf-8"))
    # Re-validate on every load: a hand-edited or truncated file must not be usable.
    for size in PER_INSTANCE_SIZES:
        cells = d["table3"]["per_instance"][str(size)]
        if len(cells) != 27:
            raise KRefError(f"k_reference.json table3 n{size}: {len(cells)}/27 cells")
        exp = d["table3"]["summary"][str(size)]["joint"]["bk"]
        mean = sum(v["joint_bk"] for v in cells.values()) / 27
        if abs(mean - exp) > 0.05:
            raise KRefError(f"k_reference.json table3 n{size}: mean {mean:.2f} != published {exp}")
    return d


def table3(size):
    """Per-instance rows for |C| in {10,20,30}. Raises for any other size -- K publish none."""
    if size not in PER_INSTANCE_SIZES:
        raise KRefError(f"K publish NO per-instance data at |C|={size}. "
                        f"Available: {PER_INSTANCE_SIZES}. "
                        f"n50 is pooled-only (table4); n100 is per-family (table6); "
                        f"n40 was never run.")
    return dict(_doc()["table3"]["per_instance"][str(size)])


def summary(size):
    """Table 3 summary rows: averages, total run time, initial solution."""
    if size not in PER_INSTANCE_SIZES:
        raise KRefError(f"no Table 3 summary at |C|={size}")
    return dict(_doc()["table3"]["summary"][str(size)])


def derived_lb(size):
    """K's implied lower bound.

    |C| in {10,20,30}: per instance, BK * (1 - gap/100).
    |C| = 100       : per FAMILY, from published means -- carries a JENSEN CAVEAT, because
                      mean((1-g_i) z_i) != (1 - mean g)(mean z) and the bias sign is unknown.
    |C| = 50        : raises. K publish only a 27-instance pooled average (table4); use
                      table4() and state the caveat explicitly.
    """
    if size == 100:
        return {f: v["joint"]["zIP"] * (1 - v["gap_joint"] / 100)
                for f, v in _doc()["table6"].items()}
    if size == 50:
        raise KRefError("K publish no per-instance or per-family LB at |C|=50, only a pooled "
                        "27-instance average (table4). Do not derive a per-cell bound from it.")
    return {c: v["joint_bk"] * (1 - v["joint_gap"] / 100) for c, v in table3(size).items()}


def table4(size=None, wls=None, method=None):
    """Pooled rows: 3 sizes {10,20,50} x 4 WLS x 2 methods = 24."""
    rows = _doc()["table4"]
    out = [r for r in rows
           if (size is None or r["size"] == size)
           and (wls is None or r["wls"] == wls)
           and (method is None or r["method"] == method)]
    if not out:
        raise KRefError(f"no table4 row for size={size} wls={wls} method={method}; "
                        f"K cover sizes {sorted({r['size'] for r in rows})} "
                        f"and WLS {sorted({r['wls'] for r in rows})}")
    return out


def table6(family=None):
    """|C|=100 per-family block, proximity 0.1."""
    t = _doc()["table6"]
    if family is None:
        return dict(t)
    if family not in t:
        raise KRefError(f"unknown family {family!r}; have {sorted(t)}")
    return dict(t[family])


def fact(key):
    f = _doc()["text_facts"]
    if key not in f:
        raise KRefError(f"unknown fact {key!r}; have {sorted(f)}")
    return f[key]


def fam(cell):
    return "RC" if cell.startswith("RC") else cell[0]


if __name__ == "__main__":
    d = _doc()
    print("k_reference.json loaded and validated")
    print(f"  source     : {d['source']['citation']}")
    for s in PER_INSTANCE_SIZES:
        t = table3(s)
        print(f"  table3 n{s:<3}: {len(t)} cells | run time "
              f"Joint {summary(s)['joint']['run_time']}s / LBBD {summary(s)['lbbd']['run_time']}s")
    print(f"  table4     : {len(_doc()['table4'])} pooled rows")
    t6 = ", ".join("%s n=%d gap %.1f%%" % (k, v["n"], v["gap_joint"]) for k, v in table6().items())
    print("  table6     : " + t6)
    print(f"  derived_lb(100): " + ", ".join(f"{k} {v:.1f}" for k, v in derived_lb(100).items()))
    for bad in (40, 50):
        try:
            table3(bad)
        except KRefError as e:
            print(f"  table3({bad}) correctly raises: {str(e)[:66]}...")
