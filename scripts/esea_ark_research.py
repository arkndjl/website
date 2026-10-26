#!/usr/bin/env python3
"""ARK Rating and veto research (Oct 26 2026): which player rating best predicts the next match, and which
map-strength source finds real map edges for the veto.

    python3 scripts/esea_ark_research.py      # reads research/esea_matches.json.gz, writes data/esea_ark_research.json

ARK part. Each team's strength before a match = the mean of its five players' ratings from their earlier
league maps only (S58 Main/Intermediate, S59 Main), each shrunk toward average by k rounds. Variants:
  kd        kills minus deaths per round (baseline)
  ark       the live ARK 2 weights on the same features (rounds per unit, data/esea.json arkModel)
  ark_out   ark plus the KAST-style team-result credit (what the page shows)
  stab      ark with each feature regressed to the league mean by its own split-half reliability
  pred      weights fitted to predict the NEXT match (player career averages -> next round share), ridge
Scored on the later 40% of matches by date (all weights and k fitted on the first 60%): next-match log loss
and round-share error, paired per match; plus split-half reliability (odd vs even maps) of each rating.

Veto part. For every map played, does a map-strength source predict the team's round share on that map
beyond its overall strength? Sources: team lifetime FACEIT map splits (the live preview's), the five
players' lifetime map splits (every FACEIT match: thousands of maps each), and earlier league maps.
"""
import gzip
import json
import math
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'research', 'esea_matches.json.gz')
OUT = os.path.join(ROOT, 'data', 'esea_ark_research.json')
FEATS = ['kpr', 'dpr', 'adr', 'mks', 'entry', 'clutch', 'apr', 'fpr', 'udr', 'fsr', 'usr']
FEATS_P = FEATS + ['pist']   # pistol kills per pistol round (2 a map): FACEIT has no round-by-round data


def clip(p):
    return min(1 - 1e-4, max(1e-4, p))


def ll(p, y):
    p = clip(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def solve(A, b):
    n = len(b)
    M = [A[i][:] + [b[i]] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            return None
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [a - f * x for a, x in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] for i in range(n)]


def ridge(X, y, lam):
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) + (lam if i == j else 0) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * t for r, t in zip(X, y)) for i in range(k)]
    return solve(A, b)


# counts kept per player: the raw totals the per-round features are built from
CNT = ['R', 'k', 'd', 'a', 'dmg', 'mk', 'ew', 'el', 'c11', 'c12', 'fl', 'ud', 'fs', 'us', 'cred', 'setups', 'entries', 'pk', 'maps']


def counts(q, R, rf, ra, credit):
    """a cached box-score line (fetch_esea.mjs boxLines order) as counts"""
    ew = q[13]
    return {'R': R, 'k': q[0], 'd': q[6], 'a': q[7], 'dmg': q[8] * R, 'mk': q[9] + 2 * q[10] + 3 * q[11] + 4 * q[12],
            'ew': ew, 'el': max(0, q[2] - ew), 'c11': q[14], 'c12': q[15], 'fl': q[17], 'ud': q[16], 'fs': q[19], 'us': q[20],
            'cred': credit * R, 'setups': (q[24] + q[25]) or q[5], 'entries': q[2], 'pk': q[22], 'maps': 1}


def feats(c, lg=None):
    R = c['R']
    if not R:
        return None
    ew, el, c11, c12 = c['ew'], c['el'], c['c11'], c['c12']
    if lg and c['entries']:
        p = (ew + 10 * lg['entry']) / (c['entries'] + 10)
        ew, el = c['entries'] * p, c['entries'] * (1 - p)
    if lg and c['setups']:
        won = c11 + c12
        p = (won + 10 * lg['clutch']) / (c['setups'] + 10)
        f = p * c['setups'] / won if won else 1
        c11, c12 = c11 * f, c12 * f
    return {'kpr': c['k'] / R, 'dpr': c['d'] / R, 'adr': c['dmg'] / R / 100, 'mks': c['mk'] / R, 'entry': (ew - el) / R,
            'clutch': (c11 + 1.5 * c12) / R, 'apr': c['a'] / R, 'fpr': c['fl'] / R, 'udr': c['ud'] / 100 / R, 'fsr': c['fs'] / R, 'usr': c['us'] / R,
            'pist': c['pk'] / max(1, c['maps']) / 2, 'cred': c['cred'] / R}


