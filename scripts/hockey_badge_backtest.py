#!/usr/bin/env python3
"""Backtest: do CHL badges predict what a pick became in the NHL beyond the hockey prospects board's draft grade?

    python3 scripts/hockey_badge_backtest.py --pull   # CHL (HockeyTech) skater seasons -> scripts/.cache/hockey/chl
    python3 scripts/hockey_badge_backtest.py          # -> data/hockey_badge_backtest.json

Badges as on the other boards (scripts/cfb_badges.mjs, scripts/nhl_badges.py): one trait from the draft-year CHL line
(HockeyTech's public OHL/WHL/QMJHL feeds), regressed toward the pool mean by games, v' = m + (v - m) * n / (n + k),
k = n (1 - r) / r from the year-to-year r of the stat (CHL skaters with 20+ games in back-to-back seasons, same
league), z'd within the pool: first-time draft-eligibles (17-18 on Sep 15 of the season) at the position (F / D) in
that league and season, 20+ games.
Rows: every 2008-19 skater pick whose draft-year line is in the CHL, joined by birth date and the shared name matcher.
Outcome: the board's outcome FV (scripts/hockey_prospects.py: peak descriptive WAR in the first seven seasons).
Held fixed: the board's draft model, its kept drivers (data/hockey_fit.json: slot, D, G, NHLe, class strength).
  t       the badge z's coefficient in outcome FV ~ drivers + z (HC1 standard errors; one row a player)
  oos     leave one draft class out (the board's fold rule): MSE gain of drivers + z over drivers, classes won of 12
  pass    t >= 2, oos > 0 and 8+ of 12 classes (the board's driver gate), forward (fit 2008-15, grade 2016-19) MSE
          better, positive sign
Stages 1-2 test the CHL line k seasons after the draft the same way, on that stage model's drivers (fv0 = the class-out
draft grade, NHLe, WJC, WAR... from data/hockey_fit.json), pool = the same birth cohort.
Results (Nov 1 2026; 984 of 1,014 CHL skater picks joined at the draft, 1,003 at stage 1, 733 at stage 2):
  draft   none: best Penalty Kill t 1.6; Sniper (shooting %) t -3.8 and Physical (PIM) t -3.0 negative
  stage 1 Shooter (shots a game) t 2.57, class-out MSE -1.32, 9/12, forward -1.28 (457 picks: shots from ~2013) PASS;
          Playmaker t 2.0 / Two-Way 2.5 / Penalty Kill 2.4 fail the class-out gate
  stage 2 none (Penalty Kill t 2.55 fails forward; Shooter t .68)
33 tests: one pass at t 2.57 is near what chance gives, and Shooter does not repeat at the draft or stage 2.
"""
import json
import math
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import hockey_badges as B
import hockey_fv_drivers as FV
import hockey_prospects as H
import names as NM

OUT = os.path.join(ROOT, 'data', 'hockey_badge_backtest.json')
MIN_GP = B.MIN_GP


def pull_chl():
    os.makedirs(FV.CHLD, exist_ok=True)
    jobs = []
    for c, k in FV.HTKEY.items():
        for s in (FV._get(FV.HT % (k, c) + '&view=seasons') or {}).get('SiteKit', {}).get('Seasons') or []:
            m = re.match(r'(\d{4}) ?- ?(\d{2,4}) \|? ?Regular Season$', s['season_name'].strip())
            if m and 2006 <= int(m.group(1)) <= 2026:
                jobs.append((c, k, s['season_id'], int(m.group(1)) + 1))

    def season(j):
        c, k, sid, yr = j
        fn = os.path.join(FV.CHLD, f'{c}_{yr}.json')
        if not os.path.exists(fn) or yr >= 2027:
            d = FV._get(FV.HT % (k, c) + f'&view=statviewtype&type=topscorers&season_id={sid}&first=0&limit=3000&stat=all&order_direction=')
            if d:
                json.dump(d['SiteKit'].get('Statviewtype'), open(fn, 'w'))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(season, jobs))
    print(len(os.listdir(FV.CHLD)), 'CHL seasons')


