# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL Potential Breakout ("next up" tab): breakout odds and contextual ice-time scaling for every NHL skater
(static/data/next-up/nhl.json). Model and held-out tests: scripts/nhl_breakout_research.py -> data/nhl_breakout_fit.json.

    python3 scripts/nhl_breakout.py            # build from the NHL stats API + static/data/nhl-war + the fit; stdlib only

Workload = ice time a game, split by state. Three fitted relations, each next season's value on this season's + the
change in workload + that change x the player's traits:
    ev_p60   even-strength points a 60 as even-strength minutes a game change
    pp_p60   power-play points a 60 as power-play minutes a game change
    pp_toi   power-play minutes a game as total minutes a game change (where added minutes land)
A tier (TOI 15 / 18 / 21) = pp_toi gives the power-play minutes at that ice time, the rest of the added minutes are
even strength (penalty-kill minutes held), the two rates are read at those minutes, points = rate x minutes.
Goalies are not on the tab. Feature columns live here so the research fit and the live board build them the same way."""
import datetime as dt
import gzip
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nhl_data as D  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FIT = os.path.join(ROOT, 'data', 'nhl_breakout_fit.json')
OUT = os.path.join(ROOT, 'static', 'data', 'next-up', 'nhl.json')
CEIL = os.path.join(ROOT, 'data', 'nhl_ceiling_fit.json')      # scripts/nhl_ceiling_research.py
WAR = os.path.join(ROOT, 'static', 'data', 'nhl-war')
CACHE = os.path.join(D.CACHE, 'bo')
FACE = 'https://a.espncdn.com/combiner/i?img=/i/headshots/nhl/players/full/%s.png&w=96&h=70&scale=crop'

REPORTS = {
    'summary': ('skaterFullName', 'positionCode', 'gamesPlayed', 'goals', 'assists', 'points', 'shots', 'evPoints',
                'ppPoints', 'shPoints'),
    'timeonice': ('timeOnIce', 'evTimeOnIce', 'ppTimeOnIce', 'shTimeOnIce'),
    'bios': ('height', 'weight', 'birthDate', 'draftOverall'),
    'scoringRates': ('goals5v5', 'primaryAssists5v5', 'points5v5', 'onIceShootingPct5v5', 'satRelative5v5'),
    'percentages': ('skaterShootingPlusSavePct5v5',),
    'realtime': ('hits',),
}


def pull(S, fresh=False):
    """{player id: {field: value}} for one season (regular season, skaters), cached; a finished season is fetched once"""
    path = os.path.join(CACHE, f'{S}.json.gz')
    if os.path.exists(path) and not fresh:
        return D.load(path)
    out = {}
    for rep, fields in REPORTS.items():
        j = D.get(f'{D.STATS}/skater/{rep}?limit=-1&cayenneExp=seasonId={D.sid(S)}%20and%20gameTypeId=2')
        if not j or not j.get('data'):
            if os.path.exists(path):
                return D.load(path)
            raise RuntimeError(f'NHL stats API: no {rep} for {S}')
        for r in j['data']:
            o = out.setdefault(str(r['playerId']), {})
            for k in fields:
                o[k] = r.get(k)
    D.save(path, out)
    return out


def war_file(S):
    try:
        return json.load(open(os.path.join(WAR, f'{S}.json')))
    except (OSError, ValueError):
        return None


def season(S, fresh=False):
    """{pid: player-season} with per-game minutes, rates and the site's WAR"""
    raw = pull(S, fresh)
    wf = war_file(S) or {}
    W = {str(p['id']): p for p in wf.get('players', []) if p.get('grp') != 'G'}
    gmax = min(82, wf.get('games') or 82)
    P = {}
    for pid, r in raw.items():
        gp, sec = r.get('gamesPlayed') or 0, r.get('timeOnIce') or 0
        if gp < 1 or sec <= 0 or 'evTimeOnIce' not in r:
            continue
        tmin, evmin, ppmin, shmin = (float(r.get(k) or 0) / 60 for k in ('timeOnIce', 'evTimeOnIce', 'ppTimeOnIce',
                                                                        'shTimeOnIce'))
        pts, g, shots = r.get('points') or 0, r.get('goals') or 0, r.get('shots') or 0
        p5, g5, a5 = r.get('points5v5') or 0, r.get('goals5v5') or 0, r.get('primaryAssists5v5') or 0
        pos = r.get('positionCode') or 'C'
        w = W.get(pid) or {}
        age = w.get('ax') or w.get('age') or 27.0
        if r.get('birthDate'):
            try:
                b = dt.date.fromisoformat(r['birthDate'][:10])
                age = (dt.date(S - 1, 9, 15) - b).days / 365.25
            except ValueError:
                pass
        ht, wt = r.get('height') or 73, r.get('weight') or 200
        o = {'pid': pid, 'y': S, 'n': r.get('skaterFullName') or w.get('n') or '', 'pos': pos, 'd': 1.0 if pos == 'D' else 0.0,
             'c': 1.0 if pos == 'C' else 0.0, 'gp': gp, 'gmax': gmax, 'tmin': tmin, 'evmin': evmin, 'ppmin': ppmin,
             'toi': tmin / gp, 'ev': evmin / gp, 'pp': ppmin / gp, 'sh': shmin / gp, 'pts': pts, 'g': g, 'shots': shots,
             'shp': r.get('shPoints') or 0,
             'ev_p60': (r.get('evPoints') or 0) / max(evmin, 1.0) * 60,
             'pp_p60': (r.get('ppPoints') or 0) / max(ppmin, 1.0) * 60 if ppmin >= 1 else 0.0,
             'p60': pts / tmin * 60, 'sh60': shots / tmin * 60, 'shpct': g / shots if shots else 0.0,
             'prim': (g5 + a5 + 3.5) / (p5 + 5.0),
             'oish': r['onIceShootingPct5v5'] if r.get('onIceShootingPct5v5') is not None else 0.085,
             'satrel': r.get('satRelative5v5') or 0.0,
             'pdo': r.get('skaterShootingPlusSavePct5v5') or 1.0,
             'hits60': (r.get('hits') or 0) / tmin * 60, 'ht': float(ht), 'bmi': 703.0 * wt / ht ** 2, 'age': age,
             'pick': r.get('draftOverall') or 0, 'tm': w.get('tm'), 'war': w.get('war'), 'hpm': w.get('hpm'),
             'ph': w.get('ph'), 'go': w.get('go') or 0.0, 'gd': w.get('gd') or 0.0}
        P[pid] = o
    return P