def credit_of(team, R, rf, ra):
    """the page's KAST-style outcome credit (OUT_W .5): half equally, half by round MVPs"""
    if not R:
        return [0] * len(team)
    e = 0.5 * (rf - ra) / (2 * R)
    mv = sum(q[18] for q in team)
    return [e * (0.5 / len(team) + 0.5 * (q[18] + 0.5) / (mv + 0.5 * len(team))) for q in team]


def load():
    d = json.load(gzip.open(DATA))
    maps = []   # one row per map: time, match id, both sides' [pid, counts], score, map name, team ids
    for m in sorted(d['matches'], key=lambda m: m['at'] or 0):
        if m.get('winner') not in ('faction1', 'faction2'):
            continue
        for mi, mp in enumerate(m['maps']):
            if mp.get('s1') is None or mp.get('s2') is None:
                continue
            P1 = [x for x in mp.get('p1') or [] if len(x) > 5 and x[5]]
            P2 = [x for x in mp.get('p2') or [] if len(x) > 5 and x[5]]
            if len(P1) != 5 or len(P2) != 5:
                continue
            R = mp['s1'] + mp['s2']
            c1 = credit_of([x[5] for x in P1], R, mp['s1'], mp['s2'])
            c2 = credit_of([x[5] for x in P2], R, mp['s2'], mp['s1'])
            maps.append({'at': m['at'], 'mid': m['id'], 'mi': mi, 'map': mp.get('map'), 'R': R, 's1': mp['s1'], 's2': mp['s2'],
                         't1': m['f1']['id'], 't2': m['f2']['id'], 'season': m['season'],
                         'L1': [(x[0], counts(x[5], R, mp['s1'], mp['s2'], c)) for x, c in zip(P1, c1)],
                         'L2': [(x[0], counts(x[5], R, mp['s2'], mp['s1'], c)) for x, c in zip(P2, c2)]})
    return d, maps


def league(maps):
    e = sum(c['ew'] for m in maps for _, c in m['L1'] + m['L2'])
    en = sum(c['entries'] for m in maps for _, c in m['L1'] + m['L2'])
    w = sum(c['c11'] + c['c12'] for m in maps for _, c in m['L1'] + m['L2'])
    s = sum(c['setups'] for m in maps for _, c in m['L1'] + m['L2'])
    return {'entry': e / en if en else .5, 'clutch': w / s if s else .3}


def descriptive_fit(maps, lam_frac=0.15, F=FEATS):
    """ARK 2's fit: team round margin on (sum of its five's per-map features - the other five's) / 2"""
    X, y = [], []
    for m in maps:
        f1 = [feats(c) for _, c in m['L1']]
        f2 = [feats(c) for _, c in m['L2']]
        a = [sum(f[k] for f in f1) for k in F]
        b = [sum(f[k] for f in f2) for k in F]
        X.append([(x - z) / 2 for x, z in zip(a, b)])
        y.append((m['s1'] - m['s2']) / (2 * m['R']))
    sd = [math.sqrt(sum(r[i] ** 2 for r in X) / len(X)) or 1 for i in range(len(F))]
    Z = [[r[i] / sd[i] for i in range(len(F))] for r in X]
    w = ridge(Z, y, lam_frac * len(X))
    return {k: w[i] / sd[i] for i, k in enumerate(F)}


