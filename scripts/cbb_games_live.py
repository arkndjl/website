#!/usr/bin/env python3
"""The daily build of the college basketball game model (python3 scripts/cbb_games.py, run by .github/workflows/cbb-board.yml):
data/cbb_games.json (the next two slates, power ratings, season odds) and data/cbb_picks.json.

This season's games and lines are kept in scripts/data/cbb_games_<season>.json.gz (committed): each run re-reads ESPN's
scoreboard for every date of the season (schedule, scores), refreshes the lines of games in the next two days (ESPN's
core odds, every book; the line at publish time for picks) and takes each final game's closing line once. Ratings start
from scripts/data/cbb_games_state.json (last season's final ratings, Elo and market ratings, written by --fit) and the
preseason prior from the board's rosters (scripts/cbb_prior.json.gz); Barttorvik supplies possessions and per-game minutes.
"""
import gzip
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import cbb_games as C
import cbb_games_hist as H
import numpy as np

SEASON = 2027
LOG = os.path.join(C.HERE, 'data', f'cbb_games_{SEASON}.json.gz')
PICKS_LEFT = 2                    # slates shown: today's and the next date with games
SIMS = 5000
# the season sims' strength shock, tuned on 2016-20 rest-of-season wins (CRPS t -5.6 against the old 3 x sqrt(8 / (8 +
# games)), 2021-26 t -9.8; conference wins -5.5 / -10.6; conference title log loss -0.8 / -4.7)
SHOCK_A, SHOCK_K, SHOCK_B = 2.0, 8.0, 4.0
POSTSEASON = re.compile(r'tournament|championship|playoff', re.I)     # conference games with these notes: the tournaments


def iso(d):
    """ESPN's '2026-11-01T14:30Z' as RFC 3339 with seconds (Hugo's time parses only that)"""
    return d[:-1] + ':00Z' if len(d) == 17 else d


def now_utc():
    return datetime.now(timezone.utc)


def fetch_json(url, timeout=40):
    for i in range(3):
        r = subprocess.run(['curl', '-s', '-m', str(timeout), '-A', H.UA, url], capture_output=True, text=True)
        try:
            return json.loads(r.stdout)
        except ValueError:
            continue
    return None


def parse(e):
    g = H.parse_event(e)
    if not g:
        return None
    c = e['competitions'][0]
    side = {x['homeAway']: x for x in c['competitors']}
    g['ha'], g['aa'] = side['home']['team'].get('abbreviation'), side['away']['team'].get('abbreviation')
    g['venue'] = (c.get('venue') or {}).get('fullName')
    if c.get('timeValid') is False:
        g['tba'] = True               # ESPN lists a date with no tip time yet (05:00Z)
    g['tv'] = ', '.join(n for b in c.get('broadcasts') or [] for n in b.get('names', []))
    for k in ('home', 'away'):
        rk = (side[k].get('curatedRank') or {}).get('current')
        if rk and rk <= 25:
            g[k[0] + 'ap'] = rk
    return g