def history(P, pid, y):
    return [P[(pid, s)] for s in range(y - 6, y + 1) if (pid, s) in P]


# ---------- ice-time scaling ----------
# x = the rate, u = its workload (minutes a game), n = its sample (minutes), k = shrink minutes, low = (ref, scale) of
# the low-workload ramp, rose = the workload rise the tab projects, minn = sample floor (this season, next), cap = weight cap
TARGETS = {
    'ev_p60': {'x': 'ev_p60', 'u': 'ev', 'n': 'evmin', 'k': 600.0, 'low': (13.0, 4.0), 'rose': 1.5, 'minn': (250, 400),
               'mean': (1.6, 0.8), 'own_k': 4.0},
    'pp_p60': {'x': 'pp_p60', 'u': 'pp', 'n': 'ppmin', 'k': 150.0, 'low': (1.5, 1.5), 'rose': 0.75, 'minn': (20, 60),
               'mean': (4.2, 3.2), 'own_k': 1.0},
    'pp_toi': {'x': 'pp', 'u': 'toi', 'n': 'tmin', 'k': 300.0, 'low': (14.0, 4.0), 'rose': 2.0, 'minn': (250, 400),
               'mean': (1.5, 1.2), 'own_k': 6.0},
}
BASE = ['x0', 'x0*r0', 'r0', 'age', 'age2', 'u0', 'xprev', 'hasprev', 'd']
BLOCKS = {
    'role': ['dD', 'c', 'ppsh', 'shsh', 'hits60'],
    'frame': ['ht', 'bmi'],
    'shot profile': ['sh60', 'shpct', 'prim'],
    'past TOI history': ['own', 'xprevc'],
    'age': ['agec'],
    'low-TOI rates': ['x0c', 'x0c_low'],
    'on-ice context': ['oish', 'satrel'],
}


