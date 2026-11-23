"""Shared pieces for the Nov 23 mock driver tests: the gate (paired one-sided t, Holm) and small helpers."""
import math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
OUT = HERE


def pnorm_upper(t): return 0.5 * math.erfc(t / math.sqrt(2))


def paired(base_loss, new_loss, groups):
    """per-row gain d = base - new (positive = driver helps): mean, one-sided t and p, groups won."""
    d = np.asarray(base_loss) - np.asarray(new_loss)
    g = np.asarray(groups)
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std() > 0 else 0.0
    won = {}
    for k in sorted(set(g.tolist())):
        won[k] = float(d[g == k].mean())
    return {'gain': float(d.mean()), 't': round(t, 2), 'p': pnorm_upper(t), 'won': sum(v > 0 for v in won.values()), 'of': len(won),
            'perDraft': {str(k): round(v, 5) for k, v in won.items()}}


def holm(tests, alpha=0.05):
    """tests: list of dicts with 'p'; adds 'holm' (pass/fail at alpha) and 'pAdj'."""
    o = sorted(range(len(tests)), key=lambda i: tests[i]['p'])
    m = len(tests); stop = False; run = 0.0
    for r, i in enumerate(o):
        adj = min(1.0, (m - r) * tests[i]['p']); run = max(run, adj)
        tests[i]['pAdj'] = round(run, 5)
        if tests[i]['p'] > alpha / (m - r): stop = True
        tests[i]['holm'] = not stop
    for t in tests:
        t['pass'] = bool(t['holm'] and t['gain'] > 0 and t['won'] * 2 > t['of'])
        t['p'] = round(t['p'], 6)
    return tests


def ridge(X, y, lam=1.0):
    I = np.eye(X.shape[1]); I[0, 0] = 0
    return np.linalg.solve(X.T @ X + lam * I, X.T @ y)
