"""Does the CFB preseason prior gain from roster turnover? A backtest on free data only (no CFBD calls):
ESPN scores and closes (scripts/cfb_espn_hist.py), ESPN box scores and 247 composite classes
(scripts/cfb_roster_hist.py), and USA Today's head coach by school and year (scripts/cfb_coach_fit.py's pulls).

Each FBS team-season gets a preseason prior in points, a regression of its season-end rating on what was known in
August; the in-season rating is a ridge margin rating shrunk toward that prior with lam games of weight (the live
model's prior plays the same part: scripts/cfb_model.mjs eloStart and adjust). Every game is predicted from the games
before it. Inputs, for season S:
  last, last2   season-end margin rating (points over the FBS mean) in S-1 and S-2
  qbRet         share of S-1 passing yards thrown by players back on the team in S
  offRet        share of S-1 rushing + receiving yards back
  tal           247 composite, the team's signees in classes S-3..S (top 20 a class, composite over .75), z
  fresh         the same for class S alone (the true freshmen)
  hcNew         a new head coach (USA Today, by coach id; 2026 from the coaching market's tenure)
  qbIn, offIn   transfers in: S-1 passing / rushing + receiving yards by players who played for another FBS team in S-1,
                over the team's own S-1 totals (the portal; fit on NIL-era seasons only, 2022 on)
  young         share of S-1 yards back from players in their first or second season with a stat line (development:
                young players improve; experience counted from the 2014 boxes, so clean from 2017 on)
  x terms       last x (1 - offRet) and last x hcNew: a good team that loses its players or its coach regresses more
"Back on the team" is read from the box scores: the player recorded a stat for the team in S, or in S+1 without
playing for anyone else in S (a player hurt all of S is still back, as an August roster would have him). Players who
recorded nothing (most linemen) are not counted either way.

Selection follows the project rule: forward selection on the tuning seasons (paired per game log loss, t <= -1.5,
every weight positive in the direction it should be), then each kept input must not be worse on the held-out
seasons. Roster inputs: tune 2016-20, hold out 2021-26 (2026 through the games played). young: tune 2018-20. Portal
inputs, on top of what was kept: tune 2022-23, hold out 2024-26. (ESPN boxes carry tackles in full only from
2024, so defensive returning production can't be tested.)
  OMP_NUM_THREADS=1 python3 scripts/cfb_roster_prior.py
Writes data/cfb_roster_prior.json: the evidence, and (feats) the roster inputs for the last two seasons, which the
live prior reads. Refresh each season once week 2 is played (back / in are read from appearances; weeks 1-2 alone
give the same gain, see leakCheck), after scripts/cfb_espn_hist.py, scripts/cfb_roster_hist.py (boxes, then --247
for the new class). Until the file has the season, the live prior falls back to CFBD talent and returning PPA.
"""
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cfb_elo_research import close_of, phi  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_hist')
R247 = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'r247')
HC = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'hc_by_year.json')
OUT = os.path.join(ROOT, 'data', 'cfb_roster_prior.json')
SEASONS = list(range(2014, 2027))
TUNE, HOLD = list(range(2016, 2021)), list(range(2021, 2027))
PTUNE, PHOLD = [2022, 2023], [2024, 2025, 2026]
YTUNE = [2018, 2019, 2020]
FCS = 'FCS'
r4 = lambda x: round(float(x), 4)


# ---- data --------------------------------------------------------------------------------------------------
def load_games():
    G = {}
    for S in SEASONS:
        p = os.path.join(DIR, f'games{S}.json')
        if not os.path.exists(p):
            continue
        gs = [g for g in json.load(open(p)) if g['done'] and g['hp'] is not None and g['ap'] is not None]
        n80 = Counter()
        for g in gs:
            if g['grp'] == 'fbs':
                n80[g['h']] += 1
                n80[g['a']] += 1
        fbs = {t for t, c in n80.items() if c >= 4}
        rows = [{'id': g['id'], 'S': S, 'w': g['w'], 'date': g['date'], 'h': g['h'] if g['h'] in fbs else FCS,
                 'a': g['a'] if g['a'] in fbs else FCS, 'n': g['n'], 'm': g['hp'] - g['ap'],
                 'close': close_of(g.get('lines') or [])}
                for g in gs if g['h'] in fbs or g['a'] in fbs]
        rows = [r for r in rows if not (r['h'] == FCS and r['a'] == FCS)]
        rows.sort(key=lambda r: r['date'])
        G[S] = {'rows': rows, 'fbs': fbs, 'raw': gs}
    return G


