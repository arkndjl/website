# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer Potential Breakout ("next up" tab): breakout odds and contextual workload scaling for big-five outfield
players (static/data/next-up/soccer.json). Model and held-out tests: scripts/soccer_breakout_research.py ->
data/soccer_breakout_fit.json.

    python3 scripts/soccer_breakout.py         # build from static/data/soccer-war/<season>.json + the fit; stdlib only

Workload = shot involvement share (SI%): the player's shots + key passes per 100 team shots while he is on the pitch
(team shots a 90 x his minutes). Efficiency = (non-penalty xG + xA) per shot involvement. xG+xA a 90 = SI% x team
shots a 90 x efficiency. Value = GAR a 90 (scripts/soccer_players.py).

Feature columns live here so the research fit and the live board build them the same way."""
import datetime as dt
import glob
import json
import math
import os
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SDIR = os.path.join(ROOT, 'static', 'data', 'soccer-war')
FIT = os.path.join(ROOT, 'data', 'soccer_breakout_fit.json')
OUT = os.path.join(ROOT, 'static', 'data', 'next-up', 'soccer.json')
LOGOS = os.path.join(ROOT, 'data', 'soccer_logos.json')
LG = {'eng.1': 'EPL', 'esp.1': 'LaLiga', 'ger.1': 'BuLi', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1'}
PH = 'https://img.a.transfermarkt.technology/portrait/medium/'

SUM = ('min', 'mp', 'st', 'g', 'a', 'npxg', 'xa', 'xg', 'sh', 'kp', 'ch', 'bu', 'gar')
TARGETS = ('eff',)
MEAN = {'eff': 0.10}
K_INV = 40.0          # shot involvements that carry half the weight of a season's efficiency
MIN_PAIR = 900
TSH = 12.5            # league-average team shots a 90
BASE = ['x0', 'x0*r0', 'r0', 'age', 'age2', 'u0', 'xprev', 'hasprev']
BLOCKS = {
    'role': ['F', 'D', 'kpsh', 'bu90', 'stsh'],
    'shot profile': ['xgsh', 'xakp', 'sh90'],
    'past workload history': ['own', 'xprevc'],
    'age': ['agec'],
    'low-workload rates': ['x0c', 'x0c_lowu'],
    'low-minute rates': ['lowm', 'x0c_lowm'],
    'team strength': ['tsh', 'dT'],
}


# ---------- data ----------
def seasons():
    return sorted(int(os.path.basename(f)[:4]) for f in glob.glob(os.path.join(SDIR, '[0-9]*.json')))


def load(S):
    """one season file -> (players {p: pooled season}, teams {team: totals}, file meta)"""
    J = json.load(open(os.path.join(SDIR, f'{S}.json')))
    T = defaultdict(lambda: {'sh': 0.0, 'min': 0.0, 'npxg': 0.0, 'inv': 0.0, 'pmin': defaultdict(float), 'lg': None,
                             'ps': []})
    for r in J['players']:
        t = T[r['team']]
        t['sh'] += r['sh']; t['min'] += r['min']; t['npxg'] += r['npxg']; t['inv'] += r['sh'] + r['kp']
        t['pmin'][r['pos']] += r['min']; t['lg'] = r['lg']; t['ps'].append(r)
    for t in T.values():
        m = max(t['min'] / 990.0, 1e-9)           # team matches' worth of minutes
        t['sh90'], t['x90'] = t['sh'] / m, t['npxg'] / m
    by = defaultdict(list)
    for r in J['players']:
        by[r['p']].append(r)
    P = {}
    for p, rs in by.items():
        top = max(rs, key=lambda r: r['min'])
        o = {'p': p, 'S': S, 'n': top['n'], 'pos': top['pos'], 'team': top['team'], 'lg': top['lg'],
             'teams': [r['team'] for r in rs], 'age': top.get('age'), 'mv': top.get('mv'), 'xmv': top.get('xmv'),
             'ph': top.get('ph')}
        for k in SUM:
            o[k] = sum(r.get(k) or 0 for r in rs)
        if o['min'] <= 0:
            continue
        opp = sum(T[r['team']]['sh90'] * r['min'] / 90.0 for r in rs)
        o['inv'] = o['sh'] + o['kp']
        o['U'] = 100.0 * o['inv'] / opp if opp > 0 else 0.0
        o['eff'] = (o['npxg'] + o['xa'] + MEAN['eff'] * 3) / (o['inv'] + 3)
        o['tsh'] = sum(T[r['team']]['sh90'] * r['min'] for r in rs) / o['min']
        o['tx'] = sum(T[r['team']]['x90'] * r['min'] for r in rs) / o['min']
        o['g90'] = o['gar'] * 90.0 / o['min']
        P[p] = o
    return P, dict(T), {k: J.get(k) for k in ('games', 'asof', 'label')}


def team_sh(T, team, lg):
    """a team's shots a 90 in a season; a side not in the league that season reads as its bottom three"""
    if team in T:
        return T[team]['sh90']
    v = sorted(t['sh90'] for t in T.values() if t['lg'] == lg)
    return sum(v[:3]) / 3 if len(v) >= 3 else TSH


