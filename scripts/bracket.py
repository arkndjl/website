# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Projected brackets from season sims, shared by every sport.

Each sim records, per simulated season, every playoff team's seed in its group (conference, region) and the round it
reached. From the counts:
  seed odds   P(team holds seed k of its group), P(in the field)
  projected   the seeding with the most expected exact seeds: an assignment of teams to seed slots (Hungarian on
              the seed-probability matrix), so a team can't fill two slots. It is the bracket a reader would score
              best on seed by seed, which the single most common full seeding (almost never repeated across 10,000
              sims) is not. A division winner's slot goes to the likeliest winner even when no one is above 50% in.
              field_first: the k teams most likely in first, then their seeding (for a field without fixed slots).
  winners     each projected game advances the side with the higher P(reach the next round) in the sims.

    python3 scripts/bracket.py --test
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'data', 'brackets')


def assign(P):
    """P: rows = slots (n), cols = candidates (m >= n), values to maximise. -> list, slot i -> column index.
    Hungarian (shortest augmenting path, O(n^2 m))."""
    n = len(P)
    m = len(P[0]) if n else 0
    if n == 0:
        return []
    if m < n:
        raise ValueError('fewer candidates than slots')
    INF = float('inf')
    big = max(max(r) for r in P)
    a = [[big - x for x in r] for r in P]          # cost, non-negative
    u = [0.0] * (n + 1); v = [0.0] * (m + 1); p = [0] * (m + 1); way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i; j0 = 0
        minv = [INF] * (m + 1); used = [False] * (m + 1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = INF; j1 = 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = a[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur; way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]; j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta; v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0:
                break
    out = [None] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


class Tally:
    """per group: seed counts by team and round reach counts by team.
    groups: {group name: number of seed slots}; rounds: round keys in order (first = in the field)"""

    def __init__(self, groups, rounds):
        self.groups = dict(groups)
        self.rounds = list(rounds)
        self.seed = {g: {} for g in self.groups}
        self.reach = {}
        self.n = 0

    def season(self):
        self.n += 1

    def seeds(self, group, order):
        """order: the group's playoff teams, seed 1 first"""
        S = self.seed[group]
        for k, t in enumerate(order):
            S.setdefault(t, [0] * self.groups[group])[k] += 1

    def reached(self, team, rnd):
        r = self.reach.setdefault(team, dict.fromkeys(self.rounds, 0))
        r[rnd] += 1

    def project(self, field_first=False):
        """{group: [{t, seed, p (P this seed), pin (P in field), sd: [P seed k]}]} best seed first, plus reach odds"""
        N = max(1, self.n)
        out = {}
        for g, k in self.groups.items():
            S = self.seed[g]
            teams = sorted(S, key=lambda t: -sum(S[t]))
            if field_first:
                teams = teams[:k]
            while len(teams) < k:
                teams.append(None)
            P = [[(S[t][i] / N if t else 0.0) for t in teams] for i in range(k)]
            pick = assign(P)
            out[g] = [{'t': teams[j], 'seed': i + 1, 'p': round(P[i][j], 3),
                       'pin': round(sum(S[teams[j]]) / N, 3) if teams[j] else 0.0} for i, j in enumerate(pick)]
        odds = {t: {r: round(c / N, 3) for r, c in v.items()} for t, v in self.reach.items()}
        sd = {g: {t: [round(c / N, 3) for c in v] for t, v in S.items() if sum(v) / N >= 0.005} for g, S in self.seed.items()}
        return out, odds, sd


def advance(a, b, odds, rnd):
    """projected winner of a game in round rnd's reach (the side with the higher P(reach rnd))"""
    if a is None:
        return b
    if b is None:
        return a
    pa = odds.get(a, {}).get(rnd, 0.0); pb = odds.get(b, {}).get(rnd, 0.0)
    return a if pa >= pb else b


def ent(t, seed, odds, k):
    return {'t': t, 'seed': seed, 'p': odds.get(t, {}).get(k, 0.0)} if t is not None else None


def game(a, b, seed, odds, k, kn):
    """one projected game: both sides with P(reach this round k), the winner by P(reach round kn). b None = a bye"""
    return {'a': ent(a, seed.get(a), odds, k), 'b': ent(b, seed.get(b), odds, k), 'w': advance(a, b, odds, kn)}


def payload(asof, sims, tally, proj, odds, sd, sections, rounds, teams, **extra):
    """the file layouts/shortcodes/bracket.html reads. rounds: [[key, label]] for the odds table, first = in the field.
    teams: {t: {n, a, logo}}"""
    groups = [{'name': g, 'n': tally.groups[g], 'seeds': proj[g]} for g in tally.groups]
    keep = {t for t, o in odds.items() if o.get(rounds[0][0], 0) >= 0.005}
    for g in groups:
        keep |= {r['t'] for r in g['seeds'] if r['t']}
    od = {}
    for t in keep:
        o = {k: odds.get(t, {}).get(k, 0.0) for k, _ in rounds}
        for g, m in sd.items():
            if t in m:
                o['sd'] = m[t]; o['g'] = g
        od[t] = o
    return {'asof': asof, 'sims': sims, 'groups': groups, 'sections': sections, 'rounds': rounds, 'odds': od,
            'teams': {t: teams.get(t, {'n': t}) for t in keep}, **extra}


def save(sport, payload):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f'{sport}.json')
    with open(path, 'w') as f:
        json.dump(payload, f, separators=(',', ':'))
    return path


def _test():
    import random
    P = [[.9, .1, 0], [.8, .5, .1], [0, .3, .3]]
    assert assign(P) == [0, 1, 2], assign(P)
    P = [[.2, .7, .1, 0], [.6, .3, .1, 0]]
    assert assign(P) == [1, 0], assign(P)
    rng = random.Random(1)
    for _ in range(200):                                       # brute force check on small random cases
        import itertools
        n, m = rng.randint(1, 4), rng.randint(4, 6)
        P = [[rng.random() for _ in range(m)] for _ in range(n)]
        best = max(itertools.permutations(range(m), n), key=lambda c: sum(P[i][c[i]] for i in range(n)))
        got = assign(P)
        assert abs(sum(P[i][got[i]] for i in range(n)) - sum(P[i][best[i]] for i in range(n))) < 1e-9
    T = Tally({'A': 2}, ['po', 'champ'])
    for s in range(10):
        T.season(); T.seeds('A', ['x', 'y'] if s < 6 else ['y', 'x']); T.reached('x', 'po'); T.reached('y', 'po')
    pr, odds, sd = T.project()
    assert [r['t'] for r in pr['A']] == ['x', 'y'] and pr['A'][0]['p'] == 0.6
    print('bracket ok')


if __name__ == '__main__':
    import sys
    if '--test' in sys.argv:
        _test()
