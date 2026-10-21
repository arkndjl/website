#!/usr/bin/env python3
"""College basketball player projections for Predictions: each rotation player's points, rebounds and assists (and
PRA) in his team's next game, with a negative binomial spread (data/cbb_players.json), the model behind them
(data/cbb_players_fit.json), and whether they help the game model (data/cbb_players_research.json).

    python3 scripts/cbb_players.py --fit       # walk-forward backtest 2021-26 (tune 2021-23, held out 2024-26)
    python3 scripts/cbb_players.py --research  # the projected lineup against the game model's walk-forward misses
    python3 scripts/cbb_players.py             # the next slates (stdlib; runs in the cbb-board workflow in season)

Data: Barttorvik's player game logs (<season>_all_advgames.json.gz: minutes, points, rebounds, assists, possessions),
the same file the game model's injury term reads; Covers' injury report (scripts/cbb_games_live.py) live. The model is
the NBA one (scripts/nba_players.py) on a 200-minute game: role minutes (recent games played) and long minutes,
per-minute rates shrunk to the position's, the season average, the minutes teammates who sat their last games leave
behind (their chance to sit again by games missed in a row, cbb_games.SIT_STREAK; a Covers status when listed), pace,
the opponent's rates allowed, and the season's first games. College has no injury report history, so the backtest
reads availability from the logs alone (who sat the last games).
"""
import datetime as dt
import gzip
import json
import math
import os
import subprocess
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_players as NP  # noqa: E402