def main():
    d, maps = load()
    n = len(maps)
    print('maps with full lines', n)
    cut = maps[int(n * 0.6)]['at']
    train = [m for m in maps if m['at'] < cut]
    lg = league(train)
    pop = [feats(c) for m in train for _, c in m['L1'] + m['L2']]
    mu = {k: sum(f[k] for f in pop) / len(pop) for k in FEATS_P}
    live = None
    try:
        live = json.load(open(os.path.join(ROOT, 'data', 'esea.json')))['arkModel']['beta']
    except Exception:
        pass
    beta_desc = descriptive_fit(train)
    res = {'maps': n, 'train_maps': len(train), 'cut': cut, 'league': lg, 'beta_desc': {k: round(v, 4) for k, v in beta_desc.items()}, 'beta_live': live}
    print('descriptive weights (train)', res['beta_desc'])
    print('live weights', live)

    # ---- walk through maps in time order, keeping each player's running counts --------------------
    def run(value_fn, K):
        """value_fn(counts) -> rounds/round over average; team = mean of five shrunk values; returns per-map
        (prior diff, outcome) for every map"""
        tot = defaultdict(lambda: dict.fromkeys(CNT, 0.0))
        out = []
        for m in maps:
            def team(L):
                v = []
                for pid, _ in L:
                    c = tot[pid]
                    if c['R']:
                        val = value_fn(c)
                        v.append(val * c['R'] / (c['R'] + K))
                    else:
                        v.append(0.0)
                return sum(v) / len(v)
            out.append((m, team(m['L1']) - team(m['L2'])))
            for L in (m['L1'], m['L2']):
                for pid, c in L:
                    t = tot[pid]
                    for k in CNT:
                        t[k] += c[k]
        return out

    def lin(beta, with_credit):
        def f(c):
            x = feats(c, lg)
            v = sum(beta[k] * (x[k] - mu[k]) for k in beta)
            return v + (c['cred'] / c['R'] if with_credit else 0)
        return f

    # stability: each feature's split-half reliability across players (odd vs even maps, 40+ rounds each half)
    halves = defaultdict(lambda: [dict.fromkeys(CNT, 0.0), dict.fromkeys(CNT, 0.0), 0])
    for m in train:
        for pid, c in m['L1'] + m['L2']:
            h = halves[pid]
            side = h[2] % 2
            for k in CNT:
                h[side][k] += c[k]
            h[2] += 1
    pairs = [(feats(a, lg), feats(b, lg), min(a['R'], b['R'])) for a, b, _ in halves.values() if a['R'] >= 40 and b['R'] >= 40]
    rel = {}
    for k in FEATS_P + ['cred']:
        xs = [p[0][k] for p in pairs]
        ys = [p[1][k] for p in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        r = cov / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        Rm = sum(p[2] for p in pairs) / len(pairs)
        # rounds at which the stat is half signal: k = R (1 - r) / r (Spearman-Brown on the mean half size)
        rel[k] = {'r': round(r, 3), 'k_rounds': round(Rm * (1 - r) / r) if r > 0.01 else 99999}
    res['reliability'] = rel
    print('feature split-half', rel)

    def stab_fn(beta, credit=False):
        def f(c):
            x = feats(c, lg)
            v = x['cred'] * c['R'] / (c['R'] + rel['cred']['k_rounds']) if credit else 0
            for k in beta:
                kk = rel[k]['k_rounds']
                w = c['R'] / (c['R'] + kk)
                v += beta[k] * (mu[k] + w * (x[k] - mu[k]) - mu[k])
            return v
        return f

    # predictive weights: players' career averages before the map -> this map's margin (train only)
    def pred_fit(F=FEATS):
        tot = defaultdict(lambda: dict.fromkeys(CNT, 0.0))
        X, y = [], []
        for m in train:
            rows = []
            for L in (m['L1'], m['L2']):
                acc = [0.0] * len(F)
                for pid, _ in L:
                    c = tot[pid]
                    if c['R'] >= 50:
                        x = feats(c, lg)
                        w = c['R'] / (c['R'] + 300)
                        for i, k in enumerate(F):
                            acc[i] += w * (x[k] - mu[k])
                rows.append(acc)
            X.append([(a - b) / 2 for a, b in zip(*rows)])
            y.append((m['s1'] - m['s2']) / (2 * m['R']))
            for L in (m['L1'], m['L2']):
                for pid, c in L:
                    for k in CNT:
                        tot[pid][k] += c[k]
        sd = [math.sqrt(sum(r[i] ** 2 for r in X) / len(X)) or 1 for i in range(len(F))]
        Z = [[r[i] / sd[i] for i in range(len(F))] for r in X]
        # ridge strength picked on the last quarter of the training maps, then refit on all of them
        q = int(len(Z) * 0.75)
        best = None
        for lam in (1, 10, 30, 100, 300, 1000, 3000):
            w = ridge(Z[:q], y[:q], lam)
            mse = sum((sum(a * b for a, b in zip(w, z)) - t) ** 2 for z, t in zip(Z[q:], y[q:])) / (len(Z) - q)
            if best is None or mse < best[0]:
                best = (mse, lam)
        w = ridge(Z, y, best[1])
        return {k: w[i] / sd[i] for i, k in enumerate(F)}

    beta_pred = pred_fit()
    beta_pred_p = pred_fit(FEATS_P)
    beta_desc_p = descriptive_fit(train, F=FEATS_P)
    res['beta_desc_pistol'] = {k: round(v, 4) for k, v in beta_desc_p.items()}
    res['beta_pred_pistol'] = {k: round(v, 4) for k, v in beta_pred_p.items()}
    print('descriptive + pistol', res['beta_desc_pistol'])
    print('predictive + pistol', res['beta_pred_pistol'])
    res['beta_pred'] = {k: round(v, 4) for k, v in beta_pred.items()}
    print('predictive weights', res['beta_pred'])

    variants = {'kd': lambda c: (c['k'] - c['d']) / c['R'] * 0.12,
                'ark': lin(live or beta_desc, False), 'ark_out': lin(live or beta_desc, True),
                'ark_refit': lin(beta_desc, False), 'stab': stab_fn(live or beta_desc), 'pred': lin(beta_pred, False),
                'ark_pistol': lin(beta_desc_p, True), 'pred_pistol': lin(beta_pred_p, False), 'stab_refit': stab_fn(beta_desc), 'stab_out': stab_fn(live or beta_desc, True), 'pred_stab': stab_fn(beta_pred, False), 'pred_stab_out': stab_fn(beta_pred, True)}
    scores = {}
    test_ids = None
    perm = {}
    for name, fn in variants.items():
        best = None
        for K in (0, 100, 200, 400, 800, 1600):
            out = run(fn, K)
            tr = [(m, x) for m, x in out if m['at'] < cut]
            # logistic slope on train (map won or lost)
            Xs = [[x] for _, x in tr]
            ys = [1 if m['s1'] > m['s2'] else 0 for m, _ in tr]
            b = [0.0]
            for _ in range(30):
                g = h = 0
                for xx, t in zip(Xs, ys):
                    p = 1 / (1 + math.exp(-b[0] * xx[0]))
                    g += (t - p) * xx[0]
                    h += p * (1 - p) * xx[0] ** 2
                b[0] += g / (h + 1e-9)
            trll = sum(ll(1 / (1 + math.exp(-b[0] * x)), 1 if m['s1'] > m['s2'] else 0) for m, x in tr) / len(tr)
            if best is None or trll < best[0]:
                best = (trll, K, b[0], out)
        trll, K, slope, out = best
        te = [(m, x) for m, x in out if m['at'] >= cut]
        L = {(m['mid'], m['mi']): ll(1 / (1 + math.exp(-slope * x)), 1 if m['s1'] > m['s2'] else 0) for m, x in te}
        perm[name] = L
        scores[name] = {'K': K, 'slope': round(slope, 2), 'train_ll': round(trll, 4), 'test_ll': round(sum(L.values()) / len(L), 4), 'n_test': len(L)}
    base = perm['ark_out']
    for name in variants:
        dd = [perm[name][k] - base[k] for k in base]
        mu_ = sum(dd) / len(dd)
        sd_ = math.sqrt(sum((x - mu_) ** 2 for x in dd) / (len(dd) - 1)) or 1e-9
        scores[name]['vs_ark_out_t'] = round(mu_ / (sd_ / math.sqrt(len(dd))), 2) if name != 'ark_out' else None
        print('ark', name, scores[name])
    res['ark'] = scores

    # split-half reliability of each rating (players with 200+ rounds each half, all maps)
    allh = defaultdict(lambda: [dict.fromkeys(CNT, 0.0), dict.fromkeys(CNT, 0.0), 0])
    for m in maps:
        for pid, c in m['L1'] + m['L2']:
            h = allh[pid]
            for k in CNT:
                h[h[2] % 2][k] += c[k]
            h[2] += 1
    hp = [(a, b) for a, b, _ in allh.values() if a['R'] >= 150 and b['R'] >= 150]
    relr = {}
    for name, fn in variants.items():
        xs = [fn(a) for a, _ in hp]
        ys = [fn(b) for _, b in hp]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        relr[name] = round(r, 3)
    res['split_half'] = {'players': len(hp), 'r': relr}
    print('rating split-half', len(hp), relr)

    # ---- veto: map-strength sources ------------------------------------------------------------
    pm, tm = d.get('playerMaps') or {}, d.get('teamMaps') or {}
    lgx = lambda p: math.log(clip(p) / (1 - clip(p)))

    plater = defaultdict(lambda: [0, 0])     # (player, map) -> this and later league maps won, played
    plater_all = defaultdict(lambda: [0, 0])
    for m in maps:
        w = 1 if m['s1'] > m['s2'] else 0
        for L, y in ((m['L1'], w), (m['L2'], 1 - w)):
            for pid, _ in L:
                plater[(pid, m['map'])][0] += y
                plater[(pid, m['map'])][1] += 1
                plater_all[pid][0] += y
                plater_all[pid][1] += 1

    def dev_player(pids, mp, k=50):
        v = []
        for pid in pids:
            s = pm.get(pid)
            if not s or mp not in s['maps'] or not s['life'][0]:
                continue
            n_, wr, _ = s['maps'][mp]
            life_n, life_wr = s['life']
            if wr is None or life_wr is None:
                continue
            lw, ln = plater[(pid, mp)]
            aw, an = plater_all[pid]
            if n_ - ln <= 0 or life_n - an <= 0:
                continue
            wr = (wr / 100 * n_ - lw) / (n_ - ln) * 100
            life_wr = (life_wr / 100 * life_n - aw) / (life_n - an) * 100
            n_ -= ln
            if not (0 < wr < 100 and 0 < life_wr < 100):
                continue
            v.append((lgx(wr / 100) - lgx(life_wr / 100)) * n_ / (n_ + k))
        return sum(v) / len(v) if v else 0.0

    # later league maps per (team, map) and per team, to take back out of the lifetime splits (no leakage)
    later = defaultdict(lambda: [0, 0])
    later_all = defaultdict(lambda: [0, 0])
    for m in maps:
        if not m['map']:
            continue
        w = 1 if m['s1'] > m['s2'] else 0
        for t, y in ((m['t1'], w), (m['t2'], 1 - w)):
            later[(t, m['map'])][0] += y
            later[(t, m['map'])][1] += 1
            later_all[t][0] += y
            later_all[t][1] += 1

    def dev_team(tid, mp, k=8):
        s = tm.get(tid)
        if not s or mp not in s['maps']:
            return 0.0
        n_, wr, _ = s['maps'][mp]
        if wr is None:
            return 0.0
        lw, ln = later[(tid, mp)]
        n_, wr = max(0, n_ - ln), (wr / 100 * n_ - lw) / max(1, n_ - ln) * 100 if n_ - ln > 0 else 50
        aw, an = later_all[tid]
        L0, Lw = s['life'][0] or 0, (s['life'][1] or 50) / 100 * (s['life'][0] or 0)
        s = {'life': [max(0, L0 - an), ((Lw - aw) / max(1, L0 - an)) * 100 if L0 - an > 0 else 50]}
        return lgx((wr * n_ + 50 * k) / (n_ + k) / 100) - lgx(((s['life'][1] or 50) * s['life'][0] + 50 * k) / (s['life'][0] + k) / 100) if s['life'][0] else 0.0

    # overall strength: the best ARK variant's prior diff; map term on top, fit on train, scored on test
    strength = {(m['mid'], m['mi']): x for m, x in run(variants['ark_out'], scores['ark_out']['K'])}
    hist = defaultdict(lambda: [0, 0])   # (team, map) -> league maps won, played (earlier only)
    rows = []
    pist = defaultdict(lambda: [0.0, 0.0])   # (team, map) -> pistol kills for, against (earlier maps)
    pist_lg = defaultdict(lambda: [0.0, 0.0])
    for m in maps:
        if not m['map']:
            continue
        h1, h2 = hist[(m['t1'], m['map'])], hist[(m['t2'], m['map'])]
        def pshare(t, k=40):
            f, a = pist[(t, m['map'])]
            lf, la = pist_lg[m['map']]
            base = lf / (lf + la) if lf + la else 0.5
            return lgx((f + k * base) / (f + a + k)) if True else 0
        dl = lgx((h1[0] + 4) / (h1[1] + 8)) - lgx((h2[0] + 4) / (h2[1] + 8))
        rows.append({'m': m, 'x': strength[(m['mid'], m['mi'])], 'y': 1 if m['s1'] > m['s2'] else 0,
                     'player': dev_player([p for p, _ in m['L1']], m['map']) - dev_player([p for p, _ in m['L2']], m['map']),
                     'team': dev_team(m['t1'], m['map']) - dev_team(m['t2'], m['map']), 'league': dl,
                     'pistol': pshare(m['t1']) - pshare(m['t2'])})
        w = 1 if m['s1'] > m['s2'] else 0
        for L, y in ((m['L1'], w), (m['L2'], 1 - w)):
            for pid, _ in L:
                plater[(pid, m['map'])][0] -= y
                plater[(pid, m['map'])][1] -= 1
                plater_all[pid][0] -= y
                plater_all[pid][1] -= 1
        for t, y in ((m['t1'], w), (m['t2'], 1 - w)):
            later[(t, m['map'])][0] -= y
            later[(t, m['map'])][1] -= 1
            later_all[t][0] -= y
            later_all[t][1] -= 1
        p1 = sum(c['pk'] for _, c in m['L1'])
        p2 = sum(c['pk'] for _, c in m['L2'])
        pist[(m['t1'], m['map'])][0] += p1
        pist[(m['t1'], m['map'])][1] += p2
        pist[(m['t2'], m['map'])][0] += p2
        pist[(m['t2'], m['map'])][1] += p1
        pist_lg[m['map']][0] += p1
        pist_lg[m['map']][1] += p2
        h1[0] += w
        h1[1] += 1
        h2[0] += 1 - w
        h2[1] += 1
    tr = [r for r in rows if r['m']['at'] < cut]
    te = [r for r in rows if r['m']['at'] >= cut]

    def logit(rows_, ks):
        b = [0.0] * len(ks)
        for _ in range(40):
            g = [0.0] * len(ks)
            H = [[1e-6 * (i == j) for j in range(len(ks))] for i in range(len(ks))]
            for r in rows_:
                z = sum(bi * r[k] for bi, k in zip(b, ks))
                p = 1 / (1 + math.exp(-z))
                for i, ki in enumerate(ks):
                    g[i] += (r['y'] - p) * r[ki]
                    for j, kj in enumerate(ks):
                        H[i][j] += p * (1 - p) * r[ki] * r[kj]
            st = solve(H, g)
            if not st:
                break
            b = [bi + si for bi, si in zip(b, st)]
        return b

    veto = {'n_train': len(tr), 'n_test': len(te), 'coverage': {'players_with_splits': len(pm), 'teams_with_splits': len(tm)}}
    base_b = logit(tr, ['x'])
    base_L = {id(r): ll(1 / (1 + math.exp(-base_b[0] * r['x'])), r['y']) for r in te}
    veto['strength_only'] = {'coef': [round(c, 3) for c in base_b], 'test_ll': round(sum(base_L.values()) / len(te), 4)}
    for r in rows:
        r['pt'] = 0.5 * r['player'] * 5 + 0.5 * r['team'] * 1.6   # equal blend on each source's fitted scale
    for src in ('player', 'team', 'league', 'pistol', 'pt'):
        b = logit(tr, ['x', src])
        L = {id(r): ll(1 / (1 + math.exp(-(b[0] * r['x'] + b[1] * r[src]))), r['y']) for r in te}
        dd = [L[k] - base_L[k] for k in base_L]
        mu_ = sum(dd) / len(dd)
        sd_ = math.sqrt(sum((x - mu_) ** 2 for x in dd) / (len(dd) - 1)) or 1e-9
        veto[src] = {'coef': [round(c, 3) for c in b], 'test_ll': round(sum(L.values()) / len(te), 4), 'vs_strength_t': round(mu_ / (sd_ / math.sqrt(len(dd))), 2)}
        print('veto', src, veto[src])
    print('veto strength only', veto['strength_only'])
    res['veto'] = veto
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