def columns(tgt=None):
    return BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in tr], []) for tr in BLOCKS.values()], [])


def own_slope(hist, tgt):
    """the player's own workload -> rate slope across his seasons, shrunk toward 0"""
    T = TARGETS[tgt]
    h = [o for o in hist if o[T['n']] >= T['minn'][0]]
    if len(h) < 2:
        return 0.0
    W = [o[T['n']] / 1000 for o in h]
    sw = sum(W)
    mu = sum(w * o[T['u']] for w, o in zip(W, h)) / sw
    mx = sum(w * o[T['x']] for w, o in zip(W, h)) / sw
    sxy = sum(w * (o[T['u']] - mu) * (o[T['x']] - mx) for w, o in zip(W, h))
    sxx = sum(w * (o[T['u']] - mu) ** 2 for w, o in zip(W, h))
    return sxy / (sxx + T['own_k'])


def trait_vals(tgt, a, hist):
    T = TARGETS[tgt]
    x0 = a[T['x']]
    prev = [o for o in hist if o['y'] < a['y'] and o[T['n']] >= T['minn'][0]]
    xprev = prev[-1][T['x']] if prev else x0
    low = max(0.0, T['low'][0] + (4.0 if a['d'] and tgt != 'pp_p60' else 0.0) - a[T['u']]) / T['low'][1]
    mean = T['mean'][int(a['d'])]
    return {'dD': a['d'], 'c': a['c'], 'ppsh': a['pp'] / a['toi'], 'shsh': a['sh'] / a['toi'], 'hits60': a['hits60'],
            'ht': a['ht'], 'bmi': a['bmi'], 'sh60': a['sh60'], 'shpct': (a['g'] + 3.0) / (a['shots'] + 30.0),
            'prim': a['prim'], 'own': own_slope(hist, tgt), 'xprevc': xprev - x0, 'agec': a['age'] - 26,
            'x0c': x0 - mean, 'x0c_low': (x0 - mean) * low, 'oish': a['oish'] - 0.085, 'satrel': a['satrel'],
            '_xprev': xprev, '_has': 1.0 if prev else 0.0}


def features(tgt, a, hist, dU):
    T = TARGETS[tgt]
    t = trait_vals(tgt, a, hist)
    x0, r0, age = a[T['x']], a[T['n']] / (a[T['n']] + T['k']), a['age']
    v = {'x0': x0, 'x0*r0': x0 * r0, 'r0': r0, 'age': age, 'age2': age * age, 'u0': a[T['u']],
         'xprev': t['_xprev'], 'hasprev': t['_has'], 'd': a['d'], 'dU': dU}
    for tr in BLOCKS.values():
        for k in tr:
            v[k] = t[k]
            v['dU*' + k] = dU * t[k]
    return [v[c] for c in columns(tgt)]


def predict(fit, tgt, a, hist, dU):
    f = fit['scaling'][tgt]['fit']
    x = dict(zip(columns(tgt), features(tgt, a, hist, dU)))
    return f['b0'] + sum(b * x[c] for b, c in zip(f['b'], f['cols']))


def tier(fit, a, hist, k):
    """(points a game, points a 60, pp minutes) at k minutes a game"""
    dT = k - a['toi']
    pp = min(max(predict(fit, 'pp_toi', a, hist, dT), 0.0), 0.3 * k, 5.5)
    sh = min(a['sh'], 0.25 * k)
    ev = max(k - pp - sh, 0.5 * k)
    e = max(predict(fit, 'ev_p60', a, hist, ev - a['ev']), 0.0)
    q = max(predict(fit, 'pp_p60', a, hist, pp - a['pp']), 0.0)
    pg = e * ev / 60 + q * pp / 60 + a['shp'] / a['gp']
    return pg, pg / k * 60, pp


