#!/usr/bin/env python3
"""CFP selection model: the committee's ranking fit as a rank-ordered (Plackett-Luce) logit, and the season sim's
playoff odds scored against the old hand-set formula.

    python3 scripts/rank_polls.py cfb 2014 2025 cfp   # the committee's releases -> scripts/data/polls/cfb.json
    python3 scripts/cfb_cfp.py                        # fit + backtest -> data/cfb_cfp.json (numpy; ~35 s)
scripts/cfb_model.mjs simulate() reads data/cfb_cfp.json (feats, beta) for the live season sim. Refit each January
after pulling that season's releases.

The committee model. Every CFP release (2017-25, six a season) ranks 25 teams. Plackett-Luce: the committee takes
the best team first with probability exp(s_i) / sum over every FBS team of exp(s_j), then the best of the rest, and
so on down to 25, with s = b . x. Sampling a ranking from it = sort s + Gumbel noise, which is how the season sim
(scripts/cfb_model.mjs) uses it. Inputs, as of each release (games before its date):
  L, W            losses and wins (FCS games count)
  rating          our game model's rating, read back from its walk-forward margins (scripts/data/games_wf: ridge on
                  team and home terms over the season's regular-season games up to a week after the release (each margin made
                  before its game), earlier games down-weighted exp(-days / 56), bowls
                  left out: their margins carry opt-out adjustments; the live sim
                  uses the rating itself)
  wab             strength of record: wins above a bubble team (the 12th-best rating) against the same schedule,
                  sum of (won - P(bubble team wins that game)) at the game's site, sd 15
  champ           conference champion (the last release only, after the title games)
  p4              power conference (Power Five through 2023, Power Four since; Notre Dame counts)
Fit on the 2017-21 releases, held out 2022-25. Candidate inputs are kept by the held-out log likelihood of the
last release of each season (the one that picks the field) and the log loss of P(in the field).

The field: the 12-team rule applied to every season (2017-23 counterfactually) -- the five best-ranked conference
champions plus the seven best-ranked others. The 2026 rule (Power Four champions in regardless of rank, the
best-ranked Group of Six champion, Notre Dame if top 12, seeds 1-12 straight from the ranking, top four bye) is the
live sim's; history can't separate the two because a Power Four champion has never ranked outside the field.

The old formula: resume = -6 x losses + 0.5 x strength + 3 x champion, deterministic. For a fair score it gets the
same Gumbel treatment with a temperature fit on 2017-21.

Season-sim backtest: from weeks 6, 9 and 12 of 2017-25, ratings read back at the checkpoint (games in the next three
weeks), every remaining regular-season game simulated as in the live sim (team shock 8 x sqrt(share left), game sd
from the walk-forward file), conference title games between the top two in conference record (ties: strength, the
same for both rules), then each selection rule. Scored: log loss of P(in the field) over every FBS team, against the
field the real final ranking gives. Tiebreakers checked separately on the real final standings."""
import gzip
import json
import math
import os
import re
from collections import defaultdict, Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cfb_cfp.json')
TUNE, HOLD = range(2017, 2022), range(2022, 2026)
P5 = {'SEC', 'Big Ten', 'ACC', 'Big 12', 'Pac-12'}
P4 = {'SEC', 'Big Ten', 'ACC', 'Big 12'}
ND = '87'
GSD = 15.0
SIMS = 3000
FEATS_ALL = ['L', 'W', 'rating', 'wab', 'champ', 'p4']


