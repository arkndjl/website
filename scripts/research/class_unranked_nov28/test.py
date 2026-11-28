# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Unranked commits in the CFB class score (prereg.md). Needs the nflverse draft picks and players in
scripts/.cache/statplus (as scripts/arkstars_hist.py --test). python3 test.py -> result.json"""
import json, math, os, sys
from collections import Counter, defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import arkstars_hist as A  # noqa: E402

FLOOR = 20.0
CLASSES = range(2011, 2021)


def unrated(r):
    """no service rates him: no ESPN grade, no industry or lone-service rating"""
    return not (r.get('grade') or 0) >= 60 and not r.get('ind') and not any(v for v in (r.get('svc3') or []) if v) and not r.get('g247') and not r.get('c247')


def rows():
    pack, _ = A.read_pack(); d = A.fitfile()
    for y in pack: A.score(pack[y], d)
    A.label({y: pack[y] for y in CLASSES}, A.espn_teams())
    out = defaultdict(lambda: {'lv': None, 'on': 0.0, 'off': 0.0, 'offr': 0.0, 'offu': 0, 'n_off': 0, 'n_on': 0, 'y': 0})
    seen = Counter()
    for y in CLASSES:
        for r in pack[y]:
            if 'ark' not in r or r.get('dup') or not r['tid'] or r.get('tsrc') == 'b' or not r['level']: continue
            o = out[(r['tid'], y)]; o['lv'] = r['level']; o['y'] += bool(r.get('drafted'))
            pts = max(0.0, r['x'] - FLOOR)
            if A.listed(r): o['on'] += pts; o['n_on'] += 1
            else:
                o['off'] += pts; o['n_off'] += 1
                if unrated(r): o['offu'] += 1
                else: o['offr'] += pts
            seen['listed' if A.listed(r) else ('off unrated' if unrated(r) else 'off rated')] += 1
    R = [{'t': t, 'c': c, **v} for (t, c), v in out.items()]
    return R, dict(seen)


FORMS = {
    'none': lambda r, u: [r['on']],
    'graded': lambda r, u: [r['on'] + r['off']],
    'half': lambda r, u: [r['on'] + r['offr'] + u * r['offu']],
}


def X_of(rs, f, u=0.0):
    lv = ['P4', 'G5', 'FCS']
    X = []
    for r in rs:
        s = f(r, u)[0]; row = []
        for k in lv: row += [1.0 if r['lv'] == k else 0.0, s if r['lv'] == k else 0.0]
        X.append(row)
    return np.array(X)


def ols(X, y): return np.linalg.lstsq(X, y, rcond=None)[0]


def fit_u(tr):
    """the 0.5-star tier's points a commit: the grid value with the best in-sample fit on the training classes"""
    y = np.array([r['y'] for r in tr], float); best = None
    for u in np.arange(0, 8.01, 0.25):
        X = X_of(tr, FORMS['half'], u); e = ((y - X @ ols(X, y)) ** 2).sum()
        if best is None or e < best[1]: best = (float(u), e)
    return best[0]


def held(R, form):
    err = {}
    for c in CLASSES:
        tr = [r for r in R if r['c'] != c]; te = [r for r in R if r['c'] == c]
        u = fit_u(tr) if form == 'half' else 0.0
        y = np.array([r['y'] for r in tr], float); b = ols(X_of(tr, FORMS[form], u), y)
        p = X_of(te, FORMS[form], u) @ b
        for r, q in zip(te, p): err[(r['t'], r['c'])] = (r['y'] - q) ** 2
    return err


def t_cluster(d, g):
    d = np.asarray(d); by = defaultdict(float)
    for x, k in zip(d - d.mean(), g): by[k] += x
    se = math.sqrt(sum(v * v for v in by.values())) / len(d)
    return float(d.mean() / se) if se else 0.0


