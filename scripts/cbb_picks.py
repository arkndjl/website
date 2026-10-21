#!/usr/bin/env python3
"""College basketball picks (data/cbb_picks.json, the picks tab on the College Basketball ARKBOARD): the college
football board's two fixed rules on the college basketball game model, listed every day whatever their backtest says,
with that backtest shown beside them.

    upset picks     the model has the market underdog winning outright and sits more than 4 points off the line
    favorite picks  the moneyline favorite priced -105 to -200 that the model makes a bigger favorite by more than 4

    python3 scripts/cbb_picks.py --backtest    # data/cbb_picks_fit.json: both rules on the 2016-26 walk-forward
                                               # predictions (scripts/cbb_games.py --fit writes them; 2021-26 held out)

Live (inside scripts/cbb_games.py's daily build): a game is flagged at the line and price when the rule first fires
(ESPN's lines, refreshed each run until tip), kept in the log, graded once final on the moneyline at the flagged price
(the spread at -110 when there was no moneyline), with closing line value against the close ESPN lists after the game.
Units: the Kelly stake at the model's chance over the backtest's average Kelly stake, clipped 0.25 to 3 (mean 1u).
The rules and the grading are the NFL picks' (scripts/nfl_picks.py); the line is the home side's expected margin.
"""
import gzip
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_picks as N
import clv as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BT = os.path.join(ROOT, 'data', 'cbb_picks_fit.json')
OUT = os.path.join(ROOT, 'data', 'cbb_picks.json')
WALK = os.path.join(ROOT, 'scripts', '.cache', 'cbb', 'games', 'walk_pred.json.gz')


def backtest():
    F = json.load(open(os.path.join(ROOT, 'data', 'cbb_games_fit.json')))
    sd = F['sd']
    rows = []
    for r in json.load(gzip.open(WALK)):
        if r['L'] is None:
            continue
        rows.append({'S': r['S'], 'm': r['m'], 'L': r['L'], 'res': r['res'], 'mlH': N.odds(r['mlH']), 'mlA': N.odds(r['mlA']), 'oH': None, 'oA': None})
    res = {'sd': sd, 'upset': N.rule_backtest(rows, lambda r: N.upset_side(r['m'], r['L']), sd, {'edge': N.UPSET_EDGE}),
           'fav': N.rule_backtest(rows, lambda r: N.fav_side(r['m'], r['L'], r['mlH'], r['mlA']), sd, {'edge': N.FAV_EDGE, 'band': list(N.FAV_ML)})}
    for k in ('upset', 'fav'):
        cuts = []
        for e in (2, 3, 4, 5, 6, 8):
            if k == 'upset':
                rl = lambda r, e=e: None if r['L'] == 0 or r['m'] * r['L'] >= 0 or abs(r['m'] - r['L']) <= e else ('away' if r['L'] > 0 else 'home')
            else:
                def rl(r, e=e):
                    side = 'home' if r['L'] > 0 else 'away'
                    o = r['mlH'] if side == 'home' else r['mlA']
                    if not r['L'] or o is None or not N.FAV_ML[0] <= o <= N.FAV_ML[1]:
                        return None
                    return side if (r['m'] if side == 'home' else -r['m']) - abs(r['L']) > e else None
            b = N.rule_backtest(rows, rl, sd, {})['ml']
            cuts.append({'edge': e, 'ml': {'n': b['n'], 'w': b['w'], 'l': b['l'], 'roi': b['roi'], 't': b['t']}})
        res[k]['cuts'] = cuts
    with open(BT, 'w') as f:
        json.dump(res, f, indent=1)
    for k in ('upset', 'fav'):
        print(k, {m: {kk: res[k][m][kk] for kk in ('n', 'w', 'l', 'roi', 't', 'sized', 'won')} for m in ('ml', 'close')})
        print('  held out 2021-26', {m: res[k][m]['heldOut'] for m in ('ml', 'close')})


