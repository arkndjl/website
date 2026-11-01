#!/usr/bin/env python3
"""Soccer badge backtest (Nov 1 2026, "predictive badges like CFB's on other sports"): which trait badges predict the
board's own outcome BEYOND what the board already has. Results -> data/soccer_badge_backtest.json.

    python3 scripts/soccer_badge_backtest.py pro         # player board (GAR): next season's GAR a 90
    python3 scripts/soccer_badge_backtest.py prospects   # prospect board: the outcome FV the board's FV is fit to

Badge = scripts/soccer_badges.py (pro) / the prospect candidates below: one stat a 90 relative to the league-season
mean at the position, regressed by minutes, v' = m + (v - m) n/(n + k), k = n(1 - r)/r from the season-to-season r at
the mean minutes of the 900+ / 900+ pairs; r < .15 is dropped as noise.

PRO test. Rows: player-seasons 2015-25 with 900+ big-five minutes and 900+ the next season (Understat, frozen
scripts/data/soccer_player_rows.json.gz). y = next season's GAR a 90 (value a 90 minus position replacement, at the
board's fitted weights, data/soccer_war_fit.json). Held fixed: this season's GAR a 90, last season's (0 and a flag
when he had none), log minutes, age, age^2 (Transfermarkt birth date via soccer_mv_link), one fit per position
group. Candidate enters as the z of v' within the position. PASS = coefficient > 0 with t >= 2 CLUSTERED BY PLAYER,
AND leave-one-season-out (target season) MSE lower than without it, AND better in a majority of seasons. Passers
are refit jointly; one that falls under t 2 there is dropped. FotMob season lists (tackles, interceptions,
defensive actions, line-breaking passes, dribbles, goals prevented; per 90, regulars only) are candidates too:
cached in scripts/.cache/soccer/fmbdg.

PROSPECT test: the board's Oct 24 rows 2013-20 (53k player-seasons, as soccer_prospects.fit builds them). y = outcome
FV. Base = the board's kept FV drivers; the candidate is added and the whole fit redone leaving one birth cohort out
(the board's own FV scoring). Candidates from what the board has (Transfermarkt lineups: no xG, no tackles, no aerials):
senior goals a 90 and assists a 90 over last season + this season to the snapshot, a keeper's goals conceded a 90 in
full senior games; regressed by minutes against his main league's mean at the position group. Same gate.

RESULTS (Nov 1 2026; oosGain = held-out MSE cut x 1000, in the outcome's units)
PRO, 2015-25 -> next season, 900+/900+ (F 2,510 rows / 933 players, M 4,172 / 1,550, D 4,207 / 1,409, GK 864 / 252):
  y-to-y r: shots .75, key passes .76, xA .66, xGBuildup .69, xGChain-xGBuildup .67, FotMob tkl+int .67, defensive
  actions .70, dribbles .79, line-breaking passes .54 (2 seasons only), goals - xG .07 (dropped), keeper goals saved vs
  xG .11 (dropped), FotMob goals prevented vs xGOT .16.
  F: key passes t 5.34 (8/11), shots 2.47, xA 2.02, dribbles 3.42 pass; chain -1.77 fails. Joint: key passes + shots
     (t 6.16 / 4.14); xA (r .83 with key passes) and dribbles drop out.
  M: key passes 6.59, xGBuildup 3.86 (9/11), shots 3.38, xA 3.28, dribbles 2.84 pass; chain 1.09, tkl+int -.91,
     defensive actions -.71, line-breaking .71 (n 215) fail. Joint: key passes + xGBuildup + shots (6.98 / 7.57 / 4.01).
  D: xGBuildup 7.10 (9/11), key passes 2.88 pass; xA .95, tkl+int .23, defensive actions -3.05 fail. Joint: both.
  GK: goals prevented -.90 fails. SHIPPED: Chance Creator (key passes, F/M/D), Shot Volume (F/M), Progressor
  (xGBuildup, M/D). No projection on the player board to hook them into (GAR is a description of the season).
PROSPECTS, 53,680 rows (base cohort-out MSE 55.75, the board's 55.77; outcome var 96.3), r: goals a 90 .60 (k 13),
  assists a 90 .45 (k 25), keeper goals conceded .36 (82 pairs only).
  Finisher (goals a 90): F t -.56, M .33 fail. Chance Creator (assists a 90): F 1.37, M 1.41 fail; D t 2.50, 7/10
  cohorts, held-out MSE -.036 PASS (2.23 with a full-back dummy in the base, so not just full-backs). Shot Stopper
  (keeper goals conceded): t 1.91, 7/10, fails. No tackles, aerials or xG in the board's data (Transfermarkt lineups).
  SHIPPED: Chance Creator for defenders, display only: the held-out gain (R2 +.0004) is too small to justify refitting
  the five snapshot models it would have to enter.
"""
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_badge_backtest.json')


