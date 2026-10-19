#!/usr/bin/env python3
"""Can the game models beat the betting market? A research pass, nothing here feeds the site or the picks.
Writes data/market_edge_research.json (numpy).

    python3 scripts/market_edge_research.py            # rebuild the walk-forward frames if missing, run every test
    python3 scripts/market_edge_research.py --rebuild  # re-walk the models first (a few minutes each)

The models' own walk-forward predictions (each season scored by weights fit on the seasons before it, every input known
before tip), the same ones scripts/cbb_games.py --fit and scripts/nba_games.py --fit report, joined to the market's lines:
    college basketball  closing spread and total 2016-26; opening spread 2024-26 (ESPN core odds, one book a game)
    NBA                 closing spread and total 2015-26; opening spread 2015-17 and 2024-26
    NFL                 closing lines only (nflverse): the shipped fit's residual-vs-close numbers are quoted, not rerun
No opening totals exist in either file, so totals get the residual-vs-close test only.

Tests (in order):
 1. market as prior: (result - close) on (model - close); (close - open) on (model - open); (result - open) on
    (model - open); (result - close) on both (model - close) and (close - open). OLS with robust (HC1) t. Held-out gain:
    each season's prediction close + b x (model - close) with b fit on the seasons before, against the close alone
 2. CLV at the open: bets where |model - open| >= th, the line's move toward the model's side by the close, in points;
    its t, and the bets a result-based test would need for the same t
 3. the same by segment: high-major / mixed / mid-major (college: today's conference membership, Pac-12 schools as
    high-major), early (college before Dec 15, NBA before Dec 1) / late, conference / non-conference
 4. false discoveries: every rule cell (sport x line x segment x threshold x sides/totals) scored on the earlier seasons
    only, p one-sided against the -110 break-even (52.38%); Benjamini-Hochberg and Bonferroni over all cells; the
    rules a fixed criterion picks on the earlier seasons scored once on the final held-out season(s)
 5. sizing on the picked rules: flat, raw Kelly, and Kelly on the held-out shrunk edge (slope from test 1), capped
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
CACHE = os.path.join(HERE, '.cache', 'research')
OUT = os.path.join(ROOT, 'data', 'market_edge_research.json')
BE = 110 / 210                              # break-even cover rate at -110
WIN = 100 / 110                             # profit a unit staked at -110
HIGH = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12', 'Pac-12'}
PAC = {'2483', '264', '26', '30', '12', '9', '254', '38', '24', '25', '204', '265'}   # Pac-12 2014-24 (ESPN ids)
HOLD = {'cbb': [2026], 'nba': [2025, 2026]}
THS = [1, 2, 3, 4, 5, 6]


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


Phi = np.vectorize(phi)


# ---------------------------------------------------------------- frames: one row a game, model and market
def cbb_frame():
    import cbb_games as C
    games, btname, d1s, tprior, avs = C.load_all()
    F = json.load(open(C.FIT))
    feats = F['feats']
    W, rows = C.run_walk(F['params'], games, tprior, btname, d1s, avs)
    D, Xa, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    pred = C.walk_pred(Xa, y, S, d1)
    tpred = C.walk_pred(TX, ty, S, d1)
    conf = {p['id']: p['conf'] for p in json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['power']}
    hi = lambda t: conf.get(t) in HIGH or t in PAC
    out = []
    for (g, _, _), m, tp, s, k in zip(D, pred, tpred, S, d1):
        if not k or np.isnan(m) or g.get('spread') is None:
            continue
        mo, dd = int(g['date'][5:7]), g['date'][5:10]
        early = mo in (10, 11) or (mo == 12 and dd < '12-15')
        out.append({'id': g['id'], 'S': int(s), 'date': g['date'][:10], 'm': float(m), 'L': -g['spread'],
                    'O': -g['open'] if g.get('open') is not None else None, 'y': g['hs'] - g['as'],
                    'tp': float(tp), 'T': g.get('total'), 'ty': g['hs'] + g['as'],
                    'tier': int(hi(g['home'])) + int(hi(g['away'])), 'early': int(early), 'conf': int(bool(g.get('conf')))})
    return out


def nba_frame():
    import nba_games as N
    import nba_games_fit as NF
    games, names = N.load_hist()
    inj = NF.load_inj()
    F = json.load(open(N.FIT))
    feats = F['feats']
    D, X, TX, y, ty, S, line, tline = NF.design(games, names, F['P'], F['params'], inj, feats)
    pred = NF.wf(NF.mat(X, feats), y, S)
    tpred = NF.wf(TX, ty, S)
    out = []
    for (g, _, _), m, tp in zip(D, pred, tpred):
        if np.isnan(m) or g.get('L') is None:
            continue
        mo, dd = int(g['tip'][5:7]), g['tip'][5:10]
        out.append({'id': g['id'], 'S': int(g['S']), 'date': g['tip'][:10], 'm': float(m), 'L': float(g['L']),
                    'O': g.get('Lo'), 'y': g['hs'] - g['as'], 'tp': float(tp), 'T': g.get('T'), 'ty': g['hs'] + g['as'],
                    'tier': 2, 'early': int(mo in (10, 11)), 'conf': 0})
    return out


def frame(sport):
    p = os.path.join(CACHE, f'{sport}_frame.json.gz')
    if '--rebuild' in sys.argv or not os.path.exists(p):
        rows = cbb_frame() if sport == 'cbb' else nba_frame()
        os.makedirs(CACHE, exist_ok=True)
        with gzip.open(p, 'wt') as f:
            json.dump(rows, f)
    rows = json.load(gzip.open(p))
    A = {k: np.array([np.nan if r[k] is None else r[k] for r in rows], float) for k in ('S', 'm', 'L', 'O', 'y', 'tp', 'T', 'ty', 'tier', 'early', 'conf')}
    A['date'] = np.array([r['date'] for r in rows])
    # ESPN's open is the home side's, and isn't sign-checked the way the close is: an open more than 6 points off the
    # close that sits within 3 of it flipped is a sign error, flipped back; anything else over 10 off is dropped
    d, df = np.abs(A['L'] - A['O']), np.abs(A['L'] + A['O'])
    flip = (d >= 6) & (df <= 3)
    A['O'] = np.where(flip, -A['O'], A['O'])
    bad = ~flip & (d > 10)
    A['O'] = np.where(bad, np.nan, A['O'])
    A['openFix'] = {'flipped': int(flip.sum()), 'dropped': int(bad.sum())}
    return A


# ---------------------------------------------------------------- statistics
def ols(y, X):
    """slopes, HC1 robust t"""
    X = np.column_stack([np.ones(len(y))] + list(X))
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    V = XtXi @ (X.T * e ** 2) @ X @ XtXi * len(y) / (len(y) - X.shape[1])
    return b, b / np.sqrt(np.diag(V))


def tstat(v):
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))) if len(v) > 2 and v.std() > 0 else 0.0


def p_one(z):
    return 1 - phi(z)


def reg(y, xs, names, k):
    if k.sum() < 30:
        return None
    b, t = ols(y[k], [x[k] for x in xs])
    out = {'n': int(k.sum()), 'const': round(float(b[0]), 3)}
    for nm, bb, tt in zip(names, b[1:], t[1:]):
        out[nm] = round(float(bb), 3); out['t_' + nm] = round(float(tt), 2)
    return out


def gain(y, base, edge, S, k, seasons):
    """held-out: each season in seasons predicted by base + b x edge, b from (y - base) on edge over the earlier seasons in k"""
    rows = []
    for s in seasons:
        tr, te = k & (S < s), k & (S == s)
        if tr.sum() < 200 or not te.any():
            continue
        b = ols(y[tr] - base[tr], [edge[tr]])[0]
        p = base[te] + b[0] + b[1] * edge[te]
        rows.append((np.abs(p - y[te]), np.abs(base[te] - y[te]), (p - y[te]) ** 2, (base[te] - y[te]) ** 2, float(b[1])))
    if not rows:
        return None
    a1, a0, q1, q0 = (np.concatenate([r[i] for r in rows]) for i in range(4))
    return {'n': int(len(a1)), 'seasons': [int(s) for s in seasons], 'slopesUsed': [round(r[4], 3) for r in rows],
            'maeLine': round(float(a0.mean()), 4), 'maeShrunk': round(float(a1.mean()), 4), 'tMae': round(tstat(a1 - a0), 2),
            'mseLine': round(float(q0.mean()), 3), 'mseShrunk': round(float(q1.mean()), 3), 'tMse': round(tstat(q1 - q0), 2)}


def ats(edge, r, k):
    """bet the model's side where k: covers (pushes out), win rate, ROI at -110, z against break-even"""
    k = k & (r != 0) & (edge != 0)
    n = int(k.sum())
    if n == 0:
        return {'n': 0}
    w = float((np.sign(edge[k]) == np.sign(r[k])).mean())
    z = (w - BE) / math.sqrt(BE * (1 - BE) / n)
    return {'n': n, 'win': round(w, 4), 'roi': round(w * WIN - (1 - w), 4), 'z': round(z, 2), 'p': round(p_one(z), 4)}


