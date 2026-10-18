#!/usr/bin/env python3
"""NFL picks (data/nfl_picks.json, the picks tab on the NFL ARKBOARD): the college board's two fixed rules on the NFL
game model, each listed every week whatever its backtest says, with that backtest shown beside it.

    upset picks     the model has the market underdog winning outright and sits more than UPSET_EDGE points off the line
    favorite picks  the moneyline favorite priced FAV_ML that the model makes a bigger favorite by more than FAV_EDGE

    python3 scripts/nfl_picks.py --backtest     # data/nfl_picks_fit.json (numpy): both rules on 2015-25 walk-forward
                                                # predictions, the live model's (nfl_games.py fit: train on the seasons
                                                # before, score the season; 2021-25 never touched the tuning)

The live picks run inside nfl_games.py build (stdlib): each game is flagged on the line and price when the rule first
fires (nfldata games.csv, the current line until kickoff), kept in the log, and graded once final on the moneyline at the
flag price (the spread at -110 when there was no moneyline), with closing line value against games.csv's close.
Units: the Kelly stake at the model's own chance (normal around its margin, the fit's sd) over the backtest's average
Kelly stake, clipped KELLY_MIN to KELLY_CAP, so the average pick is 1 unit.
History has closing lines only (no opening lines or prices in nflverse), so the backtest grades at the close; live
picks get the earlier, published line.
"""
import datetime
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BT = os.path.join(ROOT, 'data', 'nfl_picks_fit.json')
OUT = os.path.join(ROOT, 'data', 'nfl_picks.json')
UPSET_EDGE = 4.0
FAV_EDGE, FAV_ML = 4.0, (-200, -105)
KELLY_MIN, KELLY_CAP = 0.25, 3.0


