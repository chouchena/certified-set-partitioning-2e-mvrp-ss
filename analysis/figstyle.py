"""Shared figure style. AOR/Springer artwork requirements, applied once.

PUBLISHER REQUIREMENTS these settings implement (paper/AOR_SUBMISSION_CHECKLIST.md section 5,
quoted from the journal's own submission guidelines):

  * lettering in HELVETICA or ARIAL -- matplotlib's default DejaVu Sans is neither
  * lettering sized 2-3 mm, i.e. 8-12 pt, and CONSISTENT across all artwork
  * vector formats preferred (EPS); we emit PDF + EPS + a PNG for quick viewing
  * colour is free online; submit RGB
  * captions live in the MANUSCRIPT text file, not in the figure -- so no suptitle here

DESIGN INTENT. These are result figures for a computational-study submission. The venue anchor
(K's own Figures 4 and 5) is managerial and uncluttered: few series, direct labelling, no
chartjunk. A figure that plots solver internals has to carry a reader-facing message to belong,
so each figure here states one claim and is built to make that claim legible at print size.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGDIR = os.path.join(ROOT, "paper", "figures")

# Family colours: colour-blind safe, and distinguishable in greyscale by lightness.
FAMILY = {"C": "#1b6ca8", "R": "#d1495b", "RC": "#2e8b57"}
MARKER = {"C": "o", "R": "s", "RC": "^"}
GREY = "#5a5a5a"
LIGHT = "#c8c8c8"


def _pick_font():
    """Helvetica or Arial, per the guidelines. Fall back loudly rather than silently."""
    have = {f.name for f in font_manager.fontManager.ttflist}
    for want in ("Helvetica", "Arial", "Liberation Sans", "Nimbus Sans"):
        if want in have:
            return want, (want in ("Helvetica", "Arial"))
    return "DejaVu Sans", False


def apply(base=9):
    name, compliant = _pick_font()
    if not compliant:
        print(f"  [warn] neither Helvetica nor Arial found; using {name!r}. "
              f"The submitted artwork MUST be re-rendered with a compliant font.")
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [name, "Arial", "Helvetica", "DejaVu Sans"],
        "font.size": base,                 # 8-12 pt window
        "axes.titlesize": base + 1,
        "axes.labelsize": base,
        "xtick.labelsize": base - 1,
        "ytick.labelsize": base - 1,
        "legend.fontsize": base - 1,
        "axes.linewidth": 0.7,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#e6e6e6",
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "lines.linewidth": 1.4,
        "lines.markersize": 4.5,
        "legend.frameon": False,
        "figure.dpi": 150,
        "savefig.dpi": 600,                # >= the 600 dpi combination-art requirement
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "pdf.fonttype": 42,                # embed as TrueType, not Type 3
        "ps.fonttype": 42,
    })
    return name


def save(fig, stem, sources=None):
    """Write the artwork AND a provenance sidecar.

    THE SAME RULE AS NUMBERS: a figure that cannot say which code and which artifacts produced
    it is not reproducible, and a reader cannot tell whether it matches the text beside it.
    Each figure therefore gets `<stem>.prov.json` carrying the generating script, the code
    hash, the commit, and the artifact families it consumed.

    `sources` names the artifact globs this figure reads, so a reader can find the inputs
    without reverse-engineering the script.
    """
    import sys, json, datetime, subprocess
    os.makedirs(FIGDIR, exist_ok=True)
    out = []
    for ext in ("pdf", "eps", "png"):
        p = os.path.join(FIGDIR, f"{stem}.{ext}")
        try:
            fig.savefig(p)
            out.append(os.path.relpath(p, ROOT))
        except Exception as e:
            print(f"  [warn] could not write {ext}: {e}")
    plt.close(fig)

    prov = dict(figure=stem, generated_by="analysis/make_figures.py",
                sources=sources or [], outputs=out,
                generated_at=datetime.datetime.now(datetime.timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                python=sys.version.split()[0], font=plt.rcParams["font.sans-serif"][0])
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        if os.path.join(ROOT, "analysis") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "analysis"))
        from provenance import _git, _code_hash                   # noqa: E402
        prov["git"] = _git()
        ch = _code_hash()
        prov["code_hash"] = ch[0] if isinstance(ch, (tuple, list)) else ch
    except Exception as e:
        prov["code_hash_error"] = f"{type(e).__name__}: {e}"
        try:
            prov["git"] = dict(sha=subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                text=True).stdout.strip())
        except Exception:
            prov["git"] = None
    pj = os.path.join(FIGDIR, f"{stem}.prov.json")
    json.dump(stamped(prov, __file__), open(pj, "w"), indent=1, default=str)
    out.append(os.path.relpath(pj, ROOT))
    print("  wrote " + ", ".join(out))
    return out


def family_of(cell):
    return "RC" if cell.startswith("RC") else cell[0]
