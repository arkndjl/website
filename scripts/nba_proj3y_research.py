#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research + fit (Nov 3 2026): a 3-season projection for every NBA player (the XPM board's "3Y"), extending the rookie
3Y (scripts/nba_rookie_proj_research.py) to veterans.

    python3 scripts/nba_proj3y_research.py     # writes data/nba_proj3y_fit.json (numpy)

Rows: every player-season S 2012..2025 on the XPM board with minutes (S+3 <= 2026 for the 3-season target), as of the
end of season S. Inputs, all known then:
    proj   XPM (proj) = prior + (XPM - prior) x MP / (k + MP)   (scripts/nba_proj.py; prior nba_xpm.prior_xpm(S), k vet/new)
    age    bbref season age in S
    M      the contract tab's projected minutes for a full season (nba_proj: this season's minutes a game blended with
           last season's over 15 games, x his share of games, x 82); enters as ln(1 + M)
Targets (minutes-weighted XPM, shrunk toward -2, so a player who leaves the league sits near -2):
    y1     season S+1, shrunk with 500 MP;   y2, y3 the same for S+2, S+3 (per-year, for the contract tab)
    y3y    seasons S+1..S+3 pooled, shrunk with 1,000 MP (the rookie 3Y target)
    v3     VORX summed over S+1..S+3 (0 in a season off the board)
Baselines (the site's own):
    flat   proj held flat
    aged   proj + the delta-method aging curve summed to each year (nba_games.aging_curve(S + 1): pairs ending by S), the
           contract tab's later years; 3Y = mean of the three years
    cal    a + b x aged, fit on the training seasons (the strongest baseline: fixes the +.4 level and the slope)
Forms (pre-registered, 3; linear least squares):
    F1     c0 + c1 proj + c2 (age - 27) + c3 (age - 27)^2 + c4 ln(1 + M)
    F2     F1 with the prior and the season's shrunk deviation (proj - prior) as separate terms
    F3     F1 + c5 proj x (age - 27)
  added after the first run (F1-F3 ran ~1 point low on proj 6+ players), 5 forms in all:
    F4     F3 + c6 proj x (ln(1 + M) - 7)         <- picked (lowest held-out RMSE of the forms that beat F1, t <= -2)
    F5     F1 + c5 proj x (ln(1 + M) - 7)
  plus F3c (contract only): year-j XPM given he plays (rows with minutes in S+j, weighted by them), times M, for VORX.
Held out: leave one season out, training seasons within 3 of it dropped (1 for y1) so no training target overlaps the
held-out season's inputs or targets. Paired t on squared error, players as units (a player's seasons summed).
Kept: F1 unless a later form beats F1 with t <= -2 (lowest RMSE among those). Ships if it beats `aged` AND `cal` on y1
and y3y with t <= -2 at every f, wins most seasons, slope .8-1.2. Contract tab switch: a per-year form beats the aged
VORX (minutes M held flat) with t <= -2 at every f.
Result (Nov 3 2026): F4 ships (3Y held out at season end RMSE .843 vs cal .897 / aged 1.031 / flat 1.160, t -8.2 vs
cal, 12/12 seasons). Contract switch fails: shrunk forms lose on VORX late in a season, F3c loses early (f .1 t +7).
Stars still run low (proj 4+: 3.80 vs actual 4.44 over three seasons; aged 5.43).
Nov 4 2026: superseded live by H4 (F4 + hinge max(0, proj - 3) + the two seasons before + proj x ln(3-season minutes),
scripts/nba_proj3y_star_research.py): rerun that with --write after this script, or the live form falls back to F4.

Live guard (a partial season): coefficients per season share f, fit on simulated partial seasons like the rookie 3Y:
games g_f = max(1, round(g f)), minutes MP g_f / g x exp(N(0, .25 sqrt((1 - f) / f))) (role noise, an assumption),
raw XPM + N(0, s2 (1 / MP_f - 1 / MP)) with s2 = 606 vets / 797 newcomers (data/nba_proj_fit.json); proj and M
recomputed from those. 10 draws per row. Baselines are scored on the same draws.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_xpm as X
import nba_games as N
import nba_proj as P

