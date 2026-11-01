#!/usr/bin/env python3
"""Player badges for the hockey prospects ARKBOARD's pipeline (the College Football board's medals, scripts/cfb_badges.mjs).

A badge is one trait from a CHL season line (HockeyTech's public OHL/WHL/QMJHL feeds), regressed toward the pool mean
by games, v' = m + (v - m) * n / (n + k), k = n (1 - r) / r from the stat's year-to-year r (CHL skaters, 20+ games in
back-to-back seasons). The pool: CHL skaters of his birth cohort (first-time draft-eligibles of the same draft year) at
his position (F / D) in that league and season, 20+ games. Tiers by percentile in the pool: Bronze 75th, Silver 90th,
Gold 97th, Platinum 99th.
CANDS lists every candidate scripts/hockey_badge_backtest.py measures (on the draft model and the stage 1-2 models, the
outcome the board's FV is fitted to). SHIP holds the ones that passed, by stage (seasons since the draft): only those
reach the board, as display. They are not added to the FV.
"""
import bisect
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as NM

CHLD = os.path.join(HERE, '.cache', 'hockey', 'chl')
HT = 'https://lscluster.hockeytech.com/feed/?feed=modulekit&fmt=json&lang=en&key=%s&client_code=%s'
HTKEY = {'ohl': 'f1aa699db3d81487', 'whl': '41b145a848f4bd67', 'lhjmq': 'f322673b6bcae299'}   # the leagues' public site keys
HTLG = {'ohl': 'OHL', 'whl': 'WHL', 'lhjmq': 'QMJHL'}
CODE = {v: k for k, v in HTLG.items()}
MIN_GP = 20
TIERS = [('p', .99), ('g', .97), ('s', .90), ('b', .75)]


