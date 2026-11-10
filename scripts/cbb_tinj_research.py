#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB totals: availability in the total. The margin has 'inj' (rotation players who sat the team's last game, valued by
game BPM over the team's bench) and 'pinj' (last season's players who haven't played yet); the total has neither.
A missing scorer lowers his own side's points and a missing defender raises the other side's, so the same players
split into offensive and defensive game BPM (Barttorvik's per-game OBPM + DBPM = BPM) move the total by their
defensive value minus their offensive value.

PRE-REGISTERED (before any run):
  players   exactly avail()'s and pre_out()'s: the same rotation, sat-last-game and not-yet-played sets, the same weight
            (minutes a team game / 40) and the same players (net BPM over the bench > 0)
  split     each side shrunk to half the flat level (-0.5 by 150 minutes, as BPM to -1), the bench's O and D levels
            shrunk to half the flat replacement (-1.5 each by 400 bench minutes)
  terms     tinj   sum over both teams of weight x ((DBPM - bench D) - (OBPM - bench O)) x poss / 100, avail players
            tinj2  tinj plus the same over pre_out players (last season's split line)
  fit       each a totals term (TFEATS) fit walk-forward, like every totals input
  pass      house bar (scripts/cbb_tclash_research.py): totals MAE 2016-20 paired t <= -1.5 (day clusters), 2021-26
            not worse, and against the close (close + b (model - close) + c term, walk-forward) held-out SE no worse.
            Holm over the two terms on the tune t.

    OMP_NUM_THREADS=1 python3 scripts/cbb_tinj_research.py      # -> data/cbb_tinj_research.json

Result: both FAIL, not shipped (TFEATS unchanged). Coefficient ~.42-.43 (right sign, near the margin's .49).
  tinj   totals MAE tune -0.0037 (t -2.26), held -0.0021 (t -1.25); vs the close held-out SE +0.0049 (worse)
  tinj2  tune -0.0056 (t -2.76), held -0.0015 (t -0.79); vs the close held-out SE +0.0217 (worse)
The close already prices who is missing from the total.
"""
import gzip
import json
import os
import sys
from collections import defaultdict

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H        # noqa: E402
import cbb_games as C      # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_tinj_research.json')


def od_logs(season):
    """team -> [(date, {pid: (min, obpm, dbpm)})], Barttorvik's game lines (cols 30, 31: OBPM + DBPM = col 44)"""
    C.bt_logs(season)
    try:
        rows = json.load(gzip.open(os.path.join(C.BTLOG, f'{season}.json.gz')))
    except Exception:
        return {}
    by = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        try:
            d = str(r[0]); d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
            if (r[8] or 0) > 0:
                by[r[47]][d][r[51]] = (float(r[8]), float(r[30] or 0), float(r[31] or 0))
        except (IndexError, TypeError, ValueError):
            continue
    return {t: sorted(v.items()) for t, v in by.items()}


def bench_od(st, k, bench=C.BENCH, repl=-3.0):
    bs = [(mn, bo, bd) for g, mn, bo, bd in st.values() if g < 0.6 * k or mn / g < 12]
    m = sum(x[0] for x in bs)
    rb = (sum(x[1] + x[2] for x in bs) + repl * bench) / (m + bench)
    ro = (sum(x[1] for x in bs) + repl / 2 * bench) / (m + bench)
    rd = (sum(x[2] for x in bs) + repl / 2 * bench) / (m + bench)
    return rb, ro, rd


def tavail(logs, n0=150.0):
    """(team, date) -> sum of weight x (D over bench - O over bench) of avail()'s sitters"""
    out = {}
    for t, gl in logs.items():
        st, v = {}, 0.0
        for k in range(len(gl) + 1):
            v = 0.0
            if k >= 3:
                last = gl[k - 1][1]
                rb, ro, rd = bench_od(st, k)
                for pid, (g, mn, bo, bd) in st.items():
                    if g < 0.6 * k or mn / g < 12 or pid in last:
                        continue
                    bpm = (bo + bd - n0) / (mn + n0)
                    if bpm - rb <= 0:
                        continue
                    o, d = (bo - n0 / 2) / (mn + n0), (bd - n0 / 2) / (mn + n0)
                    v += ((d - rd) - (o - ro)) * (mn / k) / 40
            if k < len(gl):
                out[(t, gl[k][0])] = v
                for pid, (mn, ob, db) in gl[k][1].items():
                    s = st.setdefault(pid, [0, 0.0, 0.0, 0.0])
                    s[0] += 1; s[1] += mn; s[2] += ob * mn; s[3] += db * mn
    return out


def tpre(logs, prev, n0=150.0, minmin=200.0):
    """pre_out()'s players (history: played for the team later this season, not yet), split the same way"""
    tot = defaultdict(lambda: [0.0, 0.0, 0.0, defaultdict(float)])
    ng = {t: len(gl) for t, gl in prev.items()}
    for t, gl in prev.items():
        for _, d in gl:
            for pid, (mn, ob, db) in d.items():
                z = tot[pid]; z[0] += mn; z[1] += ob * mn; z[2] += db * mn; z[3][t] += mn
    val = {}
    for pid, (m, bo, bd, by) in tot.items():
        if m >= minmin:
            main = max(by, key=by.get)
            val[pid] = ((bo + bd - n0) / (m + n0), (bo - n0 / 2) / (m + n0), (bd - n0 / 2) / (m + n0), m / max(1, ng[main]))
    out = {}
    for t, gl in logs.items():
        pre = {pid for _, d in gl for pid in d if pid in val}
        seen, st = set(), {}
        for k in range(len(gl)):
            rb, ro, rd = (-3.0, -1.5, -1.5)
            if k >= 3:
                rb, ro, rd = bench_od(st, k)
            now = gl[k][1]
            v = 0.0
            for pid in pre:
                if pid in seen or pid in now:
                    continue
                b, o, d, w = val[pid]
                if b - rb > 0:
                    v += ((d - rd) - (o - ro)) * w / 40
            out[(t, gl[k][0])] = v
            for pid, (mn, ob, db) in now.items():
                seen.add(pid)
                z = st.setdefault(pid, [0, 0.0, 0.0, 0.0]); z[0] += 1; z[1] += mn; z[2] += ob * mn; z[3] += db * mn
    return out


def main():
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    seasons = sorted({g['season'] for g in games})
    TA, TP = {}, {}
    for s in seasons:
        lg, pv = od_logs(s), od_logs(s - 1)
        TA.update(tavail(lg)); TP.update(tpre(lg, pv))
        print('split', s, flush=True)
    # the shipped walk, with each game's possessions kept
    W = C.Walk(F['params'], tprior, btname)
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    rows = []
    for s in sorted(by_s):
        gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))

        def col(g, x, tx, R):
            if g.get('hs') is None:
                return
            poss = R.poss(g['home'], g['away'])
            d = C.et_date(g['date'])
            bh, ba = btname.get(g['home']), btname.get(g['away'])
            a = TA.get((bh, d), 0.0) + TA.get((ba, d), 0.0)
            p = TP.get((bh, d), 0.0) + TP.get((ba, d), 0.0)
            tx = dict(tx, tinj=a * poss / 100, tinj2=(a + p) * poss / 100)
            rows.append((g, x, tx))
        C.season_walk(W, s, gs, d1s[s], avs.get(s), col)
    feats = list(F['feats'])
    out = {'prereg': 'scripts/cbb_tinj_research.py docstring'}
    D, Xm, y, TX0, ty, S, line, tline, d1 = C.matrices(rows, feats)
    day = np.array([g['date'][:10] for g, _, _ in D])
    p0 = C.walk_pred(TX0, ty, S, d1)
    ok = ~np.isnan(p0) & d1
    k1, k2 = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    lin = ~np.isnan(tline)
    out['base'] = {'tune': round(float(np.abs(p0[k1] - ty[k1]).mean()), 4), 'held': round(float(np.abs(p0[k2] - ty[k2]).mean()), 4),
                   'nz': {t: round(float(np.mean([tx[t] != 0 for _, _, tx in D])), 3) for t in ('tinj', 'tinj2')},
                   'sd': {t: round(float(np.std([tx[t] for _, _, tx in D])), 3) for t in ('tinj', 'tinj2')}}

    def stack(p, extra=None):
        X = np.c_[np.ones(len(p)), p - tline] if extra is None else np.c_[np.ones(len(p)), p - tline, extra]
        pr = np.full(len(p), np.nan)
        for s in range(C.SCORE0, C.LAST + 1):
            tr, te = (S < s) & ok & lin, (S == s) & ok & lin
            if tr.sum() < 500 or not te.any():
                continue
            b = np.linalg.lstsq(X[tr], (ty - tline)[tr], rcond=None)[0]
            pr[te] = tline[te] + X[te] @ b
        return pr
    s0 = stack(p0)
    tt = []
    for t in ('tinj', 'tinj2'):
        _, _, _, TX, _, _, _, _, _ = C.matrices(rows, feats, C.TFEATS + [t])
        p = C.walk_pred(TX, ty, S, d1)
        r = {'coef': round(float(np.linalg.lstsq(TX[ok], ty[ok], rcond=None)[0][-1]), 4)}
        for nm, k in (('tune', k1), ('held', k2), ('tuneLined', k1 & lin), ('heldLined', k2 & lin)):
            e, e0 = np.abs(p[k] - ty[k]), np.abs(p0[k] - ty[k])
            pr = H.paired(e, e0, cluster=day[k])
            r[nm] = {'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4), 't': round(pr['t'], 2)}
        st = stack(p0, np.array([tx[t] for _, _, tx in D]))
        for nm, k in (('closeTune', k1 & lin & ~np.isnan(st)), ('closeHeld', k2 & lin & ~np.isnan(st))):
            pr = H.paired((st[k] - ty[k]) ** 2, (s0[k] - ty[k]) ** 2, cluster=day[k])
            r[nm] = {'dSE': round(float(pr['d']), 4), 't': round(pr['t'], 2)}
        r['pass'] = r['tune']['t'] <= -1.5 and r['held']['d'] <= 0 and r['closeHeld']['dSE'] <= 0
        out[t] = r
        tt.append(r['tune']['t'])
        print(t, json.dumps(r), flush=True)
    # Holm over the two on the tune t (one-sided normal)
    from math import erf, sqrt
    ps = sorted((0.5 * (1 + erf(t / sqrt(2))), n) for t, n in zip(tt, ('tinj', 'tinj2')))
    for i, (p, n) in enumerate(ps):
        out[n]['holmP'] = round(min(1.0, p * (len(ps) - i)), 4)
        out[n]['pass'] = out[n]['pass'] and out[n]['holmP'] < 0.05
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: out[k].get('pass') for k in ('tinj', 'tinj2')}))


if __name__ == '__main__':
    main()
