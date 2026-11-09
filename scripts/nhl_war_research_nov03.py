#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL WAR / pWAR research, Nov 3 2026 -> data/nhl_war_research_nov03.json

Pre-registered before any test was run:
  A  audit: pWAR's reported LOSO R2 picks the Marcel weights, K, KG, lam and the forward-selected columns on every
     season, held-out one included. Report a fully nested number (all of those chosen on the 16 other seasons).
  C1 traded players: MoneyPuck's season summary is one row a player, credited to his last team. Split each skater and
     goalie season across his teams by stats-API game-log ice time. Scored on pWAR nested LOSO team GD/GP MSE (paired
     by season) and descriptive same-season team GD R2.
  C2 per-component shrink: one K for on-ice components (evf eva pp pk), another for individual ones (g ixg a1 a2 pen),
     both in the nested grid. Scored on pWAR nested LOSO team GD/GP MSE.
  C3 goalie projection as GSAx per expected goal faced (Marcel, shrunk by xGA faced) x league xGA/60, instead of GSAx
     per 60 shrunk by ice time. Scored on next-season GSAx/60 (LOSO-calibrated, weighted by next-season ice time),
     then on pWAR nested LOSO team GD/GP MSE (must not lose: t > -1).
  Batch: Holm over C1-C3 at .05 on the season-paired t (17 seasons, df 16).
  Changed after the first look (sanity run, before C2/C3 were run): the summary's team is the mover's last team in the
  game logs (1,158 of 1,165 movers), so C1 is a correctness fix (the last team was credited ice time a mover spent
  elsewhere, a within-season choice that tracks results, e.g. deadline buyers). It is judged on the descriptive check;
  C2 and C3 are scored against the split design, and Holm covers C2-C3.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nhl_data as D
import nhl_players as P

OUT = os.path.join(os.path.dirname(HERE), 'data', 'nhl_war_research_nov03.json')
LAST = D.current_season() - 1          # last complete season
SEAS = list(range(P.FIRST - 1, LAST + 1))
TGT = list(range(P.FIRST + 1, LAST + 1))
WTS = P.WTS
KS = [3600 * k for k in (5, 10, 20, 40)]
KGS = [3600 * k for k in (50, 100, 200, 400, 800)]
LAMS = (0.3, 1.0, 3.0, 10.0)
ON, IND = ['evf', 'eva', 'pp', 'pk'], ['g', 'ixg', 'a1', 'a2', 'pen']
NAMES = P.COMPS + ['gsax'] + P.PRIORS


def tdist_p(t, df):
    try:
        from scipy import stats
        return float(2 * stats.t.sf(abs(t), df))
    except ImportError:
        return float(math.erfc(abs(t) / math.sqrt(2)))


def splits(S):
    """{pid: {team: ice time s}} from stats-API regular-season game logs, skaters and goalies"""
    sp = defaultdict(lambda: defaultdict(float))
    for row in D._logs('skater', S, 2, False):
        sp[str(row[1])][row[3]] += float(row[5] or 0)
    gp = defaultdict(lambda: defaultdict(float))
    for row in D._logs('goalie', S, 2, False):
        gp[str(row[1])][row[3]] += float(row[5] or 0)
    return sp, gp


def pieces(r, sp):
    """(team, ice time) pieces of a season row: by game-log share when the player played for 2+ teams"""
    s = sp.get(r['id'])
    if not s or len(s) < 2:
        return [(r['tm'], r['toi'])]
    tot = sum(s.values())
    return [(t, r['toi'] * v / tot) for t, v in s.items() if v > 0]


def load():
    sk = {S: P.skaters(S) for S in SEAS}
    gk = {S: P.goalies(S) for S in SEAS}
    res = {S: P.team_results(S) for S in SEAS}
    spl = {S: splits(S) for S in range(P.FIRST, LAST + 1)}
    return sk, gk, res, spl