# ---------- breakout odds ----------
K_SHR, ROLE_MIN, ROW_MIN = 600.0, 900.0, 200.0
BO_CANDS = ('age curve', 'low-TOI efficiency', 'vacated TOI', 'shooting luck', 'projection gap', 'TOI room',
            'TOI scaling', 'draft capital', 'site HPM', 'shot share', 'production')
BO_NEW = ('development curve', 'depth opportunity', 'departures ahead', 'coaching change', 'within-season trend',
          'experience', 'offence / defence split')
BO_LABEL = {'development curve': 'dev curve', 'depth opportunity': 'depth', 'departures ahead': 'open spot',
            'coaching change': 'new coach', 'within-season trend': 'trend', 'experience': 'experience',
            'offence / defence split': 'off/def',
            'age curve': 'age', 'low-TOI efficiency': 'low-TOI eff', 'vacated TOI': 'open TOI', 'shooting luck': 'shot luck',
            'projection gap': 'proj gap', 'TOI room': 'TOI room', 'TOI scaling': 'scales', 'draft capital': 'pedigree',
            'site HPM': 'HPM', 'shot share': 'shot share', 'production': 'points'}


def rate(o):
    """WAR a 1,000 minutes"""
    return o['war'] / o['tmin'] * 1000


def shr(o):
    """WAR a 1,000 minutes shrunk to replacement (0) by ice time"""
    return o['war'] / (o['tmin'] + K_SHR) * 1000


def best(a, hist):
    """his best shrunk WAR rate of this season and the ones before it (6 back)"""
    return max([shr(a)] + [shr(o) for o in hist if o['y'] < a['y'] and o['war'] is not None])


def career(first=2009, last=None):
    """{pid: {season: shrunk WAR rate}} over every season file of the site's WAR (skaters)"""
    C = {}
    for S in range(first, (last or D.current_season()) + 1):
        for p in (war_file(S) or {}).get('players', []):
            if p.get('grp') != 'G' and p.get('war') is not None and p.get('toi'):
                C.setdefault(str(p['id']), {})[S] = p['war'] / (p['toi'] + K_SHR) * 1000
    return C


def peak(C, pid, y):
    """best shrunk WAR rate of any season through y (None: no season)"""
    v = [r for S, r in C.get(pid, {}).items() if S <= y]
    return max(v) if v else None


def marcel(hist, y):
    """3-season WAR a 1,000 minutes, weights 5/4/3 by minutes, shrunk to replacement with 1,000 minutes"""
    num = den = 0.0
    for o in hist:
        w = {0: 5, 1: 4, 2: 3}.get(y - o['y'])
        if w and o['war'] is not None:
            num += w * o['war']
            den += w * o['tmin']
    return num / (den + 1000) * 1000


def ceil_inputs(a, hist):
    """ceiling inputs for one base season; hist includes it (scripts/nhl_ceiling_research.py)"""
    return {'s0': shr(a), 'mar': marcel(hist, a['y']), 'age': a['age'], 'age2': a['age'] ** 2,
            'lnm': math.log(max(a['tmin'], 1.0)), 'd': a['d'], 'toi': a['toi'], 'pps': a['pp'] / max(a['toi'], 1.0),
            'ev60': a['ev_p60']}


def career_sh(hist, y):
    """shooting % over the seasons before y, shrunk to the league's"""
    g = sum(o['g'] for o in hist if o['y'] < y)
    s = sum(o['shots'] for o in hist if o['y'] < y)
    return (g + 9.0) / (s + 100.0)


