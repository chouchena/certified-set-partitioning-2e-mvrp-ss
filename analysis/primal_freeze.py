"""THE FROZEN PRIMAL CONFIGURATION. One place, so the freeze is auditable rather than scattered.

Every driver imports from here. A value that appears in a driver instead of here is not frozen,
it is a local choice, and the next reader cannot tell the difference. That is the whole point.

Governed by validation/PRIMAL_FREEZE_PROTOCOL.md. Each entry below carries its evidence and its
status: FROZEN (decided, with evidence), FALLBACK (declared before the data, in force until the
trial that would change it runs) or OPEN.

--------------------------------------------------------------------------------------------
F1  STOP RULE -- FROZEN (d250, amended d254)
    WALL for production and the grid; DET for every controlled comparison.
    The grid's claim is denominated in K's wall seconds, so wall stopping makes our per-cell
    spend EXACTLY the envelope rather than an estimate. But two runs of the IDENTICAL algorithm
    on the same seed, with zero policy activity, differ by 1.65 percent (n50) and 3.66 percent
    (n100) in OPPOSITE directions -- so a wall-stopped contrast cannot resolve a 1-3 percent
    arm or variant effect. det_used is recorded either way, as a load measurement; gate G14
    enforces that and armed itself on 2026-09-22.

F2  STALL WINDOW -- FROZEN at 0.75 of each run's own budget
    Scored offline against 932 banked traces by OBJECTIVE LOST, not by firing count, because a
    stall ENDS the seed and the trace records what would have happened after any candidate
    stall point. Per size, p90 objective lost:
        window   n10      n20      n30
        0.50     0.00%    0.68%    5.87%   <- the setting in force until today
        0.60     0.00%    0.03%    6.63%
        0.75     0.00%    0.00%    0.80%   <- frozen
        0.85     0.00%    0.00%    1.57%
    0.50 was costing up to 5.87 percent at n30, which is larger than any effect we are chasing.
    The pooled p90 of 0.69 percent hid it, being dominated by n20 (421 of 528 firings).
    NOT EVIDENCED AT n50/n100: one firing apiece out of 25 and 160 traces. B degenerates to A
    there, which gate T3b tests rather than assumes.

F3  KICK WINDOW -- FALLBACK at 0.05 of budget, pending T3a
    A kick PERTURBS and continues, so it cannot be replayed offline -- it changes the
    trajectory. Calibrated instead on FIRING RATE, from 19,219 measured inter-improvement gaps:
        window   n10    n20     n30    n50    n100
        0.05     3.3%   15.4%   9.3%   4.5%   5.7%   <- in band everywhere
        0.25     ~1%    ~3%     ~3%    <1%    <1%    <- the setting that produced 0 kicks
    The 0.25 in force during the A/B/D pilot and the B-vs-D smoke sits ABOVE the p99 gap at
    n10, n50 and n100, so D could not act there by arithmetic. 8 kicks fired in 32 runs, all
    at n20, none improving.

F4  ARM -- FALLBACK to B, pending T4
    B is never worse than D on objective across 33 paired cells and strictly better on wall at
    31 of them (n10: 36.3 s vs 57.6 s for an identical answer). But that evidence is 4 paired
    cells at n20 -- a rule-of-three bound of 75 percent -- and D was tested at a kick window
    where it barely fires. B is the default on SIMPLICITY and demonstrated reliability, not on
    a measured advantage, and the paper must say so unless T4 changes it.

F5  SEEDS -- FROZEN at 5.  d66 makes mean +- SD the headline, which needs a uniform N.
F6  HARDWARE FACTOR -- FROZEN at 2.5 (d245). The strictest tested; a budget claim made at 2.5
    survives every weaker reading. Costs a median 38.7 percent of primal envelope against 2.0.

F7  FLEET OPERATOR -- FROZEN OFF (d261), on three paired seeds at R205 n20

                    mean      SD      one car on     vs baseline
        baseline   675.788   2.055      3 of 3            --
        route_merge 725.839  59.152     1 of 3         +7.41% WORSE
        route_drop  674.338    --       3 of 3         identical, 0 fires

    route_merge is a high-variance gamble: ONE win of -4.74 percent (642.216, attaining K's
    proven 642.2) against TWO losses of +13.5 percent. Its variance is 28x the baseline's. On
    the losing seeds it burned the budget (21 iterations against 165-172) and forfeited the
    one-car solution the baseline finds RELIABLY on every seed. PIPELINE.md:68 recorded this
    failure mode years before -- "route_merge REMOVED from kick (made it 16 iters/2400s)" --
    and it reproduced exactly.

    route_drop is STRUCTURALLY INERT, not under-resourced: its gate needs nCars > 1, and the
    baseline reaches one car, after which nCars-1 is below the vehicle floor and the operator
    is disabled for the rest of the run. It still cost 34 percent more wall for the identical
    165 iterations, almost certainly the _vehicle_floor bound being computed.

    THE PREMISE THAT MOTIVATED THIS TRIAL WAS ALSO FALSE (d260). "RC at n100 runs 13.33 cars
    against K's 8.75, +52.4 percent" was raw CONSTRUCTION output in my averages. The corrected
    figure on the one optimised RC cell is +2.9 percent fleet. There is no large fleet lever at
    n100: we are +6.7 percent on C and MINUS 4.3 percent on R, both fully covered.
--------------------------------------------------------------------------------------------
"""