ROOT = X.ROOT
OUT = os.path.join(ROOT, 'data', 'nba_proj3y_fit.json')
A0 = 27
FS = [0.1, 0.2, 0.35, 0.5, 0.75, 1.0]
DRAWS = 10
K1, K3, WASH = 500.0, 1000.0, -2.0
FORMS = ('F1', 'F2', 'F3', 'F4', 'F5')
CF = 'F4'                          # the per-year contract form (F3c below uses it)


def load():
    fit = json.load(open(P.FIT))
    files = {}
    for s in range(2010, 2027):
        d = P.load(s)
        if d: files[s] = d
    by = {s: {p['id']: p for p in d['players'] if p.get('xpm') is not None and not p.get('pr')} for s, d in files.items()}
    rows = []
    for S in range(2012, 2026):
        prior, old = X.prior_xpm(S), P.past_mp(S)
        cv = N.aging_curve(S + 1)
        last, lastg = by.get(S - 1, {}), files[S - 1]['games']
        for pid, p in by[S].items():
            if p['mp'] <= 0 or not p.get('age') or not p.get('g'): continue
            g = 'vet' if old.get(pid, 0) >= P.VET_MP else 'new'
            l = last.get(pid)
            fut = [by.get(S + j, {}).get(pid) for j in (1, 2, 3)]
            ys = [((f['xpm'] * f['mp'] if f else 0) + WASH * K1) / ((f['mp'] if f else 0) + K1) for f in fut]
            mp3 = sum(f['mp'] for f in fut if f)
            y3y = (sum(f['xpm'] * f['mp'] for f in fut if f) + WASH * K3) / (mp3 + K3) if S + 3 <= 2026 else None
            v3 = sum(f['vorx'] for f in fut if f) if S + 3 <= 2026 else None
            rows.append(dict(S=S, id=pid, g=g, k=fit[g]['k'], s2=fit[g]['sig2'], prior=prior(pid)[0], xpm=p['xpm'], mp=p['mp'],
                             gp=p['g'], games=files[S]['games'], age=p['age'], lmp=l['mp'] if l else None, lg=l['g'] if l else None,
                             lgames=lastg, ag=[sum(cv(p['age'] + i) for i in range(1, j + 1)) for j in (1, 2, 3)],
                             y=ys, y3y=y3y, v3=v3, fmp=[f['mp'] if f else 0 for f in fut], fx=[f['xpm'] if f else 0.0 for f in fut]))
    return rows


def minutes(r, mp, cg):
    """nba_proj's full-season minutes: pace blended with last season over G0 games x share of games x 82"""
    lmpg = r['lmp'] / r['lg'] if r['lmp'] and r['lg'] else None
    mpg = (lmpg * P.G0 + mp) / (P.G0 + cg) if lmpg is not None else mp / cg
    share = min(1.0, ((r['lg'] or 0) + 0.8 * 20) / ((r['lgames'] if r['lg'] else 0) + 20))
    return mpg * share * 82


def design(form, proj, prior, age, lm):
    a = age - A0
    c = {'F1': [proj, a, a * a, lm], 'F2': [prior, proj - prior, a, a * a, lm], 'F3': [proj, a, a * a, lm, proj * a], 'F4': [proj, a, a * a, lm, proj * a, proj * (lm - 7)], 'F5': [proj, a, a * a, lm, proj * (lm - 7)],
         'cal': [proj]}[form]
    return np.column_stack([np.ones_like(proj)] + c)


def inputs(rows, f, rng):
    """arrays at season share f (f = 1: the real season-end rows)"""
    n = DRAWS if f < 1 else 1
    proj, prior, age, lm, M = [], [], [], [], []
    for r in rows:
        for _ in range(n):
            if f < 1:
                cg = max(1, round(r['gp'] * f))
                mp = max(1.0, r['mp'] * cg / r['gp'] * math.exp(rng.normal(0, 0.25 * math.sqrt((1 - f) / f))))
                x = r['xpm'] + rng.normal() * math.sqrt(r['s2'] * max(1 / mp - 1 / r['mp'], 0))
            else:
                cg, mp, x = r['gp'], r['mp'], r['xpm']
            pj = r['prior'] + (x - r['prior']) * mp / (r['k'] + mp)
            m = minutes(r, mp, cg)
            proj.append(pj); prior.append(r['prior']); age.append(r['age']); lm.append(math.log1p(m)); M.append(m)
    return n, *(np.array(v, float) for v in (proj, prior, age, lm, M))


