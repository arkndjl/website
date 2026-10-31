#!/usr/bin/env python3
"""NHL player props (Oct 31 2026, Noah: "NBA/NHL player props in the same way we did NFL ones"): a per-game projection
of each skater's shots on goal, goals, assists, points, blocked shots and hits and each goalie's saves, and the paper
test of it against the books' archived prop lines and prices.

    python3 scripts/nhl_pbox.py                 # ESPN box scores 2021-22 on (ESPN ids, as the props carry)
    python3 scripts/props_archive.py nhl        # the prop opens and closes: ESPN BET Mar 2024 on, DraftKings after
    python3 scripts/nhl_props.py --test         # -> data/nhl_props_research.json, data/nhl_props_fit.json (numpy)
    python3 scripts/nhl_props.py                # today's goalies' projected saves -> data/nhl_props.json (stdlib; NHL build)

Result (Oct 31 2026): fails. Held out at the book's prices every stat but hits and saves loses (all props -2.6%, t -6;
41k bets); hits won but no free source prices them live; saves won on the 2024 tune props and at the close held out,
not at the open (t 1.3). Noah picked a paper test of saves (scripts/props_daily.py nhl -> data/props_paper_nhl.json),
off the picks tab. ESPN BET lists some 2024-25 pairs under first: scripts/props_archive.py reads its over/under marks.

Projection, walked game by game in start order (nothing from the game itself or later):
    toi     ice time: a 6-game half-life average of his minutes, next to a 30-game one (long)
    rate    each stat a minute: a 25-game half-life total over his minutes, shrunk to his position's league rate with
            k0 minutes (goalies: shots against a game, the team's, and his save rate shrunk to the league's)
    base    toi x rate; savg his season average to date (last season's before his 3rd game); opp = base x the
            opponent's allowance of the stat over the league's; imp = base x his team's market goals over the league's
            (from the moneyline and total, open), fav = base x (win chance - .5)
    each season's coefficients fit on the seasons before it (least squares, no intercept)
P(over): negative binomial with variance a mu + b mu^2 and the logistic shape correction (scripts/props_model.py),
fit on 2023 (the first season with a walked projection; no props). Points = goals + assists.

Rule and pass bar as NBA's (scripts/nba_props_research.py): one bet a player a game, the side with the highest P if
P >= p*, p* picked on the 2024 props (Mar-Jun 2024), scored on 2025-27 at the book's prices, games as clusters.
"""
import datetime
import gzip
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

OUT = os.path.join(ROOT, 'data', 'nhl_props_research.json')
FIT = os.path.join(ROOT, 'data', 'nhl_props_fit.json')
OPENS = os.path.join(HERE, 'data', 'props', 'nhl_opens.json.gz')
SK = ('g', 'a', 'sog', 'blk', 'hit')
IX = {'toi': 3, 'pp': 4, 'g': 5, 'a': 6, 'sog': 7, 'blk': 8, 'hit': 9}
COMBO = {'sog': ('sog',), 'g': ('g',), 'ast': ('a',), 'pts': ('g', 'a'), 'blk': ('blk',), 'hit': ('hit',),
         'sv': ('sv',)}
FEATS = ('base', 'long', 'savg', 'opp', 'imp', 'fav')
SHAPE, TUNE, HELD = (2023,), (2024,), (2025, 2026, 2027)
BUDGET = 25.0                                      # % of bankroll a day's saves bets share at most (paper)
LIVE = os.path.join(ROOT, 'data', 'nhl_props.json')
SITE = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl'
LG_GOALS = 3.05                                    # goals a team a game, 2021-26, for the market's implied goals