def seasons():
    """{(league, season end year): [skater lines]} from the cached HockeyTech tables"""
    T = {}
    for fn in os.listdir(B.CHLD):
        c, yr = fn[:-5].split('_')
        T[(B.HTLG[c], int(yr))] = B.parse(json.load(open(os.path.join(B.CHLD, fn))))
    return T


CANDS, eligible, pool_z = B.CANDS, B.eligible, B.pool_z


def yty(T, val):
    a, b, n = [], [], []
    for (lg, yr), ps in T.items():
        nxt = {p['id']: p for p in T.get((lg, yr + 1), [])}
        for p in ps:
            q = nxt.get(p['id'])
            if p['gp'] >= MIN_GP and q and q['gp'] >= MIN_GP and q['grp'] == p['grp']:
                x, y = val(p), val(q)
                if x is not None and y is not None:
                    a.append(x); b.append(y); n.append((p['gp'] + q['gp']) / 2)
    r = float(np.corrcoef(a, b)[0, 1]) if len(a) > 50 else float('nan')
    return r, float(np.mean(n)), len(a)


def ols(X, y):
    X1 = np.column_stack([np.ones(len(y)), X])
    b, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return b, X1


def hc1_t(X, y):
    b, X1 = ols(X, y)
    e = y - X1 @ b
    XtXi = np.linalg.inv(X1.T @ X1)
    V = XtXi @ (X1.T * e ** 2) @ X1 @ XtXi * len(y) / (len(y) - X1.shape[1])
    return float(b[-1] / math.sqrt(V[-1, -1])), float(b[-1])


def loco(X0, X1, y, cls):
    d = []
    for c in np.unique(cls):
        tr, te = cls != c, cls == c
        b0, _ = ols(X0[tr], y[tr]); b1, _ = ols(X1[tr], y[tr])
        p0 = np.clip(b0[0] + X0[te] @ b0[1:], 20, 80); p1 = np.clip(b1[0] + X1[te] @ b1[1:], 20, 80)
        d.append(np.mean((y[te] - p0) ** 2) - np.mean((y[te] - p1) ** 2))
    d = np.array(d)
    return float(d.mean()), int((d > 0).sum()), len(d), float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


def r3(x):
    return None if x is None or not math.isfinite(x) else round(float(x), 3)


