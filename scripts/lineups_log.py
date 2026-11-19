#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""As-of archive of projected NHL lineups (two sources), for later tests that need the pregame lineup as it was posted.

    python3 scripts/lineups_log.py            # append what changed since the last run
    python3 scripts/lineups_log.py --test     # parse self-check on the live pages, writes nothing

Appends to scripts/data/lineups_proj/nhl-YYYY-MM.jsonl, one row per (source, key) whenever its content changes:
    {"t": UTC stamp, "src": "rw" | "dfg" | "dfl", "day": Eastern date, "key": "AWY@HOM" or team, "d": {...}}
  rw   RotoWire lineups page: per game the starting goalies (Confirmed / Expected), PP1 and PP2 units and the listed
       injuries (one request a run)
  dfg  Daily Faceoff starting goalies for the day with the news strength (one request a run)
  dfl  Daily Faceoff line combinations of each team playing today (forward lines, pairs, PP and PK units, goalies, who
       posted them and when); refetched at most every DFL_HOURS hours a team
Logging only: nothing here feeds a model. Stdlib only.
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'scripts', 'data', 'lineups_proj')
UA = {'User-Agent': 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'}
RW = 'https://www.rotowire.com/hockey/nhl-lineups.php'
DFG = 'https://www.dailyfaceoff.com/starting-goalies/{}'
DFL = 'https://www.dailyfaceoff.com/teams/{}/line-combinations'
DFL_HOURS = 4
# both sources' short codes -> the site's
CODE = {'TB': 'TBL', 'T.B': 'TBL', 'NJ': 'NJD', 'N.J': 'NJD', 'SJ': 'SJS', 'S.J': 'SJS', 'LA': 'LAK', 'L.A': 'LAK', 'UTAH': 'UTA',
        'ARI': 'UTA', 'VEG': 'VGK', 'LV': 'VGK', 'MON': 'MTL', 'WAS': 'WSH', 'CLB': 'CBJ', 'CAL': 'CGY', 'NAS': 'NSH', 'WIN': 'WPG'}


def code(a):
    a = (a or '').strip().upper()
    return CODE.get(a, a)


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode('utf-8', 'replace')


def et_day(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(hours=10)).date().isoformat()     # the slate's date until 6 a.m. Eastern


def txt(s):
    return html.unescape(re.sub(r'<[^>]+>', ' ', s)).strip()


def rw_parse(h):
    """{'AWY@HOM': {'time', 'a': side, 'h': side}}; side = {'g': [name, status], 'pp1': [[pos, name]], 'pp2': [...], 'inj': [[pos, name, tag]]}"""
    out = {}
    for box in re.split(r'<div class="lineup is-nhl(?: [^"]*)?">', h)[1:]:
        ab = re.findall(r'class="lineup__abbr">([^<]+)<', box)
        if len(ab) < 2:
            continue
        g = {'time': (re.findall(r'class="lineup__time">([^<]*)<', box) or [''])[0].strip()}
        for side, cls in (('a', 'is-visit'), ('h', 'is-home')):
            m = re.search(r'<ul class="lineup__list %s">(.*?)</ul>' % cls, box, re.S)
            s = {'g': None, 'pp1': [], 'pp2': [], 'inj': []}
            sec = None
            for li in re.findall(r'<li class="([^"]*)"[^>]*>(.*?)</li>', m.group(1) if m else '', re.S):
                c, body = li
                if 'player-highlight' in c:
                    nm = re.search(r'<a[^>]*>([^<]+)</a>', body)
                    st = 'Confirmed' if 'is-confirmed' in body else 'Expected' if 'is-expected' in body else txt(re.sub(r'<a[^>]*>.*?</a>', '', body, flags=re.S))
                    s['g'] = [nm.group(1).strip() if nm else None, st]
                elif 'lineup__title' in c:
                    t = txt(body).upper()
                    sec = 'pp1' if '#1' in t else 'pp2' if '#2' in t else 'inj' if 'INJ' in t else None
                elif 'lineup__player' in c and sec:
                    pos = txt((re.findall(r'class="lineup__pos">(.*?)</div>', body, re.S) or [''])[0])
                    a = re.search(r'<a[^>]*title="([^"]*)"', body) or re.search(r'<a[^>]*>([^<]+)</a>', body)
                    row = [pos, html.unescape(a.group(1)).strip() if a else None]
                    if sec == 'inj':
                        row.append(txt((re.findall(r'class="lineup__inj">(.*?)</span>', body, re.S) or [''])[0]))
                    s[sec].append(row)
            g[side] = s
        out[f'{code(ab[0])}@{code(ab[1])}'] = g
    return out


def next_data(h):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    return json.loads(m.group(1))['props']['pageProps']


def dfg_parse(h):
    out = {}
    for r in next_data(h).get('data') or []:
        out[f"{code(r.get('awayTeamAbbreviation'))}@{code(r.get('homeTeamAbbreviation'))}"] = {
            'a': [r.get('awayGoalieName'), r.get('awayNewsStrengthName')], 'h': [r.get('homeGoalieName'), r.get('homeNewsStrengthName')],
            'slug': [r.get('awayTeamSlug'), r.get('homeTeamSlug')]}
    return out


def dfl_parse(h):
    pp = next_data(h)
    c = pp.get('combinations') or {}
    units = {}
    for p in c.get('players') or []:
        if p.get('categoryIdentifier') == 'oi':
            units.setdefault('out', []).append([p.get('name'), p.get('injuryStatus')])
        else:
            units.setdefault(p.get('groupIdentifier'), []).append([p.get('positionIdentifier'), p.get('name')] + (['gtd'] if p.get('gameTimeDecision') else []))
    return code(c.get('teamAbbreviation')), {'by': c.get('sourceName'), 'at': c.get('updatedAt'), 'u': units}, {
        code(t.get('shortName')): t.get('slug') for t in pp.get('sortedTeams') or []}


def digest(d):
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]


