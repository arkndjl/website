#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball Potential Breakout ("next up" tab): breakout odds and contextual usage scaling for every
returning D-I player (static/data/next-up/cbb.json). Model and held-out tests: scripts/cbb_breakout_research.py ->
data/cbb_breakout_fit.json, which also freezes last season's lines (scripts/data/cbb_breakout_base.json.gz).

    python3 scripts/cbb_breakout.py            # build from static/data/cbb-all.json + the fit + the base; stdlib only

Feature columns live here so the research fit and the live board build them the same way."""
import datetime as dt
import gzip
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

FIT = os.path.join(ROOT, 'data', 'cbb_breakout_fit.json')
BASEF = os.path.join(HERE, 'data', 'cbb_breakout_base.json.gz')
BOARD = os.path.join(ROOT, 'static', 'data', 'cbb-all.json')
OUT = os.path.join(ROOT, 'static', 'data', 'next-up', 'cbb.json')
BASE_YEAR = 2026          # the season the odds are built on (2026 = 2025-26)
TIERS = (20, 25, 30)

# a season line: the columns kept from the Barttorvik research table (floats unless named in TEXT)
KEEP = ('pid', 'name', 'team', 'conf', 'role', 'year', 'cls', 'gp', 'min_per', 'usg', 'ts', 'to', 'ast', 'orb', 'ftr',
        'tpar', 'rimr', 'midr', 'dunkr', 'ft_shr', 'tp_shr', 'twop_shr', 'tp_raw', 'ft_raw', 'tpa40', 'hti', 'hgt_role',
        'age', 'big', 'guard', 'bpm', 'obpm', 'rg_lrk', 'unranked2', 'pts40', 'stl', 'blk')
TEXT = {'pid', 'name', 'team', 'conf', 'role'}
# a missing value takes the D-I middle (20%+ of minutes, 2010 on); age falls back on the class
FILL = {'usg': 18.9, 'ts': 53.0, 'to': 18.1, 'ast': 10.7, 'orb': 4.4, 'ftr': 33.3, 'tpar': 0.35, 'rimr': 0.35,
        'midr': 0.26, 'dunkr': 0.015, 'ft_shr': 0.72, 'tp_shr': 0.33, 'twop_shr': 0.48, 'tp_raw': 0.33, 'ft_raw': 0.70,
        'tpa40': 3.8, 'hti': 77.0, 'hgt_role': 0.0, 'big': 0.0, 'guard': 0.0, 'bpm': -2.0, 'obpm': -1.0,
        'rg_lrk': -6.2146, 'unranked2': 1.0, 'pts40': 13.3, 'stl': 1.7, 'blk': 1.2, 'cls': 2.0, 'gp': 0.0, 'min_per': 0.0}
AGE_CLS = {1: 19.4, 2: 20.6, 3: 21.7, 4: 22.8}


def line(r):
    """a research-table row (strings) -> a season line"""
    o = {}
    for k in KEEP:
        v = r.get(k)
        if k in TEXT:
            o[k] = v or ''
            continue
        try:
            v = float(v)
            if v != v:
                v = None
        except (TypeError, ValueError):
            v = None
        o[k] = v
    o['y'] = int(o.pop('year'))
    for k, f in FILL.items():
        if o[k] is None:
            o[k] = f
    o['cls'] = int(o['cls'])
    if o['age'] is None:
        o['age'] = AGE_CLS.get(o['cls'], 21.0)
    o['m'] = o['min_per']
    return o


# ---------- usage scaling ----------
TARGETS = ('ts', 'to')
MEAN = {'ts': 53.0, 'to': 18.5}
BASE = ['x0', 'x0*r0', 'r0', 'age', 'age2', 'u0', 'xprev', 'hasprev']
BLOCKS = {
    'shot profile': ['rimr', 'midr', 'tpar', 'ftr', 'dunkr', 'ft_shr', 'twop_shr', 'tp_shr'],
    'role': ['ast', 'orb', 'big', 'guard', 'to0'],
    'frame': ['hti', 'hgt_role'],
    'past usage history': ['own', 'xprevc'],
    'age and class': ['agec', 'fr', 'so'],
    'low-usage rates': ['x0c', 'x0c_lowu'],
    'level of competition': ['lvl', 'dlvl', 'xfer'],
}
HIST_M = 15.0      # min% a past season needs to count in a player's own history


def columns(tgt=None):
    return BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in tr], []) for tr in BLOCKS.values()], [])


def history(P, pid, y):
    return [P[(pid, s)] for s in range(y - 6, y + 1) if (pid, s) in P]


def own_slope(hist, tgt):
    """the player's own usage -> rate slope across his seasons (15%+ of minutes), shrunk toward 0"""
    h = [o for o in hist if o['m'] >= HIST_M]
    if len(h) < 2:
        return 0.0
    W = [o['m'] / 50 for o in h]
    sw = sum(W)
    mu = sum(w * o['usg'] for w, o in zip(W, h)) / sw
    mx = sum(w * o[tgt] for w, o in zip(W, h)) / sw
    sxy = sum(w * (o['usg'] - mu) * (o[tgt] - mx) for w, o in zip(W, h))
    sxx = sum(w * (o['usg'] - mu) ** 2 for w, o in zip(W, h))
    return sxy / (sxx + 20.0)


