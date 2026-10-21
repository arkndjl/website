#!/usr/bin/env python3
"""NBA head coaches by game, from Basketball-Reference's season coaching tables (research input for the game model).

    python3 scripts/nba_coaches.py 2009 2026     # pulls leagues/NBA_<S>_coaches.html, writes scripts/nba_coaches.json
    python3 scripts/nba_coaches.py --pbp         # timeouts and challenges, every sixth regular-season game 2016 on
                                                 # (ESPN play-by-play), writes scripts/nba_coach_pbp.json

Each team-season lists its coaches in the order they coached, with regular-season games, games with the franchise
and career games through that season, and playoff games. A team's regular-season games go to its coaches in that
order by their game counts; playoff and play-in games go to the coach with playoff games (the last one when none is listed).
"""
import html as H
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_espn as E

CACHE = os.path.join(HERE, '.cache', 'nba', 'coaches')
OUT = os.path.join(HERE, 'nba_coaches.json')
PBP = os.path.join(HERE, 'nba_coach_pbp.json')


def num(v):
    v = re.sub(r'<[^>]+>', '', v).strip()
    return int(v) if v.isdigit() else 0


def pull(lo, hi):
    os.makedirs(CACHE, exist_ok=True)
    out = {}
    for S in range(lo, hi + 1):
        fn = os.path.join(CACHE, f'{S}.html')
        if not os.path.exists(fn) or os.path.getsize(fn) < 50000:
            req = urllib.request.Request(f'https://www.basketball-reference.com/leagues/NBA_{S}_coaches.html', headers={'User-Agent': E.UA})
            open(fn, 'w').write(urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace'))
            time.sleep(4)
        s = open(fn).read()
        t = s[s.find('id="NBA_coaches"'):]
        t = t[:t.find('</table>')]
        rows = {}
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
            c = dict(re.findall(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', tr, re.S))
            cid = re.search(r'/coaches/(\w+)\.html', c.get('coach', ''))
            if not cid:
                continue
            tm = E.team(re.sub(r'<[^>]+>', '', c['team']).strip())
            rows.setdefault(tm, []).append({'id': cid.group(1), 'n': H.unescape(re.sub(r'<[^>]+>', '', c['coach'])),
                                            'g': num(c['cur_g']), 'w': num(c['cur_w']), 'frG': num(c['fr_g']),
                                            'carG': num(c['car_g']), 'pg': num(c.get('cur_g_p', ''))})
        out[str(S)] = rows
        print(S, len(rows), 'teams', sum(len(v) for v in rows.values()), 'coaches', flush=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))


def by_game(games):
    """game id -> (home coach, away coach) entries {id, games with franchise before tonight, career games before
    tonight, games since he took over this team this season, interim (took over mid-season)}"""
    C = json.load(open(OUT))
    seen, out = {}, {}
    for g in sorted(games, key=lambda g: g['tip']):
        pair = []
        for t in (g['h'], g['a']):
            cs = C.get(str(g['S']), {}).get(t)
            if not cs:
                pair.append(None); continue
            k = (g['S'], t)
            n = seen.setdefault(k, [0, 0])                    # regular-season games, playoff games so far
            if g['t'] != 2:                                    # playoffs and play-in
                i = max([j for j, c in enumerate(cs) if c['pg']] or [len(cs) - 1])
            else:
                i, cum = 0, 0
                while i < len(cs) - 1 and n[0] >= cum + cs[i]['g']:
                    cum += cs[i]['g']; i += 1
            c = cs[i]
            before = sum(x['g'] for x in cs[:i])
            gs_ = (n[0] - before) if g['t'] == 2 else c['g']
            pair.append({'id': c['id'], 'fr': c['frG'] - c['g'] + gs_, 'car': c['carG'] - c['g'] + gs_,
                         'since': gs_, 'mid': 1 if i > 0 else 0})
            if g['t'] != 2:
                n[1] += 1
            else:
                n[0] += 1
        out[g['id']] = pair
    return out


def pbp(every=6, lo=2016):
    """per sampled game and team: full timeouts before the 4th quarter and after, coach's challenges and overturns"""
    from concurrent.futures import ThreadPoolExecutor
    import nba_games as N
    games, _ = N.load_hist()
    try:
        out = json.load(open(PBP))
    except (OSError, ValueError):
        out = {}
    by = {}
    for g in sorted(games, key=lambda g: g['tip']):
        if g['t'] == 2 and g['S'] >= lo:
            by.setdefault(g['S'], []).append(g)
    todo = [g for L in by.values() for i, g in enumerate(L) if i % every == 0 and g['id'] not in out]

    def one(g):
        j = E.get(f'{E.SITE}/summary?event={g["id"]}')
        if not j:
            return g['id'], None
        tm = {t['team']['id']: E.team(t['team']['abbreviation']) for t in j.get('boxscore', {}).get('teams', [])}
        r = {'_n': len(j.get('plays', []))}
        for p in j.get('plays', []):
            ty = p.get('type', {}).get('text', '')
            t = tm.get((p.get('team') or {}).get('id'))
            if not t:
                continue
            a = r.setdefault(t, {'to13': 0, 'to4': 0, 'ch': 0, 'chOv': 0})
            if ty in ('Full Timeout', 'Timeout', '20 Sec. Timeout'):
                a['to13' if p.get('period', {}).get('number', 0) <= 3 else 'to4'] += 1
            elif ty.startswith("Coach's Challenge"):
                a['ch'] += 1; a['chOv'] += 'Overturned' in ty
        return g['id'], r
    with ThreadPoolExecutor(8) as ex:
        for gid, r in ex.map(one, todo):
            if r:
                out[gid] = r
    with open(PBP, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('pbp', len(out), 'games')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--pbp':
        pbp(); sys.exit()
    pull(int(a[0]) if a else 2009, int(a[1]) if len(a) > 1 else 2026)
