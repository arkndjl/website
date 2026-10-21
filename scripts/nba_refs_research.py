#!/usr/bin/env python3
"""NBA referee crews as inputs: game totals (scripts/nba_games.py), the totals pick market (scripts/games_picks.py),
and player points and minutes (scripts/nba_players.py). Research only.

    python3 scripts/nba_refs_research.py               # writes data/nba_refs_research.json (numpy; ~5 min)
    REF_HL=365 python3 scripts/nba_refs_research.py    # refs weighted by a 365-day half-life -> ..._hl.json

Needs scripts/nba_refs_hist.json.gz (scripts/nba_refs.py --pull) and the injury history (scripts/nba_inj_hist.py).
Each referee's effect is a ridge fit on every game he worked before the cut (crew effect = sum of the three refs),
refit every 14 days, so a game only sees games before it. Ridge lambda = games of shrinkage per ref, picked on 2015-21
by next-block squared error (the empirical shrink). Targets, per game: total minus the closing total, total minus the
model, free-throw attempts, personal fouls, possessions (the last three against the league's season-to-date mean).
Rule as elsewhere: 2015-21 clustered t <= -1.5 (game day x home team-season), 2022-26 not worse, BH q .10 over the
family.
Result (Oct 21 2026): nothing passed, either weighting. Crew free throws and fouls are real (next-block gain at lambda
80-160) and the held-out seasons 2022-26 gain in every one, but 2015-21 doesn't. The lean is logged forward
(scripts/nba_refs.py --today) and graded later on games it never saw.
"""
import gzip, json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as Fit
import nba_refs as R
import harness as H

OUT = os.path.join(N.ROOT, 'data', 'nba_refs_research.json')
OUT_HL = os.path.join(N.ROOT, 'data', 'nba_refs_research_hl.json')
WF = os.path.join(N.ROOT, 'scripts', 'data', 'games_wf', 'nba.json.gz')
LAMS = (5, 10, 20, 40, 80, 160, 320, 640)
BLOCK = 14


def r4(v):
    return None if v is None or v != v else round(float(v), 4)


def lg_resid(vals, S, order, prior_w=50):
    """value minus the league mean so far this season (last season's mean counted as prior_w games)"""
    out = np.full(len(vals), np.nan)
    acc, last = defaultdict(lambda: [0.0, 0]), {}
    for i in order:
        s = S[i]
        a = acc[s]
        if s not in last:
            p = acc.get(s - 1)
            last[s] = p[0] / p[1] if p and p[1] else None
        pm = last[s]
        if a[1] + (prior_w if pm is not None else 0) > 0 and not np.isnan(vals[i]):
            mean = (a[0] + (pm or 0) * (prior_w if pm is not None else 0)) / (a[1] + (prior_w if pm is not None else 0))
            out[i] = vals[i] - mean
        if not np.isnan(vals[i]):
            a[0] += vals[i]; a[1] += 1
    return out


def crew_walk(crews, days, targets, lams, ridx, hl=None):
    """walk-forward crew effect for each target and lambda: {target: {lam: array}}"""
    n, k = len(crews), len(ridx)
    A = np.zeros((n, k))
    for i, c in enumerate(crews):
        for r in c:
            A[i, ridx[r]] = 1.0
    out = {t: {l: np.full(n, np.nan) for l in lams} for t in targets}
    dnum = np.array([np.datetime64(d) for d in days]).astype('datetime64[D]').astype(int)
    start = dnum.min() + 200
    cuts = list(range(int(start), int(dnum.max()) + BLOCK, BLOCK))
    has = A.sum(1) >= 3
    for c0 in cuts:
        te = (dnum >= c0) & (dnum < c0 + BLOCK) & has
        if not te.any():
            continue
        tr = (dnum < c0) & has
        for t, y in targets.items():
            m = tr & ~np.isnan(y)
            if m.sum() < 500:
                continue
            w = np.ones(m.sum()) if hl is None else 0.5 ** ((c0 - dnum[m]) / hl)
            yy = y[m] - np.average(y[m], weights=w)
            G, b = (A[m] * w[:, None]).T @ A[m], (A[m] * w[:, None]).T @ yy
            for l in lams:
                beta = np.linalg.solve(G + l * np.eye(k), b)
                out[t][l][te] = A[te] @ beta
    return out