def forward(R, form, cut=2017):
    tr = [r for r in R if r['c'] <= cut]; te = [r for r in R if r['c'] > cut]
    y = np.array([r['y'] for r in tr], float); yt = np.array([r['y'] for r in te], float)
    u = fit_u(tr) if form == 'half' else 0.0
    e0 = (yt - X_of(te, FORMS['none']) @ ols(X_of(tr, FORMS['none']), y)) ** 2
    e1 = (yt - X_of(te, FORMS[form], u) @ ols(X_of(tr, FORMS[form], u), y)) ** 2
    return {'n': len(te), 'd': round(float((e0 - e1).mean()), 5), 't': round(t_cluster(e0 - e1, [r['t'] for r in te]), 2), 'u': u}


def main():
    R, seen = rows()
    print('rows', len(R), seen)
    base = held(R, 'none'); keys = sorted(base); out = {'n': len(R), 'commits': seen, 'classes': [CLASSES[0], CLASSES[-1]],
                                                       'drafted': int(sum(r['y'] for r in R)), 'baseRmse': round(math.sqrt(np.mean([base[k] for k in keys])), 4), 'forms': {}}
    for f in ('graded', 'half'):
        e = held(R, f); d = np.array([base[k] - e[k] for k in keys])
        up = sum(1 for c in CLASSES if sum(base[k] - e[k] for k in keys if k[1] == c) > 0)
        out['forms'][f] = {'rmse': round(math.sqrt(np.mean([e[k] for k in keys])), 4), 'd': round(float(d.mean()), 5), 't': round(t_cluster(d, [k[0] for k in keys]), 2),
                           'up': up, 'of': len(CLASSES), 'forward': forward(R, f)}
        if f == 'half': out['forms'][f]['u'] = fit_u(R)
        out['forms'][f]['pass'] = bool(out['forms'][f]['t'] >= 2 and out['forms'][f]['forward']['d'] > 0)
    # by level: how many off-board commits and their picks
    lv = defaultdict(lambda: [0, 0, 0]);
    for r in R: lv[r['lv']][0] += r['n_on']; lv[r['lv']][1] += r['n_off']; lv[r['lv']][2] += r['offu']
    out['byLevel'] = {k: {'listed': v[0], 'off': v[1], 'offUnrated': v[2]} for k, v in lv.items()}
    ok = [f for f in out['forms'] if out['forms'][f]['pass']]
    out['pick'] = max(ok, key=lambda f: out['forms'][f]['d']) if ok else 'none'
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.path.join(HERE, 'result.json'), 'w'), indent=1)


if __name__ == "__main__" and "--explore" not in sys.argv: main()


def explore():
    """not in the prereg: the off-board points as their own term (a fitted weight), and their picks against their index"""
    R, _ = rows(); keys = None
    FORMS['two'] = lambda r, u: [r['on'], r['off']]
    lv = ['P4', 'G5', 'FCS']
    def X2(rs):
        return np.array([[v for k in lv for v in ((1.0, r['on'], r['off']) if r['lv'] == k else (0.0, 0.0, 0.0))] for r in rs])
    base = held(R, 'none'); keys = sorted(base); e = {}
    for c in CLASSES:
        tr = [r for r in R if r['c'] != c]; te = [r for r in R if r['c'] == c]
        b = ols(X2(tr), np.array([r['y'] for r in tr], float))
        for r, q in zip(te, X2(te) @ b): e[(r['t'], r['c'])] = (r['y'] - q) ** 2
    d = np.array([base[k] - e[k] for k in keys])
    b = ols(X2(R), np.array([r['y'] for r in R], float))
    w = {k: {'on': round(float(b[3 * i + 1]), 4), 'off': round(float(b[3 * i + 2]), 4)} for i, k in enumerate(lv)}
    return {'two_terms': {'d': round(float(d.mean()), 5), 't': round(t_cluster(d, [k[0] for k in keys]), 2),
                          'up': sum(1 for c in CLASSES if sum(base[k] - e[k] for k in keys if k[1] == c) > 0), 'weights': w}}


if __name__ == '__main__' and '--explore' in sys.argv:
    x = explore(); print(json.dumps(x, indent=1))
    r = json.load(open(os.path.join(HERE, 'result.json'))); r['explore'] = x; json.dump(r, open(os.path.join(HERE, 'result.json'), 'w'), indent=1)