class Walk:
    def __init__(self, hl=25.0, thl=6.0, lhl=30.0, k0=120.0, carry=0.7, ohl=20.0):
        self.a, self.ta, self.la, self.oa = (0.5 ** (1 / h) for h in (hl, thl, lhl, ohl))
        self.k0, self.carry = k0, carry
        self.r = defaultdict(lambda: defaultdict(float))     # pid -> stat -> decayed total, 'toi'
        self.t = {}                                         # pid -> [toi, w] short; long
        self.tl = {}
        self.pos = {}
        self.lg = defaultdict(lambda: [0.0, 0.0])           # (pos, stat) -> [stat, minutes]
        self.allow = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))   # team -> stat -> [allowed / league exp, w]
        self.tsa = defaultdict(lambda: [0.0, 0.0])           # team -> shots against a game (decayed)
        self.tsf = defaultdict(lambda: [0.0, 0.0])
        self.lsa = [0.0, 0.0]
        self.gs = defaultdict(lambda: [0.0, 0.0])            # goalie -> [saves, shots] decayed
        self.lsv = [0.0, 0.0]
        self.season = None
        self.seas = defaultdict(lambda: defaultdict(lambda: [0] + [0.0] * 7))   # S -> pid -> [gp, toi, g, a, sog, blk, hit, sv]

    def new_season(self, S):
        for d in self.r.values():
            for k in d:
                d[k] *= self.carry
        for d in (self.t, self.tl):
            for v in d.values():
                v[0] *= .3; v[1] *= .3
        for d in self.allow.values():
            for v in d.values():
                v[0] *= .3; v[1] *= .3
        for d in (self.tsa, self.tsf, self.gs):
            for v in d.values():
                v[0] *= .3; v[1] *= .3
        self.season = S

    def lgrate(self, pos, s):
        v = self.lg[(pos, s)]
        return v[0] / v[1] if v[1] else 0.0

    def rate(self, pid, s):
        d = self.r.get(pid)
        lr = self.lgrate(self.pos.get(pid, 'F'), s)
        if not d:
            return lr
        return (d[s] + self.k0 * lr) / (d['toi'] + self.k0)

    def toi(self, pid, long=False):
        v = (self.tl if long else self.t).get(pid)
        return v[0] / v[1] if v and v[1] else None

    def opp(self, t, s):
        v = self.allow[t][s]
        return v[0] / (v[1] + 3.0)

    def lg_sa(self):
        return self.lsa[0] / self.lsa[1] if self.lsa[1] else 30.0

    def team_sa(self, t):
        v = self.tsa[t]
        return (v[0] + 5 * self.lg_sa()) / (v[1] + 5)

    def team_sf(self, t):
        v = self.tsf[t]
        return (v[0] + 5 * self.lg_sa()) / (v[1] + 5)

    def sv_rate(self, gid_):
        lg = self.lsv[0] / self.lsv[1] if self.lsv[1] else .905
        v = self.gs.get(gid_, [0.0, 0.0])
        return (v[0] + 600 * lg) / (v[1] + 600)

    def savg(self, S, pid, i, base):
        cur, prv = self.seas[S].get(pid), self.seas[S - 1].get(pid)
        if cur and cur[0] >= 3:
            return cur[i] / cur[0]
        if prv and prv[0] >= 10:
            return prv[i] / prv[0]
        return base

    def market(self, b, t):
        """(team's market goals over the league's, win chance - .5) from the open moneyline and total, or zeros"""
        ml, tot = b.get('ml'), b.get('ou')
        if not ml or not tot or None in ml:
            return 0.0, 0.0

        def imp(a):
            a = float(a)
            return 100 / (a + 100) if a > 0 else -a / (-a + 100)
        ph = imp(ml[0]) / (imp(ml[0]) + imp(ml[1]))
        p = ph if t == b['h'] else 1 - ph
        # goals split by win chance: a 60% favourite takes ~54% of the total
        g = float(tot) * (0.5 + 0.4 * (p - 0.5))
        return g / LG_GOALS - 1.0, p - 0.5

    def rows(self, b):
        """(team, pid, stat feats, kind) for every skater and goalie in the box, before the game"""
        out = []
        S = b['S']
        for t, o in ((b['h'], b['a']), (b['a'], b['h'])):
            imp, fav = self.market(b, t)
            for r in b['p'].get(t, []):
                pid = r[0]
                self.pos.setdefault(pid, r[2])
                ts, tl = self.toi(pid), self.toi(pid, True)
                ts = ts if ts is not None else (15.5 if r[2] == 'F' else 19.5) * 0.85
                tl = tl if tl is not None else ts
                fx = {}
                for s in SK:
                    rt = self.rate(pid, s)
                    base = ts * rt
                    fx[s] = {'base': base, 'long': tl * rt, 'savg': self.savg(S, pid, 2 + SK.index(s), base),
                             'opp': base * self.opp(o, s), 'imp': base * imp, 'fav': base * fav}
                out.append((t, pid, fx, 'sk'))
            for r in b['gk'].get(t, []):
                pid = r[0]
                shots = self.team_sa(t) * self.team_sf(o) / self.lg_sa()
                base = shots * self.sv_rate(pid)
                fx = {'sv': {'base': base, 'long': self.team_sa(t) * self.sv_rate(pid), 'savg': self.savg(S, pid, 7, base),
                             'opp': base * (self.team_sf(o) / self.lg_sa() - 1), 'imp': base * imp, 'fav': base * fav}}
                out.append((t, pid, fx, 'gk'))
        return out

    def update(self, b):
        S = b['S']
        for t, o in ((b['h'], b['a']), (b['a'], b['h'])):
            exp, got = defaultdict(float), defaultdict(float)
            for r in b['p'].get(t, []):
                pid, mn = r[0], r[3]
                pos = r[2]
                self.pos[pid] = pos
                d = self.r[pid]
                for s in SK:
                    exp[s] += self.lgrate(pos, s) * mn
                    got[s] += r[IX[s]]
                    d[s] = d[s] * self.a + r[IX[s]]
                    lv = self.lg[(pos, s)]
                    lv[0] = lv[0] * .9998 + r[IX[s]]; lv[1] = lv[1] * .9998 + mn
                d['toi'] = d['toi'] * self.a + mn
                for D_, a_ in ((self.t, self.ta), (self.tl, self.la)):
                    v = D_.setdefault(pid, [0.0, 0.0])
                    v[0] = v[0] * a_ + mn; v[1] = v[1] * a_ + 1
                c = self.seas[S][pid]
                c[0] += 1; c[1] += mn
                for j, s in enumerate(SK):
                    c[2 + j] += r[IX[s]]
            for s in SK:
                if exp[s] > 0:
                    v = self.allow[o][s]
                    v[0] = v[0] * self.oa + (got[s] / exp[s] - 1); v[1] = v[1] * self.oa + 1
            sf = got['sog']
            v = self.tsf[t]; v[0] = v[0] * self.oa + sf; v[1] = v[1] * self.oa + 1
            v = self.tsa[o]; v[0] = v[0] * self.oa + sf; v[1] = v[1] * self.oa + 1
            self.lsa[0] = self.lsa[0] * .999 + sf; self.lsa[1] = self.lsa[1] * .999 + 1
            for r in b['gk'].get(o, []):
                gp, sa, sv = r[0], r[3], r[4]
                v = self.gs.setdefault(gp, [0.0, 0.0])
                v[0] = v[0] * .995 + sv; v[1] = v[1] * .995 + sa
                self.lsv[0] = self.lsv[0] * .9995 + sv; self.lsv[1] = self.lsv[1] * .9995 + sa
                c = self.seas[S][gp]
                c[0] += 1; c[7] += sv