def save(section, obj):
    d = json.load(open(OUT)) if os.path.exists(OUT) else {}
    d[section] = obj
    json.dump(d, open(OUT, 'w'), indent=1, allow_nan=False)


# ---------------------------------------------------------------- stats helpers
def ols_cluster(X, y, g):
    """OLS with player-clustered SE: (b, se)"""
    XtX = np.linalg.pinv(X.T @ X)
    b = XtX @ X.T @ y
    e = y - X @ b
    meat = np.zeros((X.shape[1], X.shape[1]))
    order = np.argsort(g, kind='stable')
    gs = g[order]
    cuts = np.flatnonzero(np.r_[True, gs[1:] != gs[:-1], True])
    for i in range(len(cuts) - 1):
        idx = order[cuts[i]:cuts[i + 1]]
        s = X[idx].T @ e[idx]
        meat += np.outer(s, s)
    G = len(cuts) - 1
    n, k = X.shape
    c = G / (G - 1) * (n - 1) / (n - k)
    V = c * XtX @ meat @ XtX
    return b, np.sqrt(np.diag(V))


def loso(X, y, s):
    p = np.zeros(len(y))
    for S in np.unique(s):
        tr, te = s != S, s == S
        b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        p[te] = X[te] @ b
    return p


def test(Xb, xc, y, g, s):
    """candidate column xc on top of base Xb: coef, clustered t, LOSO MSE gain (x1000), seasons better"""
    keep = []                                            # drop base columns a subset makes constant or collinear
    for j in range(Xb.shape[1]):
        if np.linalg.matrix_rank(Xb[:, keep + [j]]) == len(keep) + 1:
            keep.append(j)
    Xb = Xb[:, keep]
    X = np.column_stack([Xb, xc])
    b, se = ols_cluster(X, y, g)
    p0, p1 = loso(Xb, y, s), loso(X, y, s)
    d = (y - p0) ** 2 - (y - p1) ** 2
    seas = np.unique(s)
    per = np.array([d[s == S].mean() for S in seas])
    return {'coef': round(float(b[-1]), 4), 't': round(float(b[-1] / se[-1]), 2),
            'oosGain': round(float(d.mean() * 1000), 4), 'oosR2Gain': round(float(d.mean() / np.var(y)), 4),
            'wins': int((per > 0).sum()), 'of': len(seas)}


def yty(pairs):
    """season-to-season r and k from [(v_S, v_S+1, n90_S)]"""
    a = np.array(pairs)
    r = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])
    n = float(a[:, 2].mean())
    return r, (n * (1 - r) / r if r > 0 else None), n


# ---------------------------------------------------------------- FotMob season lists (pro)
FMID = {'eng.1': 47, 'esp.1': 87, 'ger.1': 54, 'ita.1': 55, 'fra.1': 53}
FMST = {'total_tackle': 'tkl', 'interception': 'int', 'defensive_contributions': 'dc', 'lbp_total': 'lbp',
        'won_contest': 'drb', '_goals_prevented': 'gp'}
