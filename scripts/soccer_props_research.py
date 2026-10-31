#!/usr/bin/env python3
"""Soccer player props test (Oct 31 2026, Noah: "check for CBB, CFB, and soccer props"), on the NFL props method
(scripts/nfl_props_research.py): a walk-forward player model, a pre-registered rule tuned on one span and judged on a
later one, matches as clusters.

    python3 scripts/soccer_props_research.py      # -> data/soccer_props_research.json

Lines: DraftKings' opening prices through ESPN (scripts/soccer_props_archive.py), big five only (Understat has no MLS).
Markets: anytime goalscorer (ags), 2+ goals (g2), shots on target (sot), shots (sh), assists (ast) milestones and
goalkeeper saves (sav), each a price for yes at one rung. Graded on ESPN's box score; a player who doesn't appear is
void (DraftKings' rule), so every number is conditional on appearing.

Player model (Understat match pages 2023-24 on, every big-five league match before the day): per player decayed sums
over his appearances of minutes, xG, shots on target (Goal + SavedShot), shots, xA, assists; goalkeepers' saves (the
opponent's SavedShot while he played). A rate per 90 is shrunk toward his position group's mean by K90 matches of
minutes; expected minutes if he appears = his decayed mean minutes over appearances. The opponent's factor = its
decayed per-match xG (or shots on target) conceded over the league's mean, to the power B; home x HF. Counts are
Poisson (goals) or negative binomial (the rest, dispersion fitted on 2024-25). The model's knobs are fitted on the
2024-25 season's outcomes (no prop prices); then a logistic calibration on [logit model, logit DK implied] per market
is fitted on the tune span (matches before Jul 1 2026) and a bet is any calibrated edge at DK's price above EDGE
(tuned on the tune span). Held out: Aug 2026 on.

Result (Oct 31 2026; 680 matches, 27.8k graded props tune, 34.4k held): FAIL, nothing shipped.
  - At DraftKings' own prices no market wins held out (ags -2%, ast -7%, sot -29%, sh -36%, sav -35%; 15-79 bets
    each). DK's open is pre-line-up and yes-only, with a wide margin: implied .145 vs .107 hit for anytime goalscorer
    starters, .338 vs .233 for shots on target (q_scale .56-.60 on every market but saves).
  - The model adds information to DK's price (held-out Brier, market / model / blend: sh .1900/.1830/.1813, sot
    .1433/.1411/.1398, ags .0819/.0816/.0810), so a two-sided venue near fair would pay: priced at DK's fair chance
    plus half a hold h, held out sot +8% (h .05, t 3.5) and +10% (h .15, t 3.2), sh +10% at h .15 (t 5.2), ags +4%
    at h .15 (t 0.6). Shots isn't listed on Novig.
  - Novig's real asks (Oct 31, 2,900 player markets joined to DK): yes asks over DK's fair chance by a median .056
    on anytime goalscorer (h ~.11), .071 assists (h ~.14), .176 on 1+ shots on target (h ~.35); held out at those
    holds: ags +5.7% t 1.3, ast n 137 t 0.9, sot n 56 t 0.5. None reaches t 2. scripts/soccer_props_snap.py archives
    Novig's asks from Oct 31 so the test can be rerun at real asks (~300 graded per market)."""
import datetime as dt
import gzip
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names
import soccer_data as D
import soccer_games as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH = os.path.join(ROOT, 'scripts', 'data', 'props', 'soccer_dk_opens.json.gz')
OUT = os.path.join(ROOT, 'data', 'soccer_props_research.json')
SPLIT = '2026-07-01'
STATS = ('xg', 'sot', 'sh', 'xa', 'ast', 'g', 'sav', 'svf')
MK = {'ags': 'xg', 'g2': 'xg', 'sot': 'sot', 'sh': 'sh', 'ast': 'xa', 'sav': 'sav'}


def pgroup(pos):
    if not pos or pos == 'Sub':
        return None
    return 'G' if pos == 'GK' else 'D' if pos[0] == 'D' and not pos.startswith('DM') else 'F' if pos.startswith('FW') else 'M'


