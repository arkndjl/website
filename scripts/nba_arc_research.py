#!/usr/bin/env python3
"""Research: LUMA ARC (scripts/nba_arc.py) in the NBA game model's player values.

    python3 scripts/nba_arc_research.py [--only 0,2]   # -> data/nba_arc_research.json

The lineup term values each player at his XPM (.5 DPM + .5 BPM) of the two seasons before. ARC is a Bayesian RAPM
with a box-score prior, built from play-by-play stints, so it carries lineup evidence XPM lacks. Variants mix it into
each player's opening value at weight arcw (nba_games.arc_blend). Walk-forward refit of the shipped margin
coefficients (as nba_returners_research.py); kept: paired clustered t <= -1.5 on 2015-21 (choice of arcw) and 2022-26
no worse. Totals and win log loss reported alongside.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import harness as H

OUT = os.path.join(N.ROOT, 'data', os.environ.get('OUTF', 'nba_arc_research.json'))


def main():
    import nba_games_fit as Fit
    F = json.load(open(N.FIT))
    G, names = N.load_hist()
    inj = Fit.load_inj()
    P, feats, base = F['P'], F['feats'], F['params']

    def design(params):
        _, data = N.walk(G, names, P, params, inj=inj)
        D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
        X = {f: np.array([x[f] for _, x in D], float) for f in D[0][1]}
        TX = {f: np.array([tx[f] for g, _, tx in data if g.get('fin') and g['S'] >= N.FIRST + 1], float) for f in data[-1][2]}
        meta = dict(y=np.array([g['hs'] - g['as'] for g, _ in D], float), S=np.array([g['S'] for g, _ in D]),
                    L=np.array([g['L'] if g.get('L') is not None else np.nan for g, _ in D]),
                    day=np.array([g['tip'][:10] for g, _ in D]), hts=np.array([f"{g['h']}{g['S']}" for g, _ in D]))
        meta['ty'] = np.array([g['hs'] + g['as'] for g, _ in D], float)
        return X, TX, meta
    X0, TX0, M = design(base)
    y, S = M['y'], M['S']
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(X0, feats), y, S)
    sd = float(F['sd']) if isinstance(F.get('sd'), (int, float)) else 12.0
    Phi = np.vectorize(N.phi)
    ty = M['ty']
    tref = Fit.wf(Fit.mat(TX0, N.TFEATS), ty, S)
    V = [('arcw .25', {'arcw': 0.25}), ('arcw .5', {'arcw': 0.5}), ('arcw .75', {'arcw': 0.75}), ('arcw 1', {'arcw': 1.0}),
         ('totals lineup xpm', {'tlin': 'xpm'}), ('totals lineup arc', {'tlin': 'arc'}),
         # LOKI preseason (R1) projections, on top of the shipped arcw .25 (scripts/.cache/nba/loki_r1.json, LUMA API,
         # needs a key). FAILED Oct 28 2026 (data/nba_loki_research.json): 2015-21 t -0.9 to +0.2 with log loss worse,
         # 2022-26 t -2.8 to -4.0. The gain sits only in 2021-26, the seasons LUMA tuned LOKI on: a hindcast leak
         ('lokiw .25', {'lokiw': 0.25}), ('lokiw .5', {'lokiw': 0.5}), ('lokiw .75', {'lokiw': 0.75}),
         ('lokiw .5 no arc', {'lokiw': 0.5, 'arcw': 0.0})]
    if '--only' in sys.argv:
        V = [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    out = []
    for lab, extra in V:
        X, TX, _ = design({**base, **extra})
        r = {'label': lab}
        if 'tlin' in extra:
            for col in ('tlin', 'tlinst'):
                pr = Fit.wf(Fit.mat(TX, N.TFEATS + [col]), ty, S)
                for nm, k in (('2015_21', k1), ('2022_26', k2)):
                    e, e0 = np.abs(pr[k] - ty[k]), np.abs(tref[k] - ty[k])
                    pd_ = H.paired(e, e0, cluster=[M['day'][k], M['hts'][k]])
                    r[f'{col} {nm}'] = {'mae': round(float(e.mean()), 4), 'd': round(float(pd_['d']), 4), 't': round(float(pd_['t']), 2)}
                r[f'{col} kept'] = r[f'{col} 2015_21']['t'] <= -1.5 and r[f'{col} 2022_26']['d'] <= 0
            print(json.dumps(r), flush=True)
            out.append(r)
            continue
        pr = Fit.wf(Fit.mat(X, feats), y, S)
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
            cl = [M['day'][k], M['hts'][k]]
            pd_ = H.paired(e, e0, cluster=cl)
            win = (y[k] > 0).astype(float)
            ll = lambda m: -(win * np.log(Phi(m / sd)) + (1 - win) * np.log(1 - Phi(m / sd)))
            pl = H.paired(ll(pr[k]), ll(ref[k]), cluster=cl)
            r[nm] = {'n': int(k.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(pd_['d']), 4),
                     't': round(float(pd_['t']), 2), 'tIid': round(Fit.paired_t(e, e0), 2),
                     'll': round(float(ll(pr[k]).mean()), 5), 'dLL': round(float(pl['d']), 5), 'tLL': round(float(pl['t']), 2)}
        r['kept'] = r['2015_21']['t'] <= -1.5 and r['2022_26']['d'] <= 0
        print(json.dumps(r), flush=True)
        out.append(r)
    if '--only' in sys.argv and os.path.exists(OUT):
        out = [r for r in json.load(open(OUT)) if r['label'] not in {o['label'] for o in out}] + out
    with open(OUT, 'w') as fh:
        json.dump(out, fh, indent=1)


if __name__ == '__main__':
    main()