def team_x(T, team, lg):
    if team in T:
        return T[team]['x90']
    v = sorted(t['x90'] for t in T.values() if t['lg'] == lg)
    return sum(v[:3]) / 3 if len(v) >= 3 else 1.2


def vacated(T, team, stay, p, pos):
    """share of the side's minutes at his position, and of its shot involvements, played last season by players who
    are no longer there (stay = ids on the side now), himself left out. None when the side has no last season"""
    t = T.get(team)
    if not t:
        return None
    gm = tm = gi = ti = 0.0
    for r in t['ps']:
        if r['p'] == p:
            continue
        inv = r['sh'] + r['kp']
        ti += inv
        if r['pos'] == pos:
            tm += r['min']
        if r['p'] not in stay:
            gi += inv
            if r['pos'] == pos:
                gm += r['min']
    return [gm / tm if tm else 0.0, gi / ti if ti else 0.0]


# ---------- workload scaling ----------
def columns(tgt=None):
    return BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in tr], []) for tr in BLOCKS.values()], [])


def history(P, p, S):
    """P: {(p, S): season}"""
    return [P[(p, s)] for s in range(S - 6, S + 1) if (p, s) in P]


def own_slope(hist, tgt):
    """the player's own workload -> efficiency slope across his seasons (450+ minutes), shrunk toward 0"""
    h = [o for o in hist if o['min'] >= 450]
    if len(h) < 2:
        return 0.0
    W = [o['inv'] / 50.0 for o in h]
    sw = sum(W) or 1.0
    mu = sum(w * o['U'] for w, o in zip(W, h)) / sw
    mx = sum(w * o[tgt] for w, o in zip(W, h)) / sw
    sxy = sum(w * (o['U'] - mu) * (o[tgt] - mx) for w, o in zip(W, h))
    sxx = sum(w * (o['U'] - mu) ** 2 for w, o in zip(W, h))
    return 100.0 * sxy / (sxx + 60.0)


def trait_vals(tgt, a, hist, dT):
    x0 = a[tgt]
    prev = [o for o in hist if o['S'] < a['S'] and o['min'] >= 450]
    xprev = prev[-1][tgt] if prev else x0
    lowu = max(0.0, 30 - a['U']) / 15
    lowm = max(0.0, 1800 - a['min']) / 1800
    m90 = a['min'] / 90.0
    return {
        'F': 1.0 if a['pos'] == 'F' else 0.0, 'D': 1.0 if a['pos'] == 'D' else 0.0,
        'kpsh': (a['kp'] + 2.0) / (a['inv'] + 5.0), 'bu90': a['bu'] / m90, 'stsh': a['st'] / max(1, a['mp']),
        'xgsh': (a['npxg'] + 0.5) / (a['sh'] + 5.0), 'xakp': (a['xa'] + 0.5) / (a['kp'] + 5.0), 'sh90': a['sh'] / m90,
        'own': own_slope(hist, tgt), 'xprevc': xprev - x0, 'agec': (a['age'] or 26.0) - 26,
        'x0c': x0 - MEAN[tgt], 'x0c_lowu': (x0 - MEAN[tgt]) * lowu, 'lowm': lowm, 'x0c_lowm': (x0 - MEAN[tgt]) * lowm,
        'tsh': a['tsh'] - TSH, 'dT': dT, '_xprev': xprev, '_has': 1.0 if prev else 0.0,
    }


def features(tgt, a, hist, dT, dU):
    t = trait_vals(tgt, a, hist, dT)
    x0, r0, age = a[tgt], a['inv'] / (a['inv'] + K_INV), a['age'] or 26.0
    v = {'x0': x0, 'x0*r0': x0 * r0, 'r0': r0, 'age': age, 'age2': age * age, 'u0': a['U'],
         'xprev': t['_xprev'], 'hasprev': t['_has'], 'dU': dU}
    for tr in BLOCKS.values():
        for k in tr:
            v[k] = t[k]
            v['dU*' + k] = dU * t[k]
    return [v[c] for c in columns(tgt)]