FM_CANDS = {
    'bw': ('Ball Winner', 'DM', 'tackles + interceptions a 90 (FotMob)', lambda q: (q.get('tkl') or 0) + (q.get('int') or 0), ('tkl', 'int')),
    'dc': ('Defensive Actions', 'DM', 'defensive actions a 90 (FotMob)', lambda q: q.get('dc'), ('dc',)),
    'lbp': ('Line Breaker', 'DM', 'line-breaking passes a 90 (FotMob)', lambda q: q.get('lbp'), ('lbp',)),
    'drb': ('Dribbler', 'FM', 'dribbles won a 90 (FotMob)', lambda q: q.get('drb'), ('drb',)),
    'gp': ('Shot Stopper (xGOT)', 'G', 'goals prevented vs xGOT a 90 (FotMob)', lambda q: (q['gp'] / max(q['min'], 1) * 90) if q.get('gp') is not None else None, ('gp',)),
}


def fm_pull(cur):
    import soccer_data as D
    cache = os.path.join(D.CACHE, 'fmbdg')
    os.makedirs(cache, exist_ok=True)
    out = {}
    for lg, i in FMID.items():
        d = D.get(f'https://www.fotmob.com/api/data/leagues?id={i}')
        for L in ((d or {}).get('stats') or {}).get('seasonStatLinks') or []:
            S = int(L['Name'][-4:])
            p = os.path.join(cache, f'{lg}_{S}.json.gz')
            if os.path.exists(p) and S < cur:
                out[(lg, S)] = D.load(p)
                continue
            base = 'https://data.fotmob.com/' + L['RelativePath'].rsplit('/', 1)[0] + '/'
            P = {}
            for st, k in FMST.items():
                x = D.get(base + st + '.json') or {}
                for q in (row for t in x.get('TopLists') or [] for row in t.get('StatList') or []):
                    o = P.setdefault(str(q.get('ParticiantId')), {'n': q.get('ParticipantName'), 'team': q.get('TeamName'), 'min': 0})
                    o['min'] = max(o['min'], q.get('MinutesPlayed') or 0)
                    o[k] = q.get('StatValue')
                time.sleep(0.1)
            rows = list(P.values())
            D.save(p, rows)
            out[(lg, S)] = rows
            print('fotmob', lg, S, len(rows), {k: sum(1 for r in rows if k in r) for k in FMST.values()}, flush=True)
    return out


def fm_join(rows, fm):
    """FotMob list row onto each Understat row (same league-season, names.py name match, team check)"""
    import names as N
    import soccer_gar_tests as GT
    by = defaultdict(list)
    for r in rows:
        by[(r['lg'], r['S'])].append(r)
    nj = nl = 0
    for k, L in fm.items():
        us = by.get(k, [])
        for q in L:
            nl += 1
            c = [r for r in us if (N.key(r['n']) == N.key(q['n']) or N.same(r['n'], q['n'])) and GT.team_ok(r['team'], q['team'])]
            if c:
                max(c, key=lambda r: r['min'])['fm'] = q
                nj += 1
    return {'listed': nl, 'joined': nj}


