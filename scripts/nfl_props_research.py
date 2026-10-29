#!/usr/bin/env python3
"""NFL player props paper test (Oct 29 2026, ARK Edge Sweep): do the nfl_fantasy stat-line projections, as they would
stand on a Wednesday, beat the books' opening prop lines?

    python3 scripts/nfl_props_archive.py        # the opens: ESPN BET 2024-Nov 2025, DraftKings 2026 (once)
    python3 scripts/nfl_props_research.py       # -> data/nfl_props_research.json (numpy; ~20 min, nflverse cached)

Lines: the opening main over/under of passing yards and TDs, rushing yards, receiving yards, receptions and rushing +
receiving yards. Only opens: ESPN's `current` for a finished game is an in-play number. No prices are archived, so a
bet is graded at -110 (breakeven 52.4%) and, as a check, -115 (53.5%); main props usually sit near there.

Projections: nfl_fantasy.collect() + walk_forward(): each season's coefficients fit on the seasons before it, the
rating memory at the published fit's params. Two versions:
    wed    what's known on a Wednesday: rosters as of last week (reserve lists), no injury report, and the game
           environment from the opening spread and total (scripts/data/games_wf, SBR + ESPN opens)
    full   the live build at kickoff: final injury report and closing lines (an upper bound: news after the open)
A projection is the mean if he plays; a prop is void if he doesn't, and so is a row here (only games he played).

P(over): the shape of y / mu by projection band (deciles), from the 2016-23 walk-forward rows (no lines needed, so
nothing from the prop years), applied to each prop's line / mu. Points are right-skewed: a mean over the line is not
an over bet.

Rule, pre-registered: bet the side whose P is at least p* (one bet per player prop), p* in .52-.60 picked on 2024
(tune), scored on 2025 and 2026 (held out). Pass = held-out ROI at -110 > 0 with t >= 2, games as clusters, for the
wed version. Diagnostics: logistic slope of the result on logit(P) (does the model add anything to the line?), hit
rate by stat and season, and the mean of (mu - line) (do the books' lines sit under or over our means?).
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import nfl_fantasy as NF  # noqa: E402
import nfl_games as G  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'nfl_props_research.json')
OPENS = os.path.join(HERE, 'data', 'props', 'nfl_espnbet_opens.json.gz')
WF = os.path.join(HERE, 'data', 'games_wf', 'nfl.json.gz')
ROWS = os.path.join(HERE, '.cache', 'nfl_props_rows.npz')
FIT = os.path.join(ROOT, 'data', 'nfl_props_fit.json')       # the live rule's P(over) shape and calibration (props_paper.py)
LAST = 2026
TUNE, HELD = (2024,), (2025, 2026)
SHAPE = range(2016, 2024)
STATS = {'py': ('py',), 'ptd': ('ptd',), 'ry': ('ry',), 'wy': ('wy',), 'rc': ('rc',), 'rwy': ('ry', 'wy')}
PSTAR = (.52, .54, .56, .58, .60)
BE = {'-110': 110 / 210, '-115': 115 / 215}


def opens_market():
    """{nflverse game id: (open home-margin line, open total)}"""
    out = {}
    for r in json.load(gzip.open(WF, 'rt')):
        if r.get('Lo') is not None and r.get('To') is not None:
            out[r['id']] = (float(r['Lo']), float(r['To']))
    return out


def build_rows():
    if os.path.exists(ROWS):
        z = np.load(ROWS, allow_pickle=True)
        return {k: z[k] for k in z.files}
    F = json.load(open(NF.FIT))
    games, box, dst, status, inj, info = NF.load(NF.FIRST, LAST)
    model, _ = NF.implied(LAST, walkforward=True)
    wars = NF.war_history(NF.SNAP0, LAST)
    seasons = list(range(NF.TEST0, LAST + 1))
    OM = opens_market()
    imp0 = NF.game_imp
    out = {}
    for ver in ('full', 'wed'):
        if ver == 'wed':
            def wed_imp(g, model, market=True):
                o = OM.get(g['game_id'])
                if o:
                    return (o[1] + o[0]) / 2, (o[1] - o[0]) / 2
                return imp0(g, model, market=False)
            NF.game_imp = wed_imp
            R, _ = NF.collect(games, box, dst, info, model, F['params'], status, {}, wars)
        else:
            NF.game_imp = imp0
            R, _ = NF.collect(games, box, dst, info, model, F['params'], status, inj, wars)
        A = NF.arrays({k: v for k, v in R.items() if k in NF.SKILL})
        P = NF.walk_forward(A, seasons)
        for pos in NF.SKILL:
            a = A[pos]
            if ver == 'full':
                out.setdefault('pos', []).extend([pos] * len(a['s']))
                out.setdefault('s', []).extend(a['s'].tolist()); out.setdefault('w', []).extend(a['w'].tolist())
                out.setdefault('id', []).extend(a['id'])
                for c in ('py', 'ptd', 'ry', 'wy', 'rc'):
                    out.setdefault('y_' + c, []).extend(a['Y'][c].tolist())
            for c in ('py', 'ptd', 'ry', 'wy', 'rc'):
                v = P[pos][c] if c in P[pos] else np.zeros(len(a['s']))
                out.setdefault(f'{ver}_{c}', []).extend(v.tolist())
        print(ver, 'rows', sum(len(A[p]['s']) for p in NF.SKILL), flush=True)
    NF.game_imp = imp0
    # ESPN ids: games (nflverse games.csv 'espn') and athletes (players.csv 'espn_id')
    g2 = {str(g['espn']): (int(g['season']), int(g['week'])) for g in G.rows(G.get('games.csv', G.GAMES)) if g.get('espn') not in ('', 'NA', None)}
    a2 = {}
    for r in G.rows(G.get('players.csv', f'{NF.REL}/players/players.csv')):
        if r.get('espn_id') and r.get('gsis_id'):
            a2[str(r['espn_id']).split('.')[0]] = r['gsis_id']
    z = {k: np.array(v, dtype=object if k in ('pos', 'id') else float) for k, v in out.items()}
    z['g2'] = np.array([[k, *v] for k, v in g2.items()], dtype=object)
    z['a2'] = np.array(list(a2.items()), dtype=object)
    np.savez(ROWS, **z)
    return z


def shape(rows, ver):
    """per stat: decile edges of mu and each band's sorted y / mu, from the 2016-23 rows (mu > 0)"""
    out = {}
    S = rows['s']
    for st, parts in STATS.items():
        mu = sum(rows[f'{ver}_{c}'] for c in parts); y = sum(rows['y_' + c] for c in parts)
        m = np.isin(S, list(SHAPE)) & (mu > .05) & ~np.isnan(mu)
        if st in ('py', 'ptd'):
            m &= rows['pos'] == 'QB'
        mu, y = mu[m], y[m]
        # props are listed for players with a role: bands over the upper half of the projection
        edges = np.quantile(mu, np.linspace(0, 1, 11))
        bands = [np.sort(y[(mu >= lo) & (mu <= hi)] / mu[(mu >= lo) & (mu <= hi)]) for lo, hi in zip(edges[:-1], edges[1:])]
        out[st] = (edges, bands)
    return out


