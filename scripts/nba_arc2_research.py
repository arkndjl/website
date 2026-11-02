#!/usr/bin/env python3
"""Research (Nov 2 2026): what LUMA ARC angles are left after PR #509 (arcw .25 shipped) and PR #529 (LOKI failed).

    python3 scripts/nba_arc2_research.py CSV   # CSV = arc/v3.1/arc_season_boards.csv (github.com/lumahoops/NBA)
                                               # -> data/nba_arc2_research.json

FAILED Nov 2 2026, nothing shipped: win3/win5 2015-21 t +0.7/+0.8 (held -1.4/-1.5); win3 .5 t -0.2;
lineups +.5 t -1.4 (held -0.3), +1 t -0.9 (held +0.2); totals flat (t -1.4..+1.6). Effects <= .003 pts MAE.

Variants, each against the shipped model (arcw .25 on one-season boards S-1 and S-2):
- 'win3/win5': ARC's own pooled 3- or 5-season board ending S-1 in place of the two one-season boards
  (trailing windows: `season` = last season pooled, so no look-ahead).
- 'lineups +w': ARC's lineups part (net = skill + lineups, the stint evidence the box prior doesn't explain) added on
  top of each player's opening value at weight w, possession-weighted over S-1 and S-2 (half), shrunk toward 0 with
  n0 1250 possessions. XPM is box-based, so this is the part of ARC it can't already see.
Kept as nba_arc_research.py: walk-forward refit, paired clustered t <= -1.5 on 2015-21 and 2022-26 no worse.
"""
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import harness as H

OUT = os.path.join(N.ROOT, 'data', 'nba_arc2_research.json')
WIN = {}
for _r in csv.DictReader(open(sys.argv[1], encoding='utf-8')):
    if _r['net']:
        _f = lambda k: float(_r[k]) if _r.get(k) not in (None, '') else None
        WIN.setdefault(_r['window_years'], {}).setdefault(int(_r['season'][:4]) + 1, []).append(
            [_r['name'], _f('net'), _f('skill'), _f('lineups'), int(float(_r['poss'] or 0))])
_orig_lookup, _orig_blend = N.arc_lookup, N.arc_blend
_C = {}


def table(w, S, col):
    key = (w, S, col)
    if key not in _C:
        rows = [{'n': r[0], 'v': (r[col], r[4])} for r in WIN[str(w)].get(S, []) if r[col] is not None]
        d = {}
        for r in rows:
            k = N.norm(r['n'])
            if k not in d or d[k][1] < r['v'][1]:
                d[k] = r['v']
        _C[key] = (d, N.NM.Matcher(rows, name='n', team=None, pos=None, sport='basketball'))
    return _C[key]


def look(w, S, name, col=1):
    d, m = table(w, S, col)
    v = d.get(N.norm(name))
    if v: return v
    r, _ = m.find(name)
    return r['v'] if r else None


def set_variant(kind, arg):
    N.arc_lookup, N.arc_blend = _orig_lookup, _orig_blend
    if kind == 'win':
        # arc_blend asks for S-1 and S-2; answer S-1 with the pooled window ending S-1 and nothing for S-2.
        # arc_blend is called with the season being predicted; we can't see S there, so key on the first call.
        state = {}

        def lk(Sq, name):
            top = state.setdefault('top', Sq)
            if Sq != top:
                return None
            return look(arg, Sq, name)

        def bl(S, names, val, w, **kw):
            state.clear(); state['top'] = S - 1
            return _orig_blend(S, names, val, w, **kw)
        N.arc_lookup, N.arc_blend = lk, bl
    elif kind == 'lin':
        def bl(S, names, val, w, skip=(), n0=1250.0, **kw):
            out = _orig_blend(S, names, val, w, skip=skip, **kw)
            for pid, nm in names.items():
                if pid in skip or pid not in out:
                    continue
                num, den = 0.0, n0
                for Sq, k in ((S - 1, 1.0), (S - 2, 0.5)):
                    r = look(1, Sq, nm, col=3)
                    if r:
                        num += r[0] * r[1] * k; den += r[1] * k
                if den > n0:
                    out[pid] = out[pid] + arg * num / den
            return out
        N.arc_blend = bl


def main():
    import nba_games_fit as Fit
    F = json.load(open(N.FIT))
    G, names = N.load_hist()
    inj = Fit.load_inj()
    P, feats, base = F['P'], F['feats'], F['params']

    def design(params):
        _, data = N.walk(G, names, P, params, inj=inj)
        D = [(g, x, tx) for g, x, tx in data if g.get('fin') and g['S'] >= N.FIRST + 1]
        X = {f: np.array([x[f] for _, x, _ in D], float) for f in D[0][1]}
        TX = {f: np.array([tx[f] for _, _, tx in D], float) for f in D[0][2]}
        meta = dict(y=np.array([g['hs'] - g['as'] for g, _, _ in D], float), S=np.array([g['S'] for g, _, _ in D]),
                    ty=np.array([g['hs'] + g['as'] for g, _, _ in D], float),
                    day=np.array([g['tip'][:10] for g, _, _ in D]), hts=np.array([f"{g['h']}{g['S']}" for g, _, _ in D]))
        return X, TX, meta
    set_variant(None, None)
    X0, TX0, M = design(base)
    y, S, ty = M['y'], M['S'], M['ty']
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(X0, feats), y, S)
    tref = Fit.wf(Fit.mat(TX0, N.TFEATS), ty, S)
    sd = float(F['sd']) if isinstance(F.get('sd'), (int, float)) else 12.0
    Phi = np.vectorize(N.phi)
    V = [('win3 .25', 'win', 3, {}), ('win5 .25', 'win', 5, {}), ('win3 .5', 'win', 3, {'arcw': 0.5}),
         ('lineups +.5', 'lin', 0.5, {}), ('lineups +1', 'lin', 1.0, {})]
    out = []
    for lab, kind, arg, extra in V:
        set_variant(kind, arg)
        X, TX, _ = design({**base, **extra})
        pr = Fit.wf(Fit.mat(X, feats), y, S)
        tp = Fit.wf(Fit.mat(TX, N.TFEATS), ty, S)
        r = {'label': lab}
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
            cl = [M['day'][k], M['hts'][k]]
            pd_ = H.paired(e, e0, cluster=cl)
            win = (y[k] > 0).astype(float)
            ll = lambda m: -(win * np.log(Phi(m / sd)) + (1 - win) * np.log(1 - Phi(m / sd)))
            pl = H.paired(ll(pr[k]), ll(ref[k]), cluster=cl)
            te, te0 = np.abs(tp[k] - ty[k]), np.abs(tref[k] - ty[k])
            pt = H.paired(te, te0, cluster=cl)
            r[nm] = {'n': int(k.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(pd_['d']), 4),
                     't': round(float(pd_['t']), 2), 'dLL': round(float(pl['d']), 5), 'tLL': round(float(pl['t']), 2),
                     'tot_d': round(float(pt['d']), 4), 'tot_t': round(float(pt['t']), 2)}
        r['kept'] = r['2015_21']['t'] <= -1.5 and r['2022_26']['d'] <= 0
        r['tot_kept'] = r['2015_21']['tot_t'] <= -1.5 and r['2022_26']['tot_d'] <= 0
        print(json.dumps(r), flush=True)
        out.append(r)
    with open(OUT, 'w') as fh:
        json.dump(out, fh, indent=1)


if __name__ == '__main__':
    main()