# ---------------------------------------------------------------- pro
def pro():
    import soccer_data as D
    import soccer_players as SP
    import soccer_badges as B
    F = json.load(open(SP.FIT))
    cur = D.current_season()
    rows = [r for r in D.load(SP.ROWS) if r['S'] < cur]
    SP.prep(rows, F['shrink'])
    LS = SP.league_strength()
    F['repl'] = F.get('repl') or {}
    for r in rows:
        v, _ = SP.gar_of(r, F, LS)
        r['gar90'] = v - F['repl'][r['pos']]
    import pickle
    jc = os.path.join(D.CACHE, 'fmbdg', 'joined.pkl')       # the name join is slow: cached once per run of the pull
    if os.path.exists(jc) and '--rejoin' not in sys.argv:
        fmj, fmr = pickle.load(open(jc, 'rb'))
        for r in rows:
            q = fmr.get((r['lg'], r['S'], r['tid'], r['p']))
            if q:
                r['fm'] = q
    else:
        fm = fm_pull(cur)
        fmj = fm_join(rows, fm)
        pickle.dump((fmj, {(r['lg'], r['S'], r['tid'], r['p']): r['fm'] for r in rows if r.get('fm')}), open(jc, 'wb'))
    print('fotmob join', fmj, flush=True)
    lines = B.agg_seasons(rows)
    # minutes-weighted GAR a 90 and FotMob line per player-season
    g90 = defaultdict(lambda: [0.0, 0.0])
    fmq = {}
    for r in rows:
        k = (r['p'], r['S'])
        g90[k][0] += r['gar90'] * r['min']; g90[k][1] += r['min']
        if r.get('fm') and (k not in fmq or r['fm']['min'] > fmq[k]['min']):
            fmq[k] = r['fm']
    for k, a in lines.items():
        a['gar90'] = g90[k][0] / max(g90[k][1], 1)
    # ages
    link = D.load(SP.MV_LINK)
    import datetime as dt
    dob = {u: link['dob'].get(str(t)) for u, t in link['p'].items()}

    def age(p, S):
        d = dob.get(p)
        if not d:
            return None
        return (dt.date(S - 1, 9, 1) - dt.date.fromisoformat(d[:10])).days / 365.25
    L = list(lines.values())
    # badge values, every candidate
    vals, meta = {}, {}
    for cid, (name, pos, lab, fn) in B.CANDS.items():
        raw = B.regress(L, cid, 0.0)                   # k = 0: the raw rate relative to the league-season-position mean
        pairs = [(raw[(a['p'], a['S'])], raw[(a['p'], a['S'] + 1)], a['min'] / 90) for a in L
                 if B.PG[a['pos']] in pos and a['min'] >= 900 and (a['p'], a['S'] + 1) in lines
                 and lines[(a['p'], a['S'] + 1)]['min'] >= 900 and lines[(a['p'], a['S'] + 1)]['pos'] == a['pos']]
        r, k, n = yty(pairs)
        meta[cid] = {'name': name, 'pos': pos, 'stat': lab, 'r': round(r, 3), 'k': None if k is None else round(k, 1),
                     'pairs': len(pairs), 'n90': round(n, 1)}
        if k is not None and r >= .15:
            vals[cid] = B.regress(L, cid, k)
    # FotMob candidates: relative to the league-season-position mean of the listed players, regressed by FotMob minutes
    for cid, (name, pos, lab, fn, need) in FM_CANDS.items():
        grp = defaultdict(list)
        for k_, q in fmq.items():
            a = lines.get(k_)
            if a and fn(q) is not None and q['min'] >= 90:
                grp[(a['lg'], a['S'], a['pos'])].append((k_, fn(q), q['min']))
        rel = {}
        for gk, X in grp.items():
            tot = sum(m for _, _, m in X) or 1
            mu = sum(v * m for _, v, m in X) / tot
            for k_, v, m in X:
                rel[k_] = (v - mu, m)
        pairs = [(rel[k_][0], rel[(k_[0], k_[1] + 1)][0], rel[k_][1] / 90) for k_ in rel
                 if (k_[0], k_[1] + 1) in rel and rel[k_][1] >= 900 and rel[(k_[0], k_[1] + 1)][1] >= 900
                 and B.PG[lines[k_]['pos']] in pos]
        if len(pairs) < 50:
            meta[cid] = {'name': name, 'pos': pos, 'stat': lab, 'pairs': len(pairs), 'note': 'too few'}
            continue
        r, k, n = yty(pairs)
        meta[cid] = {'name': name, 'pos': pos, 'stat': lab, 'r': round(r, 3), 'k': None if k is None else round(k, 1),
                     'pairs': len(pairs), 'n90': round(n, 1), 'seasons': sorted({k_[1] for k_ in rel})}
        if k is not None and r >= .15:
            vals[cid] = {k_: v * (m / 90) / (m / 90 + k) for k_, (v, m) in rel.items()}
    # test rows
    res = {}
    allc = {**{c: B.CANDS[c][1] for c in B.CANDS}, **{c: FM_CANDS[c][1] for c in FM_CANDS}}
    for P in ('F', 'M', 'D', 'G'):
        T = [a for a in L if B.PG[a['pos']] == P and a['min'] >= 900 and (a['p'], a['S'] + 1) in lines
             and lines[(a['p'], a['S'] + 1)]['min'] >= 900]
        y = np.array([lines[(a['p'], a['S'] + 1)]['gar90'] for a in T])
        prev = [lines.get((a['p'], a['S'] - 1)) for a in T]
        ag = np.array([age(a['p'], a['S']) or np.nan for a in T])
        agm = np.isnan(ag); ag = np.where(agm, np.nanmean(ag), ag) - 26
        Xb = np.column_stack([np.ones(len(T)), [a['gar90'] for a in T],
                              [q['gar90'] if q and q['min'] >= 300 else 0 for q in prev],
                              [0 if q and q['min'] >= 300 else 1 for q in prev],
                              np.log([a['min'] for a in T]), ag, ag ** 2, agm])
        g = np.unique([a['p'] for a in T], return_inverse=True)[1]; s = np.array([a['S'] + 1 for a in T])
        p0 = loso(Xb, y, s)
        out = {'n': len(T), 'players': int(len(set(g))), 'baseOosR2': round(float(1 - np.mean((y - p0) ** 2) / np.var(y)), 3)}
        for cid, pos in allc.items():
            if P not in pos or cid not in vals:
                continue
            v = vals[cid]
            x = np.array([v.get((a['p'], a['S']), np.nan) for a in T])
            m = ~np.isnan(x)
            if m.sum() < 200:
                out[cid] = {'note': 'too few rows', 'n': int(m.sum())}
                continue
            sub = Xb[m]; xs = x[m]
            z = (xs - xs.mean()) / xs.std()
            o = test(sub, z, y[m], g[m], s[m])
            o['n'] = int(m.sum())
            o['pass'] = bool(o['coef'] > 0 and o['t'] >= 2 and o['oosGain'] > 0 and o['wins'] * 2 > o['of'])
            out[cid] = o
            print(P, cid, o, flush=True)
        # joint: the passers added forward (largest held-out gain first) while every badge in the set keeps a positive
        # clustered t >= 2 and the set's held-out MSE falls; FotMob players off the lists sit at the mean (0)
        ps = [c for c in out if isinstance(out[c], dict) and out[c].get('pass')]
        Zc = {}
        for c in ps:
            x = np.array([vals[c].get((a['p'], a['S']), np.nan) for a in T])
            mm = ~np.isnan(x)
            Zc[c] = np.where(mm, (x - np.nanmean(x)) / np.nanstd(x), 0.0)
        sel, e_cur, steps = [], float(np.mean((y - p0) ** 2)), []
        while True:
            best = None
            for c in ps:
                if c in sel:
                    continue
                X = np.column_stack([Xb] + [Zc[q] for q in sel + [c]])
                b, se = ols_cluster(X, y, g)
                tt = b[Xb.shape[1]:] / se[Xb.shape[1]:]
                e = float(np.mean((y - loso(X, y, s)) ** 2))
                if (tt >= 2).all() and e < e_cur and (best is None or e < best[1]):
                    best = (c, e, [round(float(v), 2) for v in tt], [round(float(v), 4) for v in b[Xb.shape[1]:]])
            if not best:
                break
            sel.append(best[0]); e_cur = best[1]
            steps.append({'add': best[0], 'oosR2': round(1 - e_cur / float(np.var(y)), 4), 't': dict(zip(sel, best[2])),
                          'coef': dict(zip(sel, best[3]))})
        if ps:
            C = np.corrcoef(np.array([Zc[c] for c in ps])) if len(ps) > 1 else np.ones((1, 1))
            out['joint'] = {'passers': ps, 'kept': sel, 'steps': steps, 'corr': np.round(np.atleast_2d(C), 2).tolist()}
            print(P, 'joint', out['joint'], flush=True)
        res[P] = out
    save('pro', {'asof': dt.date.today().isoformat(), 'outcome': "next season's GAR a 90 (900+ minutes both seasons)",
                 'base': ['GAR a 90 this season', 'last season (flag if none)', 'log minutes', 'age', 'age^2'],
                 'fotmobJoin': fmj, 'candidates': meta, 'tests': res})