def update_log():
    try:
        log = {g['id']: g for g in json.load(gzip.open(LOG))}
    except (OSError, ValueError):
        log = {}
    now = now_utc()
    today = (now - timedelta(hours=5)).strftime('%Y%m%d')
    ds = list(H.dates(SEASON))
    # every date: past ones only while a game there isn't final yet (or the date is within three days)
    final_dates = defaultdict(lambda: True)
    for g in log.values():
        d = C.et_date(g['date']).replace('-', '')
        final_dates[d] = final_dates[d] and g.get('hs') is not None
    recent = (now - timedelta(days=3)).strftime('%Y%m%d')
    want = [d for d in ds if d >= recent or not final_dates[d] or d not in {C.et_date(g['date']).replace('-', '') for g in log.values()}]
    with ThreadPoolExecutor(8) as ex:
        for j in ex.map(lambda d: fetch_json(H.SB.format(d=d)), want):
            for e in (j or {}).get('events', []):
                g = parse(e)
                if not g or g['season'] != SEASON:
                    continue
                old = log.get(g['id'], {})
                for k in ('spread', 'total', 'mlh', 'mla', 'open', 'book', 'closed', 'poss', 'hb', 'ab', 'seen'):
                    if k in old:
                        g[k] = old[k]
                log[g['id']] = g
    # lines: games in the next two days (current line), and each final game once (its close)
    soon = (now + timedelta(days=2)).isoformat()
    todo = [g for g in log.values() if (g.get('hs') is None and g['date'] <= soon and g['state'] == 'pre')
            or (g.get('hs') is not None and not g.get('closed'))]
    with ThreadPoolExecutor(16) as ex:
        for g, o in zip(todo, ex.map(lambda g: fetch_json(H.ODDS.format(i=g['id'])), todo)):
            if o is None:
                continue
            ln = H.pick_line(o.get('items', []))
            if ln.get('spread') is None and g.get('spread') is not None:
                ln = {}
            g.update(ln)
            if g.get('hs') is not None:
                g['closed'] = True
            elif ln.get('spread') is not None and 'seen' not in g:
                g['seen'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    # possessions and Barttorvik names (this season's super_sked)
    os.makedirs(C.CACHE, exist_ok=True)
    p = os.path.join(C.CACHE, f'bt_sked{SEASON}.csv')
    subprocess.run(['curl', '-s', '-m', '120', '-A', H.UA, f'https://barttorvik.com/{SEASON}_super_sked.csv', '-o', p], check=False)
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        bt = H.bart(SEASON)
        for g in log.values():
            if g.get('hs') is None or 'poss' in g:
                continue
            local = (datetime.fromisoformat(g['date'].replace('Z', '+00:00')) - timedelta(hours=6)).strftime('%Y-%m-%d')
            q = bt.get((local, tuple(sorted((g['hs'], g['as'])))))
            if q and len(q) == 1:
                g['poss'] = round(q[0][0], 1)
                if g['hs'] != g['as']:
                    g['hb'], g['ab'] = q[0][1][g['hs']], q[0][1][g['as']]
    rows = sorted(log.values(), key=lambda g: (g['date'], g['id']))
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with gzip.GzipFile(LOG, 'wb', mtime=0) as f:          # mtime 0: the same games make the same bytes (no empty commits)
        f.write(json.dumps(rows, separators=(',', ':')).encode())
    return rows


def avail_live():
    """this season's availability (value of rotation players who missed the team's last game) and their names"""
    logs = C.bt_logs(SEASON)
    if not logs:
        return {}, {}
    av = C.avail(logs)
    p = os.path.join(C.BTLOG, f'{SEASON}.json.gz')
    names = {}
    try:
        for r in json.load(gzip.open(p)):
            names[r[51]] = r[48]
    except Exception:
        pass
    out = {}
    for t, gl in logs.items():
        k = len(gl)
        if k < 3:
            continue
        st = {}
        for d, pl in gl:
            for pid, (mn, gb) in pl.items():
                s = st.setdefault(pid, [0, 0.0, 0.0]); s[0] += 1; s[1] += mn; s[2] += gb * mn
        last = gl[-1][1]
        miss = []
        for pid, (g, mn, bm) in st.items():
            if pid in last or g < 0.6 * k or mn / g < 12:
                continue
            miss.append({'name': names.get(pid, ''), 'mpg': round(mn / g, 1), 'bpm': round((bm - 150) / (mn + 150), 1)})
        if miss:
            out[t] = sorted(miss, key=lambda x: -x['mpg'])
    return av, out


def build():
    F = json.load(open(C.FIT))
    st = json.load(open(C.STATE))
    P, feats, coef, sd = F['params'], F['feats'], F['coef'], F['sd']
    rows = update_log()
    hist = C.load_hist()
    btname = C.bt_map(hist)
    tp, bt_live, confs = C.team_prior_live(SEASON, btname)
    btname.update(bt_live)
    # D-I: the board's teams, plus last season's rated teams with a full D-I schedule this season (non-D-I opponents
    # play a handful of D-I games and share one rating)
    sched = defaultdict(int)
    for g in rows:
        sched[g['home']] += 1; sched[g['away']] += 1
    d1 = set(bt_live) | {t for t in st['final'] if sched[t] >= 20}
    # a school the board has no conference for takes its conference-game opponents' (ESPN flags conference games)
    opp = defaultdict(lambda: defaultdict(int))
    for g in rows:
        if g.get('conf'):
            opp[g['home']][confs.get(g['away'], '')] += 1; opp[g['away']][confs.get(g['home'], '')] += 1
    for t in d1:
        if not confs.get(t):
            c = {k: v for k, v in opp[t].items() if k}
            if c:
                confs[t] = max(c, key=c.get)
    W = C.Walk(P, {SEASON: tp}, btname, coefs={SEASON: F['prior']})
    for t, v in st['elo'].items():
        W.elo[t] = v
    for t, v in st['mkt'].items():
        W.mkt[t] = v
    W.tlg = st.get('tlg', 140.0)
    W.final[SEASON - 1] = st['final']
    av, missing = avail_live()
    now = now_utc()
    today = (now - timedelta(hours=5)).strftime('%Y-%m-%d')
    dates = sorted({C.et_date(g['date']) for g in rows if C.et_date(g['date']) >= today and g['state'] != 'post'})
    show = set(dates[:PICKS_LEFT])
    upto = dates[PICKS_LEFT - 1] if len(dates) >= PICKS_LEFT else (dates[-1] if dates else None)
    proj = {}

    def collect(g, x, tx, R):
        m = sum(coef[f] * x[f] for f in feats)
        tot = sum(F['tcoef'][f] * tx[f] for f in C.TFEATS)
        proj[g['id']] = (m, tot, x, R.poss(g['home'], g['away']))
    R, pri, pfeats = C.season_walk(W, SEASON, rows, d1, av, collect, upto=upto or '0000')
    if not R.nobs and not upto:
        R.solve(0)
    names, logos, abbr = {}, {}, {}
    for g in rows:
        for k in ('home', 'away'):
            names[g[k]] = g[k[0] + 'n']; abbr[g[k]] = g.get(k[0] + 'a') or g[k[0] + 'n'][:4].upper()
    board = json.load(open(os.path.join(C.ROOT, 'static', 'data', 'cbb-all.json')))
    bc = {k: i for i, k in enumerate(board['cols'])}
    best = {}
    for r in board['rows']:
        m = re.search(r'/(\d+)\.png', r[bc['logo']] or '')
        if m:
            logos[m[1]] = r[bc['logo']]
            if r[bc['fv']] and (m[1] not in best or r[bc['fv']] > best[m[1]]['fv']):
                best[m[1]] = {'name': r[bc['name']], 'pos': r[bc['pos']], 'fv': r[bc['fv']]}
    logo = lambda t: logos.get(t) or f'https://a.espncdn.com/i/teamlogos/ncaa/500/{t}.png'

    # power ratings: points against an average D-I team on a neutral floor, from the game model's weights
    teams = sorted(t for t in d1 if t in R.ix)
    elo_avg = sum(W.elo[t] for t in teams) / len(teams)
    mkt_avg = sum(W.mkt[t] for t in teams) / len(teams)
    P0 = R.tau + float(np.mean([R.T[R.ix[t]] for t in teams])) * 2
    rating = {}
    for t in teams:
        x = {'eff': (R.net(t) - float(np.mean([R.net(u) for u in teams]))) * P0 / 100, 'elo': (W.elo[t] - elo_avg) / 25,
             'mkt': W.mkt[t] - mkt_avg, 'home': 0.0}
        rating[t] = sum(coef.get(f, 0.0) * x.get(f, 0.0) for f in feats)
    order = sorted(teams, key=lambda t: -rating[t])
    rk = {t: i + 1 for i, t in enumerate(order)}
    prior_rk = {t: i + 1 for i, t in enumerate(sorted(teams, key=lambda t: -pri.get(t, {}).get('net', -99)))}

    # records
    rec = defaultdict(lambda: [0, 0, 0, 0])
    for g in rows:
        if g.get('hs') is None:
            continue
        for t, w in ((g['home'], g['hs'] > g['as']), (g['away'], g['as'] > g['hs'])):
            rec[t][0 if w else 1] += 1
            if g.get('conf'):
                rec[t][2 if w else 3] += 1
    recs = lambda t: f'{rec[t][0]}-{rec[t][1]}'

    # season odds: the rest of the regular season simulated (conference tournaments and March left out); each team's
    # true strength drawn once a season around its rating, each game around its margin (the model's home court,
    # conference-home and altitude terms). The strength sd: sqrt(SHOCK_A^2 x SHOCK_K / (SHOCK_K + games played) +
    # SHOCK_B^2 x share of its regular season left), the rating's error plus its drift over the games left
    # (scripts/cbb_games_research.py sims: past seasons from Dec 1, Jan 15 and Feb 15)
    reg = lambda g: (g['stype'] == 2 and 'tournament' not in (g.get('note') or '').lower()
                     and not (g.get('conf') and POSTSEASON.search(g.get('note') or '')))
    left = [g for g in rows if g.get('hs') is None and reg(g) and g['home'] in rk and g['away'] in rk]
    nreg = defaultdict(int)
    for g in rows:
        if reg(g) and g['home'] in rk and g['away'] in rk:
            nreg[g['home']] += 1; nreg[g['away']] += 1
    sims = {}
    if left:
        ti = {t: i for i, t in enumerate(teams)}
        hi = np.array([ti[g['home']] for g in left]); ai = np.array([ti[g['away']] for g in left])
        cf = np.array([1.0 if g.get('conf') else 0.0 for g in left])
        mm = np.array([rating[g['home']] - rating[g['away']] + (0 if g['neutral'] else coef.get('home', 3.0) + coef.get('confh', 0.0) * c
                       + coef.get('alt', 0.0) * (g['home'] in C.ALT)) for g, c in zip(left, cf)])
        nleft = defaultdict(int)
        for g in left:
            nleft[g['home']] += 1; nleft[g['away']] += 1
        tsd = np.array([math.sqrt(SHOCK_A ** 2 * SHOCK_K / (SHOCK_K + R.ng[t]) + SHOCK_B ** 2 * nleft[t] / max(1, nreg[t])) for t in teams])
        rng = np.random.default_rng(int(now.strftime('%Y%m%d')))
        W_, CW, CL, title = np.zeros(len(teams)), np.zeros(len(teams)), np.zeros(len(teams)), np.zeros(len(teams))
        conf_of = np.array([confs.get(t, '') for t in teams])
        base_cw = np.array([rec[t][2] for t in teams], float); base_cl = np.array([rec[t][3] for t in teams], float)
        for chunk in range(SIMS // 1000):
            shock = rng.normal(0, 1, (1000, len(teams))) * tsd
            m = mm + shock[:, hi] - shock[:, ai]
            hw = (m + rng.normal(0, sd, m.shape)) > 0
            w = np.zeros((1000, len(teams))); cw = np.zeros((1000, len(teams))); cl = np.zeros((1000, len(teams)))
            for arr, idx, val in ((w, hi, hw), (w, ai, ~hw)):
                np.add.at(arr, (slice(None), idx), val.astype(float))
            np.add.at(cw, (slice(None), hi), (hw * cf)); np.add.at(cw, (slice(None), ai), (~hw * cf))
            np.add.at(cl, (slice(None), hi), (~hw * cf)); np.add.at(cl, (slice(None), ai), (hw * cf))
            W_ += w.sum(0); CW += cw.sum(0); CL += cl.sum(0)
            pct = (base_cw + cw) - (base_cl + cl)
            for c in set(conf_of):
                if not c:
                    continue
                k = conf_of == c
                top = pct[:, k].max(1, keepdims=True)
                title[k] += (pct[:, k] >= top - 1e-9).sum(0)
        for t, i in ti.items():
            sims[t] = {'xW': rec[t][0] + W_[i] / SIMS, 'xL': rec[t][1] + (sum(1 for g in left if t in (g['home'], g['away'])) - W_[i] / SIMS),
                       'cxW': rec[t][2] + CW[i] / SIMS, 'cxL': rec[t][3] + CL[i] / SIMS, 'title': title[i] / SIMS}

    power = []
    for t in order:
        k = R.ix[t]
        s = sims.get(t, {})
        power.append({'rk': rk[t], 'id': t, 't': names.get(t, t), 'logo': logo(t), 'conf': confs.get(t, ''),
                      'rating': round(rating[t], 1), 'off': round(float(R.mu + R.O[k]), 1), 'def': round(float(R.mu - R.D[k]), 1),
                      'tempo': round(float(R.tau + R.T[k]), 1), 'elo': round(W.elo[t]), 'mkt': round(W.mkt[t] - mkt_avg, 1),
                      'prior': round(pri.get(t, {}).get('net', 0.0), 1), 'priorRk': prior_rk.get(t), 'rec': recs(t),
                      'crec': f'{rec[t][2]}-{rec[t][3]}', 'xW': round(s['xW'], 1) if s else None, 'xL': round(s['xL'], 1) if s else None,
                      'cxW': round(s['cxW'], 1) if s else None, 'cxL': round(s['cxL'], 1) if s else None,
                      'title': round(s['title'], 3) if s else None, 'g': R.ng[t]})

    # the slates
    labels = {'eff': 'efficiency', 'elo': 'Elo', 'mkt': 'market', 'home': 'home court', 'inj': 'availability', 'rest': 'rest',
              'confh': 'conference home', 'alt': 'altitude', 'early': 'preseason prior', 'tourn': 'tournament', 'form': 'form', 'mkteff': 'early market'}
    out_games = []
    for g in rows:
        d = C.et_date(g['date'])
        if d not in show or g['id'] not in proj:
            continue
        m, tot, x, poss = proj[g['id']]
        L = -g['spread'] if g.get('spread') is not None else None
        ph = C.phi(m / sd)
        side = lambda k: {'id': g[k], 'n': names.get(g[k], g[k]), 'ab': abbr.get(g[k]), 'logo': logo(g[k]), 'rec': recs(g[k]),
                          'rk': rk.get(g[k]), 'ap': g.get(k[0] + 'ap'), 'conf': confs.get(g[k], ''), 'best': best.get(g[k])}
        item = {'id': g['id'], 'date': d, 'kick': iso(g['date']), 'home': side('home'), 'away': side('away'), 'neutral': g['neutral'],
                'tba': g.get('tba') or None, 'confGame': g.get('conf'), 'note': g.get('note') or None, 'venue': g.get('venue'), 'tv': g.get('tv') or None,
                'margin': round(m, 1), 'total': round(tot, 1), 'pHome': round(ph, 3), 'poss': round(poss, 1),
                'hs': round((tot + m) / 2), 'as': round((tot - m) / 2), 'line': L, 'tline': g.get('total'),
                'ml': {'home': g.get('mlh'), 'away': g.get('mla')} if g.get('mlh') else None, 'book': g.get('book'),
                'edge': round(m - L, 1) if L is not None else None,
                'parts': {labels[f]: round(coef[f] * x[f], 1) for f in feats if abs(coef[f] * x[f]) >= 0.5},
                'q': (rk.get(g['home'], 400) + rk.get(g['away'], 400))}
        for k in ('home', 'away'):
            mi = missing.get(btname.get(g[k]))
            if mi and g.get('hs') is None:
                item[k[0] + 'out'] = mi[:3]
        if g.get('hs') is not None:
            item['final'] = {'home': g['hs'], 'away': g['as']}
        out_games.append(item)
    out_games.sort(key=lambda z: (z['date'], z['q'], z['kick']))
    # model against the line this season, games already played (pregame margin, close)
    ats = [0, 0, 0]
    for g in rows:
        if g.get('hs') is None or g['id'] not in proj or g.get('spread') is None:
            continue
        m = proj[g['id']][0]; L = -g['spread']; r = g['hs'] - g['as']
        if abs(m - L) < 1 or r == L:
            ats[2] += r == L
            continue
        ats[0 if (m - L > 0) == (r - L > 0) else 1] += 1
    res = {'asof': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'season': f'{SEASON - 1}-{str(SEASON)[2:]}', 'sd': sd, 'tsd': F['tsd'],
           'dates': sorted(show), 'games': out_games, 'power': power, 'sims': SIMS if sims else 0, 'left': len(left),
           'ats': {'w': ats[0], 'l': ats[1]}, 'played': sum(1 for g in rows if g.get('hs') is not None),
           'test': F['test'], 'coef': coef, 'feats': feats}
    old = None
    try:
        old = json.load(open(C.OUT))
    except (OSError, ValueError):
        pass
    if old and {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in res.items() if k != 'asof'})):
        print('cbb games: no change')
    else:
        with open(C.OUT, 'w') as f:
            json.dump(res, f, separators=(',', ':'))
        print(f'cbb games: {len(out_games)} games on {sorted(show)}, {len(power)} teams rated, {len(left)} games simulated')
    import cbb_picks
    cbb_picks.live(rows, proj, sd)