def main():
    T = seasons()
    fit = json.load(open(H.FIT))
    W = H.war_tables()
    rows = H.read_rows(W)
    H.nhl_so_far(rows, W)
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT and not r['G']]
    allr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    F = [H.feats(r) for r in allr]
    cls_all = np.array([r['year'] for r in allr])
    yall = np.array([H.fv_of(r, sc) for r in allr])
    babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), yall)
    S = H.class_strength(F, cls_all, babs); H.set_cs(F, cls_all, S, float(np.mean(list(S.values()))))
    fmap = {id(r): f for r, f in zip(allr, F)}
    kept = [c for c in fit['kept'] if c != 'G']          # skaters only: the goalie flag is constant
    # the draft grade each pick's stage models start from: class-out, as the board fits them (fv0)
    _, p0 = H.score(F, yall, cls_all, fit['kept'])
    oof = {id(r): float(v) for r, v in zip(allr, p0)}
    out = {'method': 'see scripts/hockey_badge_backtest.py', 'tests': {}}
    # draft: the draft-year line, on the draft model's drivers; stages 1-2: the line k seasons after the draft (still in
    # the CHL), on that stage model's drivers (data/hockey_fit.json stages[k].kept, the goalie flag left out)
    for k in (0, 1, 2):
        if k:
            sk = [c for c in fit['stages'][str(k)]['kept'] if c != 'G']
            pop = [r for r in tr if r['year'] + k < H.D.current_season() and H.onboard(r, k)]
            X0of = lambda r, k=k, sk=sk: [H.stage_feats(r, k, oof[id(r)])[c] for c in sk]
            lgof = lambda r, k=k: (r['post'].get(k) or {}).get('lg')
        else:
            sk, pop = kept, tr
            X0of = lambda r: [fmap[id(r)][c] for c in kept]
            lgof = lambda r: (r.get('d0') or {}).get('lg')
        hits = []
        for r in pop:
            lg = lgof(r)
            if lg not in ('OHL', 'WHL', 'QMJHL'):
                continue
            c = [p for p in T.get((lg, r['year'] + k), []) if p['birth'] == r.get('birth') and NM.same(p['name'], r['name'])]
            if len(c) == 1 and c[0]['gp'] >= MIN_GP:
                hits.append((r, lg, c[0]))
        lab = 'draft' if not k else f'stage{k}'
        n_chl = sum(1 for r in pop if lgof(r) in ('OHL', 'WHL', 'QMJHL'))
        print(lab, 'CHL skater picks 2008-19', n_chl, 'joined', len(hits), 'drivers', sk)
        res = out['tests'][lab] = {'drivers': sk, 'chl': n_chl, 'joined': len(hits), 'badges': {}}
        for key, name, val, stat in CANDS:
            r_, n_, pairs = yty(T, val)
            kk = n_ * (1 - r_) / r_ if r_ > 0 else None
            ent = res['badges'][key] = {'name': name, 'stat': stat, 'pairs': pairs, 'r': r3(r_), 'volN': r3(n_), 'k': r3(kk)}
            if not r_ >= .15:
                ent.update({'pass': False, 'why': 'year-to-year r under .15'}); continue
            Z = {}
            for (lg, yr), ps in T.items():
                for g in 'FD':
                    pool = [p for p in ps if p['grp'] == g and p['gp'] >= MIN_GP and eligible(p['birth'], yr - k)]
                    Z.update({(lg, yr, i): v for i, v in pool_z(pool, val, kk).items()})
            sub = [(r, Z[(lg, r['year'] + k, p['id'])][0]) for r, lg, p in hits if (lg, r['year'] + k, p['id']) in Z]
            if len(sub) < 100:
                ent.update({'n': len(sub), 'pass': False, 'why': 'too few rows'}); continue
            X0 = np.array([X0of(r) for r, _ in sub]); z = np.array([z for _, z in sub])
            X0 = X0[:, X0.std(0) > 1e-9]                     # drivers constant on CHL rows (AHL shots, no line)
            y = np.array([H.fv_of(r, sc) for r, _ in sub]); cls = np.array([r['year'] for r, _ in sub])
            X1 = np.column_stack([X0, z])
            t, b = hc1_t(X1, y)
            g, won, of, tl = loco(X0, X1, y, cls)
            # forward, as the board's driver search checks: fit 2008-15, grade 2016-19
            f_, h_ = cls <= 2015, cls >= 2016
            fwd = None
            if f_.sum() > 50 and h_.sum() > 30:
                b0, _ = ols(X0[f_], y[f_]); b1, _ = ols(X1[f_], y[f_])
                e0 = np.mean((y[h_] - np.clip(b0[0] + X0[h_] @ b0[1:], 20, 80)) ** 2)
                e1 = np.mean((y[h_] - np.clip(b1[0] + X1[h_] @ b1[1:], 20, 80)) ** 2)
                fwd = e0 - e1
            ok = t >= 2 and g > 0 and won >= math.ceil(of * 2 / 3) and (fwd is None or fwd > 0)
            ent.update({'n': len(sub), 'coef': r3(b), 't': round(t, 2), 'oosMseGain': r3(g), 'classesWon': won, 'of': of,
                        'tLoco': round(tl, 2), 'fwdMseGain': r3(fwd), 'pass': bool(ok)})
            if not ok:
                ent['why'] = 'negative sign' if t <= -2 else ('t under 2' if t < 2 else 'held-out gate')
            print(' ', lab, key, {c: ent.get(c) for c in ('r', 'n', 'coef', 't', 'oosMseGain', 'classesWon', 'of', 'fwdMseGain', 'pass')}, flush=True)
        res['ship'] = [c for c, e in res['badges'].items() if e.get('pass')]
    json.dump(out, open(OUT, 'w'), indent=1)
    print('ship', {k: v['ship'] for k, v in out['tests'].items()})


if __name__ == '__main__':
    if '--pull' in sys.argv:
        pull_chl()
    else:
        main()
