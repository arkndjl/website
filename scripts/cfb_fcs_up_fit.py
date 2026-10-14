#!/usr/bin/env python3
"""Backtest and refit FBS% (the FCS move-up odds, FCS_UP in scripts/fetch_cfb.mjs) on NIL-era cycles.

    python3 scripts/cfb_fcs_up_fit.py            # pull (cached in scripts/.cache/fcsup/), build, fit
    python3 scripts/cfb_fcs_up_fit.py --offline  # refit from the cached pulls only

Universe: every player on an FCS roster in season S with a regular-season stat line (ESPN), S = 2023, 2024, 2025
(cycles 2023->24, 2024->25, 2025->26, all after July 2021). Outcome: on an FBS roster in S+1 and not on one in S
(ESPN's season rosters, the same labels as scripts/cfb_transfer_fit.py).

Features, all known at the end of season S: ESPN class (experience years), production (a position-group z of
ESPN's season line: scrimmage yards and touchdowns on offense, tackles, TFL, sacks, interceptions and breakups on
defense, per team game, against FCS players at the group with a stat line), games played share, the team's win%,
and the player's size against the group. The live model's production input is PFN's FCS score (zPfn), which
ranks FCS players the same way on the positions both cover; the coefficients are fit on this proxy.

Fit on 2023->24 and 2024->25, tested out of time on 2025->26 (log loss, AUC, calibration by decile and by class);
the live coefficients are refit on all three cycles. Writes data/cfb_fcs_up_fit.json.
"""
import concurrent.futures as cf
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'fcsup')
OUT = os.path.join(ROOT, 'data', 'cfb_fcs_up_fit.json')
OFFLINE = '--offline' in sys.argv
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
CYCLES = [(2023, 2024), (2024, 2025), (2025, 2026)]
os.makedirs(CACHE, exist_ok=True)
S = requests.Session(); S.headers['User-Agent'] = UA
ad = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64); S.mount('https://', ad)


def get(url):
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if os.path.exists(f):
        try:
            with open(f) as h: return json.load(h)
        except ValueError: pass
    if OFFLINE: return None
    v = None
    for i in range(5):
        try:
            r = S.get(url, timeout=30)
            if r.status_code in (400, 404): v = None; break
            r.raise_for_status(); v = r.json(); break
        except Exception:
            time.sleep(1 + 2 * i)
    tmp = f'{f}.{os.getpid()}.{id(v)}.tmp'
    with open(tmp, 'w') as h: json.dump(v, h)
    os.replace(tmp, f)
    return v


def pmap(fn, xs, n=32):
    with cf.ThreadPoolExecutor(n) as ex: return list(ex.map(fn, xs))


def rid(ref):
    m = re.search(r'/(\d+)(?:\?|$)', (ref or {}).get('$ref', ''))
    return m.group(1) if m else None


def teams(season, g):
    d = get(f'{CORE}/seasons/{season}/types/2/groups/{g}/teams?limit=400')
    return [rid(it) for it in (d or {}).get('items', [])]


def roster(season, tid):
    d = get(f'{CORE}/seasons/{season}/teams/{tid}/athletes?limit=400') or {}
    return [a for a in (rid(x) for x in d.get('items', [])) if a]


def record(season, tid):
    rec = get(f'{CORE}/seasons/{season}/types/2/teams/{tid}/record') or {}
    for it in rec.get('items', []):
        if it.get('type') == 'total':
            m = re.match(r'(\d+)-(\d+)', it.get('summary', ''))
            if m: w, l = int(m.group(1)), int(m.group(2)); return w / max(1, w + l)
    return None


def athlete(season, aid):
    a = get(f'{CORE}/seasons/{season}/athletes/{aid}') or {}
    return {'name': a.get('fullName'), 'pos': (a.get('position') or {}).get('abbreviation'),
            'exp': (a.get('experience') or {}).get('years'), 'wt': a.get('weight'), 'ht': a.get('height')}


def stats(season, aid):
    d = get(f'{CORE}/seasons/{season}/types/2/athletes/{aid}/statistics')
    out = {}
    for c in ((d or {}).get('splits') or {}).get('categories', []):
        for x in c.get('stats', []):
            if x.get('value'): out[c['name'] + '.' + x['name']] = x['value']
    return out


