#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Valve Swiss stage + single-elimination bracket engine (Major supplemental rulebook,
github.com/ValveSoftware/counter-strike_rules_and_regs), shared by the CS2 event odds (scripts/cs2_events.py) and
anything else that simulates a Valve-format stage. Takes a series win function win(a, b, bo) -> P(a beats b).

  swiss(seeds, win, rng, known=(), allbo3=False) -> (W, L, final seed order)
      16 teams, 3 wins advance / 3 losses out. Round 1: seed i v i+8. Rounds 2-3: highest seed v lowest available
      without a rematch. Rounds 4-5: the rulebook's priority table. Mid-stage seed: record, Difficulty Score
      (Buchholz: opponents' wins minus losses), initial seed. Elimination and advancement matches Bo3, the rest Bo1
      (allbo3: every match Bo3). known: per round, [(a, b, winner or None)] already drawn / played.
  bracket(tree, win, rng) -> (champion, winner of each match); tree [(slot, slot, bo)], slot ("t", team) or ("w", i)
  major_tree(order8) -> Valve's playoff tree: 1v8, 4v5 | 2v7, 3v6, Bo3, grand final Bo5
  noisy(logit, teams, sd, rng) -> win(): each team's strength drawn once per simulated event (rating uncertainty)
"""
import math
from collections import defaultdict


PRIORITY = [((1, 6), (2, 5), (3, 4)), ((1, 6), (2, 4), (3, 5)), ((1, 5), (2, 6), (3, 4)), ((1, 5), (2, 4), (3, 6)),
            ((1, 4), (2, 6), (3, 5)), ((1, 4), (2, 5), (3, 6)), ((1, 6), (2, 3), (4, 5)), ((1, 5), (2, 3), (4, 6)),
            ((1, 3), (2, 6), (4, 5)), ((1, 3), (2, 5), (4, 6)), ((1, 4), (2, 3), (5, 6)), ((1, 3), (2, 4), (5, 6)),
            ((1, 2), (3, 6), (4, 5)), ((1, 2), (3, 5), (4, 6)), ((1, 2), (3, 4), (5, 6))]


def high_low(pool, met):
    """Highest seed v the lowest available without a rematch (backtracking so the rest can still pair)."""
    if not pool:
        return []
    a = pool[0]
    for j in range(len(pool) - 1, 0, -1):
        b = pool[j]
        if b in met[a]:
            continue
        rest = high_low(pool[1:j] + pool[j + 1:], met)
        if rest is not None:
            return [(a, b)] + rest
    return None


def pair_pool(pool, met, rnd):
    if rnd >= 3 and len(pool) == 6:
        for row in PRIORITY:
            ps = [(pool[i - 1], pool[j - 1]) for i, j in row]
            if all(b not in met[a] for a, b in ps):
                return ps
        return [(pool[i - 1], pool[j - 1]) for i, j in PRIORITY[0]]
    ps = high_low(pool, met)
    return ps if ps is not None else [(pool[i], pool[-1 - i]) for i in range(len(pool) // 2)]


def swiss(seeds, win, rng, known=(), allbo3=False):
    """One 16-team Swiss stage. seeds: teams in seed order. win(a, b, bo) -> chance a beats b. known: per round, a
    list of (a, b, winner or None) already drawn (and played). -> (W, L, final seed order of all 16)."""
    W = {t: 0 for t in seeds}
    L = {t: 0 for t in seeds}
    met = {t: set() for t in seeds}
    sd = {t: i for i, t in enumerate(seeds)}

    def buch(t):
        return sum(W[o] - L[o] for o in met[t])

    for rnd in range(5):
        if rnd < len(known) and known[rnd]:
            ps = [(a, b) for a, b, _ in known[rnd]]
            res = {frozenset((a, b)): w for a, b, w in known[rnd]}
        else:
            res = {}
            if rnd == 0:
                ps = [(seeds[i], seeds[i + 8]) for i in range(8)]
            else:
                pools = defaultdict(list)
                for t in seeds:
                    if W[t] < 3 and L[t] < 3:
                        pools[(W[t], L[t])].append(t)
                ps = []
                for rec in sorted(pools, key=lambda r: (-r[0], r[1])):
                    pool = sorted(pools[rec], key=lambda t: (-buch(t), sd[t]))
                    ps += pair_pool(pool, met, rnd)
        for a, b in ps:
            bo = 3 if allbo3 or W[a] == 2 or L[a] == 2 else 1
            w = res.get(frozenset((a, b)))
            if w is None:
                w = a if rng.random() < win(a, b, bo) else b
            lo = b if w == a else a
            W[w] += 1
            L[lo] += 1
            met[a].add(b)
            met[b].add(a)
    order = sorted(seeds, key=lambda t: (-W[t], L[t], -buch(t), sd[t]))
    return W, L, order


def bracket(tree, win, rng):
    """Single elimination. tree: [(slot a, slot b, bo)], a slot is ("t", team) or ("w", match index). -> champion,
    and each match's winner."""
    won = []
    for sa, sb, bo, *res in tree:
        a = sa[1] if sa[0] == "t" else won[sa[1]]
        b = sb[1] if sb[0] == "t" else won[sb[1]]
        w = res[0] if res and res[0] in (a, b) else (a if rng.random() < win(a, b, bo) else b)
        won.append(w)
    return won[-1], won


def major_tree(order8):
    """Valve's playoff: 1v8, 4v5 | 2v7, 3v6 (Bo3), semis, grand final Bo5."""
    s = order8
    return [(("t", s[0]), ("t", s[7]), 3), (("t", s[3]), ("t", s[4]), 3), (("t", s[1]), ("t", s[6]), 3),
            (("t", s[2]), ("t", s[5]), 3), (("w", 0), ("w", 1), 3), (("w", 2), ("w", 3), 3), (("w", 4), ("w", 5), 5)]


def noisy(logit, teams, sd, rng):
    """win(a, b, bo) for one simulated event: each team's strength drawn once around its rating (sd on the logit
    scale), so a rating that is off stays off for the whole event."""
    e = {t: rng.gauss(0, sd) if sd else 0.0 for t in teams}
    return lambda a, b, bo: 1 / (1 + math.exp(-(logit(a, b, bo) + e[a] - e[b])))