def trait_vals(tgt, a, hist, lv):
    """lv = (his team's level this season, his next team's level this season, 1 if he changes teams); level = the
    team's minutes-weighted BPM"""
    x0 = a[tgt]
    prev = [o for o in hist if o['y'] < a['y'] and o['m'] >= HIST_M]
    xprev = prev[-1][tgt] if prev else x0
    lowu = max(0.0, 20 - a['usg']) / 10
    lvl, nlvl, xfer = lv
    return {
        'rimr': a['rimr'], 'midr': a['midr'], 'tpar': a['tpar'], 'ftr': a['ftr'], 'dunkr': a['dunkr'],
        'ft_shr': a['ft_shr'], 'twop_shr': a['twop_shr'], 'tp_shr': a['tp_shr'],
        'ast': a['ast'], 'orb': a['orb'], 'big': a['big'], 'guard': a['guard'], 'to0': a['to'],
        'hti': a['hti'], 'hgt_role': a['hgt_role'], 'own': own_slope(hist, tgt), 'xprevc': xprev - x0,
        'agec': a['age'] - 21, 'fr': 1.0 if a['cls'] == 1 else 0.0, 'so': 1.0 if a['cls'] == 2 else 0.0,
        'x0c': x0 - MEAN[tgt], 'x0c_lowu': (x0 - MEAN[tgt]) * lowu,
        'lvl': lvl, 'dlvl': nlvl - lvl, 'xfer': float(xfer),
        '_xprev': xprev, '_has': 1.0 if prev else 0.0,
    }


def features(tgt, a, hist, lv, dU):
    t = trait_vals(tgt, a, hist, lv)
    x0, r0, age = a[tgt], a['m'] / (a['m'] + 40.0), a['age']
    v = {'x0': x0, 'x0*r0': x0 * r0, 'r0': r0, 'age': age, 'age2': age * age, 'u0': a['usg'],
         'xprev': t['_xprev'], 'hasprev': t['_has'], 'dU': dU}
    for tr in BLOCKS.values():
        for k in tr:
            v[k] = t[k]
            v['dU*' + k] = dU * t[k]
    return v


def predict(sfit, tgt, a, hist, lv, dU):
    f = sfit[tgt]['fit']
    x = features(tgt, a, hist, lv, dU)
    return f['b0'] + sum(b * x[c] for b, c in zip(f['b'], f['cols']))


def pts40(K, usg, ts, to):
    """points a 40 from usage, TS% and TO%: K x usage share x 2 TS x (1 - TO share)"""
    return K * usg / 100 * 2 * ts / 100 * (1 - to / 100)


# ---------- team context: level, vacated and incoming usage ----------
def team_tables(lines_y, next_team):
    """lines_y: one season's lines; next_team: pid -> the team he plays for next season (absent = gone).
    Returns {team: {'lvl', 'vac', 'inc'}}: minutes-weighted BPM, share of the team's usage-minutes that left,
    usage-minutes of arriving transfers over the team's own"""
    tot, gone, bw, mw, inc = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
    for o in lines_y:
        um = o['usg'] * o['m']
        tot[o['team']] += um
        bw[o['team']] += o['bpm'] * o['m']
        mw[o['team']] += o['m']
        nt = next_team.get(o['pid'])
        if nt != o['team']:
            gone[o['team']] += um
            if nt:
                inc[nt] += um
    return {t: {'lvl': bw[t] / mw[t] if mw[t] else -1.5, 'vac': gone[t] / tot[t] if tot[t] else 0.45,
                'inc': inc[t] / tot[t] if tot[t] else 0.25} for t in tot}