def odds(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if abs(v) >= 100 else None


def dec(o):
    return 1 + o / 100 if o > 0 else 1 + 100 / -o


def kelly(p, o):
    b = dec(o) - 1
    return (p * b - (1 - p)) / b


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def upset_side(m, L):
    """L: the home side's expected margin on the line (games.csv spread_line). The underdog, when the model has it
    winning outright and is more than UPSET_EDGE off the line."""
    if L is None or L == 0 or m * L >= 0 or abs(m - L) <= UPSET_EDGE:
        return None
    return 'away' if L > 0 else 'home'


def fav_side(m, L, ml_h, ml_a):
    if L is None or L == 0:
        return None
    side = 'home' if L > 0 else 'away'
    o = ml_h if side == 'home' else ml_a
    if o is None or not FAV_ML[0] <= o <= FAV_ML[1]:
        return None
    return side if (m if side == 'home' else -m) - abs(L) > FAV_EDGE else None


def win_chance(side, m, sd):
    return phi((m if side == 'home' else -m) / sd)


def cover_chance(side, m, L, sd):
    return phi((m - L) / sd if side == 'home' else (L - m) / sd)


def grade_ml(side, res, o):
    if res == 0:
        return 0.0
    return dec(o) - 1 if (res > 0) == (side == 'home') else -1.0


def grade_spread(side, res, L, o=-110):
    d = res - L
    if d == 0:
        return 0.0
    return dec(o) - 1 if (d > 0) == (side == 'home') else -1.0


def stake(f, scale):
    return min(KELLY_CAP, max(KELLY_MIN, f / scale)) if scale and scale > 0 else 1.0


def summ(bs):
    n = len(bs)
    pr = [b['profit'] for b in bs]
    u = sum(pr)
    m = u / n if n else 0.0
    s = math.sqrt(sum((x - m) ** 2 for x in pr) / (n - 1)) if n > 1 else 0.0
    risked = sum(b['stake'] for b in bs)
    su = sum(b['stake'] * b['profit'] for b in bs)
    return {'n': n, 'w': sum(1 for x in pr if x > 0), 'l': sum(1 for x in pr if x < 0), 'p': sum(1 for x in pr if x == 0),
            'units': round(u, 1), 'roi': round(m, 3) if n else None, 't': round(m / (s / math.sqrt(n)), 2) if n > 1 and s else None,
            'sized': {'risked': round(risked, 1), 'units': round(su, 1), 'roi': round(su / risked, 3) if risked else None}}


def rule_backtest(rows, rule, sd, extra):
    """rows: {S, m, L, res, mlH, mlA, oH, oA} per game. Moneyline at the close, and the spread at the close at its
    listed price. Stakes in a season are scaled by the other seasons' average Kelly stake."""
    seasons = sorted({r['S'] for r in rows})
    by = {'ml': [], 'close': []}
    for r in rows:
        side = rule(r)
        if not side:
            continue
        o = r['mlH'] if side == 'home' else r['mlA']
        if o is not None:
            by['ml'].append({'S': r['S'], 'side': side, 'res': r['res'], 'profit': grade_ml(side, r['res'], o), 'f': kelly(win_chance(side, r['m'], sd), o)})
        so = (r['oH'] if side == 'home' else r['oA']) or -110
        if r['res'] != r['L']:
            by['close'].append({'S': r['S'], 'side': side, 'res': r['res'], 'profit': grade_spread(side, r['res'], r['L'], so),
                                'f': kelly(cover_chance(side, r['m'], r['L'], sd), so)})
    out = {'games': len(rows), 'seasons': [seasons[0], seasons[-1]], 'kelly': {'min': KELLY_MIN, 'cap': KELLY_CAP}, **extra}
    for k, bs in by.items():
        for b in bs:
            other = [x['f'] for x in bs if x['S'] != b['S']]
            b['stake'] = stake(b['f'], sum(other) / len(other) if other else None)
        out[k] = {**summ(bs), 'won': round(sum(1 for b in bs if b['res'] != 0 and (b['res'] > 0) == (b['side'] == 'home')) / len(bs), 3) if bs else None,
                  'scale': round(sum(b['f'] for b in bs) / len(bs), 4) if bs else None,
                  'heldOut': summ([b for b in bs if b['S'] >= 2021]),
                  'bySeason': [{'season': S, **summ([b for b in bs if b['S'] == S])} for S in seasons]}
    return out


def backtest():
    """Both rules on the live model's walk-forward predictions (nfl_games.py fit's run at the fit's parameters)."""
    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nfl_games as N
    F = json.load(open(N.FIT))
    last = 2025
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, F['params'])
    D = []
    for g, x, _ in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D.append((g, x))
    X = np.array([[x[f] for f in N.FEATS] for _, x in D]); y = np.array([N.num(g['result']) for g, _ in D])
    S = np.array([int(g['season']) for g, _ in D]); pred = np.full(len(y), np.nan)
    for s in range(2015, last + 1):
        tr, te = S < s, S == s
        pred[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
    rows = []
    for (g, _), m, s in zip(D, pred, S):
        L = N.num(g['spread_line'], None)
        if s < 2015 or L is None:
            continue
        rows.append({'S': int(s), 'm': float(m), 'L': L, 'res': N.num(g['result']), 'mlH': odds(g['home_moneyline']), 'mlA': odds(g['away_moneyline']),
                     'oH': odds(g['home_spread_odds']), 'oA': odds(g['away_spread_odds'])})
    sd = F['sd']
    res = {'sd': sd, 'upset': rule_backtest(rows, lambda r: upset_side(r['m'], r['L']), sd, {'edge': UPSET_EDGE}),
           'fav': rule_backtest(rows, lambda r: fav_side(r['m'], r['L'], r['mlH'], r['mlA']), sd, {'edge': FAV_EDGE, 'band': list(FAV_ML)})}
    # edge cuts, as a sensitivity table (the shipped cut is fixed whatever this says)
    cuts = {}
    for k in ('upset', 'fav'):
        cuts[k] = []
        for e in (2, 3, 4, 5, 6):
            if k == 'upset':
                rl = lambda r, e=e: None if r['L'] == 0 or r['m'] * r['L'] >= 0 or abs(r['m'] - r['L']) <= e else ('away' if r['L'] > 0 else 'home')
            else:
                def rl(r, e=e):
                    side = 'home' if r['L'] > 0 else 'away'
                    o = r['mlH'] if side == 'home' else r['mlA']
                    if not r['L'] or o is None or not FAV_ML[0] <= o <= FAV_ML[1]:
                        return None
                    return side if (r['m'] if side == 'home' else -r['m']) - abs(r['L']) > e else None
            b = rule_backtest(rows, rl, sd, {})['ml']
            cuts[k].append({'edge': e, 'ml': {'n': b['n'], 'w': b['w'], 'l': b['l'], 'roi': b['roi'], 't': b['t']}})
        res[k]['cuts'] = cuts[k]
    with open(BT, 'w') as f:
        json.dump(res, f, indent=1)
    for k in ('upset', 'fav'):
        print(k, {m: {kk: res[k][m][kk] for kk in ('n', 'w', 'l', 'roi', 't', 'sized', 'won')} for m in ('ml', 'close')})
        print('  held out 2021-25', {m: res[k][m]['heldOut'] for m in ('ml', 'close')})


def live(rows, games, sd, season, week):
    """rows: nfl_games build's per-game output this season (margin, line, ml, kick, final). Flags this week's games
    that haven't kicked off, keeps the log, grades it, and writes data/nfl_picks.json."""
    try:
        bt = json.load(open(BT))
    except (OSError, ValueError):
        bt = {}
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    log = old.get('log', [])
    seen = {(e['id'], e['type']) for e in log}
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    fires = {}
    for r in rows:
        if r['week'] != week or r.get('line') is None or 'final' in r or not r.get('kick') or r['kick'] <= stamp:
            continue
        m, L = r['margin'], r['line']
        mlH, mlA = odds(r['ml']['home']), odds(r['ml']['away'])
        for typ, side in (('upset', upset_side(m, L)), ('fav', fav_side(m, L, mlH, mlA))):
            if not side:
                continue
            o = mlH if side == 'home' else mlA
            p = win_chance(side, m, sd) if o is not None else cover_chance(side, m, L, sd)
            b = bt.get(typ, {}).get('ml' if o is not None else 'close', {})
            units = round(stake(kelly(p, o if o is not None else -110), b.get('scale')) * 4) / 4
            fires[(r['id'], typ)] = {'line': -L if side == 'home' else L, 'ml': o}
            if (r['id'], typ) in seen:
                continue
            log.append({'id': r['id'], 'season': season, 'week': week, 'type': typ, 'side': side, 'team': r[side],
                        'home': r['home'], 'away': r['away'], 'kick': r['kick'], 'L': L, 'line': -L if side == 'home' else L,
                        'ml': o, 'model': m, 'edge': round(abs(m - L), 1), 'p': round(p, 3), 'units': units, 'flagged': stamp})
            seen.add((r['id'], typ))
    # grading: the final, and games.csv's close (its line once the game has kicked off)
    G = {g['game_id']: g for g in games}
    for e in log:
        g = G.get(e['id'])
        if not g or e.get('res') is not None or g['home_score'] in ('', 'NA'):
            continue
        res = float(g['result'])
        e['res'] = res
        try:
            e['close'] = float(g['spread_line'])
        except ValueError:
            e['close'] = None
        e['won'] = res != 0 and (res > 0) == (e['side'] == 'home')
        e['profit'] = round(grade_ml(e['side'], res, e['ml']) if e['ml'] is not None else grade_spread(e['side'], res, e['L']), 3)
        e['ats'] = round(grade_spread(e['side'], res, e['L']), 3)
        if e['close'] is not None:
            e['clv'] = round(e['close'] - e['L'] if e['side'] == 'home' else e['L'] - e['close'], 1)
    record = {}
    for typ in ('upset', 'fav'):
        done = [e for e in log if e['type'] == typ and e.get('res') is not None]
        n = len(done)
        u = sum(e['profit'] for e in done)
        risked = sum(e['units'] for e in done)
        su = sum(e['units'] * e['profit'] for e in done)
        cl = [e['clv'] for e in done if e.get('clv') is not None]
        record[typ] = {'n': n, 'won': sum(1 for e in done if e['won']), 'w': sum(1 for e in done if e['profit'] > 0),
                       'l': sum(1 for e in done if e['profit'] < 0), 'p': sum(1 for e in done if e['profit'] == 0),
                       'units': round(u, 1), 'roi': round(u / n, 3) if n else None,
                       'sized': {'units': round(su, 1), 'risked': round(risked, 1), 'roi': round(su / risked, 3) if risked else None},
                       'clv': round(sum(cl) / len(cl), 2) if cl else None, 'clvPos': round(sum(1 for c in cl if c > 0) / len(cl), 3) if cl else None}
    # this season so far: both rules on the games already played, at the close (the model's pregame margin; not
    # flagged live, so shown apart from the record)
    sofar = {}
    for typ in ('upset', 'fav'):
        bs = []
        for r in rows:
            if 'final' not in r or r.get('line') is None:
                continue
            m, L = r['margin'], r['line']
            mlH, mlA = odds(r['ml']['home']), odds(r['ml']['away'])
            side = upset_side(m, L) if typ == 'upset' else fav_side(m, L, mlH, mlA)
            o = (mlH if side == 'home' else mlA) if side else None
            if o is None:
                continue
            res = r['final']['home'] - r['final']['away']
            bs.append({'profit': grade_ml(side, res, o), 'stake': 1.0, 'won': res != 0 and (res > 0) == (side == 'home')})
        sofar[typ] = {**summ(bs), 'won': sum(1 for b in bs if b['won'])}
    picks = []
    for e in log:
        if e['season'] != season or e['week'] != week:
            continue
        p = {k: e[k] for k in ('id', 'type', 'side', 'team', 'home', 'away', 'kick', 'line', 'ml', 'model', 'edge', 'p', 'units', 'flagged')}
        p['now'] = fires.get((e['id'], e['type']))
        p['started'] = e['kick'] <= stamp
        if e.get('res') is not None:
            p['won'] = e['won']
        picks.append(p)
    picks.sort(key=lambda p: (p['kick'], p['id']))
    res = {'season': season, 'week': week, 'asof': stamp, 'picks': picks, 'upsetBt': bt.get('upset'), 'favBt': bt.get('fav'),
           'record': record, 'sofar': sofar, 'log': log}
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in res.items() if k != 'asof'})):
        return print('nfl picks: no change')
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(f'nfl picks: week {week}, {sum(1 for p in picks if p["type"] == "upset")} upset, {sum(1 for p in picks if p["type"] == "fav")} favorite')


if __name__ == '__main__':
    backtest() if '--backtest' in sys.argv else print(__doc__)