def sums(sk, gk, wts):
    """per target season: skater rows [(pid, pos, toi, team)] with Marcel numerators (weighted toi x rate) and
    weighted toi; goalies the same for gsax60, and for GSAx / xGA faced"""
    six = {S: {r['id']: r for r in sk[S]} for S in SEAS}
    gix = {S: {r['id']: r for r in gk[S]} for S in SEAS}
    out = {}
    for S in TGT:
        srows = []
        for r in sk[S]:
            h = [(w, p) for w, p in P.history(r['id'], six, S, wts) if p]
            wt = sum(w * p['toi'] for w, p in h)
            num = np.array([sum(w * p['toi'] * p[c] for w, p in h) for c in P.COMPS])
            srows.append((r, wt, num))
        grows = []
        for r in gk[S]:
            h = [(w, p) for w, p in P.history(r['id'], gix, S, wts) if p]
            wt = sum(w * p['toi'] for w, p in h)
            num = sum(w * p['toi'] * p['gsax60'] for w, p in h)
            wx = sum(w * p['xga'] for w, p in h)
            nx = sum(w * (p['xga'] - p['ga']) for w, p in h)
            grows.append((r, wt, num, wx, nx))
        out[S] = (srows, grows)
    return out


def lg_xga60(gk, S):
    t = sum(r['toi'] for r in gk[S - 1]) / 3600
    return sum(r['xga'] for r in gk[S - 1]) / t


def design(sm, res, spl, gk, K, KG, Kind=None, split=False, gmode='60', KX=None):
    """team-season rows as P.fit's design (norm=True, prior=True). Kind: K for individual components (None = K).
    split: ice time split across teams. gmode '60' (shipped) or 'x' (GSAx per xGA faced, KX pseudo xGA)"""
    Kind = K if Kind is None else Kind
    kv = np.array([Kind if c in IND else K for c in P.COMPS], float)
    X, y, keys = [], [], []
    nc = len(NAMES)
    for S in TGT:
        srows, grows = sm[S]
        sp, gp = spl[S] if split else ({}, {})
        tt, tg = defaultdict(float), defaultdict(float)
        sp_rows = [(r, wt, num, pieces(r, sp)) for r, wt, num in srows]
        gp_rows = [(r, wt, num, wx, nx, pieces(r, gp)) for r, wt, num, wx, nx in grows]
        for r, _, _, pc in sp_rows:
            for t, s in pc:
                tt[t] += s
        for r, *_, pc in gp_rows:
            for t, s in pc:
                tg[t] += s
        agg = defaultdict(lambda: np.zeros(nc))
        for r, wt, num, pc in sp_rows:
            m = num / (wt + kv)
            sh = K / (wt + K)
            v = np.concatenate([m, [0.0, sh, sh * (r['pos'] == 'D'), 0.0]])
            for t, s in pc:
                if t not in res[S]:
                    continue
                agg[t] += v * (s / tt[t] * 5 * res[S][t][2])
        L60 = lg_xga60(gk, S)
        for r, wt, num, wx, nx, pc in gp_rows:
            if gmode == '60':
                g, sh = num / (wt + KG), KG / (wt + KG)
            else:
                g, sh = nx / (wx + KX) * L60, KX / (wx + KX)
            for t, s in pc:
                if t not in res[S]:
                    continue
                h = s / tg[t] * res[S][t][2]
                agg[t][len(P.COMPS)] += g * h
                agg[t][-1] += sh * h
        for t, v in sorted(agg.items()):
            gdpg, ppg, gpn = res[S][t]
            X.append(v / gpn); y.append(gdpg); keys.append(S)
    return np.array(X), np.array(y), np.array(keys)


def ridge_pred(Xtr, ytr, Xte, lam):
    A = np.column_stack([Xtr, np.ones(len(Xtr))])
    R = lam * np.eye(A.shape[1]); R[-1, -1] = 0
    b = np.linalg.solve(A.T @ A + R, A.T @ ytr)
    return np.column_stack([Xte, np.ones(len(Xte))]) @ b


def loso(X, y, S_, cols, lam, seasons=None):
    pred = np.full(len(y), np.nan)
    for s in (seasons if seasons is not None else sorted(set(S_))):
        tr, te = (S_ != s), (S_ == s)
        if seasons is not None:
            tr &= np.isin(S_, seasons)
        pred[te] = ridge_pred(X[tr][:, cols], y[tr], X[te][:, cols], lam)
    return pred


