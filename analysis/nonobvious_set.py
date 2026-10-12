"""Materialize the freeze-evaluation instance frame + K denominators from paper/paper-reference-data.md.
Emits validation/nonobvious_set.csv: one row per (cell,size) for n10/n20/n30 with
Joint BK/Gap%/IncT, LBBD BK/IncT, K_min=min(Joint,LBBD), the winning-method IncT (primary RT ref),
K_combined_IncT=Joint+LBBD (strict RT ref), and obvious flag (Joint Gap%==0 => provable, skip).
This is the FIXED denominator for the freeze eval (primal-freeze-criterion). Provenance-clean: parsed,
not transcribed. n50/n100 excluded (K pooled, no per-cell denominator)."""
import csv, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "paper", "paper-reference-data.md")
OUT = os.path.join(ROOT, "validation", "nonobvious_set.csv")


def _num(s):
    return float(s.replace("*", "").replace("−", "-").strip())


def parse():
    rows = []
    size = None
    for line in open(REF, encoding="utf-8"):
        m = re.search(r"\|C\|\s*=\s*(\d+)", line)
        if m:
            size = int(m.group(1)); continue
        if size is None or "|" not in line:
            continue
        t = [x.strip() for x in line.split("|")]
        if size == 10:
            for j in range(len(t) - 1):
                if re.fullmatch(r"[CR]C?\d{3}", t[j]):
                    try:
                        bk = _num(t[j + 1])
                    except ValueError:
                        continue
                    rows.append(dict(cell=t[j], size=10, joint_bk=bk, joint_gap=0.0,
                                     joint_inct=None, lbbd_bk=bk, lbbd_inct=None,
                                     k_min=bk, k_min_inct=None, k_combined_inct=None, obvious=True))
        else:
            if len(t) >= 8 and re.fullmatch(r"[CR]C?\d{3}", t[1]):
                try:
                    jbk, gap, jinct = _num(t[2]), _num(t[3]), _num(t[4])
                    lbk, linct = _num(t[5]), _num(t[7])
                except (ValueError, IndexError):
                    continue
                kmin = min(jbk, lbk)
                kmin_inct = linct if lbk < jbk else (jinct if jbk < lbk else min(jinct, linct))
                rows.append(dict(cell=t[1], size=size, joint_bk=jbk, joint_gap=gap, joint_inct=jinct,
                                 lbbd_bk=lbk, lbbd_inct=linct, k_min=kmin, k_min_inct=kmin_inct,
                                 k_combined_inct=jinct + linct, obvious=(gap == 0.0)))
    return rows


def main():
    rows = parse()
    flds = ["cell", "size", "joint_bk", "joint_gap", "joint_inct", "lbbd_bk", "lbbd_inct",
            "k_min", "k_min_inct", "k_combined_inct", "obvious"]
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=flds); w.writeheader()
        for r in rows:
            w.writerow(r)
    nonobv = [r for r in rows if not r["obvious"]]
    print(f"wrote {len(rows)} (cell,size) rows -> {os.path.relpath(OUT, ROOT)}")
    for size in sorted(set(r["size"] for r in rows)):
        S = [r for r in rows if r["size"] == size]
        no = [r for r in S if not r["obvious"]]
        print(f"  |C|={size}: {len(S)} cells, {len(no)} NON-OBVIOUS (freeze frame)"
              + (f" -> {sorted(r['cell'] for r in no)}" if no and size != 10 else ""))
    print(f"TOTAL non-obvious frame (n20+n30): {sum(1 for r in nonobv if r['size'] in (20,30))} cells")


if __name__ == "__main__":
    main()
