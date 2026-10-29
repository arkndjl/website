#!/usr/bin/env python3
"""Research: LEBRON (BBall Index, scripts/nba_lebron.py) in the NBA game model's player values.

    python3 scripts/nba_lebron_research.py [--only 0,2]   # -> data/nba_lebron_research.json

Team-season test first (prior-season values x actual minutes -> team ORtg/DRtg, 2011-26): net LEBRON alone is worse
than XPM, single-season RAPM and LAKER are worse, RAPTOR (2014-22 only) helps a little but stopped updating after
2022; D-LEBRON at .2-.4 of the defensive part beats XPM on points allowed (nested forward-chaining P .998, 12 of 14
seasons) but not net margin once the weight is picked out of sample (P .86). Variants here put it into each player's opening value on top of the shipped arcw .25 (nba_games.lebron_blend).

Walk-forward refit of the shipped margin coefficients (as nba_arc_research.py); kept: paired clustered t <= -1.5
on 2015-21 (choice of lbw) and 2022-26 no worse. Win log loss reported alongside.
FAILED Oct 29 2026 (data/nba_lebron_research.json): every variant worse on 2015-21; lbw stays 0. Totals (tlbw,
D-LEBRON in the totals lineup term) .25-1: flat, under .002 points of MAE either way; tlbw stays 0.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import harness as H

OUT = os.path.join(N.ROOT, 'data', os.environ.get('OUTF', 'nba_lebron_research.json'))


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
    V = [('D-LEBRON .25', {'lbw': 0.25}), ('D-LEBRON .4', {'lbw': 0.4}), ('D-LEBRON .6', {'lbw': 0.6}),
         ('LEBRON net .25', {'lbw': 0.25, 'lbside': 'n'}), ('LEBRON net .5', {'lbw': 0.5, 'lbside': 'n'}),
         ('LEBRON net .25 in place of ARC', {'lbw': 0.25, 'lbside': 'n', 'arcw': 0.0}), ('D-LEBRON .1', {'lbw': 0.1}),
         # totals: D-LEBRON in the totals lineup term's defensive values (nba_games.lebron_d)
         ('totals D-LEBRON .25', {'tlbw': 0.25}), ('totals D-LEBRON .5', {'tlbw': 0.5}), ('totals D-LEBRON .75', {'tlbw': 0.75}),
         ('totals D-LEBRON 1', {'tlbw': 1.0})]
    if '--only' in sys.argv:
        V = [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    out = []
    for lab, extra in V:
        X, TX, _ = design({**base, **extra})
        r = {'label': lab}
        if 'tlbw' in extra:
            pr = Fit.wf(Fit.mat(TX, N.TFEATS), ty, S)
            for nm, k in (('2015_21', k1), ('2022_26', k2)):
                e, e0 = np.abs(pr[k] - ty[k]), np.abs(tref[k] - ty[k])
                pd_ = H.paired(e, e0, cluster=[M['day'][k], M['hts'][k]])
                r[nm] = {'n': int(k.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(pd_['d']), 4), 't': round(float(pd_['t']), 2)}
            r['kept'] = r['2015_21']['t'] <= -1.5 and r['2022_26']['d'] <= 0
            print(json.dumps(r), flush=True)
            out.append(r)
            continue
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
