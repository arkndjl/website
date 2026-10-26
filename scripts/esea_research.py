#!/usr/bin/env python3
"""1NT model research (Oct 26 2026): what predicts an ESEA NA league match, and which inputs the 1NT
page's preview, season sim and power rank should use.

    python3 scripts/esea_research.py     # reads research/esea_matches.json.gz (scripts/esea_research_fetch.mjs)
                                          # and the git history of data/esea.json; writes data/esea_research.json

Every rating is walk-forward: a match is predicted from earlier matches only, then the ratings update.
Candidates (match winner, log loss and Brier, paired per match):
  record7   each team's season record shrunk to .500 by 7 games, log5 (the live season sim and stakes odds)
  elo       team Elo on league results, carried across seasons (carry x last rating), division offsets
  relo      the same on round share (a 13-3 moves it more than 13-11)
  pelo      player Elo: a team is the mean of the five who played; ratings follow players between teams
  prelo     player Elo on round share
Tuning on seasons before the hold-out season (grid on K / carry), held out on the last season.
Live-model check on S59: the page's own power-rank inputs (round diff per map, team ARK, FACEIT elo,
talent) as they stood before each match, from data/esea.json's git history.
"""
import gzip
import json
import math
import os
import subprocess
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'research', 'esea_matches.json.gz')
OUT = os.path.join(ROOT, 'data', 'esea_research.json')
DIV_RANK = {'Intermediate': 0, 'Main': 1, 'Advanced': 2}


def clip(p):
    return min(1 - 1e-4, max(1e-4, p))


def ll(p, y):
    p = clip(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def load():
    d = json.load(gzip.open(DATA))
    ms = []
    for m in d['matches']:
        if m.get('winner') not in ('faction1', 'faction2') or not m.get('at'):
            continue
        rf = ra = 0
        for mp in m.get('maps') or []:
            if mp.get('s1') is not None and mp.get('s2') is not None:
                rf += mp['s1']
                ra += mp['s2']
        m['y'] = 1 if m['winner'] == 'faction1' else 0
        m['share'] = rf / (rf + ra) if rf + ra else None
        m['players'] = [[p[0] for p in (mp.get('p1') or [])] for mp in m['maps'][:1]]
        p1 = {p[0] for mp in m['maps'] for p in (mp.get('p1') or [])}
        p2 = {p[0] for mp in m['maps'] for p in (mp.get('p2') or [])}
        m['P1'] = list(p1) or [r[0] for r in m['f1']['roster']][:5]
        m['P2'] = list(p2) or [r[0] for r in m['f2']['roster']][:5]
        m['div_r'] = DIV_RANK.get(m['div'].split()[0], 1)
        ms.append(m)
    ms.sort(key=lambda m: m['at'])
    return d, ms


# ---- rating models: predict(m) -> p(f1), update(m) ----------------------------------------------
class Record7:
    def __init__(self, k=7):
        self.k, self.rec = k, defaultdict(lambda: [0, 0])

    def key(self, m, t):
        return (m['season'], m[t]['id'])

    def predict(self, m):
        a, b = self.rec[self.key(m, 'f1')], self.rec[self.key(m, 'f2')]
        pa, pb = (a[0] + self.k / 2) / (a[1] + self.k), (b[0] + self.k / 2) / (b[1] + self.k)
        x, y = pa * (1 - pb), pb * (1 - pa)
        return x / (x + y)

    def update(self, m):
        for t, w in (('f1', m['y']), ('f2', 1 - m['y'])):
            r = self.rec[self.key(m, t)]
            r[0] += w
            r[1] += 1


class Elo:
    """Team or player Elo. margin=True updates on round share instead of the result; carry pulls a
    rating toward its division's level at each new season; new entries start at the division level."""
    def __init__(self, K=32, carry=0.7, margin=False, players=False, div_gap=100, scale=400):
        self.K, self.carry, self.margin, self.players, self.gap, self.s = K, carry, margin, players, div_gap, scale
        self.r, self.season = {}, {}

    def ids(self, m, t):
        return (m['P1'] if t == 'f1' else m['P2']) if self.players else [m[t]['id']]

    def get(self, i, m):
        base = self.gap * (m['div_r'] - 1)
        if i not in self.r:
            self.r[i], self.season[i] = base, m['season']
        elif self.season[i] != m['season']:
            self.r[i] = base + self.carry * (self.r[i] - base)
            self.season[i] = m['season']
        return self.r[i]

    def team(self, m, t):
        v = [self.get(i, m) for i in self.ids(m, t)]
        return sum(v) / len(v) if v else self.gap * (m['div_r'] - 1)

    def predict(self, m):
        d = self.team(m, 'f1') - self.team(m, 'f2')
        return 1 / (1 + 10 ** (-d / self.s))

    def update(self, m):
        p = self.predict(m)
        y = m['y']
        if self.margin and m['share'] is not None:
            # round share mapped to a win-equivalent: .5 + 2.5 x (share - .5), capped to [0, 1]
            y = min(1, max(0, 0.5 + 2.5 * (m['share'] - 0.5)))
        delta = self.K * (y - p)
        for t, sgn in (('f1', 1), ('f2', -1)):
            for i in self.ids(m, t):
                self.r[i] = self.get(i, m) + sgn * delta


def run(ms, model, seasons):
    out = {}
    for m in ms:
        if m['season'] in seasons:
            out[m['id']] = model.predict(m)
        model.update(m)
    return out


def score(ms, preds, ids=None):
    xs = [(preds[m['id']], m['y']) for m in ms if m['id'] in preds and (ids is None or m['id'] in ids)]
    if not xs:
        return None
    return {'n': len(xs), 'logloss': sum(ll(p, y) for p, y in xs) / len(xs), 'brier': sum((p - y) ** 2 for p, y in xs) / len(xs),
            'acc': sum((p >= .5) == (y == 1) for p, y in xs) / len(xs)}


def paired(ms, pa, pb, ids):
    d = [ll(pa[m['id']], m['y']) - ll(pb[m['id']], m['y']) for m in ms if m['id'] in ids and m['id'] in pa and m['id'] in pb]
    n = len(d)
    if n < 3:
        return None
    mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) or 1e-9
    return {'n': n, 'diff': round(mu, 4), 't': round(mu / (sd / math.sqrt(n)), 2)}