def understat(S0=2024, S1=None):
    """[(day, lg, home, away, {side: [player rows]}, {side: team stats})] for every finished big-five match"""
    S1 = S1 or D.current_season()
    out = []
    for S in range(S0, S1 + 1):
        for lg in D.BIG5:
            d = D.us_league(lg, S) or {}
            for m in d.get('matches', []):
                if not m['res']:
                    continue
                x = D.us_match(m['id'])
                if not x:
                    continue
                pl, tm = {}, {}
                for s in 'ha':
                    o = 'a' if s == 'h' else 'h'
                    shots = defaultdict(lambda: [0.0, 0, 0])
                    for mi, xg, pid, res, sit, _ in x['sh'][s]:
                        if res == 'OwnGoal':
                            continue
                        r = shots[pid]
                        r[0] += float(xg or 0)
                        r[1] += 1
                        r[2] += res in ('Goal', 'SavedShot')
                    # the opponent's saved shots by minute, for this side's goalkeepers
                    saved = [int(mi or 0) for mi, _, _, res, _, _ in x['sh'][o] if res == 'SavedShot']
                    rows = []
                    for p in x['ro'][s]:
                        t = int(p.get('time') or 0)
                        if t <= 0:
                            continue
                        sh = shots.get(p['player_id'], [0.0, 0, 0])
                        g = pgroup(p.get('position'))
                        sav = 0
                        if p.get('position') == 'GK':
                            sav = sum(1 for mi in saved if mi <= t + 5)
                        rows.append({'pid': p['player_id'], 'n': p['player'], 'pos': g, 'min': t, 'start': p.get('position') != 'Sub',
                                     'xg': sh[0], 'sh': sh[1], 'sot': sh[2], 'g': int(p.get('goals') or 0),
                                     'xa': float(p.get('xA') or 0), 'ast': int(p.get('assists') or 0), 'sav': sav,
                                     'gk': p.get('position') == 'GK'})
                    pl[s] = rows
                    tm[s] = {'xg': sum(float(v[1] or 0) for v in x['sh'][s] if v[3] != 'OwnGoal'),
                             'sot': sum(1 for v in x['sh'][s] if v[3] in ('Goal', 'SavedShot'))}
                out.append((m['t'][:10], lg, m['h'], m['a'], pl, tm))
    out.sort(key=lambda r: r[0])
    return out


