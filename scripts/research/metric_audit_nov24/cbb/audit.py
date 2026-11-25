#!/usr/bin/env python3
"""CBB metric audit (Nov 24 2026): every CBB player metric on one team harness, plus the pre-registered candidates
(prereg.md). Data: scripts/.cache/team_adj/adv<y>.csv + tr<y>.json (Barttorvik, 2010-2026; no 2026-27), roster prior
inputs from /mnt/project-files/cbb/backtest/research_seasons.csv.   python3 audit.py -> results.json"""
import csv, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'team_adj_nov24')); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import core
from cbb_data import BT_COLS
C = os.path.join(ROOT, 'scripts', '.cache', 'team_adj')
ix = {k: i for i, k in enumerate(BT_COLS)}
YEARS = range(2010, 2027); PAIRS = list(range(2012, 2026)); LO, MINN = 200, 300
POSMAP = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'G', 'Wing F': 'F', 'Stretch 4': 'F', 'PF/C': 'C', 'C': 'C'}
RNG = np.random.default_rng(0); NB = 2000


def fl(x):
    try:
        v = float(x); return v if v == v else None
    except (TypeError, ValueError): return None


def load(y):
    tr = json.load(open(os.path.join(C, f'tr{y}.json')))
    em, wp = {}, {}
    for r in tr:
        try: w, l = (int(v) for v in str(r[3]).split('-')[:2])
        except ValueError: continue
        g = w + l
        if g: em[r[1]] = ((r[4] - r[6]) * g, g); wp[r[1]] = (w, g)
    P = defaultdict(lambda: defaultdict(float)); parts = []
    for row in csv.reader(open(os.path.join(C, f'adv{y}.csv'), encoding='utf-8', errors='replace')):
        if len(row) < 66: continue
        t, pid = row[ix['team']], row[ix['pid']]
        gp, mp, b = fl(row[ix['gp']]), fl(row[ix['mp']]), fl(row[ix['bpm']])
        if t not in em or not gp or not mp or b is None: continue
        e = gp * mp; parts.append((pid, t, e))
        q = P[pid]; q['e'] += e
        for k in ('bpm', 'gbpm', 'obpm', 'dbpm'):
            q[k] += (fl(row[ix[k]]) or 0.0) * e
        for k in ('porpag', 'dporpag'):     # per game -> season total
            q[k] += (fl(row[ix[k]]) or 0.0) * gp
        q['pos'] = POSMAP.get(row[ix['role']], 'F'); q['yr'] = row[ix['yr']]; q['mpct'] = fl(row[ix['min_per']]) or 0.0
    pl = {}
    for pid, q in P.items():
        e = q['e']; pl[pid] = {'e': e, 'bpm': q['bpm'] / e, 'gbpm': q['gbpm'] / e, 'prpg': q['porpag'] / e,
                               'tprpg': (q['porpag'] + q['dporpag']) / e, 'pos': q['pos'], 'yr': q['yr'], 'mpct': q['mpct']}
    # Stat+: season norms by position, minutes weighted, 10%+ of team minutes
    nrm = {}
    for p in 'GFC':
        L = [(v['bpm'], v['e']) for v in pl.values() if v['pos'] == p and v['mpct'] >= 10]
        x, w = np.array([a for a, _ in L]), np.array([b for _, b in L]); m = np.average(x, weights=w)
        nrm[p] = (m, math.sqrt(np.average((x - m) ** 2, weights=w)))
    for v in pl.values():
        m, s = nrm[v['pos']]; v['splus'] = 100 + 25 * (v['bpm'] - m) / s; v['war'] = v['bpm'] + 2.0
    return {'parts': parts, 'pl': pl, 'em': em, 'wp': wp}


S = {y: load(y) for y in YEARS}


def D(y, val, res='em'): return {'parts': S[y]['parts'], 'val': val, 'team': S[y][res]}
def vals(y, k): return {pid: v[k] for pid, v in S[y]['pl'].items()}


# ---------------------------------------------------------------- describe
def drows(y, val, res):
    return [(x, yy) for _, x, yy, _ in core.centred(D(y, val, res), y, val)]


def describe(valf, res, seasons=PAIRS + [2026]):
    R = {y: drows(y, valf(y), res) for y in seasons}
    return R, describe_score(R)