def pday(s):
    import datetime as dt
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ------------------------------------------------------------------------------------------------ data
def load():
    hist = json.load(gzip.open(os.path.join(HERE, 'data', 'cfb_hist_md.json.gz')))
    polls = json.load(open(os.path.join(HERE, 'data', 'polls', 'cfb.json')))
    wf = json.load(gzip.open(os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')))
    return hist, polls, wf


def is_ccg(g):
    return g['seasonType'] == 'regular' and g['week'] >= 13 and bool(g.get('notes')) and 'hampion' in g['notes'] \
        and g['homeClassification'] == 'fbs' and g['awayClassification'] == 'fbs'


def season_info(games, S):
    """FBS teams, conference by team, conference-title games, regular-season games (title games apart)"""
    fbs, conf = set(), {}
    for g in games:
        for side in ('home', 'away'):
            if g[f'{side}Classification'] == 'fbs':
                t = str(g[f'{side}Id']); fbs.add(t)
                if g[f'{side}Conference']:
                    conf.setdefault(t, Counter())[g[f'{side}Conference']] += 1
    conf = {t: c.most_common(1)[0][0] for t, c in conf.items()}
    ccg = [g for g in games if is_ccg(g) and g['completed']]
    reg = [g for g in games if g['seasonType'] == 'regular' and not is_ccg(g) and g['completed'] and g['homePoints'] is not None]
    return fbs, conf, ccg, reg


def power(t, conf, S):
    c = conf.get(t)
    return 1 if t == ND or c in (P4 if S >= 2024 else P5) else 0


def readback(rows, D=None, tau=56.0, lam=1.0):
    """ridge rating per team from model margins: m = r_h - r_a + h x (not neutral), games before D down-weighted by
    exp(-days before / tau) (the early non-conference games link the conferences; a short window can't)"""
    teams = sorted({r['h'] for r in rows} | {r['a'] for r in rows})
    ix = {t: i for i, t in enumerate(teams)}
    X = np.zeros((len(rows), len(teams) + 1)); y = np.zeros(len(rows)); w = np.ones(len(rows))
    for k, r in enumerate(rows):
        X[k, ix[r['h']]] = 1; X[k, ix[r['a']]] = -1; X[k, -1] = 0 if r['n'] else 1; y[k] = r['m']
        if D is not None:
            w[k] = math.exp(-max(0.0, (D - r['d']).total_seconds() / 86400) / tau)
    Xw = X * w[:, None]
    A = Xw.T @ X + lam * np.diag([1] * len(teams) + [0]); b = np.linalg.solve(A, Xw.T @ y)
    return {t: b[ix[t]] for t in teams}, b[-1]


def rating_at(wfr, S, D):
    """the game model's rating on the margin scale as of D: its walk-forward margins for the season's regular-season
    games up to a week past D (each made before its game, so nothing after D but the coming week's view)"""
    import datetime as dt
    return readback([r for r in wfr if r['S'] == S and r['wk'] < 20 and r['d'] < D + dt.timedelta(days=7)], D)


def wf_rows(wf, hist_by_id):
    out = []
    for r in wf:
        g = hist_by_id.get(str(r['id']))
        if not g or r['m'] is None:
            continue
        out.append({'S': r['S'], 'wk': r['wk'], 'd': pday(r['date']), 'h': str(g['homeId']), 'a': str(g['awayId']),
                    'n': bool(r['neutral']), 'm': r['m'], 'sigma': r['sigma']})
    return out


# ------------------------------------------------------------------------------------------------ features
def record(reg, ccg, upto=None):
    W, L, CW, CL, h2h = Counter(), Counter(), Counter(), Counter(), {}
    for g in reg + ccg:
        if upto and pday(g['startDate']) >= upto:
            continue
        h, a = str(g['homeId']), str(g['awayId'])
        hw = g['homePoints'] > g['awayPoints']
        W[h if hw else a] += 1; L[a if hw else h] += 1
        if g['conferenceGame'] and not is_ccg(g):
            CW[h if hw else a] += 1; CL[a if hw else h] += 1
            h2h[(h, a) if hw else (a, h)] = h2h.get((h, a) if hw else (a, h), 0) + 1
    return W, L, CW, CL, h2h


def champions(fbs, conf, ccg, CW, CL, rating, S):
    """conference champions: title game winners; no title game, the best conference record (ties: rating)"""
    ch = {}
    for g in ccg:
        c = g['homeConference']
        if c and c == g['awayConference']:
            ch[c] = str(g['homeId']) if g['homePoints'] > g['awayPoints'] else str(g['awayId'])
    by = defaultdict(list)
    for t in fbs:
        if conf.get(t) and 'Independent' not in conf[t]:
            by[conf[t]].append(t)
    for c, ts in by.items():
        if c not in ch and len(ts) >= 4:
            ch[c] = max(ts, key=lambda t: (CW[t] / max(1, CW[t] + CL[t]), rating.get(t, 0)))
    return set(ch.values())


def wab_of(games, rating, fbs, bub, fcs_r, upto=None):
    """wins above bubble: sum over games of (won - P(a team rated `bub` wins that game))"""
    out = Counter()
    for g in games:
        if upto and pday(g['startDate']) >= upto:
            continue
        h, a = str(g['homeId']), str(g['awayId'])
        hw = 1.0 if g['homePoints'] > g['awayPoints'] else 0.0
        hfa = 0 if g['neutralSite'] else 2.5
        for t, o, won, site in ((h, a, hw, hfa), (a, h, 1 - hw, -hfa)):
            if t not in fbs:
                continue
            ro = rating.get(o, fcs_r if o not in fbs else 0.0)
            out[t] += won - phi((bub - ro + site) / GSD)
    return out


def release_rows(S, rel, info, wfr, final):
    """feature matrix for one release: every FBS team"""
    fbs, conf, ccg, reg = info
    D = pday(rel['date'])
    import datetime as dt
    rat, _ = rating_at(wfr, S, D)
    fr = [v for t, v in rat.items() if t not in fbs]
    fcs_r = float(np.mean(fr)) if fr else -25.0
    W, L, CW, CL, _h = record(reg, ccg, D)
    srt = sorted((rat.get(t, 0.0) for t in fbs), reverse=True)
    bub = srt[11]
    wab = wab_of(reg + ccg, rat, fbs, bub, fcs_r, D)
    champs = champions(fbs, conf, ccg, CW, CL, rat, S) if final else set()
    teams = sorted(fbs)
    X = np.array([[L[t], W[t], rat.get(t, 0.0), wab[t], 1.0 if t in champs else 0.0, power(t, conf, S)] for t in teams])
    rk = {x['id']: x['rk'] for x in rel['ranks']}
    order = [teams.index(x['id']) for x in sorted(rel['ranks'], key=lambda x: x['rk']) if x['id'] in teams]
    return {'S': S, 'final': final, 'teams': teams, 'X': X, 'order': order, 'champs': champs, 'rk': rk, 'conf': conf}


# ------------------------------------------------------------------------------------------------ Plackett-Luce
def pl_nll(beta, rows, cols, w_final=1.0, ridge=0.01):
    """negative log likelihood, gradient and Hessian (each stage's covariance of x under its choice probabilities)"""
    k = len(cols); nll, grad, H = 0.0, np.zeros(k), 2 * ridge * np.eye(k)
    for r in rows:
        X = r['X'][:, cols]; s = X @ beta; wt = w_final if r['final'] else 1.0
        alive = np.ones(len(s), bool)
        for i in r['order']:
            Xa = X[alive]; m = s[alive].max(); e = np.exp(s[alive] - m); p = e / e.sum()
            mu = p @ Xa
            nll -= wt * (s[i] - m - math.log(e.sum()))
            grad -= wt * (X[i] - mu)
            H += wt * ((Xa * p[:, None]).T @ Xa - np.outer(mu, mu))
            alive[i] = False
    return nll + ridge * beta @ beta, grad + 2 * ridge * beta, H


def pl_fit(rows, cols, w_final=1.0):
    b = np.zeros(len(cols))
    for _ in range(50):
        f, g, H = pl_nll(b, rows, cols, w_final)
        step = np.linalg.solve(H, g); t = 1.0
        while pl_nll(b - t * step, rows, cols, w_final)[0] > f and t > 1e-4:
            t /= 2
        b = b - t * step
        if np.abs(t * step).max() < 1e-7:
            break
    return b


def pl_hess_se(beta, rows, cols, w_final=1.0):
    """standard errors from the information matrix, releases treated as independent (weekly releases of one season
    are not, so these run small)"""
    return np.sqrt(np.diag(np.linalg.inv(pl_nll(beta, rows, cols, w_final)[2])))


def field_from_scores(s, champs_mask, rng, n=SIMS, gumbel=True):
    """P(in the 12-team field) under the five-best-champions rule, s + Gumbel draws (or deterministic)"""
    T = len(s); cnt = np.zeros(T)
    reps = n if gumbel else 1
    for _ in range(reps):
        z = s + (rng.gumbel(size=T) if gumbel else 0)
        o = np.argsort(-z)
        cnt[pick12(o, champs_mask)] += 1
    return cnt / reps


def pick12(order, champs_mask):
    ch = [i for i in order if champs_mask[i]][:5]
    f = list(ch)
    for i in order:
        if len(f) >= 12:
            break
        if i not in ch:
            f.append(i)
    return f


def actual_field(r):
    order = r['order']; mask = np.array([t in r['champs'] for t in r['teams']])
    ranked = list(order) + [i for i in range(len(r['teams'])) if i not in order]
    return set(pick12(ranked, mask))


def ll(p, y, n=SIMS):
    p = np.clip(p, 0.5 / (n + 1), 1 - 0.5 / (n + 1))
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def final_pl_ll(beta, r, cols):
    s = r['X'][:, cols] @ beta; alive = np.ones(len(s), bool); out = 0.0
    for i in r['order']:
        m = s[alive].max(); out += s[i] - m - math.log(np.exp(s[alive] - m).sum()); alive[i] = False
    return out


def old_score(X):
    # -6 x losses + 0.5 x strength + 3 x champion (cfb_model.mjs before this change)
    return -6 * X[:, 0] + 0.5 * X[:, 2] + 3 * X[:, 4]


# ------------------------------------------------------------------------------------------------ main
def main():
    hist, polls, wf = load()
    games = {int(S): g for S, g in hist['games'].items()}
    by_id = {str(g['id']): g for S in games for g in games[S]}
    wfr = wf_rows(wf, by_id)
    info = {S: season_info(games[S], S) for S in games}
    rels = defaultdict(list)
    for r in polls['releases']:
        if r['poll'] == 'cfp' and r['S'] in games and r['S'] >= 2017:
            rels[r['S']].append(r)
    rows = []
    for S, rs in sorted(rels.items()):
        rs.sort(key=lambda r: r['date'])
        for k, rel in enumerate(rs):
            rows.append(release_rows(S, rel, info[S], wfr, k == len(rs) - 1))
    tune = [r for r in rows if r['S'] in TUNE]; hold = [r for r in rows if r['S'] in HOLD]
    fin_t = [r for r in tune if r['final']]; fin_h = [r for r in hold if r['final']]
    rng = np.random.default_rng(20261025)

    def field_ll(beta, cols, fins, temp=None):
        ps, ys = [], []
        for r in fins:
            s = r['X'][:, cols] @ beta if temp is None else old_score(r['X']) / temp
            mask = np.array([t in r['champs'] for t in r['teams']])
            p = field_from_scores(s, mask, rng, 2000)
            af = actual_field(r); y = np.array([1.0 if i in af else 0.0 for i in range(len(r['teams']))])
            ps.append(p); ys.append(y)
        return ll(np.concatenate(ps), np.concatenate(ys), 2000), np.concatenate(ps), np.concatenate(ys)

    # candidate sets, forward from L + rating
    cands = {}
    sets = [['L', 'rating'], ['L', 'W', 'rating'], ['L', 'rating', 'wab'], ['L', 'rating', 'champ'], ['L', 'rating', 'p4'],
            ['L', 'rating', 'wab', 'champ'], ['L', 'rating', 'wab', 'champ', 'p4'], ['L', 'W', 'rating', 'wab', 'champ', 'p4'],
            ['L', 'rating', 'champ', 'p4'], ['wab', 'rating', 'champ', 'p4'], ['L', 'wab', 'champ', 'p4']]
    for fs in sets:
        cols = [FEATS_ALL.index(f) for f in fs]
        for wfin in (1.0, 3.0):
            b = pl_fit(tune, cols, wfin)
            key = '+'.join(fs) + f' w{wfin:g}'
            cands[key] = {'feats': fs, 'w_final': wfin, 'beta': b.tolist(),
                          'tuneFinalLL': sum(final_pl_ll(b, r, cols) for r in fin_t) / len(fin_t),
                          'holdFinalLL': sum(final_pl_ll(b, r, cols) for r in fin_h) / len(fin_h),
                          'tuneField': field_ll(b, cols, fin_t)[0], 'holdField': field_ll(b, cols, fin_h)[0]}
            print(key, {k: round(v, 4) for k, v in cands[key].items() if isinstance(v, float)}, flush=True)
    # selection on the tuning seasons (final-release log likelihood), reported held out
    best = max(cands, key=lambda k: cands[k]['tuneFinalLL'])
    # old formula temperature on 2017-21
    temps = [0.5, 1, 1.5, 2, 3, 4, 6, 8]
    tl = {T: field_ll(None, None, fin_t, T)[0] for T in temps}
    T0 = min(tl, key=tl.get)
    old_hold = field_ll(None, None, fin_h, T0)
    old_det = field_ll(None, None, fin_h, 1e-6)
    B = cands[best]; cols = [FEATS_ALL.index(f) for f in B['feats']]; beta = np.array(B['beta'])
    new_hold = field_ll(beta, cols, fin_h)
    # paired t over teams on the held-out finals
    def team_losses(p, y):
        p = np.clip(p, 1 / 4000, 1 - 1 / 4000); return -(y * np.log(p) + (1 - y) * np.log(1 - p))
    d = team_losses(new_hold[1], new_hold[2]) - team_losses(old_hold[1], old_hold[2])
    t_sel = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    # refit on every season for live
    allrows = tune + hold
    beta_all = pl_fit(allrows, cols, B['w_final'])
    se = pl_hess_se(beta_all, allrows, cols, B['w_final'])
    # misses on held-out finals: the most likely team left out / the least likely team put in
    misses = []
    for r in fin_h:
        s = r['X'][:, cols] @ beta; mask = np.array([t in r['champs'] for t in r['teams']])
        p = field_from_scores(s, mask, rng, 2000); af = actual_field(r)
        for i in np.argsort(-p)[:16]:
            if (i in af) != (p[i] >= 0.5):
                misses.append({'S': r['S'], 'tid': r['teams'][i], 'p': round(float(p[i]), 3), 'in': i in af})
    sim = sim_backtest(games, info, wfr, rels, beta, cols, T0, fin_t + fin_h)
    tb = tiebreak_check(games, info, wfr)
    out = {
        'note': 'CFP committee model: Plackett-Luce on CFP releases 2017-25 (scripts/cfb_cfp.py)',
        'feats': B['feats'], 'w_final': B['w_final'], 'beta': [round(float(x), 4) for x in beta_all],
        'se': [round(float(x), 4) for x in se], 'betaTune': [round(float(x), 4) for x in beta],
        'gsd': GSD, 'candidates': {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != 'beta'} for k, v in cands.items()},
        'selection': {'heldFieldLL': round(new_hold[0], 4), 'oldHeldFieldLL': round(old_hold[0], 4), 'oldTemp': T0,
                      'oldDeterministicLL': round(old_det[0], 4), 't': round(t_sel, 2), 'teams': int(len(d))},
        'misses': misses, 'sim': sim, 'tiebreak': tb,
    }
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: out[k] for k in ('feats', 'beta', 'se', 'selection', 'sim', 'tiebreak')}, indent=1))


