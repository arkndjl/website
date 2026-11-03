#!/usr/bin/env python3
"""Research + fit (Nov 3 2026): next-season and three-season GAR projections for the soccer players board.

    python3 scripts/soccer_proj_research.py --snaps   # partial-season GAR snapshots from the Understat cache
                                                      # (scripts/.cache/soccer; -> scripts/.cache/soccer/proj_snaps.json.gz)
    python3 scripts/soccer_proj_research.py           # fit + backtest (numpy) -> data/soccer_proj_fit.json

Lead (scripts/soccer_gar_research_nov03.py C2): last two seasons' rates pooled carry to next season's team goal
difference better than last season alone (t -3.73, 9/11), but nothing turned that into a player projection.

Unit: a big-five player-season S (stints summed, 90+ minutes), seen at share f of his league's season (f = matches
played / scheduled; .25 .5 .75 rebuilt from the cached match files with only the matches before that date, 1 = the
season file). Inputs (soccer_players.proj_x): G0 = GAR so far / f (full-season pace), M0 = minutes / f, P = the
S-1 and S-2 seasons' GAR pooled per 90 minutes, shrunk to 0 with 900 minutes (P1 = P x M0 / 90), ln(1 + M0), age on
Sep 1 (Transfermarkt birth date via scripts/data/soccer_mv_link.json.gz; 26 = 0). League strength in a snapshot is the
previous season's (what the live board has).
Targets: 1Y = GAR in S+1, for players in the big five in S+1 (90+ minutes); 3Y = GAR summed over S+1..S+3, a season
out of the big five counted 0 (same players).
Baselines: flat (1Y G0, 3Y 3 G0), pooled prior alone (S, S-1, S-2 GAR per 90 pooled by minutes x M0 / 90; 3Y x 3),
flatFit (OLS on [1, G0]: flat with its regression to the mean); the gate uses the best of the three held out.
Forms (3, pre-registered, OLS): pool [1, G0, P1, lnM0]; age = pool + [a, a^2, a M0/90]; agepos = pool + position
dummies + [a x position, a^2, a M0/90].
Leave one season out, prediction seasons 2017-2025 (1Y) / 2017-2023 (3Y). Paired t on squared error with players as
units (a player's seasons averaged), seasons won, held-out calibration slope (target on prediction).
Kept: the age form chosen (age or agepos, lower held RMSE at f = 1) beats the better baseline and the pool form at
every f with t <= -2, wins most seasons, slope .8-1.2.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D       # noqa: E402
import soccer_players as SP   # noqa: E402

OUT = os.path.join(SP.ROOT, 'data', 'soccer_proj_fit.json')
SNAPS = os.path.join(D.CACHE, 'proj_snaps.json.gz')
FS = [0.25, 0.5, 0.75, 1.0]
S_FIRST, S_LAST = 2017, 2026


def snapshot(S, f, F, LS):
    """{p: [min, gar, pos]} for season S after share f of each league's matches, and {lg: f actually reached}"""
    rows, fl = [], {}
    keep = D.BIG5
    for lg in keep:
        d = D.us_league(lg, S)
        if not d:
            continue
        ms = sorted((m for m in d['matches'] if m['res']), key=lambda m: m['t'] or '')
        k = int(round(f * len(d['matches'])))
        if k >= len(ms):
            continue
        D.BIG5 = [lg]
        try:
            rows += SP.build_rows(S, S, before=ms[k]['t'])
        finally:
            D.BIG5 = keep
        fl[lg] = k / len(d['matches'])
    SP.prep(rows, F['shrink'])
    out = {}
    for r in rows:
        if r['min'] < 90:
            continue
        v = SP.value(r, F) + (F.get('lgScale') or {}).get('k', 0.0) * SP.lg_of(LS, r['lg'], S - 1)
        g = (v - F['repl'][r['pos']]) * r['min'] / 90
        o = out.setdefault(r['p'], [0, 0.0, r['pos'], r['lg'], 0])
        o[0] += r['min']; o[1] += g
        if r['min'] > o[4]:
            o[2], o[3], o[4] = r['pos'], r['lg'], r['min']
    return {p: v[:4] for p, v in out.items()}, fl