ROOT = os.path.dirname(HERE)
BTLOG = os.path.join(HERE, '.cache', 'cbb', 'games_bt')            # shared with cbb_games.py
FIT = os.path.join(ROOT, 'data', 'cbb_players_fit.json')
OUT = os.path.join(ROOT, 'data', 'cbb_players.json')
RESEARCH = os.path.join(ROOT, 'data', 'cbb_players_research.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
PSTATS = ('pts', 'reb', 'ast')
FEATS = ('base', 'long', 'savg', 'fill', 'pace', 'opp', 'home', 'eS', 'eB', 'eL')
GROUPS = {'early': ('eS', 'eB', 'eL')}
EARLY = 5.0
TUNE, HOLD = (2021, 2022, 2023), (2024, 2025, 2026)
SIT_STREAK = {0: 0.06, 1: 0.518, 2: 0.678, 3: 0.765, 4: 0.863}      # P(sits) by games missed in a row (0: measured below)


def logs(season):
    """[(date, team, opp, home, pid, name, min, pts, reb, ast, fg3, poss, bpm)] from Barttorvik's game logs"""
    p = os.path.join(BTLOG, f'{season}.json.gz')
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        os.makedirs(BTLOG, exist_ok=True)
        subprocess.run(['curl', '-s', '-m', '300', '-A', UA, f'https://barttorvik.com/{season}_all_advgames.json.gz', '-o', p], check=False)
    try:
        rows = json.load(gzip.open(p))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in rows:
        try:
            d = str(r[0])
            mn = float(r[8] or 0)
            if mn <= 0:
                continue
            out.append((f'{d[:4]}-{d[4:6]}-{d[6:8]}', r[47], r[5], r[46], r[51], r[48], mn, float(r[33] or 0),
                        float(r[34] or 0) + float(r[35] or 0), float(r[36] or 0), float(r[25] or 0), float(r[43] or 0),
                        float(r[44] or 0)))
        except (IndexError, TypeError, ValueError):
            continue
    return out


class Walk:
    """team rosters, role minutes, missed streaks and per-minute rates, in date order"""
    def __init__(self, hl=15.0, k0=60.0, carry=0.5, rhl=4.0, mhl=10.0, ohl=10.0):
        self.a, self.ra, self.ma, self.oa = (0.5 ** (1 / x) for x in (hl, rhl, mhl, ohl))
        self.k0, self.carry = k0, carry
        self.r = defaultdict(lambda: defaultdict(float))      # pid -> stat -> weighted total
        self.role = {}                                        # pid -> [weighted minutes, weight] (recent)
        self.mL = {}
        self.team = {}
        self.members = defaultdict(set)
        self.streak = defaultdict(int)
        self.lg = defaultdict(lambda: [0.0, 0.0])
        self.allow = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        self.pace = defaultdict(lambda: [0.0, 0.0])
        self.lgp = [68.0, 1.0]
        self.ngp = defaultdict(int)
        self.season = None
        self.seas = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])          # (S, pid) -> [gp, min, pts, reb, ast]
        self.names = {}

    def new_season(self, S):
        for d in self.r.values():
            for k in d:
                d[k] *= self.carry
        for d in (self.role, self.mL):
            for v in d.values():
                v[0] *= 0.5; v[1] *= 0.5
        for d in self.allow.values():
            for v in d.values():
                v[0] *= 0.3; v[1] *= 0.3
        for v in self.pace.values():
            v[0] *= 0.3; v[1] *= 0.3
        self.streak.clear(); self.ngp.clear()
        self.members.clear(); self.team.clear()         # rosters rebuild from this season's games (transfers, graduates)
        self.season = S

    def lgrate(self, s):
        v = self.lg[s]
        return v[0] / v[1] if v[1] else 0.0

    def rate(self, pid, s):
        d = self.r.get(pid)
        lr = self.lgrate(s)
        return lr if not d else (d[s] + self.k0 * lr) / (d['min'] + self.k0)

    def roster(self, t):
        return [p for p in self.members[t] if p in self.role]

    def rows(self, t, o, home, status=None, sit=None):
        """{pid: (P(plays), role minutes, feats by stat)} for team t before a game against o"""
        sit = sit or SIT_STREAK
        ros = []
        for p in self.roster(t):
            m, w = self.role[p]
            if w <= 0:
                continue
            ps = (status or {}).get(p)
            pr = 1 - (ps if ps is not None else sit[min(self.streak[p], 4)])
            ros.append((p, m / w, pr))
        if not ros:
            return {}
        A = sum(m * pr for _, m, pr in ros)
        fill = 200.0 / min(max(A, 120.0), 280.0) - 1.0
        L = self.lgp[0] / self.lgp[1]
        pr_ = lambda x: self.pace[x][0] / (self.pace[x][1] + 2.0)
        pace_rel = (pr_(t) + pr_(o)) / L
        out = {}
        for p, mS, pr in ros:
            v = self.mL.get(p)
            mL = v[0] / v[1] if v and v[1] else mS
            fx = {}
            for s in PSTATS:
                r = self.rate(p, s)
                b = mS * r
                al = self.allow[o][s]
                fx[s] = {'base': b, 'long': mL * r, 'fill': b * fill, 'pace': b * pace_rel,
                         'opp': b * al[0] / (al[1] + 3.0), 'home': b * home}
            fx['min'] = {'base': mS, 'long': mL, 'fill': mS * fill, 'pace': 0.0, 'opp': 0.0, 'home': mS * home}
            cur, prv = self.seas.get((self.season, p)), self.seas.get((self.season - 1, p))
            NP.add_savg(fx, cur, prv)
            out[p] = (pr, mS, fx)
        return out

    def update(self, t, o, rows):
        """one team's game: rows of logs()"""
        tot = sum(r[6] for r in rows)
        if tot < 150:
            return
        on = set()
        exp, got = defaultdict(float), defaultdict(float)
        for r in rows:
            pid, mn = r[4], r[6]
            on.add(pid)
            self.names[pid] = r[5]
            st = {'pts': r[7], 'reb': r[8], 'ast': r[9], 'fg3': r[10], 'bpm': r[12] * mn}
            for s in PSTATS:
                exp[s] += self.lgrate(s) * mn
                got[s] += st[s]
            d = self.r[pid]
            for s in st:
                d[s] = d[s] * self.a + st[s]
            d['min'] = d['min'] * self.a + mn
            for dd, k in ((self.role, self.ra), (self.mL, self.ma)):
                v = dd.setdefault(pid, [0.0, 0.0])
                v[0] = v[0] * k + mn; v[1] = v[1] * k + 1
            for s in PSTATS + ('fg3',):
                lv = self.lg[s]
                lv[0] = lv[0] * 0.9998 + st[s]; lv[1] = lv[1] * 0.9998 + mn
            old = self.team.get(pid)
            if old != t:
                if old:
                    self.members[old].discard(pid)
                self.team[pid] = t
                self.members[t].add(pid)
            self.streak[pid] = 0
            a = self.seas[(self.season, pid)]
            a[0] += 1; a[1] += mn; a[2] += r[7]; a[3] += r[8]; a[4] += r[9]
        for p in self.roster(t):
            if p not in on:
                self.streak[p] += 1
        for s in PSTATS:
            if exp[s] > 0:
                v = self.allow[o][s]
                v[0] = v[0] * self.oa + (got[s] / exp[s] - 1); v[1] = v[1] * self.oa + 1
        poss = max(r[11] for r in rows)
        if poss > 40:
            L = self.lgp[0] / self.lgp[1]
            v = self.pace[t]
            v[0] = v[0] * self.oa + (poss - L); v[1] = v[1] * self.oa + 1
            self.lgp[0] = self.lgp[0] * 0.999 + poss; self.lgp[1] = self.lgp[1] * 0.999 + 1
        self.ngp[t] += 1