# ------------------------------------------------------------------------------------------------ tiebreakers
def standings_order(ts, CW, CL, h2h, rat, use_h2h):
    """top two by conference record; ties broken by head-to-head (round-robin record among the tied teams, only when
    each played every other) then rating"""
    pct = lambda t: CW[t] / max(1, CW[t] + CL[t])
    grp = defaultdict(list)
    for t in ts:
        grp[round(pct(t), 6)].append(t)
    out = []
    for p in sorted(grp, reverse=True):
        g = grp[p]
        if use_h2h and len(g) > 1:
            full = all(h2h.get((a, b), 0) + h2h.get((b, a), 0) > 0 for a in g for b in g if a < b)
            hw = {t: sum(h2h.get((t, o), 0) for o in g if o != t) for t in g} if full else {t: 0 for t in g}
            g = sorted(g, key=lambda t: (-hw[t], -rat.get(t, 0)))
        else:
            g = sorted(g, key=lambda t: -rat.get(t, 0))
        out += g
        if len(out) >= 2:
            break
    return out[:2]


def tiebreak_check(games, info, wfr):
    """on the real final standings, 2017-25: does head-to-head-then-rating pick the actual title game pair more often
    than rating alone, among the conferences with a tie for a spot"""
    res = {'ties': 0, 'h2h': 0, 'rating': 0}
    import datetime as dt
    for S in range(2017, 2026):
        fbs, conf, ccg, reg = info[S]
        W, L, CW, CL, h2h = record(reg, [])
        for g in ccg:
            c = g['homeConference']
            if not c or c != g['awayConference']:
                continue
            D = pday(g['startDate'])
            rat, _ = rating_at(wfr, S, D - dt.timedelta(days=7))
            ts = [t for t in fbs if conf.get(t) == c]
            pct = sorted({round(CW[t] / max(1, CW[t] + CL[t]), 6) for t in ts}, reverse=True)
            top = sorted(ts, key=lambda t: -CW[t] / max(1, CW[t] + CL[t]))
            if len(top) < 3:
                continue
            p2 = CW[top[1]] / max(1, CW[top[1]] + CL[top[1]]); p3 = CW[top[2]] / max(1, CW[top[2]] + CL[top[2]])
            if abs(p2 - p3) > 1e-9:
                continue
            real = {str(g['homeId']), str(g['awayId'])}
            res['ties'] += 1
            res['h2h'] += set(standings_order(ts, CW, CL, h2h, rat, True)) == real
            res['rating'] += set(standings_order(ts, CW, CL, h2h, rat, False)) == real
    return res


