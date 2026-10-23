#!/usr/bin/env python3
"""Residual learner over the failed-input pool (team model idea 11, Oct 23 2026). Research only.

    python3 scripts/residual_research.py            # nba nfl cbb -> data/residual_research.json
    python3 scripts/residual_research.py nba        # one sport

Each game model's walk-forward margin prediction (the shipped design, rebuilt as scripts/harness_rescore.py does)
leaves a residual. One shallow boosted tree (depth 2, monotone in each input, numpy) learns that residual from the
pool of inputs that failed as linear terms (rest/travel/b2b splits, altitude, early-season, epa, weather, FT luck,
game control, ...) plus the shipped inputs themselves, so it can find interactions and bends a linear term misses.
Settings are fixed up front; the number of rounds is picked by a season walk inside the tune years; the tree is then
fit on the tune years once and scored on the held-out years once (no re-tuning). Abs margin error, paired per game,
cluster-robust (game day x home team-season, NFL week x home team-season). Any interaction it leans on is promoted
to a named linear term and re-tested in the ordinary walk.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H

OUT = os.path.join(ROOT, 'data', 'residual_research.json')
CACHE = os.path.join(HERE, '.cache', 'residual')
# fixed before any held-out look
DEPTH, LR, BINS, LAM, MAXR, MINLEAF, CLIP = 2, 0.05, 24, 50.0, 400, 0.02, 2.5


def jload(name):
    return json.load(open(os.path.join(ROOT, 'data', name)))


# ---------------------------------------------------------------- boosted tree (depth 2, monotone, histogram)
def bins_of(Xp, lo_rows):
    """quantile bin edges from the training rows only"""
    E = []
    for j in range(Xp.shape[1]):
        v = Xp[lo_rows, j]
        v = v[~np.isnan(v)]
        e = np.unique(np.quantile(v, np.linspace(0, 1, BINS + 1)[1:-1])) if len(v) else np.array([])
        E.append(e)
    return E


def binned(Xp, E):
    B = np.zeros(Xp.shape, np.int16)
    for j, e in enumerate(E):
        B[:, j] = np.searchsorted(e, np.nan_to_num(Xp[:, j]), side='right')
    return B


def best_split(B, g, rows, sign, lo, hi, minleaf, skip=-1):
    """the best (feature, bin) split of rows on gradient g (= residual), leaf values bounded [lo, hi] and ordered by sign"""
    best = (0.0, None)
    gr, n = g[rows], len(rows)
    tot = gr.sum()
    base = tot * tot / (n + LAM)
    nb, J = BINS + 1, B.shape[1]
    flat = (B[rows].astype(np.int64) + np.arange(J) * nb).ravel()
    S_ = np.bincount(flat, np.repeat(gr, J), J * nb).reshape(J, nb)
    C_ = np.bincount(flat, minlength=J * nb).reshape(J, nb).astype(float)
    sl, cl = np.cumsum(S_, 1)[:, :-1], np.cumsum(C_, 1)[:, :-1]
    sr, cr = tot - sl, n - cl
    sg = np.asarray(sign, float)[:, None]
    ok = (cl >= minleaf) & (cr >= minleaf) & (sg != 0)
    if skip >= 0:
        ok[skip] = False
    wl, wr = np.clip(sl / (cl + LAM), lo, hi), np.clip(sr / (cr + LAM), lo, hi)
    ok &= (wr - wl) * sg >= 0                      # monotone: the higher bin never gets the lower value
    gain = np.where(ok, 2 * (sl * wl + sr * wr) - (cl + LAM) * wl ** 2 - (cr + LAM) * wr ** 2 - base, -np.inf)
    j, k = np.unravel_index(int(np.argmax(gain)), gain.shape)
    if gain[j, k] > best[0]:
        best = (float(gain[j, k]), (int(j), int(k), float(wl[j, k]), float(wr[j, k])))
    return best


def grow(B, g, rows, sign, minleaf):
    """one depth-2 tree: (j, k, [(j2, k2, wl, wr) | w for each side]); LightGBM-style bounds keep it monotone"""
    gain, sp = best_split(B, g, rows, sign, -np.inf, np.inf, minleaf)
    if sp is None:
        return None, []
    j, k, wl, wr = sp
    mid = (wl + wr) / 2
    bl, br = ((-np.inf, mid), (mid, np.inf)) if sign[j] > 0 else ((mid, np.inf), (-np.inf, mid))
    kids, pairs = [], []
    for side, (lo, hi), w in ((B[rows, j] <= k, bl, wl), (B[rows, j] > k, br, wr)):
        r = rows[side]
        g2, sp2 = best_split(B, g, r, sign, lo, hi, minleaf, skip=j) if DEPTH > 1 else (0, None)
        if sp2 is None:
            kids.append(w)
        else:
            kids.append(sp2)
            pairs.append((j, sp2[0], g2))
    return (j, k, kids, gain), pairs


def apply_tree(t, B):
    j, k, kids, _ = t
    out = np.zeros(len(B))
    for side, kid in ((B[:, j] <= k, kids[0]), (B[:, j] > k, kids[1])):
        if isinstance(kid, tuple):
            j2, k2, wl, wr = kid
            out[side] = np.where(B[side, j2] <= k2, wl, wr)
        else:
            out[side] = kid
    return out


def boost(Xp, r, tr, rounds=MAXR):
    """fit on rows tr; returns a predictor giving the path of every round count, plus split usage"""
    E = bins_of(Xp, tr)
    B = binned(Xp, E)
    rows = np.where(tr)[0]
    sd = np.std(r[rows])
    rc = np.clip(r, -CLIP * sd, CLIP * sd)
    # monotone direction of each input: the sign of its slope on the training residual (0: constant input, unused)
    sign = np.zeros(Xp.shape[1])
    for j in range(Xp.shape[1]):
        x = np.nan_to_num(Xp[rows, j])
        if x.std() > 0:
            sign[j] = 1.0 if np.cov(x, rc[rows])[0, 1] >= 0 else -1.0
    minleaf = max(150, int(MINLEAF * len(rows)))
    f = np.zeros(len(r))
    trees, use, pair = [], np.zeros(Xp.shape[1]), {}
    for _ in range(rounds):
        t, pp = grow(B, rc - f, rows, sign, minleaf)
        if t is None:
            break
        f += LR * apply_tree(t, B)
        trees.append(t)
        use[t[0]] += t[3]
        for a, b, gg in pp:
            key = tuple(sorted((a, b)))
            pair[key] = pair.get(key, 0.0) + gg
    def path(Bq):
        cur, P = np.zeros(len(Bq)), []
        for t in trees:
            cur = cur + LR * apply_tree(t, Bq)
            P.append(cur.copy())
        return P
    return {'E': E, 'B': B, 'path': path, 'n': len(trees), 'use': use, 'pair': pair, 'sign': sign}


# ---------------------------------------------------------------- the test
def run(sp, d):
    y, base, S = d['y'], d['pred'], d['S']
    names, Xp = d['pool_names'], np.column_stack([d['pool'][k] for k in d['pool_names']]).astype(float)
    ok = ~np.isnan(base)
    t0, t1 = d['tune']
    tune, held = H.season_masks(S, (t0, t1), d['held'], ok & d.get('ok', ok))
    r = y - base
    cl = d['cl']
    # 1) rounds by a season walk inside the tune years (each tune season from the tune seasons before it)
    curve = np.zeros(MAXR + 1)
    walk = np.full(len(y), np.nan)
    wpaths = {}
    for s in range(t0 + 2, t1 + 1):
        tr, te = tune & (S < s), tune & (S == s)
        m = boost(Xp, r, tr)
        P = m['path'](binned(Xp, m['E'])[te]) if m['n'] else []
        a0 = np.abs(r[te]).sum()
        curve[0] += a0
        for i in range(MAXR):
            curve[i + 1] += np.abs(r[te] - P[min(i, len(P) - 1)]).sum() if P else a0
        wpaths[s] = (te, P)
    nr = int(np.argmin(curve))
    tw = tune & (S >= t0 + 2)
    for s, (te, P) in wpaths.items():
        walk[te] = base[te] + (P[nr - 1] if nr and P else 0.0)
    # 2) fit once on every tune season with those rounds; score the held-out years once
    out = {'pool': names, 'rounds': nr, 'tuneCurve': [round(float(c / tw.sum()), 4) for c in curve[::25]]}
    lb = H.ae(base, y)
    tw_t = H.paired(H.ae(walk, y)[tw], lb[tw], [c[tw] for c in cl])
    out['tune'] = {k: round(v, 4) if isinstance(v, float) else v for k, v in tw_t.items()}
    out['tune']['note'] = 'season walk inside tune; rounds picked on this same walk (optimistic)'
    if nr == 0:
        out['held'] = {'d': 0.0, 't': 0.0, 'n': int(held.sum()), 'note': 'no rounds helped on tune: learner is zero'}
        out['verdict'] = 'fail'
        return out
    m = boost(Xp, r, tune, nr)
    fx = m['path'](binned(Xp, m['E']))[-1]
    new = base + fx
    d['learner'] = fx
    hp = H.paired(H.ae(new, y)[held], lb[held], [c[held] for c in cl])
    out['held'] = {k: round(v, 4) if isinstance(v, float) else v for k, v in hp.items()}
    out['heldMae'] = [round(float(lb[held].mean()), 4), round(float(H.ae(new, y)[held].mean()), 4)]
    if 'line' in d:
        L = held & ~np.isnan(d['line'])
        out['heldLined'] = {k: round(v, 4) if isinstance(v, float) else v for k, v in H.paired(H.ae(new, y)[L], lb[L], [c[L] for c in cl]).items()}
    tot = m['use'].sum() or 1.0
    out['use'] = {names[j]: round(float(m['use'][j] / tot), 3) for j in np.argsort(-m['use']) if m['use'][j] > 0}
    pt = sum(m['pair'].values()) or 1.0
    out['pairs'] = [[names[a], names[b], round(v / pt, 3)] for (a, b), v in sorted(m['pair'].items(), key=lambda kv: -kv[1])[:8]]
    z = H.stouffer([-out['tune']['t'], -out['held']['t']])
    out['z'] = round(z, 3)
    out['verdict'] = 'pass' if out['held']['t'] < -1.645 and out['tune']['t'] < 0 else 'fail'
    return out


def promote(sp, d, res, k=4):
    """each top interaction (and each top single input) as a named linear term in the shipped walk"""
    y, S, cl = d['y'], d['S'], d['cl']
    t0, t1 = d['tune']
    base = d['pred']
    ok = ~np.isnan(base)
    tune, held = H.season_masks(S, (t0, t1), d['held'], ok & d.get('ok', ok))
    lb = H.ae(base, y)
    z = lambda v: (v - np.nanmean(v[tune])) / (np.nanstd(v[tune]) or 1.0)
    cands = [(f'{a}*{b}', np.nan_to_num(z(d['pool'][a]) * z(d['pool'][b]))) for a, b, _ in res.get('pairs', [])[:k]]
    cands += [(a, np.nan_to_num(z(d['pool'][a]))) for a in list(res.get('use', {}))[:k] if a not in d['shipped']]
    rows = []
    for name, v in cands:
        p = d['walk'](v)
        a = H.ae(p, y)
        tt = H.paired(a[tune], lb[tune], [c[tune] for c in cl])
        hh = H.paired(a[held], lb[held], [c[held] for c in cl])
        rows.append({'term': name, 'tune': [round(tt['d'], 4), round(tt['t'], 2)], 'held': [round(hh['d'], 4), round(hh['t'], 2)],
                     'pass': bool(tt['t'] < -1.645 and hh['t'] < -1.645)})
    return rows


def detail(sp, d, res):
    """where the held-out gain sits (season phase, games with a closing line), and the tree's season-phase bend as
    named hinge terms: input x max(0, 1 - day/K), K picked on tune"""
    y, S, cl, base = d['y'], d['S'], d['cl'], d['pred']
    t0, t1 = d['tune']
    ok = ~np.isnan(base)
    tune, held = H.season_masks(S, (t0, t1), d['held'], ok & d.get('ok', ok))
    lb, ln = H.ae(base, y), H.ae(base + d['learner'], y)
    sday = d['pool']['sday']
    lined = ~np.isnan(d['line'])
    parts = {}
    for lab, m in (('day<30', sday < 30), ('day30-60', (sday >= 30) & (sday < 60)), ('day60+', sday >= 60),
                   ('lined', lined), ('no line', ~lined)):
        h = held & m
        p = H.paired(ln[h], lb[h], [c[h] for c in cl])
        parts[lab] = [round(p['d'], 4), round(p['t'], 2), int(p['n'])]
    hinge = []
    for f in ('pred', 'form', 'early', 'mkteff', 'eff', 'mkt'):
        if f not in d['pool']:
            continue
        best = None
        for K in (20, 40, 60, 90):
            v = np.nan_to_num(d['pool'][f]) * np.maximum(0.0, 1 - sday / K)
            a = H.ae(d['walk'](v), y)
            tt = H.paired(a[tune], lb[tune], [c[tune] for c in cl])
            if best is None or tt['t'] < best[1]['t']:
                best = (K, tt, a)
        K, tt, a = best
        hh = H.paired(a[held], lb[held], [c[held] for c in cl])
        hl = H.paired(a[held & lined], lb[held & lined], [c[held & lined] for c in cl])
        hinge.append({'term': f'{f}*fade{K}', 'tune': [round(tt['d'], 4), round(tt['t'], 2)], 'held': [round(hh['d'], 4), round(hh['t'], 2)],
                      'heldLined': [round(hl['d'], 4), round(hl['t'], 2)], 'pass': bool(tt['t'] < -1.645 and hh['t'] < -1.645)})
    return {'heldBy': parts, 'hinge': hinge}


# ---------------------------------------------------------------- adapters: shipped walk + failed pool
def season_day(dates, S):
    """days since each season's first game"""
    d = np.array([np.datetime64(x[:10]) for x in dates])
    out = np.zeros(len(d))
    for s in np.unique(S):
        m = S == s
        out[m] = (d[m] - d[m].min()).astype(int)
    return out


