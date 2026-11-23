"""F2 (prereg.md): value beyond the slot for the NFL conviction mock. nflverse picks 2010-21, outcome w_av (PFR weighted
career AV) centred within the draft; base ln pick, ln pick^2, position group; each driver added alone, leave one draft out.

    python3 scripts/research/mocks_nov23/nfl_conv.py   -> scripts/research/mocks_nov23/nfl_conv.json"""
import collections, json, math, os
import numpy as np
from common import OUT, paired, holm
import names as N
import nfl_data as ND

G = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']
YEARS = range(2010, 2022)


def rows():
    P = ND.picks(); C = ND.combine(); out = []
    for y in YEARS:
        cm = N.Matcher(C[y], name='name', team='school', pos=None)
        for r in P[y]:
            g = ND.NGRP.get(r['position'])
            if g in (None, 'K'): continue
            nm, sch = r['pfr_player_name'], r['college']
            c, _ = cm.find(nm, sch)
            a = ND.award_feats(nm, sch, y - 1)
            out.append(dict(year=y, name=nm, g=g, pick=int(r['pick']), wav=float(r['w_av']) if r['w_av'] not in ('', 'NA') else 0.0,
                            age=float(r['age']) if r['age'] not in ('', 'NA') else None, heis=a['heis'], aa=a['aa'], award=a['award'],
                            ath=c['ath'] if c else None, forty=c['forty'] if c else None, notest=c['notest'] if c else 0.0,
                            conf=ND.sec_b10(sch, y - 1)))
    m = collections.defaultdict(list)
    for r in out: m[r['year']].append(r['wav'])
    for r in out: r['y'] = r['wav'] - float(np.mean(m[r['year']]))
    ages = [r['age'] for r in out if r['age'] is not None]; am = float(np.mean(ages))
    for r in out: r['age_c'] = r['age'] - am if r['age'] is not None else 0.0
    return out


def feats(r, extra):
    lp = math.log(r['pick'])
    f = [1, lp, lp * lp] + [1.0 if r['g'] == g else 0.0 for g in G[1:]]
    return f + [r.get(k) if r.get(k) is not None else 0.0 for k in extra]


def lodo(R, extra):
    loss = np.zeros(len(R))
    for t in YEARS:
        tr = [r for r in R if r['year'] != t]; te = [i for i, r in enumerate(R) if r['year'] == t]
        X = np.array([feats(r, extra) for r in tr]); b = np.linalg.lstsq(X, np.array([r['y'] for r in tr]), rcond=None)[0]
        for i in te: loss[i] = (R[i]['y'] - float(np.dot(feats(R[i], extra), b))) ** 2
    return loss


def main():
    R = rows()
    cover = {'n': len(R), 'age': sum(r['age'] is not None for r in R), 'heis': sum(r['heis'] for r in R), 'aa': sum(r['aa'] for r in R),
             'award': sum(r['award'] for r in R), 'ath': sum(r['ath'] is not None for r in R), 'forty': sum(r['forty'] is not None for r in R),
             'notest': sum(r['notest'] for r in R), 'conf': sum(r['conf'] for r in R)}
    l0 = lodo(R, []); tests = []
    for d in ['heis', 'aa', 'award', 'age_c', 'ath', 'forty', 'notest', 'conf']:
        l1 = lodo(R, [d])
        X = np.array([feats(r, [d]) for r in R]); b = np.linalg.lstsq(X, np.array([r['y'] for r in R]), rcond=None)[0]
        res = paired(l0, l1, [r['year'] for r in R])
        res.update({'model': 'F2', 'driver': d, 'coef': round(float(b[-1]), 3), 'n': len(R),
                    'rmse': [round(float(math.sqrt(l0.mean())), 4), round(float(math.sqrt(l1.mean())), 4)]})
        tests.append(res)
    holm(tests)
    for t in tests: t['pass'] = bool(t['holm'] and t['gain'] > 0 and t['won'] >= 7)
    json.dump({'_readme': 'prereg.md F2: NFL value beyond the slot, w_av centred by draft, 2010-21 picks, LODO; coef = w_av per unit.',
               'coverage': cover, 'tests': tests}, open(os.path.join(OUT, 'nfl_conv.json'), 'w'), indent=1)
    print(json.dumps(cover))
    for t in tests:
        print(f"{t['driver']:7} coef {t['coef']:+.3f} gain {t['gain']:+.4f} t {t['t']:+.2f} p {t['p']:.4f} won {t['won']}/{t['of']} rmse {t['rmse']} pass {t['pass']}")


if __name__ == '__main__':
    main()