def market_opens(boxes):
    """ESPN game id -> open moneyline and total from the NHL game history (scripts/nhl_games_hist.json.gz), matched
    by home team and day (ESPN's start is UTC: the NHL's day is that day or the one before)"""
    try:
        H = json.load(gzip.open(os.path.join(HERE, 'nhl_games_hist.json.gz'), 'rt'))
    except OSError:
        return {}
    by = {}
    for g in H:
        o = g.get('o') or g.get('c')
        if o and o.get('ml') and o.get('t'):
            by[(g['day'], g['h'])] = (o['ml'], o['t'])
    out = {}
    for gid, b in boxes.items():
        d = datetime.date.fromisoformat(b['k'][:10])
        for dd in (d - datetime.timedelta(days=1), d):
            v = by.get((dd.isoformat(), b['h']))
            if v:
                out[gid] = v
    return out


def walk(boxes):
    """every played row: {S, g, p, t, kind, po, fx, y}"""
    W = Walk()
    mk = market_opens(boxes)
    rows = []
    for gid, b in sorted(boxes.items(), key=lambda x: x[1]['k']):
        if b['S'] != W.season:
            W.new_season(b['S'])
        if gid in mk:
            b = dict(b, ml=mk[gid][0], ou=mk[gid][1])
        for t, pid, fx, kind in W.rows(b):
            if kind == 'sk':
                r = next(x for x in b['p'][t] if x[0] == pid)
                y = {s: r[IX[s]] for s in SK}
            else:
                r = next(x for x in b['gk'][t] if x[0] == pid)
                if r[2] < 20:
                    continue                                 # a relief appearance: no saves prop stands on it
                y = {'sv': r[4]}
            rows.append({'S': b['S'], 'g': gid, 'p': pid, 't': t, 'kind': kind, 'po': b['po'], 'fx': fx, 'y': y})
        W.update(b)
    return rows, W


