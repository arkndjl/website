#!/usr/bin/env python3
"""Test 2 (prereg.md): rXPM in place of BPM in the in-season line the "now" grade reads, the FV model unchanged.

cbb_live_backtest's design on 2009-10 to 2018-19 (careers with an outcome): each player's line rebuilt at the nine
checkpoints, his games projected to a full season (the board's reading, data/cbb_live_fit.json "now"). Arm BPM = the
line as the board reads it; arm XPM = each side's BPM plus his team's minutes-weighted mean of (side GBPM - side BPM)
over every line to date at that team (scripts/cbb_xpm.py rxpm_shift on lines to date), BPM = O + D. The in-season
blend (1 - w) pre + w now, w = n / (n + k); k per arm and group picked with the season held out on realized rung
deviance, scored on the held-out season (cbb_live_backtest's kRealized arithmetic).

    python3 scripts/research/cbb_live_nov28/xpm_live.py      # -> xpm_live.json
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_data as D
import cbb_fit as F
import cbb_live as L
import cbb_live_backtest as B
import harness as H

SEASONS = range(2010, 2020)
C = L.C


def main():
    fit = json.load(open(F.OUT)); lf = json.load(open(L.LIVE_FIT))
    recon = lf['recon']
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    F.horizon_fv(careers); F.set_context(careers)
    by_pid = {str(c['pid']): c for c in careers}
    del careers
    rows = []      # per (player season, checkpoint): y, pid, new, n, j, out, Ppre, Pbpm, Pxpm, e...
    pre = {}
    for y in SEASONS:
        by_p, tg = B.load_season(y)
        full_games = np.median([len(v) for v in tg.values() if len(v) >= 10])
        cuts = [f'{y - 1 if m >= 11 else y}{m:02d}{d:02d}' for m, d in B.CHECK]
        info = {}
        for pid, rs in by_p.items():
            c = by_pid.get(pid)
            if not c or c['nba']['fvh'] is None: continue
            i = next((j for j, s in enumerate(c['seasons']) if s['year'] == y), None)
            if i is None: continue
            meta = c['seasons'][i]
            srow = {k: meta.get(k) for k in ('year', 'team', 'conf', 'yr', 'hti', 'role', 'rec')}
            pre_cc = dict(c, seasons=c['seasons'][:i] + [srow])
            info[pid] = (pre_cc, i, meta, c['nba']['fvh'])
        pids = list(info)
        e0, _, P0 = L.score_many([F.features(info[p][0], info[p][1]) for p in pids], fit, ladder=True)
        for k, p in enumerate(pids): pre[(y, p)] = (e0[k], P0[k])
        for j, cut in enumerate(cuts):
            lines = {}
            shift = defaultdict(lambda: [0.0, 0.0, 0.0])
            for pid, rs in by_p.items():
                sub, tgd = B.to_date(rs, tg, cut)
                if not sub: continue
                a = L.summed(sub, max(1, tgd))
                n = a['mp'] * a['gp']
                if n <= 0: continue
                meta = info[pid][2] if pid in info else {}
                ln = L.line(a, recon, meta)
                q = shift[sub[-1][C['team']]]
                q[0] += n * (a['ogb'] - ln['obpm']); q[1] += n * (a['dgb'] - ln['dbpm']); q[2] += n
                if pid in info: lines[pid] = (ln, a, tgd, sub[-1][C['team']])
            fb, fx, meta_rows = [], [], []
            for pid, (ln, a, tgd, team) in lines.items():
                pre_cc, i, meta, out = info[pid]
                q = shift[team]
                lx = dict(ln); lx['obpm'] = ln['obpm'] + q[0] / q[2]; lx['dbpm'] = ln['dbpm'] + q[1] / q[2]; lx['bpm'] = lx['obpm'] + lx['dbpm']
                gp_full = a['gp'] * full_games / max(1, tgd) if tgd < full_games else None
                fb.append(F.features(L.next_career(pre_cc, ln, gp_full), i + 1))
                fx.append(F.features(L.next_career(pre_cc, lx, gp_full), i + 1))
                meta_rows.append((pid, a['mp'] * a['gp'], out, not pre_cc['seasons'][:i]))
            if not fb: continue
            eb, _, Pb = L.score_many(fb, fit, ladder=True)
            ex, _, Px = L.score_many(fx, fit, ladder=True)
            for k, (pid, n, out, new) in enumerate(meta_rows):
                rows.append((y, pid, new, n, j, out, eb[k], ex[k], Pb[k], Px[k]))
        print(y, len(rows), flush=True)

    Y = np.array([r[0] for r in rows]); PID = np.array([f'{r[0]}|{r[1]}' for r in rows]); NEW = np.array([r[2] for r in rows])
    N = np.array([r[3] for r in rows], float); J = np.array([r[4] for r in rows]); OUT = np.array([r[5] for r in rows], float)
    Ppre = np.array([pre[(r[0], r[1])][1] for r in rows]); Epre = np.array([pre[(r[0], r[1])][0] for r in rows])
    arms = {'bpm': (np.array([r[6] for r in rows]), np.array([r[8] for r in rows])), 'xpm': (np.array([r[7] for r in rows]), np.array([r[9] for r in rows]))}
    kgr = [k for k in B.KGRID if k <= 3000]
    res = {'seasons': '2009-10 to 2018-19', 'rows': len(rows), 'groups': {}}
    loss = {a: np.zeros(len(rows)) for a in arms}
    for grp, gm in (('newcomer', NEW), ('returner', ~NEW)):
        g = {}
        for a, (E, P) in arms.items():
            def rdev(k, mask):
                w = (N[mask] / (N[mask] + k))[:, None]
                return F.row_dev((1 - w) * Ppre[mask] + w * P[mask], OUT[mask]).sum(1)
            ks = []
            for y in SEASONS:
                tr, te = gm & (Y != y), gm & (Y == y)
                k = min(kgr, key=lambda k: rdev(k, tr).sum())
                ks.append(k); loss[a][te] = rdev(k, te)
            kp = lf['k'][grp]
            g[a] = {'kFolds': [int(min(ks)), int(np.median(ks)), int(max(ks))], 'devOOS': round(float(loss[a][gm].mean() * 1e4), 4),
                    'devAtBoardK': round(float(rdev(kp, gm).mean() * 1e4), 4)}
        t = H.paired(loss['xpm'][gm], loss['bpm'][gm], PID[gm])
        better = sum(1 for y in SEASONS if loss['xpm'][gm & (Y == y)].sum() < loss['bpm'][gm & (Y == y)].sum())
        g['xpmVsBpm'] = {'t': round(t['t'], 2), 'seasonsBetter': better, 'of': len(SEASONS)}
        res['groups'][grp] = g
        print(grp, json.dumps(g), flush=True)
    t = H.paired(loss['xpm'], loss['bpm'], PID)
    better = sum(1 for y in SEASONS if loss['xpm'][Y == y].sum() < loss['bpm'][Y == y].sum())
    res['all'] = {'devBpm': round(float(loss['bpm'].mean() * 1e4), 4), 'devXpm': round(float(loss['xpm'].mean() * 1e4), 4),
                  't': round(t['t'], 2), 'seasonsBetter': better, 'of': len(SEASONS)}
    res['pass'] = bool(t['t'] <= -2 and better >= 6)
    # secondary: draft AUC (realized FV >= 30) of the blend at the board's k, by checkpoint
    res['aucByDate'] = []
    for j, (m, d) in enumerate(B.CHECK):
        mk = J == j
        row = {'date': f'{m}/{d}', 'players': int(mk.sum())}
        for a, (E, P) in arms.items():
            kk = np.where(NEW, lf['k']['newcomer'], lf['k']['returner'])
            w = N / (N + kk)
            bl = (1 - w) * Epre + w * E
            row[a] = round(F.auc(bl[mk], OUT[mk] >= 30), 4)
        res['aucByDate'].append(row)
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(HERE, 'xpm_live.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
