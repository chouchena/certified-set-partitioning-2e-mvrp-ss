"""
crossfeed/ — deeper coupling of the dual bound with the LBBD, per the
roadmap Phase 3b/3a sequence.

  #4  lagrangian_subproblem + subgradient : optimize the Lagrangian dual
      of the satellite-assignment coupling (hubAssignment), instead of
      reading LP-relaxation duals at one incumbent (what Karademir do).
  #5  multiplier pool : carry the optimal multipliers node-to-node.

All bounds produced here must clear the validity check (rule 3, roadmap
Phase 2.3) before being reported.
"""
