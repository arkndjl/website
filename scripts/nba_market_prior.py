#!/usr/bin/env python3
"""The market's preseason view of each NBA team in the game model's early weeks (research; Oct 21 2026).

    python3 scripts/nba_market_prior.py --research             # margin priors and the totals carry -> data/nba_market_prior.json
    python3 scripts/nba_market_prior.py --research --totals    # the totals part only ('--flat': fades of 80 games and none)

Margin ('mpri' in scripts/nba_games.py): preseason win lines, or title odds mapped to a win share, in points (2.7 wins
a point), fading as each team plays (phl / (phl + games)), with or without a flat copy. Sources (free only): win lines
and title odds 2015-16 to 2025-26 from Basketball-Reference (scripts/futures_hist.py); ESPN's DraftKings futures carry
title, conference and division odds but no win totals, so the live season could only use the title map (a line on
log(title chance), vig removed, fit on the other seasons: 4.2 wins rmse). Neither helps: the opening weeks gain a few
hundredths of a point and nothing past them (the roster-based lineup prior already sits near the market). Not kept.
Totals: each team's market total rating (its gap to the league's closing totals) used to restart at 0 every season,
which left opening-night totals within a few points of each other. Last season's final ratings as an input fading over
tphl games ('tpri') and a share kept in the new rating (tcar) cut totals error on 2017-21 and 2022-26 and pull the
opening weeks toward the close. Kept at tphl 80, tcar .25 (scripts/nba_games_fit.py).
"""
import collections
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
WT = os.path.join(HERE, 'data', 'futures', 'win_totals.json')
OUTR = os.path.join(ROOT, 'data', 'nba_market_prior.json')


def games_in(S):
    return 72 if S == 2021 else 82