def r4(x):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} if x else x


if __name__ == '__main__':
    d, ms = load()
    seasons = sorted({m['season'] for m in ms})
    held = seasons[-1]
    tune = set(seasons[1:-1])   # first season only warms the ratings up
    print('seasons', seasons, 'matches', len(ms), {s: sum(m['season'] == s for m in ms) for s in seasons})
    res = {'asof': d.get('asof'), 'matches': len(ms), 'seasons': seasons, 'held': held, 'tune': {}, 'held_out': {}}
    cands = {'record7': lambda **k: Record7(), 'elo': lambda **k: Elo(**k), 'relo': lambda **k: Elo(margin=True, **k),
             'pelo': lambda **k: Elo(players=True, **k), 'prelo': lambda **k: Elo(players=True, margin=True, **k)}
    grid = [dict(K=K, carry=c, div_gap=g) for K in (16, 24, 32, 48) for c in (0.4, 0.6, 0.8, 1.0) for g in (0, 100, 200)]
    best = {}
    for name, mk in cands.items():
        if name == 'record7':
            best[name] = {}
            continue
        sc = []
        for g in grid:
            pr = run(ms, mk(**g), tune)
            sc.append((score(ms, pr)['logloss'], g))
        sc.sort(key=lambda x: x[0])
        best[name] = sc[0][1]
        res['tune'][name] = {'best': sc[0][1], 'logloss': round(sc[0][0], 4)}
        print('tune', name, sc[0])
    heldset = {m['id'] for m in ms if m['season'] == held}
    preds = {name: run(ms, cands[name](**best[name]), set(seasons)) for name in cands}
    for name in cands:
        res['held_out'][name] = {'tune': r4(score(ms, preds[name], {m['id'] for m in ms if m['season'] in tune})), 'held': r4(score(ms, preds[name], heldset)),
                                 'vs_record7_tune': paired(ms, preds[name], preds['record7'], {m['id'] for m in ms if m['season'] in tune}),
                                 'vs_record7_held': paired(ms, preds[name], preds['record7'], heldset)}
        print(name, res['held_out'][name])
    json.dump(res, open(OUT, 'w'), indent=1)