# ---------------------------------------------------------------- prospects
P_CANDS = {
    'fin': ('Finisher', 'FM', 'goals a 90, senior'),
    'cre': ('Chance Creator', 'FMD', 'assists a 90, senior'),
    'gks': ('Shot Stopper', 'G', 'goals conceded a 90 in full senior games (fewer = better)'),
}


def p_stats(SP, A, G, P, Sx):
    """per Oct 24 row: senior goals, assists, minutes over last season + this season to the snapshot (the board's own
    features), and a keeper's goals conceded (negated) in full games over the same window"""
    import pandas as pd
    out = pd.DataFrame(index=Sx.index)
    z = lambda c: Sx[c].fillna(0).values
    out['min'] = z('mins1') + z('mins_td')
    out['fin'] = z('gl1') + z('gl_td')
    out['cre'] = z('ast1') + z('ast_td')
    out['min1'] = z('mins1')
    out['fin1'] = z('gl1')
    out['cre1'] = z('ast1')
    gk = set(P.index[P.grp.eq('G')])
    a = A[A.player_id.isin(gk) & (A.mins >= 90) & A.comp.isin(SP.VALUE)][['game_id', 'player_id', 'club', 'date', 'season']]
    g = G.drop_duplicates('game_id').set_index('game_id')[['home', 'away', 'hg', 'ag']]
    a = a.join(g, on='game_id')
    a['ca'] = np.where(a.club == a.home, a.ag, np.where(a.club == a.away, a.hg, np.nan))
    a = a[a.ca.notna()]
    by = {k: d for k, d in a.groupby('player_id')}
    con, n_, con1, n1 = [], [], [], []
    for r in Sx.itertuples():
        d = by.get(r.player_id)
        if d is None:
            con.append(0); n_.append(0); con1.append(0); n1.append(0)
            continue
        snap = SP.snapdate(r.t, SP.SEL_SNAP)
        w = d[d.season.eq(r.t - 1) | (d.season.eq(r.t) & (d.date < snap))]
        w1 = d[d.season.eq(r.t - 1)]
        con.append(-float(w.ca.sum())); n_.append(len(w) * 90); con1.append(-float(w1.ca.sum())); n1.append(len(w1) * 90)
    out['gks'], out['gmin'], out['gks1'], out['gmin1'] = con, n_, con1, n1
    return out