def massey(rows, teams, prior=None, lam=0.0, hfa=None):
    """Ridge margin rating: m = R[h] - R[a] + hfa (0 at neutral sites), margins capped at 35, shrunk toward prior with
    lam games of weight. FCS opponents share one rating. Returns (ratings, hfa)."""
    idx = {t: i for i, t in enumerate(teams)}
    k = len(teams) + (hfa is None)
    A = np.zeros((k, k))
    b = np.zeros(k)
    for r in rows:
        x = np.zeros(k)
        x[idx[r['h']]] += 1
        x[idx[r['a']]] -= 1
        y = max(-35, min(35, r['m']))
        if hfa is None:
            x[-1] = 0 if r['n'] else 1
        else:
            y -= 0 if r['n'] else hfa
        A += np.outer(x, x)
        b += x * y
    p0 = np.zeros(k)
    for t, i in idx.items():
        p0[i] = (prior or {}).get(t, 0.0)
    L = np.full(k, max(lam, 1e-3))
    if hfa is None:
        L[-1] = 1e-3
    A += np.diag(L)
    b += L * p0
    sol = np.linalg.solve(A, b)
    R = {t: float(sol[i]) for t, i in idx.items()}
    return R, (float(sol[-1]) if hfa is None else hfa)


def finals(G):
    """Season-end rating, centred on the FBS mean."""
    F = {}
    for S, g in G.items():
        teams = sorted(g['fbs']) + [FCS]
        R, h = massey(g['rows'], teams, lam=0.3)
        m = np.mean([R[t] for t in g['fbs']])
        F[S] = {t: v - m for t, v in R.items()}
    return F


def boxes(G, early=None):
    """Per season: team -> athlete -> summed stats, and athlete -> set of teams he recorded a stat for (with early, in
    the season's first weeks only)."""
    B, onT = {}, {}
    for S, g in G.items():
        tot = defaultdict(lambda: defaultdict(Counter))
        on = defaultdict(set)
        for e in g['raw']:
            if e['grp'] != 'fbs':
                continue
            p = os.path.join(DIR, 'box', f"{e['id']}.json")
            if not os.path.exists(p):
                continue
            for tid, P in json.load(open(p)).items():
                for aid, s in P.items():
                    if early is None or e['w'] <= early:
                        on[aid].add(tid)
                    for k, v in s.items():
                        if k != 'n' and isinstance(v, (int, float)):
                            tot[tid][aid][k] += v
        B[S], onT[S] = tot, on
    return B, onT


def returning(G, B, onT, onEarly=None):
    """qbRet, offRet, defRet, qbIn, offIn by (S, team). With onEarly (appearances in the first weeks only), "back"
    and "in" are read from those weeks alone, with no look ahead (the leak check)."""
    out = {}
    for S in G:
        if S - 1 not in B:
            continue
        prev, cur, nxt = B[S - 1], (onEarly or onT)[S], ({} if onEarly else onT.get(S + 1, {}))
        back = lambda aid, t: t in cur.get(aid, ()) or (not cur.get(aid) and t in nxt.get(aid, ()))
        seen2 = {a for Y in onT if Y < S - 2 for a in onT[Y]}
        has_def = sum(1 for P in prev.values() for s in P.values() if s.get('def_TOT')) > 1000
        for t in G[S]['fbs']:
            P = prev.get(t, {})
            pas = sum(s['pas_YDS'] for s in P.values() if 'pas_YDS' in s)
            off = sum(s.get('rus_YDS', 0) + s.get('rec_YDS', 0) for s in P.values())
            tk = sum(s.get('def_TOT', 0) for s in P.values())
            f = {'qbRet': sum(s.get('pas_YDS', 0) for a, s in P.items() if back(a, t)) / pas if pas > 0 else None,
                 'offRet': sum(s.get('rus_YDS', 0) + s.get('rec_YDS', 0) for a, s in P.items() if back(a, t)) / off if off > 0 else None,
                 'defRet': (sum(s.get('def_TOT', 0) for a, s in P.items() if back(a, t)) / tk) if has_def and tk > 0 else None}
            # development: the share of S-1 yards (all three kinds) that came back from players in their first or second
            # season with a stat line (ESPN boxes from 2014, so the count is clean from 2017 on)
            yds = lambda s: s.get('pas_YDS', 0) + s.get('rus_YDS', 0) + s.get('rec_YDS', 0)
            ally = sum(yds(s) for s in P.values())
            f['young'] = sum(yds(s) for a, s in P.items() if back(a, t) and a not in seen2) / ally if ally > 0 else None
            # transfers in: played for another FBS team in S-1 (and not for this one), plays for this one in S
            qi = oi = 0.0
            for aid, ts in cur.items():
                if t not in ts:
                    continue
                for u, Pu in prev.items():
                    if u == t or aid not in Pu or u not in G[S - 1]['fbs']:
                        continue
                    if aid in P:
                        continue
                    s = Pu[aid]
                    qi += s.get('pas_YDS', 0)
                    oi += s.get('rus_YDS', 0) + s.get('rec_YDS', 0)
            f['qbIn'] = min(1.5, qi / pas) if pas > 0 else 0.0
            f['offIn'] = min(1.5, oi / off) if off > 0 else 0.0
            out[(S, t)] = f
    return out