def p_over(sh, st, mu, L):
    edges, bands = sh[st]
    if not mu > 0:
        return None
    b = bands[min(len(bands) - 1, max(0, int(np.searchsorted(edges, mu, side='right')) - 1))]
    r = L / mu
    over = len(b) - np.searchsorted(b, r, side='right')
    return (over + .5) / (len(b) + 1)


def main():
    rows = build_rows()
    ix = {(int(s), int(w), i): k for k, (s, w, i) in enumerate(zip(rows['s'], rows['w'], rows['id']))}
    g2 = {str(r[0]): (int(r[1]), int(r[2])) for r in rows['g2']}
    a2 = {str(r[0]): r[1] for r in rows['a2']}
    O = json.load(gzip.open(OPENS, 'rt'))
    sh = {v: shape(rows, v) for v in ('wed', 'full')}
    props = []          # (season, gid, stat, line, y, {ver: (mu, P)})
    miss = defaultdict(int)
    for gid, g in O.items():
        sw = g2.get(gid)
        if not sw:
            miss['game'] += 1
            continue
        for a, st, L in g['props']:
            if st not in STATS:
                continue
            gs = a2.get(a)
            k = ix.get((sw[0], sw[1], gs)) if gs else None
            if k is None:
                miss['player' if not gs else 'row'] += 1
                continue
            y = sum(rows['y_' + c][k] for c in STATS[st])
            if y == L:
                miss['push'] += 1
                continue
            v = {}
            for ver in ('wed', 'full'):
                mu = sum(rows[f'{ver}_{c}'][k] for c in STATS[st])
                p = p_over(sh[ver], st, mu, L)
                v[ver] = (mu, p)
            if any(x[1] is None for x in v.values()):
                miss['mu'] += 1
                continue
            props.append((sw[0], gid, st, L, y, v, g['b']))
    print(len(props), 'graded props;', dict(miss))

    def bets(ver, ps, seasons, stat=None):
        out = []
        for s, gid, st, L, y, v, b in props:
            if s not in seasons or (stat and st != stat):
                continue
            p = v[ver][1]
            if p >= ps:
                out.append((gid, float(y > L)))
            elif 1 - p >= ps:
                out.append((gid, float(y < L)))
        return out

    def score(bb, be=BE['-110']):
        if not bb:
            return {'n': 0}
        w = np.array([x[1] for x in bb]); cl = np.array([x[0] for x in bb])
        win = 1 / be - 1                       # profit per unit staked on a win at that price
        pnl = np.where(w == 1, win, -1.0)
        pr = H.paired(pnl, np.zeros(len(pnl)), cl)
        return {'n': int(len(w)), 'games': pr['G'], 'hit': round(float(w.mean()), 4), 'roi': round(float(pnl.mean()), 4),
                't': round(pr['t'], 2)}

    res = {'graded': len(props), 'missing': dict(miss), 'book': {}, 'versions': {}}
    for s, *_, b in props:
        res['book'][f'{s} {b}'] = res['book'].get(f'{s} {b}', 0) + 1
    for ver in ('wed', 'full'):
        R = {'tune': {}, 'diag': {}}
        for ps in PSTAR:
            R['tune'][str(ps)] = score(bets(ver, ps, TUNE))
        best = max(PSTAR, key=lambda ps: (R['tune'][str(ps)].get('roi', -9) if R['tune'][str(ps)]['n'] >= 100 else -9))
        R['pstar'] = best
        R['held'] = {k: score(bets(ver, best, HELD), be) for k, be in BE.items()}
        R['heldBySeason'] = {str(s): score(bets(ver, best, (s,))) for s in HELD}
        R['heldByStat'] = {st: score(bets(ver, best, HELD, st)) for st in STATS}
        R['allP'] = {str(ps): {str(s): score(bets(ver, ps, (s,))) for s in TUNE + HELD} for ps in PSTAR}
        # does P(over) know anything the line doesn't? logistic of the result on logit(P), by period, games clustered
        for name, ss in (('tune', TUNE), ('held', HELD)):
            xs = [(math.log(v[ver][1] / (1 - v[ver][1])), float(y > L), gid) for s, gid, st, L, y, v, b in props if s in ss]
            x = np.array([q[0] for q in xs]); yy = np.array([q[1] for q in xs])
            # the line's own chance is 1/2 (no prices): Brier of P vs a coin, paired by row
            p = 1 / (1 + np.exp(-x))
            br = H.paired((p - yy) ** 2, (.5 - yy) ** 2, np.array([q[2] for q in xs]))
            b1 = np.polyfit(x, yy, 1)[0] if len(x) > 10 else None
            gap = [v[ver][0] - L for s, gid, st, L, y, v, b in props if s in ss]
            res_line = [y - L for s, gid, st, L, y, v, b in props if s in ss]
            R['diag'][name] = {'n': int(len(x)), 'brierVsCoin': round(br['d'], 5), 't': round(br['t'], 2),
                               'slope': None if b1 is None else round(float(b1), 3),
                               'overRate': round(float(yy.mean()), 4), 'meanMuMinusLine': round(float(np.mean(gap)), 2),
                               'meanYMinusLine': round(float(np.mean(res_line)), 2)}
        res['versions'][ver] = R
        print(ver, json.dumps({k: R[k] for k in ('pstar', 'held', 'heldBySeason', 'diag')}), flush=True)
    # live: the full version is what the build publishes (nfl-fantasy.json). Its P(over) is too sure (P >= .6 hits ~.56),
    # so the paper book stakes on chance = .5 + c (P - .5), c fit on the tune season through (.5, .5)
    tp = np.array([v['full'][1] for s, gid, st, L, y, v, b in props if s in TUNE])
    ty = np.array([float(y > L) for s, gid, st, L, y, v, b in props if s in TUNE])
    c = float(((tp - .5) * (ty - .5)).sum() / ((tp - .5) ** 2).sum())
    hp = np.array([v['full'][1] for s, gid, st, L, y, v, b in props if s in HELD])
    hy = np.array([float(y > L) for s, gid, st, L, y, v, b in props if s in HELD])
    hit = [float(x[1]) for x in bets('full', res['versions']['full']['pstar'], HELD)]
    res['calib'] = {'c': round(c, 3), 'heldBrier': round(float(np.mean((.5 + c * (hp - .5) - hy) ** 2)), 5),
                    'heldBrierRaw': round(float(np.mean((hp - hy) ** 2)), 5), 'heldBrierCoin': round(float(np.mean((.5 - hy) ** 2)), 5),
                    'heldChanceAtPstar': round(float(np.mean(.5 + c * (np.maximum(hp, 1 - hp)[np.maximum(hp, 1 - hp) >= res['versions']['full']['pstar']] - .5))), 4),
                    'heldHitAtPstar': round(float(np.mean(hit)), 4)}
    # stakes for the pick board (Oct 29 2026, Noah: "add the NFL props to the pick board"), the book's rule
    # (scripts/units.py): full Kelly (lam 1) on the calibrated edge times TIMING (.5, every backtest edge), times the
    # slate scale 1 / (1 + (n - 1) rho) for n bets settling the same week, clipped to [.25, BOOK_CAP]. rho: within-week
    # correlation of the bets' returns on the tune season (one-way ANOVA). Growth is log growth a week at -110, compounding
    ps = res['versions']['full']['pstar']
    B = 100 / 110
    sel = []
    for s_, gid, st, L, y, v, b in props:
        p = v['full'][1]
        side = 'o' if p >= ps else 'u' if 1 - p >= ps else None
        if side:
            ch = .5 + c * (max(p, 1 - p) - .5)
            win = (y > L) if side == 'o' else (y < L)
            sel.append((s_, g2[gid][1], gid, ch, B if win else -1.0))

    def anova_rho(rows):
        by = defaultdict(list)
        for r in rows:
            by[(r[0], r[1])].append(r[4])
        N, k = sum(len(x) for x in by.values()), len(by)
        mu = sum(sum(x) for x in by.values()) / N
        ssb = sum(len(x) * (np.mean(x) - mu) ** 2 for x in by.values())
        ssw = sum(sum((q - np.mean(x)) ** 2 for q in x) for x in by.values())
        msb, msw = ssb / (k - 1), ssw / (N - k)
        m0 = (N - sum(len(x) ** 2 for x in by.values()) / N) / (k - 1)
        return max(0.0, (msb - msw) / (msb + (m0 - 1) * msw)), N / k
    rho, nbar = anova_rho([r for r in sel if r[0] in TUNE])
    import units as U

    def stakes(rs, budget=None):
        sc = 1 / (1 + (len(rs) - 1) * rho)
        f = [min(U.BOOK_CAP, max(U.UNIT_MIN, round(max(0.0, U.TIMING * (ch * B - (1 - ch)) / B) * 100 * sc * 4) / 4)) for _, _, _, ch, _ in rs]
        if budget and sum(f) > budget:
            f = [x * budget / sum(f) for x in f]
        return f

    def growth(rows, budget=None):
        by = defaultdict(list)
        for r in rows:
            by[(r[0], r[1])].append(r)
        lg, ex = [], []
        for rs in by.values():
            f = stakes(rs, budget)
            ex.append(sum(f))
            lg.append(math.log(max(1e-9, 1 + sum(fi / 100 * r[4] for fi, r in zip(f, rs)))))
        return {'logWeek': round(float(np.mean(lg)), 4), 'worstWeek': round(float(math.expm1(min(lg))), 3),
                'exposure': round(float(np.mean(ex)), 1)}
    res['stakes'] = {'rho': round(float(rho), 4), 'nbar': round(float(nbar), 1), 'timing': U.TIMING, 'cap': U.BOOK_CAP,
                     'tune': growth([r for r in sel if r[0] in TUNE]), 'held': growth([r for r in sel if r[0] in HELD]),
                     'heldByBudget': {str(bu): growth([r for r in sel if r[0] in HELD], bu) for bu in (10, 25, 50, 100)}}
    print('stakes', res['stakes'])
    edges_q = np.linspace(0, 1, 201)
    fit = {'registered': '2026-10-29', 'pstar': res['versions']['full']['pstar'], 'c': round(c, 4),
           'rho': res['stakes']['rho'], 'shapeSeasons': [SHAPE[0], SHAPE[-1]],
           'stats': {st: [list(STATS[st]), [round(float(e), 3) for e in edges],
                          [[round(float(q), 4) for q in np.quantile(b, edges_q)] for b in bands]]
                     for st, (edges, bands) in sh['full'].items()}}
    with open(FIT, 'w') as f:
        json.dump(fit, f, separators=(',', ':'))
    print('calib', res['calib'])
    W = res['versions']['wed']['held']['-110']
    res['verdict'] = 'pass' if W.get('n', 0) and W['roi'] > 0 and W['t'] >= 2 else 'fail'
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print('verdict', res['verdict'])


if __name__ == '__main__':
    main()