def nba():
    import nba_games as N
    import nba_games_fit as NF
    F = jload('nba_games_fit.json')
    games, names = N.load_hist()
    inj = NF.load_inj()
    P, prm, feats = F['P'], dict(F['params']), list(F['feats'])
    D, X, TX, y, ty, S, line, tline = NF.design(games, names, P, prm, inj, feats)
    full = NF.wf(NF.mat(X, feats), y, S)
    xs = lambda k: np.array([float(x.get(k) or 0.0) for _, x, _ in D])
    txs = lambda k: np.array([float(tx.get(k) or 0.0) for _, _, tx in D])
    pool = {k: X[k].astype(float) for k in X}
    for k in ('effO', 'effD', 'gpn', 'linE', 'rosterE', 'pelo', 'mpri'):
        pool[k] = xs(k)
    for k in ('tpace', 'teff', 'tpri', 'pts', 'tmkt'):
        pool['t:' + k] = txs(k)
    pool['pred'] = full
    pool['sday'] = season_day([g['tip'] for g, _, _ in D], S)
    # failed variant: free-throw luck (lwft .5, PR #360 failed it) as the walk's change in prediction
    Dv = NF.design(games, names, P, dict(prm, lwft=0.5), inj, feats)
    pool['ftluck'] = NF.wf(NF.mat(Dv[1], feats), y, S) - full
    day = np.array([g['tip'][:10] for g, _, _ in D])
    team = np.array([f"{g['h']}|{g['S']}" for g, _, _ in D])
    Xm = NF.mat(X, feats)
    return dict(y=y, S=S, pred=full, pool=pool, pool_names=sorted(pool), cl=[day, team], line=line, shipped=feats,
                tune=(N.SCORE_FROM, N.HOLD_FROM - 1), held=N.HOLD_FROM,
                walk=lambda v: NF.wf(np.column_stack([Xm, v]), y, S))


