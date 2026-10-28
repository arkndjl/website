#!/usr/bin/env python3
"""Schedule spots in every other sport: letdown, look-ahead and blowout (thread "Test a CFB letdown-game driver",
Oct 28 2026). The CFB version (scripts/cfb_spots.py) shipped the letdown term; this asks the same of NFL, NBA, CBB, NHL,
soccer and tennis. Research only: nothing passed, nothing ships. Results in data/spots_research.json.

Pre-registered before any outcome was looked at. Team T, G2 = this game (regular season), G1 = T's previous game in the
walk-forward file (scripts/data/games_wf/<sport>.json.gz), G3/G4 its next ones.
  elite opponent (the analogue of ranked), known before kickoff: NFL/NBA/NHL top 8 by win % to date (min 4 games),
    CBB AP top 25 at kickoff (ESPN scoreboards, cached in scripts/.cache/cbb/scoreboard), soccer top 4 of its league by
    points per game (min 5), tennis ranked top 10
  dog / favourite at the close: NFL 3 pts, NBA 5, CBB 5; NHL win prob .40 / .60; soccer .30 / .55; tennis .35 / .70
  gap between games: NFL 9 days, NBA/NHL/CBB 4, soccer 8, tennis 4 (10 for the blowout spot)
  LD  letdown      won G1 vs an elite opponent or as a dog                                 expected -
  LA  look-ahead   G3 vs an elite opponent (soccer: or a UEFA game), G2's opponent not elite   expected -
  LA2 look-ahead   either of the next two games                                            expected -
  BB  blowout spot lost G1 as a favourite                                                  expected +
  (tennis: LD and BB only; the next opponent in a draw isn't known ahead)
Outcome: spread sports result - close (and - model), NHL home win - close prob, soccer (home win - away win) minus the
close's (cH - cA), tennis win - close prob (side by match id parity). x = flag(home) - flag(away). Tune / held: NFL, NBA
2015-21 / 2022-26; CBB 2016-21 / 2022-26; NHL 2017-21 / 2022-26; soccer 2013-20 / 2021-26; tennis 2025 / 2026.
Errors clustered by game day. Pass: tune t >= 1.5 in the expected direction AND held-out squared error of close + b x
(b from tune) below the close at paired t <= -1.5. One BH family over these 22 tests and the 16 CFB ones.

Result (Oct 28 2026): none pass. Near misses, each strong on one split only (re-score after the 2026-27 seasons, same
definitions): NBA letdown (tune -0.3 t -1.2, held -0.8 t -2.5, q .06), soccer blowout spot (tune +.035 t 1.2, held
+.10 t 2.9, q .05), CBB blowout spot (tune +0.7 t 2.4, held +0.4 t 1.3 but no held-out error gain, q .06).

    python3 scripts/spots_research.py            # every sport -> data/spots_research.json
"""
import bisect
import collections
import datetime
import glob
import json
import gzip
import math
import os
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

WF = os.path.join(HERE, 'data', 'games_wf', '{}.json.gz')
CBB_SB = os.path.join(HERE, '.cache', 'cbb', 'scoreboard')
OUT = os.path.join(ROOT, 'data', 'spots_research.json')
SPEC = {
    'nfl': dict(gap=9, dog=lambda s: s <= -3, fav=lambda s: s >= 3, top=8, tune=range(2015, 2022)),
    'nba': dict(gap=4, dog=lambda s: s <= -5, fav=lambda s: s >= 5, top=8, tune=range(2015, 2022)),
    'cbb': dict(gap=4, dog=lambda s: s <= -5, fav=lambda s: s >= 5, top=25, tune=range(2016, 2022)),
    'nhl': dict(gap=4, dog=lambda p: p <= .40, fav=lambda p: p >= .60, top=8, tune=range(2017, 2022)),
    'soccer': dict(gap=8, dog=lambda p: p <= .30, fav=lambda p: p >= .55, top=4, tune=range(2013, 2021)),
}
SIGN = {'LD': -1, 'LA': -1, 'LA2': -1, 'BB': 1}
MIN_GP = {'soccer': 5}