def predict(fit, tgt, a, hist, dT, dU):
    f = fit['scaling'][tgt]['fit']
    x = dict(zip(columns(tgt), features(tgt, a, hist, dT, dU)))
    return f['b0'] + sum(b * x[c] for b, c in zip(f['b'], f['cols']))


# ---------- breakout odds ----------
K_SHR, JUMP, MIN_NEXT, MIN_BASE = 600.0, 0.06, 1500, 450
BO_CANDS = ('age curve', 'low-workload efficiency', 'vacated minutes', 'finishing luck', 'projection gap',
            'minutes room', 'workload scaling', 'team move', 'club strength', 'market value')
BO_LABEL = {'age curve': 'age', 'low-workload efficiency': 'low-vol eff', 'vacated minutes': 'open minutes',
            'finishing luck': 'finish luck', 'projection gap': 'proj gap', 'minutes room': 'min room',
            'workload scaling': 'scales', 'team move': 'new club', 'club strength': 'strong club',
            'market value': 'market'}


def shr(g90, mn):
    """GAR a 90 shrunk to replacement (0) by minutes"""
    return g90 * mn / (mn + K_SHR)


def marcel(hist, S):
    """3-season GAR a 90, weights 5/4/3 by minutes, shrunk to replacement with 1000 minutes"""
    num = den = 0.0
    for o in hist:
        w = {0: 5, 1: 4, 2: 3}.get(S - o['S'])
        if w:
            num += w * o['gar'] * 90.0
            den += w * o['min']
    return num / (den + 1000.0)


def bo_feats(a, s0, ref, vac, mar, moved, dTx):
    """ref: his best shrunk GAR a 90 to date; vac: vacated() or None; moved: 1 if his club now is not last season's; dTx: new club's npxG a 90 minus the old"""
    age, mn = a['age'] or 26.0, a['min']
    m90 = mn / 90.0
    lowu = max(0.0, 30 - a['U']) / 15
    lm = math.log(mn)
    xgi90 = (a['npxg'] + a['xa']) / m90
    mv, xmv = a.get('mv'), a.get('xmv')
    has = 1.0 if (mv and xmv and mv > 0 and xmv > 0) else 0.0
    v = vac or [0.0, 0.0]
    return {'base': [s0, lm, ref - s0],
            'age curve': [age, age * age, age * s0],
            'low-workload efficiency': [(a['eff'] - MEAN['eff']) * lowu, a['U']],
            'vacated minutes': [v[0], v[1], 0.0 if vac else 1.0],
            'finishing luck': [(a['g'] - a['xg']) / (m90 + 5.0), (a['a'] - a['xa']) / (m90 + 5.0)],
            'projection gap': [mar - ref],
            'minutes room': [lm * s0, (mn < 1500) * xgi90, a['st'] / max(1, a['mp'])],
            'workload scaling': [(a['npxg'] + 0.5) / (a['sh'] + 5.0) * lowu, (a['kp'] + 2.0) / (a['inv'] + 5.0) * lowu],
            'team move': [moved, moved * dTx],
            'club strength': [a['tx'] + moved * dTx],
            'market value': [has * math.log(mv / xmv) if has else 0.0, has * math.log(mv) if has else 0.0, has]}


def bo_row(a, hist, Tb, team_now, stay):
    """(shrunk GAR a 90, best shrunk GAR a 90 to date, breakout feature dict) of base season a for a player now at
    team_now (stay = ids at that side now)"""
    s0 = shr(a['g90'], a['min'])
    ref = max(shr(o['g90'], o['min']) for o in hist)
    moved = 0.0 if team_now in a['teams'] else 1.0
    dTx = team_x(Tb, team_now, a['lg']) - a['tx'] if moved else 0.0
    return s0, ref, bo_feats(a, s0, ref, vacated(Tb, team_now, stay, a['p'], a['pos']), marcel(hist, a['S']), moved, dTx)


