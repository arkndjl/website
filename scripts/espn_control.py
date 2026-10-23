#!/usr/bin/env python3
"""Game control from ESPN play-by-play (free): for every game, the score timeline (each scoring play's elapsed
seconds and score) and ESPN's own in-game win probability where ESPN has it, slimmed and cached by season.
  python3 scripts/espn_control.py cfb|cbb|nba [first season] [last season]
Game ids come from the model histories: CFB scripts/data/cfb_hist_md.json.gz (plus this season's ESPN scoreboards
through scripts/cfb_espn_hist.py), CBB scripts/data/cbb_games_hist.json.gz, NBA scripts/nba_games_hist.json.gz.
Cache: scripts/.cache/control/<sport>/<season>.json, {id: {"len": regulation seconds, "sc": [[sec, hs, as], ...],
"wp": [[sec, home win prob], ...] or null}}. A game already in the cache is never pulled again.
control(rec, sd) is the time-weighted mean home win probability over regulation from score and clock alone
(no pregame prior): P(home wins) = Phi(lead / (sd * sqrt(share of the game left))).
"""
import gzip
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache', 'control')
SITE = 'https://site.api.espn.com/apis/site/v2/sports/'
SPORT = {
    # path, regulation periods x minutes, overtime minutes (football overtime is untimed: none)
    'cfb': ('football/college-football', 4, 15, 0),
    'cbb': ('basketball/mens-college-basketball', 2, 20, 5),
    'nba': ('basketball/nba', 4, 12, 5),
}
UA = {'user-agent': 'Mozilla/5.0 (arkndjl.net arkboard)'}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def clock(s):
    try:
        if ':' in s:
            m, x = s.split(':')
            return 60 * int(m) + float(x)
        return float(s)
    except Exception:
        return None


def slim(d, sport):
    _, nper, mins, ot = SPORT[sport]
    plen, reg = 60 * mins, 60 * mins * nper

    def sec(p):
        q = (p.get('period') or {}).get('number')
        c = clock((p.get('clock') or {}).get('displayValue') or '')
        if not q or c is None:
            return None
        if q <= nper:
            return (q - 1) * plen + plen - c
        return reg + (q - nper - 1) * 60 * ot + 60 * ot - c if ot else reg

    if sport == 'cfb':
        plays = [p for dr in (d.get('drives') or {}).get('previous') or [] for p in dr.get('plays') or []]
        scoring = d.get('scoringPlays') or [p for p in plays if p.get('scoringPlay')]
    else:
        plays = d.get('plays') or []
        scoring = [p for p in plays if p.get('scoringPlay')]
    sc, last = [], (0, 0)
    for p in scoring:
        t, h, a = sec(p), p.get('homeScore'), p.get('awayScore')
        if t is None or h is None or a is None or (h, a) == last:
            continue
        sc.append([round(t), int(h), int(a)])
        last = (int(h), int(a))
    at = {p.get('id'): sec(p) for p in plays}
    wp = [[round(at[w['playId']]), round(w['homeWinPercentage'], 4)] for w in d.get('winprobability') or []
          if at.get(w.get('playId')) is not None and w.get('homeWinPercentage') is not None]
    comp = ((d.get('header') or {}).get('competitions') or [{}])[0]
    fin = {x.get('homeAway'): x.get('score') for x in comp.get('competitors') or []}
    return {'len': reg, 'sc': sc, 'wp': wp or None, 'n': len(plays), 'fin': [fin.get('home'), fin.get('away')]}


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def control(rec, sd, step=15):
    """time-weighted mean home win probability over regulation, from score and clock alone"""
    L, sc = rec['len'], rec['sc']
    if not L or not sc and not rec.get('fin'):
        return None
    tot, i, lead = 0.0, 0, 0
    for t in range(0, L, step):
        while i < len(sc) and sc[i][0] <= t:
            lead = sc[i][1] - sc[i][2]
            i += 1
        left = 1 - (t + step / 2) / L
        tot += phi(lead / (sd * math.sqrt(left))) if lead else 0.5
    return tot / len(range(0, L, step))


def control_espn(rec):
    """time-weighted mean of ESPN's own win probability (carries ESPN's pregame prior)"""
    wp, L = rec.get('wp'), rec['len']
    if not wp:
        return None
    wp = sorted(x for x in wp if 0 <= x[0] <= L)
    if len(wp) < 10:
        return None
    tot = 0.0
    for (t0, p), (t1, _) in zip(wp, wp[1:] + [[L, None]]):
        tot += p * max(0, t1 - t0)
    return tot / max(1, L - wp[0][0])


def ids(sport, a, b):
    out = {}
    if sport == 'nba':
        with gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz'), 'rt') as f:
            for g in json.load(f)['games']:
                out.setdefault(g['S'], []).append(g['id'])
    elif sport == 'cbb':
        with gzip.open(os.path.join(HERE, 'data', 'cbb_games_hist.json.gz'), 'rt') as f:
            for g in json.load(f):
                if g.get('hs') is not None:
                    out.setdefault(g['season'], []).append(g['id'])
    else:
        with gzip.open(os.path.join(HERE, 'data', 'cfb_hist_md.json.gz'), 'rt') as f:
            for S, gs in json.load(f)['games'].items():
                out[int(S)] = [str(g['id']) for g in gs if g.get('completed') and 'fbs' in (g.get('homeClassification'), g.get('awayClassification'))]
        sys.path.insert(0, HERE)
        import cfb_espn_hist as H
        for S in range(a, b + 1):
            if S not in out:
                for x in ('sum', 'odds'):
                    os.makedirs(os.path.join(H.DIR, x), exist_ok=True)
                H.season(S)
                p = os.path.join(H.DIR, f'games{S}.json')
                if os.path.exists(p):
                    with open(p) as f:
                        out[S] = [str(g['id']) for g in json.load(f) if g['done'] and g.get('grp') == 'fbs']
    return {S: v for S, v in out.items() if a <= S <= b}


def load(sport, S):
    p = os.path.join(CACHE, sport, f'{S}.json')
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def season(sport, S, todo):
    os.makedirs(os.path.join(CACHE, sport), exist_ok=True)
    have = load(sport, S)
    need = [i for i in todo if str(i) not in have]

    def one(i):
        d = get(f'{SITE}{SPORT[sport][0]}/summary?event={i}')
        return i, slim(d, sport) if d else None

    with ThreadPoolExecutor(24) as ex:
        for k, (i, r) in enumerate(ex.map(one, need)):
            if r is not None:
                have[str(i)] = r
            if k % 2000 == 1999:
                with open(os.path.join(CACHE, sport, f'{S}.json'), 'w') as f:
                    json.dump(have, f, separators=(',', ':'))
    with open(os.path.join(CACHE, sport, f'{S}.json'), 'w') as f:
        json.dump(have, f, separators=(',', ':'))
    print(sport, S, len(todo), 'games,', len(have), 'cached,', sum(1 for r in have.values() if r.get('wp')), 'with ESPN win prob', flush=True)


if __name__ == '__main__':
    sport = sys.argv[1]
    a, b = (int(x) for x in sys.argv[2:4]) if len(sys.argv) > 3 else (2013, 2027)
    for S, todo in sorted(ids(sport, a, b).items()):
        season(sport, S, todo)