def implied(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def history():
    by = collections.defaultdict(list)
    for r in json.load(open(WT))['nba']:
        by[r['S']].append(r)
    return by


def title_map(skip=None):
    """win share = a + b log(title chance), least squares over the seasons other than skip"""
    xs, ys = [], []
    for S, rs in history().items():
        if S == skip or S == 2020:               # 2019-20 stopped at 63-67 games: its lines were set for 82
            continue
        p = [implied(r['title']) for r in rs if r.get('title')]
        z = sum(p)
        for r in rs:
            if r.get('title'):
                xs.append(math.log(implied(r['title']) / z)); ys.append(r['line'] / games_in(S))
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def from_title(probs, ab):
    """{team: chance (vig removed)} -> {team: win share}, recentred so the league averages .5"""
    a, b = ab
    w = {t: a + b * math.log(max(p, 1e-5)) for t, p in probs.items()}
    m = sum(w.values()) / len(w)
    return {t: round(v - m + 0.5, 4) for t, v in w.items()}


def priors(source):
    """season -> {team: preseason win share} from 'line' (the win lines) or 'title' (title odds, mapped)"""
    out = {}
    for S, rs in history().items():
        if source == 'line':
            out[S] = {r['t']: r['line'] / games_in(S) for r in rs}
        else:
            z = sum(implied(r['title']) for r in rs)
            out[S] = from_title({r['t']: implied(r['title']) / z for r in rs}, title_map(skip=S))
    return out


# ---------------------------------------------------------------- research
def research():
    import numpy as np
    import nba_games as N
    import nba_games_fit as F
    import harness as H
    fit = json.load(open(N.FIT))
    games, names = N.load_hist()
    inj = F.load_inj()
    P, params, feats = fit['P'], dict(fit['params']), list(fit['feats'])
    params.update({'tcar': 0.0, 'tphl': 80.0})        # the base: no carry (the model before Oct 21 2026)
    TF0 = [f for f in N.TFEATS if f != 'tpri']
    pri = {'line': priors('line'), 'title': priors('title')}

    def run(extra):
        D, X, TX, y, ty, S, line, tline = F.design(games, names, P, {**params, **extra}, inj, feats + ['mpri', 'mpriF'])
        TX = np.array([[tx[f] for f in TF0] for _, _, tx in D])        # the totals inputs before tpri
        return D, X, TX, y, ty, S, line, tline

    D, X, TX, y, ty, S, line, tline = run({})
    # games played before tip by the team with fewer, regular season and playoffs alike
    cnt = collections.Counter(); gp = []
    for g, _, _ in D:
        gp.append(min(cnt[(g['S'], g['h'])], cnt[(g['S'], g['a'])])); cnt[(g['S'], g['h'])] += 1; cnt[(g['S'], g['a'])] += 1
    gp = np.array(gp)
    night = np.array([g['tip'][:10] for g, _, _ in D])
    tune = (S >= 2017) & (S < N.HOLD_FROM)          # 2015-16 has no win lines to train on, so scoring starts 2017
    hold = S >= N.HOLD_FROM
    base = F.wf(F.mat(X, feats), y, S)
    tbase = F.wf(TX, ty, S)
    hasL = ~np.isnan(line)
    hasT = ~np.isnan(tline)
    buckets = [(0, 3), (3, 10), (10, 20), (20, 999)]

    def score(pr, ref, yy, ln, has):
        out = {}
        for nm, k in (('tune', tune), ('hold', hold)):
            for lo, hi in buckets + [(0, 999)]:
                m = k & has & (gp >= lo) & (gp < hi) & ~np.isnan(pr) & ~np.isnan(ref)
                pt = H.paired(np.abs(pr[m] - yy[m]), np.abs(ref[m] - yy[m]), cluster=night[m])
                out[f'{nm} {lo}-{hi if hi < 999 else "end"}'] = {
                    'n': int(m.sum()), 'mae': round(float(np.mean(np.abs(pr[m] - yy[m]))), 3),
                    'd': round(pt['d'], 4), 't': round(pt['t'], 2),
                    'toClose': round(float(np.mean(np.abs(pr[m] - ln[m]))), 3),
                    'toCloseBase': round(float(np.mean(np.abs(ref[m] - ln[m]))), 3),
                    'maeClose': round(float(np.mean(np.abs(ln[m] - yy[m]))), 3)}
        return out

    res = {'base': {'feats': feats, 'margin': score(base, base, y, line, hasL), 'total': score(tbase, tbase, ty, tline, hasT)}, 'margin': {}, 'total': {}}
    # 1. margin: the prior as an input, fading with games played (phl), or flat all season
    for src in (() if '--totals' in sys.argv else ('line', 'title')):
        for phl in (3.0, 6.0, 10.0, 20.0, 40.0):
            _, X2, _, *_ = run({'prior': pri[src], 'phl': phl})
            for add in (['mpri'], ['mpri', 'mpriF']):
                pr = F.wf(F.mat(X2, feats + add), y, S)
                key = f'{src} phl {phl:g} ' + '+'.join(add)
                res['margin'][key] = score(pr, base, y, line, hasL)
                a = res['margin'][key]
                print(key, {k: (v['d'], v['t'], v['toClose'], v['toCloseBase']) for k, v in a.items() if k.endswith(' 0-3') or k.endswith('0-end')}, flush=True)
    # 2. totals: keep part of last season's market total gaps at the rollover instead of starting every team at 0
    for tc in (() if '--totals' in sys.argv else (0.25, 0.5, 0.75, 1.0)):
        _, _, TX2, *_ = run({'tcar': tc})
        pr = F.wf(TX2, ty, S)
        res['total'][f'tcar {tc:g}'] = score(pr, tbase, ty, tline, hasT)
        a = res['total'][f'tcar {tc:g}']
        print('tcar', tc, {k: (v['d'], v['t'], v['toClose'], v['toCloseBase']) for k, v in a.items() if k.endswith(' 0-3') or k.endswith('0-end')}, flush=True)
    # 3. totals: last season's market total gaps as their own input, fading with each team's games played
    for phl in ((80.0, 1e9) if '--flat' in sys.argv else (3.0, 6.0, 10.0, 20.0, 40.0)):
        for tc in (0.0, 0.25):
            D2, _, TX2, *_ = run({'tcar': tc, 'tphl': phl})
            TX3 = np.column_stack([TX2, [tx['tpri'] for _, _, tx in D2]])
            pr = F.wf(TX3, ty, S)
            key = f'tpri phl {phl:g} tcar {tc:g}'
            res['total'][key] = score(pr, tbase, ty, tline, hasT)
            a = res['total'][key]
            print(key, {k: (v['d'], v['t'], v['toClose'], v['toCloseBase']) for k, v in a.items() if k.endswith(' 0-3') or k.endswith('0-end')}, flush=True)
    with open(OUTR, 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--research':
        research()
    else:
        print(__doc__)