# ---------- live build ----------
def main():
    fit = json.load(open(FIT))
    SS = seasons()
    cur = SS[-1]
    Pc, Tc, meta = load(cur)
    done = (meta.get('asof') or '')[5:7] in ('06', '07')
    base = cur if done else cur - 1
    P = {}
    for s in range(base - 6, base + 1):
        if s in SS:
            Ps, Ts, _ = (Pc, Tc, None) if s == cur else load(s)
            if s == base:
                Tb = Ts
            for p, o in Ps.items():
                P[(p, s)] = o
    squad = defaultdict(set)
    for o in Pc.values():
        for t in o['teams']:
            squad[t].add(o['p'])
    LJ = json.load(open(LOGOS))

    def logo(team):
        e, t = LJ.get('espn', {}).get(team), LJ.get('tm', {}).get(team)
        path = f'/img/soccer/{e}.png' if e else f'/img/soccer/tm/{t}.png' if t else None
        return path if path and os.path.exists(os.path.join(ROOT, 'static', path.lstrip('/'))) else None
    bo, sc = fit['breakout'], fit['scaling']['eff']
    tiers = fit['tiers'] if sc['keep'] and sc['tests']['kept vs levels + dU (changed)']['t'] >= 2 else []
    up99 = fit['dU_p99']
    cols = ['base'] + bo['keep']
    rows = []
    for p, c in Pc.items():
        a = P.get((p, base))
        if not a or a['pos'] == 'GK' or a['min'] < MIN_BASE or a['inv'] < 5:
            continue
        hist = history(P, p, base)
        team = c['team']
        s0, ref, f = bo_row(a, hist, Tb, team, squad[team])
        x = sum([f[k] for k in cols], [])
        z = bo['fit']['b0'] + sum(b * v for b, v in zip(bo['fit']['b'], x))
        pr = 1 / (1 + math.exp(-max(-30, min(30, z))))
        # the passing signals pushing him up most: each block's contribution against the average player
        con, i = [], len(f['base'])
        for k in bo['keep']:
            n = len(f[k])
            con.append((sum(b * (v - m) for b, v, m in zip(bo['fit']['b'][i:i + n], f[k], bo['fit']['mu'][i:i + n])), k))
            i += n
        sig = [BO_LABEL[k] for v, k in sorted(con, reverse=True)[:2] if v > 0.15]
        tsh_now = team_sh(Tb, team, c['lg'])
        dT = tsh_now - a['tsh']
        t = []
        for tr in tiers:
            dU = tr['k'] - a['U']
            e = max(0.02, predict(fit, 'eff', a, hist, dT, dU))
            t.append([round(tr['k'] / 100.0 * tsh_now * e, 2), round(e, 3), 1 if dU > up99 else 0])
        age = c.get('age') or a.get('age')
        rows.append({'id': p, 'n': c['n'], 'tm': team, 'lo': logo(team), 'sub': LG.get(c['lg'], c['lg']),
                     'pos': a['pos'],
                     'age': round(age, 1) if age else None, 'ph': PH + c['ph'] if c.get('ph') else None,
                     'p': round(pr, 3), 'u': round(a['U'], 1), 't': t, 'sig': sig})
    rows.sort(key=lambda r: -r['p'])
    lab = lambda s: f'{s - 1}-{str(s)[2:]}'  # noqa: E731
    d = bo['def']
    about = (f"Breakout = {d}. Odds: ridge logistic on {lab(base)} ({', '.join(BO_LABEL[k] for k in bo['keep'])}), "
             f"held-out log loss gain {bo['final']['gain']:.4f}, t {bo['final']['t']}, "
             f"{bo['final']['won']}/{bo['final']['seasons']} seasons. SI% = shots + key passes per 100 team shots "
             f"while on the pitch; tiers = xG+xA a 90 at that SI% for his club, efficiency (xG+xA per shot involvement) "
             f"from season pairs: levels {', '.join(sc['keep_levels'])}, SI% change x {', '.join(sc['keep'])} "
             f"(held-out t {sc['tests']['kept vs levels + dU (changed)']['t']} on 5+ point changes; the change alone adds "
             f"nothing, t {sc['tests']['dU vs levels (changed)']['t']}); extrapolated = beyond the 99th "
             f"percentile of observed jumps.")
    out = {'sport': 'soccer', 'season': lab(cur if not done else cur + 1),
           'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'base': lab(base),
           'u': {'lab': 'SI%', 'dec': 1}, 'tiers': tiers,
           'stat': {'lab': 'xG+xA/90', 'eff': 'xGI/inv', 'dec': 2, 'edec': 3},
           'about': about, 'rows': rows[:400]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, len(out['rows']), 'rows; base', lab(base), flush=True)


if __name__ == '__main__':
    main()