GROUP = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OT': 'OL', 'OG': 'OL', 'C': 'OL', 'OL': 'OL', 'G': 'OL', 'T': 'OL',
         'DE': 'EDGE', 'EDGE': 'EDGE', 'OLB': 'LB', 'DT': 'DL', 'DL': 'DL', 'NT': 'DL', 'LB': 'LB', 'ILB': 'LB', 'MLB': 'LB',
         'CB': 'CB', 'DB': 'S', 'S': 'S', 'SAF': 'S', 'FS': 'S', 'SS': 'S'}


def production(g, s):
    """one number per player: what the position's stat line rewards, per team game"""
    tg = max(s.get('general.teamGamesPlayed') or s.get('passing.teamGamesPlayed') or s.get('rushing.teamGamesPlayed') or 0,
             s.get('general.gamesPlayed') or 0, 1)
    if g == 'QB':
        v = (s.get('passing.passingYards', 0) + 20 * s.get('passing.passingTouchdowns', 0) - 45 * s.get('passing.interceptions', 0)
             + s.get('rushing.rushingYards', 0) + 20 * s.get('rushing.rushingTouchdowns', 0))
    elif g in ('RB', 'WR', 'TE'):
        v = s.get('rushing.rushingYards', 0) + s.get('receiving.receivingYards', 0) + 20 * (s.get('rushing.rushingTouchdowns', 0) + s.get('receiving.receivingTouchdowns', 0))
    elif g == 'OL':
        v = s.get('general.gamesPlayed', 0)       # no line stats: games played is all ESPN has
    else:
        v = (s.get('defensive.totalTackles', 0) + 2 * s.get('defensive.tacklesForLoss', 0) + 4 * s.get('defensive.sacks', 0)
             + 6 * s.get('defensiveInterceptions.interceptions', 0) + 2 * s.get('defensive.passesDefended', 0))
    return v / tg, (s.get('general.gamesPlayed') or 0) / tg


def collect():
    fcs = {s: teams(s, 81) for s, _ in CYCLES}
    fbs = {s: teams(s, 80) for s in sorted({x for c in CYCLES for x in c})}
    print('teams', {s: len(v) for s, v in fcs.items()}, {s: len(v) for s, v in fbs.items()})
    fbs_ids = {}
    for s, ts in fbs.items():
        ids = pmap(lambda t: roster(s, t), ts, 16); fbs_ids[s] = {a for x in ids for a in x}
        print('FBS rosters', s, len(fbs_ids[s]))
    rows = []
    for s, s1 in CYCLES:
        ts = fcs[s]
        ids = pmap(lambda t: roster(s, t), ts, 16)
        wp = dict(zip(ts, pmap(lambda t: record(s, t), ts, 16)))
        pairs = [(t, a) for t, x in zip(ts, ids) for a in x]
        t0 = time.time()
        st = pmap(lambda p: stats(s, p[1]), pairs, 48)
        keep = [(p, x) for p, x in zip(pairs, st) if x.get('general.gamesPlayed')]
        at = pmap(lambda p: athlete(s, p[0][1]), keep, 48)
        print('FCS', s, 'players', len(pairs), 'with a stat line', len(keep), f'{time.time() - t0:.0f}s')
        for ((t, a), x), info in zip(keep, at):
            rows.append({'season': s, 'tid': t, 'id': a, **info, 'wp': wp.get(t), 'stats': x,
                         'up': int(a in fbs_ids[s1] and a not in fbs_ids[s])})
    return rows


# the board's FCS population is PFN's qualified players, so each fit group keeps its top producers up to the
# board's count there (QB 170, RB 318, WR 571, TE 201, EDGE + DL 1337, LB 614, CB + S 752); ESPN lists most edge
# rushers as DL and most corners as S, so those are pooled. OL has no ESPN stat line: it takes the pooled
# production slope and no position offset (extrapolated)
FIT_GROUP = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE', 'EDGE': 'DL', 'DL': 'DL', 'LB': 'LB', 'CB': 'DB', 'S': 'DB'}
BOARD_N = {'QB': 170, 'RB': 318, 'WR': 571, 'TE': 201, 'DL': 1337, 'LB': 614, 'DB': 752}
GROUPS = ['QB', 'RB', 'WR', 'TE', 'DL', 'LB', 'DB']
CLS = ['Fr', 'So', 'Jr', 'Sr', '5th']   # year in school from the first season on any D1 roster (ESPN, 2018 on)


