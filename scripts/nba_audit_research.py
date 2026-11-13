#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA game model: pre-registered margin terms (usage overlap, late-season tanking, playoff minutes) and the value
of a later injury report. Pre-registration: /mnt/project-files/nba-audit-nov13/prereg.md.

    python3 scripts/nba_audit_research.py [late.pkl]     # data/nba_audit_research.json

Shipped params and inputs (data/nba_games_fit.json), walk-forward coefficients (nba_games_fit.wf), tune 2015-21, held
2022-26, paired t on |margin error|. Needs the player box history (nba_inseason.load_box) for usage. late.pkl:
{game id: {name: status}} from each game's last official report 30+ minutes before tip (2022-26).
"""
import gzip
import json
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as NF

OUT = os.path.join(N.ROOT, 'data', 'nba_audit_research.json')
BOX = os.environ.get('NBA_BOX', '/mnt/project-files/team-models/nba_box_hist.json.gz')
GROUPS = ((3, 'r1'), (5, 'r4'), (8, 'r6'), (99, 'r9'))


def grp(rank):
    return next(k for hi, k in GROUPS if rank <= hi)


def usage(games):
    """season -> {espn id: usage share} from the box history: 0.2 x (FGA + .44 FTA + TOV a minute) / the league's"""
    with gzip.open(BOX, 'rt') as f:
        bx = json.load(f)
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for g in games:
        if g['t'] != 2 or g['id'] not in bx:
            continue
        for rows in bx[g['id']].values():
            for r in rows:
                a = acc[g['S']][str(r[0])]
                a[0] += r[4] + 0.44 * r[8] + r[14]; a[1] += r[1]
    out = {}
    for S, d in acc.items():
        ev = sum(v[0] for v in d.values()); mn = sum(v[1] for v in d.values())
        out[S] = {p: 0.2 * (v[0] / v[1]) / (ev / mn) for p, v in d.items() if v[1] >= 200}
    return out


class Model(N.Model):
    def __init__(self, *a, usg=None, **k):
        super().__init__(*a, **k)
        self.usg_all, self.u = usg or {}, {}
        self.ub = defaultdict(lambda: [0.0, 0.0])
        self.wr = defaultdict(lambda: [0, 0])
        self.pog = defaultdict(int)
        self.r0 = {}
        self.pacc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))    # season -> group -> [minutes played, role minutes]
        self.pm = {}

    def new_season(self, S):
        super().new_season(S)
        self.u = self.usg_all.get(S - 1, {})
        self.wr.clear(); self.pog.clear(); self.r0 = {}
        tot = defaultdict(lambda: [0.0, 0.0])
        for s, d in self.pacc.items():
            if s < S:
                for k, v in d.items():
                    tot[k][0] += v[0]; tot[k][1] += v[1]
        self.pm = {k: v[0] / v[1] for k, v in tot.items() if v[1] > 0}

    def ranks(self, t):
        rs = sorted(((self.role[p][0] / self.role[p][1], p) for p in self.roster(t) if self.role[p][1] > 0), reverse=True)
        return {p: i + 1 for i, (_, p) in enumerate(rs)}

    def mins(self, t, status=None, reported=False, po=False):
        status = status or {}
        rk = self.ranks(t) if po else {}
        fade = self.ra ** self.pog[t]
        exp = []
        for p in self.roster(t):
            m, w = self.role[p]
            if w <= 0:
                continue
            R = m / w
            if po and self.pm:
                R *= self.pm.get(grp(rk[p]), 1.0) ** fade
            st = status.get(p)
            pr = N.play_prob(self.P, st, self.streak[p], reported)
            if self.b2b and t in self.night2:
                g_ = N.b2b_group(self.ages.get(p, 0), m / w)
                if not st and self.streak[p] == 0:
                    pr = min(1.0, pr * self.b2b['P'].get(('rep' if reported else 'norep') + g_, 1.0))
                R *= self.b2b['M'].get(g_, 1.0)
            exp.append((p, R * pr))
        tot = sum(e for _, e in exp)
        sc = 240.0 / tot if tot > 240 else 1.0
        return [(p, e * sc) for p, e in exp], tot * sc

    def value(self, mt):
        ms, tot = mt
        return sum(self.v(p) * e for p, e in ms) / 48 + (N.REPL * (240 - tot) / 48 if tot < 240 else 0.0)

    def U(self, mt):
        ms, tot = mt
        return (sum(self.u.get(p, 0.18) * e for p, e in ms) + 0.2 * max(0.0, 240 - tot)) / 240 - 0.2

    def feats(self, g):
        x, tx = super().feats(g)
        h, a = g['h'], g['a']
        sh, rh = self.status_for(g, h)
        sa, ra = self.status_for(g, a)
        mh, ma = self.mins(h, sh, rh), self.mins(a, sa, ra)
        assert abs(self.value(mh) - self._ctx[0]) < 1e-6 and abs(self.value(ma) - self._ctx[1]) < 1e-6
        Uh, Ua = self.U(mh), self.U(ma)
        x['usg'] = Uh - Ua
        x['usgd'] = (Uh - self.rate(self.ub, h, 1.0)) - (Ua - self.rate(self.ub, a, 1.0))
        bad = lambda t: 1.0 if g['t'] == 2 and self.wr[t][1] >= 55 and self.wr[t][0] / self.wr[t][1] <= 0.35 else 0.0
        x['tank'] = bad(h) - bad(a)
        x['poMin'] = 0.0
        if g['t'] == 3 and self.pm:
            x['poMin'] = ((self.value(self.mins(h, sh, rh, True)) - self._ctx[0])
                          - (self.value(self.mins(a, sa, ra, True)) - self._ctx[1]))
        return x, tx

    def update(self, g):
        if g.get('fin'):
            pl = g.get('pl') or {}
            for t in (g['h'], g['a']):
                rows = [(p, m) for p, m in (pl.get(t) or []) if m > 0]
                tot = sum(m for _, m in rows)
                if tot:
                    b = self.ub[t]
                    b[0] = b[0] * self.ba + sum(self.u.get(p, 0.18) * m for p, m in rows) / tot - 0.2; b[1] = b[1] * self.ba + 1
                if g['t'] == 3 and rows:
                    if t not in self.r0:
                        rk = self.ranks(t)
                        self.r0[t] = {p: (self.role[p][0] / self.role[p][1], grp(rk[p])) for p in rk}
                    st = self.status_for(g, t)[0] or {}
                    on = dict(rows)
                    for p, (R, k) in self.r0[t].items():
                        if self.streak[p] == 0 and st.get(p) not in ('Out', 'Doubtful') and self.team.get(p) == t:
                            a_ = self.pacc[g['S']][k]
                            a_[0] += on.get(p, 0.0); a_[1] += R
                    self.pog[t] += 1
            if g['t'] == 2:
                w = g['hs'] > g['as']
                self.wr[g['h']][0] += w; self.wr[g['h']][1] += 1
                self.wr[g['a']][0] += (not w); self.wr[g['a']][1] += 1
        super().update(g)