def main():
    games, names = N.load_hist()
    refs = R.load()
    inj = Fit.load_inj()
    F = json.load(open(N.FIT))
    P, feats, params = F['P'], list(F['feats']), dict(F['params'])
    _, data = N.walk(games, names, P, params, inj=inj)
    D = [(g, x, tx) for g, x, tx in data if g.get('fin') and g['S'] >= N.FIRST + 1]
    G = [g for g, _, _ in D]
    n = len(G)
    X = {f: np.array([x[f] for _, x, _ in D], float) for f in D[0][1]}
    TX = {f: np.array([tx[f] for _, _, tx in D], float) for f in D[0][2]}
    y = np.array([g['hs'] - g['as'] for g in G], float)
    ty = np.array([g['hs'] + g['as'] for g in G], float)
    S = np.array([g['S'] for g in G])
    tline = np.array([g['T'] if g.get('T') else np.nan for g in G])
    day = np.array([g['tip'][:10] for g in G])
    hts = np.array([f"{g['h']}|{g['S']}" for g in G])
    order = np.argsort([g['tip'] for g in G], kind='stable')
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM)
    k2 = S >= N.HOLD_FROM
    mat = lambda XX, fs: np.column_stack([XX[f] for f in fs])
    tbase = Fit.wf(mat(TX, N.TFEATS), ty, S)
    wf = {r['id']: r for r in json.load(gzip.open(WF, 'rt'))}
    topen = np.array([(wf.get(g['id']) or {}).get('To') or np.nan for g in G], float)

    # whistle per game
    rr = [refs.get(g['id']) for g in G]
    crews = [tuple((r or {}).get('r', [])[:3]) if r and len(r.get('r', [])) >= 3 else () for r in rr]
    tsum = lambda r, k: (sum((v.get(k) or 0) for v in r['t'].values()) if r and len(r['t']) == 2 and
                         all(v.get(k) is not None for v in r['t'].values()) else np.nan)
    fta = np.array([tsum(r, 'fta') for r in rr], float)
    pf = np.array([tsum(r, 'pf') for r in rr], float)
    poss = np.array([g.get('poss') or np.nan for g in G], float)
    names_ref = sorted({x for c in crews for x in c})
    ridx = {r: i for i, r in enumerate(names_ref)}
    targets = {'tot': ty - tline, 'mod': ty - tbase, 'fta': lg_resid(fta, S, order), 'pf': lg_resid(pf, S, order),
               'poss': lg_resid(poss, S, order)}
    res = {'games': n, 'withCrew': int(sum(1 for c in crews if c)), 'refs': len(names_ref),
           'bySeason': {int(s): int(sum(1 for c, ss in zip(crews, S) if c and ss == s)) for s in sorted(set(S))}}
    print(res, flush=True)
    HL = int(os.environ.get('REF_HL', '0')) or None          # half-life in days for the ref effects (None: all games equal)
    res['halfLifeDays'] = HL
    CW = crew_walk(crews, day, targets, LAMS, ridx, HL)

    # empirical shrink: lambda with the lowest next-block squared error on 2015-21; spread of the crew effect
    pick, shrink = {}, {}
    for t, yv in targets.items():
        sc = {}
        for l in LAMS:
            p = CW[t][l]
            m = k1 & ~np.isnan(p) & ~np.isnan(yv)
            sc[l] = float(np.mean((yv[m] - yv[m].mean() - p[m]) ** 2) - np.mean((yv[m] - yv[m].mean()) ** 2))
        l = min(sc, key=sc.get)
        pick[t] = l
        p = CW[t][l]
        m = ~np.isnan(p) & ~np.isnan(yv)
        mk2 = m & k2
        b2 = float(np.polyfit(p[mk2], yv[mk2] - yv[mk2].mean(), 1)[0]) if mk2.sum() > 100 else None
        shrink[t] = {'lam': l, 'mseGain2015_21': {str(k): r4(v) for k, v in sc.items()}, 'crewSd': r4(np.nanstd(p[S >= 2015])),
                     'rawSd': r4(np.nanstd(yv[S >= 2015])), 'slope2022_26': r4(b2),
                     'corr2022_26': r4(np.corrcoef(p[mk2], yv[mk2])[0, 1]) if mk2.sum() > 100 else None}
        print('shrink', t, shrink[t], flush=True)
    res['shrink'] = shrink
    C = {t: np.nan_to_num(CW[t][pick[t]]) for t in targets}
    haveC = ~np.isnan(CW['tot'][pick['tot']])

    tests = []

    def judge(name, new, old, loss_y, kind, mask=None):
        a, b = (np.abs(new - loss_y), np.abs(old - loss_y)) if loss_y is not None else (new, old)
        out = {'test': name, 'kind': kind}
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            k = k & ~np.isnan(a) & ~np.isnan(b) & haveC & (mask if mask is not None else True)
            p = H.paired(a[k], b[k], [day[k], hts[k]])
            out[nm] = {'d': r4(p['d']), 't': round(p['t'], 2), 'p': r4(p['p']), 'n': p['n']}
        out['bySeason'] = {}
        for ss in range(N.SCORE_FROM, int(S.max()) + 1):
            k = (S == ss) & ~np.isnan(a) & ~np.isnan(b) & haveC & (mask if mask is not None else True)
            if k.sum() > 100:
                out['bySeason'][ss] = r4((a[k] - b[k]).mean())
        out['pass'] = out['2015_21']['t'] <= -1.5 and out['2022_26']['d'] <= 0
        tests.append(out)
        print(json.dumps(out), flush=True)
        return out

    # (a) the model's total with a crew term
    TXa = {**TX, **{f'c_{t}': C[t] for t in targets}}
    for t in targets:
        pr = Fit.wf(mat(TXa, N.TFEATS + [f'c_{t}']), ty, S)
        o = judge(f'model total + crew {t}', pr, tbase, ty, 'model')
        m = k1 & haveC & ~np.isnan(tbase)
        o['coef'] = r4(np.linalg.lstsq(mat(TXa, N.TFEATS + [f'c_{t}'])[m], ty[m], rcond=None)[0][-1])
    pr = Fit.wf(mat(TXa, N.TFEATS + ['c_fta', 'c_pf', 'c_poss']), ty, S)
    judge('model total + crew fta, pf, poss', pr, tbase, ty, 'model')

    # (b) the market: does the crew move the total past the close (and the open)? close + b x crew, b fit on 2015-21
    for t in targets:
        for base_line, nm in ((tline, 'close'), (topen, 'open')):
            m = k1 & haveC & ~np.isnan(base_line)
            if m.sum() < 500:
                continue
            b = float(np.linalg.lstsq(C[t][m, None], (ty - base_line)[m], rcond=None)[0][0])
            o = judge(f'{nm} total + {b:.2f} x crew {t}', base_line + b * C[t], base_line, ty, 'market')
            o['b'] = r4(b)
    # the close already pricing the crew: open-to-close move on the crew effect
    mv = tline - topen
    for t in ('tot', 'fta', 'pf', 'poss'):
        out = {}
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            m = k & haveC & ~np.isnan(mv)
            if m.sum() > 100:
                out[nm] = {'slope': r4(np.polyfit(C[t][m], mv[m], 1)[0]), 'n': int(m.sum()),
                           'resid': r4(np.polyfit(C[t][m], (ty - tline)[m], 1)[0])}
        res.setdefault('openToClose', {})[t] = out
    # over/under hit rate vs the close when the crew leans 2+ points (signed by lean), held out
    lean = {}
    for t in ('tot', 'fta', 'pf'):
        b = None
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            m = k & haveC & ~np.isnan(tline) & (ty != tline)
            m0 = k1 & haveC & ~np.isnan(tline)
            if b is None:
                b = float(np.linalg.lstsq(C[t][m0, None], (ty - tline)[m0], rcond=None)[0][0])
            e = b * C[t]
            for cut in (1.0, 2.0, 3.0):
                q = m & (np.abs(e) >= cut)
                hit = ((np.sign(e) * (ty - tline))[q] > 0)
                lean.setdefault(t, {}).setdefault(nm, {})[str(cut)] = {'n': int(q.sum()), 'hit': r4(hit.mean()) if q.any() else None}
    res['lean'] = lean
    print('lean', json.dumps(lean), flush=True)

    # (c) players: free throws drawn and fouls
    res['players'] = players(G, C, refs, pick)

    pv = [min(x['2015_21']['p'] or 1, 1) for x in tests]
    q = H.bh(pv)
    for x, qq in zip(tests, q):
        x['q'] = r4(qq)
        x['pass'] = bool(x['pass'] and qq <= 0.10)
    res['tests'] = tests
    res['passed'] = [x['test'] for x in tests if x['pass']]
    print('passed', res['passed'], flush=True)
    json.dump(res, open(OUT_HL if HL else OUT, 'w'), indent=1)