NO_TEAM = {'lvl': -1.5, 'vac': 0.45, 'inc': 0.25}


# ---------- breakout odds ----------
K_SHR, BPM_REP = 10.0, -2.0       # BPM shrunk to replacement by 10 points of min%
ROLE_M = 40.0                     # a real role: 40%+ of team minutes
BAR_PCT = 80                      # the quality bar L: this percentile of shrunk BPM among real-role seasons (in the fit json)
# breakout: next season at or over L (shrunk BPM) with a real role, for a player with no season at or over L so far
BO_CANDS = ('age curve', 'class year', 'low-volume efficiency', 'vacated usage', 'incoming talent', 'recruiting gap',
            'shooting luck', 'projection gap', 'minutes room', 'transfer level', 'usage scaling')
BO_LABEL = {'age curve': 'age', 'class year': 'class', 'low-volume efficiency': 'low-vol eff',
            'vacated usage': 'open usage', 'incoming talent': 'thin arrivals', 'recruiting gap': 'pedigree',
            'shooting luck': 'shot luck', 'projection gap': 'proj gap', 'minutes room': 'min room',
            'transfer level': 'level', 'usage scaling': 'scales'}


def shr(bpm, m):
    return (bpm * m + BPM_REP * K_SHR) / (m + K_SHR)


def marcel(hist, y):
    """3-season BPM, weights 5/4/3 by min%, shrunk to replacement with 40 points of min%"""
    num = den = 0.0
    for o in hist:
        w = {0: 5, 1: 4, 2: 3}.get(y - o['y'])
        if w:
            num += w * o['bpm'] * o['m']
            den += w * o['m']
    return (num + BPM_REP * 5 * 40) / (den + 5 * 40)


def level(a, hist):
    """(his best shrunk BPM so far, any role; this season's shrunk BPM). Best at or over the bar = already broken out"""
    cur = shr(a['bpm'], a['m'])
    return max([cur] + [shr(o['bpm'], o['m']) for o in hist if o['y'] < a['y']]), cur


def broke_out(o, bar):
    return o['m'] >= ROLE_M and shr(o['bpm'], o['m']) >= bar


def bo_feats(a, s0, cur, mar, ctx, scal):
    """s0 = his best shrunk BPM so far, cur = this season's; ctx: {'vac', 'inc', 'top' (top-100 freshmen arriving), 'lvl', 'nlvl', 'xfer'} for the team he plays for next
    season; scal = the scaling fit's TS% change for +6 usage"""
    age, usg, ts, m = a['age'], a['usg'], a['ts'], a['m']
    lowu = max(0.0, 20 - usg) / 10
    lm = math.log(max(m, 1.0))
    tpw = min(1.0, a['tpa40'] * m / 100 / 2.5)          # 3PA volume, 0-1
    gap3 = a['tp_raw'] - (0.335 + 0.35 * (a['ft_raw'] - 0.70))
    dl = ctx['nlvl'] - ctx['lvl']
    return {'base': [s0, lm],
            'age curve': [age, age * age, age * s0],
            'class year': [1.0 if a['cls'] == 1 else 0.0, 1.0 if a['cls'] == 2 else 0.0],
            'low-volume efficiency': [(ts - MEAN['ts']) * lowu, usg],
            'vacated usage': [ctx['vac'], ctx['vac'] * (m < ROLE_M)],
            'incoming talent': [ctx['inc'], ctx['top']],
            'recruiting gap': [a['rg_lrk'], a['unranked2'], (a['rg_lrk'] + 6.2146) * (a['cls'] <= 2)],
            'shooting luck': [gap3 * tpw, a['ft_raw'] - 0.70],
            'projection gap': [mar - s0, cur - s0],
            'minutes room': [lm * s0, (m < ROLE_M) * a['obpm']],
            'transfer level': [float(ctx['xfer']), max(dl, 0.0), min(dl, 0.0)],
            'usage scaling': [scal, scal * lowu]}


