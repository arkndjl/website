# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College football Potential Breakout ("next up" tab): breakout odds and contextual workload scaling for FBS
quarterbacks, backs, receivers, tight ends, edges, tackles and linebackers (static/data/next-up/cfb.json).
Model and held-out tests: scripts/cfb_breakout_research.py -> data/cfb_breakout_fit.json.

    python3 scripts/cfb_breakout.py             # PFN impact rankings (7 pages, cached) + the board + the fit; stdlib only
    python3 scripts/cfb_breakout.py --offline   # from the cached PFN pages only

Workload = opportunities a game: pass attempts (QB), carries + catches (RB), targets (WR, TE), snaps (EDGE, DT, LB).
Efficiency = yards per opportunity (pressures per snap for EDGE and DT, tackles per snap for LB). Value = PFN's impact
score at the position (the board's production driver), as a z on that season's regulars.

Feature columns live here so the research fit and the live board build them the same way."""
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FIT = os.path.join(ROOT, 'data', 'cfb_breakout_fit.json')
OUT = os.path.join(ROOT, 'static', 'data', 'next-up', 'cfb.json')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'cfb_breakout')
ALL = os.path.join(ROOT, 'static', 'data', 'cfb-all.json')
ALLTIME = os.path.join(ROOT, 'scripts', 'data', 'cfb_alltime_rows.json.gz')
RECRUITS = os.path.join(ROOT, 'scripts', 'data', 'cfb_recruits_cfbd.json.gz')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 '
      'Safari/537.36')

PAGES = {'QB': 'quarterback', 'RB': 'running-back', 'WR': 'wide-receiver', 'TE': 'tight-end', 'EDGE': 'edge',
         'DL': 'defensive-tackle', 'LB': 'linebacker'}
POS = list(PAGES)
OFF = ('QB', 'RB', 'WR', 'TE')
GROUP = {'QB': 'QB', 'RB': 'RB', 'WR': 'REC', 'TE': 'REC', 'EDGE': 'DLN', 'DL': 'DLN', 'LB': 'LB'}
# a regular: this many opportunities a game or more; a base row: this many opportunities in the season
T_REG = {'QB': 15, 'RB': 6, 'WR': 3, 'TE': 1.5, 'EDGE': 20, 'DL': 20, 'LB': 25}
MIN_OPP = {'QB': 40, 'RB': 30, 'WR': 15, 'TE': 10, 'EDGE': 100, 'DL': 100, 'LB': 100}
# opportunities at which a season's efficiency is half signal
K_EFF = {'QB': 150, 'RB': 80, 'WR': 50, 'TE': 35, 'EDGE': 250, 'DL': 250, 'LB': 250}
P4 = {'SEC', 'Big Ten', 'Big 12', 'ACC'}                 # plus the Pac-12 through 2023 and Notre Dame
NUM = (int, float)


def num(v, d=0.0):
    return float(v) if isinstance(v, NUM) and not isinstance(v, bool) and math.isfinite(v) else d


# ---------- PFN impact rankings ----------
def parse_pfn(html):
    chunks = [json.loads(m.group(1)) for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)]
    s = next(c for c in chunks if '"packed":' in c)
    d = json.JSONDecoder().raw_decode(s[s.index('"packed":') + 9:])[0]
    return [dict(zip(d['cols'], r)) for r in d['rows']]


def pfn(g, offline=False, max_age=6 * 3600):
    """one position's player-seasons, 2019 on (FBS and FCS); cached, and the cache is the fallback when PFN fails"""
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, f'pfn_{PAGES[g]}.json')
    fresh = os.path.exists(f) and time.time() - os.path.getmtime(f) < max_age
    if not offline and not fresh:
        try:
            req = urllib.request.Request(f'https://www.profootballnetwork.com/cfb-hq/impact-rankings/{PAGES[g]}',
                                         headers={'User-Agent': UA})
            rows = parse_pfn(urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace'))
            if len(rows) > 200:
                json.dump(rows, open(f, 'w'))
            time.sleep(1)
        except Exception as e:  # noqa: BLE001
            print(f'PFN {g}: {str(e)[:100]} (using the cache)')
    return json.load(open(f))


def record(g, r):
    """one PFN row -> a player-season with workload, efficiency and the raw profile stats (None when unusable)"""
    gp = num(r.get('gp')) or num(r.get('gamesQ'))
    td = 0.0
    prof = prof2 = recsh = lk = None
    if g == 'QB':
        opp, yds = num(r.get('att')), num(r.get('pyds'))
        td = num(r.get('ptd'))
        prof, prof2 = r.get('cmpPct'), (num(r.get('ryds')) / gp if gp else None)
        lk = (td - 2 * num(r.get('int'))) / opp if opp else None
    elif g == 'RB':
        car = num(r.get('ryds')) / r['ypc'] if num(r.get('ypc')) > 0 else 0.0
        opp, yds = car + num(r.get('rec')), num(r.get('ryds')) + num(r.get('recYds'))
        td = num(r.get('rtd')) + num(r.get('recTD'))
        prof, prof2 = r.get('elu'), r.get('boom')
        recsh = num(r.get('rec')) / opp if opp else None
        lk = td / opp if opp else None
    elif g in ('WR', 'TE'):
        opp, yds = num(r.get('tar')), num(r.get('recYds'))
        td = num(r.get('recTD'))
        prof, prof2 = r.get('catch'), r.get('yac')
        lk = td / opp if opp else None
    else:
        opp = num(r.get('snaps')) or num(r.get('snapsQ'))
        yds = num(r.get('prs')) if g != 'LB' else num(r.get('tkl'))
        if g != 'LB':
            prof = 100 * num(r.get('tfl')) / opp if opp else None
            prs = num(r.get('prs'))
            lk = (num(r.get('sk')) - 0.15 * prs) / (prs + 20)
        else:
            prof = 100 * num(r.get('prs')) / opp if opp else None
    if not gp or opp < MIN_OPP[g] or not isinstance(r.get('score'), NUM):
        return None
    team = r['team']
    return {'id': r['id'], 'n': r['name'], 'tm': team, 'conf': r.get('conf'), 'y': r['season'], 'g': g, 'gp': gp,
            'opp': opp, 'u': opp / gp, 'yds': yds, 'eff': yds / opp, 'score': float(r['score']),
            'rel': opp / (opp + K_EFF[g]), 'prof_raw': prof if isinstance(prof, NUM) else None,
            'prof2_raw': prof2 if isinstance(prof2, NUM) else None, 'recsh': recsh or 0.0,
            'lk_raw': lk if isinstance(lk, NUM) else None,
            'p4': 1.0 if (r.get('conf') in P4 or team == 'Notre Dame'
                           or (r.get('conf') == 'Pac-12' and r['season'] <= 2023)) else 0.0, 'sos': num(r.get('sos'))}


def load(offline=False, fbs=True):
    """{(id, season): record} for the seven positions; a player listed at two positions keeps the bigger workload"""
    P = {}
    for g in POS:
        for r in pfn(g, offline):
            if fbs and r.get('division') != 'FBS':
                continue
            o = record(g, r)
            if not o:
                continue
            k = (o['id'], o['y'])
            if k not in P or o['opp'] / K_EFF[g] > P[k]['opp'] / K_EFF[P[k]['g']]:
                P[k] = o
    return P


def season_norms(P):
    """per (position, season): means over the regulars (T_REG a game, half the season's games) of efficiency, score and
    the profile stats, and the median workload. Spreads are pooled over seasons in the fit json (sd_from)."""
    by = defaultdict(list)
    top = defaultdict(float)
    for o in P.values():
        top[o['y']] = max(top[o['y']], o['gp'])
    for o in P.values():
        if o['u'] >= T_REG[o['g']] and o['gp'] >= 0.5 * top[o['y']]:
            by[(o['g'], o['y'])].append(o)
    N = {}
    for (g, y), rs in by.items():
        if len(rs) < 20:
            continue
        w = [o['opp'] for o in rs]
        sw = sum(w)
        d = {'n': len(rs), 'eff': sum(a * o['eff'] for a, o in zip(w, rs)) / sw,
             'score': sum(o['score'] for o in rs) / len(rs),
             'u50': sorted(o['u'] for o in rs)[len(rs) // 2], 'gmax': top[y]}
        for k in ('prof_raw', 'prof2_raw', 'lk_raw'):
            v = [o[k] for o in rs if o[k] is not None]
            d[k] = sum(v) / len(v) if v else 0.0
        N[f'{g}|{y}'] = d
    return N


def sd_from(P, N):
    """pooled spread around each season's mean, by position"""
    acc = defaultdict(lambda: defaultdict(list))
    for o in P.values():
        n = N.get(f"{o['g']}|{o['y']}")
        if not n or o['u'] < T_REG[o['g']] or o['gp'] < 0.5 * n['gmax']:
            continue
        for k in ('eff', 'score', 'prof_raw', 'prof2_raw', 'lk_raw'):
            if o[k] is not None:
                acc[o['g']][k].append(o[k] - n[k])
    return {g: {k: (sum(x * x for x in v) / len(v)) ** 0.5 or 1.0 for k, v in d.items()} for g, d in acc.items()}


def standardize(P, N, SD):
    """adds ez (efficiency z), vz (score z), u0 (ln workload over the regulars' median), profile z's; drops players of
    a (position, season) with no norms"""
    out = {}
    for k, o in P.items():
        n, sd = N.get(f"{o['g']}|{o['y']}"), SD.get(o['g'])
        if not n or not sd:
            continue
        o['ez'] = (o['eff'] - n['eff']) / sd['eff']
        o['vz'] = (o['score'] - n['score']) / sd['score']
        o['u0'] = math.log(o['u'] / n['u50'])
        o['v'] = o['opp'] / n['u50']                       # games of a regular's workload
        for a, b in (('prof', 'prof_raw'), ('prof2', 'prof2_raw'), ('lk', 'lk_raw')):
            o[a] = max(-3.0, min(3.0, (o[b] - n[b]) / sd[b])) if o[b] is not None and sd.get(b) else 0.0
        o['lk'] *= o['rel']
        out[k] = o
    return out


def ht_in(h):
    if isinstance(h, NUM):
        return float(h)
    m = re.match(r'(\d)-(\d+)', h or '')
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


CLS_YRS = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4, 'Gr': 5}


def cls_years(c):
    """years in college from the board's class label (a redshirt adds one)"""
    if not c:
        return None
    rs = c.startswith('RS-')
    b = CLS_YRS.get(c[3:] if rs else c)
    return None if b is None else min(6, b + (1 if rs else 0))


def set_context(o, yrs=None, stars=None, ht=None, wt=None, size=None):
    """years in college, recruiting stars and frame (z at the position; 0 with a flag when unknown)"""
    o['yrs'], o['hasyrs'] = (float(min(yrs, 6)), 1.0) if yrs else (3.0, 0.0)
    o['stars'], o['unr'] = (float(stars), 0.0) if stars else (2.5, 1.0)
    o['htz'] = o['bmiz'] = o['hasfr'] = 0.0
    s = (size or {}).get(o['g'])
    if ht and wt and s:
        o['htz'] = max(-3, min(3, (ht - s['ht'][0]) / s['ht'][1]))
        o['bmiz'] = max(-3, min(3, (703.0 * wt / ht ** 2 - s['bmi'][0]) / s['bmi'][1]))
        o['hasfr'] = 1.0


def alltime_context():
    """{(PFN id, season): (years in college, stars)} from the all-time FV rows (the harness's own join)"""
    return {(r['id'], r['s']): (r.get('years'), r.get('stars')) for r in json.load(gzip.open(ALLTIME))}


class Recruits:
    """247 composite classes (CFBD's copy): stars and the listed height and weight as a recruit, by name through the
    shared matcher. A player is looked up with each of his teams; a name on no team of his must be the only one."""

    def __init__(self):
        import names as NM
        rows = []
        for y, v in json.load(gzip.open(RECRUITS)).items():
            for x in v:
                rows.append({'name': x[0], 'team': x[4], 'cls': int(y), 'stars': x[2], 'ht': x[5], 'wt': x[6]})
        own = os.path.join(ROOT, 'scripts', 'cfb_recruit_247.json')
        have = {r['cls'] for r in rows}
        if os.path.exists(own):                           # classes CFBD's copy lacks: composite rating only
            for y, v in json.load(open(own))['composite'].items():
                if int(y) not in have:
                    for x in v:
                        st = 5 if x[2] >= 0.983 else 4 if x[2] >= 0.89 else 3 if x[2] >= 0.797 else 2
                        rows.append({'name': x[0], 'team': None, 'cls': int(y), 'stars': st, 'ht': None, 'wt': None})
        self.m = NM.Matcher(rows)
        self.memo = {}

    def find(self, pid, name, teams, first):
        if pid not in self.memo:
            hit = None
            for t in teams:
                r, _ = self.m.find(name, team=t, cross_team='none')
                if r and first - 6 <= r['cls'] <= first:
                    hit = r
                    break
            if not hit:
                r, _ = self.m.find(name)
                if r and first - 6 <= r['cls'] <= first:
                    hit = r
            self.memo[pid] = hit
        return self.memo[pid]


def add_context(P, live=None, board=None, size=None):
    """years in college, stars and frame on every record. History: the all-time rows' years and stars; the live season:
    the board's class. Stars and frame fall back to the recruiting classes for both."""
    AT, RC = alltime_context(), Recruits()
    seen = defaultdict(list)
    for (pid, y), o in sorted(P.items(), key=lambda kv: kv[0][1]):
        seen[pid].append(o)
    for pid, hist in seen.items():
        rc = RC.find(pid, hist[0]['n'], list(dict.fromkeys(o['tm'] for o in hist)), hist[0]['y'])
        for o in hist:
            yrs, stars = AT.get((pid, o['y']), (None, None))
            if o['y'] == live:
                b = (board or {}).get(pid)
                yrs = cls_years(b.get('cls')) if b else None
            if not yrs:
                prev = AT.get((pid, o['y'] - 1), (None, None))[0]
                yrs = prev + 1 if prev else (o['y'] - rc['cls'] + 1 if rc else None)
            if not stars and rc:
                stars = rc['stars']
            o['_ht'], o['_wt'] = (rc['ht'], rc['wt']) if rc and rc['ht'] and rc['wt'] else (None, None)
            set_context(o, yrs, stars, o['_ht'], o['_wt'], size)
    return P


# ---------- A. workload scaling ----------
DUMS = {'off': ['isQB', 'isRB', 'isTE'], 'def': ['isEDGE', 'isLB']}
BASE = ['x0', 'x0*r0', 'r0', 'yrs', 'yrs2', 'u0', 'xprev', 'hasprev']
BLOCKS = {
    'position': {'off': ['isQB', 'isRB', 'isTE'], 'def': ['isEDGE', 'isLB']},
    'production profile': ['prof', 'prof2', 'recsh'],
    'frame': ['htz', 'bmiz', 'hasfr'],
    'recruiting grade': ['starc', 'unr'],
    'own history': ['own', 'xprevc'],
    'class': ['yrsc'],
    'low-volume rates': ['x0c', 'x0c_low'],
    'level': ['p4', 'sos'],
}


def block_traits(blk, side):
    t = BLOCKS[blk]
    return t[side] if isinstance(t, dict) else t


def columns(side):
    c = BASE + DUMS[side] + ['dU']
    for blk in BLOCKS:
        for t in block_traits(blk, side):
            c.append('dU*' + t)
            if t not in c:
                c.append(t)
    return c


def history(P, pid, y):
    return [P[(pid, s)] for s in range(y - 4, y + 1) if (pid, s) in P]


def own_slope(hist):
    """the player's own ln workload -> efficiency z slope across his seasons, shrunk toward 0"""
    if len(hist) < 2:
        return 0.0
    W = [o['rel'] for o in hist]
    sw = sum(W)
    mu = sum(w * o['u0'] for w, o in zip(W, hist)) / sw
    mx = sum(w * o['ez'] for w, o in zip(W, hist)) / sw
    sxy = sum(w * (o['u0'] - mu) * (o['ez'] - mx) for w, o in zip(W, hist))
    sxx = sum(w * (o['u0'] - mu) ** 2 for w, o in zip(W, hist))
    return sxy / (sxx + 0.5)


def scale_feats(a, hist, dU, side):
    prev = [o for o in hist if o['y'] < a['y'] and o['g'] == a['g']]
    x0 = a['ez']
    xprev = prev[-1]['ez'] if prev else x0
    low = max(0.0, -a['u0'])
    v = {'x0': x0, 'x0*r0': x0 * a['rel'], 'r0': a['rel'], 'yrs': a['yrs'], 'yrs2': a['yrs'] ** 2, 'u0': a['u0'],
         'xprev': xprev, 'hasprev': 1.0 if prev else 0.0, 'dU': dU,
         'prof': a['prof'], 'prof2': a['prof2'], 'recsh': a['recsh'], 'htz': a['htz'], 'bmiz': a['bmiz'],
         'hasfr': a['hasfr'], 'starc': a['stars'] - 3, 'unr': a['unr'],
         'own': own_slope([o for o in hist if o['g'] == a['g']]), 'xprevc': xprev - x0, 'yrsc': a['yrs'] - 2.5,
         'x0c': x0, 'x0c_low': x0 * low, 'p4': a['p4'], 'sos': a['sos'] / 10}
    for g in POS:
        v['is' + g] = 1.0 if a['g'] == g else 0.0
    cols = columns(side)
    for c in cols:
        if c.startswith('dU*'):
            v[c] = dU * v[c[3:]]
    return [v[c] for c in cols]


def predict(fit, side, a, hist, dU):
    f = fit['scaling'][side]['fit']
    x = dict(zip(columns(side), scale_feats(a, hist, dU, side)))
    return f['b0'] + sum(b * x[c] for b, c in zip(f['b'], f['cols']))


# ---------- B. breakout odds ----------
K_SHR, REP = 4.0, -1.0
L_PCT = 0.775        # the quality bar: this quantile of regulars' shrunk score z (set in the fit json as 'L')
BO_CANDS = ('class curve', 'low-volume efficiency', 'vacated workload', 'recruiting grade', 'projection gap',
            'finishing luck', 'workload room', 'workload scaling', 'frame', 'level')
BO_LABEL = {'class curve': 'class', 'low-volume efficiency': 'low-vol eff', 'vacated workload': 'open role',
            'recruiting grade': 'recruit', 'projection gap': 'proj gap', 'finishing luck': 'luck',
            'workload room': 'room', 'workload scaling': 'scales', 'frame': 'frame', 'level': 'level'}


def shr(vz, v):
    return (vz * v + REP * K_SHR) / (v + K_SHR)


def best(hist):
    """the best shrunk score z of his seasons so far (None with no season)"""
    return max((shr(o['vz'], o['v']) for o in hist), default=None)


def career(P, pid, y):
    """every season on file through y (the not-yet-broken-out test looks at all of them)"""
    return [o for (i, s), o in P.items() if i == pid and s <= y]


def marcel(hist, y):
    """3-season score z, weights 5/4/3 by workload games, shrunk to replacement with 6 games"""
    n = d = 0.0
    for o in hist:
        w = {0: 5, 1: 4, 2: 3}.get(y - o['y'])
        if w:
            n += w * o['vz'] * o['v']
            d += w * o['v']
    return (n + REP * 6 * 5) / (d + 6 * 5)


def bo_feats(a, s0, vac, mar):
    low = max(0.0, -a['u0'])
    lv = math.log(a['v'])
    yc = a['yrs'] - 2.5
    return {'base': [s0, lv] + [1.0 if a['g'] == g else 0.0 for g in POS[1:]],
            'class curve': [yc, yc * yc, yc * s0],
            'low-volume efficiency': [a['ez'] * a['rel'] * low, a['ez'] * a['rel']],
            'vacated workload': [vac, vac * low],
            'recruiting grade': [a['stars'] - 3, a['unr'], (a['stars'] - 3) * (1.0 if a['yrs'] <= 2 else 0.0)],
            'projection gap': [mar - s0],
            'finishing luck': [a['lk']],
            'workload room': [low, low * a['vz']],
            'workload scaling': [a['prof'] * low, a['prof2'] * low, a['recsh'] * low],
            'frame': [a['htz'], a['bmiz'], a['hasfr']],
            'level': [a['p4'], a['sos'] / 10, a['p4'] * low]}


def vacated(P, gone):
    """share of a team's workload in the player's position group held by teammates who leave. gone(o) -> the chance
    the player is off this team next season (0/1 in the fit, the board's exit odds live)"""
    tot, out = defaultdict(float), defaultdict(float)
    for o in P.values():
        k = (o['tm'], o['y'], GROUP[o['g']])
        tot[k] += o['opp']
        out[k] += o['opp'] * gone(o)
    V = {}
    for key, o in P.items():
        k = (o['tm'], o['y'], GROUP[o['g']])
        rest = tot[k] - o['opp']
        V[key] = (out[k] - o['opp'] * gone(o)) / rest if rest > 0 else 0.0
    return V


# ---------- improvement sweep: extra signal blocks, splines, trees (shared by the research fit and the live build) ----------
COACH = os.path.join(ROOT, 'scripts', 'data', 'coach_alltime_src.json.gz')
STAFF = os.path.join(ROOT, 'data', 'cfb_staff.json')
EXTRA = ('position class curve', 'recruit development', 'depth opportunity', 'coaching change', 'skill profile',
         'career to date')
BO_LABEL.update({'position class curve': 'pos curve', 'recruit development': 'recruit', 'depth opportunity': 'depth',
                 'coaching change': 'new staff', 'skill profile': 'profile', 'career to date': 'career'})


def _ck(n):
    import names as NM
    return NM.key(re.sub(r'\s*\(.*?\)', '', n or ''))


def staff_index(live=None, board_ids=None):
    """{(team key, season): (head coaches, offensive coordinators, defensive coordinators)} as name-key sets: the
    all-time coach rows, plus the live season from data/cfb_staff.json (board_ids: {team name: ESPN team id})"""
    import names as NM
    ST = {}
    for r in json.load(gzip.open(COACH))['cfb']['rows']:
        if r['y'] >= 2017:
            ST[(NM.team_key(r['t']), r['y'])] = ({_ck(c[0]) for c in r.get('cs') or []}, {_ck(c) for c in r.get('oc') or []},
                                                 {_ck(c) for c in r.get('dc') or []})
    if live and board_ids and os.path.exists(STAFF):
        teams = json.load(open(STAFF))['teams']
        for name, tid in board_ids.items():
            t = teams.get(str(tid))
            if not t:
                continue
            nm = lambda k: {_ck(x) for x in ((t.get(k) or {}).get('names') or [(t.get(k) or {}).get('name')]) if x}  # noqa: E731
            ST[(NM.team_key(name), live)] = (nm('hc'), nm('oc'), nm('dc'))
    return ST


def staff_feats(o, ST):
    import names as NM
    tk = NM.team_key(o['tm'])
    a, b = ST.get((tk, o['y'])), ST.get((tk, o['y'] - 1))
    if not a or not b or not a[0] or not b[0]:
        return [0.0, 0.0, 0.0]
    i = 1 if o['g'] in OFF else 2
    return [0.0 if a[0] & b[0] else 1.0, 1.0 if (a[i] and b[i] and not a[i] & b[i]) else 0.0, 1.0]


def depth(P):
    """who is ahead of him at his team and position group: count, the share held by those in year 4+, the returning
    ones' quality, his own share"""
    grp = defaultdict(list)
    for o in P.values():
        grp[(o['tm'], o['y'], GROUP[o['g']])].append(o)
    D = {}
    for key, o in P.items():
        g = grp[(o['tm'], o['y'], GROUP[o['g']])]
        tot = sum(x['opp'] for x in g)
        ah = [x for x in g if x['opp'] > o['opp']]
        back = [x for x in ah if x['yrs'] < 4]
        wb = sum(x['opp'] for x in back)
        D[key] = [min(len(ah), 4) / 4, sum(x['opp'] for x in ah if x['yrs'] >= 4) / tot,
                  sum(x['opp'] * x['vz'] for x in back) / wb if wb else 0.0, o['opp'] / tot]
    return D


def extra_feats(a, dep, stf, earlier, Lq):
    """the sweep's candidate blocks. earlier = his seasons on file before this one"""
    yc = a['yrs'] - 2.5
    sc = a['stars'] - 3
    top = best(earlier + [a])
    return {'position class curve': [yc if a['g'] == g else 0.0 for g in POS[1:]],
            'recruit development': [sc, a['unr'], sc * yc, sc * yc * yc, a['unr'] * yc],
            'depth opportunity': list(dep),
            'coaching change': list(stf),
            'skill profile': [a['prof'], a['prof2'], a['recsh']],
            'career to date': [0.0 if earlier else 1.0, math.log(1 + sum(o['v'] for o in earlier)), Lq - top]}


SPLINE = ('s0', 'lnv', 'yc', 'gap')


def spline_raw(a, s0, mar):
    return [s0, math.log(a['v']), a['yrs'] - 2.5, mar - s0]


def hinges(raw, knots):
    """piecewise-linear terms: max(0, x - knot) for each top feature's knots"""
    return [max(0.0, x - k) for x, ks in zip(raw, knots) for k in ks]


def tree_score(trees, x):
    """sum of the leaf values of serialized depth-limited trees: node = [feature, threshold, left, right] or [leaf]"""
    s = 0.0
    for t in trees:
        n = t
        while len(n) == 4:
            n = n[2] if x[n[0]] <= n[1] else n[3]
        s += n[0]
    return s


def recal(p, cal):
    """the shipped recalibration: Platt (a + b logit p) or isotonic knots, or nothing"""
    if not cal:
        return p
    if cal['kind'] == 'platt':
        p = min(max(p, 1e-6), 1 - 1e-6)
        return 1 / (1 + math.exp(-(cal['a'] + cal['b'] * math.log(p / (1 - p)))))
    xs, ys = cal['x'], cal['y']
    if p <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if p <= xs[i]:
            return ys[i - 1] + (ys[i] - ys[i - 1]) * (p - xs[i - 1]) / ((xs[i] - xs[i - 1]) or 1)
    return ys[-1]


# ---------- live build ----------
def main():
    import names as NM
    offline = '--offline' in sys.argv
    fit = json.load(open(FIT))
    P = load(offline)
    live = max(y for _, y in P)
    N = dict(fit['norms'])
    N.update({k: v for k, v in season_norms(P).items() if k.endswith(f'|{live}')})
    P = standardize(P, N, fit['sd'])
    d = json.load(open(ALL))
    board = [dict(zip(d['cols'], r)) for r in d['rows']]
    board = [r for r in board if r.get('div') == 'FBS']
    M = NM.Matcher(board)
    bmap = {}
    for (pid, y), o in P.items():
        if y == live:
            o['b'], _ = M.find(o['n'], team=o['tm'], pos=o['g'], cross_team='none')
            if o['b']:
                bmap[pid] = o['b']
    add_context(P, live, bmap, fit['size'])
    cur = {k: o for k, o in P.items() if k[1] == live}

    def gone(o):
        b = o.get('b')
        if not b:
            return 0.5
        if isinstance(b.get('stayP'), NUM):
            return 1 - b['stayP']
        return 1.0 if (b.get('cls') or '').endswith(('Sr', 'Gr')) else 0.25
    V = vacated(cur, gone)
    by_id = defaultdict(list)
    for (pid, y), o in P.items():
        by_id[pid].append(o)
    bo = fit['breakout']
    keep, fb = bo['keep'], bo['fit']
    fb.setdefault('form', 'logistic')
    fb.setdefault('extra', [])
    D = depth(cur)
    ST = staff_index(live, {o['tm']: re.search(r'/(\d+)\.png', o['b'].get('logo') or '/0.png').group(1)
                            for o in cur.values() if o.get('b')})
    tiers = fit['tiers']
    rows = []
    for key, o in cur.items():
        b = o.get('b')
        if not b or (b.get('cls') or '').endswith('Gr') or b.get('cls') in ('Sr', 'RS-Sr'):
            continue                                      # no board row, or out of eligibility after this season
        if o['u0'] < bo['u0_min'][o['g']]:
            continue                                      # a workload smaller than any the fit has seen at the position
        hist = history(P, o['id'], live)
        top = best(by_id[o['id']])
        if top >= bo['L']:
            continue                                      # already at the quality bar this season or an earlier one
        s0, mar = shr(o['vz'], o['v']), marcel(hist, live)
        f = bo_feats(o, s0, V[key], mar)
        f.update(extra_feats(o, D[key], staff_feats(o, ST), [x for x in by_id[o['id']] if x['y'] < live], bo['L']))
        blocks = keep + fb['extra']
        x = f['base'] + sum([f[k] for k in blocks], [])
        if fb['form'].startswith('trees'):
            if fb.get('all_columns'):
                x = f['base'] + sum([f[k] for k in keep + list(EXTRA) + [c for c in BO_CANDS if c not in keep]], [])
            p, sig = 1 / (1 + math.exp(-(fb['f0'] + tree_score(fb['trees'], x)))), []
        else:
            if fb.get('knots'):
                x = x + hinges(spline_raw(o, s0, mar), fb['knots'])
            p = 1 / (1 + math.exp(-(fb['b0'] + sum(c * v for c, v in zip(fb['b'], x)))))
            parts, i = [], len(f['base'])
            for k in blocks:
                n = len(f[k])
                parts.append((sum(c * (v - m) for c, v, m in zip(fb['b'][i:i + n], f[k], fb['mu'][i:i + n])), k))
                i += n
            sig = list(dict.fromkeys(BO_LABEL[k] for c, k in sorted(parts, reverse=True)[:2] if c > 0.1))
        p = recal(p, fb.get('cal'))
        side = 'off' if o['g'] in OFF else 'def'
        t = []
        sc = fit['scaling'].get(side)
        n = N[f"{o['g']}|{live}"]
        for pct in tiers['pct']:
            if side != 'off' or not sc or not sc.get('ship'):
                t.append(None)
                continue
            uk = tiers['u'][o['g']][str(pct)]
            dU = math.log(uk / o['u'])
            ez = predict(fit, side, o, hist, dU)
            eff = max(0.0, n['eff'] + fit['sd'][o['g']]['eff'] * ez)
            t.append([round(uk * eff, 1), round(eff, 2), 1 if (dU > sc['du99'] or dU < sc['du01']) else 0])
        m = re.search(r'/id/(\d+)', b.get('espnl') or '')
        ph = b.get('photo')
        if ph == 1:
            ph = f'https://a.espncdn.com/i/headshots/college-football/players/full/{m.group(1)}.png' if m else None
        rows.append({'id': m.group(1) if m else o['id'], 'n': b['name'], 'tm': b['team'],
                     'pos': 'DT' if o['g'] == 'DL' else o['g'], 'age': b.get('age') or b.get('ageEst'),
                     'ph': ph or None, 'lo': b.get('logo'), 'sub': b.get('conf') or '', 'cls': b.get('cls'),
                     'p': round(p, 3), 'best': round(top, 2), 'u': round(o['u'], 1), 't': t, 'sig': sig,
                     'st': None if o.get('unr') else o.get('stars')})   # status for next up EDGE (scripts/next_up_status_research.py)
    rows.sort(key=lambda r: -r['p'])
    rows = rows[:400]
    sc = fit['scaling']['off']
    ship = sc.get('ship')
    out = {'sport': 'cfb', 'season': f'{live}', 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'base': str(live), 'u': {'lab': 'OPP/G', 'dec': 1},
           'tiers': [{'k': p, 'lab': f'P{p}'} for p in tiers['pct']] if ship else [],
           'stat': {'lab': 'YDS/G', 'eff': 'Y/OPP', 'dec': 1, 'edec': 2},
           'about': fit['about'], 'rows': rows}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, len(rows), 'rows; top:', [(r['n'], r['pos'], r['p']) for r in rows[:8]])


if __name__ == '__main__':
    main()
