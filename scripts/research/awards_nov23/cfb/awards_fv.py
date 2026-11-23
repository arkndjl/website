# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Awards -> FV (pre-registered in prereg.md, tests 32-33): does a season-end, held-out award probability add to the CFB
board's FV as a driver of its outcome?

  drv_heis  P(Heisman top 4) from the Heisman voter model fit leaving that season out (Plackett-Luce top 4 of the
            model's utilities, Gumbel draws); its columns hold no FV
  drv_pos   P(win) of his position award (O'Brien QB, Doak RB, Biletnikoff WR, Mackey TE, Nagurski EDGE/DT/LB), the
            Nov 14 columns, fit leaving that season out

Rows: scripts/data/cfb_alltime_rows.json.gz last seasons (final) whose draft is 2015-23 (undrafted: class = last + 1).
Driver z = log(1 + p / .01). Candidate fm' = fm + w z / b, with AV ~ position intercept + b fm + w z fit on the
training classes (leave one draft class out). Scored per held-out class: mean within-position Pearson r of the grade with
AV a season, and the top 32 of the class by grade (mean AV). Pass: one-sided paired t over classes clears Holm (2 tests),
gain > 0, most classes won, top 32 not worse.

    python3 scripts/research/awards_nov23/cfb/awards_fv.py      (needs the ESPN history pool: awards_football.py cfb)"""
import collections, gzip, json, math, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import numpy as np
import awards_engine as E
import awards_football as F
import awards_football_more as M
import names as NM
from awards_research import t_sf, holm

POS_AW = {'QB': 'obrien', 'RB': 'doak', 'WR': 'bilet', 'TE': 'mackey', 'EDGE': 'nagurski', 'DL': 'nagurski', 'LB': 'nagurski'}
FIT = json.load(open(os.path.join(ROOT, 'data', 'awards_fit.json')))['cfb']


def loso_probs(races, cols, depth, k):
    """{season: [P(top k) per pool row]} from fits leaving that season out"""
    rng = random.Random(7)
    out = {}
    rr = [(s, [[r[c] for c in cols] for r in p], o) for s, p, o in races]
    for s, X, _ in rr:
        b, mu, sd = E.fit([(Z, o) for t, Z, o in rr if t != s and o], depth=depth)
        z = [sum(bk * ((x - m) / v) for bk, x, m, v in zip(b, row, mu, sd)) for row in X]
        if k == 1:
            out[s] = E.prob(X, b, mu, sd); continue
        acc = [0] * len(z)
        for _ in range(4000):
            g = sorted(((u - math.log(-math.log(max(rng.random(), 1e-300))), i) for i, u in enumerate(z)), reverse=True)
            for _, i in g[:k]: acc[i] += 1
        out[s] = [a / 4000 for a in acc]
    return out


def main():
    R = M.cfb_rows()
    hr = M.heis_races(R)
    ph = loso_probs(hr, FIT['heisman']['cols'], 3, 4)
    pos = {}
    for a in set(POS_AW.values()):
        rc = M.award_races(R, a, F.CFB_AWARDS[a][2])
        pos[a] = (rc, loso_probs(rc, FIT[a]['cols'], 1, 1))
    rows = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cfb_alltime_rows.json.gz')))
    F_ = [r for r in rows if r['final']]
    cls = lambda r: r['draft'] or r['last'] + 1
    F_ = [r for r in F_ if 2015 <= cls(r) <= 2023 and r.get('av') is not None]
    PFX = {'DL': 'DT'}
    joined = collections.Counter()
    for r in F_:
        S = r['s']
        r['drv_heis'] = r['drv_pos'] = 0.0
        hp = [x for x in hr if x[0] == S]
        if hp:
            pool = hp[0][1]
            m = NM.Matcher(pool, name='n', team=None, pos=lambda x: M.POS_FV.get(x['pos'], x['pos']))
            h, _ = m.find(r['name'], pos=PFX.get(r['g'], r['g']))
            if h is not None:
                r['drv_heis'] = ph[S][pool.index(h)]; joined['heis'] += 1
        a = POS_AW[r['g']]
        rc, pp = pos[a]
        hp = [x for x in rc if x[0] == S]
        if hp:
            pool = hp[0][1]
            m = NM.Matcher(pool, name='n', team=None, pos=lambda x: M.POS_FV.get(x['pos'], x['pos']))
            h, _ = m.find(r['name'], pos=PFX.get(r['g'], r['g']))
            if h is not None:
                r['drv_pos'] = pp[S][pool.index(h)]; joined['pos'] += 1
    print('rows', len(F_), 'joined', dict(joined), 'heis p>.05:', sum(r['drv_heis'] > .05 for r in F_),
          'pos p>.05:', sum(r['drv_pos'] > .05 for r in F_))
    C = sorted({cls(r) for r in F_})
    G = sorted({r['g'] for r in F_})
    res = {}
    for drv in ('drv_heis', 'drv_pos'):
        z = lambda r: math.log(1 + r[drv] / .01)
        by = []
        for c in C:
            tr = [r for r in F_ if cls(r) != c]
            te = [r for r in F_ if cls(r) == c]
            X = np.array([[1.0 * (r['g'] == g) for g in G] + [r['fm'], z(r)] for r in tr])
            y = np.array([r['av'] for r in tr])
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            b, w = beta[-2], beta[-1]
            grade = lambda r: r['fm'] + (w / b) * z(r)
            def within(f):
                rs = []
                for g in G:
                    T = [r for r in te if r['g'] == g]
                    if len(T) < 10: continue
                    a_ = np.array([f(r) for r in T]); o = np.array([r['av'] for r in T])
                    if a_.std() > 0 and o.std() > 0: rs.append(np.corrcoef(a_, o)[0, 1])
                return float(np.mean(rs))
            top = lambda f: float(np.mean([r['av'] for r in sorted(te, key=lambda r: -f(r))[:32]]))
            by.append({'class': c, 'n': len(te), 'w_over_b': round(float(w / b), 3), 'r0': round(within(lambda r: r['fm']), 4),
                       'r1': round(within(grade), 4), 'top0': round(top(lambda r: r['fm']), 3), 'top1': round(top(grade), 3),
                       'moved': sum(1 for r in te if z(r) > 0)})
        d = [x['r1'] - x['r0'] for x in by]
        n = len(d); m = sum(d) / n; v = sum((x - m) ** 2 for x in d) / (n - 1)
        t = m / math.sqrt(v / n) if v > 0 else 0.0
        dt = [x['top1'] - x['top0'] for x in by]
        res[drv] = {'by': by, 'gain_r': round(m, 4), 't': round(t, 2), 'p': round(t_sf(t, n - 1), 4), 'wins': sum(x > 0 for x in d),
                    'n': n, 'top32_gain': round(sum(dt) / n, 3), 'top32_wins': sum(x > 0 for x in dt)}
    ok = holm([res[k]['p'] for k in res])
    for (k, v), h in zip(res.items(), ok):
        v['pass'] = bool(h and v['gain_r'] > 0 and v['wins'] * 2 > v['n'] and v['top32_gain'] >= 0)
        print(k, {x: v[x] for x in ('gain_r', 't', 'p', 'wins', 'n', 'top32_gain', 'top32_wins', 'pass')})
        for x in v['by']: print('   ', x)
    json.dump(res, open(os.path.join(HERE, 'awards_fv_results.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