def vacated(Pa, Pb):
    """{pid: (share of his position group's minutes, share of the power-play minutes) on his team this season (Pa)
    played by others who are not on that team next season (Pb)}"""
    tot, gone = {}, {}
    left = {}
    for pid, o in Pa.items():
        nx = Pb.get(pid)
        left[pid] = nx is None or nx['tm'] != o['tm']
        for key, v in (((o['tm'], o['d']), o['tmin']), ((o['tm'], 'pp'), o['ppmin'])):
            tot[key] = tot.get(key, 0.0) + v
            if left[pid]:
                gone[key] = gone.get(key, 0.0) + v
    V = {}
    for pid, o in Pa.items():
        v = []
        for key, mine in (((o['tm'], o['d']), o['tmin']), ((o['tm'], 'pp'), o['ppmin'])):
            v.append((gone.get(key, 0.0) - (mine if left[pid] else 0.0)) / tot[key] if tot.get(key) else 0.0)
        V[pid] = tuple(v)
    return V


def depth(Pa):
    """{pid: [share of his club's position group ahead of him by TOI a game, minutes-weighted mean age of those ahead
    - 28, share of the minutes ahead of him held by team-mates aged 31+]}; team-mates with 20+ GP (per 82)"""
    G = {}
    for o in Pa.values():
        if o['tm'] and o['gp'] >= 20 * o['gmax'] / 82:
            G.setdefault((o['tm'], o['d']), []).append(o)
    out = {}
    for pid, a in Pa.items():
        g = G.get((a['tm'], a['d']), [])
        ah = [o for o in g if o['toi'] > a['toi'] and o['pid'] != pid]
        m = sum(o['tmin'] for o in ah)
        n = len([o for o in g if o['pid'] != pid])
        out[pid] = [len(ah) / n if n else 0.0, sum(o['age'] * o['tmin'] for o in ah) / m - 28 if m else 0.0,
                    sum(o['tmin'] for o in ah if o['age'] >= 31) / m if m else 0.0]
    return out


def ahead_gone(Pa, Pb):
    """{pid: [share of the minutes of same-group team-mates with more TOI a game that left the club, the same for the
    power-play minutes of team-mates with more PP TOI a game]}"""
    T = {}
    for o in Pa.values():
        if o['tm']:
            T.setdefault(o['tm'], []).append(o)
    left = {pid: (Pb.get(pid) is None or Pb[pid]['tm'] != o['tm']) for pid, o in Pa.items()}
    out = {}
    for pid, a in Pa.items():
        tm = T.get(a['tm'], [])
        ah = [o for o in tm if o['d'] == a['d'] and o['toi'] > a['toi']]
        pa = [o for o in tm if o['pp'] > a['pp']]
        m, q = sum(o['tmin'] for o in ah), sum(o['ppmin'] for o in pa)
        out[pid] = [sum(o['tmin'] for o in ah if left[o['pid']]) / m if m else 0.0,
                    sum(o['ppmin'] for o in pa if left[o['pid']]) / q if q else 0.0]
    return out


REC = 'https://records.nhl.com/site/api'


def coach_stints(fresh=False):
    """{team: [(first game, last game, coach)]} regular-season head-coach stints (records.nhl.com), cached"""
    path = os.path.join(CACHE, 'coaches.json')
    if os.path.exists(path) and not fresh:
        return D.load(path)
    fr, rec = D.get(f'{REC}/franchise'), D.get(f'{REC}/coach-franchise-records')
    if not fr or not rec:
        return D.load(path) if os.path.exists(path) else {}
    tri = {f['id']: D.team(f['teamAbbrev']) for f in fr['data']}
    out = {}
    for r in rec['data']:
        tm = tri.get(r['franchiseId'])
        if tm in D.TEAMS and r.get('gameTypeId') == 2 and r.get('firstCoachedDate') and r.get('lastCoachedDate'):
            out.setdefault(tm, []).append([r['firstCoachedDate'][:10], r['lastCoachedDate'][:10], r['coachName']])
    D.save(path, out)
    return out