def when(s):
    s = s.replace('Z', '')
    return datetime.datetime.fromisoformat(s[:16] if 'T' in s else s[:10] + 'T12:00')


def ols_cl(X, y, c):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    meat = sum(np.outer(s, s) for s in (X[c == g].T @ e[c == g] for g in np.unique(c)))
    n, k = X.shape
    G = len(np.unique(c))
    V = XtXi @ meat @ XtXi * G / (G - 1) * (n - 1) / (n - k)
    return b, np.sqrt(np.diag(V))


# ---- games: home outcome y, close c and model m on the same scale, the close's home strength s (team view via tv)
def games(sport):
    G = []
    for r in json.load(gzip.open(WF.format(sport))):
        if sport in ('nfl', 'nba', 'cbb'):
            if r.get('res') is None or r.get('L') is None:
                continue
            G.append(dict(id=str(r['id']), S=r['S'], t=when(r['date']), h=r['home'], a=r['away'], po=r.get('po', 0), y=float(r['res']),
                          c=float(r['L']), m=float(r['m']), hw=r['res'] > 0, aw=r['res'] < 0, s=float(r['L'])))
        elif sport == 'nhl':
            if not r.get('c') or r['c'].get('p') is None:
                continue
            G.append(dict(id=str(r['id']), S=r['S'], t=when(r['day']), h=r['h'], a=r['a'], po=r.get('po', 0), y=float(r['hs'] > r['as']),
                          c=r['c']['p'], m=r['p'], hw=r['hs'] > r['as'], aw=r['as'] > r['hs'], s=r['c']['p']))
        else:
            if not r.get('c'):
                continue
            c, p = r['c'], r['p']
            G.append(dict(id=str(r['id']), S=r['S'], t=when(r['day']), h=r['h'], a=r['a'], po=0, lg=r['lg'], y=float((r['hs'] > r['as']) - (r['as'] > r['hs'])),
                          c=c[0] - c[2], m=p[0] - p[2], hw=r['hs'] > r['as'], aw=r['as'] > r['hs'], s=(c[0], c[2])))
    G.sort(key=lambda g: g['t'])
    return G


def tv(sport, g, me):
    if sport in ('nfl', 'nba', 'cbb'):
        return g['s'] if me == 'h' else -g['s']
    if sport == 'nhl':
        return g['s'] if me == 'h' else 1 - g['s']
    return g['s'][0] if me == 'h' else g['s'][1]


def table_game(sport, g):
    return not g['po'] and not (sport == 'soccer' and g['lg'].startswith('uefa'))


class Standings:
    """each team's record before a date, and the top-N cutoff of its league table that day (win %, soccer points a game)"""

    def __init__(self, sport, G):
        self.sport, self.top, self.min = sport, SPEC[sport]['top'], MIN_GP.get(sport, 4)
        self.hist, self.cut = collections.defaultdict(list), collections.defaultdict(list)
        tbl = collections.defaultdict(dict)
        for day, gs in self._days(G):
            for lgk in {self._lg(g) for g in gs if table_game(sport, g)}:
                vals = sorted((self._val(v) for v in tbl[lgk].values() if v[0] >= self.min), reverse=True)
                self.cut[lgk].append((day, vals[self.top - 1] if len(vals) >= self.top else 9))
            for g in gs:
                if not table_game(sport, g):
                    continue
                for side, w, l in (('h', g['hw'], g['aw']), ('a', g['aw'], g['hw'])):
                    v = tbl[self._lg(g)].setdefault(g[side], [0, 0, 0])
                    v[0] += 1
                    v[1] += w
                    v[2] += 3 * w + (not w and not l)
                    self.hist[(g['S'], g[side])].append((g['t'], tuple(v), self._lg(g)))

    def _days(self, G):
        by = collections.OrderedDict()
        for g in G:
            by.setdefault(g['t'].date(), []).append(g)
        return by.items()

    def _lg(self, g):
        return (g['S'], g.get('lg'))

    def _val(self, v):
        return v[2] / v[0] if self.sport == 'soccer' else v[1] / v[0]

    def elite(self, S, team, t):
        h = self.hist.get((S, team), [])
        i = bisect.bisect_left([x[0] for x in h], t)
        if not i:
            return False
        _, v, lgk = h[i - 1]
        cs = self.cut[lgk]
        j = bisect.bisect_right([x[0] for x in cs], t.date())
        return v[0] >= self.min and j > 0 and self._val(v) >= cs[j - 1][1]