def talent(G):
    """247 composite by ESPN team id: tal (classes S-3..S) and fresh (class S), z across FBS each season."""
    import cfb_coach_fit as C
    idx = C.espn_teams()
    tid = lambda s: idx.get(C.ALIAS.get(C.norm(s), C.norm(s))) or idx.get(C.norm(s))
    cls = {}
    miss = Counter()
    for y in range(2011, 2027):
        p = os.path.join(R247, f'{y}.json')
        if not os.path.exists(p):
            continue
        by = defaultdict(list)
        for r in json.load(open(p)):
            if r['school']:
                t = tid(r['school'])
                if t:
                    by[t].append(r['comp'])
                else:
                    miss[r['school']] += 1
        cls[y] = {t: sum(max(0, c - 0.75) for c in sorted(v, reverse=True)[:20]) for t, v in by.items()}
    out = {}
    for S in G:
        fb = sorted(G[S]['fbs'])
        if not all(y in cls for y in range(S - 3, S + 1)):
            continue
        tal = np.array([sum(cls[y].get(t, 0) for y in range(S - 3, S + 1)) for t in fb])
        fr = np.array([cls[S].get(t, 0) for t in fb])
        for i, t in enumerate(fb):
            out[(S, t)] = {'tal': (tal[i] - tal.mean()) / tal.std(), 'fresh': (fr[i] - fr.mean()) / fr.std()}
    return out, miss