def build(rows, first):
    out = []
    for r in rows:
        g = FIT_GROUP.get(GROUP.get(r['pos'] or ''))
        if not g: continue
        v, gs = production(GROUP[r['pos']], r['stats'])
        yrs = r['season'] - int(first.get(r['id'], r['season'])) + 1
        out.append({**{k: r[k] for k in ('season', 'id', 'name', 'wp', 'up')}, 'g': g, 'v': math.log1p(max(0.0, v)), 'yrs': yrs, 'cls': CLS[min(5, max(1, yrs)) - 1]})
    keep = []
    by = defaultdict(list)
    for r in out: by[(r['season'], r['g'])].append(r)
    for (s, g), xs in by.items():
        xs = sorted(xs, key=lambda r: -r['v'])[:BOARD_N[g]]
        m, sd = np.mean([r['v'] for r in xs]), np.std([r['v'] for r in xs]) or 1
        for r in xs: r['z'] = (r['v'] - m) / sd
        keep += xs
    wp = defaultdict(list)
    for r in keep:
        if r['wp'] is not None: wp[r['season']].append(r['wp'])
    for r in keep:
        m, sd = np.mean(wp[r['season']]), np.std(wp[r['season']])
        r['tz'] = ((r['wp'] if r['wp'] is not None else m) - m) / sd
    return keep


# season intercepts (the move-up rate climbed: 7.2% of the board-like pool in 2023->24, 11.3% and 11.6% since);
# the live intercept is the latest cycle's, as Transfer% does
NAMES = ['const', 'prod', 'team'] + [f'cls_{c}' for c in CLS if c != 'Jr'] + [f'pos_{g}' for g in GROUPS if g != 'DL']
def X(r, seasons=()):
    return [1.0, r['z'], r['tz']] + [float(r['cls'] == c) for c in CLS if c != 'Jr'] + [float(r['g'] == g) for g in GROUPS if g != 'DL'] + [float(r['season'] == s) for s in seasons]


def logit(Xm, y, lam=1.0):
    b = np.zeros(Xm.shape[1])
    for _ in range(60):
        p = 1 / (1 + np.exp(-Xm @ b)); H = Xm.T @ (Xm * (p * (1 - p))[:, None]) + lam * np.eye(len(b)); H[0, 0] -= lam
        g = Xm.T @ (y - p) - lam * b; g[0] += lam * b[0]; b += np.linalg.solve(H, g)
    return b