def games_of(S):
    """{date: {(team, opp): [rows]}} for season S"""
    by = defaultdict(lambda: defaultdict(list))
    for r in logs(S):
        by[r[0]][(r[1], r[2])].append(r)
    return by


def walk(lo=2019, hi=2026, params=None, hook=None):
    """walk seasons lo..hi; hook(S, date, team, opp, home, rows_before, played_rows) on every team game"""
    W = Walk(**(params or {}))
    for S in range(lo, hi + 1):
        W.new_season(S)
        by = games_of(S)
        for d in sorted(by):
            day = by[d]
            if hook:
                for (t, o), rows in day.items():
                    home = {'H': 1.0, 'A': -1.0}.get(rows[0][3], 0.0)
                    hook(S, d, t, o, home, W.rows(t, o, home), rows, W)
            for (t, o), rows in day.items():
                W.update(t, o, rows)
    return W


def fit(write=True):
    import numpy as np
    D = []

    def hook(S, d, t, o, home, pre, rows, W):
        if S < min(TUNE):
            return
        played = {r[4]: r for r in rows}
        for p, (pr, mS, fx) in pre.items():
            r = played.get(p)
            cur = W.seas.get((S, p)); prv = W.seas.get((S - 1, p))
            ref = cur if cur and cur[0] >= 1 else (prv if prv and prv[0] >= 5 else None)
            if not r or not ref or mS < 10:
                continue
            D.append((S, fx, [r[6], r[7], r[8], r[9]], [ref[i] / ref[0] for i in (1, 2, 3, 4)], cur[0] if cur else 0))

    walk(hook=hook)
    S = np.array([x[0] for x in D])
    tune, hold = np.isin(S, TUNE), np.isin(S, HOLD)
    ks = ('min',) + PSTATS
    Y = {s: np.array([x[2][i] for x in D]) for i, s in enumerate(ks)}
    NV = {s: np.array([x[3][i] for x in D]) for i, s in enumerate(ks)}
    X = {s: {f: np.array([x[1][s][f] for x in D]) for f in FEATS} for s in ks}

    def wf(s, feats):
        A = np.column_stack([X[s][f] for f in feats])
        pred = np.full(len(S), np.nan)
        for yr in sorted(set(S)):
            tr, te = S < yr, S == yr
            if tr.sum() >= 5000:
                pred[te] = A[te] @ np.linalg.lstsq(A[tr], Y[s][tr], rcond=None)[0]
        return pred

    def pt(e1, e0):
        d = e1 - e0
        return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))

    rep = {'n': {'tune': int(tune.sum()), 'hold': int(hold.sum())}, 'stats': {}}
    preds = {}
    for s in ks:
        feats = ['base', 'long', 'savg']
        cur = wf(s, feats)
        ok = ~np.isnan(cur)
        log = []
        for f in [f for f in FEATS if not any(f in g for g in GROUPS.values())] + list(GROUPS):
            if f in feats or (s == 'min' and f in ('pace', 'opp')):
                continue
            add = list(GROUPS.get(f, (f,)))
            new = wf(s, feats + add)
            e0, e1 = (Y[s] - cur) ** 2, (Y[s] - new) ** 2
            tt, th = pt(e1[tune & ok], e0[tune & ok]), pt(e1[hold & ok], e0[hold & ok])
            keep = tt <= -1.5 and th <= 0
            log.append({'feat': f, 't_tune': round(tt, 2), 't_hold': round(th, 2), 'keep': keep})
            print(s, f, round(tt, 2), round(th, 2), keep, flush=True)
            if keep:
                feats += add; cur = new
        A = np.column_stack([X[s][f] for f in feats])
        coef = np.linalg.lstsq(A, Y[s], rcond=None)[0]
        preds[s] = cur
        rep['stats'][s] = {'feats': feats, 'coef': [round(float(c), 4) for c in coef], 'select': log}
    preds['pra'] = preds['pts'] + preds['reb'] + preds['ast']
    Y['pra'] = Y['pts'] + Y['reb'] + Y['ast']
    NV['pra'] = NV['pts'] + NV['reb'] + NV['ast']
    ok = ~np.isnan(preds['min'])
    for s in ks + ('pra',):
        acc = {}
        for nm, msk in (('tune', tune & ok), ('hold', hold & ok)):
            em, en = np.abs(Y[s][msk] - preds[s][msk]), np.abs(Y[s][msk] - NV[s][msk])
            acc[nm] = {'mae': round(float(em.mean()), 3), 'naive': round(float(en.mean()), 3), 't': round(pt(em, en), 1), 'n': int(msk.sum())}
        rep['stats'].setdefault(s, {})['acc'] = acc
        print(s, acc, flush=True)
    V, cal = {}, {}
    for s in PSTATS + ('pra',):
        msk = tune & ok & (preds[s] > 0)
        mu = preds[s][msk]
        ab = np.linalg.lstsq(np.column_stack([mu, mu * mu]), (Y[s][msk] - mu) ** 2, rcond=None)[0]
        V[s] = [float(ab[0]), float(ab[1])]
    for s in PSTATS + ('pra',):
        msk = hold & ok & (preds[s] > 0)
        mu, y, nv = preds[s][msk], Y[s][msk], NV[s][msk]
        line = np.floor(nv) + 0.5
        p = np.array([NP.nb_over(a, NP.var_of(V, s, a), L) for a, L in zip(mu, line)])
        o = (y > line).astype(float)
        bins = []
        for lo_, hi_ in ((0, .3), (.3, .4), (.4, .45), (.45, .5), (.5, .55), (.55, .6), (.6, .7), (.7, 1.01)):
            b = (p >= lo_) & (p < hi_)
            if b.sum() >= 50:
                bins.append({'p': round(float(p[b].mean()), 3), 'hit': round(float(o[b].mean()), 3), 'n': int(b.sum())})
        cal[s] = {'brier': round(float(((p - o) ** 2).mean()), 4), 'brier50': round(float(((0.5 - o) ** 2).mean()), 4), 'bins': bins}
        print(s, cal[s], flush=True)
    rep['calib'], rep['var'] = cal, {s: [round(x, 4) for x in v] for s, v in V.items()}
    if write:
        with open(FIT, 'w') as f:
            json.dump(rep, f, indent=1)
    return rep