# ---------- the improvement sweep's signals (scripts/cbb_breakout_sweep.py) ----------
BO_EXTRA = ('dev curve by pedigree', 'dev curve by archetype', 'depth opportunity', 'coaching change', 'box profile',
            'team context')
BO_LABEL.update({'dev curve by pedigree': 'pedigree x age', 'dev curve by archetype': 'archetype',
                 'depth opportunity': 'depth', 'coaching change': 'new coach', 'box profile': 'box profile',
                 'team context': 'team level'})


def group(a):
    return 'g' if a['guard'] else 'b' if a['big'] else 'w'


def depth_tables(lines_y, next_team):
    """pid -> [players ahead of him in his position group on next season's team, ahead of him on the whole team,
    min% / 100 of the position-group players ahead, min% / 100 played ahead of him in his group this season by
    teammates who are not back]. Ahead = a higher shrunk BPM this season; players known to be there = returners and
    arriving transfers with 10%+ of minutes this season"""
    by_next, by_team = defaultdict(list), defaultdict(list)
    for o in lines_y:
        if o['m'] >= 10:
            by_team[o['team']].append(o)
            if next_team.get(o['pid']):
                by_next[next_team[o['pid']]].append(o)
    out = {}
    for o in lines_y:
        nt = next_team.get(o['pid'])
        if not nt:
            continue
        v, g = shr(o['bpm'], o['m']), group(o)
        ah = [q for q in by_next[nt] if q['pid'] != o['pid'] and shr(q['bpm'], q['m']) > v]
        ap = [q for q in ah if group(q) == g]
        gone = [q for q in by_team[o['team']] if q['pid'] != o['pid'] and group(q) == g
                and shr(q['bpm'], q['m']) > v and next_team.get(q['pid']) != o['team']]
        out[o['pid']] = [float(len(ap)), float(len(ah)), sum(q['m'] for q in ap) / 100, sum(q['m'] for q in gone) / 100]
    return out


def bo_extra(a, cur, ctx, dep, newcoach):
    agec, rgc, ht = a['age'] - 21, a['rg_lrk'] + 6.2146, a['hti'] - 77
    fr = 1.0 if a['cls'] == 1 else 0.0
    return {'dev curve by pedigree': [agec * rgc, agec * agec * rgc, fr * rgc],
            'dev curve by archetype': [a['big'], a['guard'], agec * a['big'], agec * a['guard'], ht, agec * ht],
            'depth opportunity': list(dep),
            'coaching change': [float(newcoach), float(newcoach) * (1 - ctx['xfer'])],
            'box profile': [a['stl'], a['blk'], a['orb'], a['ast'], a['bpm'] - a['obpm']],
            'team context': [ctx['lvl'], ctx['lvl'] * (a['m'] < ROLE_M), cur - ctx['lvl']]}


NO_DEP = [0.0, 0.0, 0.0, 0.0]


def bo_row(a, hist, ctx, sfit, keep):
    s0, cur = level(a, hist)
    lv = (ctx['lvl'], ctx['nlvl'], ctx['xfer'])
    scal = predict(sfit, 'ts', a, hist, lv, 6.0) - predict(sfit, 'ts', a, hist, lv, 0.0)
    f = bo_feats(a, s0, cur, marcel(hist, a['y']), ctx, scal)
    return f, sum([f['base']] + [f[k] for k in keep], [])


def leaf(nodes, x):
    """one serialized tree ([feature, threshold, left, right] or [-1, value]) on a feature row: x <= threshold goes left"""
    i = 0
    while nodes[i][0] != -1:
        i = nodes[i][2] if x[nodes[i][0]] <= nodes[i][1] else nodes[i][3]
    return nodes[i][1]


def interp(p, kx, kv):
    if p <= kx[0]:
        return kv[0]
    for i in range(1, len(kx)):
        if p <= kx[i]:
            return kv[i - 1] + (kv[i] - kv[i - 1]) * (p - kx[i - 1]) / ((kx[i] - kx[i - 1]) or 1.0)
    return kv[-1]


