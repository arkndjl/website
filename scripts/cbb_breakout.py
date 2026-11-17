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
        'age', 'big', 'guard', 'bpm', 'obpm', 'rg_lrk', 'unranked2', 'pts40')
TEXT = {'pid', 'name', 'team', 'conf', 'role'}
# a missing value takes the D-I middle (20%+ of minutes, 2010 on); age falls back on the class
FILL = {'usg': 18.9, 'ts': 53.0, 'to': 18.1, 'ast': 10.7, 'orb': 4.4, 'ftr': 33.3, 'tpar': 0.35, 'rimr': 0.35,
        'midr': 0.26, 'dunkr': 0.015, 'ft_shr': 0.72, 'tp_shr': 0.33, 'twop_shr': 0.48, 'tp_raw': 0.33, 'ft_raw': 0.70,
        'tpa40': 3.8, 'hti': 77.0, 'hgt_role': 0.0, 'big': 0.0, 'guard': 0.0, 'bpm': -2.0, 'obpm': -1.0,
        'rg_lrk': -6.2146, 'unranked2': 1.0, 'pts40': 13.3, 'cls': 2.0, 'gp': 0.0, 'min_per': 0.0}
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
    return [P[(pid, s)] for s in range(y - 4, y + 1) if (pid, s) in P]


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
JUMP, ROLE_M = 3.0, 40.0          # breakout: next-season BPM 3+ over his best shrunk BPM so far, on 40%+ of team minutes
LVL_M = 10.0                      # min% a season needs to count toward his best so far
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
    """(his best shrunk BPM so far, this season's shrunk BPM): a comeback to an old level is not a breakout"""
    cur = shr(a['bpm'], a['m'])
    return max([cur] + [shr(o['bpm'], o['m']) for o in hist if o['y'] < a['y'] and o['m'] >= LVL_M]), cur


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


def bo_row(a, hist, ctx, sfit, keep):
    s0, cur = level(a, hist)
    lv = (ctx['lvl'], ctx['nlvl'], ctx['xfer'])
    scal = predict(sfit, 'ts', a, hist, lv, 6.0) - predict(sfit, 'ts', a, hist, lv, 0.0)
    f = bo_feats(a, s0, cur, marcel(hist, a['y']), ctx, scal)
    return f, sum([f['base']] + [f[k] for k in keep], [])


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
    b0, bb, mu = bfit['fit']['b0'], bfit['fit']['b'], bfit['fit']['mu']
    spans, i = {}, 2
    for k in keep:
        n = len(bo_feats(cur[0], 0.0, 0.0, 0.0, {'vac': 0, 'inc': 0, 'top': 0, 'lvl': 0, 'nlvl': 0, 'xfer': 0}, 0.0)[k])
        spans[k] = (i, i + n)
        i += n
    out = []
    for r, a in match:
        if a['m'] < fit['min_m'] or a['gp'] < fit['min_gp']:
            continue
        nt = next_team[a['pid']]
        here, there = T.get(a['team'], NO_TEAM), T.get(nt, NO_TEAM)
        ctx = {'vac': there['vac'], 'inc': there['inc'], 'top': float(tops.get(nt, 0)), 'lvl': here['lvl'],
               'nlvl': there['lvl'], 'xfer': 1.0 if nt != a['team'] else 0.0}
        hist = history(P, a['pid'], a['y'])
        _, x = bo_row(a, hist, ctx, sfit, keep)
        z = b0 + sum(b * v for b, v in zip(bb, x))
        p = 1 / (1 + math.exp(-max(-30, min(30, z))))
        push = sorted(((sum(bb[j] * (x[j] - mu[j]) for j in range(*spans[k])), k) for k in keep), reverse=True)
        sig = [('usage' if k == 'low-volume efficiency' and a['usg'] >= 20 else BO_LABEL[k]) for v, k in push[:2] if v > 0.1]
        now = r.get('now') or {}
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
                    't': tiers, 'sig': sig})
    out.sort(key=lambda o: -o['p'])
    out = out[:400]
    d = bfit['definition']
    f = bfit['final']
    about = (f"odds from {label} Barttorvik lines; breakout = {d}; held-out log loss {f['base']:.4f} -> {f['cand']:.4f} "
             f"(t {f['t']}, {f['won']}/{f['seasons']} seasons); signals: {', '.join(keep)}; tiers = TS% and points a 40 "
             f"at that usage from the contextual scaling fit ({', '.join(sfit['ts']['keep'])}); * = a usage jump past "
             f"the 99th percentile of observed jumps (+{dmax:.0f}); u = usage this season (2+ games) or last")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'sport': 'cbb', 'season': '2026-27', 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
               'base': label, 'u': {'lab': 'USG', 'dec': 1},
               'tiers': [{'k': k, 'lab': f'USG {k}'} for k in TIERS],
               'stat': {'lab': 'PTS/40', 'eff': 'TS%', 'dec': 1, 'edec': 1}, 'about': about, 'rows': out},
              open(OUT, 'w'), separators=(',', ':'))
    print(f'{len(match)} board players with a {label} line, {len(out)} rows -> {OUT}')


if __name__ == '__main__':
    main()