def fwd(X, y, S_, lam, seasons):
    """P.fit's forward selection from the core, on the given seasons only"""
    m = np.isin(S_, seasons)
    keep = [NAMES.index(c) for c in ('evf', 'eva', 'gsax', 'pl', 'pD', 'gpl')]
    while True:
        cur = ((loso(X, y, S_, keep, lam, seasons) - y)[m]) ** 2
        cand = []
        for j in range(len(NAMES)):
            if j in keep:
                continue
            d = ((loso(X, y, S_, keep + [j], lam, seasons) - y)[m]) ** 2 - cur
            cand.append((float(-d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), j))
        if not cand:
            break
        t, j = max(cand)
        if t < 1.5:
            break
        keep.append(j)
    return keep


def nested(designs):
    """designs: {config: (X, y, S_)}. For each held-out season: pick config + lam by inner LOSO (all columns) on the
    other seasons, forward-select there, fit there, predict the held-out season. Returns predictions, y, S_, choices"""
    cfg0 = next(iter(designs))
    y, S_ = designs[cfg0][1], designs[cfg0][2]
    allc = list(range(len(NAMES)))
    # inner errors: for each config/lam, the LOSO prediction of each season from all others except one outer season
    pred = np.zeros(len(y))
    picks = {}
    for s in sorted(set(S_)):
        inner = [x for x in sorted(set(S_)) if x != s]
        mi = np.isin(S_, inner)
        best = None
        for cfg, (X, _, _) in designs.items():
            for lam in LAMS:
                e = float((((loso(X, y, S_, allc, lam, inner) - y)[mi]) ** 2).mean())
                if best is None or e < best[0]:
                    best = (e, cfg, lam)
        _, cfg, lam = best
        X = designs[cfg][0]
        keep = fwd(X, y, S_, lam, inner)
        te = S_ == s
        pred[te] = ridge_pred(X[mi][:, keep], y[mi], X[te][:, keep], lam)
        picks[int(s)] = {'cfg': str(cfg), 'lam': lam, 'keep': [NAMES[j] for j in keep]}
        print(' outer', s, picks[int(s)], flush=True)
    return pred, y, S_, picks


def season_paired(pa, pb, y, S_):
    """b vs a: per-season MSE difference (a - b, positive = b better), paired t over seasons, seasons improved"""
    ss = sorted(set(S_))
    d = np.array([((pa - y)[S_ == s] ** 2).mean() - ((pb - y)[S_ == s] ** 2).mean() for s in ss])
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    base = float(((y - y.mean()) ** 2).mean())
    return {'r2A': round(1 - float(((pa - y) ** 2).mean()) / base, 4), 'r2B': round(1 - float(((pb - y) ** 2).mean()) / base, 4),
            't': round(t, 2), 'p': round(tdist_p(t, len(d) - 1), 4), 'improved': int((d > 0).sum()), 'seasons': len(d)}


def shipped_protocol(designs):
    """P.fit as shipped: config, lam and columns chosen on every season, then LOSO"""
    allc = list(range(len(NAMES)))
    best = None
    for cfg, (X, y, S_) in designs.items():
        for lam in LAMS:
            e = float(((loso(X, y, S_, allc, lam) - y) ** 2).mean())
            if best is None or e < best[0]:
                best = (e, cfg, lam)
    _, cfg, lam = best
    X, y, S_ = designs[cfg]
    keep = fwd(X, y, S_, lam, sorted(set(S_)))
    return loso(X, y, S_, keep, lam), {'cfg': str(cfg), 'lam': lam, 'keep': [NAMES[j] for j in keep]}


def desc_check(sk, gk, res, spl, split):
    """descriptive WAR summed by team vs same-season team GD/GP; per-season squared errors"""
    pv = {S: P.pen_value(S) for S in TGT}
    ys, ps, ss = [], [], []
    for S in [P.FIRST] + TGT:
        a = [dict(r) for r in P.skaters(S)]
        g = [dict(r) for r in P.goalies(S)]
        if split:
            sp, gpp = spl[S]
            a = [dict(r, tm=t, toi=s) for r in a for t, s in pieces(r, sp)]
            g = [dict(r, tm=t, toi=s) for r in g for t, s in pieces(r, gpp)]
        P.describe(S, a, g, pv.get(S) or P.pen_value(S))
        tot = defaultdict(float)
        for r in a + g:
            tot[r['tm']] += r['dr'] * r['toi'] / 3600
        for t, (gd, ppg, gpn) in res[S].items():
            if t in tot:
                ys.append(gd); ps.append(tot[t] / gpn); ss.append(S)
    return np.array(ys), np.array(ps), np.array(ss)