def coaches(G):
    hc = json.load(open(HC))
    # 2026: the coaching market's tenure (1 = first season), USA Today runs through 2025
    cur = {t['tid']: float(t['tenure'] <= 1) for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_coach_market.json')))['teams']}
    out = {}
    for S in G:
        for t in G[S]['fbs']:
            y = (hc.get(t) or {}).get('years', {})
            a, b = y.get(str(S - 1)), y.get(str(S))
            if S == 2026 and t in cur:
                out[(S, t)] = cur[t]
            elif a and b:
                out[(S, t)] = float(a[0] != b[0])
    return out


# ---- features, prior, walk -----------------------------------------------------------------------------
BASE = ['last']
CANDS = ['last2', 'qbRet', 'offRet', 'young', 'tal', 'fresh', 'hcNew', 'xRet', 'xHc', 'qbIn', 'offIn']
PORTAL = {'qbIn', 'offIn'}


def features(G, F, RET, TAL, HCN):
    X = {}
    for S in G:
        if S - 1 not in F:
            continue
        rets = [v for (s, t), v in RET.items() if s == S]
        mean_of = lambda k: np.mean([v[k] for v in rets if v[k] is not None]) if any(v[k] is not None for v in rets) else 0.0
        mu = {k: mean_of(k) for k in ('qbRet', 'offRet', 'defRet', 'young')}
        fcs1 = F[S - 1].get(FCS, -20)
        for t in G[S]['fbs']:
            r = RET.get((S, t), {})
            g = lambda k: r.get(k) if r.get(k) is not None else mu.get(k, 0.0)
            last = F[S - 1].get(t, fcs1)
            last2 = F.get(S - 2, {}).get(t, F.get(S - 2, {}).get(FCS, fcs1)) if S - 2 in F else last
            X[(S, t)] = {'last': last, 'last2': last2, 'qbRet': g('qbRet') - mu['qbRet'], 'offRet': g('offRet') - mu['offRet'],
                         'defRet': g('defRet') - mu['defRet'], 'young': g('young') - mu['young'], 'tal': TAL.get((S, t), {}).get('tal', -1.0),
                         'fresh': TAL.get((S, t), {}).get('fresh', -0.5), 'hcNew': HCN.get((S, t), 0.0),
                         'qbIn': r.get('qbIn', 0.0), 'offIn': r.get('offIn', 0.0)}
            x = X[(S, t)]
            x['xRet'] = last * (g('offRet') - mu['offRet'])
            x['xHc'] = last * x['hcNew']
    return X


def fit_prior(X, F, keys, seasons, ridge=1.0):
    """OLS (light ridge) of the season-end rating on [1, keys] over the given seasons."""
    ids = [(S, t) for (S, t) in X if S in seasons and t in F.get(S, {})]
    A = np.array([[1.0] + [X[i][k] for k in keys] for i in ids])
    y = np.array([F[i[0]][i[1]] for i in ids])
    L = np.eye(A.shape[1]) * ridge
    L[0, 0] = 0
    return np.linalg.solve(A.T @ A + L, A.T @ y)


def prior_of(X, w, keys, S, G, F):
    P = {t: float(np.dot(w, [1.0] + [X[(S, t)][k] for k in keys])) for t in G[S]['fbs'] if (S, t) in X}
    P[FCS] = F[S - 1].get(FCS, -20)
    return P


_SNAP = {}


def snapshots(G, S, hfa):
    """Cumulative normal equations of the margin rating before each game day of S (cached by season and hfa)."""
    key = (S, hfa)
    if key in _SNAP:
        return _SNAP[key]
    teams = sorted(G[S]['fbs']) + [FCS]
    idx = {t: i for i, t in enumerate(teams)}
    k = len(teams)
    A, b = np.zeros((k, k)), np.zeros(k)
    snaps, day = {}, None
    for r in G[S]['rows']:
        d = r['date'][:10]
        if d != day:
            snaps[d] = (A.copy(), b.copy())
            day = d
        i, j = idx[r['h']], idx[r['a']]
        y = max(-35, min(35, r['m'])) - (0 if r['n'] else hfa)
        A[i, i] += 1; A[j, j] += 1; A[i, j] -= 1; A[j, i] -= 1
        b[i] += y; b[j] -= y
    _SNAP[key] = (teams, idx, snaps)
    return _SNAP[key]


def walk(G, S, prior, lam, hfa):
    """Predicted home margin for every game of S from the games before its day (the ridge rating shrunk to prior)."""
    teams, idx, snaps = snapshots(G, S, hfa)
    p0 = np.array([prior.get(t, 0.0) for t in teams])
    R = {}
    for d, (A, b) in snaps.items():
        R[d] = np.linalg.solve(A + lam * np.eye(len(teams)), b + lam * p0)
    return [(r, R[r['date'][:10]][idx[r['h']]] - R[r['date'][:10]][idx[r['a']]] + (0 if r['n'] else hfa)) for r in G[S]['rows']]


def score(preds, sigma):
    m = np.array([p for _, p in preds])
    y = np.array([r['m'] for r, _ in preds])
    keep = y != 0
    pw = np.clip(phi(m / sigma), 1e-4, 1 - 1e-4)
    ll = np.where(y > 0, -np.log(pw), -np.log(1 - pw))
    return np.abs(y - m), np.where(keep, ll, np.nan)


def paired(a, b):
    d = (b - a)[~np.isnan(b - a)]
    return r4(d.mean()), r4(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


class Run:
    def __init__(self, G, F, X, lam=4.0, hfa=2.5, sigma=15.5):
        self.G, self.F, self.X, self.lam, self.hfa, self.sigma = G, F, X, lam, hfa, sigma

    def preds(self, keys, fit_seasons, seasons, weeks=None):
        w = fit_prior(self.X, self.F, keys, fit_seasons)
        out = []
        for S in seasons:
            P = prior_of(self.X, w, keys, S, self.G, self.F)
            out += [(r, p) for r, p in walk(self.G, S, P, self.lam, self.hfa) if weeks is None or r['w'] <= weeks]
        return out, w

    def metrics(self, keys, fit_seasons, seasons, weeks=None):
        pr, w = self.preds(keys, fit_seasons, seasons, weeks)
        ae, ll = score(pr, self.sigma)
        return ae, ll, w, pr


def main():
    G = load_games()
    F = finals(G)
    B, onT = boxes(G)
    RET = returning(G, B, onT)
    TAL, miss = talent(G)
    HCN = coaches(G)
    X = features(G, F, RET, TAL, HCN)
    print('team-seasons', len(X), 'ret', len(RET), 'tal', len(TAL), 'hc', len(HCN), '247 unmatched', miss.most_common(8), flush=True)
    res = {'seasons': {'tune': [TUNE[0], TUNE[-1]], 'hold': [HOLD[0], HOLD[-1]], 'portalTune': PTUNE, 'portalHold': PHOLD},
           'coverage': {str(S): {'teams': len(G[S]['fbs']), 'games': len(G[S]['rows']),
                                 'defRet': sum(1 for (s, t), v in RET.items() if s == S and v['defRet'] is not None),
                                 'hc': sum(1 for (s, t) in HCN if s == S), 'tal': sum(1 for (s, t) in TAL if s == S)} for S in G}}

    # hyperparameters on the base prior, tuning seasons (prior fit in sample there: it's the base for everyone)
    run = Run(G, F, X)
    best = None
    for lam in (2, 3, 4, 6, 8):
        for hfa in (2.0, 2.5, 3.0):
            run.lam, run.hfa = lam, hfa
            ae, ll, _, pr = run.metrics(BASE, TUNE, TUNE)
            if not best or ae.mean() < best[0]:
                best = (ae.mean(), lam, hfa, pr)
    run.lam, run.hfa = best[1], best[2]
    pr = best[3]
    m = np.array([p for _, p in pr]); y = np.array([r['m'] for r, _ in pr])
    run.sigma = float(np.sqrt(np.mean((y - m) ** 2)))
    res['hyper'] = {'lam': run.lam, 'hfa': run.hfa, 'sigma': r4(run.sigma)}
    print('hyper', res['hyper'], flush=True)

    # prior-only accuracy (season-end rating) and game accuracy, by variant
    def evaluate(keys, tune, hold, weeks=None):
        # tuning seasons: prior weights fit leave-one-season-out within the tuning set (out of sample for the prior)
        ae_t, ll_t = [], []
        for S in tune:
            a, l, _, _ = run.metrics(keys, [s for s in tune if s != S], [S], weeks)
            ae_t.append(a); ll_t.append(l)
        a_h, l_h, w, _ = run.metrics(keys, tune, hold, weeks)
        return np.concatenate(ae_t), np.concatenate(ll_t), a_h, l_h, w

    def select(base, cands, tune, hold, label):
        log = []
        keys, dropped = list(base), set()
        cur = evaluate(keys, tune, hold)
        while True:
            trial = []
            for c in cands:
                if c in keys or c in dropped:
                    continue
                ev = evaluate(keys + [c], tune, hold)
                dll, tll = paired(cur[1], ev[1])
                dae, tae = paired(cur[0], ev[0])
                hdll, htll = paired(cur[3], ev[3])
                hdae, htae = paired(cur[2], ev[2])
                wc = ev[4][-1]
                trial.append({'add': c, 'to': list(keys), 'tune': {'dLogLoss': dll, 't': tll, 'dMae': dae, 'tMae': tae},
                              'hold': {'dLogLoss': hdll, 't': htll, 'dMae': hdae, 'tMae': htae}, 'w': r4(wc), 'ev': ev})
            if not trial:
                break
            ok = [x for x in trial if x['tune']['t'] <= -1.5 and right_sign(x['add'], x['w'])]
            for x in trial:
                log.append({k: v for k, v in x.items() if k != 'ev'})
                print(label, 'try', x['add'], 'on', '+'.join(keys), 'tune', x['tune'], 'hold', x['hold'], 'w', x['w'], flush=True)
            ok = [x for x in ok if x['add'] not in dropped]
            if not ok:
                break
            pick = min(ok, key=lambda x: x['tune']['t'])
            if pick['hold']['dLogLoss'] > 0:          # passes tuning, worse held out: not kept, not retried
                dropped.add(pick['add'])
                log.append({'failedHoldOut': pick['add'], 'hold': pick['hold']})
                print(label, 'DROP (worse held out)', pick['add'], pick['hold'], flush=True)
                continue
            keys.append(pick['add'])
            cur = pick['ev']
            log.append({'kept': pick['add'], 'hold': pick['hold']})
            print(label, 'KEEP', pick['add'], 'held out', pick['hold'], flush=True)
        return keys, log

    sel, log = select(BASE, [c for c in CANDS if c not in PORTAL and c != 'young'], TUNE, HOLD, 'roster')
    res['roster'] = {'kept': sel, 'log': log}
    # development (young players back) on top, on the seasons where experience is counted cleanly
    ysel, ylog = select(sel, ['young'], YTUNE, HOLD, 'young')
    res['young'] = {'kept': ysel, 'log': ylog}
    # the portal on top, NIL-era seasons only
    psel, plog = select(ysel, sorted(PORTAL), PTUNE, PHOLD, 'portal')
    res['portal'] = {'kept': psel, 'log': plog}
    sel = psel

    # single-input report: each candidate on top of the base, the whole 2016-25 span (and weeks 1-4 only)
    single = {}
    for c in CANDS:
        tune, hold = (PTUNE, PHOLD) if c in PORTAL else (YTUNE, HOLD) if c == 'young' else (TUNE, HOLD)
        b = evaluate(BASE, tune, hold, 4)
        e = evaluate(BASE + [c], tune, hold, 4)
        single[c] = {'weeks1to4': {'tune': paired(b[1], e[1]), 'hold': paired(b[3], e[3]), 'holdMae': paired(b[2], e[2])}, 'w': r4(e[4][-1])}
    res['singleEarly'] = single

    # the kept prior's weights, fit on every season 2016-25, and its accuracy against the base prior and the close
    keys = sel
    w_all = fit_prior(X, F, keys, TUNE + HOLD[:-1])
    res['final'] = {'keys': ['1'] + keys, 'w': [r4(v) for v in w_all]}
    for name, ks in (('base', BASE), ('kept', keys)):
        a, l, w, pr = run.metrics(ks, TUNE, HOLD)
        cl = [(r, p) for r, p in pr if r['close'] is not None]
        res['final'][name] = {'holdMae': r4(a.mean()), 'holdLogLoss': r4(np.nanmean(l)), 'n': len(a),
                              'closeMae': r4(np.mean([abs(r['m'] - r['close']) for r, _ in cl])),
                              'modelMaeSameGames': r4(np.mean([abs(r['m'] - p) for r, p in cl]))}
    # how much the prior matters by week (held out, MAE base vs kept)
    a0, _, _, p0 = run.metrics(BASE, TUNE, HOLD)
    a1, _, _, p1 = run.metrics(keys, TUNE, HOLD)
    byw = defaultdict(lambda: [[], []])
    for (r, _), x0, x1 in zip(p0, a0, a1):
        wk = min(r['w'], 13)
        byw[wk][0].append(x0); byw[wk][1].append(x1)
    res['final']['holdMaeByWeek'] = {str(k): [r4(np.mean(v[0])), r4(np.mean(v[1])), len(v[0])] for k, v in sorted(byw.items())}
    # leak check: "back" and "transferred in" from appearances in weeks 1-2 only (no look ahead), scored on week 3 on,
    # against the full-season reading on the same games
    _, onE = boxes(G, early=2)
    XE = features(G, F, returning(G, B, onT, onE), TAL, HCN)
    lk = {}
    for name, XX in (('fullSeason', X), ('weeks1to2', XE)):
        rr = Run(G, F, XX, run.lam, run.hfa, run.sigma)
        b0 = rr.metrics(BASE + ['tal'], TUNE, HOLD)
        b1 = rr.metrics(keys, TUNE, HOLD)
        late = np.array([r['w'] >= 3 for r, _ in b0[3]])
        lk[name] = {'holdMaeWk3on': [r4(b0[0][late].mean()), r4(b1[0][late].mean())], 'gain': paired(b0[0][late], b1[0][late]),
                    'w': [r4(v) for v in b1[2]]}
    res['leakCheck'] = {'note': 'kept prior vs last + tal, held out, games from week 3 on', **lk}
    # the live prior's roster inputs (scripts/cfb_model.mjs PTS_ROSTER) for the last two seasons in the data: 247 class
    # talent (z), returning QB and skill yards (share, centred), transfers in (share)
    last = max(S for S in G if any(s == S for s, _ in X))
    res['feats'] = {str(S): {t: {'tal247': r4(X[(S, t)]['tal']), 'offRet': r4(X[(S, t)]['offRet']), 'qbRet': r4(X[(S, t)]['qbRet']),
                                 'offIn': r4(X[(S, t)]['offIn'])} for s, t in X if s == S} for S in (last - 1, last)}
    print('leak check', lk, flush=True)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res['final'], indent=1))


SIGN = {'young': 1, 'last2': 1, 'qbRet': 1, 'offRet': 1, 'defRet': 1, 'tal': 1, 'fresh': 1, 'hcNew': None, 'xRet': 1, 'xHc': -1, 'qbIn': 1, 'offIn': 1}


def right_sign(k, w):
    s = SIGN.get(k)
    return s is None or w * s > 0


if __name__ == '__main__':
    main()