def snaps():
    D._us_down[0] = True                                   # cache only
    F = json.load(open(SP.FIT))
    LS = SP.league_strength()
    out = {}
    for S in range(S_FIRST, S_LAST + 1):
        for f in FS[:-1]:
            pl, fl = snapshot(S, f, F, LS)
            out[f'{S}_{f}'] = {'p': pl, 'f': fl}
            print(S, f, len(pl), fl, flush=True)
    D.save(SNAPS, out)


def season_files():
    """S -> {p: [min, gar, pos, lg]} from static/data/soccer-war (stints summed, position/league of the longest)"""
    out = {}
    for fn in sorted(os.listdir(SP.SDIR)):
        S = int(fn[:4])
        d = json.load(open(os.path.join(SP.SDIR, fn)))
        m, best = {}, {}
        for o in d['players']:
            x = m.setdefault(o['p'], [0, 0.0, o['pos'], o['lg']])
            x[0] += o['min']; x[1] += o['gar']
            if o['min'] > best.get(o['p'], 0):
                best[o['p']] = o['min']; x[2], x[3] = o['pos'], o['lg']
        out[S] = m
    return out


def full_f(S):
    D._us_down[0] = True
    fl = {}
    for lg in D.BIG5:
        d = D.us_league(lg, S)
        if d and d['matches']:
            fl[lg] = sum(m['res'] for m in d['matches']) / len(d['matches'])
    return fl


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    SF = season_files()
    snap = D.load(SNAPS)
    dob = SP.proj_dobs()
    res = {'note': 'pred = c . x, x = soccer_players.proj_x(); coefficients per season share f, linear in between',
           'forms': ['pool', 'age', 'agepos'], 'formsTried': 3, 'K': SP.PROJ_K, 'A0': SP.PROJ_A0}
    for tgt in ('1y', '3y'):
        last = 2025 if tgt == '1y' else 2023
        res[tgt] = {'grid': []}
        for f in FS:
            X, Y, SS, PID, BF, BP = [], [], [], [], [], []
            for S in range(S_FIRST, last + 1):
                if f < 1:
                    sn = snap[f'{S}_{f}']; cur, fl = sn['p'], sn['f']
                else:
                    cur, fl = SF[S], full_f(S)
                nxt = SF.get(S + 1, {})
                for p, (mn, g, pos, lg) in cur.items():
                    if p not in nxt or p not in dob or lg not in fl:
                        continue
                    y = nxt[p][1] if tgt == '1y' else sum(SF.get(S + k, {}).get(p, [0, 0.0])[1] for k in (1, 2, 3))
                    x1, x2 = SF.get(S - 1, {}).get(p), SF.get(S - 2, {}).get(p)
                    pr = [(x1 or [0, 0.0])[0], (x1 or [0, 0.0])[1], (x2 or [0, 0.0])[0], (x2 or [0, 0.0])[1]]
                    age = SP.age_on(S, dob[p])
                    fx = max(fl[lg], 0.05)
                    X.append(SP.proj_x(mn, g, pos, age, pr, fx)); Y.append(y); SS.append(S); PID.append(p)
                    m0, g0 = mn / fx, g / fx
                    pool = (g + pr[1] + pr[3]) / max(mn + pr[0] + pr[2], 1) * m0     # pooled GAR a minute x paced minutes
                    k = 1 if tgt == '1y' else 3
                    BF.append(k * g0); BP.append(k * pool)
            X, Y, SS = np.array(X), np.array(Y), np.array(SS)
            PID = np.array(PID)
            cols = SP.PROJ_COLS
            sel = {'flatFit': [cols.index(c) for c in ('one', 'g0')],
                   'pool': [cols.index(c) for c in ('one', 'g0', 'p1', 'lm0')],
                   'age': [cols.index(c) for c in ('one', 'g0', 'p1', 'lm0', 'a', 'a2', 'am')]}
            sel['agepos'] = sel['age'] + [cols.index(c) for c in ('d', 'm', 'fw', 'ad', 'am_', 'af')]
            pr = {'flat': np.array(BF), 'poolAlone': np.array(BP)}
            seasons = sorted(set(SS.tolist()))
            for form, ix in sel.items():
                p_ = np.zeros(len(Y))
                for s in seasons:
                    tr, te = SS != s, SS == s
                    b = np.linalg.lstsq(X[tr][:, ix], Y[tr], rcond=None)[0]
                    p_[te] = X[te][:, ix] @ b
                pr[form] = p_
            e = {k: (v - Y) ** 2 for k, v in pr.items()}
            rm = {k: round(float(np.sqrt(v.mean())), 4) for k, v in e.items()}
            base = min(('flat', 'poolAlone', 'flatFit'), key=lambda k: rm[k])

            def tstat(a, b_):
                d = defaultdict(list)
                for pid, x in zip(PID, e[a] - e[b_]):
                    d[pid].append(x)
                v = np.array([np.mean(x) for x in d.values()])
                return round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2), len(v)

            def won(a, b_):
                return int(sum(e[a][SS == s].mean() < e[b_][SS == s].mean() for s in seasons))
            g = {'f': f, 'n': int(len(Y)), 'seasons': [seasons[0], seasons[-1]], 'rmse': rm, 'baseline': base}
            for form in [k for k in sel if k != 'flatFit']:
                t, npl = tstat(form, base)
                g[form] = {'tVsBase': t, 'wonVsBase': won(form, base), 'slope': round(float(np.polyfit(pr[form], Y, 1)[0]), 3),
                           'rho': round(float(np.mean([spearman(pr[form][SS == s], Y[SS == s]) for s in seasons])), 4)}
                if form != 'pool' and form != 'flatFit':
                    g[form]['tVsPool'], _ = tstat(form, 'pool'); g[form]['wonVsPool'] = won(form, 'pool')
                g['players'] = npl
            g['rhoBase'] = round(float(np.mean([spearman(pr[base][SS == s], Y[SS == s]) for s in seasons])), 4)
            g['c'] = {form: [round(float(v), 5) for v in np.linalg.lstsq(X[:, ix], Y, rcond=None)[0]] for form, ix in sel.items()}
            res[tgt]['grid'].append(g)
            print(tgt, f, json.dumps({k: v for k, v in g.items() if k != 'c'}), flush=True)
        G = res[tgt]['grid']
        pick = min(('age', 'agepos'), key=lambda k: G[-1]['rmse'][k])
        res[tgt]['form'] = pick
        res[tgt]['kept'] = all(x[pick]['tVsBase'] <= -2 and x[pick]['tVsPool'] <= -2 and x[pick]['wonVsBase'] > len(range(S_FIRST, last + 1)) / 2
                               and 0.8 <= x[pick]['slope'] <= 1.2 for x in G)
    # the live board reads cols + per-f coefficients of the picked form, padded to the full column list
    for tgt in ('1y', '3y'):
        form = res[tgt]['form']
        ix = {'pool': ['one', 'g0', 'p1', 'lm0'], 'age': ['one', 'g0', 'p1', 'lm0', 'a', 'a2', 'am']}
        ix['agepos'] = ix['age'] + ['d', 'm', 'fw', 'ad', 'am_', 'af']
        for g in res[tgt]['grid']:
            full = dict(zip(ix[form], g['c'][form]))
            g['live'] = [full.get(c, 0.0) for c in SP.PROJ_COLS]
    res['cols'] = SP.PROJ_COLS
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    if '--snaps' in sys.argv:
        snaps()
    else:
        main()