def clv(m, L, O, k, sd):
    """bet at the open on the model's side; CLV = how far the close moved toward that side, points"""
    e = m - O
    k = k & ~np.isnan(O) & (e != 0)
    if k.sum() < 10:
        return None
    c = np.sign(e[k]) * (L[k] - O[k])
    t = tstat(c)
    # a point of line value as cover chance near the number: E[Phi(c/sd)] - 1/2
    ce = float(np.mean(Phi(c / sd)) - 0.5)
    need = (t * 0.5 / ce) ** 2 if ce > 0 else None
    return {'n': int(k.sum()), 'clv': round(float(c.mean()), 3), 't': round(t, 2), 'toward': round(float((c > 0).mean()), 3),
            'away': round(float((c < 0).mean()), 3), 'coverEdge': round(ce, 4),
            'resultBetsForSameT': (int(need) if need else None), 'ratio': (round(need / k.sum(), 1) if need else None)}


# ---------------------------------------------------------------- one sport
def segments(A, sport):
    S = A['S']
    seg = {'all': np.ones(len(S), bool), 'early': A['early'] == 1, 'late': A['early'] == 0}
    if sport == 'cbb':
        seg.update({'high': A['tier'] == 2, 'mixed': A['tier'] == 1, 'mid': A['tier'] == 0,
                    'conf': A['conf'] == 1, 'nonconf': A['conf'] == 0})
    return seg