def loso_sse(R, ys):
    """per season: SSE of the no-intercept slope fit on the other seasons, and SST"""
    out = {}
    for y in ys:
        xs = np.array([x for s in ys if s != y for x, _ in R[s]]); yy = np.array([b for s in ys if s != y for _, b in R[s]])
        b = float(xs @ yy / (xs @ xs)); X = np.array([x for x, _ in R[y]]); Y = np.array([v for _, v in R[y]])
        out[y] = (float(((Y - b * X) ** 2).sum()), float((Y ** 2).sum()))
    return out


def describe_score(R):
    ys = sorted(R)
    allr = [r for y in ys for r in R[y]]
    ins = core.r2(*zip(*allr)); L = loso_sse(R, ys)
    ho = 1 - sum(a for a, _ in L.values()) / sum(b for _, b in L.values())
    bs = []
    for _ in range(NB):
        pp = RNG.choice(ys, len(ys)); bs.append(1 - sum(L[p][0] for p in pp) / sum(L[p][1] for p in pp))
    return {'inSample': round(ins, 4), 'heldOut': round(ho, 4), 'heldOut90': [round(float(np.percentile(bs, 5)), 4), round(float(np.percentile(bs, 95)), 4)], 'seasons': len(ys)}


# ---------------------------------------------------------------- predict
def predict_rows(n, vn, k_next):
    """team rows for pair n (predictor vn: pid -> rate) and player pairs vs the n+1 metric k_next and n+1 BPM"""
    e0 = {pid: v['e'] for pid, v in S[n]['pl'].items()}
    low = [v for pid, v in vn.items() if e0.get(pid, 0) < LO] or list(vn.values())
    fill = float(np.mean(low))
    nx = D(n + 1, vals(n + 1, 'bpm'))
    fd = {pid: fill for pid, t, x in nx['parts'] if pid not in vn}
    rows = [(x, y) for _, x, y, _ in core.centred(nx, n + 1, vn, fd)]
    P1 = S[n + 1]['pl']
    pp = [(vn[pid], P1[pid][k_next], P1[pid]['bpm'], P1[pid]['e']) for pid in P1 if pid in vn and pid in S[n]['pl'] and P1[pid]['e'] >= MINN]
    return rows, pp


def predict(vnf, k_next='bpm', pairs=PAIRS):
    per, pp = {}, {}
    for n in pairs:
        per[n], pp[n] = predict_rows(n, vnf(n), k_next)
    return per, pp, predict_score(per, pp)


def predict_score(per, pp, pairs=PAIRS):
    f = lambda ps: core.r2(*zip(*[r for n in ps for r in per[n]]))
    bs = [f(RNG.choice(pairs, len(pairs))) for _ in range(NB)]
    P = [q for n in pairs for q in pp[n]]
    own = core.wcorr([q[0] for q in P], [q[1] for q in P], [q[3] for q in P])
    vb = core.wcorr([q[0] for q in P], [q[2] for q in P], [q[3] for q in P])
    return {'teamR2': round(f(pairs), 4), 'teamR2_90': [round(float(np.percentile(bs, 5)), 4), round(float(np.percentile(bs, 95)), 4)],
            'playerR': round(own, 4), 'playerR_vsBPM': round(vb, 4), 'nPlayers': len(P), 'pairs': len(pairs),
            'byPair': {n: round(core.r2(*zip(*per[n])), 4) for n in pairs}}


# ---------------------------------------------------------------- roster prior (scripts/cbb_roster.py player model)
def roster_prior():
    """pair n -> {pid: walk-forward projected BPM for season n+1} (fit on target seasons <= n)"""
    import cbb_roster as R
    by = R.load_seasons(); ts = R.team_strength(by)
    rows = defaultdict(list)
    for y in sorted(by):
        if y - 1 not in by: continue
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            k = R.kind(r, p, h)
            rows[y].append((pid, k, R.xrow(k, r, h if h else p, ts, y), max(-15, min(15, R.f(r['bpm'], R.REPL))), R.f(r['min_per'], 0)))
    out = {}
    for n in PAIRS:
        y = n + 1; tr = [q for yy in rows if yy <= n for q in rows[yy]]; M = {}
        for k in ('ret', 'tr', 'fr', 'new', 'back'):
            Q = [q for q in tr if q[1] == k]
            if Q: M[k] = R.wls([q[2] for q in Q], [q[3] for q in Q], [q[4] / 100 + 0.02 for q in Q])
        out[n] = {pid: (float(np.dot(M[k], x)), k) for pid, k, x, _, _ in rows[y] if k in M}
    return out