def nfl():
    import nfl_games as G
    F = jload('nfl_games_fit.json')
    last = 2025
    games, box, qbs = G.load(last)
    G.index_qbs(qbs, games); G.load_qb_teams(last)
    inj = G.injury_history(games, range(G.INJ_FIRST, last + 1))
    _, data = G.walk(games, box, qbs, F['params'])
    for g, x, _ in data:
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
    Dd = [(g, x, tx) for g, x, tx in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
    feats = [f for f in G.FEATS if f != 'epa']
    allx = sorted(set(G.FEATS) | {'epa'})
    X = {f: np.array([x.get(f, 0.0) for _, x, _ in Dd], float) for f in allx}
    y = np.array([G.num(g['result']) for g, _, _ in Dd], float)
    S = np.array([int(g['season']) for g, _, _ in Dd])
    Xm = np.column_stack([X[f] for f in feats])
    full = H.walk_ols(Xm, y, S, 2015)
    num = lambda v, dflt: G.num(v, dflt)
    pool = dict(X)
    pool['pred'] = full
    pool['week'] = np.array([num(g['week'], 0) for g, _, _ in Dd], float)
    pool['div'] = np.array([num(g['div_game'], 0) for g, _, _ in Dd], float)
    pool['dome'] = np.array([tx['dome'] for _, _, tx in Dd], float)
    pool['grass'] = np.array([1.0 if (g['surface'] or '').strip() == 'grass' else 0.0 for g, _, _ in Dd])
    pool['temp'] = np.array([num(g['temp'], 65) if g['temp'] not in ('', 'NA') else 65.0 for g, _, _ in Dd], float)
    pool['wind'] = np.array([num(g['wind'], 0) if g['wind'] not in ('', 'NA') else 0.0 for g, _, _ in Dd], float)
    pool['primetime'] = np.array([1.0 if g['weekday'] in ('Monday', 'Thursday') or (g['weekday'] == 'Sunday' and (g['gametime'] or '') >= '20:00') else 0.0 for g, _, _ in Dd])
    pool['post'] = np.array([0.0 if g['game_type'] == 'REG' else 1.0 for g, _, _ in Dd])
    pool['t:pts'] = np.array([tx['pts'] for _, _, tx in Dd], float)
    pool['t:tmkt'] = np.array([tx['tmkt'] for _, _, tx in Dd], float)
    wk = np.array([f"{g['season']}|{g['week']}" for g, _, _ in Dd])
    team = np.array([f"{g['home_team']}|{g['season']}" for g, _, _ in Dd])
    line = np.array([G.num(g['spread_line'], np.nan) for g, _, _ in Dd], float)
    return dict(y=y, S=S, pred=full, pool=pool, pool_names=sorted(pool), cl=[wk, team], line=line, shipped=feats,
                tune=(2015, 2020), held=2021, walk=lambda v: H.walk_ols(np.column_stack([Xm, v]), y, S, 2015, ridge=1e-6))


def cbb():
    import cbb_games as C
    F = jload('cbb_games_fit.json')
    P, feats = F['params'], list(F['feats'])
    games, btname, d1s, tprior, avs = C.load_all()
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    allx = list(dict.fromkeys(feats + C.CANDS + ['mkt', 'alt']))
    D, Xa, y, TX, ty, S, line, tline, d1 = C.matrices(rows, allx)
    Xm = Xa[:, [allx.index(f) for f in feats]]
    full = C.walk_pred(Xm, y, S, d1)
    pool = {f: Xa[:, i].astype(float) for i, f in enumerate(allx)}
    for i, f in enumerate(C.TFEATS):
        if f != 'one':
            pool['t:' + f] = TX[:, i].astype(float)
    pool['pred'] = full
    pool['sday'] = season_day([g['date'] for g, _, _ in D], S)
    pool['conf'] = np.array([1.0 if g.get('conf') else 0.0 for g, _, _ in D])
    day = np.array([g['date'][:10] for g, _, _ in D])
    team = np.array([f"{g['home']}|{g['season']}" for g, _, _ in D])
    return dict(y=y, S=S, pred=full, pool=pool, pool_names=sorted(pool), cl=[day, team], line=line, shipped=feats, ok=d1,
                tune=(C.SCORE0, C.TUNE_END), held=C.TUNE_END + 1,
                walk=lambda v: C.walk_pred(np.column_stack([Xm, v]), y, S, d1, ridge=1e-6))


ADAPT = {'nba': nba, 'nfl': nfl, 'cbb': cbb}


def clean(o):
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        return clean(o.item())
    return o


def main(args):
    want = [a for a in args if a in ADAPT] or list(ADAPT)
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    out['settings'] = {'depth': DEPTH, 'lr': LR, 'bins': BINS, 'lambda': LAM, 'maxRounds': MAXR, 'minLeaf': MINLEAF, 'clipSd': CLIP,
                       'loss': 'abs margin error (tree fit on residual clipped at 2.5 sd)', 'pass': 'held t < -1.645 and tune t < 0'}
    for sp in want:
        print('building', sp, flush=True)
        d = ADAPT[sp]()
        res = run(sp, d)
        print(sp, json.dumps(clean(res)), flush=True)
        res['promoted'] = promote(sp, d, res) if res['rounds'] else []
        if res['verdict'] == 'pass':
            res['detail'] = detail(sp, d, res)
        out[sp] = res
        print(sp, json.dumps(clean(res), indent=1), flush=True)
        json.dump(clean(out), open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1:])