def coach_changed(CS, tm, y):
    """1.0 when the club opens the season after y under a different head coach than it ended y with (None: unknown)"""
    end = '2020-03-12' if y == 2020 else f'{y}-04-30'
    start = {2012: '2013-02-05', 2020: '2021-02-01'}.get(y, f'{y}-11-01')
    st = CS.get(tm) or []
    a = [c for c in st if c[0] <= end]
    b = [c for c in st if c[0] <= start and c[1] >= f'{y}-09-01']
    if not a or not b:
        return None
    return 0.0 if max(a)[2] == max(b)[2] else 1.0


def trend(logs):
    """{pid: [TOI a game change (min), points a 60 change, shots a 60 change]}: the second half of his regular-season
    games minus the first, changes in the rates shrunk by GP / (GP + 40); 30+ GP"""
    by = {}
    for r in logs:
        if str(r[0])[4:6] == '02':
            by.setdefault(str(r[1]), []).append(r)
    out = {}
    for pid, g in by.items():
        if len(g) < 30:
            continue
        g.sort(key=lambda r: r[0])
        h = len(g) // 2
        v = []
        for part in (g[:h], g[h:]):
            sec = sum(r[5] for r in part) or 1.0
            v.append((sec / 60 / len(part), sum(r[6] + r[7] for r in part) / sec * 3600, sum(r[8] for r in part) / sec * 3600))
        k = len(g) / (len(g) + 40.0)
        out[pid] = [v[1][0] - v[0][0], (v[1][1] - v[0][1]) * k, (v[1][2] - v[0][2]) * k]
    return out


def bo_feats(a, hist, vac, ctx=None):
    """vac: (position-group share, power-play share) or None when next season's rosters are not known;
    ctx: {'depth', 'ahead', 'coach', 'trend'} values for this player-season (None = not known)"""
    ctx = ctx or {}
    s0, age, toi = shr(a), a['age'], a['toi']
    ref = 20.0 if a['d'] else 16.0
    low = max(0.0, ref - toi) / 4
    lm = math.log(a['tmin'])
    evc = a['ev_p60'] * a['evmin'] / (a['evmin'] + 300) - TARGETS['ev_p60']['mean'][int(a['d'])] * a['evmin'] / (a['evmin'] + 300)
    p60c = (a['p60'] - (0.9 if a['d'] else 1.8)) * a['tmin'] / (a['tmin'] + 400)
    ped = -math.log(a['pick'] or 250)
    hpm = a['hpm'] if a['hpm'] is not None else 0.0
    shn = a['shots'] / (a['shots'] + 100.0)
    return {'base': [s0, best(a, hist) - s0, lm, a['d']],
            'age curve': [age, age * age, age * s0],
            'low-TOI efficiency': [evc * low, toi - ref],
            'vacated TOI': list(vac) if vac else None,
            'shooting luck': [(a['shpct'] - career_sh(hist, a['y'])) * shn, a['oish'] - 0.085, a['pdo'] - 1.0],
            'projection gap': [marcel(hist, a['y']) - s0],
            'TOI room': [lm * s0, low * p60c],
            'TOI scaling': [a['sh60'] * low, a['pp'] / toi * low],
            'draft capital': [ped, ped * max(0.0, 25 - age)],
            'site HPM': [hpm, hpm * low],
            'shot share': [a['satrel'], a['satrel'] * low],
            'production': [p60c, evc],
            'development curve': [ped * (age - 24), ped * (age - 24) ** 2, age * a['d'], age * age * a['d']],
            'depth opportunity': ctx.get('depth'),
            'departures ahead': ctx.get('ahead'),
            'coaching change': [ctx['coach'], ctx['coach'] * low] if ctx.get('coach') is not None else None,
            'within-season trend': ctx.get('trend'),
            'experience': [math.log(1 + min(246, sum(o['gp'] for o in hist if o['y'] < a['y']))),
                           0.0 if any(o['y'] < a['y'] for o in hist) else 1.0],
            'offence / defence split': [a['go'] / (a['tmin'] + K_SHR) * 1000, a['gd'] / (a['tmin'] + K_SHR) * 1000]}