def value(W, p, n0=150.0, rook=-3.0):
    """his BPM per minute played (minutes-weighted, recent), shrunk to a bench level with n0 minutes"""
    d = W.r.get(p)
    if not d:
        return rook
    return (d['bpm'] + n0 * rook) / (d['min'] + n0)


def research():
    """the projected lineup (minutes from the player model x P(plays), BPM value) minus the full-strength one, home minus
    away, against the game model's walk-forward misses (scripts/data/games_wf/cbb.json.gz, which already has its own
    injury term): a walk-forward slope on the miss, tuned 2016-20 is not possible (logs from 2019), so 2021-23 tune
    (fit on the seasons before each), 2024-26 held out"""
    import numpy as np
    F = json.load(open(FIT))
    cm = F['stats']['min']
    wfg = json.load(gzip.open(os.path.join(HERE, 'data', 'games_wf', 'cbb.json.gz')))
    key = {}
    for g in wfg:
        if g.get('res') is None or g.get('m') is None:
            continue
        key[(g['date'], g['home'], g['away'])] = g
    terms = {}

    def lineup(W, pre, full):
        tot, V = 0.0, 0.0
        for p, (pr, mS, fx) in pre.items():
            mm = max(0.0, sum(c * fx['min'][f] for c, f in zip(cm['coef'], cm['feats'])))
            e = mm * (1.0 if full else pr)
            tot += e
            V += value(W, p) * e
        sc = 200.0 / tot if tot > 200 else 1.0
        return V * sc / 40 + (-3.0 * (200 - tot) / 40 if tot < 200 else 0.0)

    def hook(S, d, t, o, home, pre, rows, W):
        if S < 2020 or not pre:
            return
        terms[(d, t, o)] = (lineup(W, pre, False) - lineup(W, pre, True), lineup(W, pre, False))

    walk(lo=2019, hi=2026, hook=hook)
    X, Y, SS = [], [], []
    for (d, h, a), g in key.items():
        th, ta = terms.get((d, h, a)), terms.get((d, a, h))
        if not th or not ta:
            continue
        X.append([th[0] - ta[0], th[1] - ta[1]]); Y.append(g['res'] - g['m']); SS.append(g['S'])
    X, Y, SS = np.array(X), np.array(Y), np.array(SS)
    res = {'n': len(Y)}
    for j, nm in enumerate(('plinDelta', 'plin')):
        pred = np.zeros(len(Y))
        for yr in sorted(set(SS)):
            tr, te = SS < yr, SS == yr
            if tr.sum() >= 2000:
                b = float(np.dot(X[tr, j], Y[tr]) / np.dot(X[tr, j], X[tr, j]))
                pred[te] = b * X[te, j]
        out = {}
        for lab, msk in (('tune', np.isin(SS, TUNE)), ('hold', np.isin(SS, HOLD))):
            e0, e1 = np.abs(Y[msk]), np.abs(Y[msk] - pred[msk])
            dd = e1 - e0
            out[lab] = {'mae0': round(float(e0.mean()), 4), 'mae1': round(float(e1.mean()), 4),
                        't': round(float(dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))), 2), 'n': int(msk.sum())}
        out['slope'] = round(float(np.dot(X[:, j], Y) / np.dot(X[:, j], X[:, j])), 3)
        out['keep'] = out['tune']['t'] <= -1.5 and out['hold']['mae1'] < out['hold']['mae0']
        res[nm] = out
        print(nm, out, flush=True)
    with open(RESEARCH, 'w') as f:
        json.dump(res, f, indent=1)


