#!/usr/bin/env python3
"""In-game injury news as next-game availability: the backtest preregistered in PREREG.md (Nov 17 2026).

    python3 scripts/research/ingame_nov17/ingame.py          # both sports -> results.json + the table
"""
import csv
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import names as NM  # noqa: E402
import nfl_games as G  # noqa: E402
import rotowire as RW  # noqa: E402

ET = ZoneInfo('America/New_York')
IG = re.compile(r"won't return|will not return|not return to|won't finish|ruled out for (the )?(rest|remainder)|done for the "
                r"(day|night|game|evening)|\b(exits|leaves|exited|departs)\b|questionable to return|doubtful to return|"
                r"carted off|out for the (rest|remainder) of|won't come back|not be returning|unlikely to return", re.I)
CUR = {'nfl': {'Out': 0.0, 'Doubtful': 0.02, 'Questionable': 0.75},
       'nba': {'Out': 0.001, 'Doubtful': 0.015, 'Questionable': 0.535}}
C1 = {'Out': 0.38, 'Doubtful': 0.55, 'Questionable': 0.84}
GROUP = {'Out': 'out', 'Doubtful': 'out', 'Out (season)': None, 'Questionable': 'q'}
CLIP = (0.02, 0.98)


def items(sp, season):
    """RotoWire items for a season: backfill file, or the live history for the 2026 season"""
    p = os.path.join(HERE, f'rw_{sp}_{season}.json.gz')
    if os.path.exists(p):
        return list(json.load(gzip.open(p))['items'].values())
    h = json.load(gzip.open(os.path.join(SCRIPTS, 'data', 'rotowire_history', f'{sp}.json.gz')))['items']
    return list(h.values())


def nfl_status(it):
    return G.status_of(it['head']) or G.status_of(re.split(r'(?<=[.!?])\s', it.get('body') or '', maxsplit=1)[0])


def nba_status(it):
    return RW.item_status(dict(it, ts=it.get('tw') or 0))