def walk_forward(rows):
    """mu by stat for every row, each season's coefficients fit on the seasons before (regular season only)"""
    import numpy as np
    S = np.array([r['S'] for r in rows])
    po = np.array([r['po'] for r in rows])
    coefs = {}
    for s in SK + ('sv',):
        m = np.array([s in r['fx'] for r in rows])
        A = np.array([[r['fx'][s][f] for f in FEATS] if s in r['fx'] else [0.0] * len(FEATS) for r in rows])
        y = np.array([r['y'].get(s, 0.0) for r in rows])
        pred = np.full(len(rows), np.nan)
        for yr in sorted(set(S)) + [max(S) + 1]:
            tr = m & (S < yr) & (po == 0)
            if tr.sum() < 2000:
                continue
            c = np.linalg.lstsq(A[tr], y[tr], rcond=None)[0]
            coefs[yr] = coefs.get(yr, {})
            coefs[yr][s] = [round(float(x), 5) for x in c]
            te = m & (S == yr)
            pred[te] = np.maximum(A[te] @ c, 0.02)
        for r, p in zip(rows, pred):
            if not np.isnan(p):
                r.setdefault('mu', {})[s] = float(p)
    return coefs


def test():
    import numpy as np
    import nhl_pbox as B
    import props_model as M
    rows, _ = walk(B.load())
    coefs = walk_forward(rows)
    print(len(rows), 'rows', flush=True)

    def mu_y(r, st):
        if 'mu' not in r or any(c not in r['mu'] for c in COMBO[st]):
            return None, None
        return sum(r['mu'][c] for c in COMBO[st]), sum(r['y'][c] for c in COMBO[st])
    sh = {}
    for st in COMBO:
        xs = [(m_, y_, r) for r in rows if r['S'] in SHAPE and not r['po'] for m_, y_ in [mu_y(r, st)] if m_ is not None]
        mu = np.array([x[0] for x in xs]); y = np.array([x[1] for x in xs])
        nv = np.array([sum(x[2]['fx'][c]['savg'] for c in COMBO[st]) for x in xs])
        sh[st] = M.fit_shape(mu, y, nv, every=3)
    print('shape', sh, flush=True)
    ix = {(r['g'], r['p']): r for r in rows}
    O = json.load(gzip.open(OPENS, 'rt'))
    out, graded = {}, {}
    for target in ('open', 'close'):
        props, miss = [], defaultdict(int)
        for gid, g in O.items():
            for a, st, L, oO, oU, cL, cO, cU, *_ in g['props']:
                if st not in COMBO:
                    continue
                if target == 'close':
                    L, oO, oU = cL, cO, cU
                r = ix.get((gid, a))
                if r is None:
                    miss['row'] += 1
                    continue
                mu, y = mu_y(r, st)
                if mu is None:
                    miss['mu'] += 1
                    continue
                if oO is None or oU is None or not (-300 <= oO <= 300 and -300 <= oU <= 300) or abs(oO) < 100 or abs(oU) < 100:
                    miss['price'] += 1
                    continue
                props.append({'S': r['S'], 'g': gid, 'a': a, 'st': st, 'L': L, 'oO': oO, 'oU': oU, 'y': y, 'mu': mu,
                              'P': M.p_over(sh[st], mu, L), 'q': M.no_vig(oO, oU), 'b': g['b'], 'k': g['k'], 'po': r['po']})
        res = M.evaluate(props, TUNE, HELD, tuple(COMBO))
        res['missing'] = dict(miss)
        out[target], graded[target] = res, props
        print(target, len(props), json.dumps({k: res[k] for k in ('pstar', 'held', 'heldBySeason', 'heldBySide',
                                                                    'heldAllProps', 'diag', 'calib', 'verdict')}), flush=True)
        print('  by stat alone', {st: (v['tune'].get('roi'), v['held'].get('roi'), v['held'].get('t'), v['held'].get('n'))
                                  for st, v in res['byStatAlone'].items()}, flush=True)
    # the saves rule for the paper test (Noah, Oct 31 2026: "Paper-test NHL saves"): saves alone was the one stat that
    # won on the 2024 tune props; p* is its tune pick, scored held out on its own
    tune_sv = {ps: M.score(M.bets(graded['open'], ps, TUNE, stat='sv')) for ps in M.PSTAR}
    ps = max(M.PSTAR, key=lambda x: tune_sv[x].get('roi', -9) if tune_sv[x]['n'] >= 100 else -9)
    tb = M.bets(graded['open'], ps, TUNE, stat='sv')
    tp = np.array([b[6] for b in tb]); ty = np.array([float(b[1] > 0) for b in tb])
    c = float(((tp - .5) * (ty - .5)).sum() / ((tp - .5) ** 2).sum())
    held = {t: M.score(M.bets(graded[t], ps, HELD, stat='sv')) for t in ('open', 'close')}
    held.update({f'{t} {S}': M.score(M.bets(graded[t], ps, (S,), stat='sv')) for t in ('open', 'close') for S in HELD})
    sv = {'tune': {str(k): v for k, v in tune_sv.items()}, 'pstar': ps, 'c': round(c, 4), 'held': held}
    print('saves', json.dumps(sv), flush=True)
    with open(OUT, 'w') as f:
        json.dump({'shape': sh, 'tests': out, 'saves': sv}, f, indent=1)
    with open(FIT, 'w') as f:
        json.dump({'rule': f'nhl-saves-{round(ps * 100)}', 'registered': '2026-10-31T06:00:00Z', 'stats': ['sv'],
                   'sides': 'ou', 'pstar': ps, 'c': round(c, 4), 'rho': 0.0, 'budget': BUDGET, 'paper': True,
                   'verdict': 'pass', 'shape': {'sv': sh['sv']}, 'feats': list(FEATS),
                   'coefs': {str(int(k)): v['sv'] for k, v in coefs.items() if 'sv' in v},
                   'backtest': {'held': held, 'note': 'saves at the book prices, held out 2025-27: a paper test, not a pass '
                                                      'at the open (t 1.3 at p* .54); shown off the picks tab'}},
                  f, separators=(',', ':'))
    return out, sh, coefs, graded


