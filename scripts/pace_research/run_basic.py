"""NBA, CBB, NHL: pre-game pace features on each walk-forward row, tested on totals against the model and the close"""
import gzip
import json
import sys

import numpy as np

import os
SC = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/'
from core import Pace, test, fmt, OUT

W = SC + 'data/games_wf/'


def load(p):
    return json.load(gzip.open(p))


def feats_from(games, key_id, key_S, key_h, key_a, key_x, key_day, hl, carry):
    """walk games in time order; record pre-game features by id"""
    P = Pace(hl=hl, carry=carry)
    out = {}
    for g in sorted(games, key=key_day):
        P.season(key_S(g))
        h, a = key_h(g), key_a(g)
        lg = P.lg or 0
        rh, ra = P.r[h], P.r[a]
        ready = P.n[h] >= 3 and P.n[a] >= 3
        out[str(key_id(g))] = None if not ready else {
            'ep': rh + ra, 'clash': abs(rh - ra), 'trend': (P.fast[h] - rh) + (P.fast[a] - ra),
            'rel': (lg + rh + ra) / lg - 1 if lg else 0.0,
            'sd': (P.sd(h) or np.nan) + (P.sd(a) or np.nan)}
        P.add(h, a, key_x(g))
    return out


def run(sport, wf, F, tune, held_from, first_pred, tot_key='tot', T_key='T', tm_key='tm', day_key='date'):
    rows = [r for r in wf if F.get(str(r['id'])) and r.get(T_key) is not None and r.get(tot_key) is not None]
    has_tm = sum(r.get(tm_key) is not None for r in rows) > 0.5 * len(rows)
    if has_tm:
        rows = [r for r in rows if r.get(tm_key) is not None]
    y = np.array([float(r[tot_key]) for r in rows])
    S = np.array([r['S'] for r in rows])
    day = np.array([str(r[day_key])[:10] for r in rows])
    T = np.array([float(r[T_key]) for r in rows])
    f = {k: np.array([F[str(r['id'])][k] for r in rows], float) for k in ('ep', 'clash', 'trend', 'rel')}
    f['relT'] = f['rel'] * T
    cands = [('expected pace', [f['ep']]), ('pace x line (multiplicative)', [f['relT']]),
             ('pace clash |h-a|', [f['clash']]), ('pace trend (recent - rating)', [f['trend']]),
             ('pace + clash + trend', [f['ep'], f['clash'], f['trend']])]
    res = {}
    print('##', sport, len(rows), 'rows')
    if has_tm:
        tm = np.array([float(r[tm_key]) for r in rows])
        for nm, c in cands:
            r = test(rows, [tm], c, y, S, day, tune, held_from, first_pred)
            res['model: ' + nm] = r
            print(fmt('model+ ' + nm, r))
        base = [T, tm - T]
    else:
        base = [T]
    for nm, c in cands:
        r = test(rows, base, c, y, S, day, tune, held_from, first_pred)
        res['close: ' + nm] = r
        print(fmt('close+ ' + nm, r))
    return res


if __name__ == '__main__':
    which = sys.argv[1:] or ['nba', 'cbb', 'nhl']
    out = {}
    if 'nba' in which:
        g = load(SC + 'nba_games_hist.json.gz')['games']
        g = [x for x in g if x.get('poss') and x.get('fin')]
        F = feats_from(g, lambda x: x['id'], lambda x: x['S'], lambda x: x['h'], lambda x: x['a'], lambda x: x['poss'],
                       lambda x: x['tip'], hl=12, carry=0.6)
        out['nba'] = run('nba', load(W + 'nba.json.gz'), F, (2015, 2021), 2022, 2015)
    if 'cbb' in which:
        g = load(SC + 'data/cbb_games_hist.json.gz')
        g = [x for x in g if x.get('poss') and x.get('hs') is not None]
        F = feats_from(g, lambda x: x['id'], lambda x: x['season'], lambda x: x['home'], lambda x: x['away'],
                       lambda x: x['poss'], lambda x: x['date'], hl=8, carry=0.7)
        out['cbb'] = run('cbb', load(W + 'cbb.json.gz'), F, (2016, 2020), 2021, 2016)
    if 'nhl' in which:
        g = load(SC + 'nhl_games_hist.json.gz')

        def sog(x):
            gl = x.get('gl')
            if not gl or not gl.get('h') or not gl.get('a'):
                return None
            return sum(e[4] for e in gl['h']) + sum(e[4] for e in gl['a'])

        def xg(x):
            return x['x']['h'][1] + x['x']['a'][1] if x.get('x') else None
        for nm, fx in (('shots on goal', sog), ('xG', xg)):
            gg = [x for x in g if fx(x) is not None]
            F = feats_from(gg, lambda x: x['id'], lambda x: x['S'], lambda x: x['h'], lambda x: x['a'], fx,
                           lambda x: x['t'], hl=20, carry=0.5)
            wf = [dict(r, tot=r['hs'] + r['as']) for r in load(W + 'nhl.json.gz')]
            out['nhl ' + nm] = run('nhl ' + nm, wf, F, (2016, 2023), 2024, 2018, day_key='day')
    json.dump(out, open(OUT + 'basic_%s.json' % '_'.join(which), 'w'), indent=1)
