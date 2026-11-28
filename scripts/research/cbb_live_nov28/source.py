#!/usr/bin/env python3
"""Test 1 (prereg.md): which season line the live board should read when Barttorvik's file covers only part of the
games in the logs. His conference-only file stands in for that file; the target is the grade on his full-season line.

    python3 scripts/research/cbb_live_nov28/fetch.py && python3 scripts/cbb_careers_kit.py
    python3 scripts/research/cbb_live_nov28/source.py      # -> source.json
"""
import csv, json, math, os, sys
from collections import Counter, defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_data as D
import cbb_fit as F
import cbb_live as L
import cbb_live_backtest as B
import harness as H

SEASONS = list(range(2010, 2027))
C = L.C


def load_conf(y):
    out = {}
    with open(os.path.join(D.CACHE, 'bt', f'conf{y}.csv'), newline='', encoding='utf-8', errors='replace') as f:
        for row in csv.reader(f):
            if len(row) < 66: continue
            r = {k: (row[i] if k in D.BT_TEXT else D.num(row[i])) if i < len(row) else None for i, k in enumerate(D.BT_COLS)}
            out[str(r['pid']).split('.')[0]] = r
    return out


def main():
    fit = json.load(open(F.OUT))
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    F.horizon_fv(careers); F.set_context(careers)
    by_pid = {str(c['pid']): c for c in careers}
    # recon pieces per season (cbb_live_backtest.fit_recon), so each season's rebuild is fit with that season held out
    XYW, data = {}, {}
    for y in SEASONS:
        by_p, tg = B.load_season(y)
        off = {r['pid']: r for r in D.load_bt(y)}
        X, Y, W = [], {k: [] for k in L.RECON}, []
        for pid, rs in by_p.items():
            o = off.get(pid)
            if not o or (o['mp'] or 0) * (o['gp'] or 0) < 40 or any(o[k] is None for k in L.RECON): continue
            a = L.summed(rs, len(tg.get(rs[-1][C['team']], [])) or 1)
            X.append(L.rx(a)); W.append(min(1000.0, (o['mp'] or 0) * (o['gp'] or 0)))
            for k in L.RECON: Y[k].append(o[k])
        XYW[y] = (np.array(X, float), {k: np.array(v) for k, v in Y.items()}, np.sqrt(np.array(W)))
        data[y] = (by_p, tg, off)
        print(y, len(X), flush=True)

    def recon_wo(y):
        ys = [s for s in SEASONS if s != y]
        X = np.vstack([XYW[s][0] for s in ys]); W = np.concatenate([XYW[s][2] for s in ys])
        out = {}
        for k in L.RECON:
            Yk = np.concatenate([XYW[s][1][k] for s in ys])
            out[k] = {'w': [float(v) for v in np.linalg.lstsq(X * W[:, None], Yk * W, rcond=None)[0]]}
        return out

    rows = []
    for y in SEASONS:
        by_p, tg, off = data[y]
        conf_off = load_conf(y)
        recon = recon_wo(y)
        tconf = defaultdict(Counter)
        for r in off.values(): tconf[r['team']][r['conf']] += 1
        tconf = {t: c.most_common(1)[0][0] for t, c in tconf.items()}
        # each team's conference games (date, game id), for min_per on the conference part
        tcg = defaultdict(set)
        for pid, rs in by_p.items():
            for g in rs:
                if tconf.get(g[C['opp']]) is not None and tconf.get(g[C['opp']]) == tconf.get(g[C['team']]):
                    tcg[g[C['team']]].add((g[C['date']], g[C['muid']]))
        n0 = len(rows)
        for pid, rs in by_p.items():
            c, o, oc = by_pid.get(pid), off.get(pid), conf_off.get(pid)
            if not c or not o or not oc or o['team'] != rs[-1][C['team']] or oc['team'] != o['team']: continue
            if any(o[k] is None for k in L.RECON) or any(oc[k] is None for k in L.RECON): continue
            i = next((j for j, s in enumerate(c['seasons']) if s['year'] == y), None)
            if i is None: continue
            team = o['team']
            S = [g for g in rs if tconf.get(g[C['opp']]) == tconf.get(team)]
            gpS = sum(1 for g in S if (g[C['min']] or 0) > 0)
            gpA = sum(1 for g in rs if (g[C['min']] or 0) > 0)
            if not S or gpS != int(oc['gp'] or 0) or gpA != int(o['gp'] or 0) or gpS == gpA: continue
            aA = L.summed(rs, len(tg.get(team, [])) or 1)
            if aA['mp'] * aA['gp'] < 40: continue
            aS = L.summed(S, len(tcg.get(team, ())) or 1)
            meta = c['seasons'][i]
            srow = {k: meta.get(k) for k in ('year', 'team', 'conf', 'yr', 'hti', 'role', 'rec')}
            pre_cc = dict(c, seasons=c['seasons'][:i] + [srow])
            RA = L.line(aA, recon, meta); RS = L.line(aS, recon, meta)
            Bl = dict(RA)
            for k in L.RECON: Bl[k] = RA[k] + (oc[k] - RS[k])
            # his partial file as it stands (stale: the conference games only), for reference
            Ol = dict(RA)
            for k in L.RECON: Ol[k] = oc[k]
            T = {k: o.get(k) for k in L.KEEP}
            rows.append({'y': y, 'pid': pid, 'n': aA['mp'] * aA['gp'], 'share': gpS / gpA,
                         'bpm': (o['bpm'], RA['bpm'], Bl['bpm'], oc['bpm']),
                         'f': [F.features(L.next_career(pre_cc, ln), i + 1) for ln in (T, RA, Bl, Ol)]})
        print(f'{y}: {len(rows) - n0} players', flush=True)

    E = [L.score_many([r['f'][j] for r in rows], fit)[0] for j in range(4)]
    T, A, Bv, O = E
    yr = np.array([r['y'] for r in rows]); pid = np.array([f"{r['y']}|{r['pid']}" for r in rows])
    n = np.array([r['n'] for r in rows]); bp = np.array([r['bpm'] for r in rows], float)
    eA, eB, eO = (A - T) ** 2, (Bv - T) ** 2, (O - T) ** 2
    t = H.paired(eB, eA, np.array([r['pid'] for r in rows]))
    better = sum(1 for y in SEASONS if eB[yr == y].mean() < eA[yr == y].mean())
    wr = lambda e: float(math.sqrt((n * e).sum() / n.sum()))
    res = {'players': len(rows), 'seasons': f'{SEASONS[0] - 1}-{str(SEASONS[0])[2:]} to {SEASONS[-1] - 1}-{str(SEASONS[-1])[2:]}',
           'gradeRmse': {'rebuilt': round(math.sqrt(eA.mean()), 4), 'anchored': round(math.sqrt(eB.mean()), 4), 'his partial file': round(math.sqrt(eO.mean()), 4)},
           'bpmRmseMinW': {'rebuilt': round(wr((bp[:, 1] - bp[:, 0]) ** 2), 4), 'anchored': round(wr((bp[:, 2] - bp[:, 0]) ** 2), 4),
                           'his partial file': round(wr((bp[:, 3] - bp[:, 0]) ** 2), 4)},
           'anchoredVsRebuilt': {'d': round(t['d'], 5), 't': round(t['t'], 2), 'seasonsBetter': better, 'of': len(SEASONS)},
           'byShare': []}
    for lo, hi in ((0, .5), (.5, .65), (.65, .8), (.8, .9), (.9, 1)):
        m = (np.array([r['share'] for r in rows]) > lo) & (np.array([r['share'] for r in rows]) <= hi)
        if m.any():
            tt = H.paired(eB[m], eA[m], np.array([r['pid'] for r in rows])[m])
            nm = n[m]
            wrm = lambda e: float(math.sqrt((nm * e).sum() / nm.sum()))
            res['byShare'].append({'share': f'{lo}-{hi}', 'players': int(m.sum()), 'rebuilt': round(math.sqrt(eA[m].mean()), 4),
                                   'anchored': round(math.sqrt(eB[m].mean()), 4), 't': round(tt['t'], 2),
                                   'seasonsBetter': sum(1 for y in SEASONS if (m & (yr == y)).any() and eB[m & (yr == y)].mean() < eA[m & (yr == y)].mean()),
                                   'bpmRebuilt': round(wrm((bp[m, 1] - bp[m, 0]) ** 2), 3), 'bpmAnchored': round(wrm((bp[m, 2] - bp[m, 0]) ** 2), 3)})
    for lo, hi in ((40, 200), (200, 500), (500, 1e9)):
        m = (n >= lo) & (n < hi)
        tt = H.paired(eB[m], eA[m], np.array([r['pid'] for r in rows])[m])
        res.setdefault('byMinutes', []).append({'minutes': f'{lo}-{int(hi) if hi < 1e9 else "up"}', 'players': int(m.sum()),
                                                'rebuilt': round(math.sqrt(eA[m].mean()), 4), 'anchored': round(math.sqrt(eB[m].mean()), 4), 't': round(tt['t'], 2)})
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(HERE, 'source.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