def upcoming():
    """today's and tomorrow's games not started: [(espn id, start, home, away, (home ML, away ML), total)]"""
    import nhl_pbox as B
    out = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for d in (0, 1):
        day = (now - datetime.timedelta(hours=5) + datetime.timedelta(days=d)).strftime('%Y%m%d')
        j = B.get(f'{SITE}/scoreboard?dates={day}&limit=50') or {}
        for e in j.get('events', []):
            if (e.get('status') or {}).get('type', {}).get('state') != 'pre':
                continue
            c = e['competitions'][0]
            side = {x['homeAway']: B.D.team(x['team']['abbreviation']) for x in c['competitors']}
            od = (c.get('odds') or [{}])[0]
            ml = od.get('moneyline') or {}

            def pick(x):
                v = (ml.get(x) or {})
                for k in ('open', 'close'):
                    try:
                        return float(str((v.get(k) or {}).get('odds')).replace('EVEN', '100'))
                    except (TypeError, ValueError):
                        pass
                return None
            out.append((e['id'], e['date'], side['home'], side['away'], (pick('home'), pick('away')), od.get('overUnder')))
    return out


def build():
    """data/nhl_props.json: every goalie's projected saves for today's and tomorrow's games, for the saves paper test
    (scripts/props_snap.py joins them to DraftKings' saves props by ESPN id)"""
    import nhl_pbox as B
    F = json.load(open(FIT))
    today = datetime.date.today()
    S = today.year + 1 if today.month >= 8 else today.year
    B.pull(since=datetime.date(S - 2, 10, 1))
    boxes = {g: b for g, b in B.load().items() if b['S'] >= S - 1}
    W = Walk()
    for gid, b in sorted(boxes.items(), key=lambda x: x[1]['k']):
        if b['S'] != W.season:
            W.new_season(b['S'])
        W.update(b)
    if W.season != S:
        W.new_season(S)
    coef = F['coefs'].get(str(S)) or F['coefs'][max(F['coefs'])]
    last = {}                                         # goalie -> (team, last start, name) this season and last
    for b in sorted(boxes.values(), key=lambda x: x['k']):
        for t, gs in b['gk'].items():
            for r in gs:
                if r[2] >= 20:
                    last[r[0]] = (t, b['k'], r[1])
    games = []
    for gid, k, h, a, ml, ou in upcoming():
        g = {'id': gid, 'k': k, 'h': h, 'a': a, 'sv': {}}
        b = {'S': S, 'h': h, 'a': a, 'ml': ml if None not in ml else None, 'ou': ou, 'p': {}, 'gk': {}}
        for t in (h, a):
            b['gk'][t] = [[pid, nm, 60.0, 0, 0] for pid, (tt, _, nm) in last.items() if tt == t]
        for t, pid, fx, kind in W.rows(b):
            m = max(0.0, sum(c * fx['sv'][f] for c, f in zip(coef, F['feats'])))
            g['sv'][pid] = {'n': last[pid][2], 't': t, 'm': round(m, 2), 'last': last[pid][1]}
        games.append(g)
    out = {'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'season': S,
           'rule': F['rule'], 'games': games}
    with open(LIVE, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('nhl props:', len(games), 'games,', sum(len(g['sv']) for g in games), 'goalies projected')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
    else:
        build()
