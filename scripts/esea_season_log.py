#!/usr/bin/env python3
"""1NT ESEA season log: one entry per league season (S53 on) for the season summary window and its GFX cards.

Per season: record (matches, maps, rounds), every league match in order (regular season then playoffs) with its
maps and round diff, round diff by map, and each player's line for that season only (RWA from data/esea_rwa.json
'seasons', joined by FACEIT id -> current nick exactly like the players_sNN.exe cards; the rest from data/esea.json
'players' (current season) and 'seasons' (past)).

Inputs: research/esea_1nt_history.json.gz (past seasons, scripts/esea_1nt_history.mjs), data/esea.json (current
season, scripts/fetch_esea.mjs), data/esea_rwa.json. Output: data/esea_seasons.json. Runs in esea.yml after
fetch_esea.mjs and esea_rwa.py. Forfeits count in the record and show as FF; they have no rounds.
"""
import gzip
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p, gz=False):
    try:
        with (gzip.open if gz else open)(os.path.join(ROOT, p), 'rt') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def div_name(comp):
    s = re.sub(r'^(ESEA\s+)?S\d{2}\s+(NA\s+)?', '', comp or '')
    return re.sub(r'\s*-\s*(Regular Season|Playoffs.*)$', '', s).strip()


def player_row(p, sn, nick_of, rwa_s):
    nick = nick_of.get(p.get('id'), p.get('name'))
    rw = (rwa_s.get(nick) or {}).get(str(sn))
    keep = ('name', 'country', 'maps', 'k', 'd', 'kd', 'adr', 'hs', 'kpr', 'rating', 'hltv', 'entryPM', 'clutch',
            'mapMvps', 'multi', 'role')
    out = {k: p.get(k) for k in keep if p.get(k) is not None}
    if rw:
        out['rwa'] = rw[0]
    return out


def summarize(sn, matches, comps, players):
    w = sum(m['res'] == 'W' for m in matches)
    mw = sum(x['rf'] > x['ra'] for m in matches for x in m['maps'])
    ml = sum(x['rf'] < x['ra'] for m in matches for x in m['maps'])
    rf = sum(x['rf'] for m in matches for x in m['maps'])
    ra = sum(x['ra'] for m in matches for x in m['maps'])
    by = {}
    for m in matches:
        for x in m['maps']:
            q = by.setdefault(x['map'], {'map': x['map'], 'w': 0, 'l': 0, 'rf': 0, 'ra': 0})
            q['w' if x['rf'] > x['ra'] else 'l'] += 1
            q['rf'] += x['rf']
            q['ra'] += x['ra']
    cum = 0
    for m in matches:
        if m['maps']:
            m['rd'] = sum(x['rf'] - x['ra'] for x in m['maps'])
            cum += m['rd']
        m['cum'] = cum
    rs = [c for c in comps if not re.search(r'Playoff', c)]
    return {'season': sn, 'div': div_name(rs[0] if rs else (comps[0] if comps else '')), 'playoffs': any('Playoff' in c for c in comps),
            'w': w, 'l': len(matches) - w, 'mapsW': mw, 'mapsL': ml, 'rf': rf, 'ra': ra,
            'matches': matches, 'maps': sorted(by.values(), key=lambda q: (-(q['w'] + q['l']), -(q['rf'] - q['ra']))),
            'players': players}


def main():
    H = load('research/esea_1nt_history.json.gz', gz=True) or {}
    D = load('data/esea.json') or {}
    R = load('data/esea_rwa.json') or {}
    cur = int(D.get('season') or 0)
    rwa_s = R.get('seasons') or {}
    nick_of = {m['id']: m['nick'] for m in D.get('members') or []}
    out = {}
    # past seasons
    by, comps = {}, {}
    for m in H.get('matches') or []:
        sm = re.search(r'\bS(\d{2})\b', m.get('compName') or '')
        if not sm or re.search('Qualifier', m['compName']) or m.get('status') != 'FINISHED':
            continue
        sn = int(sm.group(1))
        if cur and sn >= cur:
            continue
        maps = [{'map': x['map'], 'rf': x['rf'], 'ra': x['ra']} for x in m.get('maps') or [] if x.get('rf') is not None and x.get('ra') is not None]
        res = 'W' if m.get('winner') == 'us' else 'L'
        by.setdefault(sn, []).append({'at': m.get('at'), 'opp': (m.get('opp') or {}).get('name') or 'TBD', 'res': res,
                                      'po': 'Playoff' in m['compName'], 'ff': not maps, 'maps': maps})
        comps.setdefault(sn, [])
        if m['compName'] not in comps[sn]:
            comps[sn].append(m['compName'])
    past = D.get('seasons') or {}
    for sn, ms in by.items():
        ms.sort(key=lambda m: (m['po'], m['at'] or 0))
        pl = [player_row(p, sn, nick_of, rwa_s) for p in past.get(str(sn)) or []]
        out[str(sn)] = summarize(sn, ms, comps[sn], pl)
    # current season
    if cur and D.get('matches'):
        ms = []
        for m in D['matches']:
            if m.get('result') not in ('W', 'L'):
                continue
            maps = [{'map': x['map'], 'rf': x['rf'], 'ra': x['ra']} for x in m.get('maps') or [] if x.get('rf') is not None and x.get('ra') is not None]
            ms.append({'at': m.get('at'), 'opp': (m.get('opp') or {}).get('name') or 'TBD', 'res': m['result'],
                       'po': 'Playoff' in (m.get('stage') or ''), 'ff': not maps, 'maps': maps})
        ms.sort(key=lambda m: (m['po'], m['at'] or 0))
        pl = [player_row(p, cur, nick_of, rwa_s) for p in D.get('players') or []]
        s = summarize(cur, ms, [(D.get('championship') or {}).get('name') or ''], pl)
        s['total'] = (D.get('record') or {}).get('total')
        s['current'] = True
        out[str(cur)] = s
    for s in out.values():   # RWA first (it beat ARK Rating held out), ARK Rating when a season has no RWA line
        s['players'].sort(key=lambda p: (p.get('rwa') is None, -(p.get('rwa') if p.get('rwa') is not None else p.get('rating') or 0)))
    res = {'asof': D.get('asof'), 'current': cur, 'seasons': dict(sorted(out.items(), key=lambda kv: -int(kv[0])))}
    with open(os.path.join(ROOT, 'data', 'esea_seasons.json'), 'w') as f:
        json.dump(res, f, separators=(',', ':'))
    for k, s in res['seasons'].items():
        print(f"S{k} {s['div']}: {s['w']}-{s['l']} maps {s['mapsW']}-{s['mapsL']} rounds {s['rf']}-{s['ra']} ({s['rf'] - s['ra']:+d}) players {len(s['players'])}")


if __name__ == '__main__':
    main()