def players(G, C, refs, pick):
    """nba_players' walk-forward rows; a crew term for points (his free-throw rate x the crew's extra attempts) and
    minutes (his foul rate x the crew's extra fouls), added to the shipped features and judged on squared error"""
    import nba_players as NP
    rows = NP.collect()
    FT = json.load(open(NP.FIT))
    gi = {g['id']: i for i, g in enumerate(G)}
    with gzip.open(NP.PHIST, 'rt') as f:
        box = json.load(f)
    # running rates per player before each game: FTA per minute (box col 13), PF per minute (refs hist)
    rate = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])   # fta, min (box), pf, min (refs)
    pre = {}
    for g in sorted(G, key=lambda g: g['tip']):
        if g['S'] < 2019:
            continue
        b, r = box.get(g['id']), refs.get(g['id'])
        pre[g['id']] = {}
        for t in (b or {}):
            for row in b[t]:
                a = rate[row[0]]
                pre[g['id']][row[0]] = (a[0] / a[1] if a[1] > 50 else None, a[2] / a[3] if a[3] > 50 else None)
        if b:
            for t in b:
                for row in b[t]:
                    if row[4]:
                        a = rate[row[0]]; a[0] += row[13]; a[1] += row[4]
        if r:
            for t in r['p']:
                for pid, mn, f in r['p'][t]:
                    a = rate[pid]; a[2] += f; a[3] += mn
    lgf = np.nanmean([v[0] for d in pre.values() for v in d.values() if v[0] is not None])
    lgp = np.nanmean([v[1] for d in pre.values() for v in d.values() if v[1] is not None])
    D = [r for r in rows if r['y'] and r['nv'] and r['mS'] >= 10 and not r['po'] and r['g'] in gi]
    S = np.array([r['S'] for r in D])
    ok = np.array([bool(C['fta'][gi[r['g']]] or C['pf'][gi[r['g']]]) for r in D])
    tune, hold = np.isin(S, NP.TUNE), np.isin(S, NP.HOLD)
    gid = np.array([r['g'] for r in D])
    out = {'rows': len(D), 'withCrew': int(ok.sum()), 'lgFtaPerMin': r4(lgf), 'lgPfPerMin': r4(lgp)}
    for s, ci, ct in (('pts', 'fta', 'ftr'), ('min', 'pf', 'pfr'), ('pts', 'pf', 'pfr'), ('min', 'fta', 'ftr')):
        feats = FT['stats'][s]['feats']
        Xm = np.column_stack([np.array([r['fx'][s][f] for r in D]) for f in feats])
        Y = np.array([r['y'][('min', 'pts', 'reb', 'ast').index(s)] for r in D])
        def extra(r):
            fr, pr = pre.get(r['g'], {}).get(r['p'], (None, None))
            c = C[ci][gi[r['g']]]
            if ct == 'ftr':
                return r['mS'] * (fr if fr is not None else lgf) / (lgf * 2 * 10) * c   # his share of the crew's extra FTA
            return r['mS'] * (pr if pr is not None else lgp) / (lgp * 2 * 10) * c
        xe = np.array([extra(r) for r in D])
        def wfp(A):
            pred = np.full(len(S), np.nan)
            for yr in sorted(set(S)):
                tr, te = (S < yr), S == yr
                if tr.sum() < 1000:
                    continue
                pred[te] = A[te] @ np.linalg.lstsq(A[tr], Y[tr], rcond=None)[0]
            return pred
        p0, p1 = wfp(Xm), wfp(np.column_stack([Xm, xe]))
        e0, e1 = (Y - p0) ** 2, (Y - p1) ** 2
        o = {'stat': s, 'crew': ci}
        for nm, k in (('tune', tune & ok), ('hold', hold & ok)):
            k = k & ~np.isnan(e0) & ~np.isnan(e1)
            p = H.paired(e1[k], e0[k], [gid[k]])
            o[nm] = {'d': r4(p['d']), 't': round(p['t'], 2), 'p': r4(p['p']), 'n': p['n']}
        m = tune & ok & ~np.isnan(p0)
        o['coef'] = r4(np.linalg.lstsq(np.column_stack([Xm, xe])[m], Y[m], rcond=None)[0][-1])
        o['pass'] = o['tune']['t'] <= -1.5 and o['hold']['d'] <= 0
        out[f'{s}~{ci}'] = o
        print('player', json.dumps(o), flush=True)
    return out


if __name__ == '__main__':
    main()