class State:
    """walk-forward player and team sums; decay DP per appearance (players), DT per match (teams)"""

    def __init__(self, DP=0.93, DM=0.75, DT=0.9):
        self.DP, self.DM, self.DT = DP, DM, DT
        self.p = {}
        self.t = {}
        self.lg = defaultdict(lambda: [0.0, 0.0, 0.0])  # league: [xg, sot, matches] decayed
        self.pos = defaultdict(lambda: defaultdict(float))

    def add(self, row):
        day, lg, h, a, pl, tm = row
        for s, team, opp in (('h', h, a), ('a', a, h)):
            o = 'a' if s == 'h' else 'h'
            T = self.t.setdefault(team, {'xga': 0.0, 'sota': 0.0, 'xgf': 0.0, 'sotf': 0.0, 'n': 0.0})
            for k in T:
                T[k] *= self.DT
            T['xga'] += tm[o]['xg']
            T['sota'] += tm[o]['sot']
            T['xgf'] += tm[s]['xg']
            T['sotf'] += tm[s]['sot']
            T['n'] += 1
            L = self.lg[lg]
            L[0] = L[0] * 0.995 + tm[s]['xg']
            L[1] = L[1] * 0.995 + tm[s]['sot']
            L[2] = L[2] * 0.995 + 1
            for r in pl[s]:
                P = self.p.setdefault(r['pid'], {'m': 0.0, 'w': 0.0, 'mm': 0.0, 'mw': 0.0, 'pos': defaultdict(int),
                                                 'team': team, 'n': r['n'], 'apps': 0, 'last': day,
                                                 **{k: 0.0 for k in STATS}})
                for k in ('m', 'w') + STATS:
                    P[k] *= self.DP
                P['mm'] = P['mm'] * self.DM + r['min']
                P['mw'] = P['mw'] * self.DM + 1
                P['m'] += r['min']
                P['w'] += 1
                for k in ('xg', 'sot', 'sh', 'xa', 'ast', 'g'):
                    P[k] += r[k]
                if r['gk']:
                    P['sav'] += r['sav']
                    P['svf'] += tm[o]['sot'] * r['min'] / 90
                if r['pos']:
                    P['pos'][r['pos']] += 1
                P['team'], P['apps'], P['last'] = team, P['apps'] + 1, day
                g = max(P['pos'], key=P['pos'].get) if P['pos'] else 'M'
                for k in ('xg', 'sot', 'sh', 'xa', 'ast', 'g'):
                    self.pos[g][k] += r[k]
                self.pos[g]['m'] += r['min']
                if r['gk']:
                    self.pos['G']['sav'] += r['sav']
                    self.pos['G']['svf'] += tm[o]['sot'] * r['min'] / 90

    def group(self, pid):
        P = self.p[pid]
        return max(P['pos'], key=P['pos'].get) if P['pos'] else 'M'

    def lam(self, pid, opp, home, lg, K):
        """{market: expected count if he appears} and his minutes if he appears"""
        P = self.p.get(pid)
        if not P or P['apps'] < 3:
            return None
        g = self.group(pid)
        Q = self.pos[g]
        m90 = P['mm'] / P['mw'] / 90
        M90 = P['m'] / 90
        rate = {k: (P[k] + K['k90'] * 90 * Q[k] / max(Q['m'], 1) * 1) / (M90 + K['k90']) for k in ('xg', 'sot', 'sh', 'xa', 'ast', 'g')}
        L = self.lg[lg]
        T = self.t.get(opp)
        fx = fs = 1.0
        if T and T['n'] > 3 and L[2] > 20:
            fx = (T['xga'] / T['n']) / (L[0] / L[2])
            fs = (T['sota'] / T['n']) / (L[1] / L[2])
        hf = K['hf'] if home else 1 / K['hf']
        out = {'m90': m90, 'g': g}
        gl = (K['wx'] * rate['xg'] + (1 - K['wx']) * rate['g']) * m90 * fx ** K['b'] * hf
        out['xg'] = gl
        out['sot'] = rate['sot'] * m90 * fs ** K['b'] * hf
        out['sh'] = rate['sh'] * m90 * fs ** K['b'] * hf
        out['xa'] = (K['wa'] * rate['xa'] + (1 - K['wa']) * rate['ast']) * m90 * fx ** K['b'] * hf
        if g == 'G' and T and T['n'] > 3:
            # saves: the opponent's shots on target for, against his save share
            sr = (P['sav'] + K['k90'] * 0.7) / (P['svf'] + K['k90'])
            own = self.t.get(P['team'])
            fd = (own['sota'] / own['n']) / (L[1] / L[2]) if own and own['n'] > 3 else 1.0
            out['sav'] = sr * (T['sotf'] / T['n']) * fd ** K['b'] * m90 / hf
        return out


def nb_ge(lam, t, a):
    """P(X >= t) for a negative binomial with mean lam and var lam + a lam^2 (Poisson at a = 0)"""
    t = int(round(t))
    if t <= 0:
        return 1.0
    lam = max(lam, 1e-6)
    if a <= 1e-9:
        p, s = math.exp(-lam), 0.0
        for k in range(t):
            s += p
            p *= lam / (k + 1)
        return max(1e-9, 1 - s)
    r = 1 / a
    q = r / (r + lam)
    p, s = q ** r, 0.0
    for k in range(t):
        s += p
        p *= (k + r) / (k + 1) * (1 - q)
    return min(1 - 1e-9, max(1e-9, 1 - s))