def run(sport):
    A = frame(sport)
    S, m, L, O, y, tp, T, ty = (A[k] for k in ('S', 'm', 'L', 'O', 'y', 'tp', 'T', 'ty'))
    hold = np.isin(S, HOLD[sport])
    hasL, hasO, hasT = ~np.isnan(L), ~np.isnan(O), ~np.isnan(T) & ~np.isnan(tp)
    sd = float(np.std((y - L)[hasL]))
    tsd = float(np.std((ty - T)[hasT]))
    seasons = sorted(set(S.astype(int)))
    res = {'games': int(hasL.sum()), 'openGames': int(hasO.sum()), 'openSeasons': sorted(set(S[hasO].astype(int).tolist())),
           'holdSeasons': HOLD[sport], 'openFix': A['openFix'], 'sdResidClose': round(sd, 2), 'sdResidTotal': round(tsd, 2)}
    seg = segments(A, sport)

    # 1. market as prior
    t1 = {}
    for nm, k in seg.items():
        kc, ko, kt = k & hasL, k & hasL & hasO, k & hasT
        blk = {}
        for part, kk in (('tune', ~hold), ('held', hold), ('all', np.ones(len(S), bool))):
            blk[part] = {
                'resultMinusClose_on_modelMinusClose': reg(y - L, [m - L], ['b'], kc & kk),
                'closeMinusOpen_on_modelMinusOpen': reg(L - O, [m - O], ['b'], ko & kk),
                'resultMinusOpen_on_modelMinusOpen': reg(y - O, [m - O], ['b'], ko & kk),
                'resultMinusClose_on_both': reg(y - L, [m - L, L - O], ['model', 'move'], ko & kk),
                'totals_resultMinusClose_on_modelMinusClose': reg(ty - T, [tp - T], ['b'], kt & kk)}
        # held-out predictive gain, walk-forward a season at a time over the seasons after the first two scored
        later = [s for s in seasons if s >= seasons[0] + 2]
        blk['gainClose'] = {'final': gain(y, L, m - L, S, kc, HOLD[sport]), 'walk': gain(y, L, m - L, S, kc, later)}
        ol = sorted(set(S[ko].astype(int)))
        blk['gainOpen'] = {'final': gain(y, O, m - O, S, ko, HOLD[sport]), 'walk': gain(y, O, m - O, S, ko, ol[1:])}
        blk['gainTotals'] = {'final': gain(ty, T, tp - T, S, kt, HOLD[sport]), 'walk': gain(ty, T, tp - T, S, kt, later)}
        t1[nm] = blk
    # context: does the model's residual slope vary with the cheap features (one regression, interactions)
    e = m - L
    ctx = [e, e * A['early']] + ([e * (A['tier'] == 0), e * (A['tier'] == 1), e * A['conf']] if sport == 'cbb' else [])
    cn = ['edge', 'edge_x_early'] + (['edge_x_mid', 'edge_x_mixed', 'edge_x_conf'] if sport == 'cbb' else [])
    t1['contextInteractions'] = {'tune': reg(y - L, ctx, cn, hasL & ~hold), 'held': reg(y - L, ctx, cn, hasL & hold)}
    res['test1'] = t1
    # season by season: is the residual slope against the close stable, and the |edge| >= 4 record at the close
    res['bySeason'] = {int(s): {'slope': reg(y - L, [m - L], ['b'], hasL & (S == s)), 'ats4Close': ats(m - L, y - L, hasL & (S == s) & (np.abs(m - L) >= 4)),
                                'clv2': clv(m, L, O, hasL & (S == s) & (np.abs(m - O) >= 2), sd)} for s in seasons}

    # 2-3. CLV at the open by threshold and segment
    t2 = {}
    for nm, k in seg.items():
        t2[nm] = {}
        for part, kk in (('tune', ~hold), ('held', hold), ('all', np.ones(len(S), bool))):
            t2[nm][part] = {}
            for th in [0] + THS:
                c = clv(m, L, O, k & kk & hasL & (np.abs(m - O) >= th), sd)
                if c:
                    # the same bets' results, at the open's number and at the close's
                    sel = k & kk & hasL & hasO & (np.abs(m - O) >= th)
                    c['atsAtOpen'] = ats(m - O, y - O, sel)
                    c['atsAtClose'] = ats(m - O, y - L, sel)
                t2[nm][part][str(th)] = c
    res['test2'] = t2

    # 4. rule cells on the earlier seasons only
    cells = []
    for nm, k in seg.items():
        for th in THS:
            for line, edge, r, kk in (('close', m - L, y - L, hasL), ('open', m - O, y - O, hasL & hasO),
                                      ('totalClose', tp - T, ty - T, hasT)):
                sel = k & kk & (np.abs(edge) >= th)
                a = ats(edge, r, sel & ~hold)
                if a['n'] >= 50:
                    cells.append({'sport': sport, 'seg': nm, 'line': line, 'th': th, 'tune': a, '_sel': sel, '_edge': edge, '_r': r})
    return res, cells, A