# ------------------------------------------------------------------------------------------------ season sims
def sim_backtest(games, info, wfr, rels, beta, cols, T0, finals):
    """from weeks 6, 9 and 12: P(in field) by the committee model vs the old formula, log loss vs the real field"""
    fin_by = {r['S']: r for r in finals}
    rng = np.random.default_rng(7)
    out = {}
    for wk in (6, 9, 12):
        rec = {'tune': {'new': [], 'old': [], 'y': []}, 'hold': {'new': [], 'old': [], 'y': []}}
        for S in range(2017, 2026):
            if S == 2020 or S not in fin_by:
                continue
            fbs, conf, ccg, reg = info[S]
            fr = fin_by[S]; teams = fr['teams']; ix = {t: i for i, t in enumerate(teams)}; T = len(teams)
            nxt = [r['d'] for r in wfr if r['S'] == S and r['wk'] == wk + 1]
            rat, hfa = rating_at(wfr, S, min(nxt))
            fcs_r = float(np.mean([v for t, v in rat.items() if t not in fbs] or [-25.0]))
            sig = float(np.mean([r['sigma'] for r in wfr if r['S'] == S]))
            done = [g for g in reg if g['week'] <= wk]; left = [g for g in reg if g['week'] > wk]
            r0 = np.array([rat.get(t, 0.0) for t in teams])
            nleft = Counter()
            for g in left:
                nleft[str(g['homeId'])] += 1; nleft[str(g['awayId'])] += 1
            tu = np.array([8 * math.sqrt(min(1, nleft[t] / 12)) for t in teams])
            N = 2000
            strn = r0[None, :] + rng.standard_normal((N, T)) * tu[None, :]
            Wm = np.zeros((N, T)); Lm = np.zeros((N, T)); CWm = np.zeros((N, T)); CLm = np.zeros((N, T))
            wab = np.zeros((N, T))
            # every game: home/away index (-1 = FCS), result per sim
            allg = done + left
            hi = np.array([ix.get(str(g['homeId']), -1) for g in allg]); ai = np.array([ix.get(str(g['awayId']), -1) for g in allg])
            neu = np.array([g['neutralSite'] for g in allg]); cg = np.array([bool(g['conferenceGame']) for g in allg])
            sh = np.where(hi[None, :] >= 0, strn[:, np.maximum(hi, 0)], fcs_r)
            sa = np.where(ai[None, :] >= 0, strn[:, np.maximum(ai, 0)], fcs_r)
            nd = len(done)
            hw = np.zeros((N, len(allg)))
            hw[:, :nd] = np.array([1.0 if g['homePoints'] > g['awayPoints'] else 0.0 for g in done])[None, :]
            mu = sh[:, nd:] - sa[:, nd:] + np.where(neu[nd:], 0, hfa)[None, :]
            hw[:, nd:] = (mu + rng.standard_normal(mu.shape) * sig > 0).astype(float)
            # h2h within conference for tiebreaks: kept per sim only for the top-two step below (dict of arrays)
            for j in range(len(allg)):
                h, a = hi[j], ai[j]
                if h >= 0:
                    Wm[:, h] += hw[:, j]; Lm[:, h] += 1 - hw[:, j]
                if a >= 0:
                    Wm[:, a] += 1 - hw[:, j]; Lm[:, a] += hw[:, j]
                if cg[j] and h >= 0 and a >= 0:
                    CWm[:, h] += hw[:, j]; CLm[:, h] += 1 - hw[:, j]; CWm[:, a] += 1 - hw[:, j]; CLm[:, a] += hw[:, j]
            bub = -np.sort(-strn, axis=1)[:, 11]
            for j in range(len(allg)):
                h, a = hi[j], ai[j]; site = 0 if neu[j] else 2.5
                if h >= 0:
                    wab[:, h] += hw[:, j] - 0.5 * (1 + erf_v((bub - sa[:, j] + site) / GSD / math.sqrt(2)))
                if a >= 0:
                    wab[:, a] += (1 - hw[:, j]) - 0.5 * (1 + erf_v((bub - sh[:, j] - site) / GSD / math.sqrt(2)))
            # conference title games (conferences that held one that season), top two by conference pct, ties strength
            champ = np.zeros((N, T))
            ccg_confs = {g['homeConference'] for g in ccg if g['homeConference'] == g['awayConference']}
            byc = defaultdict(list)
            for t in teams:
                if conf.get(t) and 'Independent' not in conf[t]:
                    byc[conf[t]].append(ix[t])
            for c, ts in byc.items():
                if len(ts) < 4:
                    continue
                ts = np.array(ts)
                key = CWm[:, ts] / np.maximum(1, CWm[:, ts] + CLm[:, ts]) * 1000 + strn[:, ts] / 100
                o = np.argsort(-key, axis=1)
                a1 = ts[o[:, 0]]; a2 = ts[o[:, 1]]
                if c in ccg_confs:
                    s1 = strn[np.arange(N), a1]; s2 = strn[np.arange(N), a2]
                    w1 = (s1 - s2 + rng.standard_normal(N) * sig) > 0
                    win = np.where(w1, a1, a2); lose = np.where(w1, a2, a1)
                    Wm[np.arange(N), win] += 1; Lm[np.arange(N), lose] += 1
                    wab[np.arange(N), win] += 1 - 0.5 * (1 + erf_v((bub - strn[np.arange(N), lose]) / GSD / math.sqrt(2)))
                    wab[np.arange(N), lose] += 0 - 0.5 * (1 + erf_v((bub - strn[np.arange(N), win]) / GSD / math.sqrt(2)))
                    champ[np.arange(N), win] = 1
                else:
                    champ[np.arange(N), a1] = 1
            p4 = np.array([power(t, conf, S) for t in teams], float)
            feats = {'L': Lm, 'W': Wm, 'rating': strn, 'wab': wab, 'champ': champ, 'p4': np.broadcast_to(p4, (N, T))}
            snew = sum(beta[k] * feats[FEATS_ALL[c]] for k, c in enumerate(cols))
            sold = (-6 * Lm + 0.5 * strn + 3 * champ)
            pn = np.zeros(T); po = np.zeros(T); pod = np.zeros(T)
            gum = rng.gumbel(size=(N, T))
            for n in range(N):
                m = champ[n].astype(bool)
                pn[pick12(np.argsort(-(snew[n] + gum[n])), m)] += 1
                pod[pick12(np.argsort(-sold[n]), m)] += 1
            pn /= N; pod /= N
            af = actual_field(fr); y = np.array([1.0 if i in af else 0.0 for i in range(T)])
            part = 'tune' if S in TUNE else 'hold'
            rec[part]['new'].append(pn); rec[part]['old'].append(pod); rec[part]['y'].append(y)
        res = {}
        for part, d in rec.items():
            if not d['y']:
                continue
            pn, po, y = np.concatenate(d['new']), np.concatenate(d['old']), np.concatenate(d['y'])
            cl = lambda p: np.clip(p, 1 / (N + 1), 1 - 1 / (N + 1))
            ln = -(y * np.log(cl(pn)) + (1 - y) * np.log(1 - cl(pn))); lo = -(y * np.log(cl(po)) + (1 - y) * np.log(1 - cl(po)))
            dd = ln - lo
            res[part] = {'new': round(float(ln.mean()), 4), 'old': round(float(lo.mean()), 4),
                         't': round(float(dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))), 2),
                         'brierNew': round(float(((pn - y) ** 2).mean()), 4), 'brierOld': round(float(((po - y) ** 2).mean()), 4),
                         'seasons': len(d['y'])}
        out[f'wk{wk}'] = res
        print('week', wk, res, flush=True)
    return out


_erf = np.vectorize(math.erf)


def erf_v(x):
    return _erf(x)


if __name__ == '__main__':
    main()