def goalie_next(sk, gk, KG, KX, wts):
    """goalie projections for next season: (S, pred60 shipped form, pred60 per-xGA form, actual GSAx60, next toi)"""
    gix = {S: {r['id']: r for r in gk[S]} for S in SEAS}
    rows = []
    for S in TGT:
        L60 = lg_xga60(gk, S)
        for r in gk[S]:
            h = [(w, p) for w, p in P.history(r['id'], gix, S, wts) if p]
            if not h:
                continue
            wt = sum(w * p['toi'] for w, p in h)
            a = sum(w * p['toi'] * p['gsax60'] for w, p in h) / (wt + KG)
            wx = sum(w * p['xga'] for w, p in h)
            b = sum(w * (p['xga'] - p['ga']) for w, p in h) / (wx + KX) * L60
            rows.append((S, a, b, r['gsax60'], r['toi']))
    return np.array(rows)


def wcal_mse(x, yv, w, S_):
    """LOSO linear calibration of y on x, toi-weighted MSE per season"""
    out = {}
    for s in sorted(set(S_)):
        tr, te = S_ != s, S_ == s
        A = np.column_stack([x[tr], np.ones(tr.sum())]) * np.sqrt(w[tr])[:, None]
        b = np.linalg.lstsq(A, yv[tr] * np.sqrt(w[tr]), rcond=None)[0]
        p = b[0] * x[te] + b[1]
        out[s] = float((w[te] * (p - yv[te]) ** 2).sum() / w[te].sum())
    return out


