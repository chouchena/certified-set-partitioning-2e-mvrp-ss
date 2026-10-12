"""
aggregate_results.py -- authoritative current best-of table, self-contained gaps.

Best VERIFIED incumbent per cell (from fixopt run logs) + best PROVEN block_relax
per cell (from the descend JSONs). Computes our_LB% = (our_UB - our_LB)/our_UB.
Karademir's numbers shown side-by-side, never as a denominator.
"""
from __future__ import annotations
import glob, json, re, os

LOOSE = ["C203", "C204", "R203", "R204", "R207", "R208", "R211",
         "RC202", "RC203", "RC204", "RC208"]

K = {  # Karademir |C|=20: (Joint BK, Joint Gap%, LBBD BK)
    "C203": (682.7, 54, 676.3), "C204": (683.5, 57, 668.1),
    "R203": (638.4, 37, 635.8), "R204": (605.7, 42, 605.7),
    "R207": (601.7, 36, 605.4), "R208": (549.9, 37, 549.9),
    "R211": (669.1, 48, 584.4), "RC202": (906.4, 44, 906.4),
    "RC203": (754.3, 56, 767.6), "RC204": (642.4, 50, 642.4),
    "RC208": (881.6, 65, 858.7),
}

# every place a verified fixopt final can appear
INCUMBENT_SOURCES = [
    "validation/pipeline_fixopt.log", "validation/kick_smoke.log",
    "validation/akick_c204_rc203.log", "validation/fixopt_n20_3mode.log",
] + glob.glob("validation/on_*.log") + glob.glob("validation/ms_*.log") \
  + glob.glob("validation/akick_*.log") + glob.glob("validation/rc203_opt*.log") \
  + glob.glob("validation/rc203_rmerge_*.log")

# cell token: bounded so R203 != RC203, C204 != RC204
def cell_re(c):
    return re.compile(rf"(?<![A-Za-z0-9]){c}(?![A-Za-z0-9])")


def _section_bounds(txt, c):
    """(start,end) offsets of each block clearly belonging to cell c: a header
    line naming c, up to the next header or EOF."""
    hdr = re.compile(r"(?:instance|rseg|fixopt rseg|adaptive-kick|kick smoke|"
                     r"\[A joint-direct\]|===|PAIR|--cell)\s+([A-Z]{1,2}\d{3})")
    marks = [(m.start(), m.group(1)) for m in hdr.finditer(txt)]
    spans = []
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(txt)
        if name == c:
            spans.append((pos, end))
    return spans


_ORD = sorted(LOOSE, key=len, reverse=True)  # RC203 before R203


def _file_cell(base):
    """the cell a single-cell log belongs to, or None for multi-cell logs."""
    b = base.lower()
    if b.startswith("rc203_opt") or b.startswith("rc203_rmerge"):
        return "RC203"
    for c in _ORD:
        cl = c.lower()
        if re.search(rf"(?:^|[_/])(?:on|ms|fixopt|waivee|akick)_{cl}(?:_|\.)", b) \
           or b == f"akick_{cl}.log":
            return c
    return None


MULTI = {"validation/pipeline_fixopt.log", "validation/kick_smoke.log", "validation/fixopt_n20_3mode.log"}


def best_incumbent(c):
    best, src = None, None
    for f in sorted(set(INCUMBENT_SOURCES)):
        if not os.path.exists(f):
            continue
        try:
            txt = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        base = os.path.basename(f)
        fc = _file_cell(base)
        if f.replace("\\", "/") in MULTI or fc is None:
            chunks = [txt[s:e] for (s, e) in _section_bounds(txt, c)]
        elif fc == c:
            chunks = [txt]
        else:
            continue
        for ch in chunks:
            for m in re.finditer(r"final best \(verified\)\s*=\s*([\d.]+)", ch):
                v = float(m.group(1))
                if best is None or v < best:
                    best, src = v, base
    return best, src


def best_bound(c):
    best, k = None, None
    for f in glob.glob("crossfeed/easy_reduction*.json"):
        b = os.path.basename(f)
        if not re.search(rf"_{c}_n20\.json$", b):
            continue
        try:
            rows = json.load(open(f, encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for r in rows:
            if r.get("proven") and r.get("block_relax") is not None:
                if best is None or r["block_relax"] > best:
                    best, k = r["block_relax"], r["k"]
    return best, k


if __name__ == "__main__":
    print(f"{'cell':6} {'ourLB':>8} {'k*':>3} {'ourUB':>8} {'LB%':>6} "
          f"{'K_bnd':>7} {'K_inc':>7} {'K_gap%':>7} {'UBvsK':>7} {'xKbnd':>6}  src")
    ogs, dis, dbs = [], [], []
    for c in LOOSE:
        ub, usrc = best_incumbent(c)
        lb, lk = best_bound(c)
        jbk, jgap, lbbd = K[c]
        kb = round(jbk * (1 - jgap / 100), 1)
        ki = min(jbk, lbbd)
        og = (ub - lb) / ub * 100 if (ub and lb) else None
        kg = (ki - kb) / ki * 100
        di = (ub - ki) / ki * 100 if ub else None
        db = lb / kb if lb else None
        if og is not None:
            ogs.append(og)
        if di is not None:
            dis.append(di)
        if db:
            dbs.append(db)
        print(f"{c:6} {lb or 0:8.2f} {str(lk):>3} {ub or 0:8.2f} {og or 0:6.1f} "
              f"{kb:7.1f} {ki:7.1f} {kg:7.1f} {di or 0:+7.1f} {db or 0:6.2f}  {usrc or '-'}")
    print(f"\nmean LB% {sum(ogs)/len(ogs):.1f}   "
          f"mean UB vs K_inc {sum(dis)/len(dis):+.2f}%   "
          f"mean bound xK {sum(dbs)/len(dbs):.2f}   "
          f"wins {sum(1 for d in dis if d < 0)}/{len(dis)}   "
          f"LB%<10 {sum(1 for g in ogs if g < 10)}/{len(ogs)}")