EXTRA = ['usg', 'usgd', 'tank', 'poMin']


def design(games, names, P, params, inj, feats, usg):
    m = Model(names, P, inj=inj, usg=usg, **params)
    D = []
    for g in games:
        x, tx = m.feats(g)
        if g.get('fin') and g['S'] >= N.FIRST + 1:
            D.append((g, x))
        m.update(g)
    X = {f: np.array([x[f] for _, x in D]) for f in list(feats) + EXTRA}
    y = np.array([g['hs'] - g['as'] for g, _ in D], float)
    S = np.array([g['S'] for g, _ in D])
    po = np.array([g['t'] == 3 for g, _ in D])
    ids = [g['id'] for g, _ in D]
    return X, y, S, po, ids, m


def pt(a, b):
    d = a - b
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0


def main():
    F = json.load(open(N.FIT))
    feats, params = F['feats'], F['params']
    games, names = N.load_hist()
    inj = NF.load_inj()
    _, _, PT = NF.measure_P(games, names, inj, {k: v for k, v in params.items() if k != 'b2b'})
    usg = usage(games)
    X, y, S, po, ids, m = design(games, names, PT, params, inj, feats, usg)
    k1, k2 = (S >= 2015) & (S < 2022), S >= 2022
    base = NF.wf(NF.mat(X, feats), y, S)
    e0 = np.abs(base - y)
    out = {'prereg': '/mnt/project-files/nba-audit-nov13/prereg.md', 'base': {'tune': round(float(e0[k1].mean()), 4), 'held': round(float(e0[k2].mean()), 4)},
           'poMult': {k: round(v, 3) for k, v in sorted(m.pm.items())}, 'terms': {}}
    print('base', out['base'], 'playoff minutes multipliers', out['poMult'], flush=True)
    for c in EXTRA:
        pr = NF.wf(NF.mat(X, feats + [c]), y, S)
        e = np.abs(pr - y)
        b = np.linalg.lstsq(NF.mat(X, feats + [c]), y, rcond=None)[0][-1]
        r = {'coef': round(float(b), 3), 'sd': round(float(X[c].std()), 4), 'tune_t': round(pt(e[k1], e0[k1]), 2), 'tune_d': round(float((e - e0)[k1].mean()), 4),
             'held_t': round(pt(e[k2], e0[k2]), 2), 'held_d': round(float((e - e0)[k2].mean()), 4)}
        if c == 'poMin':
            r.update(po_tune_t=round(pt(e[k1 & po], e0[k1 & po]), 2), po_held_t=round(pt(e[k2 & po], e0[k2 & po]), 2),
                     po_tune_d=round(float((e - e0)[k1 & po].mean()), 4), po_held_d=round(float((e - e0)[k2 & po].mean()), 4), n_po=[int((k1 & po).sum()), int((k2 & po).sum())])
        out['terms'][c] = r
        print(c, r, flush=True)
    if len(sys.argv) > 1:
        late, used = pickle.load(open(sys.argv[1], 'rb'))
        inj2 = dict(inj)
        inj2.update({gid: {N.norm(k): v for k, v in rep.items()} for gid, rep in late.items()})
        X2, y2, S2, _, ids2, _ = design(games, names, PT, params, inj2, feats, usg)
        assert ids2 == ids
        # coefficients as shipped: fit on the 5 PM reports' design, applied to the late-report design
        pr = np.full(len(y), np.nan)
        Xm, Xl = NF.mat(X, feats), NF.mat(X2, feats)
        for s in range(2022, int(S.max()) + 1):
            pr[S == s] = Xl[S == s] @ np.linalg.lstsq(Xm[S < s], y[S < s], rcond=None)[0]
        e = np.abs(pr - y)
        ch = np.array([i in late for i in ids]) & k2
        mv = np.abs(pr - base)
        out['late'] = {'n': int(ch.sum()), 'held_d': round(float((e - e0)[ch].mean()), 4), 'held_t': round(pt(e[ch], e0[ch]), 2),
                       'meanMove': round(float(mv[ch].mean()), 3), 'moved1': int((mv[ch] >= 1).sum()),
                       'moved1_d': round(float((e - e0)[ch & (mv >= 1)].mean()), 3) if (ch & (mv >= 1)).any() else None,
                       'bySeason': {int(s): round(float((e - e0)[ch & (S == s)].mean()), 4) for s in range(2022, 2027)}}
        print('late', out['late'], flush=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