def tstat(d, ids):
    s = {}
    for i, v in zip(ids, d): s[i] = s.get(i, 0) + v
    v = np.array(list(s.values()))
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v))))


def evaluate(rows, f, rng):
    n, proj, prior, age, lm, M = inputs(rows, f, rng)
    rep = lambda k: np.repeat(np.array([r[k] for r in rows], float), n)
    S, ids = rep('S'), np.repeat([r['id'] for r in rows], n)
    AG = np.repeat(np.array([r['ag'] for r in rows], float), n, axis=0)
    Y = np.repeat(np.array([r['y'] for r in rows], float), n, axis=0)
    y3y = np.repeat(np.array([np.nan if r['y3y'] is None else r['y3y'] for r in rows]), n)
    v3 = np.repeat(np.array([np.nan if r['v3'] is None else r['v3'] for r in rows]), n)
    tg = {'y1': (Y[:, 0], proj + AG[:, 0], 1), 'y2': (Y[:, 1], proj + AG[:, 1], 3), 'y3': (Y[:, 2], proj + AG[:, 2], 3),
          'y3y': (y3y, proj + AG.mean(1), 3)}
    res, preds, coefs = {}, {}, {}
    for tn, (T, aged, buf) in tg.items():
        ok = ~np.isnan(T)
        if tn in ('y2',):           # S+2 <= 2026
            ok &= S <= 2024
        if tn in ('y3', 'y3y'):
            ok &= S <= 2023
        seasons = sorted(set(S[ok].astype(int)))
        P_ = {'flat': proj.copy(), 'aged': aged.copy()}
        for form in ('cal',) + FORMS:
            p = np.zeros_like(T)
            for c in seasons:
                tr = ok & (np.abs(S - c) > buf); te = ok & (S == c)
                xin = aged if form == 'cal' else proj
                b = np.linalg.lstsq(design(form, xin[tr], prior[tr], age[tr], lm[tr]), T[tr], rcond=None)[0]
                p[te] = design(form, xin[te], prior[te], age[te], lm[te]) @ b
            P_[form] = p
            if form != 'cal':
                coefs[(tn, form)] = np.linalg.lstsq(design(form, proj[ok], prior[ok], age[ok], lm[ok]), T[ok], rcond=None)[0]
        E = {k: (v - T) ** 2 for k, v in P_.items()}
        out = {'n': int(ok.sum() // n), 'seasons': [int(seasons[0]), int(seasons[-1])],
               'rmse': {k: round(float(np.sqrt(e[ok].mean())), 4) for k, e in E.items()}}
        for form in FORMS:
            o = {}
            for base in ('flat', 'aged', 'cal') + (('F1',) if form != 'F1' else ()):
                d = (E[form] - E[base])[ok]
                won = sum(np.sqrt(E[form][ok & (S == c)].mean()) < np.sqrt(E[base][ok & (S == c)].mean()) for c in seasons)
                o[base] = {'t': round(tstat(d, ids[ok]), 2), 'won': int(won), 'of': len(seasons)}
            o['slope'] = round(float(np.polyfit(P_[form][ok], T[ok], 1)[0]), 3)
            out[form] = o
        out['slopeAged'] = round(float(np.polyfit(P_['aged'][ok], T[ok], 1)[0]), 3)
        top = ok & (proj >= 4)                          # the stars: mean held-out prediction vs actual, proj 4+
        out['top4'] = {k: round(float(v[top].mean()), 2) for k, v in P_.items()} | {'actual': round(float(T[top].mean()), 2)}
        res[tn] = out
        preds[tn] = (P_, ok)
    # VORX over the three seasons at the contract tab's minutes (M held flat): baseline aged vs per-year F
    ok = ~np.isnan(v3)
    vb = sum(0.030 * (proj + AG[:, j] - X.VORX_REP) * M / 48 for j in range(3))
    vres = {'rmse': {}}
    for form in FORMS:
        vf = sum(0.030 * (preds[f'y{j + 1}'][0][form] - X.VORX_REP) * M / 48 for j in range(3))
        e, e0 = (vf - v3) ** 2, (vb - v3) ** 2
        vres['rmse'][form] = round(float(np.sqrt(e[ok].mean())), 3)
        sea = sorted(set(S[ok].astype(int)))
        vres[form] = {'t': round(tstat((e - e0)[ok], ids[ok]), 2),
                      'won': int(sum(np.sqrt(e[ok & (S == c)].mean()) < np.sqrt(e0[ok & (S == c)].mean()) for c in sea)), 'of': len(sea)}
    vres['rmse']['aged'] = round(float(np.sqrt(((vb - v3) ** 2)[ok].mean())), 3)
    # contract form (added after the shrunk per-year targets lost on VORX: a shrunk-to--2 XPM times full minutes counts
    # a washout twice): year-j XPM given he plays, fit on rows with minutes in S+j weighted by them; VORX at M held flat
    FM = np.repeat(np.array([r['fmp'] for r in rows], float), n, axis=0)
    FX = np.repeat(np.array([r['fx'] for r in rows], float), n, axis=0)
    sea = sorted(set(S[ok].astype(int)))
    vc, cc = np.zeros_like(proj), {}
    for j in range(3):
        pj = np.zeros_like(proj)
        for c in sea:
            tr = (np.abs(S - c) > 3) & (FM[:, j] > 0) & (S + j + 1 <= 2026); te = S == c
            w = np.sqrt(FM[tr, j])
            A = design(CF, proj[tr], prior[tr], age[tr], lm[tr])
            b = np.linalg.lstsq(A * w[:, None], FX[tr, j] * w, rcond=None)[0]
            pj[te] = design(CF, proj[te], prior[te], age[te], lm[te]) @ b
        vc += 0.030 * (pj - X.VORX_REP) * M / 48
        tr = (FM[:, j] > 0) & (S + j + 1 <= 2026); w = np.sqrt(FM[tr, j])
        cc[f'x{j + 1}'] = np.linalg.lstsq(design(CF, proj[tr], prior[tr], age[tr], lm[tr]) * w[:, None], FX[tr, j] * w, rcond=None)[0]
    e, e0 = (vc - v3) ** 2, (vb - v3) ** 2
    vres['rmse']['F3c'] = round(float(np.sqrt(e[ok].mean())), 3)
    vres['F3c'] = {'t': round(tstat((e - e0)[ok], ids[ok]), 2),
                   'won': int(sum(np.sqrt(e[ok & (S == c)].mean()) < np.sqrt(e0[ok & (S == c)].mean()) for c in sea)), 'of': len(sea),
                   'slope': round(float(np.polyfit(vc[ok], v3[ok], 1)[0]), 3), 'slopeAged': round(float(np.polyfit(vb[ok], v3[ok], 1)[0]), 3)}
    for j in range(3):
        coefs[(f'x{j + 1}', CF)] = cc[f'x{j + 1}']
    res['v3'] = vres
    return res, coefs


def raw_check(rows):
    """season-end only: unshrunk 3Y XPM (minutes-weighted, raw) for players with 500+ MP in S+1..S+3, F1 vs aged/cal"""
    by = {}
    for s in range(2010, 2027):
        d = P.load(s)
        if d: by[s] = {p['id']: p for p in d['players'] if p.get('xpm') is not None and not p.get('pr')}
    R = [r for r in rows if r['S'] <= 2023 and sum(r['fmp']) >= 500]
    T = np.array([sum(by[r['S'] + j][r['id']]['xpm'] * by[r['S'] + j][r['id']]['mp'] for j in (1, 2, 3) if r['id'] in by[r['S'] + j]) / sum(r['fmp']) for r in R])
    S = np.array([r['S'] for r in R], float); ids = [r['id'] for r in R]
    proj = np.array([r['prior'] + (r['xpm'] - r['prior']) * r['mp'] / (r['k'] + r['mp']) for r in R])
    prior = np.array([r['prior'] for r in R]); age = np.array([r['age'] for r in R], float)
    lm = np.array([math.log1p(minutes(r, r['mp'], r['gp'])) for r in R])
    aged = proj + np.array([np.mean(r['ag']) for r in R])
    out = {'n': len(R)}
    P_ = {'aged': aged}
    for form in ('cal',) + FORMS:
        p = np.zeros_like(T)
        for c in sorted(set(S.astype(int))):
            tr, te = np.abs(S - c) > 3, S == c
            xin = aged if form == 'cal' else proj
            b = np.linalg.lstsq(design(form, xin[tr], prior[tr], age[tr], lm[tr]), T[tr], rcond=None)[0]
            p[te] = design(form, xin[te], prior[te], age[te], lm[te]) @ b
        P_[form] = p
    E = {k: (v - T) ** 2 for k, v in P_.items()}
    out['rmse'] = {k: round(float(np.sqrt(e.mean())), 4) for k, e in E.items()}
    out['tF1vsAged'] = round(tstat(E['F1'] - E['aged'], ids), 2)
    out['tF1vsCal'] = round(tstat(E['F1'] - E['cal'], ids), 2)
    out['tF3vsAged'] = round(tstat(E['F3'] - E['aged'], ids), 2)
    out['tF3vsCal'] = round(tstat(E['F3'] - E['cal'], ids), 2)
    for a in ('F4', 'F5'):
        out[f't{a}vsCal'] = round(tstat(E[a] - E['cal'], ids), 2)
    return out


def main():
    rows = load()
    rng = np.random.default_rng(20261103)
    out = {'n': len(rows), 'seasons': [2012, 2025], 'A0': A0, 'forms': list(FORMS), 'grid': [],
           'note': 'live: pred = c0 + c1 proj + c2 (age - 27) + c3 (age - 27)^2 + c4 ln(1 + M) + c5 proj (age - 27) (F3); '
                   'M = nba_proj minutes per 82; c per target (y1 next season, y3y next three) on f = min(1, team games / 82), '
                   'linear in between. y1/y2/y3 per year shrunk to -2 with 500 MP, y3y pooled with 1,000 MP'}
    for f in FS:
        res, coefs = evaluate(rows, f, rng)
        g = {'f': f, 'res': res, 'cF1': {tn: [round(float(v), 4) for v in coefs[(tn, 'F1')]] for tn in ('y1', 'y2', 'y3', 'y3y')},
             'cF2': {tn: [round(float(v), 4) for v in coefs[(tn, 'F2')]] for tn in ('y1', 'y3y')},
             **{f'c{a}': {tn: [round(float(v), 4) for v in coefs[(tn, a)]] for tn in ('y1', 'y2', 'y3', 'y3y')} for a in FORMS[2:]},
             'cx': {tn: [round(float(v), 4) for v in coefs[(tn, CF)]] for tn in ('x1', 'x2', 'x3')}}
        out['grid'].append(g)
        print(f, json.dumps(res), flush=True)
    out['rawCheck'] = raw_check(rows)
    print('raw', out['rawCheck'])
    G = out['grid']
    # pre-registered pick: F1 unless F2 / F3 beat it with t <= -2 on y1 and y3y at every f
    # (F4 / F5 added after the first run showed F1-F3 a point low on proj 6+ players; the pick takes the lowest mean
    # held-out RMSE on y1 + y3y among forms that beat F1 with t <= -2 at every f, else F1)
    ok = [a for a in FORMS[1:] if all(g['res'][tn][a]['F1']['t'] <= -2 for g in G for tn in ('y1', 'y3y'))]
    score = lambda a: sum(g['res'][tn]['rmse'][a] for g in G for tn in ('y1', 'y3y'))
    pick = min(ok, key=score) if ok else 'F1'
    out['form'] = pick
    for g in G:
        g['c'] = {tn: g[f'c{pick}'][tn] for tn in ('y1', 'y3y')}
    out['kept'] = all(g['res'][tn][pick][b]['t'] <= -2 and 2 * g['res'][tn][pick][b]['won'] > g['res'][tn][pick][b]['of']
                      and 0.8 <= g['res'][tn][pick]['slope'] <= 1.2 for g in G for tn in ('y1', 'y3y') for b in ('aged', 'cal'))
    # contract tab's later years: one per-year form must beat its aged VORX (minutes held flat) with t <= -2 at every f
    out['contract'] = {k: all(g['res']['v3'][k]['t'] <= -2 for g in G) for k in FORMS + ('F3c',)}
    json.dump(out, open(OUT, 'w'), indent=1)
    print('form', pick, 'kept', out['kept'], 'contract', out['contract'])


if __name__ == '__main__':
    main()