def hinges(a):
    """hinge terms for the spline form: age, shrunk WAR rate, TOI against the position's reference"""
    s0, t = shr(a), a['toi'] - (20.0 if a['d'] else 16.0)
    return ([max(0.0, a['age'] - k) for k in (22, 25, 28)] + [max(0.0, s0 - k) for k in (0, .4, .8)]
            + [max(0.0, t - k) for k in (-4, -2, 0)])


def bo_prob(fit, f, a=None):
    """(probability, [(signal, contribution)]) from the kept signals (+ the hinge terms when the fit carries them)"""
    B = fit['breakout']
    b, mu = B['fit']['b'], B['fit']['mu']
    x, groups = list(f['base']), [('base', len(f['base']))]
    for k in B['keep']:
        v = f[k]
        if v is None:
            i = len(x)
            v = mu[i:i + B['width'][k]]
        x += list(v)
        groups.append((k, len(v)))
    if B.get('splines'):
        x += hinges(a)
    eta = B['fit']['b0'] + sum(bi * xi for bi, xi in zip(b, x))
    con, i = [], 0
    for k, n in groups:
        if k != 'base':
            con.append((k, sum(b[j] * (x[j] - mu[j]) for j in range(i, i + n))))
        i += n
    return 1 / (1 + math.exp(-max(-30, min(30, eta)))), con


# ---------- live board ----------
TIERS = (15, 18, 21)


def logo(tm):
    """the team's logo path when the file is in the repo (as scripts/rookies.py)"""
    path = f'/img/nhl/{(tm or "").lower()}.png'
    return path if tm and os.path.exists(os.path.join(ROOT, 'static', path.lstrip('/'))) else None


