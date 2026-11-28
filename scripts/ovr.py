#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""OVR: a 0-99 overall grade for pro players (NBA, NFL, NHL, soccer, ATP / WTA, CS2), the pro counterpart of FV.

OVR is predictive: it reads each sport's most predictive player rate, recalibrated on next season's descriptive rate, with
the extra inputs that passed held out (scripts/research/ovr_nov28/run.py -> research/ovr_research.json; leave one season
out, scored on next-season rate error, next-season value r and team results, a pass needs |t| >= 2 on one and no loss
past t = 1 on the others):
    NBA     pXPM (sxpm)                                              nothing else passed
    NHL     pWAR a 60 (PR #1395), F / D + its slope on career TOI     G: + age, age^2
    soccer  p/90 + SV x min / (min + median) + age, age^2 + position
    NFL     pXP/60 (already within sub-position, three seasons)       not tested here (history files hold 2023-25 only)
    tennis  ARK (log-odds of the win chance against the average top-50 player), per tour
    CS2     RWA rating
The rate z then maps onto the grade piecewise linearly: replacement 60, the median starter 75, the mean of each
season's best 97 (above it the upper slope goes on, capped at 99; below replacement the lower slope, floor 20).
Starters: NBA the top 150 in minutes a season, NHL the top 12 F / 6 D / 1 G a team in TOI, soccer 1,800+ minutes,
NFL regulars (40% of his side's snaps), tennis #25 on ARK, CS2 the median tier-1 player. NHL goalies on their own range
(the pooled scale put every starter at 86-89; held out the goalie order ranks next season's WAR a 60 at Spearman .17). NHL and soccer rates are put on
full seasons first (WAR a 60 x a starter's TOI), so one scale holds every position. Band: the 80% band on true talent
(tau^2 = t0 + t1 / (sample + c0), fit held out with coverage checked). NBA O / D: the grade with the other side at the
median starter's (own-side next-season error t -21 O, -31 D against the total split).

    python3 scripts/ovr.py --fit    # anchors from the season files + the research params -> data/ovr_fit.json
    python3 scripts/ovr.py [sports] # rows -> data/ovr/<sport>.json (Hugo) and data/ovr.json (summary for the GFX)
    python3 scripts/ovr.py --test
Stdlib only."""
import glob, json, math, os, statistics as st, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
FIT = os.path.join(ROOT, 'data', 'ovr_fit.json')
RES = os.path.join(ROOT, 'research', 'ovr_research.json')
OUTD = os.path.join(ROOT, 'data', 'ovr')
SUM = os.path.join(ROOT, 'data', 'ovr.json')
SPORTS = ('nba', 'nhl', 'nfl', 'soccer', 'atp', 'wta', 'cs2')
LO, MID, HI, CAP, FLOOR = 60.0, 75.0, 97.0, 99, 20
Z80 = 1.2816


def grade(z, K):
    """z -> OVR (float): replacement r 60, starter s 75, top t 97"""
    if z is None: return None
    r, s, t = K['r'], K['s'], K['t']
    g = LO + (MID - LO) * (z - r) / (s - r) if z <= s else MID + (HI - MID) * (z - s) / (t - s)
    return max(FLOOR, min(CAP, g))


def gi(z, K):
    g = grade(z, K)
    return None if g is None else int(math.floor(g + 0.5))


def jload(fn, d=None):
    try: return json.load(open(fn))
    except (OSError, ValueError): return d


def r2(x, n=2): return None if x is None else round(x, n)


# ---------------------------------------------------------------- features (the same builders as the research suite)
def feats(ship, c, r):
    x = [r['P']]
    dv = r['D'] if r.get('D') is not None else r['P']
    a = (r.get('age') or c.get('age0', 27.0)) - c.get('age0', 27.0)
    for nm in ship:
        if nm == 'holistic': x.append(dv)
        elif nm == 'holisticN': x.append(dv * r['n'] / (r['n'] + c['medn']))
        elif nm == 'shrink': x.append(r['P'] * (r['n'] + r['car']) / (r['n'] + r['car'] + c['K']))
        elif nm == 'age': x += [a, a * a]
        elif nm == 'pos': x += [1.0 if r.get('pos') == p else 0.0 for p in c['pos'][1:]]
    return x


def zof(par, r):
    if r.get('P') is None: return None
    return sum(b * v for b, v in zip(par['beta'], [1.0] + feats(par['ship'], par['consts'], r)))


def tau(par, r):
    b = par.get('bands')
    if not b: return None
    return math.sqrt(max(b['t0'] + b['t1'] / (r['n'] + r['car'] + b['c0']), 0.0))


# ---------------------------------------------------------------- NBA
def nba_files():
    return {int(os.path.basename(f)[:4]): f for f in glob.glob(os.path.join(ROOT, 'static', 'data', 'nba-xpm', '20*.json'))}


def nba_pos(p):
    p = (p or '').split('-')[0].split('/')[0]
    return 'C' if p == 'C' else 'G' if p in ('PG', 'SG', 'G') else 'F'


def nba_rows(season, F):
    """research-shaped rows for one season file: P sxpm, D txpm, n mp, car = minutes before this season"""
    car = {}
    for s in sorted(F):
        if s >= season: break
        for p in jload(F[s], {}).get('players', []):
            if p.get('xpm') is not None and not p.get('pr'): car[p['id']] = car.get(p['id'], 0) + p['mp']
    out = []
    for p in jload(F[season], {}).get('players', []):
        if p.get('xpm') is None or p.get('pr') or p.get('sxpm') is None: continue
        out.append({'p': p, 'id': p['id'], 'P': p['sxpm'], 'D': p.get('txpm', p.get('xpm')), 'n': p['mp'], 'car': car.get(p['id'], 0),
                    'age': p.get('age'), 'pos': nba_pos(p.get('pos')), 'Po': p.get('soxpm'), 'Pd': p.get('sdxpm')})
    return out


def nba_fit(par):
    F = nba_files(); S, T, D = [], [], []
    for s in sorted(F):
        if s < 2016 or s >= max(F): continue
        rows = nba_rows(s, F)
        for r in rows: r['z'] = zof(par, r)
        top = sorted(rows, key=lambda r: -r['n'])[:150]
        S.append(st.median(r['z'] for r in top)); D.append(st.median(r['Pd'] for r in top if r.get('Pd') is not None))
        T.append(max(r['z'] for r in rows if r['n'] >= 1000))
    rep = (jload(os.path.join(ROOT, 'data', 'repl_levels.json'), {}).get('nba') or {}).get('level', -1.4)
    return {'r': round(rep, 3), 's': round(st.mean(S), 3), 't': round(st.mean(T), 3), 'dMed': round(st.mean(D), 3),
            'from': [2016, max(F) - 1], 'unit': 'pXPM'}


def nba_build(par, K):
    F = nba_files(); cur = max(F); rows = nba_rows(cur, F); out = []
    oMed = K['s'] - K['dMed']
    for r in rows:
        p = r['p']; z = zof(par, r); t = tau(par, r)
        o = zof(par, dict(r, P=r['Po'] + K['dMed'])) if r.get('Po') is not None else None
        d = zof(par, dict(r, P=r['Pd'] + oMed)) if r.get('Pd') is not None else None
        out.append({'n': p['n'], 'id': p['id'], 'tm': p.get('tm'), 'pos': p.get('pos'), 'pg': r['pos'], 'age': p.get('age'),
                    'ovr': gi(z, K), 'o': gi(o, K), 'd': gi(d, K),
                    'lo': gi(z - Z80 * t, K) if t else None, 'hi': gi(z + Z80 * t, K) if t else None,
                    'm': r2(p['sxpm'], 1), 'x': r2(r['D'], 1), 'smp': p['mp'], 'g': p.get('g'), 'ph': p.get('ph'), 'z': r2(z, 3)})
    return out, {'season': cur, 'label': f'{cur - 1}-{str(cur)[2:]}', 'metric': 'pXPM', 'desc': 'XPM', 'sample': 'MP'}


# ---------------------------------------------------------------- NHL
def nhl_files():
    return {int(os.path.basename(f)[:4]): f for f in glob.glob(os.path.join(ROOT, 'static', 'data', 'nhl-war', '20*.json'))}


def nhl_rows(season, F):
    car = {}
    for s in sorted(F):
        if s >= season: break
        for p in jload(F[s], {}).get('players', []):
            if p.get('toi'): car[p['id']] = car.get(p['id'], 0) + p['toi']
    out = []
    for p in jload(F[season], {}).get('players', []):
        if not p.get('toi') or p.get('pwar') is None or p.get('grp') not in ('F', 'D', 'G'): continue
        g = p['grp']
        out.append({'p': p, 'id': p['id'], 'grp': g, 'P': p['pwar'] / p['toi'] * 60, 'D': p['war'] / p['toi'] * 60 if p.get('war') is not None else None,
                    'n': p['toi'], 'car': car.get(p['id'], 0), 'age': p.get('age'), 'pos': p.get('pos') if g == 'F' else g})
    return out


NHL_SLOTS = {'F': 12, 'D': 6, 'G': 1}


def nhl_fit(pars):
    F = nhl_files(); full = {'F': [], 'D': [], 'G': []}; per = []
    for s in sorted(F):
        if s >= max(F): continue
        d = jload(F[s], {})
        if d.get('games', 82) < 82: continue
        rows = nhl_rows(s, F); per.append((s, rows))
        for g in full:
            by = {}
            for r in rows:
                if r['grp'] == g: by.setdefault(r['p'].get('tm'), []).append(r)
            st_ = [x for v in by.values() for x in sorted(v, key=lambda r: -r['n'])[:NHL_SLOTS[g]]]
            if st_: full[g].append(st.median(r['n'] for r in st_))
    T = {g: round(st.mean(v), 0) for g, v in full.items()}
    S, TT, GS, GT = [], [], [], []
    for s, rows in per[-11:]:
        ws, top = [], []
        for g in full:
            by = {}
            for r in rows:
                if r['grp'] == g: by.setdefault(r['p'].get('tm'), []).append(r)
            for v in by.values():
                for r in sorted(v, key=lambda r: -r['n'])[:NHL_SLOTS[g]]:
                    ws.append(zof(pars[g], r) * T[g] / 60)
            top += [zof(pars[g], r) * T[g] / 60 for r in rows if r['grp'] == g and r['n'] >= T[g] / 2]
        S.append(st.median(ws)); TT.append(max(top))
        # goalies on their own range (replacement 0, the median starter, the season's best): pooled, every starter sat at 86-89
        gs = []
        by = {}
        for r in rows:
            if r['grp'] == 'G': by.setdefault(r['p'].get('tm'), []).append(r)
        for v in by.values():
            gs += [zof(pars['G'], r) * T['G'] / 60 for r in sorted(v, key=lambda r: -r['n'])[:1]]
        GS.append(st.median(gs)); GT.append(max(zof(pars['G'], r) * T['G'] / 60 for r in rows if r['grp'] == 'G' and r['n'] >= T['G'] / 2))
    return {'r': 0.0, 's': round(st.mean(S), 3), 't': round(st.mean(TT), 3), 'toi': T, 'from': [per[-11][0], per[-1][0]], 'unit': 'WAR a full season',
            'G': {'r': 0.0, 's': round(st.mean(GS), 3), 't': round(st.mean(GT), 3)}}


def nhl_build(pars, K):
    F = nhl_files(); cur = max(F); rows = nhl_rows(cur, F); out = []
    for r in rows:
        p = r['p']; g = r['grp']; f = K['toi'][g] / 60; KK = K['G'] if g == 'G' and K.get('G') else K
        z = zof(pars[g], r); t = tau(pars[g], r)
        out.append({'n': p['n'], 'id': p['id'], 'tm': p.get('tm'), 'pos': p.get('pos'), 'pg': g, 'age': p.get('age'),
                    'ovr': gi(z * f, KK), 'lo': gi((z - Z80 * t) * f, KK) if t else None, 'hi': gi((z + Z80 * t) * f, KK) if t else None,
                    'm': r2(z * f, 2), 'x': r2(p.get('war'), 2), 'smp': p['toi'], 'g': p.get('gp'), 'ph': p.get('ph'), 'z': r2(z * f, 3), 'zr': r2(z, 5)})
    return out, {'season': cur, 'label': f'{cur - 1}-{str(cur)[2:]}', 'metric': 'pWAR/82', 'desc': 'WAR', 'sample': 'TOI'}


# ---------------------------------------------------------------- soccer
def soccer_rows(players):
    out = []
    for p in players:
        if p.get('pg90') is None or not p.get('min'): continue
        out.append({'p': p, 'id': p.get('p'), 'P': p['pg90'], 'D': p.get('sv') if p.get('sv') is not None else p.get('gar90'),
                    'n': p['min'], 'car': 0, 'age': p.get('age'), 'pos': p.get('pos')})
    return out


SOC_FULL = 34 * 90 / 90          # a full big-five season in 90s (34 matches)


def soccer_fit(par):
    S, T = [], []
    for s in range(2015, 2023):
        d = jload(os.path.join(ROOT, 'static', 'data', 'soccer-war', f'{s}.json'))
        if not d: continue
        rows = soccer_rows(d['players'])
        for r in rows: r['z'] = zof(par, r) * SOC_FULL
        S.append(st.median(r['z'] for r in rows if r['n'] >= 1800)); T.append(max(r['z'] for r in rows if r['n'] >= 1500))
    return {'r': 0.0, 's': round(st.mean(S), 3), 't': round(st.mean(T), 3), 'from': [2015, 2022], 'unit': 'GAR a full season'}


def soccer_build(par, K):
    d = jload(os.path.join(ROOT, 'data', 'soccer_war.json'), {}); rows = soccer_rows(d.get('players', [])); out = []
    for r in rows:
        p = r['p']; z = zof(par, r); t = tau(par, r)
        out.append({'n': p['n'], 'id': p.get('p'), 'tm': p.get('team'), 'lg': p.get('lg'), 'pos': p.get('pos'), 'pg': p.get('pos'),
                    'age': r2(p.get('age'), 1), 'ovr': gi(z * SOC_FULL, K),
                    'lo': gi((z - Z80 * t) * SOC_FULL, K) if t else None, 'hi': gi((z + Z80 * t) * SOC_FULL, K) if t else None,
                    'm': r2(p['pg90'], 3), 'x': r2(r['D'], 3), 'smp': p['min'], 'g': p.get('mp'), 'z': r2(z * SOC_FULL, 3)})
    cur = d.get('season')
    return out, {'season': cur, 'label': f'{cur - 1}-{str(cur)[2:]}' if cur else '', 'metric': 'p/90', 'desc': 'SV', 'sample': 'Min'}


# ---------------------------------------------------------------- NFL
def nfl_build(K=None):
    d = jload(os.path.join(ROOT, 'static', 'data', 'nfl-war.json'), {}); P = d.get('players', [])
    q = [p for p in P if p.get('pxp') is not None and p.get('q')]
    bk = [p for p in P if p.get('pxp') is not None and not p.get('q') and p.get('sn', 0) >= 50]
    if K is None:
        top = sorted((p['pxp'] for p in q), reverse=True)[:3]
        K = {'r': round(sum(p['pxp'] * p['sn'] for p in bk) / sum(p['sn'] for p in bk), 3), 's': round(st.median(p['pxp'] for p in q), 3),
             't': round(st.mean(top), 3), 'from': [d.get('season'), d.get('season')], 'unit': 'pXP/60'}
    out = []
    for p in P:
        if p.get('pxp') is None or p.get('sn', 0) < 50: continue
        out.append({'n': p['n'], 'id': p.get('id'), 'tm': p.get('tm') or p.get('t'), 'pos': p.get('pos'), 'pg': p.get('pos'), 'age': p.get('age'),
                    'ovr': gi(p['pxp'], K), 'm': r2(p['pxp'], 2), 'x': r2(p.get('xp'), 2), 'smp': p.get('sn'), 'g': p.get('g'),
                    'q': 1 if p.get('q') else 0, 'z': r2(p['pxp'], 3)})
    return out, {'season': d.get('season'), 'label': str(d.get('season')), 'metric': 'pXP/60', 'desc': 'XP/60', 'sample': 'Snaps'}, K


# ---------------------------------------------------------------- tennis
def logit(p): p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p / (1 - p))


def tennis_build(tour, K=None):
    d = (jload(os.path.join(ROOT, 'data', 'tennis.json'), {}).get('tours') or {}).get(tour, {})
    P = [p for p in d.get('players', []) if p.get('ark') is not None]
    zs = sorted((logit(p['ark']) for p in P), reverse=True)
    if K is None:
        K = {'r': round(zs[min(99, len(zs) - 1)], 4), 's': round(zs[24], 4), 't': round(st.mean(zs[:3]), 4), 'unit': 'ARK log-odds'}
    out = []
    for p in P:
        z = logit(p['ark']); u = p.get('unc')
        out.append({'n': p['n'], 'id': p.get('id'), 'nat': p.get('nat'), 'age': p.get('age'), 'ovr': gi(z, K),
                    'm': r2(p['ark'] * 100, 1), 'x': p.get('rank'), 'smp': p.get('nm'), 'elo': p.get('elo'), 'z': r2(z, 4)})
    return out, {'label': tour.upper(), 'metric': 'ARK', 'desc': 'Rank', 'sample': 'Matches'}, K


# ---------------------------------------------------------------- CS2
def cs2_build(K=None):
    d = jload(os.path.join(ROOT, 'data', 'cs2_players.json'), {}); P = [p for p in d.get('board', []) if p.get('rwa') is not None]
    if K is None:
        t1 = [p['rwa'] for p in P if p.get('tier') == 1]
        top = sorted((p['rwa'] for p in P), reverse=True)[:3]
        K = {'r': d.get('repl', -2.91), 's': round(st.median(t1), 3), 't': round(st.mean(top), 3), 'unit': 'RWA'}
    out = []
    for p in P:
        out.append({'n': p['n'], 'id': p.get('id'), 'tm': p.get('tm'), 'tk': p.get('tk'), 'logo': p.get('logo'), 'nat': p.get('nat'),
                    'tier': p.get('tier'), 'age': r2(p.get('age'), 1), 'ovr': gi(p['rwa'], K), 'm': r2(p['rwa'], 2),
                    'x': r2(p.get('d90'), 2), 'smp': p.get('maps'), 'z': r2(p['rwa'], 3)})
    return out, {'label': '', 'metric': 'RWA', 'desc': 'Δ90', 'sample': 'Maps'}, K



# ---------------------------------------------------------------- team OVR
# A team's value is its players' z weighted by the minutes they play (scripts/research/ovr_nov28/team.py: held out, next
# season's team rating from the minutes they went on to play R2 .699 NBA / .522 NHL, against .579 / .451 on last season's
# minutes, .585 / .364 on depth slots fit by rank and .584 / .383 on the top players equally). In season the minutes so far.
#   NBA  sum(z x MP) / sum(MP) x 5 (team rating, points a 100 over average)    NHL  sum(WAR a 60 x TOI / 60) x 82 / games
#   NFL  sum(pXP/60 x snaps / 60) / games                                     CS2  mean RWA of the five with the most maps
def team_value(sp, rows):
    T = {}
    for r in rows:
        t = (r.get('tk') if sp == 'cs2' else str(r.get('tm') or '').split('/')[-1]) or ''
        if t and t != 'None': T.setdefault(t, []).append(r)
    out = {}
    for t, pl in T.items():
        if sp == 'nba':
            w = sum(r['smp'] for r in pl)
            if w: out[t] = sum(r['z'] * r['smp'] for r in pl) / w * 5
        elif sp == 'nhl':
            g = max(r.get('g') or 0 for r in pl)
            if g: out[t] = sum(r['zr'] * r['smp'] / 60 for r in pl) * 82 / g
        elif sp == 'nfl':
            g = max(r.get('g') or 0 for r in pl)
            if g: out[t] = sum(r['z'] * r['smp'] / 60 for r in pl) / g
        elif sp == 'cs2':
            five = sorted(pl, key=lambda r: -(r.get('smp') or 0))[:5]
            if len(five) == 5: out[t] = sum(r['z'] for r in five) / 5
    return out, T


def team_fit(P, K):
    """anchors for team OVR: replacement roster 60, the median team 75, the mean of each season's best team 97"""
    TK = {}
    F = nba_files(); med, top = [], []
    for s_ in sorted(F):
        if s_ < 2016 or s_ >= max(F): continue
        rows = [{'tm': r['p'].get('tm'), 'z': zof(P['nba'], r), 'smp': r['n']} for r in nba_rows(s_, F)]
        v, _ = team_value('nba', rows); med.append(st.median(v.values())); top.append(max(v.values()))
    TK['nba'] = {'r': K['nba']['r'] * 5, 's': round(st.mean(med), 3), 't': round(st.mean(top), 3), 'unit': 'team rating'}
    F = nhl_files(); med, top = [], []
    for s_ in sorted(F):
        if s_ < 2014 or s_ >= max(F) or jload(F[s_], {}).get('games', 82) < 82: continue
        rows = [{'tm': r['p'].get('tm'), 'zr': zof(P['nhl'][r['grp']], r), 'smp': r['n'], 'g': r['p'].get('gp')} for r in nhl_rows(s_, F)]
        v, _ = team_value('nhl', rows); med.append(st.median(v.values())); top.append(max(v.values()))
    TK['nhl'] = {'r': 0.0, 's': round(st.mean(med), 3), 't': round(st.mean(top), 3), 'unit': 'team pWAR, 82 games'}
    rows, _, _ = nfl_build(K['nfl']); v, T = team_value('nfl', rows)
    rep = st.mean(K['nfl']['r'] * sum(r['smp'] for r in T[t]) / 60 / max(r.get('g') or 1 for r in T[t]) for t in v)
    TK['nfl'] = {'r': round(rep, 3), 's': round(st.median(v.values()), 3), 't': round(max(v.values()), 3), 'unit': 'pXP a game over average regulars'}
    rows, _, _ = cs2_build(K['cs2']); v, T = team_value('cs2', rows)
    t1 = [x for t, x in v.items() if any(r.get('tier') == 1 for r in T[t])]
    TK['cs2'] = {'r': K['cs2']['r'], 's': round(st.median(t1), 3), 't': round(max(v.values()), 3), 'unit': 'mean RWA of the five'}
    return TK


def team_rows(sp, rows, K):
    v, T = team_value(sp, rows); out = []
    for t, x in v.items():
        pl = sorted(T[t], key=lambda r: -(r.get('ovr') or 0))
        out.append({'tm': t, 'n': pl[0].get('tm') if sp == 'cs2' else t, 'ovr': gi(x, K), 'v': r2(x, 3), 'np': len(pl),
                    'logo': pl[0].get('logo'), 'tier': min((r.get('tier') or 9) for r in pl) if sp == 'cs2' else None,
                    'top': [[r['n'], r['ovr'], r.get('pos')] for r in pl[:3]]})
    out.sort(key=lambda r: -r['v'])
    for i, r in enumerate(out): r['rk'] = i + 1
    return out

# ---------------------------------------------------------------- fit / run
def research_par(R, key):
    x = R.get(key) or {}
    if not x.get('beta'): return None
    return {'beta': x['beta'], 'ship': x.get('ship', []), 'consts': x.get('consts', {}),
            'bands': {k: x['bands'][k] for k in ('t0', 't1', 'c0')} if x.get('bands') else None}


def fit():
    R = jload(RES, {})
    par = {'nba': research_par(R, 'nba'), 'soccer': research_par(R, 'soccer'),
           'nhl': {g: research_par(R, 'nhl' + g) for g in 'FDG'}}
    K = {'nba': nba_fit(par['nba']), 'nhl': nhl_fit(par['nhl']), 'soccer': soccer_fit(par['soccer'])}
    _, _, K['nfl'] = nfl_build()
    for t in ('atp', 'wta'): _, _, K[t] = tennis_build(t)
    _, _, K['cs2'] = cs2_build()
    K['team'] = team_fit(par, K)
    import datetime as dt
    out = {'asof': dt.date.today().isoformat(), 'scale': {'repl': LO, 'starter': MID, 'top': HI, 'cap': CAP, 'floor': FLOOR},
           'par': par, 'anchors': K}
    json.dump(out, open(FIT, 'w'), indent=1)
    print(json.dumps(K, indent=1))
    return out


def posrank(rows):
    by = {}
    for r in sorted(rows, key=lambda r: (-(r['ovr'] or 0), -(r.get('z') or 0))): by.setdefault(r.get('pg') or r.get('pos'), []).append(r)
    for v in by.values():
        for i, r in enumerate(v): r['prk'] = i + 1


def build(sports):
    Fd = jload(FIT)
    if not Fd: Fd = fit()
    P, K = Fd['par'], Fd['anchors']; os.makedirs(OUTD, exist_ok=True)
    summ = jload(SUM, {}) or {}
    import datetime as dt
    for sp in sports:
        if sp == 'nba': rows, meta = nba_build(P['nba'], K['nba'])
        elif sp == 'nhl': rows, meta = nhl_build(P['nhl'], K['nhl'])
        elif sp == 'soccer': rows, meta = soccer_build(P['soccer'], K['soccer'])
        elif sp == 'nfl': rows, meta, _ = nfl_build(K['nfl'])
        elif sp in ('atp', 'wta'): rows, meta, _ = tennis_build(sp, K[sp])
        elif sp == 'cs2': rows, meta, _ = cs2_build(K['cs2'])
        else: continue
        rows = [r for r in rows if r.get('ovr') is not None]
        rows.sort(key=lambda r: (-r['ovr'], -(r.get('z') or 0)))
        for i, r in enumerate(rows): r['rk'] = i + 1
        posrank(rows)
        if sp in K.get('team', {}):
            meta['teams'] = team_rows(sp, rows, K['team'][sp]); meta['teamAnchors'] = K['team'][sp]
            summ.setdefault('teams', {})[sp] = meta['teams'][:10]
        meta.update(sport=sp, asof=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), n=len(rows), anchors=K[sp])
        json.dump(dict(meta, rows=rows), open(os.path.join(OUTD, f'{sp}.json'), 'w'), separators=(',', ':'))
        summ[sp] = dict(meta, top=[{k: r.get(k) for k in ('n', 'tm', 'pos', 'ovr', 'lo', 'hi', 'age')} for r in rows[:30]])
        print(sp, len(rows), [(r['n'], r['ovr']) for r in rows[:5]])
    json.dump(summ, open(SUM, 'w'), indent=1)


def _test():
    K = {'r': -1.0, 's': 1.0, 't': 9.0}
    assert gi(-1.0, K) == 60 and gi(1.0, K) == 75 and gi(9.0, K) == 97
    assert gi(100, K) == CAP and gi(-100, K) == FLOOR
    assert gi(0.0, K) == 68 and gi(5.0, K) == 86
    par = {'beta': [0.0, 1.0, 0.5, 0.1, 0.0], 'ship': ['holisticN', 'age'], 'consts': {'medn': 100.0, 'age0': 27.0}}
    r = {'P': 2.0, 'D': 4.0, 'n': 100.0, 'car': 0, 'age': 28}
    assert abs(zof(par, r) - (2.0 + 0.5 * 2.0 + 0.1 * 1.0)) < 1e-9
    print('ovr: tests pass')


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--test' in a: _test()
    elif '--fit' in a: fit(); build(SPORTS)
    else: build([s for s in a if s in SPORTS] or SPORTS)