# ---- F2 / F3: windows, as fractions of each run's OWN wall budget -------------------------
STALL_FRAC = 0.75          # FROZEN
KICK_FRAC_T = 0.05         # FALLBACK pending T3a
KICK_FRAC = 0.35           # how much of the instance a kick frees; banked portfolio value
STALL_KICKS = 2

# ---- F4 / F5 / F6 -------------------------------------------------------------------------
ARM = "B"                  # FALLBACK pending T4
N_SEEDS = 5                # FROZEN (d66)
HW_FACTOR = 2.5            # FROZEN (d245)

# ---- F7 -----------------------------------------------------------------------------------
FLEET_OP = None            # FROZEN OFF (d261): both operators FAIL on 3 paired seeds. See T1.

# ---- F1: which stop rule a given purpose takes --------------------------------------------
STOP_RULE = {"production": "wall", "comparison": "det"}


def arm_flags(arm, budget):
    """The CLI flags implementing an arm at a given wall budget. One definition, every driver.

    B  stall only -- the seed ends on a genuine stall.
    D  kick first, then stall once `stall_kicks` consecutive kicks have failed. fixopt keeps
       `best` separate across a kick, so a premature kick costs time but cannot lose the
       incumbent -- which is why the kick window is set more aggressively than the stall.
    A  neither: grind to the cap.
    """
    stall = round(STALL_FRAC * budget, 1)
    if arm == "A":
        return []
    if arm == "B":
        return ["--stall-patience", str(stall)]
    if arm == "D":
        return ["--kick-patience", str(round(KICK_FRAC_T * budget, 1)),
                "--kick-frac", str(KICK_FRAC),
                "--stall-patience", str(stall),
                "--stall-kicks", str(STALL_KICKS)]
    raise ValueError("unknown arm %r" % arm)


def fleet_flags(op):
    """Structural fleet operators. Both FROZEN OFF by d261 after failing T1 on 3 paired seeds.

    Kept callable so the trial that refuted them can be re-run, not because either is a option.
    """
    if op is None:
        return []
    if op == "route_merge":
        return ["--route-merge"]
    if op == "route_drop":
        return ["--route-drop", "--route-drop-k", "1"]
    raise ValueError("unknown fleet operator %r" % op)


def summary():
    return ("primal freeze: stall %.2f (FROZEN) | kick %.2f (fallback) | arm %s (fallback) | "
            "N %d | factor %.1f | fleet_op %s (FROZEN OFF)"
            % (STALL_FRAC, KICK_FRAC_T, ARM, N_SEEDS, HW_FACTOR, FLEET_OP))


if __name__ == "__main__":
    print(summary())
