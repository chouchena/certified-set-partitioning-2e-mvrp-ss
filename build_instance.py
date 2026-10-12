"""
Faithful instance builder with a choice of transfer duration tau.

The inherited instanceGenerator.GenerateProblem() forces self.TransferDuration
to 0 three times, so every generated instance runs with tau = 0 regardless of
the paper's stated "tau = ceil(2 * mean customer service)". This helper rebuilds
the instance the way the code WOULD produce it if those three lines were absent,
for a given tau:
  - AddCDC computes tau (or we override it)
  - AddSatellites sets satellite serviceTime = tau
  - UpdateTWs folds tau into max_return (CDC/garage/satellite latest)
Set_cost_coefficients is called exactly once here (it mutates travelcostwater
with *=, so callers must NOT call it again).
"""
import math
import instanceGenerator as IG


def build(name, size, wls=0.1, tau="code", proximity=0.0, time_limit=600):
    """tau: 'code' -> 0 (inherited behaviour);
            'formula' -> ceil(2 * mean customer service);
            a number -> that value."""
    orig_gp = IG.instance.GenerateProblem

    def gp_keep_tau(self):
        self.AddCDC()                       # sets self.TransferDuration = ceil(2*mean svc)
        formula_tau = self.TransferDuration
        if tau == "code":
            self.TransferDuration = 0
        elif tau == "formula":
            self.TransferDuration = formula_tau
        else:
            self.TransferDuration = float(tau)
        self.AddSatellites()                # satellite serviceTime = self.TransferDuration
        self._resolved_tau = self.TransferDuration
        self.CreateDistMatrix()
        self.UpdateTWs()                    # max_return uses self.TransferDuration

    IG.instance.GenerateProblem = gp_keep_tau
    try:
        p = IG.readGenerate(name if name.endswith(".json") else name + ".json",
                            size, timeLimit=time_limit, problem_type="2eVRP",
                            closeness=proximity)
    finally:
        IG.instance.GenerateProblem = orig_gp

    p.costScenario = wls
    p.update_rule = [False, False]
    p.Set_cost_coefficients()               # exactly once
    return p