def fit_model(US, K, lo='2024-07-01', hi='2025-07-01'):
    """log likelihood of every appearance's goals (Poisson), shots on target, shots, assists in the 2024-25 season"""
    st = State(K['dp'], K['dm'])
    ll = defaultdict(float)
    n = 0
    for row in US:
        day, lg, h, a, pl, tm = row
        if lo <= day < hi:
            for s, opp in (('h', a), ('a', h)):
                for r in pl[s]:
                    x = st.lam(r['pid'], opp, s == 'h', lg, K)
                    if not x:
                        continue
                    n += 1
                    for k, y, aa in (('xg', r['g'], 0), ('sot', r['sot'], K['asot']), ('sh', r['sh'], K['ash']),
                                     ('xa', r['ast'], 0)):
                        p1 = nb_ge(x[k], 1, aa)
                        ll[k] += math.log(p1 if y >= 1 else 1 - p1)
        elif day >= hi:
            break
        st.add(row)
    return n, dict(ll)


def logit(p):
    p = min(1 - 1e-6, max(1e-6, p))
    return math.log(p / (1 - p))


def logreg(X, y, l2=1.0, it=50):
    """Newton logistic regression, small ridge on all but the intercept"""
    d = len(X[0])
    w = [0.0] * d
    for _ in range(it):
        g = [0.0] * d
        H = [[0.0] * d for _ in range(d)]
        for x, t in zip(X, y):
            z = sum(a * b for a, b in zip(w, x))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            for i in range(d):
                g[i] += (p - t) * x[i]
                for j in range(d):
                    H[i][j] += p * (1 - p) * x[i] * x[j]
        for i in range(1, d):
            g[i] += l2 * w[i]
            H[i][i] += l2
        # solve H dw = g
        A = [H[i][:] + [g[i]] for i in range(d)]
        for i in range(d):
            piv = max(range(i, d), key=lambda r: abs(A[r][i]))
            A[i], A[piv] = A[piv], A[i]
            for r in range(d):
                if r != i and A[i][i]:
                    f = A[r][i] / A[i][i]
                    A[r] = [u - f * v for u, v in zip(A[r], A[i])]
        dw = [A[i][d] / A[i][i] for i in range(d)]
        w = [a - b for a, b in zip(w, dw)]
        if max(abs(v) for v in dw) < 1e-8:
            break
    return w


def link(arch, US):
    """ESPN match -> index into US (same league, day within 1, both team names alike)"""
    by = defaultdict(list)
    for i, r in enumerate(US):
        by[(r[1], r[0])].append(i)
    out = {}
    for g in arch:
        d0 = dt.date.fromisoformat(g['day'])
        best = None
        for dd in (0, -1, 1):
            for i in by.get((g['lg'], str(d0 + dt.timedelta(days=dd))), []):
                s = G.name_sim(g['h'], US[i][2]) + G.name_sim(g['a'], US[i][3])
                if s >= 1.0 and (not best or s > best[0]):
                    best = (s, i)
        if best:
            out[g['id']] = best[1]
    return out


def rows(K):
    """one row per DK prop on a linked big-five match: model P(yes | appears), DK implied, outcome (None = void)"""
    arch = [g for g in json.load(gzip.open(ARCH, 'rt')) if g['lg'] in D.BIG5]
    US = understat()
    lk = link(arch, US)
    need = defaultdict(list)
    for g in arch:
        if g['id'] in lk:
            need[lk[g['id']]].append(g)
    st = State(K['dp'], K['dm'])
    out = []
    unl = [0, 0]
    for i, row in enumerate(US):
        day, lg, h, a, pl, tm = row
        for g in need.get(i, []):
            # ESPN athlete -> Understat player in this match (same side, best name strength)
            side = {}
            for s, team in (('h', h), ('a', a)):
                for r in pl[s]:
                    side.setdefault(s, []).append(r)
            amap = {}
            for aid, ro in g['ro'].items():
                nm, tn = ro[0], ro[1]
                s = 'h' if G.name_sim(tn, g['h']) >= G.name_sim(tn, g['a']) else 'a'
                best = max(((names.strength(nm, r['n']), r) for r in side.get(s, [])), key=lambda z: z[0], default=(0, None))
                if best[0] >= 1:
                    amap[aid] = (s, best[1])
            for aid, mk, ot, odec, ct, cdec in g['p']:
                if not odec or odec <= 1:
                    continue
                ro = g['ro'].get(aid)
                if not ro:
                    continue
                appeared = ro[3]
                if aid not in amap:
                    unl[appeared] += 1
                    continue
                s, ur = amap[aid]
                x = st.lam(ur['pid'], a if s == 'h' else h, s == 'h', lg, K)
                if not x or mk not in MK or MK[mk] not in x:
                    continue
                t = 2 if mk == 'g2' else ot
                aa = {'sot': K['asot'], 'sh': K['ash']}.get(mk, 0.0)
                p = nb_ge(x[MK[mk]], t, aa)
                stat = {'ags': 4, 'g2': 4, 'sot': 5, 'sh': 6, 'ast': 7, 'sav': 8}[mk]
                y = None
                if appeared and ro[stat] is not None:
                    y = int(ro[stat] >= t)
                out.append({'id': g['id'], 'day': g['day'], 'lg': lg, 'mk': mk, 't': t, 'dec': odec, 'q': 1 / odec,
                            'p': p, 'y': y, 'm90': x['m90'], 'g': x['g'], 'n': ro[0]})
        st.add(row)
    print('linked matches', len(lk), 'of', len(arch), '; props without an Understat player (void, played):', unl, flush=True)
    return out