def cbb_ranks():
    R = {}
    for fn in glob.glob(os.path.join(CBB_SB, '*.json')):
        for e in json.load(open(fn)).get('events', []):
            t = {x['homeAway']: x for x in e['competitions'][0]['competitors']}
            if 'home' in t and 'away' in t:
                rk = lambda x: (lambda r: r if r and r <= 25 else 99)((x.get('curatedRank') or {}).get('current', 99))
                R[e['id']] = {'h': rk(t['home']), 'a': rk(t['away'])}
    return R


def flags(sport, G):
    sp, st = SPEC[sport], Standings(sport, G)
    RK = cbb_ranks() if sport == 'cbb' else None

    def elite(g, side, at):          # side's team elite as of `at`; CBB: its AP rank at that game's kickoff
        if sport == 'cbb':
            return RK.get(g['id'], {}).get(side, 99) <= 25
        if sport == 'soccer' and g['lg'].startswith('uefa') and at == g['t']:
            return False             # a UEFA opponent is elite only as the game ahead (look-ahead)
        return st.elite(g['S'], g[side], at)

    sch = collections.defaultdict(list)
    for g in G:
        for me, op in (('h', 'a'), ('a', 'h')):
            sch[g[me]].append((g, me, op))
    F = {}
    for es in sch.values():
        for i, (g, me, op) in enumerate(es):
            f = dict.fromkeys(SIGN, 0)
            F[(g['id'], me)] = f
            if g['po']:
                continue
            if i:
                p, pme, pop = es[i - 1]
                if p['S'] == g['S'] and (g['t'] - p['t']).total_seconds() / 864e2 <= sp['gap']:
                    won, lost = (p['hw'], p['aw']) if pme == 'h' else (p['aw'], p['hw'])
                    s = tv(sport, p, pme)
                    f['LD'] = int(won and (elite(p, pop, p['t']) or sp['dog'](s)))
                    f['BB'] = int(lost and sp['fav'](s))
            cur_ok = not elite(g, op, g['t']) and not (sport == 'soccer' and g['lg'].startswith('uefa'))
            big = []
            for j in (i + 1, i + 2):
                if j < len(es):
                    n, _, nop = es[j]
                    if n['S'] == g['S'] and (n['t'] - g['t']).total_seconds() / 864e2 <= sp['gap'] * (j - i):
                        # the next opponent's standing as of G2's kickoff (CBB: its rank at its own kickoff, days later)
                        big.append((sport == 'soccer' and n['lg'].startswith('uefa')) or elite(n, nop, g['t']))
            f['LA'] = int(cur_ok and bool(big) and big[0])
            f['LA2'] = int(cur_ok and any(big))
    return F


def score(rows, x, y, C, M, tune, day):
    held = ~tune
    X = np.c_[np.ones(len(x)), x]
    o = {'flagged': [int((x[tune] != 0).sum()), int((x[held] != 0).sum())]}
    for base, nm in ((C, 'close'), (M, 'model')):
        if base is None:
            continue
        r = y - base
        d = {}
        for part, mk in (('tune', tune), ('held', held)):
            b, s = ols_cl(X[mk], r[mk], day[mk])
            d[part] = [round(float(b[1]), 4), round(float(b[1] / s[1]), 2)]
        bt = ols_cl(X[tune], r[tune], day[tune])[0]
        new, old = base + bt[0] + bt[1] * x, base + r[tune].mean()
        pr = H.paired(H.se(new[held], y[held]), H.se(old[held], y[held]), cluster=day[held])
        d['seHeld'] = [round(float(pr['d']), 5), round(pr['t'], 2)]
        o[nm] = d
    return o


