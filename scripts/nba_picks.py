#!/usr/bin/env python3
"""NBA picks (data/nba_picks.json, the picks tab on the NBA ARKBOARD): the college board's two fixed rules on the NBA
game model, listed every day whatever their backtest says, with that backtest shown beside them.

    upset picks     the model has the market underdog winning outright and sits more than UPSET_EDGE points off the line
    favorite picks  the moneyline favorite priced FAV_ML that the model makes a bigger favorite by more than FAV_EDGE

    python3 scripts/nba_picks.py --backtest     # data/nba_picks_fit.json: both rules on the 2015-26 walk-forward
                                                # predictions nba_games.py --fit leaves in scripts/.cache/nba/wf_preds.json

The live picks run inside nba_games.py's build (stdlib): each game is flagged at the line and price when the rule
first fires (ESPN's books, median), kept in the log, and graded once final on the moneyline at the flag price (the
spread at -110 when there was no moneyline), with closing line value against the close. Units: the Kelly stake at
the model's chance over the backtest's mean Kelly stake, clipped 0.25-3, so the average pick is 1 unit. The rules,
the edges and the sizing are nfl_picks.py's.
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nfl_picks as K
import clv as C

ROOT = os.path.dirname(HERE)
BT = os.path.join(ROOT, 'data', 'nba_picks_fit.json')
OUT = os.path.join(ROOT, 'data', 'nba_picks.json')
PREDS = os.path.join(ROOT, 'scripts', '.cache', 'nba', 'wf_preds.json')
HELD = 2022


def backtest():
    sys.path.insert(0, HERE)
    import nba_games as N
    F = json.load(open(N.FIT))
    sd = F['sd']
    rows = []
    for r in json.load(open(PREDS)):
        rows.append({**r, 'mlH': K.odds(r['mlH']), 'mlA': K.odds(r['mlA']), 'oH': K.odds(r['oH']), 'oA': K.odds(r['oA'])})
    res = {'sd': sd}
    for typ in ('upset', 'fav'):
        rule = (lambda r: K.upset_side(r['m'], r['L'])) if typ == 'upset' else (lambda r: K.fav_side(r['m'], r['L'], r['mlH'], r['mlA']))
        extra = {'edge': K.UPSET_EDGE} if typ == 'upset' else {'edge': K.FAV_EDGE, 'band': list(K.FAV_ML)}
        b = K.rule_backtest(rows, rule, sd, extra, held=HELD)
        # the spread at the opening line, where ESPN kept one (the rule judged on the open, -110): the nearest
        # history has to a line taken when the board publishes
        op = []
        for r in rows:
            if r.get('Lo') is None or C.bad_open_g('nba', 'spread', r):     # the shared cleaner (clv.py)
                continue
            ro = {**r, 'L': r['Lo']}
            side = rule(ro)
            if side and r['res'] != r['Lo']:
                clv = (r['L'] - r['Lo']) if side == 'home' else (r['Lo'] - r['L'])
                op.append({'S': r['S'], 'side': side, 'res': r['res'], 'stake': 1.0,
                           'profit': K.grade_spread(side, r['res'], r['Lo']), 'clv': clv})
        b['open'] = {**K.summ(op), 'clv': round(sum(x['clv'] for x in op) / len(op), 2) if op else None,
                     'clvPos': round(sum(1 for x in op if x['clv'] > 0) / len(op), 3) if op else None,
                     'seasons': sorted({x['S'] for x in op})}
        cuts = []
        for e in (2, 3, 4, 5, 6):
            if typ == 'upset':
                rl = lambda r, e=e: None if r['L'] == 0 or r['m'] * r['L'] >= 0 or abs(r['m'] - r['L']) <= e else ('away' if r['L'] > 0 else 'home')
            else:
                def rl(r, e=e):
                    side = 'home' if r['L'] > 0 else 'away'
                    o = r['mlH'] if side == 'home' else r['mlA']
                    if not r['L'] or o is None or not K.FAV_ML[0] <= o <= K.FAV_ML[1]:
                        return None
                    return side if (r['m'] if side == 'home' else -r['m']) - abs(r['L']) > e else None
            c = K.rule_backtest(rows, rl, sd, {}, held=HELD)['ml']
            cuts.append({'edge': e, 'ml': {k: c[k] for k in ('n', 'w', 'l', 'roi', 't')}})
        b['cuts'] = cuts
        res[typ] = b
    with open(BT, 'w') as f:
        json.dump(res, f, indent=1)
    for k in ('upset', 'fav'):
        print(k, {m: {kk: res[k][m].get(kk) for kk in ('n', 'w', 'l', 'roi', 't', 'won')} for m in ('ml', 'close', 'open')})
        print('  held out 2022-26', {m: res[k][m]['heldOut'] for m in ('ml', 'close')})


def live(rows, games, sd, season, day):
    """rows: the build's projections for the slate (id, margin, line, ml, tip, home, away). Flags games not yet
    tipped, keeps the log, grades it from games (compact, final with the close), writes data/nba_picks.json."""
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
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    fires = {}
    for r in rows:
        if r.get('line') is None or r.get('final') or not r.get('tip') or r['tip'] <= stamp:
            continue
        m, L = r['margin'], r['line']
        mlH, mlA = K.odds(r['ml']['home']), K.odds(r['ml']['away'])
        for typ, side in (('upset', K.upset_side(m, L)), ('fav', K.fav_side(m, L, mlH, mlA))):
            if not side:
                continue
            o = mlH if side == 'home' else mlA
            p = K.win_chance(side, m, sd) if o is not None else K.cover_chance(side, m, L, sd)
            b = bt.get(typ, {}).get('ml' if o is not None else 'close', {})
            units = round(K.stake(K.kelly(p, o if o is not None else -110), b.get('scale')) * 4) / 4
            fires[(r['id'], typ)] = {'line': -L if side == 'home' else L, 'ml': o}
            if (r['id'], typ) in seen:
                continue
            log.append({'id': r['id'], 'season': season, 'day': r['day'], 'type': typ, 'side': side, 'team': r[side],
                        'home': r['home'], 'away': r['away'], 'tip': r['tip'], 'L': L, 'line': -L if side == 'home' else L,
                        'ml': o, 'model': m, 'edge': round(abs(m - L), 1), 'p': round(p, 3), 'units': units, 'flagged': stamp})
            seen.add((r['id'], typ))
    G = {g['id']: g for g in games}
    for e in log:
        g = G.get(e['id'])
        if not g or e.get('res') is not None or not g.get('fin'):
            continue
        res = g['hs'] - g['as']
        e['res'] = res
        e['close'] = g.get('L')
        e['won'] = (res > 0) == (e['side'] == 'home')
        e['profit'] = round(K.grade_ml(e['side'], res, e['ml']) if e['ml'] is not None else K.grade_spread(e['side'], res, e['L']), 3)
        e['ats'] = round(K.grade_spread(e['side'], res, e['L']), 3)
        if e['close'] is not None:
            C.judge_pick(e, 'nba', e['close'], (K.odds(g.get('mlH')), K.odds(g.get('mlA'))))
    for e in log:
        # picks graded before closing line value was priced (Oct 21 2026)
        if e.get('res') is not None and e.get('close') is not None and 'clvRet' not in e:
            C.judge_pick(e, 'nba', e['close'])
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
        record[typ].update(C.summary(done))
    days = {r['day'] for r in rows}
    picks = []
    for e in log:
        if e['season'] != season or e['day'] not in days:
            continue
        p = {k: e[k] for k in ('id', 'type', 'side', 'team', 'home', 'away', 'tip', 'line', 'ml', 'model', 'edge', 'p', 'units', 'flagged', 'day')}
        p['now'] = fires.get((e['id'], e['type']))
        p['started'] = e['tip'] <= stamp
        if e.get('res') is not None:
            p['won'] = e['won']
        picks.append(p)
    picks.sort(key=lambda p: (p['tip'], p['id']))
    res = {'season': season, 'day': day, 'asof': stamp, 'picks': picks, 'upsetBt': bt.get('upset'), 'favBt': bt.get('fav'),
           'record': record, 'log': log}
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in res.items() if k != 'asof'})):
        return print('nba picks: no change')
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(f'nba picks: {sum(1 for p in picks if p["type"] == "upset")} upset, {sum(1 for p in picks if p["type"] == "fav")} favorite')


if __name__ == '__main__':
    backtest() if '--backtest' in sys.argv else print(__doc__)
