"""
Standing guard: which CLAIMS embed numbers whose inputs have since changed?

THE GAP THIS CLOSES (found 2026-09-13). We built guards for artifacts -- `join_freshness.py`
for stored joins, `ab_grid_build.py --verify` for the grid, `gurobi_validity_check.py` for the
validity anchoring. **Nothing guarded the claims themselves**, and a claim is the last link in
the provenance chain: instance data -> code -> artifact -> derived join -> CLAIM.

Adopting TW arc pruning changed `ab_code_hash` from 4897cede2c185f22 to 4134cf4a2559c9d8. Every
claim whose numbers were computed under the old hash silently went stale, including the HEADLINE
(`ab-tightens-k-published-gaps` still said "23 of 54"; the current figure is 24/54).

This cannot auto-verify prose. What it CAN do is flag every claim whose declared inputs have
moved, so a human re-derives those and only those.

    python analysis/claims_freshness.py           # report
    python analysis/claims_freshness.py --stamp   # record current input hashes on STANDING claims

Exit 0 clean, 2 if any claim's inputs changed since it was stamped, 1 if it cannot run.
"""
import os, re, sys, json, argparse
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAIMS = os.path.join(ROOT, "validation", "claims.json")

# Artifacts whose content defines a claim's numbers, and how to read their current identity.
SOURCES = {
    "ab_grid": ("runs/ab_grid_provenanced.json",
                lambda d: d["provenance"]["ab_code_hash"]),
    "ab_wls": ("runs/ab_wls_provenanced.json",
               lambda d: d["provenance"]["ab_code_hash"]),
}

# A claim depends on a source if its text mentions any of these.
TRIGGERS = {
    "ab_grid": (r"\bab4\b|arithmetic bound|ab_grid|crossover|AB /|AB/|AB beats|"
                r"tighten|dominated at n20"),
    "ab_wls": r"ab_wls|WLS sweep|wls sweep",
}


def current():
    out = {}
    for name, (rel, get) in SOURCES.items():
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            try:
                out[name] = get(json.load(open(p, encoding="utf-8")))
            except Exception:
                out[name] = None
    return out


def depends(claim, src):
    txt = (claim.get("claim", "") + " " + claim.get("value", "") + " "
           + claim.get("source", ""))
    return bool(re.search(TRIGGERS[src], txt, re.I))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", action="store_true",
                    help="record current input hashes on STANDING claims (maintainer use, "
                         "ONLY after their numbers have been re-derived)")
    a = ap.parse_args()
    rows = json.load(open(CLAIMS, encoding="utf-8"))
    cur = current()
    if not cur:
        print("no provenanced AB artifacts found -- cannot check. NOT a pass.")
        return 1

    print("=" * 74)
    print("CLAIMS FRESHNESS -- do any claims rest on inputs that have since changed?")
    print("=" * 74)
    print("current input identities: " + ", ".join(f"{k}={v}" for k, v in cur.items()))
    print()

    stale, unstamped, ok = [], [], 0
    for r in rows:
        if r.get("status") != "STANDING":
            continue
        deps = [s for s in SOURCES if depends(r, s)]
        if not deps:
            continue
        rec = r.get("input_hashes") or {}
        for s in deps:
            if s not in rec:
                unstamped.append((r["id"], s))
            elif rec[s] != cur.get(s):
                stale.append((r["id"], s, rec[s], cur.get(s)))
            else:
                ok += 1

    if stale:
        print(f"STALE -- inputs changed since the claim was stamped ({len(stale)}):")
        for cid, s, was, now in stale:
            print(f"   {cid}\n      {s}: stamped {was} -> now {now}")
        print()
    if unstamped:
        print(f"UNSTAMPED -- depends on an artifact but records no input hash ({len(unstamped)}):")
        for cid, s in sorted(set(unstamped)):
            print(f"   {cid}  ({s})")
        print("   These cannot be checked. Re-derive their numbers, then --stamp.")
        print()
    print(f"verified current: {ok}")
    print("-" * 74)

    if a.stamp:
        n = 0
        for r in rows:
            if r.get("status") != "STANDING":
                continue
            deps = [s for s in SOURCES if depends(r, s)]
            if deps:
                r.setdefault("input_hashes", {}).update({s: cur.get(s) for s in deps})
                n += 1
        json.dump(rows, open(CLAIMS, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print(f"STAMPED {n} claims with current input hashes.")
        print("This asserts their numbers ARE current. Only run it after re-deriving them.")
        return 0

    if stale or unstamped:
        print("Do NOT quote an unstamped or stale claim without re-deriving its numbers.")
        return 2
    print("All dependent claims rest on current inputs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
