"""Best-known n100 objective per cell across every banked artifact directory (the d374 table was an
inline scan; this is its generating code). An artifact counts if it is a JSON dict with objVal
and nCars, names a cell, and is at n100 (filename carries n100, or size == 100). Verified means
it carries a verifier3 recomputation (_verifier_recomputed) or a PASS marker; unstamped means no
_provenance block (CLAUDE.md: code_hash is the anchor -- such rows are listed, flagged, and must
be re-run under a stamping harness before they are cited).

    python analysis/bks_n100.py [--include-unverified]
Writes runs/oracle/bks_n100.json.
"""
import argparse
import glob
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = ["runs/postpass", "runs/trial_F5", "runs/trial_F6", "runs/trial_F7", "runs/trial_C2", "runs/grid",
        "runs/v2batch_R_n100", "runs/alloc_abd", "runs/tep", "runs/tsc", "analysis"]
CELLS = ["C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208",
         "R201", "R202", "R203", "R204", "R205", "R206", "R207", "R208", "R209", "R210", "R211",
         "RC201", "RC202", "RC203", "RC204", "RC205", "RC206", "RC207", "RC208"]
K_FAMILY_LBBD = {"C": 3857.2, "R": 3720.9, "RC": 4810.6}   # lower of K's two family means (d347)
try:
    PROBE = json.load(io.open(os.path.join(ROOT, "analysis", "chaining_probe.json"), encoding="utf-8"))
except Exception:
    PROBE = {}


def scan(include_unverified):
    rows = []
    for d in DIRS:
        for f in glob.glob(os.path.join(ROOT, d, "*.json")):
            base = os.path.basename(f)
            m = re.search(r"(RC|R|C)(2\d\d)", base)      # 201-211 (the first draft's 20\d hid R210/R211)
            if not m:
                continue
            cell = m.group(1) + m.group(2)
            if "n100" not in base and "_n100" not in base:
                pass
            try:
                a = json.load(io.open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(a, dict) or "objVal" not in a or "nCars" not in a:
                continue
            size = a.get("size") or a.get("_size") or (100 if "n100" in base else None)
            if size != 100:
                continue
            v = a.get("_verifier")
            # fixopt's --dump-best writes only a best that passed verifier3 ("verify=OK (recomputed ...)")
            # and marks it _verifier == "verifier3"; TEP/assembly artifacts carry _verifier_recomputed.
            verified = ((a.get("_verifier_recomputed") is not None) or (a.get("verify") == "PASS") or (a.get("_verified") is True)
                        or (isinstance(v, str) and v.startswith("verifier3"))
                        or (isinstance(v, dict) and (v.get("ok") is True or str(v.get("status", "")).upper() == "PASS" or str(v.get("verdict", "")).upper() == "PASS")))
            if base.startswith("chain_") and d == "analysis":
                # post-pass artifacts carry no marker; the census record does (verify == PASS)
                probe = PROBE.get(cell) or {}
                verified = probe.get("verify") == "PASS" and abs(float(probe.get("s2_obj", -1)) - float(a["objVal"])) < 1e-6
            if not verified and not include_unverified:
                continue
            stamped = isinstance(a.get("_provenance"), dict) or bool(a.get("_code_hash"))
            rows.append(dict(cell=cell, obj=float(a["objVal"]), cars=int(a["nCars"]), verified=bool(verified), stamped=stamped, file=os.path.relpath(f, ROOT).replace("\\", "/")))
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--include-unverified", action="store_true"); a = ap.parse_args()
    rows = scan(a.include_unverified)
    best = {}
    for r in rows:
        if r["cell"] not in best or r["obj"] < best[r["cell"]]["obj"]:
            best[r["cell"]] = r
    print("%-6s %9s %5s %-3s %-3s  %s" % ("cell", "BKS", "cars", "ver", "stp", "source"))
    fam = {}
    for c in CELLS:
        b = best.get(c)
        if b:
            print("%-6s %9.1f %5d %-3s %-3s  %s" % (c, b["obj"], b["cars"], "y" if b["verified"] else "n", "y" if b["stamped"] else "N", b["file"]))
            fam.setdefault(c.rstrip("0123456789"), []).append(b["obj"])
        else:
            print("%-6s %9s" % (c, "-"))
    for f, v in sorted(fam.items()):
        print("family %-3s mean of BKS %8.1f over %d cells  vs K family bound %8.1f  (%+.1f%%)" % (f, sum(v) / len(v), len(v), K_FAMILY_LBBD[f], 100.0 * (sum(v) / len(v) / K_FAMILY_LBBD[f] - 1)))
    unst = [c for c in CELLS if best.get(c) and not best[c]["stamped"]]
    if unst:
        print("UNSTAMPED best rows (re-run under a stamping harness before citing): %s" % " ".join(unst))
    # coverage assertion: every cell has a seed-0 grid artifact, so a missing row is a scan
    # defect (the first draft's regex hid R210/R211), never a fact about the cell
    missing = [c for c in CELLS if c not in best]
    json.dump(dict(best=best, n_rows=len(rows), missing=missing), io.open(os.path.join(ROOT, "runs", "oracle", "bks_n100.json"), "w", encoding="utf-8"), indent=1)
    if missing:
        print("COVERAGE FAILURE: no artifact matched for %s -- fix the scan before reading the table" % " ".join(missing))
        sys.exit(2)


if __name__ == "__main__":
    main()