def main():
    fit = json.load(open(FIT))
    cur = D.current_season()
    wf = war_file(cur)
    if not wf:
        cur -= 1
        wf = war_file(cur)
    half = (wf.get('games') or 0) >= 41
    y0 = cur if half else cur - 1
    P = {}
    for S in range(y0 - 6, cur + 1):
        try:
            for pid, o in season(S, fresh=S == cur).items():
                P[(pid, S)] = o
        except RuntimeError as e:
            print('nhl breakout:', e)
            if S >= y0:
                raise
    now = {pid: o for (pid, S), o in P.items() if S == cur}
    base = {pid: o for (pid, S), o in P.items() if S == y0}
    V = vacated(base, now) if y0 < cur else {}
    live = {str(p['id']): p for p in wf['players'] if p.get('grp') != 'G'}
    q99 = fit['scaling']['pp_toi']['du_q99']
    C, Lq = career(last=cur), fit['L']
    keep = fit['breakout']['keep']
    dp = depth(base)
    ag = ahead_gone(base, now) if y0 < cur else {}
    CS = coach_stints(fresh=True) if 'coaching change' in keep else {}
    tr = {}
    if 'within-season trend' in keep:
        try:
            tr = trend(D._logs('skater', y0, 2, y0 == cur))
        except Exception as e:
            print('nhl breakout: game logs skipped:', e)
    import ceiling as CE
    cf = json.load(open(CEIL))
    rows = []
    for pid, a in base.items():
        w = live.get(pid)
        if not w or a['war'] is None or a['tmin'] < ROW_MIN * a['gmax'] / 82:
            continue
        pk = peak(C, pid, cur)
        if pk is not None and pk >= Lq:   # already at the bar in a past season or this one to date
            continue
        hist = history(P, pid, y0)
        ctx = {'depth': dp.get(pid), 'ahead': ag.get(pid), 'coach': coach_changed(CS, a['tm'], y0),
               'trend': tr.get(pid, [0.0, 0.0, 0.0]) if tr else None}
        p, con = bo_prob(fit, bo_feats(a, hist, V.get(pid), ctx), a)
        c = now.get(pid)
        u = c['toi'] if c and c['gp'] >= 5 else a['toi']
        t = []
        for k in TIERS:
            pg, p60, _ = tier(fit, a, hist, k)
            t.append([round(pg * 82, 1), round(p60, 2), 1 if k - a['toi'] > q99 else 0])
        sig = [BO_LABEL[k] for k, v in sorted(con, key=lambda kv: -kv[1])[:2] if v > 0.05]
        ph = w.get('ph') or a.get('ph')
        tm = w.get('tm') or a['tm']
        rows.append({'id': pid, 'n': a['n'] or w.get('n'), 'tm': tm, 'pos': a['pos'], 'lo': logo(tm),
                     'age': round((c or a)['age'] + (0 if c else cur - y0), 1), 'ph': FACE % ph if ph else None,
                     'p': round(p, 3), 'best': round(pk, 2) if pk is not None else None, 'u': round(u, 1), 't': t, 'sig': sig,
                     'x': round(shr(c) if c and c.get('war') is not None else shr(a), 2),
                     'xc': round(CE.value(cf, ceil_inputs(a, hist),
                                          max(0.0, min(cf['scen'], cf['cap']['D' if a['d'] else 'F'] - a['toi']))), 2)})
    rows.sort(key=lambda r: -r['p'])
    rows = rows[:400]
    B, Sc = fit['breakout'], fit['scaling']
    lab = lambda S: f'{S - 1}-{S % 100:02d}'  # noqa: E731
    about = (f"Skaters with {int(ROW_MIN)}+ minutes in {lab(y0)} who have played in {lab(cur)} and have never reached the bar "
             f"(any season since 2008-09, {lab(cur)} to date included). Breakout: {fit['definition']} "
             f"Odds: logistic on shrunk WAR rate, gap to his best, ln minutes, D + {', '.join(B['keep'])}; held-out log loss "
             f"{B['final']['base']:.4f} -> {B['final']['cand']:.4f} (t {B['final']['t']}, {B['final']['won']}/"
             f"{B['final']['seasons']} seasons). Tiers: next-season even-strength and power-play points a 60 at the minutes "
             f"that ice time brings, fit on {Sc['ev_p60']['n']:,} season pairs; kept context: "
             + '; '.join(f"{k} {', '.join(v['keep']) or 'none'}" for k, v in Sc.items())
             + f". Tiers past the 99th percentile of rises seen (+{q99:.1f} min) are beyond the data. Goalies not included. "
             f"CEIL: 80th percentile of next-season shrunk WAR a 1,000 minutes with TOI +{cf['scen']:g} a game (cap {cf['cap']['F']} F, "
             f"{cf['cap']['D']} D) on 900+ minutes: shrunk WAR rate, Marcel, age, ln minutes, D + TOI change x age, TOI, D, WAR rate, "
             f"PP share, EV P/60, spread by age, minutes, TOI, D (held-out 80th-percentile loss t {cf['final']['t']}, {cf['final']['won']}/{cf['final']['seasons']} "
             f"seasons; {round(100 * cf['coverage']['up'])}% of TOI-up seasons under it). NHL stats API, site WAR (MoneyPuck).")
    out = {'sport': 'nhl', 'season': lab(cur), 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'base': lab(y0), 'u': {'lab': 'TOI', 'dec': 1},
           'tiers': [{'k': k, 'lab': f'TOI {k}'} for k in TIERS],
           'stat': {'lab': 'P/82', 'eff': 'P/60', 'dec': 0, 'edec': 2},
           'cur': {'lab': 'WAR/1k', 't': 'WAR a 1,000 minutes this season, shrunk to replacement by ice time (k 600)', 'dec': 2},
           'ceil': {'lab': 'CEIL', 't': 'ceiling WAR a 1,000 minutes (shrunk, like Best): 80th percentile season if TOI rises %g minutes a game' % cf['scen'],
                    'dec': 2},
           'about': about, 'rows': rows}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, len(rows), 'rows; top', [(r['n'], r['p']) for r in rows[:5]])


if __name__ == '__main__':
    main()
