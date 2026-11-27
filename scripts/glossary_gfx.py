#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Build data/glossary_gfx.json: what each glossary GFX card on Process draws (assets/js/gfx.js buildTerm).

research/glossary_gfx_base.json = the compact cards (formula + one picture), keyed by the term exactly as in
data/library.json. EXPLAIN below = the explainer cards (portrait): stands for, what, use, formula, a held-out test
against similar metrics, a distribution or calibration picture, and the top 10 from the site's own data files.
Test numbers are copied from the backtest files and the glossary; the top 10s and distributions are computed here.
Rerun after a season file or a refit changes:  python3 scripts/glossary_gfx.py
Copy rules (CLAUDE.md): brief, descriptive, unemotional. No adjectives that sell.
"""
import glob, json, math, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
J = lambda p: json.load(open(ROOT / p))


def seasons(pattern, last_complete=True):
    """season files of a per-season folder, oldest first; the season in progress left out when last_complete"""
    out = [J(f) for f in sorted(glob.glob(str(ROOT / pattern)))]
    return out[:-1] if last_complete and len(out) > 1 else out


def hist(vals, lo, hi, step):
    """counts per bin [x0, n], values outside the range go to the end bins"""
    k = int(round((hi - lo) / step))
    n = [0] * k
    for v in vals:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        i = min(k - 1, max(0, int((v - lo) // step)))
        n[i] += 1
    return [[round(lo + i * step, 4), c] for i, c in enumerate(n)]


def best(rows, key, name='n', k=10):
    """top k by key, one row per player (his best season)"""
    seen, out = set(), []
    for p in sorted((p for p in rows if p.get(key) is not None), key=lambda p: -p[key]):
        if p[name] in seen:
            continue
        seen.add(p[name]); out.append(p)
        if len(out) == k:
            break
    return out


def span(a, b):
    return f'{a} to {b}'


def nba():
    S = seasons('static/data/nba-xpm/20*.json')
    rows = []
    for d in S:
        q = 1000 * d['games'] / 82
        rows += [dict(p, lab=d['label']) for p in d['players'] if (p.get('mp') or 0) >= q]
    yrs = span(S[0]['label'], S[-1]['label'])
    top = lambda k: [[p['n'], p['lab'], p['tm'], p[k]] for p in best(rows, k)]
    last = [p for p in S[-1]['players'] if (p.get('mp') or 0) >= 1000 * S[-1]['games'] / 82]
    xpm = {
        'stands': 'Cross Plus-Minus · NBA',
        'what': 'The points a player adds per 100 possessions over an average player, as played.',
        'use': 'The headline number on every NBA board. It feeds VORX, the game models and the CBB FV target.',
        'f': ['XPM = .5 DPM + .5 BPM', 'O-XPM, D-XPM: same blend each side'],
        'parts': [['databallr DPM', .5], ['Basketball-Reference BPM', .5]],
        'test': {'t': 'next-season team net rating · RMSE', 'lo': True, 'unit': '',
                 'rows': [['XPM (.5 / .5)', 2.933, 1], ['BPM alone', 2.966, 0], ['DPM alone', 3.012, 0]],
                 'n': 'leave one season out · 480 team seasons 2011-26'},
        'viz': {'kind': 'dist', 't': f"qualified players {S[-1]['label']}", 'unit': '',
                'bins': hist([p['xpm'] for p in last], -6, 10, 1), 'mark': 0, 'marks': [[-1.4, 'repl'], [0, 'avg']]},
        'top': {'t': f'best qualified season per player · {yrs}', 'rows': top('xpm'), 'dec': 1, 'sign': True},
        'foot': 'qualified = 1,000 MP a 82 games · BPM only where no DPM row',
    }
    vorx = {
        'stands': 'Value Over Replacement XPM · NBA',
        'what': 'The wins a player adds over a replacement player across his minutes.',
        'use': 'The default sort of the XPM and rookie boards. Contract value converts it to dollars.',
        'f': ['VORX = .030 × (XPM + 1.4) × MP / 48', 'replacement XPM -1.4 · .030 wins a point'],
        'test': {'t': 'rookies: order of next-3-season VORX · Spearman', 'lo': False, 'unit': '',
                 'rows': [['VORX', .398, 1], ['pXPM', .395, 0], ['aXPM', .379, 0], ['XPM', .330, 0]],
                 'n': 'held out · rookies 2010-23'},
        'viz': {'kind': 'bars', 't': 'VORX at 2,000 MP', 'unit': '',
                'rows': [['XPM -1.4', 0], ['XPM 0', 1.75], ['XPM +2', 4.25], ['XPM +4', 6.75], ['XPM +6', 9.25]]},
        'top': {'t': f'best season per player · {yrs}', 'rows': top('vorx'), 'dec': 1},
        'foot': 'constants fit to team wins, 480 team seasons 2011-26',
    }
    px = J('data/nba_pxpm_research.json'); k = px['ship'][0]
    pxpm = {
        'stands': 'predictive XPM · NBA',
        'what': "Next season's XPM from three seasons weighted by minutes, shrunk to a role mean and aged.",
        'use': "The read on small samples and next season's level. It separates a hot 300 minutes from a level.",
        'f': [f'({k} × role mean + Σ w MP × XPM)', f'/ ({k} + Σ w MP)  · w 1 / {px["ship"][1]:g} / {px["ship"][2]:g}', '+ aging to next season'],
        'test': {'t': 'next-season XPM · RMSE', 'lo': True, 'unit': '',
                 'rows': [['pXPM', px['loo']['player'], 1], ['k 600 shrink', px['base']['pXPM (live)']['player'], 0],
                          ['DPM', px['base']['DPM']['player'], 0], ['XPM', px['base']['rXPM']['player'], 0],
                          ['BPM', px['base']['BPM']['player'], 0]],
                 'n': 'leave one season out · 2011-26'},
        'viz': {'kind': 'bars', 't': 'next-season team net · R²', 'unit': '',
                'rows': [['pXPM', px['loo']['team']], ['BPM', px['base']['BPM']['team']], ['XPM', px['base']['rXPM']['team']],
                         ['DPM', px['base']['DPM']['team']], ['k 600 shrink', px['base']['pXPM (live)']['team']]]},
        'top': {'t': f'best qualified season per player · {yrs}', 'rows': top('sxpm'), 'dec': 1, 'sign': True},
    }
    return xpm, vorx, pxpm


def nhl():
    S = seasons('static/data/nhl-war/20*.json')
    fit = J('data/nhl_war.json')
    rows = [dict(p, lab=d['label']) for d in S for p in d['players']]
    yrs = span(S[0]['label'], S[-1]['label'])
    sk = [p for p in S[-1]['players'] if p.get('grp') != 'G' and (p.get('toi') or 0) >= 500]
    war = {
        'stands': 'wins above replacement · NHL',
        'what': 'The wins a player added over a replacement-level player, from what happened on the ice.',
        'use': 'Descriptive value, meaning who drove results this season. It sums to team goal differential.',
        'f': ['5v5 on-ice xG vs teammates', '+ PP xG / 5 + PK / 4', '+ finishing + penalties', f"÷ {fit['goalsPerWin']} goals a win"],
        'test': {'t': 'team WAR vs team goal differential, same season', 'tiles': [['R²', f"{fit['r2Same']:.3f}".lstrip('0'), 'same season'], ['team seasons', f"{fit['teamSeasons']}", '2009-26']],
                 'n': 'projection test: see pWAR'},
        'viz': {'kind': 'dist', 't': f"skaters 500+ min · {S[-1]['label']}", 'unit': '',
                'bins': hist([p['war'] for p in sk], -2, 6, .5), 'mark': 0, 'marks': [[0, 'repl']]},
        'top': {'t': f'best season per player · {yrs}', 'rows': [[p['n'], p['lab'], p['tm'], p['war']] for p in best(rows, 'war')], 'dec': 2},
        'foot': 'replacement = outside each team\'s top 13 F / 7 D / 2 G · goalies: GSAx',
    }
    pwar = {
        'stands': 'projected WAR · NHL',
        'what': 'Expected WAR next season, from shrunk and weighted rates and projected ice time.',
        'use': 'The forward-looking value for rosters, trades, backups and the game model.',
        'f': ['HPM = Marcel rates (1 / .5 / .25), shrunk', 'pWAR = (HPM − repl) × TOI / 60 ÷ goals a win'],
        'test': {'t': 'next-season team goal diff · R²', 'lo': False, 'unit': '',
                 'rows': [['pWAR', fit['r2'], 1], ['points only', fit['r2Points'], 0], ['on-ice xG only', fit['r2OnIceXg'], 0]],
                 'n': f"leave one season out · {fit['teamSeasons']} team seasons"},
        'viz': {'kind': 'bars', 't': 'Marcel weights', 'unit': '', 'rows': [['last season', 1], ['2 back', .5], ['3 back', .25]]},
        'top': {'t': f'highest pWAR, best per player · {yrs}', 'rows': [[p['n'], p['lab'], p['tm'], p['pwar']] for p in best(rows, 'pwar')], 'dec': 2},
    }
    return war, pwar


def soccer():
    S = seasons('static/data/soccer-war/20*.json')
    fit = J('data/soccer_war_fit.json')
    rows = [dict(p, lab=d['label']) for d in S for p in d['players']]
    yrs = span(S[0]['label'], S[-1]['label'])
    last = [p for p in S[-1]['players'] if (p.get('min') or 0) >= 900]
    return {
        'stands': 'goals above replacement · soccer',
        'what': 'The goals a season a player adds over a replacement regular, on one scale for every league.',
        'use': 'Player value on the soccer board. It is the base of xMV, 1Y / 3Y and backup watch.',
        'f': ['shrunk per-90 rates × weights', 'on-ice xGA, npxG, xA, xGBuildup, GK saves', 'PAR = GAR × .626 points a goal'],
        'parts': [[n, fit['w'][k]] for n, k in (('xA', 'xas'), ('npxG', 'npxg'), ('xGBuildup', 'bup'), ('on-ice xGA', 'ona')) if k in fit['w']],
        'test': {'t': 'next-season team goal diff · R²', 'lo': False, 'unit': '',
                 'rows': [['GAR + priors', fit['r2Held'], 1], ['GAR, no priors', fit['r2HeldNoPriors'], 0]],
                 'n': 'held out seasons'},
        'viz': {'kind': 'dist', 't': f"900+ minutes · {S[-1]['label']}", 'unit': '',
                'bins': hist([p['gar'] for p in last], -4, 12, 1), 'mark': 0, 'marks': [[0, 'repl']]},
        'top': {'t': f'best season per player · {yrs}', 'rows': [[p['n'], p['lab'], p['team'], p['gar']] for p in best(rows, 'gar')], 'dec': 1},
        'foot': 'replacement: regulars on each league\'s bottom three sides, less collapsed sides',
    }


def nfl():
    d = J('static/data/nfl-war.json')
    P = d['players']
    return {
        'stands': 'wins above replacement · NFL',
        'what': 'The wins a player added over a replacement player at his position, on both sides of the ball.',
        'use': 'Season value on the NFL board, and in team WAR, rookies and standouts.',
        'f': ['WAR = .6 × AV WAR + .4 × XV', 'AV WAR = (AV − repl AV × snaps) × .091'],
        'parts': [['AV WAR', .6], ['XV (stat lines)', .4]],
        'test': {'t': 'margin lost on missed games · t', 'lo': False, 'unit': '',
                 'rows': [['XV', 4.9, 1], ['AV WAR', 2.1, 0]], 'n': 'team seasons 2018-25'},
        'viz': {'kind': 'dist', 't': f"200+ snaps · {d['season']} through week {d['week']}", 'unit': '',
                'bins': hist([p['war'] for p in P if (p.get('sn') or 0) >= 200], -0.25, 1.25, .125), 'mark': 0, 'marks': [[0, 'repl']]},
        'top': {'t': f"{d['season']} season to date", 'rows': [[p['n'], p['pos'], p['tm'], p['war']] for p in sorted(P, key=lambda p: -p['war'])[:10]], 'dec': 2},
        'foot': '.091 wins an AV · 160 team seasons 2021-25, r .86',
    }


def fv():
    d = J('data/fv_alltime.json')['cbb']
    c = d['check']
    rows = sorted(d['rows'], key=lambda r: -r['fvx'])[:10]
    return {
        'stands': 'future value · 20-80',
        'what': 'A grade of what a prospect becomes at peak, the mean outcome of past players with the profile.',
        'use': 'It ranks every prospect board. Each board has one scale, graded on absolute talent.',
        'f': ['FV = Σ tier odds × tier outcome', '50 regular · 60 plus · 70 star · 80 generational'],
        'test': {'t': 'CBB held out: grade given vs outcome reached', 'tiles': [['slope', f"{c['slope']:.2f}", '1 = exact'], ['bias', f"{c['bias']:+.1f}", 'FV points'], ['players', f"{c['n']:,}", f"{d['seasons'][0]}-{d['seasons'][1]}"]]},
        'viz': {'kind': 'cal', 't': 'FV given vs outcome FV', 'lo': 20, 'hi': 65,
                'rows': [[b['given'], b['became'], b['n']] for b in c['bands']]},
        'top': {'t': f"highest CBB grades · {d['seasons'][0]}-{d['seasons'][1]}",
                'rows': [[r['name'], str(r['season']), r['team'], r['fv']] + ([f"became {r['out']}"] if r.get('out') else ['']) for r in rows], 'dec': 0},
        'foot': 'outcome = peak NBA value (XPM and role) on the FV scale',
    }


def cs2():
    d = J('data/cs2_players.json')
    sc = {s['name']: s['r2'] for s in d['fit']['score']}
    b = sorted(d['board'], key=lambda r: -r['rwa'])
    return {
        'stands': 'round win % added · CS2',
        'what': 'The round win % a player adds per round, opponent-adjusted. 0 is an average tier-1 starter.',
        'use': 'The player board, prospect FV and the player term in series odds.',
        'f': ['box: round share on per-round stat lines', '+ ½ plus-minus residual', '+ tier lift · opponents credited'],
        'test': {'t': 'next-map round share · R²', 'lo': False, 'unit': '',
                 'rows': [['RWA', sc.get('ARK player rating', .134), 1], ['Nov 2 RWA', sc.get('Nov 2 rating (no headshots, damage taken, plus-minus or tier lift)', .120), 0],
                          ['K-D per round', sc.get('kills minus deaths per round', .113), 0]],
                 'n': f"held out {d['fit']['held'][0][:7]} on · {d['fit']['score'][0]['n']:,} player-maps"},
        'viz': {'kind': 'dist', 't': 'board', 'unit': '', 'bins': hist([p['rwa'] for p in b], -4, 4, .5), 'mark': 0, 'marks': [[0, 'avg tier-1']]},
        'top': {'t': f"top RWA · maps since {d['first'][:4]}", 'rows': [[p['n'], f"{p['maps']} maps", p['tm'], p['rwa']] for p in b[:10]], 'dec': 2, 'sign': True},
    }


def gleague():
    g = J('data/gleague_callup_fit.json')['tests'][0]
    S = J('static/data/gleague-past.json')['seasons']
    rows = [dict(p, lab=str(s['season'] - 1) + '-' + str(s['season'])[2:]) for s in S for p in s['players'] if p.get('p1') is not None]
    return {
        'stands': 'chance of NBA minutes · G League',
        'what': 'The chance a G League player plays NBA minutes next season. 500% and xVORX cover bigger roles.',
        'use': 'The G League tab, for who is next up.',
        'f': ['ridge logistic: age, minutes, per-36 box,', 'efficiency, NBA history, draft slot'],
        'test': {'t': 'next season NBA minutes · AUC', 'lo': False, 'unit': '',
                 'rows': [['with G League stats', g['auc'], 1], ['NBA history only', g['auc_hist'], 0]],
                 'n': f"leave one season out · {g['n']:,} player seasons · {g['wins']}/{g['seasons']} seasons won"},
        'viz': {'kind': 'cal', 't': 'predicted vs observed, by decile', 'lo': 0, 'hi': 1, 'pct': True,
                'rows': [[c[0], c[1], c[2]] for c in g['calibration']]},
        'top': {'t': f"highest xVORX (next 3 seasons) · {S[-1]['season'] - 1}-{str(S[0]['season'])[2:]}", 'rows': [[p['n'], p['lab'], p['tm'], p['xv']] for p in best(rows, 'xv')], 'dec': 2},
        'foot': f"base rate {round(g['rate'] * 100)}%",
    }


def nextup():
    d = J('static/data/next-up/nba.json')
    return {
        'stands': 'breakout odds',
        'what': 'The chance of a first season over the quality bar next season, for players never over it.',
        'use': 'The next up tab on every sport page.',
        'f': ['logistic on shrunk value + signals', 'bar ≈ 75-80th percentile of regulars'],
        'test': {'t': 'held-out t vs no-signal baseline', 'lo': False, 'unit': '',
                 'rows': [['CBB', 14.4, 1], ['NBA', 7.9, 1], ['soccer', 6.2, 1], ['CFB', 6.0, 1], ['NHL', 5.6, 1], ['NFL', 3.3, 1]],
                 'n': 'leave one season out, Holm'},
        'viz': {'kind': 'bars', 't': 'the bar', 'unit': '', 'txt': True,
                'rows': [['NBA', 'BPM +1.0'], ['CBB', 'BPM +2.8'], ['NHL', 'WAR/1k min 1.19'], ['soccer', 'GAR/90 .090'], ['NFL', 'PPR/G 12'], ['CFB', 'PFN z .32']]},
        'top': {'t': f"highest NBA BO% · {d['season']}", 'rows': [[p['n'], p['pos'], p['tm'], round(p['p'] * 100)] for p in sorted(d['rows'], key=lambda p: -p['p'])[:10]], 'dec': 0, 'unit': '%'},
        'foot': 'failed: vacated role, coaching change, trend, boosted trees',
    }


def statplus():
    b = J('data/cfb_statplus_backtest.json')['byPosition']
    return {
        'stands': 'production index · CFB',
        'what': 'Production against the position this season. 100 is average and 25 points is one SD.',
        'use': 'The CFB board, WAR quality and a production driver in FV.',
        'f': ['Stat+ = 100 + 25 × z', 'z of the PFN position score vs snap-weighted mean'],
        'test': {'t': 'validity vs NFL AV · r', 'lo': False, 'unit': '',
                 'rows': [[k, v, 1] for k, v in sorted(b.items(), key=lambda kv: -kv[1])], 'n': 'FBS players who reached the NFL'},
        'viz': {'kind': 'scale', 't': 'scale', 'lo': 50, 'hi': 150, 'ticks': [[50, '-2σ'], [75, '-1σ'], [100, 'avg'], [125, '+1σ'], [150, '+2σ']], 'mark': 100},
    }


def main():
    out = J('research/glossary_gfx_base.json')
    xpm, vorx, pxpm = nba()
    war, pwar = nhl()
    full = {'XPM': xpm, 'VORX': vorx, 'pXPM (predictive XPM)': pxpm, 'NHL WAR': war, 'pWAR / HPM': pwar,
            'GAR (soccer, senior)': soccer(), 'NFL WAR': nfl(), 'FV (future value)': fv(), 'RWA (CS2)': cs2(),
            'G League NBA% / 500% / xVORX': gleague(), 'Next up (breakout odds)': nextup(), 'Stat+': statplus()}
    ab = {'G League NBA% / 500% / xVORX': 'NBA%', 'Next up (breakout odds)': 'BO%', 'pWAR / HPM': 'pWAR'}
    terms = {e['term'] for s in J('data/library.json')['sections'] for e in s['entries']}
    for k, v in full.items():
        assert k in terms, k
        base = {kk: vv for kk, vv in out.get(k, {}).items() if kk in ('ab',)}
        out[k] = dict(base, **v, x=1)
        if k in ab:
            out[k]['ab'] = ab[k]
    for k in out:
        assert k in terms, k
    (ROOT / 'data/glossary_gfx.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print('explainers', len(full), 'cards', len(out))


if __name__ == '__main__':
    main()