def auc(p, y):
    o = np.argsort(p); rk = np.empty(len(p)); rk[o] = np.arange(1, len(p) + 1); n1 = y.sum(); n0 = len(y) - n1
    return float((rk[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def scores(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    e = [0, .05, .1, .2, .3, .5, 1.01]
    return {'n': len(y), 'rate': round(float(y.mean()), 4), 'mean': round(float(p.mean()), 4), 'auc': round(auc(p, y), 3),
            'logLoss': round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4), 'brier': round(float(np.mean((p - y) ** 2)), 4),
            'calib': [{'pred': f'{a:.2f}-{b:.2f}', 'n': int(((p >= a) & (p < b)).sum()), 'mean': round(float(p[(p >= a) & (p < b)].mean()), 3),
                       'actual': round(float(y[(p >= a) & (p < b)].mean()), 3)} for a, b in zip(e, e[1:]) if ((p >= a) & (p < b)).sum()]}


# the live formula before this fit (fetch_cfb.mjs FCS_UP, 2022-26 CFBD box scores), on the same proxies: conference and
# recruiting at their means (they shift no one's level), youth = 3 - class
OLD = {'c': -2.376, 'prod': 0.727, 'team': 0.158, 'young': 0.423, 'hs': 0.145}
def old(r): return 1 / (1 + math.exp(-(OLD['c'] + OLD['prod'] * r['z'] + OLD['team'] * r['tz'] + OLD['young'] * (3 - min(5, r['yrs'])) - OLD['hs'])))


def main():
    rows = json.load(open(os.path.join(CACHE, 'rows.json'))) if os.path.exists(os.path.join(CACHE, 'rows.json')) and OFFLINE else collect()
    json.dump(rows, open(os.path.join(CACHE, 'rows.json'), 'w'))
    first_f = os.path.join(CACHE, 'first.json')
    if os.path.exists(first_f) and OFFLINE: first = json.load(open(first_f))
    else:
        first = {}
        for s in range(2018, 2027):
            for x in pmap(lambda t: roster(s, t), teams(s, 80) + teams(s, 81), 24):
                for a in x: first.setdefault(a, s)
        json.dump(first, open(first_f, 'w'))
    R = build(rows, first)
    tr = [r for r in R if r['season'] < 2025]; te = [r for r in R if r['season'] == 2025]
    yt, ye = np.array([r['up'] for r in tr]), np.array([r['up'] for r in te])
    # train with a 2023 dummy, score 2025 at the latest (2024) intercept
    b = logit(np.array([X(r, (2023,)) for r in tr]), yt)
    pn = 1 / (1 + np.exp(-np.array([X(r, (2023,)) for r in te])[:, :-1] @ b[:-1])); po = np.array([old(r) for r in te])
    bflat = logit(np.array([X(r) for r in tr]), yt)
    pf = 1 / (1 + np.exp(-np.array([X(r) for r in te]) @ bflat))
    test = {'new': scores(pn, ye), 'pooledIntercept': scores(pf, ye), 'old': scores(po, ye), 'base': scores(np.full(len(ye), yt.mean()), ye),
            'byClass': {c: {'n': int(sum(r['cls'] == c for r in te)), 'actual': round(float(np.mean([r['up'] for r in te if r['cls'] == c])), 3),
                            'new': round(float(np.mean([p for p, r in zip(pn, te) if r['cls'] == c])), 3), 'old': round(float(np.mean([p for p, r in zip(po, te) if r['cls'] == c])), 3)} for c in CLS},
            'byYear': {y: round(float(np.mean([r['up'] for r in te if min(5, r['yrs']) == y])), 3) for y in range(1, 6)}}
    # the live refit: season intercepts (const = 2025->26) and the 5th-year term on the post-COVID cycle (a 5th-year
    # moved up 5-6% while the COVID year lasted, 2.7% in 2025->26), so the earlier cycles get their own 5th-year term
    # and production counts for little at a 5th-year then (the top third of 5th-years by production moved up 5%,
    # 4th-years 28%): a 5th-year production slope, again with its own pre-2025 term
    f5 = lambda r: float(r['cls'] == '5th')
    pre5 = lambda r: [f5(r) * (r['season'] < 2025), f5(r) * (r['season'] < 2025) * r['z']]
    bl = logit(np.array([X(r, (2023, 2024)) + [f5(r) * r['z']] + pre5(r) for r in R]), np.array([r['up'] for r in R]))
    prod5 = float(bl[len(NAMES) + 2]); bl = bl[:len(NAMES)]
    # the board's ESPN class stops at Sr, so a player it can't place by first season gets the 4th/5th-year blend:
    # the log odds of the pooled rate against the 4th-years'
    r4 = np.mean([r['up'] for r in R if r['cls'] == 'Sr' and r['season'] == 2025]); r5 = np.mean([r['up'] for r in R if r['cls'] == '5th' and r['season'] == 2025])
    n4 = sum(r['cls'] == 'Sr' for r in R if r['season'] == 2025); n5 = sum(r['cls'] == '5th' for r in R if r['season'] == 2025)
    rp = (r4 * n4 + r5 * n5) / (n4 + n5); lo = lambda q: math.log(q / (1 - q))
    srPooled = float(bl[NAMES.index('cls_Sr')] + lo(rp) - lo(r4))
    # first season on a D1 roster for everyone on this season's FCS rosters, for the board (fetch_cfb.mjs)
    cur = max(int(s) for s in first.values())
    now = {a for t in teams(cur, 81) for a in roster(cur, t)}
    fifth = sorted(a for a in now if a in first and cur - int(first[a]) + 1 >= 5)
    json.dump({'_readme': 'ESPN ids of this season\'s FCS players in their 5th+ season on a D1 roster (scripts/cfb_fcs_up_fit.py)', 'season': cur, 'fifth': fifth},
              open(os.path.join(ROOT, 'data', 'cfb_fcs_fifth.json'), 'w'), separators=(',', ':'))
    out = {'asof': time.strftime('%Y-%m-%d'), 'cycles': CYCLES, 'n': len(R), 'moved': int(sum(r['up'] for r in R)),
           'rates': {str(s): round(float(np.mean([r['up'] for r in R if r['season'] == s])), 4) for s, _ in CYCLES},
           'names': NAMES, 'coefTrain': [round(float(x), 3) for x in b], 'coef': [round(float(x), 3) for x in bl], 'srPooled': round(srPooled, 3), 'prod5th': round(prod5, 3), 'test2025': test, 'old': OLD}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: out[k] for k in ('n', 'moved', 'rates', 'names', 'coef', 'srPooled', 'prod5th')}))
    print('test 2025->26', json.dumps({k: {kk: v[kk] for kk in ('mean', 'auc', 'logLoss', 'brier')} for k, v in test.items() if k in ('new', 'pooledIntercept', 'old', 'base')}))
    print('by class', json.dumps(test['byClass']), 'by year in school', test['byYear'])


if __name__ == '__main__':
    main()