# ---------------------------------------------------------------- sizing
def sizing(A, rule, slope, sd, hold):
    """bankroll walk on the held-out bets of one rule: flat 1% of the start, raw Kelly, shrunk-and-capped Kelly"""
    line = rule['line']
    m, y = (A['tp'], A['ty']) if line == 'totalClose' else (A['m'], A['y'])
    base = {'close': A['L'], 'open': A['O'], 'totalClose': A['T']}[line]
    edge = m - base
    k = rule['_sel'] & hold & (y - base != 0)
    idx = np.where(k)[0]
    idx = idx[np.argsort(A['date'][idx], kind='stable')]
    out = {}
    for name in ('flat', 'kelly', 'shrunkKelly'):
        bank, peak, mdd, staked, profit = 1.0, 1.0, 0.0, 0.0, 0.0
        day, day_bank = None, 1.0
        for i in idx:
            if A['date'][i] != day:
                day, day_bank = A['date'][i], bank
            e = abs(edge[i])
            if name == 'flat':
                f = 0.01
            else:
                p = phi((e if name == 'kelly' else slope * e) / sd)
                f = max(0.0, (p * (WIN + 1) - 1) / WIN)
                if name == 'shrunkKelly':
                    f = min(f, 0.02)
            st = f * (day_bank if name != 'flat' else 1.0)
            st = min(st, bank) if bank > 0 else 0.0
            won = np.sign(edge[i]) == np.sign((y - base)[i])
            pl = st * WIN if won else -st
            bank += pl; staked += st; profit += pl
            peak = max(peak, bank); mdd = max(mdd, (peak - bank) / peak if peak > 0 else 1.0)
        out[name] = {'bets': int(len(idx)), 'roi': round(profit / staked, 4) if staked else None, 'final': round(bank, 3),
                     'maxDrawdown': round(mdd, 3)}
    return out


