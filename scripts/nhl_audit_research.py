#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL audit tests on three free sources the models had not used (pre-registered: research/prereg/hockey-2026-11-13.md).

    python3 scripts/nhl_audit_research.py --pull    # SBR odds pages, right-rail (referees, coaches, power plays), EDGE
    python3 scripts/nhl_audit_research.py           # the tests -> data/nhl_audit_research.json

Sources
  SBR   sportsbookreviewsonline.com NHL archive, 2007-08 to 2022-23: opening and closing moneyline, opening and closing
        total with prices (the visitor's row carries the over price, the home row the under: the line moves up 95% of
        the time when the visitor's row is the juiced one, 6% when the home row is). Parsed rows are committed
        (scripts/data/odds_hist/sbr_nhl.json.gz, by NHL game id). Used as the close for 2011-2019; ESPN from 2019-20.
  RR    api-web.nhle.com gamecenter/<id>/right-rail: referees, head coaches, power plays, every game 2010-11 on.
  EDGE  api-web.nhle.com edge/skater-detail: top speed, 20+ mph bursts, top shot speed, zone time, 2021-22 on.
Tests (one Holm family of six; ship rule: tuning t >= 1.5 and the held-out one-sided p past Holm)
  A1 mkt     market rating with SBR closes behind it, added to the win model
  A2 nc      new head coach in his first 20 games, home minus away, added to the win model
  B1         totals regression trained on 2016+ (SBR closes) against the live one (ESPN-lined, 2020+)
  B2 refPP   the two referees' shrunk power plays a game over the league's, added to the totals model
  C1 EDGE    four tracking inputs added to next season's skater rate (leave one target season out)
  D1         model total against the opening total at SBR's opening price (X tuned 2017-20, verdict 2021-23)
Measured: the model against the SBR close 2017-19; lineup value with weights known at the time (now the default:
scripts/nhl_players.py nested()).
"""
import datetime as dt
import gzip
import html
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H             # noqa: E402
import nhl_data as D            # noqa: E402
import nhl_games as G           # noqa: E402

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(D.CACHE, 'audit')
SBR_DIR = next((p for p in ('/mnt/project-files/research/sbr-mirror',) if os.path.isdir(p)), os.path.join(CACHE, 'sbr'))
SBR_OUT = os.path.join(HERE, 'data', 'odds_hist', 'sbr_nhl.json.gz')
RR = os.path.join(CACHE, 'rr.jsonl')
EDGE = os.path.join(CACHE, 'edge.jsonl')
OUT = os.path.join(ROOT, 'data', 'nhl_audit_research.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
SBR_PAGES = ['2007-08', '2008-09', '2009-10', '2010-11', '2011-12', '2012-13', '2013-14', '2014-15', '2015-16', '2016-17',
             '2017-18', '2018-19', '2019-20', '2021', '2021-22', '2022-23']
SBR_TEAM = {'Anaheim': 'ANA', 'Arizona': 'UTA', 'Phoenix': 'UTA', 'Atlanta': 'WPG', 'Boston': 'BOS', 'Buffalo': 'BUF',
            'Calgary': 'CGY', 'Carolina': 'CAR', 'Chicago': 'CHI', 'Colorado': 'COL', 'Columbus': 'CBJ', 'Dallas': 'DAL',
            'Detroit': 'DET', 'Edmonton': 'EDM', 'Florida': 'FLA', 'LosAngeles': 'LAK', 'Minnesota': 'MIN', 'Montreal': 'MTL',
            'Nashville': 'NSH', 'NewJersey': 'NJD', 'NYIslanders': 'NYI', 'NYRangers': 'NYR', 'Ottawa': 'OTT',
            'Philadelphia': 'PHI', 'Pittsburgh': 'PIT', 'SanJose': 'SJS', 'St.Louis': 'STL', 'TampaBay': 'TBL', 'Tampa': 'TBL',
            'Toronto': 'TOR', 'Vancouver': 'VAN', 'Vegas': 'VGK', 'Washington': 'WSH', 'Winnipeg': 'WPG', 'WinnipegJets': 'WPG',
            'Seattle': 'SEA', 'SeattleKraken': 'SEA'}
REF_K, NC_GAMES, EDGE_MIN = 80, 20, 400


def fetch(url, tries=4):
    err = None
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=40).read()
        except Exception as e:
            err = e
            time.sleep(2 + 3 * k)
    raise err


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


# ---------------------------------------------------------------- pulls
def pull_sbr():
    os.makedirs(SBR_DIR, exist_ok=True)
    for y in SBR_PAGES:
        fn = os.path.join(SBR_DIR, f'nhl-odds-{y}.html')
        if not os.path.exists(fn):
            open(fn, 'wb').write(fetch(f'https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-{y}/'))
            time.sleep(1)

    def num(s):
        try:
            return float(s)
        except ValueError:
            return None
    by = defaultdict(list)
    for y in SBR_PAGES:
        s = open(os.path.join(SBR_DIR, f'nhl-odds-{y}.html'), encoding='utf8', errors='ignore').read()
        rows = [[html.unescape(re.sub('<[^>]+>', '', c)).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)]
                for r in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S)]
        rows = [r for r in rows[1:] if len(r) >= 14]
        y0, i = int(y[:4]), 0
        while i + 1 < len(rows):
            a, b = rows[i], rows[i + 1]
            if not (a[2] in 'VN' and b[2] in 'HN'):
                i += 1
                continue
            i += 2
            mo, d = int(a[0]) // 100, int(a[0]) % 100
            year = 2021 if y == '2021' else 2020 if (y == '2019-20' and mo in (8, 9)) else y0 if mo >= 8 else y0 + 1
            ta, tb = SBR_TEAM.get(a[3].replace(' ', '')), SBR_TEAM.get(b[3].replace(' ', ''))
            if not ta or not tb:
                continue
            # home, away closing and opening moneylines; total and its over (visitor row) / under (home row) price
            by[f'{year}-{mo:02d}-{d:02d}'].append({'h': tb, 'a': ta, 'hs': num(b[7]), 'as': num(a[7]),
                                                  'mlo': [num(b[8]), num(a[8])], 'mlc': [num(b[9]), num(a[9])],
                                                  'to': num(a[-4]) if num(a[-4]) == num(b[-4]) else None,
                                                  'top': [num(a[-3]), num(b[-3])],
                                                  'tc': num(a[-2]) if num(a[-2]) == num(b[-2]) else None,
                                                  'tcp': [num(a[-1]), num(b[-1])]})
    out, used = {}, set()
    for g in G.load_hist():
        if g['S'] > 2023:
            continue
        for k in (0, -1, 1):
            day = (dt.date.fromisoformat(g['day']) + dt.timedelta(days=k)).isoformat()
            hit = next((i for i, r in enumerate(by.get(day, [])) if r['h'] == g['h'] and r['a'] == g['a'] and (day, i) not in used), None)
            if hit is not None:
                used.add((day, hit))
                out[str(g['id'])] = {k2: v for k2, v in by[day][hit].items() if k2 not in ('h', 'a', 'hs', 'as')}
                break
    D.save(SBR_OUT, out)
    print('sbr games', len(out), 'by season', sorted(Counter(g['S'] for g in G.load_hist() if str(g['id']) in out).items()))


def _pull_lines(path, todo, get, workers):
    done = set()
    if os.path.exists(path):
        done = {json.loads(l)['k'] for l in open(path)}
    todo = [t for t in todo if json.dumps(t) not in done]
    print(os.path.basename(path), len(todo), 'to pull', flush=True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with ThreadPoolExecutor(workers) as ex, open(path, 'a') as f:
        for t, r in zip(todo, ex.map(get, todo)):
            if r is not None:
                f.write(json.dumps(dict(r, k=json.dumps(t))) + '\n')


def pull_rr():
    def get(i):
        try:
            d = json.loads(fetch(f'https://api-web.nhle.com/v1/gamecenter/{i}/right-rail'))
        except Exception:
            return None
        gi = d.get('gameInfo') or {}
        pp = next((x for x in d.get('teamGameStats', []) if x.get('category') == 'powerPlay'), {})
        return {'id': i, 'ref': [r['fullName']['default'] for r in gi.get('referees', [])],
                'coach': [(gi.get(s) or {}).get('headCoach', {}).get('default') for s in ('homeTeam', 'awayTeam')],
                'pp': [pp.get('homeValue'), pp.get('awayValue')]}
    _pull_lines(RR, [g['id'] for g in G.load_hist()], get, 6)


def pull_edge():
    todo = []
    for S in range(2022, D.current_season()):
        for p in json.load(open(os.path.join(G.WARD, f'{S}.json')))['players']:
            if p['grp'] != 'G' and p['toi'] >= 300:
                todo.append([p['id'], S])

    def get(t):
        try:
            d = json.loads(fetch(f'https://api-web.nhle.com/v1/edge/skater-detail/{t[0]}/{t[1] - 1}{t[1]}/2'))
        except Exception:
            return None
        sk, z = d.get('skatingSpeed') or {}, d.get('zoneTimeDetails') or {}
        return {'id': t[0], 'S': t[1], 'spd': (sk.get('speedMax') or {}).get('imperial'),
                'b20': (sk.get('burstsOver20') or {}).get('value'), 'shot': (d.get('topShotSpeed') or {}).get('imperial'),
                'oz': z.get('offensiveZonePctg')}
    _pull_lines(EDGE, todo, get, 3)


# ---------------------------------------------------------------- inputs
def sbr_close(r):
    h, a = r['mlc']
    if not h or not a or abs(h) < 100 or abs(a) < 100:
        return None
    ih, ia = G.implied(h), G.implied(a)
    if not 1.0 <= ih + ia <= 1.10:
        return None
    c = {'p': round(ih / (ih + ia), 4), 'ml': [h, a]}
    if r.get('tc') and 3.5 <= r['tc'] <= 9.5:
        c['t'] = r['tc']
    return c


def with_sbr(hist, sbr):
    out = []
    for g in hist:
        r = sbr.get(str(g['id']))
        c = sbr_close(r) if r and g['S'] <= 2019 else None
        out.append(dict(g, c=c) if c else g)
    return out


def ppo(r):
    try:
        return sum(int(str(v).split('/')[1]) for v in r['pp'])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def rr_inputs(hist):
    """pre-game nc (new coach, home minus away) and refPP by game id, walking the history in start order"""
    rr = {}
    if os.path.exists(RR):
        for l in open(RR):
            r = json.loads(l)
            rr[r['id']] = r
    nc, ref = {}, {}
    first, cg = {}, defaultdict(int)
    rn, rs = defaultdict(int), defaultdict(float)
    ls, ln, prev, cur = 0.0, 0, None, None
    for g in hist:
        S = g['S']
        if S != cur:
            if cur is not None and ln:
                prev = ls / ln
            ls, ln, cur = 0.0, 0, S
        r = rr.get(g['id'])
        if not r:
            continue
        lm = ls / ln if ln >= 100 else prev if prev is not None else (ls / ln if ln else None)
        fl = []
        for t, c in zip((g['h'], g['a']), r.get('coach') or [None, None]):
            fl.append(int(bool(c) and c != first.setdefault((S, t), c) and cg[(S, t, c)] < NC_GAMES))
        nc[g['id']] = fl[0] - fl[1]
        refs = (r.get('ref') or [])[:2]
        v = [rs[x] / (rn[x] + REF_K) for x in refs]
        ref[g['id']] = float(np.mean(v)) if v else 0.0
        for t, c in zip((g['h'], g['a']), r.get('coach') or [None, None]):
            if c:
                cg[(S, t, c)] += 1
        o = ppo(r)
        if o is not None and not g.get('po'):
            if lm is not None:
                for x in refs:
                    rn[x] += 1
                    rs[x] += o - lm
            ls += o
            ln += 1
    return nc, ref, len(rr)


def cut(r):
    return {'d': round(float(r['d']), 5), 't': round(float(r['t']), 2), 'p': round(float(r['p']), 4), 'n': int(r['n'])}


# ---------------------------------------------------------------- tests
def main():
    hist = G.load_hist()
    sbr = D.load(SBR_OUT)
    fit = json.load(open(G.FIT))
    P, feats = fit['params'], fit['feats']
    mv = G.hist_moves(hist)
    _, rows0, _ = G.walk(hist, P, moves=mv)
    _, rows1, _ = G.walk(with_sbr(hist, sbr), P, moves=mv)
    nc, ref, nrr = rr_inputs(hist)
    for g, f in rows1:
        f['nc'] = nc.get(g['id'], 0)
        f['refPP'] = ref.get(g['id'], 0.0)
    S, y, mg, tot, pc, tc, day = G.arrays(rows1)
    tc0 = G.arrays(rows0)[5]
    tune, held = (S >= 2017) & (S <= 2023), S >= 2024
    out = {'asof': dt.date.today().isoformat(), 'prereg': 'research/prereg/hockey-2026-11-13.md',
           'data': {'sbrGames': len(sbr), 'rightRailGames': nrr}, 'tests': {}, 'measured': {}}

    def wl(fs):
        return H.logloss(G.walk_logit(G.design(rows1, fs), y, S, G.SCORE_FROM + 1), y)
    lb = wl(feats)
    # the model against the close, 2017-19 on SBR, then ESPN
    p = G.walk_logit(G.design(rows1, feats), y, S, G.SCORE_FROM + 1)
    for lab, m in (('2017-19', (S >= 2017) & (S <= 2019)), ('2020-23', (S >= 2020) & (S <= 2023)), ('2024-26', held)):
        k = m & ~np.isnan(p) & ~np.isnan(pc)
        z, zc = np.log(p[k] / (1 - p[k])), np.log(pc[k] / (1 - pc[k]))
        out['measured'][f'close {lab}'] = {'n': int(k.sum()), 'model': round(float(H.logloss(p[k], y[k]).mean()), 4),
                                           'close': round(float(H.logloss(pc[k], y[k]).mean()), 4),
                                           't': round(float(H.paired(H.logloss(p[k], y[k]), H.logloss(pc[k], y[k]), day[k])['t']), 2),
                                           'sdRatio': round(float(z.std() / zc.std()), 3)}
    for name, key in (('A1 mkt', 'mkt'), ('A2 nc', 'nc')):
        l1 = wl(feats + [key])
        out['tests'][name] = {'tune': cut(H.paired(l1[tune], lb[tune], day[tune])), 'held': cut(H.paired(l1[held], lb[held], day[held]))}
    # totals
    lt0, lt1 = ~np.isnan(tc0), ~np.isnan(tc)
    T0 = G.walk_ols(G.design(rows0, G.TFEATS), tot, S, G.FIRST_TEST, lt0)
    T1 = G.walk_ols(G.design(rows1, G.TFEATS), tot, S, G.FIRST_TEST, lt1)
    T2 = G.walk_ols(G.design(rows1, G.TFEATS + ['refPP']), tot, S, G.FIRST_TEST, lt1)
    for name, new, base in (('B1 totals 2016+', T1, T0), ('B2 refPP', T2, T1)):
        res = {}
        for lab, m in (('tune', (S >= 2021) & (S <= 2023)), ('held', held)):
            k = m & lt0 & ~np.isnan(new) & ~np.isnan(base)
            res[lab] = cut(H.paired((new[k] - tot[k]) ** 2, (base[k] - tot[k]) ** 2, day[k]))
        out['tests'][name] = res
    # totals at the open
    Tw = G.walk_ols(G.design(rows1, G.TFEATS), tot, S, 2017, lt1)
    recs = []
    for i, (g, f) in enumerate(rows1):
        r = sbr.get(str(g['id']))
        if not r or np.isnan(Tw[i]) or not r.get('to') or None in r['top'] or min(abs(v) for v in r['top']) < 100:
            continue
        if not 1.0 <= 1 / dec(r['top'][0]) + 1 / dec(r['top'][1]) <= 1.10 or not 3.5 <= r['to'] <= 9.5:
            continue
        recs.append((g['S'], g['day'], Tw[i], r['to'], r['top'][0], r['top'][1], g['hs'] + g['as']))

    def open_rule(seasons, X):
        pr, dd = [], []
        for s, d, t, L, po, pu, goals in recs:
            if s in seasons and abs(t - L) >= X:
                over = t > L
                pr.append(0.0 if goals == L else (dec(po if over else pu) - 1 if (goals > L) == over else -1.0))
                dd.append(d)
        pr = np.array(pr)
        r = H.paired(-pr, np.zeros(len(pr)), np.array(dd))
        return {'x': X, 'n': len(pr), 'ret': round(100 * float(pr.mean()), 2), 't': round(-float(r['t']), 2), 'p': round(float(r['p']), 4)}
    grid = [open_rule((2017, 2018, 2019, 2020), X) for X in (0.2, 0.3, 0.4, 0.5)]
    best = max(grid, key=lambda r: r['t'])
    out['tests']['D1 totals at the open'] = {'tune': grid, 'held': open_rule((2021, 2022, 2023), best['x'])}
    # EDGE in the skater projection
    import nhl_players as PL
    w = json.load(open(PL.FIT))['w']
    edge = {}
    if os.path.exists(EDGE):
        for l in open(EDGE):
            r = json.loads(l)
            edge[(r['id'], r['S'])] = r
    er = []
    for s in range(2022, D.current_season() - 1):
        cur = {q['id']: q for q in json.load(open(os.path.join(G.WARD, f'{s}.json')))['players'] if q['grp'] != 'G'}
        nxt = {r['id']: r for r in PL.skaters(s + 1)}
        for pid, q in cur.items():
            n, e = nxt.get(pid), edge.get((pid, s))
            if not n or not e or q['toi'] < EDGE_MIN or n['toi'] < EDGE_MIN * 60 or q.get('ax') is None:
                continue
            if any(e.get(k) is None for k in ('spd', 'b20', 'shot', 'oz')):
                continue
            er.append([pid, s, int(q['grp'] == 'D'), q['hpm'], q['ax'], sum(w[c] * n[c] for c in ('evf', 'eva', 'a1', 'ixg')),
                       n['toi'] / 3600, e['spd'], e['b20'] / (q['toi'] / 60), e['shot'], e['oz']])
    if er:
        A = np.array([r[2:] for r in er], float)
        ids, Se = np.array([r[0] for r in er]), np.array([r[1] for r in er])
        Z = A[:, 5:].copy()
        for s in set(Se):
            for d_ in (0, 1):
                k = (Se == s) & (A[:, 0] == d_)
                Z[k] = (Z[k] - Z[k].mean(0)) / Z[k].std(0)
        B = np.column_stack([np.ones(len(A)), A[:, 1], A[:, 2], A[:, 2] ** 2, A[:, 0]])
        ye, we = A[:, 3], A[:, 4]

        def loso(X):
            pr = np.zeros(len(ye))
            for s in set(Se):
                tr, te = Se != s, Se == s
                sw = np.sqrt(we[tr])
                pr[te] = X[te] @ np.linalg.lstsq(X[tr] * sw[:, None], ye[tr] * sw, rcond=None)[0]
            return pr
        lb_, lc_ = we * (loso(B) - ye) ** 2, we * (loso(np.column_stack([B, Z])) - ye) ** 2
        out['tests']['C1 EDGE'] = {'held': cut(H.paired(lc_, lb_, ids)),
                                   'foldsBetter': f'{sum(int(lc_[Se == s].sum() < lb_[Se == s].sum()) for s in set(Se))}/{len(set(Se))}',
                                   'alone': {k: round(float(H.paired(we * (loso(np.column_stack([B, Z[:, j]])) - ye) ** 2, lb_, ids)['t']), 2)
                                             for j, k in enumerate(('spd', 'b20', 'shot', 'oz'))}}
    # Holm over the family, on each test's verdict split
    ps = sorted((v['held']['p'], k) for k, v in out['tests'].items())
    ok = True
    for i, (pv, k) in enumerate(ps):
        ok = ok and pv <= 0.05 / (len(ps) - i)
        out['tests'][k]['holm'] = bool(ok)
        t = out['tests'][k].get('tune')
        gate = t['t'] <= -1.5 if isinstance(t, dict) else True
        out['tests'][k]['ship'] = bool(ok and gate)
    json.dump(out, open(OUT, 'w'), indent=1)
    for k, v in out['tests'].items():
        print(k, json.dumps(v))
    print(json.dumps(out['measured']))


if __name__ == '__main__':
    if '--pull' in sys.argv:
        pull_sbr()
        pull_rr()
        pull_edge()
    else:
        main()