def _n(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _pg(k):
    return lambda p: p[k] / p['gp']


# [key, name, value (higher is better), what the stat is]; volume = games
CANDS = [
    ['scorer', 'Scorer', _pg('g'), 'goals a game'],
    ['playmaker', 'Playmaker', _pg('a'), 'assists a game'],
    ['ashare', 'Distributor', lambda p: p['a'] / p['pts'] if p['pts'] >= 5 else None, 'assists share of points'],
    ['es', 'Even Strength', lambda p: (p['pts'] - p['ppp'] - p['shp']) / p['gp'], 'even-strength points a game'],
    ['pp', 'Power Play', _pg('ppp'), 'power-play points a game'],
    ['ppshare', 'PP Reliant', lambda p: p['ppp'] / p['pts'] if p['pts'] >= 5 else None, 'power-play share of points'],
    ['shooter', 'Shooter', lambda p: p['sog'] / p['gp'] if p['sog'] > 0 else None, 'shots a game'],
    ['sniper', 'Sniper', lambda p: p['g'] / p['sog'] if p['sog'] >= 30 else None, 'shooting %'],
    ['twoway', 'Two-Way', _pg('pm'), '+/- a game'],
    ['pk', 'Penalty Kill', _pg('shp'), 'short-handed points a game'],
    ['physical', 'Physical', _pg('pim'), 'penalty minutes a game'],
]
BY = {c[0]: c for c in CANDS}
# shipped (stage -> key -> k). Nov 1 2026, data/hockey_badge_backtest.json: stage 1 (the first season after the draft,
# still in the CHL) Shooter, shots a game: year-to-year r .84 at 56 games (k 10.7); on the stage 1 model's drivers
# t 2.57, leave-one-class-out MSE -1.32 (9 of 12 classes), forward (fit 2008-15, grade 2016-19) -1.28; 457 picks (the
# feeds carry shots from about 2013). It did not hold at the draft (t .78) or stage 2 (t .68): the weakest of the
# shipped badges across boards. Every other candidate failed at every stage (draft model: none over t 1.6; negative:
# Sniper t -3.8, Physical t -3.0).
SHIP = {1: {'shooter': 10.7}}


def parse(d):
    """a HockeyTech topscorers table -> skater lines with position group, birth date, games and counting stats"""
    out = []
    for p in d or []:
        pos = (p.get('position') or '').upper()
        if pos in ('G', ''):
            continue
        try:
            bd = dt.datetime.strptime(p.get('birthdate') or '', '%b %d, %Y').date().isoformat()
        except ValueError:
            bd = None
        nm = p['name']
        if ', ' in nm:                                  # QMJHL's feed writes 'Last, First'
            a, _, b = nm.partition(', '); nm = f'{b} {a}'
        gp = _n(p.get('games_played'))
        if gp <= 0:
            continue
        out.append({'id': str(p.get('player_id')), 'name': nm, 'birth': bd, 'grp': 'D' if pos.startswith('D') else 'F', 'gp': gp,
                    'g': _n(p.get('goals')), 'a': _n(p.get('assists')), 'pts': _n(p.get('points')),
                    'ppp': _n(p.get('power_play_goals')) + _n(p.get('power_play_assists')),
                    'shp': _n(p.get('short_handed_goals')) + _n(p.get('short_handed_assists')),
                    'pm': _n(p.get('plus_minus')), 'pim': _n(p.get('penalty_minutes')), 'sog': _n(p.get('shots'))})
    return out


def eligible(birth, yr):
    """first-time draft-eligible in the season ending yr: born Sep 16 (yr - 19) to Sep 15 (yr - 18)"""
    if not birth:
        return False
    return dt.date(yr - 19, 9, 16).isoformat() <= birth <= dt.date(yr - 18, 9, 15).isoformat()


def pool_z(ps, val, k):
    """{line id: (z, percentile)} for one pool"""
    xs = [(p['id'], val(p), p['gp']) for p in ps]
    xs = [x for x in xs if x[1] is not None]
    if len(xs) < 20:
        return {}
    m = sum(v * n for _, v, n in xs) / sum(n for _, _, n in xs)
    reg = [(i, m + (v - m) * n / (n + k)) for i, v, n in xs]
    mu = sum(v for _, v in reg) / len(reg)
    sd = (sum((v - mu) ** 2 for _, v in reg) / len(reg)) ** .5 or 1
    srt = sorted(v for _, v in reg)
    return {i: ((v - mu) / sd, bisect.bisect_left(srt, v) / len(srt)) for i, v in reg}


def season_lines(lg, yr, fetch=True):
    """the league's regular season ending yr (cache scripts/.cache/hockey/chl, pulled when missing)"""
    c = CODE.get(lg)
    if not c:
        return []
    fn = os.path.join(CHLD, f'{c}_{yr}.json')
    if not os.path.exists(fn) and fetch:
        import urllib.request
        UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
        get = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=60).read())
        try:
            for s in get(HT % (HTKEY[c], c) + '&view=seasons')['SiteKit']['Seasons']:
                m = re.match(r'(\d{4}) ?- ?(\d{2,4}) \|? ?Regular Season$', s['season_name'].strip())
                if m and int(m.group(1)) + 1 == yr:
                    d = get(HT % (HTKEY[c], c) + f'&view=statviewtype&type=topscorers&season_id={s["season_id"]}&first=0&limit=3000&stat=all&order_direction=')
                    os.makedirs(CHLD, exist_ok=True)
                    json.dump(d['SiteKit'].get('Statviewtype'), open(fn, 'w'))
                    break
        except Exception as e:
            print('CHL season', lg, yr, 'not pulled:', e)
    return parse(json.load(open(fn))) if os.path.exists(fn) else []


def assign(items):
    """items: [(board row, pick row)] with board row k (seasons since the draft) and league; sets row['bdg'] =
    [[name, tier letter, percentile, stat], ...] best first for the SHIP badges of his stage, bronze or better"""
    rank = {'p': 4, 'g': 3, 's': 2, 'b': 1}
    tabs = {}
    n = 0
    for row, r in items:
        k, lg = row.get('k'), row.get('league')
        if k not in SHIP or lg not in CODE or not r.get('birth'):
            continue
        yr = r['year'] + k
        if (lg, yr) not in tabs:
            tabs[(lg, yr)] = season_lines(lg, yr)
        ps = tabs[(lg, yr)]
        me = [p for p in ps if p['birth'] == r['birth'] and NM.same(p['name'], r['name'])]
        if len(me) != 1 or me[0]['gp'] < MIN_GP:
            continue
        me = me[0]
        pool = [p for p in ps if p['grp'] == me['grp'] and p['gp'] >= MIN_GP and eligible(p['birth'], r['year'])]
        got = []
        for key, kk in SHIP[k].items():
            _, name, val, stat = BY[key]
            z = pool_z(pool, val, kk).get(me['id'])
            t = z and next((t for t, cut in TIERS if z[1] >= cut), None)
            if t:
                got.append([name, t, min(99, int(100 * z[1])), stat])
        if got:
            row['bdg'] = sorted(got, key=lambda x: (-rank[x[1]], -x[2])); n += 1
    return n