# ---------- live build ----------
def board_rows():
    d = json.load(open(BOARD))
    C = d['cols']
    return [dict(zip(C, r)) for r in d['rows']]


def top100(rec):
    rk = [rec[k] for k in ('on3rk', 'rk247') if rec and rec.get(k)]
    return bool(rk) and sum(-math.log(max(r, 1)) for r in rk) / len(rk) >= -math.log(100)


def main():
    import names as N
    fit = json.load(open(FIT))
    base = json.load(gzip.open(BASEF, 'rt'))
    P = {(o['pid'], o['y']): o for o in base['lines']}
    cur = [o for o in base['lines'] if o['y'] == BASE_YEAR]
    by_key = defaultdict(list)
    for o in cur:
        by_key[N.key(o['name'])].append(o)
    by_team = defaultdict(list)
    for o in cur:
        by_team[o['team']].append(o)
    rows = board_rows()
    label = f'{BASE_YEAR - 1}-{str(BASE_YEAR)[2:]}'
    # the board's team -> its Barttorvik name (the name this season's and last season's lines carry)
    vote = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r.get('now') and r['now'].get('team'):
            vote[r['team']][r['now']['team']] += 3
        elif r.get('last') and r['last'].get('season') == label and not r.get('new'):
            vote[r['team']][r['last']['team']] += 1
    bteams = {N.team_key(t): t for t in by_team}
    bt_of = {}
    for t in {r['team'] for r in rows}:
        v = vote.get(t)
        bt_of[t] = max(v, key=v.get) if v else bteams.get(N.team_key(t))
    # each board player with a line last season -> that line (same name by the shared matcher, same team last season)
    match, used = [], set()
    for r in rows:
        L = r.get('last')
        if not L or L.get('season') != label:
            continue
        c = [o for o in by_key.get(N.key(r['name']), []) if o['team'] == L['team']]
        if not c:
            c = [o for o in by_team.get(L['team'], []) if N.same(o['name'], r['name'])]
        c = [o for o in c if o['pid'] not in used]
        if len(c) > 1:
            c = sorted(c, key=lambda o: abs(o['usg'] - (L.get('usg') or 0)))[:1]
        if c:
            used.add(c[0]['pid'])
            match.append((r, c[0]))
    next_team = {o['pid']: bt_of.get(r['team']) or r['team'] for r, o in match}
    T = team_tables(cur, next_team)
    tops = defaultdict(int)
    for r in rows:
        if r.get('cls') == 'Fr' and r.get('new') and top100(r.get('rec')):
            tops[bt_of.get(r['team']) or r['team']] += 1
    sfit, bfit = fit['scaling'], fit['breakout']
    keep, K, dmax = bfit['keep'], fit['K'], fit['dU_p99']
    # the improvement sweep's shipped model when it has run (extra signals, hinge terms, recalibration), else the kept logistic
    sw = bfit.get('sweep') or {}
    extra = sw.get('extra') or []
    mfit = sw.get('fit') or bfit['fit']
    b0, bb, mu = mfit['b0'], mfit['b'], mfit['mu']
    spline = mfit.get('spline') or []
    zero = {'vac': 0, 'inc': 0, 'top': 0, 'lvl': 0, 'nlvl': 0, 'xfer': 0}
    width = {**{k: len(v) for k, v in bo_feats(cur[0], 0.0, 0.0, 0.0, zero, 0.0).items()},
             **{k: len(v) for k, v in bo_extra(cur[0], 0.0, zero, NO_DEP, 0.0).items()}}
    spans, i = {}, 2
    for k in keep + extra:
        spans[k] = (i, i + width[k])
        i += width[k]
    DEP = depth_tables(cur, next_team)
    out, bar, done = [], bfit['L'], 0
    for r, a in match:
        if a['m'] < fit['min_m'] or a['gp'] < fit['min_gp']:
            continue
        # already broken out: a past season, or this season to date (shrunk by its share of a 31-game season), at the bar
        now = r.get('now') or {}
        m_now = (now.get('mpg') or 0) / 40 * 100 * min(1.0, (now.get('gp') or 0) / 31)
        best = level(a, history(P, a['pid'], a['y']))[0]
        if now.get('bpm') is not None:
            best = max(best, shr(now['bpm'], m_now))
        if best >= bar:
            done += 1
            continue
        nt = next_team[a['pid']]
        here, there = T.get(a['team'], NO_TEAM), T.get(nt, NO_TEAM)
        ctx = {'vac': there['vac'], 'inc': there['inc'], 'top': float(tops.get(nt, 0)), 'lvl': here['lvl'],
               'nlvl': there['lvl'], 'xfer': 1.0 if nt != a['team'] else 0.0}
        hist = history(P, a['pid'], a['y'])
        _, x = bo_row(a, hist, ctx, sfit, keep)
        if extra:
            # a first-year head coach is not in the live inputs: the coaching-change signal did not ship
            e = bo_extra(a, shr(a['bpm'], a['m']), ctx, DEP.get(a['pid'], NO_DEP), 0.0)
            x = x + sum([e[k] for k in extra], [])
        x = x + [max(0.0, x[j] - kn) for j, ks in spline for kn in ks]
        if sw.get('gbt'):
            z = sw['gbt']['f0'] + sum(leaf(t, x) for t in sw['gbt']['trees'])
        else:
            z = b0 + sum(b * v for b, v in zip(bb, x))
        z = max(-30, min(30, z))
        if sw.get('platt'):
            z = sw['platt'][0] + sw['platt'][1] * z
        p = 1 / (1 + math.exp(-z))
        if sw.get('isotonic'):
            p = interp(p, *sw['isotonic'])
        push = sorted(((sum(bb[j] * (x[j] - mu[j]) for j in range(*spans[k])), k) for k in keep + extra), reverse=True)
        sig = [('usage' if k == 'low-volume efficiency' and a['usg'] >= 20 else BO_LABEL[k]) for v, k in push[:2] if v > 0.1]
        u_now = now.get('usg') if (now.get('gp') or 0) >= 2 else None
        u = u_now if u_now is not None else a['usg']
        lv = (ctx['lvl'], ctx['nlvl'], ctx['xfer'])
        tiers = []
        for k in TIERS:
            dU = k - a['usg']
            ts = predict(sfit, 'ts', a, hist, lv, dU)
            to = max(5.0, predict(sfit, 'to', a, hist, lv, dU))
            tiers.append([round(pts40(K, k, ts, to), 1), round(ts, 1), 1 if dU > dmax else 0])
        age = r.get('age') if r.get('age') is not None else r.get('ageEst')
        out.append({'id': a['pid'], 'n': r['name'], 'tm': r['team'], 'lo': r.get('logo'), 'sub': r.get('conf') or '', 'pos': r.get('pos') or '',
                    'age': age, 'ph': r.get('photo'), 'p': round(p, 3), 'u': round(u, 1), 'u0': round(a['usg'], 1),
                    'best': round(best, 1), 't': tiers, 'sig': sig})
    out.sort(key=lambda o: -o['p'])
    out = out[:400]
    d = bfit['definition']
    f = bfit['final']
    more = ''
    if sw:
        g = sw['final_vs_redo']
        more = f"; improvement sweep {g['base']:.4f} -> {g['cand']:.4f} (t {g['t']}, {g['won']}/{g['seasons']})"
    about = (f"odds from {label} Barttorvik lines; breakout = {d}; players already there are left out; held-out log loss {f['base']:.4f} -> {f['cand']:.4f} "
             f"(t {f['t']}, {f['won']}/{f['seasons']} seasons){more}; signals: {', '.join(keep + extra)}; tiers = TS% and points a 40 "
             f"at that usage from the contextual scaling fit ({', '.join(sfit['ts']['keep'])}); * = a usage jump past "
             f"the 99th percentile of observed jumps (+{dmax:.0f}); u = usage this season (2+ games) or last")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'sport': 'cbb', 'season': '2026-27', 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
               'base': label, 'u': {'lab': 'USG', 'dec': 1},
               'tiers': [{'k': k, 'lab': f'USG {k}'} for k in TIERS],
               'stat': {'lab': 'PTS/40', 'eff': 'TS%', 'dec': 1, 'edec': 1}, 'about': about, 'rows': out},
              open(OUT, 'w'), separators=(',', ':'))
    print(f'{len(match)} board players with a {label} line, {done} already at the bar ({bar}), {len(out)} rows -> {OUT}')


if __name__ == '__main__':
    main()