def cl_t_fast(v, keys):
    by, cnt = defaultdict(float), defaultdict(int)
    for x, k in zip(v, keys):
        by[k] += x
        cnt[k] += 1
    n = len(v)
    if n < 2:
        return 0.0
    mu = sum(v) / n
    s2 = sum((by[k] - mu * cnt[k]) ** 2 for k in by)
    return mu / (math.sqrt(s2) / n) if s2 > 0 else 0.0


def feats(r):
    return [1.0, logit(r['p']), logit(r['q'])]


def evaluate(R, W, edge, mks):
    """bets on rows R at calibrated edge > edge: n, hit, roi a unit, t (matches as clusters), Kelly log growth"""
    v, keys, hit, lg = [], [], 0, 0.0
    for r in R:
        if r['mk'] not in mks or r['y'] is None or r['mk'] not in W:
            continue
        w = W[r['mk']]
        c = 1 / (1 + math.exp(-sum(a * b for a, b in zip(w, feats(r)))))
        e = c * r['dec'] - 1
        if e <= edge:
            continue
        ret = r['dec'] - 1 if r['y'] else -1.0
        v.append(ret)
        keys.append(r['id'])
        hit += r['y']
        f = min(0.01, e / (r['dec'] - 1))
        lg += math.log(1 + f * ret)
    n = len(v)
    return {'n': n, 'hit': round(hit / n, 3) if n else None, 'roi': round(sum(v) / n, 4) if n else None,
            't': round(cl_t_fast(v, keys), 2), 'log': round(lg, 4), 'matches': len(set(keys))}


def sig(z):
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def at_hold(R, W, M, h, mk, edge=0.0):
    """Novig-like prices: the market's fair chance (a logistic on DK's implied alone, fitted on the tune span) plus half
    the two-sided hold h on the side taken; bet yes or no when the calibrated chance beats that ask by edge. Novig has
    no prop history, so this is the only way to price a two-sided venue here."""
    v, keys, lg = [], [], 0.0
    for r in R:
        if r['mk'] != mk or r['y'] is None:
            continue
        c = sig(sum(a * b for a, b in zip(W[mk], feats(r))))
        f = sig(M[mk][0] + M[mk][1] * logit(r['q']))
        for side, pc, ask in (('y', c, f + h / 2), ('n', 1 - c, 1 - f + h / 2)):
            if ask >= 1 or pc - ask <= edge:
                continue
            win = r['y'] if side == 'y' else 1 - r['y']
            ret = (1 - ask) / ask if win else -1.0
            v.append(ret)
            keys.append(r['id'])
            fk = min(0.01, (pc - ask) / (1 - ask))
            lg += math.log(1 + fk * ret)
    n = len(v)
    return {'n': n, 'roi': round(sum(v) / n, 4) if n else None, 't': round(cl_t_fast(v, keys), 2), 'log': round(lg, 4)}


