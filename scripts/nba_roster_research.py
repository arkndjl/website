#!/usr/bin/env python3
"""Research: do summer roster moves and rookies reach the NBA game model's projections early in a season?

    python3 scripts/nba_roster_research.py     # writes data/nba_roster_research.json (numpy)

Same walk-forward as the fit (scripts/nba_games_fit.py). Variants of the live model, each judged on all games and on
season openers (games before both teams' 15th), 2015-21 for selection and 2022-26 held out:
    rk       rookies drafted last summer join their team's lineup at their draft slot's rookie XPM and minutes
             (a + b ln(pick), fit only on earlier drafts) until they play
    ypk      second- and third-year players shrink toward their slot's value instead of a newcomer's
    rosterE  the two lineups' value difference, fading over each team's first 20 games
    linE     the lineup term, fading the same way (extra weight on tonight's lineup early)
    --priors (data/nba_roster_research_priors.json):
    rkc      college draftees at slot + final college BPM (scripts/nba_prior_research.py) instead of slot alone
    age      veterans' prior plus the XPM aging curve at their age
Kept by the fit's rule: paired t <= -1.5 on 2015-21 and 2022-26 no worse.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as Fit

OUT = os.path.join(N.ROOT, 'data', 'nba_roster_research.json')


def run():
    F = json.load(open(N.FIT))
    games, names = N.load_hist()
    inj = Fit.load_inj()
    P, feats, base = F['P'], F['feats'], F['params']

    def design(params):
        _, data = N.walk(games, names, P, params, inj=inj)
        D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
        X = {f: np.array([x[f] for _, x in D], float) for f in D[0][1]}
        y = np.array([g['hs'] - g['as'] for g, _ in D], float)
        S = np.array([g['S'] for g, _ in D])
        line = np.array([g['L'] if g.get('L') is not None else np.nan for g, _ in D])
        return X, y, S, line
    X0, y, S, line = design(base)
    early = X0['gpn'] < 15
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(X0, feats), y, S)
    ok = ~np.isnan(line)

    def score(pr, lab):
        r = {'label': lab}
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            for sub, kk in (('all', k), ('openers', k & early)):
                e, e0 = np.abs(pr[kk] - y[kk]), np.abs(ref[kk] - y[kk])
                r[f'{sub}{nm}'] = {'n': int(kk.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4),
                                   't': round(Fit.paired_t(e, e0), 2) if lab != 'live' else None,
                                   'maeLine': round(float(np.abs(line[kk & ok] - y[kk & ok]).mean()), 4)}
        r['kept'] = lab != 'live' and r['all2015_21']['t'] is not None and r['all2015_21']['t'] <= -1.5 and r['all2022_26']['d'] <= 0
        r['keptOpeners'] = lab != 'live' and r['openers2015_21']['t'] is not None and r['openers2015_21']['t'] <= -1.5 and r['openers2022_26']['d'] <= 0
        print(json.dumps(r), flush=True)
        return r
    out = [score(ref, 'live')]
    if '--priors' in sys.argv:          # Oct 21 follow-up: rookies' college BPM, veterans' aging curve
        for lab, extra in (('rkc', {'rkc': 1}), ('age', {'age': 1}), ('rkc+age', {'rkc': 1, 'age': 1})):
            X, _, _, _ = design({**base, **extra})
            out.append(score(Fit.wf(Fit.mat(X, feats), y, S), lab))
        with open(OUT.replace('.json', '_priors.json'), 'w') as fh:
            json.dump(out, fh, indent=1)
        return
    for f in ('rosterE', 'linE'):
        out.append(score(Fit.wf(Fit.mat(X0, feats + [f]), y, S), '+' + f))
    for lab, extra in (('rk', {'rk': 1}), ('rk, rookies 3 games', {'rk': 1, 'rkw': 3.0}), ('rk+ypk', {'rk': 1, 'ypk': 1}), ('ypk', {'ypk': 1})):
        X, _, _, _ = design({**base, **extra})
        out.append(score(Fit.wf(Fit.mat(X, feats), y, S), lab))
        for f in ('rosterE', 'linE'):
            out.append(score(Fit.wf(Fit.mat(X, feats + [f]), y, S), f'{lab} +{f}'))
    with open(OUT, 'w') as fh:
        json.dump(out, fh, indent=1)


if __name__ == '__main__':
    run()