def t_sf(t, df):
    """one-sided Student t tail P(T > t) by numerical integration (no scipy here)"""
    x = np.linspace(t, t + 400, 400001)
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    v = c * (1 + x ** 2 / df) ** (-(df + 1) / 2)
    return float(np.trapezoid(v, x)) if t >= 0 else 1 - t_sf(-t, df)


def paired_t(d):
    d = np.asarray(d, float)
    if len(d) < 3 or d.std() == 0: return 0.0, 0.5
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    return round(t, 2), t_sf(t, len(d) - 1)


def main():
    out = {'pairs': PAIRS, 'targets': {'describe': 'win% (actual) and adjEM', 'predict': 'next-season adjEM'}, 'metrics': {}}
    M = {'BPM (Torvik; WAA rate)': 'bpm', 'WAR rate (BPM + 2)': 'war', 'Stat+': 'splus', 'GBPM (Torvik)': 'gbpm',
         'PRPG! (Torvik, offense)': 'prpg', 'total PRPG (O + D)': 'tprpg'}
    for name, k in M.items():
        _, dw = describe(lambda y: vals(y, k), 'wp'); _, de = describe(lambda y: vals(y, k), 'em')
        _, _, pr = predict(lambda n: vals(n, k), k)
        out['metrics'][name] = {'describeWin': dw, 'describeEM': de, 'predict': pr}
        print(name, dw['inSample'], dw['heldOut'], de['heldOut'], pr['teamR2'], pr['playerR'], flush=True)
    RP = roster_prior()
    for name, kinds in (('roster prior BPM_hat (returners; same fill)', ('ret', 'tr', 'back')), ('roster prior BPM_hat (all, own newcomer projections)', None)):
        vnf = lambda n: {pid: v for pid, (v, k) in RP[n].items() if kinds is None or k in kinds}
        _, _, pr = predict(vnf, 'bpm')
        out['metrics'][name] = {'describeWin': None, 'describeEM': None, 'predict': pr}
        print(name, pr['teamR2'], pr['playerR'], flush=True)

    # ------------------------------------------------ candidates
    cand = {}
    base_per, base_pp, base = predict(lambda n: vals(n, 'bpm'))

    def tuned(grid, make):
        """leave-one-pair-out choice of the grid value; returns per-pair rows, player pairs, chosen values"""
        G = {g: predict(lambda n: make(n, g)) for g in grid}
        per, pp, ch = {}, {}, {}
        for n in PAIRS:
            others = [m for m in PAIRS if m != n]
            best = max(grid, key=lambda g: core.r2(*zip(*[r for m in others for r in G[g][0][m]])))
            per[n], pp[n], ch[n] = G[best][0][n], G[best][1][n], best
        return per, pp, ch

    def two_year(n, w):
        a, b = S[n]['pl'], S[n - 1]['pl']
        return {pid: (v['bpm'] * v['e'] + w * b[pid]['bpm'] * b[pid]['e']) / (v['e'] + w * b[pid]['e']) if pid in b else v['bpm'] for pid, v in a.items()}

    def shrink(n, k):
        a = S[n]['pl']; c = float(np.mean([v['bpm'] for v in a.values() if v['e'] < LO]))
        return {pid: (v['bpm'] * v['e'] + c * k) / (v['e'] + k) for pid, v in a.items()}

    def blend(n, a_, key='gbpm'):
        return {pid: (1 - a_) * v['bpm'] + a_ * v[key] for pid, v in S[n]['pl'].items()}

    def class_step():
        per, pp, ch = {}, {}, {}
        for n in PAIRS:
            num, den = defaultdict(float), defaultdict(float)
            for m in PAIRS:
                if m == n: continue
                for pid, v in S[m]['pl'].items():
                    w = S[m + 1]['pl'].get(pid)
                    if w and w['e'] >= MINN: num[v['yr']] += (w['bpm'] - v['bpm']) * w['e']; den[v['yr']] += w['e']
            d = {c: num[c] / den[c] for c in den}
            vn = {pid: v['bpm'] + d.get(v['yr'], 0.0) for pid, v in S[n]['pl'].items()}
            per[n], pp[n] = predict_rows(n, vn, 'bpm'); ch[n] = {c: round(x, 2) for c, x in d.items()}
        return per, pp, ch

    tests = {'P1 two-year BPM': tuned([0, .25, .5, .75, 1], two_year), 'P2 minutes shrink': tuned([0, 100, 200, 400, 800], shrink),
             'P3 class step': class_step(), 'P4 GBPM blend': tuned([0, .25, .5, .75, 1], blend)}
    for name, (per, pp, ch) in tests.items():
        sc = predict_score(per, pp)
        d = [sc['byPair'][n] - base['byPair'][n] for n in PAIRS]
        t, p = paired_t(d)
        bsd = [np.mean([d[i] for i in RNG.integers(0, len(d), len(d))]) for _ in range(NB)]
        cand[name] = {'target': 'next-season team R2 (adjEM)', 'before': base['teamR2'], 'after': sc['teamR2'], 'after90': sc['teamR2_90'],
                      'playerR_vsBPM': [base['playerR_vsBPM'], sc['playerR_vsBPM']], 'pairsBetter': int(sum(x > 0 for x in d)),
                      't': t, 'p': p, 'pBetterBoot': round(float(np.mean(np.array(bsd) > 0)), 3), 'chosen': {str(k): v for k, v in ch.items()},
                      'guard': bool(sc['playerR_vsBPM'] >= base['playerR_vsBPM'] - .01)}
        print(name, cand[name]['before'], cand[name]['after'], t, p, flush=True)

    # descriptive candidates on win%: tune a by the other seasons' held-out fit, per-season SSE vs base
    ys = PAIRS + [2026]
    RB = {y: drows(y, vals(y, 'bpm'), 'wp') for y in ys}; LB = loso_sse(RB, ys)
    sd = {y: float(np.std([v['bpm'] for v in S[y]['pl'].values()])) for y in ys}

    def dblend(y, a_, key):
        pl = S[y]['pl']
        if key == 'gbpm': return {pid: (1 - a_) * v['bpm'] + a_ * v['gbpm'] for pid, v in pl.items()}
        z = np.array([v['tprpg'] for v in pl.values()]); m, s = float(z.mean()), float(z.std())
        return {pid: v['bpm'] + a_ * sd[y] * (v['tprpg'] - m) / s for pid, v in pl.items()}

    for name, grid, key in (('D1 GBPM blend', [0, .25, .5, .75, 1], 'gbpm'), ('D2 PRPG blend', [0, .25, .5, 1], 'tprpg')):
        G = {g: {y: drows(y, dblend(y, g, key), 'wp') for y in ys} for g in grid}
        sse, ch = {}, {}
        for y in ys:
            oth = [s for s in ys if s != y]
            def ho(g):
                L = loso_sse({s: G[g][s] for s in oth}, oth); return sum(a for a, _ in L.values()) / sum(b for _, b in L.values())
            g = min(grid, key=ho); ch[y] = g
            xs = np.array([x for s in oth for x, _ in G[g][s]]); yy = np.array([b for s in oth for _, b in G[g][s]]); b = float(xs @ yy / (xs @ xs))
            X = np.array([x for x, _ in G[g][y]]); Y = np.array([v for _, v in G[g][y]]); sse[y] = float(((Y - b * X) ** 2).sum())
        sst = sum(LB[y][1] for y in ys)
        d = [LB[y][0] - sse[y] for y in ys]          # positive = candidate better
        t, p = paired_t(d)
        cand[name] = {'target': 'held-out describe R2 (win%)', 'before': round(1 - sum(LB[y][0] for y in ys) / sst, 4),
                      'after': round(1 - sum(sse.values()) / sst, 4), 'seasonsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': p,
                      'chosen': {str(k): v for k, v in ch.items()}, 'guard': True}
        print(name, cand[name]['before'], cand[name]['after'], t, p, flush=True)

    # Holm over the batch of 6
    order = sorted(cand, key=lambda k: cand[k]['p']); m = len(order); stop = False
    for i, k in enumerate(order):
        adj = min(1.0, cand[k]['p'] * (m - i)); cand[k]['pHolm'] = round(adj, 4)
        ok = (not stop) and adj < .05 and cand[k]['after'] > cand[k]['before'] and cand[k]['guard']
        if adj >= .05: stop = True
        cand[k]['pass'] = bool(ok); cand[k]['p'] = round(cand[k]['p'], 4)
    out['candidates'] = cand
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