def live(games, proj, sd):
    """games: this season's log (scripts/cbb_games_live.py); proj: id -> (margin, total, inputs, possessions) for the
    games projected this run. Flags games that haven't tipped, keeps the log, grades it, writes data/cbb_picks.json."""
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
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    G = {g['id']: g for g in games}
    fires = {}
    for gid, (m, _, _, _) in proj.items():
        g = G[gid]
        if g.get('hs') is not None or g.get('spread') is None or g['date'] <= stamp[:16] + 'Z' or g.get('state') != 'pre' or g.get('tba'):
            continue
        L = -g['spread']
        mlH, mlA = N.odds(g.get('mlh')), N.odds(g.get('mla'))
        for typ, side in (('upset', N.upset_side(m, L)), ('fav', N.fav_side(m, L, mlH, mlA))):
            if not side:
                continue
            o = mlH if side == 'home' else mlA
            p = N.win_chance(side, m, sd) if o is not None else N.cover_chance(side, m, L, sd)
            b = bt.get(typ, {}).get('ml' if o is not None else 'close', {})
            units = round(N.stake(N.kelly(p, o if o is not None else -110), b.get('scale')) * 4) / 4
            fires[(gid, typ)] = {'line': -L if side == 'home' else L, 'ml': o}
            if (gid, typ) in seen:
                continue
            log.append({'id': gid, 'season': g['season'], 'date': g['date'][:10], 'type': typ, 'side': side, 'team': g[side[0] + 'n'],
                        'teamId': g[side], 'opp': g[('away' if side == 'home' else 'home')[0] + 'n'], 'neutral': g['neutral'],
                        'kick': g['date'][:-1] + ':00Z' if len(g['date']) == 17 else g['date'], 'L': L, 'line': -L if side == 'home' else L, 'ml': o, 'model': round(m, 1),
                        'edge': round(abs(m - L), 1), 'p': round(p, 3), 'units': units, 'flagged': stamp})
            seen.add((gid, typ))
    for e in log:
        g = G.get(e['id'])
        if not g or e.get('res') is not None or g.get('hs') is None:
            continue
        res = g['hs'] - g['as']
        e['res'] = res
        e['close'] = -g['spread'] if g.get('closed') and g.get('spread') is not None else None
        e['won'] = res != 0 and (res > 0) == (e['side'] == 'home')
        e['profit'] = round(N.grade_ml(e['side'], res, e['ml']) if e['ml'] is not None else N.grade_spread(e['side'], res, e['L']), 3)
        if e['close'] is not None:
            C.judge_pick(e, 'cbb', e['close'], (N.odds(g.get('mlh')), N.odds(g.get('mla'))) if g.get('closed') else None)
    for e in log:
        # picks graded before closing line value was priced (Oct 21 2026)
        if e.get('res') is not None and e.get('close') is not None and 'clvRet' not in e:
            C.judge_pick(e, 'cbb', e['close'])
    record = {}
    for typ in ('upset', 'fav'):
        done = [e for e in log if e['type'] == typ and e.get('res') is not None]
        n = len(done)
        u = sum(e['profit'] for e in done)
        risked = sum(e['units'] for e in done)
        su = sum(e['units'] * e['profit'] for e in done)
        cl = [e['clv'] for e in done if e.get('clv') is not None]
        record[typ] = {'n': n, 'won': sum(1 for e in done if e['won']), 'w': sum(1 for e in done if e['profit'] > 0),
                       'l': sum(1 for e in done if e['profit'] < 0), 'units': round(u, 1), 'roi': round(u / n, 3) if n else None,
                       'sized': {'units': round(su, 1), 'risked': round(risked, 1), 'roi': round(su / risked, 3) if risked else None},
                       'clv': round(sum(cl) / len(cl), 2) if cl else None, 'clvPos': round(sum(1 for c in cl if c > 0) / len(cl), 3) if cl else None}
        record[typ].update(C.summary(done))
    # open picks (not yet final) and the last three days' graded ones
    recent = sorted({e['date'] for e in log if e.get('res') is not None})[-3:]
    picks = []
    for e in log:
        if e.get('res') is not None and e['date'] not in recent:
            continue
        p = {k: e.get(k) for k in ('id', 'type', 'side', 'team', 'teamId', 'opp', 'neutral', 'kick', 'line', 'ml', 'model', 'edge', 'p', 'units', 'flagged', 'won', 'profit', 'clv', 'clvRet')}
        p['now'] = fires.get((e['id'], e['type']))
        p['started'] = e['kick'] <= stamp
        picks.append(p)
    picks.sort(key=lambda p: (p.get('won') is not None, p['kick'], p['id']))
    res = {'asof': stamp, 'picks': picks, 'upsetBt': bt.get('upset'), 'favBt': bt.get('fav'), 'record': record, 'log': log}
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in res.items() if k != 'asof'})):
        return print('cbb picks: no change')
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(f'cbb picks: {sum(1 for p in picks if p["type"] == "upset" and p.get("won") is None)} upset, '
          f'{sum(1 for p in picks if p["type"] == "fav" and p.get("won") is None)} favorite open')


if __name__ == '__main__':
    backtest() if '--backtest' in sys.argv else print(__doc__)