def last_seen(day):
    """(src, key) -> (content hash, stamp) of the newest row logged for this slate"""
    seen = {}
    for fn in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
        if not fn.startswith('nhl-') or fn[4:11] < day[:7][:4] + '-' + '%02d' % max(1, int(day[5:7]) - 1):
            continue
        for ln in open(os.path.join(DIR, fn)):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get('day') == day:
                seen[(r['src'], r['key'])] = (r.get('x'), r['t'])
    return seen


def main(test=False):
    now = dt.datetime.now(dt.timezone.utc)
    day, stamp = et_day(now), now.strftime('%Y-%m-%dT%H:%M:%SZ')
    seen = {} if test else last_seen(day)
    rows = []

    def put(src, key, d):
        x = digest(d)
        if seen.get((src, key), (None,))[0] != x:
            rows.append({'t': stamp, 'src': src, 'day': day, 'key': key, 'x': x, 'd': d})
    rw, dfg = {}, {}
    try:
        rw = rw_parse(get(RW))
        for k, d in rw.items():
            put('rw', k, d)
    except Exception as e:  # noqa: BLE001
        print('lineups log: rotowire', repr(e), file=sys.stderr)
    time.sleep(1.2)
    try:
        dfg = dfg_parse(get(DFG.format(day)))
        for k, d in dfg.items():
            put('dfg', k, {'a': d['a'], 'h': d['h']})
    except Exception as e:  # noqa: BLE001
        print('lineups log: daily faceoff goalies', repr(e), file=sys.stderr)
    slugs = {}
    for k, d in dfg.items():
        for t, s in zip(k.split('@'), d['slug']):
            if s:
                slugs[t] = s
    n_l = 0
    for t, s in sorted(slugs.items())[:2 if test else None]:
        prev = seen.get(('dfl', t))
        chk = seen.get(('dfl_chk', t), prev)
        if chk and (now - dt.datetime.strptime(chk[1], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)).total_seconds() < DFL_HOURS * 3600:
            continue
        time.sleep(1.2)
        try:
            tm, d, _ = dfl_parse(get(DFL.format(s)))
            put('dfl', t, d); n_l += 1
        except Exception as e:  # noqa: BLE001
            print('lineups log: daily faceoff lines', t, repr(e), file=sys.stderr)
    games = sorted(set(rw) | set(dfg))
    both = [g for g in games if g in rw and g in dfg]
    agree = sum(1 for g in both for s in ('a', 'h') if rw[g][s]['g'] and dfg[g][s][0] and
                rw[g][s]['g'][0].split()[-1].lower() == dfg[g][s][0].split()[-1].lower())
    print(f'lineups log {day}: rotowire {len(rw)} games, daily faceoff {len(dfg)} games, {n_l} line pages; '
          f'starters agree {agree}/{2 * len(both)}; {len(rows)} new rows')
    if test:
        teams = 2 * len(games)
        ok_rw = sum(1 for g in rw.values() for s in ('a', 'h') if g[s]['g'] and g[s]['g'][0] and len(g[s]['pp1']) >= 4)
        ok_df = sum(1 for g in dfg.values() for s in ('a', 'h') if g[s][0])
        ok_l = sum(1 for r in rows if r['src'] == 'dfl' and len(r['d']['u'].get('f1', [])) == 3 and len(r['d']['u'].get('pp1', [])) >= 4)
        print(f'test: rotowire sides parsed {ok_rw}/{2 * len(rw)}, daily faceoff sides {ok_df}/{2 * len(dfg)}, line pages parsed {ok_l}/{n_l}')
        assert not games or (ok_rw >= 0.9 * 2 * len(rw) and ok_df >= 0.9 * 2 * len(dfg) and ok_l == n_l), 'parse coverage under 90%'
        return
    if rows:
        os.makedirs(DIR, exist_ok=True)
        with open(os.path.join(DIR, f'nhl-{day[:7]}.jsonl'), 'a') as f:
            for r in rows:
                f.write(json.dumps(r, separators=(',', ':'), ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main(test='--test' in sys.argv)