def main():
    K = {'dp': 0.95, 'dm': 0.8, 'k90': 6.0, 'b': 0.7, 'hf': 1.06, 'wx': 0.8, 'wa': 0.7, 'asot': 0.15, 'ash': 0.1}
    US = understat(2024)
    # 1. the model's knobs on 2024-25 outcomes (coordinate search on each market's own likelihood)
    grid = {'dp': [0.9, 0.95, 0.98], 'dm': [0.6, 0.8, 0.9], 'k90': [3.0, 6.0, 12.0], 'b': [0.0, 0.5, 1.0],
            'hf': [1.0, 1.06, 1.12], 'wx': [0.5, 0.8, 1.0], 'wa': [0.4, 0.7, 1.0], 'asot': [0.0, 0.15, 0.3],
            'ash': [0.0, 0.1, 0.25]}
    tot = lambda ll: sum(ll.values())
    base = fit_model(US, K)
    print('start', base, flush=True)
    for _ in range(2):
        for k, vals in grid.items():
            best = None
            for v in vals:
                n, ll = fit_model(US, {**K, k: v})
                if not best or tot(ll) > best[0]:
                    best = (tot(ll), v)
            K[k] = best[1]
            print(k, K[k], round(best[0], 1), flush=True)
    n, ll = fit_model(US, K)
    # 2. props: calibration + edge on the tune span, judged held out
    R = rows(K)
    tune = [r for r in R if r['day'] < SPLIT and r['y'] is not None]
    held = [r for r in R if r['day'] >= SPLIT and r['y'] is not None]
    W = {}
    cal = {}
    for mk in MK:
        T = [r for r in tune if r['mk'] == mk]
        if len(T) < 200:
            continue
        W[mk] = logreg([feats(r) for r in T], [r['y'] for r in T])
        H = [r for r in held if r['mk'] == mk]
        # Brier: market (implied with its margin removed by the tune-span mean) vs model vs calibrated
        mq = sum(r['y'] for r in T) / sum(r['q'] for r in T)
        cal[mk] = {'tune_n': len(T), 'held_n': len(H), 'w': [round(x, 3) for x in W[mk]], 'q_scale': round(mq, 3),
                   'brier_mkt': round(sum((min(1, r['q'] * mq) - r['y']) ** 2 for r in H) / max(len(H), 1), 5),
                   'brier_model': round(sum((r['p'] - r['y']) ** 2 for r in H) / max(len(H), 1), 5),
                   'brier_cal': round(sum((1 / (1 + math.exp(-sum(a * b for a, b in zip(W[mk], feats(r))))) - r['y']) ** 2
                                          for r in H) / max(len(H), 1), 5)}
    res = {}
    for mk in W:
        rt = {e: evaluate(tune, W, e, {mk}) for e in (0.0, 0.03, 0.06, 0.1, 0.15)}
        ok = [e for e in rt if rt[e]['n'] >= 30]
        e = max(ok, key=lambda e: rt[e]['log']) if ok else 0.0
        res[mk] = {'edge': e, 'tune': rt[e], 'held': evaluate(held, W, e, {mk}),
                   'held_all_edges': {str(x): evaluate(held, W, x, {mk}) for x in rt}}
    M = {mk: logreg([[1.0, logit(r['q'])] for r in tune if r['mk'] == mk], [r['y'] for r in tune if r['mk'] == mk])
         for mk in W}
    hyp = {mk: {str(h): {'tune': at_hold(tune, W, M, h, mk), 'held': at_hold(held, W, M, h, mk)}
                for h in (0.02, 0.05, 0.10, 0.15)} for mk in W}
    for mk, v in hyp.items():
        for h, x in v.items():
            print('hyp', mk, h, x)
    out = {'asof': dt.date.today().isoformat(), 'K': K, 'hypothetical_two_sided': hyp, 'model_ll_2425': {k: round(v, 1) for k, v in ll.items()},
           'appearances_2425': n, 'props': len(R), 'graded': len(tune) + len(held), 'tune_graded': len(tune),
           'held_graded': len(held), 'split': SPLIT, 'calibration': cal, 'markets': res}
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: out[k] for k in ('props', 'tune_graded', 'held_graded')}))
    for mk, v in res.items():
        print(mk, 'edge', v['edge'], 'tune', v['tune'], 'held', v['held'])
    print(json.dumps(cal, indent=0))


if __name__ == '__main__':
    main()