def prospect_rows():
    """the board's Oct 24 rows 2013-20 (as soccer_prospects.fit builds them) plus the badge stats, cached"""
    import pandas as pd
    import soccer_prospects as SP
    fn = os.path.join(SP.CACHE, 'badge_rows.pkl')
    G, A, P, V = SP.load()
    for c in ('mins', 'gl', 'ast', 'mv', 'age', 'start'):
        A[c] = pd.to_numeric(A[c], errors='coerce').astype(float)
    V['mv'] = pd.to_numeric(V.mv, errors='coerce').astype(float)
    print('loaded', len(G), len(A), len(P), flush=True)
    R = SP.club_ratings(G, A, V)
    A = SP.add_value(A, R)
    O, scale = SP.outcome(A, P)
    TG = SP.team_games(G)
    done = O[O.s22 <= SP.COHORTS[1]]
    xs = []
    for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
        X = SP.features(A, P, V, R, TG, t, SP.snapdate(t, SP.SEL_SNAP))
        X['mvlvl'] = SP.mv_level(X.mv)
        X = X[X.index.isin(done.index) & X.old]
        X['fv_out'] = done.fv.reindex(X.index)
        X['s22'] = done.s22.reindex(X.index)
        xs.append(X.reset_index().rename(columns={'index': 'player_id'}))
        print('season', t, len(X), flush=True)
    Sx = pd.concat(xs, ignore_index=True)
    Sx['mvd'] = Sx.mv * np.exp(float(Sx.groupby('t').mvlvl.first().mean()) - Sx.mvlvl)
    st = p_stats(SP, A, G, P, Sx)
    Sx = pd.concat([Sx, st.add_prefix('b_')], axis=1)
    Sx.to_pickle(fn)
    return Sx


