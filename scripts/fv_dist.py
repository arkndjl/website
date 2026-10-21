"""FV as a distribution (data/fv_dist.json, fit by scripts/fv_dist_fit.py): for a graded FV and a player's spread
group, the chance of each outcome tier, the 80% range and the expected value. Same rules as fvDist in
scripts/fv_dist.mjs and layouts/partials/fvdist.html."""
import json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIT = None


def fit():
    global _FIT
    if _FIT is None:
        try:
            _FIT = json.load(open(os.path.join(ROOT, 'data', 'fv_dist.json')))
        except (OSError, ValueError):
            _FIT = {}
    return _FIT


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def fv_dist(board, fv, z=None):
    """{'p': bin chances, 'tiers': [<30, 30s, 40s, 50s, 60+], 'p10', 'p50', 'p90', 'mean', 'ev'} or None."""
    M = fit().get(board)
    if not M or fv is None: return None
    z = z or {}
    b1, b2, b3 = M['loc']
    mu = b1 * (fv - 40) / 10 + b2 * max(0, fv - 45) / 10 + b3 * max(0, fv - 60) / 10
    s = math.exp(max(-3, min(3, sum(g * z.get(k, 0) for k, g in (M.get('scale') or {}).items()))))
    F = [ncdf((c - mu) / s) for c in M['cuts']]
    p = [max(0.0, (F[k] if k < len(F) else 1) - (F[k - 1] if k else 0)) for k in range(len(F) + 1)]
    edges = M['edges']; lo = [20] + edges; hi = edges + [80]; fl = M['floorShare']

    def q(x):
        if x <= p[0] * fl: return 20.0
        if x <= p[0]: return 20 + 10 * (x / p[0] - fl) / max(1e-9, 1 - fl)
        c = p[0]
        for j in range(1, len(p)):
            if x <= c + p[j] or j == len(p) - 1: return lo[j] + (hi[j] - lo[j]) * min(1.0, (x - c) / max(1e-12, p[j]))
            c += p[j]
        return 80.0
    tiers = [0.0] * 5
    for j, v in enumerate(p): tiers[min(4, max(0, (lo[j] - 20) // 10))] += v
    bv = M.get('binValue')
    return {'p': p, 'tiers': tiers, 'p10': q(0.1), 'p50': q(0.5), 'p90': q(0.9), 'mean': sum(v * m for v, m in zip(p, M['binMean'])),
            'ev': sum(v * m for v, m in zip(p, bv)) if bv else None}
