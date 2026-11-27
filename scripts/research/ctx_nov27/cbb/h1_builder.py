#!/usr/bin/env python3
"""H1 (prereg.md): the team builder's next-season player value. Now = season-end xXPM + class change; candidate = pXPM
board form after the season. Target next-season rXPM, weighted by next-season minutes.  -> h1.json"""
import csv, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cbb_xpm_hist as XH
KIT = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit/college_seasons_nba.csv')
KB = {'ret': 583.0, 'new': 259.0}      # data/cbb_live_fit.json kb


def tstat(d):
    d = np.asarray(d, float)
    return float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if len(d) > 1 and d.std(ddof=1) > 0 else 0.0


def load():
    H = XH.load(); cls = {}
    for r in csv.DictReader(open(KIT, newline='')):
        try: k = (str(int(float(r['pid']))), int(r['year'])); mp = float(r['min_per'] or 0)
        except ValueError: continue
        if k not in cls or mp > cls[k][1]: cls[k] = (r['yr'], mp)
    return H, cls


def xx_end(H, pid, y, new_mu):
    """the board's xXPM at season end (cbb_live's blend with no games left)"""
    q = H[(pid, y)]; n = q['e']; p = H.get((pid, y - 1))
    kb = KB['ret' if p else 'new']; xb0 = p['px2'] if p else new_mu
    rate = (xb0 * kb + q['xpm'] * n) / (kb + n)
    return (q['xpm'] * n + rate * kb) / (n + kb)


def main():
    H, cls = load()
    years = sorted({y for _, y in H})
    dev_pairs = defaultdict(lambda: defaultdict(list)); new_x = defaultdict(lambda: [0.0, 0.0])
    for (pid, y), q in H.items():
        if (pid, y - 1) not in H: new_x[y][0] += q['e'] * q['xpm']; new_x[y][1] += q['e']
        nx = H.get((pid, y + 1)); c = cls.get((pid, y)); c1 = cls.get((pid, y + 1))
        if nx and c and c1 and c[1] >= 20 and c1[1] >= 20: dev_pairs[y][c[0]].append(nx['bpm'] - q['bpm'])
    res = []
    for y in range(2014, 2025):
        dv = defaultdict(list)
        for p in range(2011, y):            # pairs (p, p + 1) known before the offseason after y
            for c, v in dev_pairs[p].items(): dv[c] += v
        dev = {c: float(np.mean(v)) for c, v in dv.items()}
        nm = sum(new_x[k][0] for k in years if k < y and k > years[0]) / max(1.0, sum(new_x[k][1] for k in years if k < y and k > years[0]))
        a, b, raw, t, w, g = [], [], [], [], [], []
        for (pid, yy), q in H.items():
            if yy != y or not q['e']: continue
            nx = H.get((pid, y + 1)); c = cls.get((pid, y))
            if not nx or not nx['e'] or not c: continue
            d = dev.get(c[0], 0.5)
            a.append(xx_end(H, pid, y, nm) + d); raw.append(q['xpm'] + d); b.append(q['px2']); t.append(nx['xpm']); w.append(nx['e'])
            c1 = cls.get((pid, y + 1)); g.append(bool(c1 and c[1] >= 20 and c1[1] >= 20))
        a, b, raw, t, w, g = map(np.array, (a, b, raw, t, w, g))
        ws = lambda p: float((w * (p - t) ** 2).sum() / w.sum())
        res.append({'pair': f'{y}->{y + 1}', 'n': len(t), 'now': ws(a), 'raw': ws(raw), 'cand': ws(b), 'dev': {k: round(v, 2) for k, v in dev.items() if k in ('Fr', 'So', 'Jr', 'Sr')},
                    'g_now': float(np.sqrt(((a - t)[g] ** 2).mean())), 'g_cand': float(np.sqrt(((b - t)[g] ** 2).mean())), 'g_n': int(g.sum()),
                    'bias_now': float((w * (a - t)).sum() / w.sum()), 'bias_cand': float((w * (b - t)).sum() / w.sum())})
        print(res[-1]['pair'], res[-1]['n'], round(res[-1]['now'] ** .5, 3), round(res[-1]['raw'] ** .5, 3), round(res[-1]['cand'] ** .5, 3), round(res[-1]['g_now'], 3), round(res[-1]['g_cand'], 3))
    d = np.array([r['now'] - r['cand'] for r in res]); gd = np.array([r['g_now'] - r['g_cand'] for r in res])
    out = {'pairs': res, 'rmse_now': round(float(np.mean([r['now'] for r in res]) ** .5), 3), 'rmse_raw_plus_dev': round(float(np.mean([r['raw'] for r in res]) ** .5), 3),
           'rmse_cand': round(float(np.mean([r['cand'] for r in res]) ** .5), 3), 't': round(tstat(d), 2), 'k': int((d > 0).sum()), 'n': len(d),
           'guard_rmse_now': round(float(np.mean([r['g_now'] for r in res])), 3), 'guard_rmse_cand': round(float(np.mean([r['g_cand'] for r in res])), 3),
           'guard_t': round(tstat(gd), 2), 'guard_k': int((gd > 0).sum())}
    print({k: v for k, v in out.items() if k != 'pairs'})
    json.dump(out, open(os.path.join(HERE, 'h1.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