def team_sport(sport):
    G = games(sport)
    F = flags(sport, G)
    rows = [g for g in G if not g['po']]
    S = np.array([g['S'] for g in rows])
    day = np.array([g['t'].date().isoformat() for g in rows])
    y, C, M = (np.array([g[k] for g in rows], float) for k in ('y', 'c', 'm'))
    tune = np.isin(S, list(SPEC[sport]['tune']))
    return {k: score(rows, np.array([F[(g['id'], 'h')][k] - F[(g['id'], 'a')][k] for g in rows], float), y, C, M, tune, day) for k in SIGN}


def tennis():
    import tennis_data as T
    rows = []
    for r in T.mm_rows(refresh=False):
        try:
            pc, t = float(r['winner_close_prob']), when(r['start_time_utc'])
        except (ValueError, KeyError):
            continue
        if 0 < pc < 1:
            rk = lambda x: int(x) if x else 9999
            rows.append(dict(id=r['match_id'], t=t, w=r['_tour'] + r['winner_id'], l=r['_tour'] + r['loser_id'], pc=pc, wr=rk(r['winner_rank']), lr=rk(r['loser_rank'])))
    rows.sort(key=lambda g: g['t'])
    sch = collections.defaultdict(list)
    for g in rows:
        sch[g['w']].append((g, 'w'))
        sch[g['l']].append((g, 'l'))
    F = {}
    for es in sch.values():
        for i, (g, me) in enumerate(es):
            f = F[(g['id'], me)] = {'LD': 0, 'BB': 0}
            if i:
                q, qme = es[i - 1]
                gap = (g['t'] - q['t']).total_seconds() / 864e2
                pq, opp = (q['pc'], q['lr']) if qme == 'w' else (1 - q['pc'], q['wr'])
                f['LD'] = int(qme == 'w' and gap <= 4 and (opp <= 10 or pq <= .35))
                f['BB'] = int(qme == 'l' and gap <= 10 and pq >= .70)
    side = [('w', 'l') if zlib.crc32(g['id'].encode()) % 2 == 0 else ('l', 'w') for g in rows]
    y = np.array([float(a == 'w') for a, _ in side])
    C = np.array([g['pc'] if a == 'w' else 1 - g['pc'] for g, (a, _) in zip(rows, side)])
    S = np.array([g['t'].year for g in rows])
    day = np.array([g['t'].date().isoformat() for g in rows])
    return {k: score(rows, np.array([F[(g['id'], a)][k] - F[(g['id'], b)][k] for g, (a, b) in zip(rows, side)], float), y, C, None, S == 2025, day)
            for k in ('LD', 'BB')}


def family(res):
    """one BH family: these tests and the CFB ones (data/cfb_spots.json)"""
    N = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
    tests = []
    for sp, d in res.items():
        for k, o in d.items():
            c = o['close']
            z = H.stouffer([SIGN[k] * c['tune'][1], SIGN[k] * c['held'][1]])
            o['z'] = round(z, 2)
            o['pass'] = bool(SIGN[k] * c['tune'][1] >= 1.5 and c['seHeld'][1] <= -1.5)
            tests.append((o, 2 * (1 - N(abs(z)))))
    cfb = json.load(open(os.path.join(ROOT, 'data', 'cfb_spots.json')))['terms']
    tests += [({}, o['p']) for o in cfb.values()]
    for (o, p), q in zip(tests, H.bh([p for _, p in tests])):
        if o:
            o['p'], o['q'] = round(p, 5), round(float(q), 4)


if __name__ == '__main__':
    res = {sp: team_sport(sp) for sp in SPEC}
    res['tennis'] = tennis()
    family(res)
    json.dump({'asof': datetime.date.today().isoformat(), 'sports': res}, open(OUT, 'w'), indent=1)
    for sp, d in res.items():
        for k, o in d.items():
            c = o['close']
            print(f"{sp:7}{k:4} n {o['flagged']}  close tune {c['tune']} held {c['held']} held SE {c['seHeld']}  q {o['q']}  {'PASS' if o['pass'] else ''}")
