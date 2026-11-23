#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT milestones (data/esea_milestones.json): per ESEA season the division, final regular-season standing,
playoff bracket + series + placing, and each 1NT player's rank in the division on RWA, ARK, ADR, K/D, KPR and HS%;
plus a dated milestone log (debut, division moves, playoff firsts, best finishes, division #1s, world-rank firsts).

    python3 scripts/esea_milestones.py        # esea.yml, after esea_rwa.py and esea_season_log.py

Inputs: data/esea.json (current season + standing), data/esea_seasons.json (1NT's league matches by season),
research/esea_1nt_history.json.gz (1NT's championships), research/esea_matches.json.gz (every league map of
1NT's divisions, S53 on) + the run's .cache/esea/rounds.json (this season's maps) through esea_rwa.state(),
data/esea_world.json (weekly world rank, scripts/esea_world.py).
Final standings: FACEIT leaderboard of each past regular season (FACEIT_API_KEY; fetched once, kept in the output);
without a key, wins then round diff over the archive's matches, only where the archive holds the whole season.
Division ranks: players with 40% of the division's most-played player's maps; RWA/ARK = that season's lines
(esea_rwa.season_lines, the players_sNN.exe numbers); box stats over the regular season's maps.
"""
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'esea_milestones.json')
TEAM = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a'
API = 'https://open.faceit.com/data/v4'
KEY = os.environ.get('FACEIT_API_KEY')
LEVEL = {'Open': 0, 'Open9-10': 0, 'Open1-8': 0, 'Intermediate': 1, 'Main': 2, 'Advanced': 3}
STATS = ('rwa', 'ark', 'adr', 'kd', 'kpr', 'hs')
LABEL = {'rwa': 'RWA', 'ark': 'ARK', 'adr': 'ADR', 'kd': 'K/D', 'kpr': 'KPR', 'hs': 'HS%'}
WORLD_N = (300, 275, 250, 225, 200, 175, 150, 125, 100, 75, 50, 25, 10)
CAP = 600   # FACEIT's match list stops here: an archive championship this long may be cut short


def load(p, gz=False):
    try:
        with (gzip.open if gz else open)(os.path.join(ROOT, p), 'rt') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def api(p):
    for a in range(4):
        try:
            rq = urllib.request.Request(API + p, headers={'Authorization': 'Bearer ' + KEY, 'Accept': 'application/json'})
            with urllib.request.urlopen(rq, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code != 429 and e.code < 500:
                raise
        except OSError:
            pass
        time.sleep(2 * (a + 1))
    return None


def div_of(name):
    s = re.sub(r'^(ESEA\s+)?S\d{2}\s+(NA\s+)?', '', name or '')
    return re.sub(r'\s*-\s*(Regular Season|Playoffs.*)$', '', s).strip()


def level(div):
    return LEVEL.get((div or '').split(' ')[0], 1)


def et_day(ms):
    return (datetime.fromtimestamp(ms / 1000, timezone.utc) - timedelta(hours=5)).strftime('%Y-%m-%d')


def leaderboard(cid):
    """1NT's final row on a championship leaderboard -> {rank, of, tied, w, l, pts}"""
    lbs = api(f'/leaderboards/championships/{cid}?limit=50') or {}
    for lb in lbs.get('items') or []:
        rows = []
        for off in range(0, 2000, 50):
            j = api(f'/leaderboards/{lb["leaderboard_id"]}?offset={off}&limit=50') or {}
            rows += j.get('items') or []
            if len(j.get('items') or []) < 50:
                break
        tid = lambda r: (r.get('team') or {}).get('team_id') or (r.get('player') or {}).get('user_id')
        me = next((r for r in rows if tid(r) == TEAM), None)
        if not me:
            continue
        key = lambda r: (r.get('points') or 0, r.get('win_rate') or 0, r.get('won') or 0)
        if me.get('position'):
            rank = int(me['position'])
            tied = sum(1 for r in rows if r.get('position') == me['position']) > 1
        else:
            rank = 1 + sum(1 for r in rows if key(r) > key(me))
            tied = sum(1 for r in rows if key(r) == key(me)) > 1
        return {'rank': rank, 'of': len(rows), 'tied': tied, 'w': me.get('won'), 'l': me.get('lost'),
                'pts': me.get('points'), 'src': 'faceit'}
    return None


def archive_standing(ms, whole=False):
    """wins then round diff over the archive's matches (byes count as wins, as on FACEIT)"""
    if len(ms) >= CAP and not whole:
        return None
    W, RD = defaultdict(int), defaultdict(int)
    for m in ms:
        win = m.get('winner')
        for f, o in (('f1', 'f2'), ('f2', 'f1')):
            t = m[f]['id']
            if t == 'bye':
                continue
            W[t] += 0
            if win == ('faction1' if f == 'f1' else 'faction2'):
                W[t] += 1
            for mp in m.get('maps') or []:
                a, b = (mp['s1'], mp['s2']) if f == 'f1' else (mp['s2'], mp['s1'])
                RD[t] += (a or 0) - (b or 0)
    if TEAM not in W:
        return None
    key = lambda t: (W[t], RD[t])
    return {'rank': 1 + sum(1 for t in W if key(t) > key(TEAM)), 'of': len(W),
            'tied': sum(1 for t in W if key(t) == key(TEAM)) > 1, 'src': 'archive'}


def placing(ms):
    """playoff placing from a bracket's matches: teams whose last match came on a later ET day finished above;
    teams out the same day share the range -> {teams, place: [lo, hi], champion}"""
    last, lost = {}, {}
    for m in ms:
        if not m.get('at') or m.get('winner') not in ('faction1', 'faction2'):
            continue
        for f in ('f1', 'f2'):
            t = m[f]['id']
            if t == 'bye':
                continue
            if m['at'] >= last.get(t, 0):
                last[t] = m['at']
                lost[t] = m.get('winner') != ('faction1' if f == 'f1' else 'faction2')
    if TEAM not in last:
        return None
    day = {t: et_day(a * 1000 if a < 1e11 else a) for t, a in last.items()}
    me = day[TEAM]
    if not lost[TEAM] and me == max(day.values()):
        return {'teams': len(last), 'place': [1, 1], 'champion': True}
    above = sum(1 for t in day if day[t] > me or (day[t] == me and not lost[t]))
    same = sum(1 for t in day if day[t] == me and lost[t])
    return {'teams': len(last), 'place': [above + 1, above + same], 'champion': False}


def box(maps_by_team):
    """[(team id, map)] -> per player totals"""
    P = defaultdict(lambda: {'maps': 0, 'r': 0, 'k': 0, 'd': 0, 'dmg': 0.0, 'hk': 0, 'hr': 0, 'team': defaultdict(int)})
    for tid, mp, side in maps_by_team:
        rr = (mp.get('s1') or 0) + (mp.get('s2') or 0)
        if rr < 13:
            continue
        for x in mp.get(side) or []:
            q = P[x[0]]
            q['maps'] += 1
            q['r'] += rr
            q['k'] += x[1] or 0
            q['d'] += x[2] or 0
            q['dmg'] += (x[4] or 0) * rr
            q['team'][tid] += 1
            f = x[5] if len(x) > 5 else None
            if f and len(f) > 23 and not mp.get('live'):
                q['hk'] += f[23] or 0
                q['hr'] += x[1] or 0
    return P


def main():
    es = load('data/esea.json') or {}
    seas = (load('data/esea_seasons.json') or {}).get('seasons') or {}
    hist = load('research/esea_1nt_history.json.gz', True) or {}
    world = load('data/esea_world.json') or {}
    prev = load('data/esea_milestones.json') or {}
    cache = dict(prev.get('standings') or {})
    raw = load('research/esea_matches.json.gz', True) or {}
    byc = defaultdict(list)
    for m in raw.get('matches') or []:
        byc[m['champ']].append(m)
    full = set()   # championships whose missing matches scripts/esea_div_backfill.mjs filled
    ids = {m['id'] for m in raw.get('matches') or []}
    # 1NT's own league matches (research/esea_1nt_history.json.gz, both fives' lines) where the archive lacks them
    ln = lambda q: [q[0], q[2][0], q[2][6], q[2][7], q[2][8], q[2]]
    for h in hist.get('matches') or []:
        if h['id'] in ids or h.get('comp') not in (hist.get('comps') or {}) or not h.get('maps'):
            continue
        ids.add(h['id'])
        byc[h['comp']].append({'id': h['id'], 'champ': h['comp'], 'at': (h.get('at') or 0) // 1000,
                               'winner': 'faction1' if h.get('winner') == 'us' else 'faction2',
                               'f1': {'id': TEAM, 'roster': (h.get('us') or {}).get('roster') or []},
                               'f2': {'id': (h.get('opp') or {}).get('id'), 'roster': (h.get('opp') or {}).get('roster') or []},
                               'maps': [{'map': x['map'], 's1': x['rf'], 's2': x['ra'], 'p1': [ln(q) for q in x.get('us') or []],
                                         'p2': [ln(q) for q in x.get('them') or []]} for x in h['maps']]})
    for m in (load('research/esea_div_backfill.json.gz', True) or {}).get('matches') or []:
        full.add(m['champ'])
        if m['id'] not in ids:
            ids.add(m['id'])
            byc[m['champ']].append(m)
    comps = dict(hist.get('comps') or {})
    for c in es.get('championships') or []:
        comps[c['id']] = c['name']
    cur_cid = (es.get('championship') or {}).get('id')
    cur = int(es.get('season') or 0)
    rs, po = {}, defaultdict(list)
    for cid, name in comps.items():
        mm = re.search(r'\bS(\d{2})\b', name or '')
        if not mm:
            continue
        sn = int(mm[1])
        if 'Regular Season' in name:
            rs[sn] = (cid, name)
        elif 'Playoff' in name:
            po[sn].append((cid, name))

    import esea_rwa as RW
    S = RW.state()
    live = S['live']

    nick = {}
    for q, n in ((load('data/esea_rwa.json') or {}).get('names') or {}).items():
        nick[q] = n
    for x in es.get('members') or []:
        nick[x['id']] = x['nick']
    for rows in (es.get('seasons') or {}).values():
        for x in rows:
            if x.get('id'):
                nick.setdefault(x['id'], x['name'])
    country = dict(es.get('countries') or {})

    seasons_out = []
    for sn in sorted(set(int(k) for k in seas) | set(rs)):
        s = seas.get(str(sn)) or {}
        cid, cname = rs.get(sn, (None, None))
        div = s.get('div') or div_of(cname)
        # ---- standing
        st = None
        if sn == cur and es.get('standing'):
            x = es['standing']
            st = {'rank': x.get('rank'), 'of': x.get('of'), 'tied': x.get('tied'), 'src': 'faceit'}
        elif cid:
            st = cache.get(cid)
            if (not st or st.get('src') != 'faceit') and KEY:
                try:
                    st = leaderboard(cid) or st
                except Exception as e:   # noqa: BLE001
                    print(f'leaderboard {cid}: {e}', file=sys.stderr)
            if not st:
                st = archive_standing(byc.get(cid) or [], cid in full)
            if st:
                cache[cid] = st
        # ---- playoffs
        ms = s.get('matches') or []
        pm = [m for m in ms if m.get('po')]
        pl = None
        if pm or po.get(sn):
            name = ' + '.join(div_of(n).split(' ')[0] + ' ' + re.sub(r'^.*Playoffs\s*(Bracket\s*)?', '', n).strip()
                              for _, n in po.get(sn, [])).replace('  ', ' ').strip() or 'Playoffs'
            ser = [{'opp': m['opp'], 'res': m['res'], 'at': m['at'], 'ff': m.get('ff'),
                    'mw': sum(1 for x in m.get('maps') or [] if x['rf'] > x['ra']),
                    'ml': sum(1 for x in m.get('maps') or [] if x['rf'] < x['ra'])} for m in pm]
            pl = {'name': name, 'w': sum(1 for x in ser if x['res'] == 'W'), 'l': sum(1 for x in ser if x['res'] == 'L'),
                  'series': ser}
            for pcid, _ in po.get(sn, []):
                pp = placing(byc.get(pcid) or [])
                if pp:
                    pl.update(pp)
            if ser and ser[-1]['res'] == 'L' and not pl.get('champion'):
                pl['out'] = ser[-1]['opp']
        # ---- division ranks
        lines = []
        for m in byc.get(cid) or []:
            for mp in m.get('maps') or []:
                lines += [(m['f1']['id'], mp, 'p1'), (m['f2']['id'], mp, 'p2')]
        if sn == cur and cid == cur_cid:
            for m in live:
                for mp in m['maps']:
                    mp = dict(mp, live=True)
                    lines += [(m['f1']['id'], mp, 'p1'), (m['f2']['id'], mp, 'p2')]
        P = box(lines)
        players, pool = [], 0
        if P:
            top = max(q['maps'] for q in P.values())
            minm = max(3, math.ceil(0.4 * top))
            sl = RW.season_lines(S['M'], S['c'], S['th'], S['p'], S['es'], S['center'], S['cn'],
                                 who=[{'id': q, 'nick': q} for q in P])
            V = {}
            for q, t in P.items():
                rw = (sl.get(q) or {}).get(str(sn))
                V[q] = {'maps': t['maps'], 'rwa': rw[0] if rw else None, 'ark': rw[1] if rw else None,
                        'adr': round(t['dmg'] / t['r'], 1) if t['r'] else None,
                        'kd': round(t['k'] / t['d'], 2) if t['d'] else None,
                        'kpr': round(t['k'] / t['r'], 2) if t['r'] else None,
                        'hs': round(100 * t['hk'] / t['hr']) if t['hr'] >= 0.5 * t['k'] and t['hr'] else None,
                        'ok': t['maps'] >= minm}
            elig = [q for q in V if V[q]['ok']]
            pool = len(elig)
            ranks = {}
            for k in STATS:
                vals = sorted((V[q][k] for q in elig if V[q][k] is not None), reverse=True)
                for q in elig:
                    v = V[q][k]
                    if v is not None:
                        ranks[(q, k)] = 1 + sum(1 for x in vals if x > v)
            for q, t in P.items():
                if not t['team'].get(TEAM):
                    continue
                row = {'name': nick.get(q, q[:8]), 'country': country.get(q), 'maps': V[q]['maps']}
                for k in STATS:
                    row[k] = V[q][k]
                    if (q, k) in ranks:
                        row[k + 'R'] = ranks[(q, k)]
                players.append(row)
            players.sort(key=lambda r: (-(r['maps'] >= minm), r.get('rwaR') or 9999, -r['maps']))
        seasons_out.append({'season': sn, 'div': div, 'w': s.get('w'), 'l': s.get('l'), 'rf': s.get('rf'), 'ra': s.get('ra'),
                            'standing': st, 'playoffs': pl, 'players': players, 'pool': pool,
                            'minMaps': max(3, math.ceil(0.4 * max([q['maps'] for q in P.values()] or [0]))),
                            'current': sn == cur, 'start': ms[0]['at'] if ms else None, 'end': ms[-1]['at'] if ms else None})

    # ---- milestone log
    # playoff round by match time (1NT's history, this season's matches)
    rnd = {h['at']: h.get('round') for h in hist.get('matches') or [] if h.get('at')}
    rnd.update({m['at']: m.get('round') for m in es.get('matches') or [] if m.get('at')})
    log = []
    add = lambda at, sn, kind, t: log.append({'at': at, 's': sn, 'k': kind, 't': t})
    prevs = None
    po_seen = po_win = False
    for x in seasons_out:
        sn, at = x['season'], x['start']
        if at is None:
            continue
        if prevs is None:
            add(at, sn, 'debut', f'ESEA debut · {x["div"]}')
        elif level(x['div']) != level(prevs['div']):
            up = level(x['div']) > level(prevs['div'])
            add(at, sn, 'up' if up else 'down', f'{"Promoted" if up else "Relegated"} to {x["div"].split(" ")[0]} · from {prevs["div"]}')
            x['move'], x['from'] = ('up' if up else 'down'), prevs['div']
        p = x['playoffs']
        if p and p['series']:
            if not po_seen:
                add(p['series'][0]['at'], sn, 'po', f'First playoffs · {p["name"]}')
                po_seen = True
            for q in p['series']:
                if q['res'] != 'W':
                    continue
                rd = rnd.get(q['at'])
                sc = 'forfeit' if q.get('ff') else f'{q["mw"]}-{q["ml"]}'
                add(q['at'], sn, 'po', f'{"First playoff series win" if not po_win else "Playoff series win"} · {p["name"]}'
                    f'{f" round {rd}" if rd else ""} · beat {q["opp"]} {sc}')
                po_win = True
            if p.get('champion'):
                add(p['series'][-1]['at'], sn, 'po', 'Won ' + p['name'])
            if p['w'] >= 3:
                add(p['series'][-1]['at'], sn, 'po', f'{p["w"]} playoff series wins · {p["name"]}')
        for r in x['players']:
            for k in STATS:
                rk = r.get(k + 'R')
                if rk and (rk <= 3 or (k in ('rwa', 'ark') and rk <= 10)):
                    add(x['end'], sn, 'player', f'{r["name"]} #{rk} {LABEL[k]} in {x["div"]} ({x["pool"]} players)')
        prevs = x
    def season_at(at):
        sn = None
        for x in sorted(seasons_out, key=lambda x: x['season']):
            if x['start'] and at >= x['start'] - 21 * 86400000:
                sn = x['season']
        return sn
    wk = world.get('weekly') or []
    hit = set()
    best = None
    for w in wk:
        at = int(datetime.strptime(w['d'], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
        for n in WORLD_N:
            if w.get('vrs') and w['vrs'] <= n and n not in hit and n < (wk[0].get('vrs') or 9999):
                hit.add(n)
                add(at, season_at(at), 'world', f'World top {n} · #{w["vrs"]} of {w["of"]}')
        if w.get('vrs') and (best is None or w['vrs'] < best['vrs']):
            best = dict(w, at=at)
    world_out = None
    if wk:
        bn = min((w for w in wk if w.get('na')), key=lambda w: w['na'], default=None)
        world_out = {'best': {'vrs': best['vrs'], 'of': best['of'], 'd': best['d']} if best else None,
                     'bestNa': {'na': bn['na'], 'of': bn['naOf'], 'd': bn['d']} if bn else None,
                     'first': {'vrs': wk[0]['vrs'], 'of': wk[0]['of'], 'd': wk[0]['d']},
                     'now': world.get('now')}
        if best:
            add(best['at'], season_at(best['at']), 'world', f'Best world rank · #{best["vrs"]} of {best["of"]}')
    log.sort(key=lambda e: e['at'])

    # career totals for the top tiles
    tot = {'seasons': len([x for x in seasons_out if x['start']]),
           'poSeasons': sum(1 for x in seasons_out if x['playoffs'] and x['playoffs']['series']),
           'poW': sum(x['playoffs']['w'] for x in seasons_out if x['playoffs']),
           'poL': sum(x['playoffs']['l'] for x in seasons_out if x['playoffs']),
           'w': sum(x['w'] or 0 for x in seasons_out), 'l': sum(x['l'] or 0 for x in seasons_out)}
    out = {'asof': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'totals': tot, 'world': world_out,
           'seasons': sorted(seasons_out, key=lambda x: -x['season']), 'log': log[::-1], 'standings': cache}
    s = json.dumps(out, separators=(',', ':'), allow_nan=False)
    open(OUT, 'w').write(s)
    print(f'wrote {OUT}: {len(seasons_out)} seasons, {len(log)} milestones, {len(s) // 1024} KB', file=sys.stderr)


if __name__ == '__main__':
    main()
