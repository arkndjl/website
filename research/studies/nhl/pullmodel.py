"""Markov model of the end of regulation for a trailing team (per-second steps).
rates: dict with per-60 goal rates:
  r0       : each team's 5v5 rate when tied late
  a5[d],b5[d] : trailing team's 5v5 GF and GA per 60 when down d (goalies in)
  a6[d],b6[d] : trailing team's GF and GA per 60 with net empty (6v5) when down d
Value = P(trailing team is level or ahead at 60:00)."""
import numpy as np
DMAX = 4

def solve(rates, S, tau=None, optimal_for=(1, 2, 3, 4)):
    """tau: dict d -> pull threshold in seconds left (pull when s <= tau[d]). For d not in tau: optimal policy.
    Returns V[s, d] for s=0..S, d=0..DMAX, and optimal thresholds (largest s at which pulling is optimal)."""
    tau = tau or {}
    p = lambda r: r / 3600.0
    V = np.zeros((S + 1, DMAX + 1)); V[0, 0] = 1.0
    best = {d: 0 for d in range(1, DMAX + 1)}
    r0 = p(rates["r0"])
    for s in range(1, S + 1):
        prev = V[s - 1]
        V[s, 0] = r0 * 1.0 + r0 * prev[1] + (1 - 2 * r0) * prev[0]
        for d in range(1, DMAX + 1):
            dd = min(d, 2)
            up = prev[d + 1] if d < DMAX else prev[DMAX]
            def val(a, b):
                a, b = p(a), p(b)
                return a * prev[d - 1] + b * up + (1 - a - b) * prev[d]
            vn = val(rates["a5"][dd], rates["b5"][dd])
            vp = val(rates["a6"][dd], rates["b6"][dd])
            if d in tau:
                V[s, d] = vp if s <= tau[d] else vn
            else:
                V[s, d] = max(vp, vn)
            if vp > vn: best[d] = s
    return V, best
