"""Team ratings that carry their own uncertainty: a Kalman filter on points over an average team (numpy).

Every team's rating is a state with a variance, and the filter keeps the full covariance across teams (ratings are
only known relative to each other). A game is one noisy look at the home minus away gap:

    observed margin (or a closing spread) = r_home - r_away + home court + noise, noise variance R

The gain on each team is its share of the gap's uncertainty, so a rating moves fast while it is uncertain (opening
night, a new team) and settles as games accumulate. Between games each team's variance grows by q (form drifts);
each offseason the means fall back toward the prior (keep) and the variances widen by Q0 (rosters change).

    k = Kalman(R=150, q=0.05, Q0=10)
    k.new_season()                      # or k.new_season(prior={team: (mean, var)}) from a market prior
    k.drift(h, a)                       # before each game
    m, v = k.pred(h, a, neutral)        # expected margin and the variance of the rating gap (not game noise)
    k.update(h, a, margin, neutral)     # after the game

Scripts: nba_kalman_research.py (the tests), nba_games.py (live ratings).
"""
import math

import numpy as np


class Kalman:
    def __init__(self, R, q, Q0, keep=1.0, P0=None, hca=0.0):
        self.R, self.q, self.Q0, self.keep, self.hca = float(R), float(q), float(Q0), float(keep), float(hca)
        self.P0 = float(P0 if P0 is not None else Q0)
        self.idx = {}
        self.x = np.zeros(0)
        self.P = np.zeros((0, 0))
        self.ll = 0.0                    # running innovation log-likelihood (for tuning)
        self.n = 0

    def i(self, t):
        if t not in self.idx:
            n = len(self.x)
            self.idx[t] = n
            self.x = np.append(self.x, 0.0)
            P = np.zeros((n + 1, n + 1))
            P[:n, :n] = self.P
            P[n, n] = self.P0
            self.P = P
        return self.idx[t]

    def new_season(self, prior=None):
        """means back toward 0 (or a prior's means), variances widened by Q0 (or set to the prior's variances)"""
        self.x *= self.keep
        self.P = self.P * self.keep ** 2 + self.Q0 * np.eye(len(self.x))
        for t, (m, v) in (prior or {}).items():
            j = self.i(t)
            self.x[j] = m
            self.P[j, :] = 0.0; self.P[:, j] = 0.0
            self.P[j, j] = v

    def rating(self, t):
        j = self.i(t)
        return float(self.x[j]), float(self.P[j, j])

    def pred(self, h, a, neutral=0, s=-1):
        """s -1: the gap h - a (margins, spreads); s +1: the sum h + a (totals, each rating a team's points over the
        league in its games)"""
        i, j = self.i(h), self.i(a)
        m = self.x[i] + s * self.x[j] + (0.0 if neutral else self.hca)
        v = self.P[i, i] + self.P[j, j] + 2 * s * self.P[i, j]
        return float(m), float(v)

    def drift(self, h, a):
        """a game's worth of form drift on both teams; call once before pred() and update() for the game"""
        i, j = self.i(h), self.i(a)
        self.P[i, i] += self.q; self.P[j, j] += self.q

    def update(self, h, a, y, neutral=0, R=None, s=-1):
        i, j = self.i(h), self.i(a)
        R = self.R if R is None else R
        m, v = self.pred(h, a, neutral, s)
        S = v + R
        e = y - m
        self.ll += -0.5 * (math.log(2 * math.pi * S) + e * e / S)
        self.n += 1
        PH = self.P[:, i] + s * self.P[:, j]      # P H'
        K = PH / S
        self.x += K * e
        self.P -= np.outer(K, PH)
        return e, S
