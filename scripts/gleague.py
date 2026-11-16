# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""G League season totals (stats.gleague.nba.com, the league's own stats API) and the G League term in the NBA 1Y / 3Y.

    python3 scripts/gleague.py            # pull the current season into scripts/data/gleague.json (soft-fails, keeps cache)
    python3 scripts/gleague.py --all      # pull 2007-08 .. now
    python3 scripts/gleague.py --fit      # held-out check + coefficients into data/nba_proj3y_fit.json 'gleague' (numpy)

Index: Hollinger Game Score per 36 over the season's G League minutes, minus the minutes-weighted league mean,
shrunk  idx = (GS36 - mean) x MIN / (MIN + 400);  gl = 1 when G League MIN >= 200 (both fixed before any test).
Linked to the XPM board's ids by the shared name key (scripts/names.py), unique key only, age within 1.5.

Term: 1Y / 3Y (XPM given he plays) += a + b x idx for a player with gl = 1 this season; a, b fit on the residuals of
the live H4 form at season end, minutes weighted. a < 0: a season in the G League is itself a signal (the box score
he posts there counts for less than the NBA board's minutes say). The same a, b at every season share; idx shrinks
partial seasons by itself.
Test (pre-registered with an NBA-newcomer prior test, Holm over 2; /mnt/project-files/research/realgm-alt-nov16/):
NBA players under 1,000 board MP with a G League season, leave one season out. Shipped form F4 + [gl, gl x idx]
on the shrunk target: 1Y t -2.63 (10/14 seasons), 3Y t -3.89 (9/12). Live H4 form, given-he-plays target:
1Y RMSE 1.733 -> 1.682 t -2.28 (11/14), 3Y 1.524 -> 1.443 t -2.30 (10/12). The newcomer prior test failed (t +.18):
G League production says nothing about a call-up's first NBA season beyond a constant.
"""
import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as NM

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, 'data', 'gleague.json')
BOARD = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
FIT3 = os.path.join(ROOT, 'data', 'nba_proj3y_fit.json')
MIN_GL, K_GL = 200, 400
API = ('https://stats.gleague.nba.com/stats/leaguedashplayerstats?College=&Conference=&Country=&DateFrom=&DateTo=&Division='
       '&DraftPick=&DraftYear=&GameScope=&GameSegment=&Height=&LastNGames=0&LeagueID=20&Location=&MeasureType=Base&Month=0'
       '&OpponentTeamID=0&Outcome=&PORound=0&PaceAdjust=N&PerMode=Totals&Period=0&PlayerExperience=&PlayerPosition=&PlusMinus=N'
       '&Rank=N&Season={s}&SeasonSegment=&SeasonType=Regular%20Season&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=0'
       '&VsConference=&VsDivision=&Weight=')
HDR = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
       'Referer': 'https://gleague.nba.com/', 'Origin': 'https://gleague.nba.com', 'Accept': 'application/json'}


def current_season():
    t = time.gmtime()
    return t.tm_year + (t.tm_mon >= 10)


def pull(y):
    """season ending in y -> [[player id, name, age, MIN, Game Score total], ...] (one row per player, teams summed)"""
    req = urllib.request.Request(API.format(s=f'{y - 1}-{y % 100:02d}'), headers=HDR)
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())['resultSets'][0]
    h, agg = d['headers'], {}
    for r in d['rowSet']:
        x = dict(zip(h, r))
        if not x['PLAYER_NAME'] or not x['MIN']: continue
        gs = (x['PTS'] + .4 * x['FGM'] - .7 * x['FGA'] - .4 * (x['FTA'] - x['FTM']) + .7 * x['OREB'] + .3 * x['DREB']
              + x['STL'] + .7 * x['AST'] + .7 * x['BLK'] - .4 * x['PF'] - x['TOV'])
        a = agg.setdefault(x['PLAYER_ID'], [x['PLAYER_ID'], x['PLAYER_NAME'], x['AGE'], 0.0, 0.0])
        a[3] += x['MIN']; a[4] += gs
    return [[p, n, ag, round(m, 1), round(g, 1)] for p, n, ag, m, g in agg.values()]


def load():
    return json.load(open(CACHE)) if os.path.exists(CACHE) else {}


def save(seasons):
    c = load()
    for y in seasons:
        try:
            c[str(y)] = pull(y); print('gleague', y, len(c[str(y)]), flush=True)
        except Exception as e:
            print('gleague', y, 'not updated:', e, flush=True)
        time.sleep(3)
    json.dump(dict(sorted(c.items())), open(CACHE, 'w'), separators=(',', ':'))


def board_keys():
    keys = {}
    for fn in sorted(os.listdir(BOARD)):
        if not fn[:4].isdigit(): continue
        s = int(fn[:4])
        for p in json.load(open(os.path.join(BOARD, fn)))['players']:
            keys.setdefault(NM.key(p['n']), {}).setdefault(p['id'], {})[s] = p.get('age')
    return keys


def index(cache=None, keys=None):
    """{(season, board id): (gl, idx)}"""
    cache = load() if cache is None else cache
    keys = board_keys() if keys is None else keys
    out = {}
    for ys, rows in cache.items():
        y = int(ys)
        tm = sum(r[3] for r in rows)
        if not tm: continue
        mg = 36 * sum(r[4] for r in rows) / tm
        for pid, n, age, mn, gs in rows:
            c = keys.get(NM.key(n), {})
            if len(c) != 1 or not mn: continue
            (bid, ages), = c.items()
            ba = ages.get(y) or ages.get(y + 1)
            if ba and age and abs(ba - age) > 1.5: continue
            out[(y, bid)] = (mn >= MIN_GL, (36 * gs / mn - mg) * mn / (mn + K_GL))
    return out


def term(fit3, season):
    """board id -> (1Y add, 3Y add) for this season, or {} when the term is not fit"""
    g = (fit3 or {}).get('gleague')
    if not g: return {}
    return {bid: tuple(g[k][0] + g[k][1] * v for k in ('y1', 'y3y'))
            for (y, bid), (on, v) in index().items() if y == season and on}


def fit():
    import numpy as np
    import nba_proj3y_research as R
    import nba_proj3y_star_research as SR
    import nba_proj3y_play_research as PR
    gi = index()
    rows = SR.add_history(R.load()); rng = np.random.default_rng(0)
    SR.inputs_with_mp(rows, 1.0, rng)
    n, proj, prior, age, lm, M = R.inputs(rows, 1.0, rng)
    a = lambda k: np.array([r[k] for r in rows], float)
    d1 = (a('x1') + 2) * a('m1') / (a('m1') + 1000); d2 = (a('x2') + 2) * a('m2') / (a('m2') + 1000)
    B = SR.design('H4', proj, prior, age, lm, d1, d2, np.log1p(SR.MPF[0] + a('m1') + a('m2')))
    v = [gi.get((r['S'], r['id']), (False, 0.0)) for r in rows]
    gl = np.array([1.0 if on else 0.0 for on, _ in v]); ix = np.array([x if on else 0.0 for on, x in v])
    G = np.column_stack([gl, gl * ix])
    S = a('S'); FM = np.array([r['fmp'] for r in rows], float); FX = np.array([r['fx'] for r in rows], float)
    out, rep = {}, {}
    for tn, act, w, buf, last in (('y1', FX[:, 0], FM[:, 0], 1, 2025),
                                  ('y3y', (FX * FM).sum(1) / np.maximum(FM.sum(1), 1e-9), FM.sum(1), 3, 2023)):
        ok = (S <= last) & (w > 0)
        sub = ok & (gl == 1) & (a('mp') < 1000)
        p0, p1, won, ss = np.zeros(len(rows)), np.zeros(len(rows)), 0, sorted(set(S[sub].astype(int)))
        for c in ss:      # the shipped scheme: live base fit, then the additive term on its residuals
            tr, te = ok & (np.abs(S - c) > buf), sub & (S == c)
            cb = PR.wfit(B[tr], act[tr], w[tr]); res = act - B @ cb
            tg = tr & (gl == 1)
            cg = PR.wfit(G[tg], res[tg], w[tg])
            p0[te] = B[te] @ cb; p1[te] = p0[te] + G[te] @ cg
            won += np.average((p1[te] - act[te]) ** 2, weights=w[te]) < np.average((p0[te] - act[te]) ** 2, weights=w[te])
        ws, e0, e1 = w[sub], (p0 - act)[sub], (p1 - act)[sub]
        cb = PR.wfit(B[ok], act[ok], w[ok]); res = act - B @ cb; tg = ok & (gl == 1)
        out[tn] = [round(float(x), 4) for x in PR.wfit(G[tg], res[tg], w[tg])]
        rep[tn] = {'n': int(sub.sum()), 'rmse': [round(float(np.sqrt(np.average(e ** 2, weights=ws))), 3) for e in (e0, e1)],
                   't': round(R.tstat(ws * (e1 ** 2 - e0 ** 2), [rows[i]['id'] for i in np.where(sub)[0]]), 2),
                   'won': f'{won}/{len(ss)}'}
    print(json.dumps({'coef': out, 'heldOut': rep}, indent=1))
    if all(rep[k]['t'] <= -2 for k in rep):
        f3 = json.load(open(FIT3))
        f3['gleague'] = dict(out, minG=MIN_GL, k=K_GL, heldOut=rep)
        json.dump(f3, open(FIT3, 'w'), indent=1)
        print('written', FIT3)
    else:
        print('held-out check failed: term not written')


if __name__ == '__main__':
    if '--fit' in sys.argv: fit()
    elif '--all' in sys.argv: save(range(2008, current_season() + 1))
    else: save([current_season()])
