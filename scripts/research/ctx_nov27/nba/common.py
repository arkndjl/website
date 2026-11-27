"""shared: season files and the unrounded pXPM (scripts/nba_xpm.py pxpm), point in time"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import nba_xpm as X, nba_games as N
LAST = 2026                                   # lockbox: nothing from 2026-27
F = {}
for y in range(2010, LAST + 1):
    fn = os.path.join(X.OUT, f'{y}.json')
    if os.path.exists(fn):
        d = json.load(open(fn))
        F[y] = {'g': d['games'], 'p': {p['id']: p for p in d['players'] if not p.get('pr') and p.get('oxpm') is not None}}


def pxpm_row(p, games, hist, y, aging=True):
    """pXPM from a season row p, his rows the two seasons before (hist: [row or None, row or None]) -> projects y + 1"""
    m = p['mp']; lm = math.log(1 + m * 82 / max(games, 1) / 100)
    rows = [(1.0, p)] + [(w, r) for w, r in zip(X.PXPM_W[1:], hist) if r]
    tot = 0.0
    for k, side in (('oxpm', 'o'), ('dxpm', 'd')):
        a, b = X.PXPM_MU[side]
        num, den = X.PXPM_K * (a + b * lm), X.PXPM_K
        for w, r in rows: num += w * r['mp'] * r[k]; den += w * r['mp']
        tot += num / den
    cv = N.aging_curve(y + 1) if aging else None      # pairs ending <= y
    return tot + (cv(p['age'] + 1) if cv and p.get('age') else 0.0)


def pxpm(pid, y, aging=True):
    """pXPM of season y (projects y + 1) from seasons <= y; None with no line in y"""
    p = F.get(y, {}).get('p', {}).get(pid)
    if not p: return None
    return pxpm_row(p, F[y]['g'], [F.get(y - j, {}).get('p', {}).get(pid) for j in (1, 2)], y, aging)


def tstat(d):
    d = np.asarray(d, float); return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