# ---------------------------------------------------------------- daily build
def project(F, fx):
    out = {}
    for s in ('min',) + PSTATS:
        st = F['stats'][s]
        out[s] = max(0.0, sum(c * fx[s][f] for c, f in zip(st['coef'], st['feats'])))
    out['pra'] = out['pts'] + out['reb'] + out['ast']
    sd = {s: round(math.sqrt(NP.var_of(F['var'], s, out[s])), 2) for s in PSTATS + ('pra',) if out[s] > 0}
    return out, sd


def build():
    import cbb_games_live as CL
    import names as NM
    F = json.load(open(FIT))
    S = CL.SEASON
    now = dt.datetime.now(dt.timezone.utc)
    res = {'season': S, 'asof': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'games': [], 'n': 0,
           'test': {s: F['stats'][s]['acc'] for s in ('min',) + PSTATS + ('pra',)},
           'calib': F['calib'], 'feats': {s: F['stats'][s]['feats'] for s in ('min',) + PSTATS}}
    W = walk(lo=S - 2, hi=S)
    if W.season != S:
        W.new_season(S)
    played = {t for t, n in W.ngp.items() if n > 0}            # this season's rosters exist once a team has played
    try:
        G = json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))
    except (OSError, ValueError):
        G = {}
    up = [g for g in G.get('games', []) if not g.get('final') and g.get('kick', '') > res['asof']]
    days = sorted({g['date'] for g in up})[:2]
    tkey = {NM.team_key(t): t for t in W.members}
    # Covers' report: listed players' chance to sit (cbb_games_live.SIT), by the shared name matcher on each roster
    listed = defaultdict(dict)
    names = {}
    if any(tkey.get(NM.team_key(g[s]['n'])) in played for g in up if g['date'] in days for s in ('home', 'away')):
        for team, name, pos, stt, detail, when in CL.covers_report():
            t = tkey.get(NM.team_key(team))
            sit = CL.SIT.get(stt.lower())
            if not t or sit is None:
                continue
            m = NM.Matcher([{'pid': p, 'name': W_name(W, p)} for p in W.members[t]], team=None, pos=None, sport='basketball')
            hit, _ = m.find(name)
            if hit:
                listed[t][hit['pid']] = (sit, stt)
    for g in up:
        if g['date'] not in days:
            continue
        h, a = tkey.get(NM.team_key(g['home']['n'])), tkey.get(NM.team_key(g['away']['n']))
        if h not in played or a not in played:
            continue
        players = []
        for t, o, home in ((h, a, 0.0 if g.get('neutral') else 1.0), (a, h, 0.0 if g.get('neutral') else -1.0)):
            st = {p: v[0] for p, v in listed.get(t, {}).items()}
            for p, (pr, mS, fx) in W.rows(t, o, home, status=st).items():
                mu, sd = project(F, fx)
                if mu['min'] < 8:
                    continue
                c = W.seas.get((S, p))
                players.append({'id': p, 'n': W_name(W, p), 't': t, 'st': (listed.get(t, {}).get(p) or (None, None))[1],
                                'pr': round(pr, 2), 'min': round(mu['min'], 1), **{s: round(mu[s], 1) for s in PSTATS + ('pra',)},
                                'sd': sd, 'gp': c[0] if c else 0,
                                'avg': None if not c else {s: round(c[i] / c[0], 1) for i, s in ((2, 'pts'), (3, 'reb'), (4, 'ast'))}})
        players.sort(key=lambda r: -r['pra'] * r['pr'])
        res['games'].append({'id': g['id'], 'tip': g['kick'], 'day': g['date'], 'h': h, 'a': a, 'players': players})
    res['n'] = sum(len(g['players']) for g in res['games'])
    with open(OUT, 'w') as f:
        json.dump(res, f, separators=(',', ':'))
    print('cbb players:', len(res['games']), 'games,', res['n'], 'players')


def W_name(W, p):
    return W.names.get(p, '')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--fit':
        fit()
    elif a and a[0] == '--research':
        research()
    else:
        build()
