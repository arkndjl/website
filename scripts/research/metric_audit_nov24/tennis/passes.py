#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Tennis metric audit (Nov 24 2026): walk-forward passes of the live model with a Dec 31 snapshot of every metric.

    python3 passes.py full    # every row -> snapshots + scored matches (describe in-sample, predict)
    python3 passes.py half    # half A rows only -> snapshots; half B matches scored (describe held out)
Lockbox: rows after 20261110 are never read (the export used ends Oct 26 2026). Output: scripts/.cache/tennis/audit_nov24.
"""
import csv, datetime as dt, gzip, json, math, os, pickle, sys, time, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCRIPTS)
import tennis_model as M  # noqa: E402
from tennis_data import is_qual  # noqa: E402

LOCK = 20261110
SRC = '/mnt/project-files/tennis'
OUT = os.path.join(SCRIPTS, '.cache', 'tennis', 'audit_nov24')
RANKD = os.path.join(OUT, 'sack', 'sackmann')
LW = {'S': 0.5, 'C': 0.85, 'Q': 0.85, 'D': 0.85}          # D1 / P2 level weights (qualifying rows carry lv Q? see lvw)


def lvw(lv, rd):
    if lv == 'S': return 0.5
    if lv in ('C', 'D') or is_qual(rd): return 0.85
    return 1.0


def _i(x):
    try: return int(float(x))
    except (TypeError, ValueError): return None


def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return None


def load_rows():
    rows = []
    with gzip.open(os.path.join(SRC, 'matches.csv.gz'), 'rt') as fh:
        rd = csv.reader(fh); next(rd)
        for x in rd:
            d = int(x[0])
            if d > LOCK: continue
            ws = [_i(v) for v in x[11:20]]; ls = [_i(v) for v in x[20:29]]
            ws = ws if all(v is not None for v in ws) else None
            ls = ls if all(v is not None for v in ls) else None
            rows.append([d, x[1], x[2], x[3], x[4], _i(x[5]) or 3, x[6], x[7], x[8], x[9], ws, ls,
                         _i(x[29]), _i(x[30]), _f(x[31]), _f(x[32])])
    with gzip.open(os.path.join(SRC, 'players.json.gz'), 'rt') as fh:
        players = json.load(fh)
    return rows, players


def half_of(r):
    return zlib.crc32(f'{r[0]}|{r[6]}|{r[7]}|{r[8]}|{r[4]}'.encode()) & 1   # 0 = A, 1 = B


def scorable(r):
    return r[2] in M.TOUR_LV and not is_qual(r[4]) and not M.games(r[9])[2]


def snapshot(m, e538, ss, year, P):
    day = (dt.date(year, 12, 31) - M.DAY0).days
    d0 = (dt.date(year, 1, 1) - M.DAY0).days
    out = {}
    for tour in ('atp', 'wta'):
        act = [p for p, d in m.last.items() if p[0] == tour[0] and day - d <= 183 and m.nm.get(p, 0) >= 15]
        if len(act) < 50: continue
        ref = m.set_ref(tour, act, day)
        top = sorted(act, key=lambda p: -m.elo[p][0])[:50]
        ref_pa = sum(m.ppa(p, day) for p in top) / len(top)
        mixc = ss.get(('mix', tour), {s: 1 for s in M.SURFS}); tot = sum(mixc.values()) or 1
        mix = {s: mixc.get(s, 0) / tot for s in M.SURFS}
        wa, wb, wg = (P.get(k + '0', P[k]) for k in 'ABG')
        for p, s in ss.items():
            if not isinstance(p, str) or p[0] != tour[0] or s['m'] < 5 or p not in m.elo: continue
            rp = m.rpa(p, day, 0)          # raw rate (the pre-change rPA)
            pipe = 0.0
            ark = arkpa = 0.0
            for sf in M.SURFS:
                if not mix[sf]: continue
                _, pe, pp, gx, _ = m.predict(p, ref, tour, sf, day, 3, match=False)
                pipe += mix[sf] * M.sig(M.logit(m.predict(p, ref, tour, sf, day, 3, match=False)[0]))
                ark += mix[sf] * M.sig(wa * M.logit(pe) + wb * M.logit(pp) + wg * gx)
                arkpa += mix[sf] * M.sig(P['A'] * M.logit(pe) + P['B'] * M.logit(pp) + P['G'] * gx
                                         + P['CP'] * (m.ppa(p, day) - ref_pa) / 10)
            q = m._wq(p, day)
            pq = [x for x in m.pq.get(p, []) if x[0] >= day - 364]
            x = m._pt(p, day)
            st = s['st']
            out[p] = {
                'm': s['m'], 'tour': tour,
                'ark': M.logit(min(max(ark, 1e-4), 1 - 1e-4)), 'ark_pa': M.logit(min(max(arkpa, 1e-4), 1 - 1e-4)),
                'elo': m.elo[p][0], 'elo538': e538.get(p, [1500, 0])[0], 'pts': x[0] + x[2],
                'ppa': m.ppa(p, day), 'rpa': rp,
                'rpa_k': 100 * sum(z[1] for z in pq) / (sum(z[2] for z in pq) + 300),
                'war': sum(v for _, v, _ in q), 'sv': sum(v for d, v, _ in q if d >= d0),
                'war_l': None,
                'war_rate': m.war_rate(p, day), 'pipe_war': m.war(p, day), 'pipe_rpa': m.rpa(p, day),
                'pipe_ark': M.logit(min(max(pipe, 1e-4), 1 - 1e-4)),
                'wins': s['w'], 'wl': 2 * s['w'] - s['m'], 'winpct': (s['w'] + 2) / (s['m'] + 4),
                'gwp': s['gw'] / (s['gw'] + s['gl']) if s['gw'] + s['gl'] else 0.5,
                'spw': (st[1] + 30) / (st[0] + 50) if st[0] else None,
                'rpw': (st[3] + 20) / (st[2] + 50) if st[2] else None,
            }
            o = out[p]
            o['dr'] = (o['rpw'] / (1 - o['spw'])) if o['spw'] and o['rpw'] else None
            o['sv_l'] = s['svl']
    return out


def run(mode):
    rows, players = load_rows()
    P = dict(M.DEFAULT, **json.load(open(M.FIT))['params'])
    m = M.Model(P); m.set_bios(players)
    M.mark_two_week(rows)
    e538 = {}
    snaps, matches = {}, []
    cur, ss = None, {}
    t0 = time.time()
    for i, r in enumerate(rows):
        y = r[0] // 10000
        if cur is not None and y != cur:
            if cur >= 2010:
                snaps[cur] = snapshot(m, e538, ss, cur, P)
                print(mode, cur, len(snaps[cur]), round(time.time() - t0), 's', flush=True)
            ss = {}
        cur = y
        h = half_of(r)
        if y >= 2010 and scorable(r) and (mode == 'full' or h == 1):
            matches.append((y, r[1], r[6], r[7], r[8]))
        if mode == 'half' and h == 1: continue
        if y >= 2010:
            gw, gl, ret = M.games(r[9])
            if r[2] in M.TOUR_LV and not is_qual(r[4]):
                mx = ss.setdefault(('mix', r[1]), {s: 0 for s in M.SURFS}); mx[r[3]] += 1
            for pid, won, a, b in ((r[7], 1, r[10], r[11]), (r[8], 0, r[11], r[10])):
                s = ss.setdefault(pid, {'m': 0, 'w': 0, 'gw': 0, 'gl': 0, 'st': [0, 0, 0, 0], 'svl': 0.0})
                s['m'] += 1; s['w'] += won
                s['gw'] += gw if won else gl; s['gl'] += gl if won else gw
                if a and b and a[0] and b[0]:
                    s['st'][0] += a[0]; s['st'][1] += a[2] + a[3]; s['st'][2] += b[0]; s['st'][3] += b[0] - b[2] - b[3]
        # WAR credit with level weights: replicate value_update's credit before the update
        day = M.dnum(r[0], r[4], r[2], r[6])
        sw = P['SW']; rr = P['REPL_' + r[1].upper()]
        lw = lvw(r[2], r[4])
        for pid, won, opp in ((r[7], 1, r[8]), (r[8], 0, r[7])):
            e = m._e(opp)
            ro = (1 - sw) * e[0] + sw * e[2][r[3]][0]
            p = 1 / (1 + 10 ** ((ro - rr) / 400))
            if r[5] == 5: p = M.bo5(p)
            wl_ = m.wl_ = getattr(m, 'wl_', {})
            wl_.setdefault(pid, []).append((day, (won - p) * lw))
            if y >= 2010 and pid in ss: ss[pid]['svl'] += (won - p) * lw
        m.update(r)
        # 538 / Tennis Abstract style Elo: overall only, every level, no level or retirement discount
        a, b = e538.setdefault(r[7], [1500.0, 0]), e538.setdefault(r[8], [1500.0, 0])
        pe = 1 / (1 + 10 ** ((b[0] - a[0]) / 400))
        ka, kb = 250 / (a[1] + 5) ** 0.4, 250 / (b[1] + 5) ** 0.4
        a[0] += ka * (1 - pe); b[0] -= kb * (1 - pe); a[1] += 1; b[1] += 1
        if (i & 0xFFFFF) == 0:
            # trim level-weighted WAR history to 52 weeks
            for k, q in m.wl_.items():
                m.wl_[k] = [z for z in q if z[0] >= day - 400]
    if cur is not None and cur >= 2010 and cur <= 2026:
        snaps[cur] = snapshot(m, e538, ss, cur, P)
    os.makedirs(OUT, exist_ok=True)
    pickle.dump({'snaps': snaps, 'matches': matches}, open(os.path.join(OUT, mode + '.pkl'), 'wb'))
    print('done', mode, round(time.time() - t0), 's')


# war_l from the parallel deque (replaces the placeholder in snapshot)
_snap = snapshot


def snapshot(m, e538, ss, year, P):  # noqa: F811
    out = _snap(m, e538, ss, year, P)
    day = (dt.date(year, 12, 31) - M.DAY0).days
    for p, o in out.items():
        o['war_l'] = sum(v for d, v in getattr(m, 'wl_', {}).get(p, []) if d >= day - 364)
    return out


if __name__ == '__main__':
    run(sys.argv[1])
