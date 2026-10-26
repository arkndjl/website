#!/usr/bin/env python3
"""Player stats for the 13 other leagues on the SOCCER ARKBOARD (soccer_data.SHOWN), from FotMob's season stat lists
(data.fotmob.com/stats/<league>/season/<id>/<stat>.json, free, no key): minutes, matches, goals, assists, xG, xA,
shots, chances created, FotMob's match rating, nationality. One file a season in static/data/soccer-more/<S>.json,
next to the big five's static/data/soccer-war/<S>.json (same field names, so the stats view reads both). Seasons
follow soccer-war's numbering (2027 = 2026-27); the spring-to-autumn leagues (Norway, Sweden) file their calendar
year Y under Y + 1, the season it ends next to. No GAR: Understat's minute-level data (on/off, xGBuildup) exists only
for the big five. Players under 22 on the soccer prospects board carry its FV (matched on name and club through
scripts/names.py's rules).

    python3 scripts/soccer_more.py          # this season (finished seasons are cached in scripts/.cache/soccer/fms)
    python3 scripts/soccer_more.py --all    # every season FotMob lists (up to 12)
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D  # noqa: E402
import soccer_faces as SF  # noqa: E402
import names as NM  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'static', 'data', 'soccer-more')
CACHE = os.path.join(D.CACHE, 'fms')
PROS = os.path.join(ROOT, 'data', 'soccer_prospects.json')
FMMAP = os.path.join(HERE, 'data', 'soccer_fm_map.json')
FMLG = {'ned.1': 57, 'por.1': 61, 'bel.1': 40, 'tur.1': 71, 'cze.1': 122, 'gre.1': 135, 'pol.1': 196, 'den.1': 46,
        'sui.1': 69, 'nor.1': 59, 'aut.1': 38, 'sco.1': 64, 'swe.1': 67}
STATS = {'mins_played': None, 'goals': 'g', 'goal_assist': 'a', 'expected_goals': 'xg', 'expected_assists': 'xa',
         'total_scoring_att': 'sh', 'total_att_assist': 'kp', 'rating': 'rt'}


def pos_of(code):
    """FotMob's position id: 11 keeper, 3x defence, 5x-7x midfield, 8x wingers / attacking mid and 10x-11x strikers
    (Understat files wingers with the forwards)"""
    if code == 11:
        return 'GK'
    if 30 <= code < 40:
        return 'D'
    if 50 <= code < 80:
        return 'M'
    if code >= 80:
        return 'F'
    return None


def season_files(lg):
    d = D.get(f'https://www.fotmob.com/api/data/leagues?id={FMLG[lg]}')
    out = {}
    for L in ((d or {}).get('stats') or {}).get('seasonStatLinks') or []:
        n = L['Name']
        S = int(n[-4:]) + (1 if lg in D.CAL else 0)
        out.setdefault(S, 'https://data.fotmob.com/' + L['RelativePath'].rsplit('/', 1)[0] + '/')
    return out


def pull(lg, S, base):
    p = os.path.join(CACHE, f'{lg}_{S}.json.gz')
    if os.path.exists(p) and (S < D.current_season() or time.time() - os.path.getmtime(p) < 6 * 3600):
        return D.load(p)
    have = {s.get('StatName') for s in (D.get(base + 'topstats.json') or {}).get('TopLists') or []}
    P = {}
    for st, k in STATS.items():
        if st not in have:
            continue
        x = D.get(base + st + '.json') or {}
        for p_ in (row for t in x.get('TopLists') or [] for row in t.get('StatList') or []):
            i = str(p_.get('ParticiantId'))
            o = P.setdefault(i, {'p': 'fm' + i, 'n': p_.get('ParticipantName'), 'team': p_.get('TeamName'),
                                 'tid': str(p_.get('TeamId')), 'cc': p_.get('ParticipantCountryCode'),
                                 'pc': (p_.get('Positions') or [None])[0], 'min': 0, 'mp': 0})
            o['min'] = max(o['min'], p_.get('MinutesPlayed') or 0)
            o['mp'] = max(o['mp'], p_.get('MatchesPlayed') or 0)
            if k:
                o[k] = p_.get('StatValue')
        time.sleep(0.15)
    rows = list(P.values())
    D.save(p, rows)
    return rows


def prospects():
    """name key -> [(club, FV, provisional)] from the soccer prospects board"""
    try:
        B = json.load(open(PROS))['board']
    except (OSError, KeyError, ValueError):
        return {}
    out = {}
    for o in B:
        out.setdefault(NM.key(o['name']), []).append((o.get('club') or '', o['fv'], bool(o.get('prov'))))
    return out


def club_like(a, b):
    import soccer_games as G
    return NM.same_team(a, b) or G.name_sim(a, b) >= 0.5


def build(seasons=None):
    cur = D.current_season()
    mp = json.load(open(FMMAP)) if os.path.exists(FMMAP) else {}
    C = SF.ctry()
    pros = prospects()
    by = {}
    for lg in FMLG:
        for S, base in season_files(lg).items():
            if seasons and S not in seasons:
                continue
            for r in pull(lg, S, base):
                if r['min'] < 90:
                    continue
                o = {k: r.get(k) for k in ('p', 'n', 'team', 'min', 'mp', 'g', 'a', 'xg', 'xa', 'sh', 'kp', 'rt')}
                for k in ('g', 'a', 'sh', 'kp'):
                    o[k] = int(o[k] or 0)
                for k in ('xg', 'xa'):
                    o[k] = round(float(o[k]), 2) if o[k] is not None else None
                o['rt'] = round(float(o['rt']), 2) if o['rt'] is not None else None
                o['lg'], o['pos'] = lg, pos_of(r['pc'] or 0)
                lid = mp.get('f' + r['tid'], 'f' + r['tid'])
                if os.path.exists(os.path.join(ROOT, 'static', 'img', 'soccer', f'{lid}.png')):
                    o['lid'] = lid
                nat = SF.fm_iso(r.get('cc'), C)
                if nat:
                    o['nat'] = nat
                o['fph'] = r['p'][2:]
                if S == cur:
                    for club, fv, prov in pros.get(NM.key(o['n']), []):
                        if club_like(club, o['team']):
                            o['fv'] = fv
                            if prov:
                                o['prov'] = 1
                            break
                by.setdefault(S, []).append(o)
    os.makedirs(OUT, exist_ok=True)
    for S, ps in by.items():
        ps.sort(key=lambda o: -o['min'])
        games = {}
        for o in ps:
            games[o['lg']] = max(games.get(o['lg'], 0), o['mp'])
        J = {'asof': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'season': S, 'games': games, 'players': ps}
        open(os.path.join(OUT, f'{S}.json'), 'w').write(json.dumps(J, separators=(',', ':'), allow_nan=False))
        print('wrote', S, len(ps), flush=True)
    SF.fetch_flags({o.get('nat') for ps in by.values() for o in ps} - {None})


if __name__ == '__main__':
    build(None if '--all' in sys.argv else {D.current_season()})