def prospect_vals(Sx, cid, k, pos=None):
    """v' for candidate cid: scripts/soccer_badges.py (the board computes it the same way)"""
    import soccer_badges as B
    return B.prospect_vals(Sx, cid, k)


def prospects(cached=False):
    import datetime as dt
    import pandas as pd
    import soccer_prospects as SP
    fn = os.path.join(SP.CACHE, 'badge_rows.pkl')
    Sx = pd.read_pickle(fn) if cached and os.path.exists(fn) else prospect_rows()
    F = SP.design(Sx)
    kept = json.load(open(SP.FIT))['kept']
    y, co, pid, grp = Sx.fv_out.values.astype(float), Sx.s22.values, Sx.player_id.values, Sx.grp.values
    Xd = np.column_stack([np.ones(len(F)), F[kept].values])
    p0 = loso(Xd, y, co)
    base = {'mse': round(float(np.mean((y - p0) ** 2)), 2), 'var': round(float(np.var(y)), 2),
            'boardMse10_24': json.load(open(SP.FIT))['models']['10-24']['mse']}
    print('base (board drivers, cohort-out)', base, flush=True)
    meta, res, vals = {}, {}, {}
    for cid, (name, pos, lab) in P_CANDS.items():
        mn1 = 'b_gmin1' if cid == 'gks' else 'b_min1'
        n91 = Sx[mn1].values / 90
        d1 = pd.DataFrame({'p': pid, 't': Sx.t.values, 'v': Sx['b_' + cid + '1'].values / np.maximum(n91, 1e-9), 'n': n91,
                           'ok': np.isin(grp, list(pos))})
        d1 = d1[d1.ok & (d1.n >= 10)]
        m = d1.merge(d1.assign(t=d1.t - 1), on=['p', 't'], suffixes=('', '_n'))
        m = m[m.n_n >= 10]
        r = float(np.corrcoef(m.v, m.v_n)[0, 1])
        nb = float(m.n.mean())
        k = nb * (1 - r) / r if r > 0 else None
        meta[cid] = {'name': name, 'pos': pos, 'stat': lab, 'r': round(r, 3), 'k': None if k is None else round(k, 1),
                     'pairs': int(len(m)), 'n90': round(nb, 1)}
        print(cid, meta[cid], flush=True)
        if k is None or r < .15:
            continue
        vr = prospect_vals(Sx, cid, k, pos)
        vals[cid] = vr
        res[cid] = {}
        for P_ in pos:
            msk = grp == P_
            x = vr[msk]
            zz = (x - x.mean()) / x.std()
            o = test(Xd[msk], zz, y[msk], pid[msk], co[msk])
            o['n'] = int(msk.sum())
            o['pass'] = bool(o['coef'] > 0 and o['t'] >= 2 and o['oosGain'] > 0 and o['wins'] * 2 > o['of'])
            res[cid][P_] = o
            print(cid, P_, o, flush=True)
    save('prospects', {'asof': dt.date.today().isoformat(), 'rows': int(len(y)),
                       'outcome': 'outcome FV (the FV his best three GAR seasons at 22-26 earned)',
                       'base': "the board's kept FV drivers, refit with the candidate: " + ', '.join(kept),
                       'folds': 'leave one birth cohort out (the board scores its FV that way); t clustered by player',
                       'baseFit': base, 'candidates': meta, 'tests': res})


if __name__ == '__main__':
    if 'pro' in sys.argv:
        pro()
    if 'prospects-test' in sys.argv:
        prospects(cached=True)
    if 'prospects' in sys.argv:
        prospects()