# ---------------------------------------------------------------- NFL
def nfl_rows(season):
    games = [g for g in csv.DictReader(open(os.path.join(SCRIPTS, '.cache', 'nfl', 'games.csv')))
             if int(g['season']) == season and g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    sched = defaultdict(list)          # team -> [(date, week, kick hour ET)]
    for g in games:
        for t in (g['home_team'], g['away_team']):
            sched[G.team(t)].append((g['gameday'], int(g['week']), int((g['gametime'] or '13:00')[:2])))
    for t in sched:
        sched[t].sort()
    played = defaultdict(set)          # (team, week) -> name keys with a snap
    for r in csv.DictReader(open(os.path.join(SCRIPTS, '.cache', 'nfl', f'snap_counts_{season}.csv'))):
        if r['game_type'] != 'REG':
            continue
        if any(float(r[k] or 0) > 0 for k in ('offense_snaps', 'defense_snaps', 'st_snaps')):
            played[(G.team(r['team']), int(r['week']))].add(NM.key(r['player']))
    its = items('football', season)
    by_p = defaultdict(list)
    for it in its:
        st = nfl_status(it)
        if st:
            by_p[(it['abbr'], NM.key(it['player']))].append((it['d'], st, it))
    rows = {}
    for it in its:
        if not IG.search(it['head']):
            continue
        st = nfl_status(it)
        g = GROUP.get(st)
        if not g:
            continue
        t = G.team(G.RW_TEAM.get(it['abbr'], it['abbr']))
        S = sched.get(t, [])
        d = it['d']
        k = next((i for i, (gd, wk, hr) in enumerate(S) if gd == d or (hr >= 19 and (dt.date.fromisoformat(gd) + dt.timedelta(days=1)).isoformat() == d)), None)
        if k is None or k + 1 >= len(S):
            continue
        gd, wk, _ = S[k]
        nd, nwk, _ = S[k + 1]
        if nwk == wk:
            continue
        key = (t, NM.key(it['player']), wk)
        # still newest: no other status item for him after the game day and before the next game's day minus 2
        cut = (dt.date.fromisoformat(nd) - dt.timedelta(days=2)).isoformat()
        later = [x for x in by_p[(it['abbr'], NM.key(it['player']))] if d < x[0] < cut]
        if key in rows and rows[key]['d'] >= d:
            continue
        team_played = played.get((t, nwk))
        if not team_played:
            continue
        rows[key] = {'season': season, 'player': it['player'], 'team': t, 'wk': wk, 'd': d, 'st': st, 'g': g,
                     'head': it['head'], 'newest': not later, 'y': int(NM.key(it['player']) in team_played)}
    return list(rows.values())


# ---------------------------------------------------------------- NBA
def nba_games(S):
    import nba_games as N
    if S <= 2026:
        d = json.load(gzip.open(N.HIST))
        return [g for g in d['games'] if g['S'] == S], d['names']
    gs = N.season_games(S)
    names = {}
    for g in gs:
        names.update(g.pop('nm', {}))
    return [g for g in gs if g['fin']], names


def nba_rows(season):
    S = season + 1                      # ESPN's season label: 2025-26 is 2026
    import nba_espn as E
    games, names = nba_games(S)
    sched = defaultdict(list)           # team -> [(ET date, tip hour, game)]
    for g in games:
        if g.get('t') != 2 or not g.get('pl'):
            continue
        tip = dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00')).astimezone(ET)
        for t in (g['h'], g['a']):
            sched[t].append((tip.date().isoformat(), tip.hour, g))
    for t in sched:
        sched[t].sort(key=lambda x: x[2]['tip'])
    its = items('basketball', season)
    by_p = defaultdict(list)
    for it in its:
        st = nba_status(it)
        if st:
            by_p[(it['abbr'], NM.key(it['player']))].append(it['d'])
    rows = {}
    for it in its:
        if not IG.search(it['head']):
            continue
        st = nba_status(it)
        g_ = GROUP.get(st)
        if not g_:
            continue
        t = E.team(it['abbr'])
        Sx = sched.get(t, [])
        d = it['d']
        k = next((i for i, (gd, hr, _) in enumerate(Sx) if gd == d or (hr >= 19 and (dt.date.fromisoformat(gd) + dt.timedelta(days=1)).isoformat() == d)), None)
        if k is None or k + 1 >= len(Sx):
            continue
        gd, _, g0 = Sx[k]
        nd, _, g1 = Sx[k + 1]
        rost = {NM.key(names.get(p, '')): p for p, _ in (g0['pl'].get(t) or [])}
        rost.update({NM.key(names.get(p, '')): p for p, _ in (g1['pl'].get(t) or [])})
        pid = rost.get(NM.key(it['player']))
        if not pid:
            continue
        mins = {p: m for p, m in (g1['pl'].get(t) or [])}
        later = [x for x in by_p[(it['abbr'], NM.key(it['player']))] if d < x < nd]
        key = (t, pid, g0['id'])
        if key in rows and rows[key]['d'] >= d:
            continue
        rows[key] = {'season': season, 'player': it['player'], 'team': t, 'd': d, 'next': nd, 'st': st, 'g': g_,
                     'head': it['head'], 'newest': not later, 'b2b': nd <= (dt.date.fromisoformat(gd) + dt.timedelta(days=1)).isoformat(),
                     'y': int((mins.get(pid) or 0) > 0)}
    return list(rows.values())


# ---------------------------------------------------------------- scoring
def ll(p, y):
    p = min(max(p, CLIP[0]), CLIP[1])
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def paired(a, b):
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    if n < 2:
        return None, None
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    return m, (m / (sd / math.sqrt(n)) if sd > 0 else None)


def evaluate(sport, rows):
    out = {'n': len(rows), 'rates': {}, 'tests': {}}
    for sea in sorted({r['season'] for r in rows}):
        for g in ('out', 'q'):
            for pop in ('newest', 'all'):
                rr = [r for r in rows if r['season'] == sea and r['g'] == g and (pop == 'all' or r['newest'])]
                out['rates'][f'{sea} {g} {pop}'] = [len(rr), round(sum(r['y'] for r in rr) / len(rr), 3) if rr else None]
    tests = sorted({r['season'] for r in rows})[1:]
    for pop in ('newest', 'all'):
        res = defaultdict(lambda: defaultdict(list))
        for sea in tests:
            prior = [r for r in rows if r['season'] < sea and (pop == 'all' or r['newest'])]
            fit = {}
            for g in ('out', 'q'):
                pr = [r['y'] for r in prior if r['g'] == g]
                fit[g] = (sum(pr) + 1) / (len(pr) + 3)
            for r in rows:
                if r['season'] != sea or (pop == 'newest' and not r['newest']):
                    continue
                cur = CUR[sport][r['st']]
                cands = {'C2': fit[r['g']]}
                if sport == 'nfl':
                    cands['C1'] = C1[r['st']]
                for c, p in cands.items():
                    res[c]['cur_ll'].append(ll(cur, r['y'])); res[c]['new_ll'].append(ll(p, r['y']))
                    res[c]['cur_br'].append((cur - r['y']) ** 2); res[c]['new_br'].append((p - r['y']) ** 2)
                    res[c]['sea'].append(sea)
            out.setdefault('fits', {})[f'{pop} {sea}'] = {g: round(v, 3) for g, v in fit.items()}
        for c, v in res.items():
            m, t = paired(v['new_ll'], v['cur_ll'])
            mb, tb = paired(v['new_br'], v['cur_br'])
            per = {}
            for sea in tests:
                ix = [i for i, s in enumerate(v['sea']) if s == sea]
                if ix:
                    per[sea] = [len(ix), round(sum(v['cur_ll'][i] for i in ix) / len(ix), 4), round(sum(v['new_ll'][i] for i in ix) / len(ix), 4)]
            out['tests'][f'{c} {pop}'] = {'n': len(v['sea']), 'cur_ll': round(sum(v['cur_ll']) / len(v['cur_ll']), 4),
                                         'new_ll': round(sum(v['new_ll']) / len(v['new_ll']), 4), 'dLL': round(m, 4) if m is not None else None,
                                         't': round(t, 2) if t is not None else None, 'dBrier': round(mb, 4) if mb is not None else None,
                                         'tBrier': round(tb, 2) if tb is not None else None, 'bySeason': per}
    return out


def main():
    res = {}
    nfl = [r for s in (2024, 2025, 2026) for r in nfl_rows(s)]
    res['nfl'] = evaluate('nfl', nfl)
    nba = [r for s in (2024, 2025, 2026) for r in nba_rows(s)]
    res['nba'] = evaluate('nba', nba)
    res['nba']['b2b'] = {g: [sum(1 for r in nba if r['g'] == g and r['b2b']), sum(r['y'] for r in nba if r['g'] == g and r['b2b'])] for g in ('out', 'q')}
    json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    json.dump({'nfl': nfl, 'nba': nba}, gzip.open(os.path.join(HERE, 'rows.json.gz'), 'wt'))
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