def main():
    results, cells, frames = {}, [], {}
    for sport in ('cbb', 'nba'):
        r, c, A = run(sport)
        results[sport] = r; cells += c; frames[sport] = A
        print(sport, 'done', len(c), 'cells', flush=True)

    # 4. Benjamini-Hochberg and Bonferroni over every cell tried, then a fixed pick rule on the tuning seasons:
    #    per sport and line, the cell with the highest tuning z among those with n >= 200 and p < 0.05; each picked
    #    rule scored once on the held-out season(s)
    ps = np.array([c['tune']['p'] for c in cells])
    n = len(ps)
    order = np.argsort(ps)
    bh = np.empty(n)
    run_min = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        run_min = min(run_min, ps[i] * n / rank)
        bh[i] = run_min
    for c, q in zip(cells, bh):
        c['tune']['bh'] = round(float(q), 4); c['tune']['bonf'] = round(float(min(1.0, c['tune']['p'] * n)), 4)
    picked = []
    for sport in ('cbb', 'nba'):
        for line in ('close', 'open', 'totalClose'):
            cs = [c for c in cells if c['sport'] == sport and c['line'] == line and c['tune']['n'] >= 200 and c['tune']['p'] < 0.05]
            if cs:
                picked.append(max(cs, key=lambda c: c['tune']['z']))
    held_rows = []
    for c in picked:
        A = frames[c['sport']]
        hold = np.isin(A['S'], HOLD[c['sport']])
        h = ats(c['_edge'], c['_r'], c['_sel'] & hold)
        # the shrink slope for sizing: the tuning seasons' (result - line) on (model - line), every game with that line
        kk = ~np.isnan(c['_edge']) & ~np.isnan(c['_r']) & ~hold
        slope = float(ols(c['_r'][kk], [c['_edge'][kk]])[0][1])
        sd = results[c['sport']]['sdResidTotal' if c['line'] == 'totalClose' else 'sdResidClose']
        row = {k: c[k] for k in ('sport', 'seg', 'line', 'th')}
        row.update({'tune': c['tune'], 'held': h, 'shrinkSlope': round(slope, 3), 'sizingHeld': sizing(A, c, slope, sd, hold)})
        held_rows.append(row)
    nsig = int((bh < 0.05).sum()); nbonf = int((ps * n < 0.05).sum())
    out = {'what': 'research only: can the walk-forward game models beat the market (scripts/market_edge_research.py)',
           'breakEven': round(BE, 4), 'thresholds': THS, 'sports': results,
           'falseDiscovery': {'cellsTried': n, 'bhSignificant05': nsig, 'bonferroniSignificant05': nbonf,
                              'cells': [{**{k: c[k] for k in ('sport', 'seg', 'line', 'th')}, **c['tune']} for c in cells]},
           'picked': held_rows,
           'nfl': nfl_quote()}
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    summary(out)


def nfl_quote():
    """NFL: nflverse has closing lines only; the shipped fit's residual-vs-close and ATS numbers"""
    try:
        F = json.load(open(os.path.join(ROOT, 'data', 'nfl_games_fit.json')))
        return {'note': 'closing lines only (nflverse); from data/nfl_games_fit.json, not rerun',
                'test': {k: {kk: v[kk] for kk in ('games', 'edgeSlope', 'ats1', 'ats2', 'ats3', 'maeModel', 'maeLine')} for k, v in F['test'].items()}}
    except (OSError, KeyError):
        return None


def summary(out):
    for sport, r in out['sports'].items():
        a = r['test1']['all']
        print(sport, 'games', r['games'], 'open', r['openGames'], r['openSeasons'], r['openFix'])
        for part in ('tune', 'held'):
            print(' ', part, {k: v for k, v in a[part].items()})
        print('  gainClose', a['gainClose']); print('  gainOpen', a['gainOpen']); print('  gainTotals', a['gainTotals'])
        print('  ctx', r['test1']['contextInteractions'])
        for s, b in r['bySeason'].items():
            print('  season', s, b['slope'] and (b['slope']['b'], b['slope']['t_b']), b['ats4Close'], b['clv2'] and (b['clv2']['n'], b['clv2']['clv'], b['clv2']['t']))
        for nm, d in r['test2'].items():
            for part in ('tune', 'held'):
                print('  clv', nm, part, {th: (c['n'], c['clv'], c['t'], c['atsAtOpen'].get('win'), c['atsAtOpen'].get('roi')) if c else None for th, c in d[part].items()})
    fd = out['falseDiscovery']
    print('cells', fd['cellsTried'], 'BH sig', fd['bhSignificant05'], 'Bonf sig', fd['bonferroniSignificant05'])
    for c in sorted(fd['cells'], key=lambda c: c['p'])[:12]:
        print('  ', c)
    for p in out['picked']:
        print('picked', json.dumps(p))


if __name__ == '__main__':
    main()