def main():
    sk, gk, res, spl = load()
    print('loaded', flush=True)
    sm = {wts: sums(sk, gk, wts) for wts in WTS}
    out = {}

    def grid(**kw):
        d = {}
        for wts in WTS:
            for K in KS:
                for KG in KGS:
                    d[(wts, K, KG)] = design(sm[wts], res, spl, gk, K, KG, **kw)
        return d

    base = grid()
    p_ship, ch = shipped_protocol(base)
    p_base, y, S_, picks0 = nested(base)
    out['A_audit'] = {'shippedProtocol': ch, 'cmp': season_paired(p_ship, p_base, y, S_),
                      'note': 'A = shipped protocol (tuning sees held-out season), B = fully nested'}
    print('A', out['A_audit'], flush=True)
    # C1 traded split (a correctness fix: the last team gets a mover's whole season)
    sp_grid = grid(split=True)
    p_s_ship, ch1 = shipped_protocol(sp_grid)
    p_c1, _, _, picks1 = nested(sp_grid)
    out['C1_split'] = season_paired(p_base, p_c1, y, S_)
    out['C1_splitAudit'] = {'shippedProtocol': ch1, 'cmp': season_paired(p_s_ship, p_c1, y, S_)}
    yd, pd0, sd = desc_check(sk, gk, res, spl, False)
    _, pd1, _ = desc_check(sk, gk, res, spl, True)
    out['C1_desc'] = season_paired(pd0, pd1, yd, sd)
    out['C1_desc']['slopeA'] = round(float(np.polyfit(pd0, yd, 1)[0]), 3)
    out['C1_desc']['slopeB'] = round(float(np.polyfit(pd1, yd, 1)[0]), 3)
    print('C1', out['C1_split'], out['C1_splitAudit'], out['C1_desc'], flush=True)
    # C2 per-component K (on the split design)
    d2 = {}
    for wts in WTS:
        for K in KS:
            for Ki in KS:
                for KG in (3600 * 200, 3600 * 400, 3600 * 800):
                    d2[(wts, K, Ki, KG)] = design(sm[wts], res, spl, gk, K, KG, Kind=Ki, split=True)
    p_c2, _, _, picks2 = nested(d2)
    out['C2_perK'] = season_paired(p_c1, p_c2, y, S_)
    print('C2', out['C2_perK'], flush=True)
    # C3 goalie per-xGA: next-season GSAx first
    KXS = (100, 200, 400, 800, 1600, 3200)
    gn = {}
    for wts in WTS:
        for KG in KGS:
            for KX in KXS:
                gn[(wts, KG, KX)] = goalie_next(sk, gk, KG, KX, wts)
    ss = sorted(set(TGT))
    ea, eb = {}, {}
    cache = {k: (wcal_mse(v[:, 1], v[:, 3], v[:, 4], v[:, 0]), wcal_mse(v[:, 2], v[:, 3], v[:, 4], v[:, 0])) for k, v in gn.items()}
    for s in ss:
        def tot(m):
            return sum(v for k, v in m.items() if k != s)
        ka = min(gn, key=lambda k: tot(cache[k][0]))
        kb = min(gn, key=lambda k: tot(cache[k][1]))
        ea[s], eb[s] = cache[ka][0][s], cache[kb][1][s]
    d = np.array([ea[s] - eb[s] for s in ss])
    tg = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    out['C3_goalieNext'] = {'mseA': round(float(np.mean([ea[s] for s in ss])), 4), 'mseB': round(float(np.mean([eb[s] for s in ss])), 4),
                            't': round(tg, 2), 'p': round(tdist_p(tg, len(d) - 1), 4), 'improved': int((d > 0).sum()), 'seasons': len(d)}
    print('C3 next', out['C3_goalieNext'], flush=True)
    d3 = {}
    for wts in WTS:
        for K in KS:
            for KX in (200, 800, 3200):
                d3[(wts, K, KX)] = design(sm[wts], res, spl, gk, K, None, gmode='x', KX=KX, split=True)
    p_c3, _, _, picks3 = nested(d3)
    out['C3_teamGD'] = season_paired(p_c1, p_c3, y, S_)
    print('C3 GD', out['C3_teamGD'], flush=True)
    # Holm over C2-C3 (C1 is a correctness fix, judged on the descriptive check; C2/C3 against the split design)
    prim = [('C2', out['C2_perK']), ('C3', out['C3_goalieNext'])]
    order = sorted(prim, key=lambda kv: kv[1]['p'])
    holm, alive = {}, True
    for i, (k, v) in enumerate(order):
        thr = 0.05 / (len(order) - i)
        ok = alive and v['t'] > 0 and v['p'] < thr
        alive = ok
        holm[k] = {'p': v['p'], 'thr': round(thr, 4), 'pass': bool(ok)}
    if holm['C3']['pass'] and out['C3_teamGD']['t'] <= -1:
        holm['C3']['pass'] = False
    out['holm'] = holm
    out['picks'] = {'base': picks0, 'C1': picks1, 'C2': picks2, 'C3': picks3}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(holm), flush=True)


def leak_check():
    """the shipped Oct 25 model on both team credits: does crediting a mover's whole season to his last team predict
    team GD beyond the split (a sign the last team carries within-season results)?"""
    sk, gk, res, spl = load()
    sm = sums(sk, gk, (1, .7, .5))
    keep = [NAMES.index(c) for c in ('evf', 'eva', 'gsax', 'pl', 'pD', 'gpl', 'a1', 'pk')]
    X0, y, S_ = design(sm, res, spl, gk, 36000, 1440000, split=False)
    X1, _, _ = design(sm, res, spl, gk, 36000, 1440000, split=True)
    p0, p1 = loso(X0, y, S_, keep, 3.0), loso(X1, y, S_, keep, 3.0)
    b = float(((y - y.mean()) ** 2).mean())
    d, e = p0 - p1, y - p1
    out = json.load(open(OUT))
    out['C1_leak'] = {'r2LastTeam': round(1 - float(((p0 - y) ** 2).mean()) / b, 4),
                      'r2Split': round(1 - float(((p1 - y) ** 2).mean()) / b, 4),
                      'corrGapResid': round(float(np.corrcoef(d, e)[0, 1]), 3),
                      'slopeGapResid': round(float(np.polyfit(d, e, 1)[0]), 3)}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(out['C1_leak'])


if __name__ == '__main__':
    leak_check() if '--leak' in sys.argv else main()
