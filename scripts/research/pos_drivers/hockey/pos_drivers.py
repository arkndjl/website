#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Hockey prospects: position-purpose FV drivers (Noah, Nov 2 2026; research). Each position's job turned into one or
two pre-registered numbers from the CHL season line (HockeyTech), offered on top of the live draft model and the live
stage-1 model (the season after the draft), against NHL outcomes, with the board's gate (sweep2.evalc).

Pre-registered (defined before any outcome was looked at; constants fixed, not tuned):
  C  win possession at the dot, drive play up the middle and create for the wingers
     cFO   faceoff win% - .50, x attempts / (attempts + 300), in 10-point units (seasons with 100+ attempts)
     cAst  assists / points - (mean over C picks), x pts / (pts + 20), x10 (10+ points)
  W  finish: turn chances into goals, and get to shooting spots
     wGsh  goals / points - (mean over W picks), x pts / (pts + 20), x10 (10+ points)
     wSOG  shots a game / league-season forward mean - 1, x gp / (gp + 20) (seasons the feed has shots)
  D  keep the puck out at even strength and move it up (goal differential while on, beyond the team's)
     dRPM  (+/- a game - .4 x team goal differential a game), x3, x gp / (gp + 20)
     dSOG  shots a game / league-season defence mean - 1, x gp / (gp + 20) (activation / point shot)
  G  stop shots, with the team's shot quality taken out
     gRel  save% - the save% of his team's other goalies (same team, same season), in sv% points (x100),
           x n_eff / (n_eff + 400), n_eff = shots_him x shots_others / (shots_him + shots_others)

Each driver is zero off its position. 7 drivers x (draft model, stage 1) = 14 pre-registered tests; Holm across them.
    python3 scripts/hockey_fv_drivers.py --pull                 # landing pages + CHL season tables
    python3 scripts/research/pos_drivers/hockey/pull_pos.py     # CHL goalie tables + standings
    python3 scripts/research/pos_drivers/hockey/pos_drivers.py  # -> scripts/.cache/hockey/pos_drivers.json
"""
import datetime as dt
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCRIPTS)
import hockey_prospects as H
import hockey_fv_drivers as HD
import hockey_fv_sweep2 as S2
import names as NM
import nhl_data as D

POS = os.path.join(H.CACHE, 'pos')
OUT = os.path.join(H.CACHE, 'pos_drivers.json')
DRV = ['cFO', 'cAst', 'wGsh', 'wSOG', 'dRPM', 'dSOG', 'gRel']
CODE = {v: k for k, v in HD.HTLG.items()}


def n(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def bdate(s):
    try:
        return dt.datetime.strptime(s or '', '%b %d, %Y').date().isoformat()
    except ValueError:
        return None


def fixname(nm):
    if ', ' in nm:
        a, _, b = nm.partition(', ')
        nm = f'{b} {a}'
    return nm


def load():
    """skaters {(LG, yr): {birth: [p]}}, league-season shot means by F/D, team GD a game, goalie lines"""
    SK, SM, GD, GK = {}, {}, {}, {}
    for fn in os.listdir(HD.CHLD):
        c, yr = fn[:-5].split('_'); LG = HD.HTLG[c]; yr = int(yr)
        ps = json.load(open(os.path.join(HD.CHLD, fn))) or []
        idx = {}
        acc = {'F': [], 'D': []}
        for p in ps:
            b = bdate(p.get('birthdate'))
            if b:
                idx.setdefault(b, []).append(p)
            gp, sh = n(p.get('games_played')), n(p.get('shots'))
            if gp >= 20 and sh > 0:
                acc['D' if (p.get('position') or '') == 'D' else 'F'].append(sh / gp)
        SK[(LG, yr)] = idx
        SM[(LG, yr)] = {k: float(np.mean(v)) for k, v in acc.items() if len(v) >= 30}
    for fn in os.listdir(POS):
        c, yr, tag = fn[:-5].split('_'); LG = HD.HTLG[c]; yr = int(yr)
        d = json.load(open(os.path.join(POS, fn))) or []
        if tag == 'st':
            for t in d:
                if t.get('team_id') and n(t.get('games_played')) > 0:
                    GD[(LG, yr, str(t['team_id']))] = (n(t['goals_for']) - n(t['goals_against'])) / n(t['games_played'])
        else:
            GK[(LG, yr)] = d
    return SK, SM, GD, GK


def line(SK, lg, yr, name, birth):
    for p in SK.get((lg, yr), {}).get(birth or '', []):
        if NM.same(fixname(p['name']), name):
            return p
    return None


def gk_rel(GK, lg, yr, name, birth):
    """save% over his team-mates in goal (each team stint), in sv% points, shrunk"""
    ls = GK.get((lg, yr)) or []
    mine = [g for g in ls if bdate(g.get('birthdate')) == birth and NM.same(fixname(g['name']), name)]
    if not mine:
        return None
    num, den = 0.0, 0.0
    for m in mine:
        t = str(m.get('team_id'))
        sh, sv = n(m.get('shots')), n(m.get('saves'))
        o = [g for g in ls if str(g.get('team_id')) == t and g is not m and g not in mine]
        osh, osv = sum(n(g.get('shots')) for g in o), sum(n(g.get('saves')) for g in o)
        if sh < 100 or osh < 100:
            continue
        ne = sh * osh / (sh + osh)
        num += (sv / sh - osv / osh) * 100 * ne / (ne + 400) * sh; den += sh
    return num / den if den else None


def feats_of(p, r, lg, yr, SM, GD, means):
    """the six skater drivers from one CHL season line (zero off position / missing)"""
    f = {k: 0.0 for k in DRV}
    if p is None or r['G']:
        return f
    gp, g, a, pts = n(p.get('games_played')), n(p.get('goals')), n(p.get('assists')), n(p.get('points'))
    if gp < 10:
        return f
    sh, fa, fw, pm = n(p.get('shots')), n(p.get('faceoff_attempts')), n(p.get('faceoff_wins')), n(p.get('plus_minus'))
    pos = r['pos'] or ''
    isC = pos.startswith('C'); isD = bool(r['D']); isW = not isC and not isD
    wg = gp / (gp + 20)
    sm = SM.get((lg, yr), {})
    if isC:
        if fa >= 100:
            f['cFO'] = (fw / fa - .5) * fa / (fa + 300) * 10
        if pts >= 10:
            f['cAst'] = (a / pts - means['cAst']) * pts / (pts + 20) * 10
    if isW:
        if pts >= 10:
            f['wGsh'] = (g / pts - means['wGsh']) * pts / (pts + 20) * 10
        if sh > 0 and sm.get('F'):
            f['wSOG'] = (sh / gp / sm['F'] - 1) * wg
    if isD:
        parts = p.get('team_breakdown') or [p]
        tg, gw = 0.0, 0.0
        for q in parts:
            k = (lg, yr, str(q.get('team_id')))
            if k in GD:
                w = n(q.get('games_played')) or gp
                tg += GD[k] * w; gw += w
        if gw:
            f['dRPM'] = (pm / gp - .4 * tg / gw) * 3 * wg
        if sh > 0 and sm.get('D'):
            f['dSOG'] = (sh / gp / sm['D'] - 1) * wg
    return f


def t_p(t, df=11):
    """two-sided p for a fold t (Student t with df, by numerical integration)"""
    x = abs(t)
    xs = np.linspace(0, x, 2001)
    c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))
    dens = c * (1 + xs ** 2 / df) ** (-(df + 1) / 2)
    return float(max(0.0, 1 - 2 * np.trapezoid(dens, xs)))


def main():
    W = H.war_tables()
    rows = HD.build_rows()
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr]); picks = np.array([r['pick'] for r in tr])
    fit = json.load(open(H.FIT))
    F = [H.feats(r) for r in tr]
    babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
    S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
    kept = fit['kept']
    s_all, p0 = H.score(F, y, cls, kept)
    print('draft model', kept, 'mse', round(s_all.mean(), 2), '(fit json', fit['mse'], ')', flush=True)
    fv0 = {id(r): float(p) for r, p in zip(tr, p0)}

    SK, SM, GD, GK = load()
    # draft-year and stage-1 CHL lines
    L0, L1 = {}, {}
    for r in tr:
        d0, q1 = r.get('d0') or {}, (r.get('post') or {}).get(1) or {}
        if d0.get('lg') in H.CHL:
            L0[id(r)] = (line(SK, d0['lg'], r['year'], r['name'], r.get('birth')), d0['lg'], r['year'])
        if q1.get('lg') in H.CHL:
            L1[id(r)] = (line(SK, q1['lg'], r['year'] + 1, r['name'], r.get('birth')), q1['lg'], r['year'] + 1)
    # centring means over the position's picks with a line (draft year), fixed for both tests
    def ratio(sel, num):
        v = [n(p.get(num)) / n(p.get('points')) for r in tr if sel(r) and id(r) in L0 and (p := L0[id(r)][0]) and n(p.get('points')) >= 10]
        return float(np.mean(v)) if v else 0.5
    isC = lambda r: (r['pos'] or '').startswith('C') and not r['D'] and not r['G']
    isW = lambda r: not isC(r) and not r['D'] and not r['G']
    means = {'cAst': ratio(isC, 'assists'), 'wGsh': ratio(isW, 'goals')}
    print('means', means, flush=True)
    cov = {}
    for f, r in zip(F, tr):
        p, lg, yr = L0.get(id(r), (None, None, None))
        f.update(feats_of(p, r, lg, yr, SM, GD, means))
        f['gRel'] = 0.0
        if r['G'] and lg:
            v = gk_rel(GK, lg, yr, r['name'], r.get('birth'))
            f['gRel'] = v or 0.0
    for c in DRV:
        nz = [r['year'] for f, r in zip(F, tr) if f[c] != 0]
        cov[c] = {'n': len(nz), 'classes': sorted(set(nz))[:1] + sorted(set(nz))[-1:], 'sd': round(float(np.std([f[c] for f in F if f[c] != 0] or [0])), 3)}
    print('coverage', cov, flush=True)
    res = {'means': means, 'coverage': cov, 'draft': {}, 'k1': {}}
    for c in DRV:
        o = S2.evalc(F, y, cls, picks, kept, c)
        # folds that carry the driver at all: t over those classes only (diagnostic)
        s0, _ = H.score(F, y, cls, kept); s1, _ = H.score(F, y, cls, kept + [c])
        has = sorted({r['year'] for f, r in zip(F, tr) if f[c] != 0})
        cl = sorted(set(cls)); idx = [cl.index(h) for h in has]
        d = (s0 - s1)[idx] if idx else np.array([0.0])
        o['tCov'] = round(S2.tval(d), 2) if len(d) > 2 else None; o['covFolds'] = len(idx)
        o['p'] = t_p(o['t'])
        res['draft'][c] = o; print('draft', c, o, flush=True)

    # stage 1: live k1 rows (pre model with the preseason share where the fit keeps one)
    k = 1
    sub = [r for r in tr if r['year'] + k < D.current_season() and H.onboard(r, k)]
    Fk = [H.stage_feats(r, k, fv0[id(r)]) for r in sub]
    yk = np.array([H.fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub]); pk = np.array([r['pick'] for r in sub])
    st = fit['stages'][str(k)]
    kk = list(st['kept']); kplain = list(kk)
    if 'pre' in st:
        H.pre_fill(Fk, sub, k); kk = list(st['pre']['kept'])
    s0, _ = H.score(Fk, yk, ck, kk)
    print('stage 1 base', kk, 'mse', round(s0.mean(), 2), '(fit json', st.get('pre', st)['mse'], ')', flush=True)
    for f, r in zip(Fk, sub):
        p, lg, yr = L1.get(id(r), (None, None, None))
        f.update(feats_of(p, r, lg, yr, SM, GD, means))
        f['gRel'] = 0.0
        if r['G'] and lg:
            f['gRel'] = gk_rel(GK, lg, yr, r['name'], r.get('birth')) or 0.0
    for c in DRV:
        o = S2.evalc(Fk, yk, ck, pk, kk, c); o['p'] = t_p(o['t'])
        o['plain'] = S2.evalc(Fk, yk, ck, pk, kplain, c)
        res['k1'][c] = o; print('k1', c, o, flush=True)
    # Holm over the 14 pre-registered tests (one-sided in the useful direction: a gain needs t > 0)
    tests = sorted([(res[s][c]['p'] if res[s][c]['t'] > 0 else 1.0, s, c) for s in ('draft', 'k1') for c in DRV])
    m = len(tests)
    for i, (p, s, c) in enumerate(tests):
        res[s][c]['holm'] = bool(all(tests[j][0] <= .05 / (m - j) for j in range(i + 1)))
    json.dump(res, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
