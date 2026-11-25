#!/usr/bin/env python3
"""(e2) CFB pSV/60 on neutral plays (0.10 <= wp_before <= 0.90). QB points over replacement a play, opponent-adjusted as
scripts/cfb_season_value.py (same play filter, duplicate guard, K_DEF, REPL), from the cfbfastR release parquets
(scripts/.cache/cfb/fastr/pbp_<y>.parquet, 2017-25; no 2026, no CFBD). Raw arm = the same recompute on all plays.
Scored on the round-1 QB block (../../cfb/qb_team.py): pSV/60 x n+1 QB exposure -> n+1 team offense, LOSO slope.
    python3 cfb_neutral.py  -> cfb_neutral.json"""
import json, math, os, sys
from collections import Counter, defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cfb'))
import cfb_season_value as C
FASTR = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'fastr')
SEAS = list(range(2017, 2026)); LO, HI, MIN = .10, .90, 20
OUTC = os.path.join(FASTR, 'qb_neutral.json')


def plays(path):
    """cfb_season_value.plays() with wp_before carried (QB dropbacks only matter here)"""
    import pyarrow.parquet as pq
    cols = C.COLS + ['wp_before']
    have = set(pq.ParquetFile(path).schema_arrow.names)
    t = pq.read_table(path, columns=[c for c in cols if c in have]).to_pydict()
    out, key = [], []
    nn, sid = C.nn, C.sid
    for i in range(len(t['game_id'])):
        g = lambda k: nn(t[k][i]) if k in t else None  # noqa: E731
        if g('season_type') not in ('regular', 'postseason') or g('EPA') is None: continue
        if 'fbs' not in (g('home_team_division'), g('away_team_division')): continue
        db = g('pass') == 1
        if not db and g('rush') != 1: continue
        qb = None
        for k in ('completion', 'incompletion', 'sack_taken', 'interception_thrown'):
            if sid(g(f'{k}_player_id')): qb = sid(g(f'{k}_player_id')); break
        ru = sid(g('rush_player_id')) if not db else None
        wp = g('wp_before')
        out.append((g('game_id'), g('pos_team'), g('def_pos_team'), int(db), float(g('EPA')), qb if db else None, ru, g('position_rush'),
                    wp is not None and LO <= wp <= HI))
        key.append((g('period'), g('play_text')))
    n, u = Counter((r[0], r[1]) for r in out), defaultdict(set)
    for r, k in zip(out, key): u[(r[0], r[1])].add(k)
    dup = {sk for sk, c in n.items() if c > C.DUP_N or len(u[sk]) < (1 - C.DUP_SHARE) * c}
    seen, keep = set(), []
    for r, k in zip(out, key):
        if (r[0], r[1]) in dup:
            if (r[0], r[1]) + k in seen: continue
            seen.add((r[0], r[1]) + k)
        keep.append(r)
    return keep


def season(y):
    P = plays(os.path.join(FASTR, f'pbp_{y}.parquet'))
    pc = defaultdict(Counter)
    for gid, ot, dt, db, epa, qb, ru, rup, neu in P:
        if qb: pc[qb]['QB'] += 1
        if ru and rup: pc[ru][rup] += 1
    POS = {i: c.most_common(1)[0][0] for i, c in pc.items()}
    A = defaultdict(lambda: [0.0, 0])
    for gid, ot, dt, db, epa, *_ in P:
        for k in (('d', dt, db), ('dg', gid, dt, db), ('l', db)): A[k][0] += epa; A[k][1] += 1
    def rel(t, gid, k):
        s, n = A[('d', t, k)]; sg, ng = A[('dg', gid, t, k)]; m = A[('l', k)][0] / A[('l', k)][1]
        return ((s - sg) - m * (n - ng)) / (n - ng + C.K_DEF)
    V = defaultdict(lambda: [0.0, 0, 0.0, 0])
    for gid, ot, dt, db, epa, qb, ru, rup, neu in P:
        for i in {x for x in ((qb if db else None), ru) if x}:
            if POS.get(i) != 'QB': continue
            par = epa - rel(dt, gid, db) - C.REPL['QB']
            v = V[i]; v[0] += par; v[1] += 1
            if neu: v[2] += par; v[3] += 1
    return {i: v for i, v in V.items() if v[1] >= 100}


if __name__ == '__main__':
    if not os.path.exists(OUTC):
        D = {}
        for y in SEAS:
            D[y] = season(y); print('season', y, len(D[y]), 'QBs 100+', 'neutral share', round(sum(v[3] for v in D[y].values()) / sum(v[1] for v in D[y].values()), 3), flush=True)
        json.dump({str(y): v for y, v in D.items()}, open(OUTC, 'w'))
    D = {int(y): v for y, v in json.load(open(OUTC)).items()}
    import qb_team as Q
    tot = lambda y, i, neu: None if i not in D.get(y, {}) else ((D[y][i][2] / D[y][i][3] * D[y][i][1]) if (neu and D[y][i][3] >= MIN) else D[y][i][0])
    MU = {y: sum(v[0] for v in D[y].values()) / sum(v[1] for v in D[y].values()) for y in D}
    def psv(neu):
        def f(y, pid):
            m = Q.svq.get((y, pid))
            if not m or str(m['id']) not in D.get(y, {}): return None
            Pp = S = 0.0
            for k, w in enumerate((1, .7, .5)):
                T = tot(y - k, str(m['id']), neu)
                if T is not None: Pp += w * T; S += w * D[y - k][str(m['id'])][1]
            mu = np.mean([MU[x] for x in D if x <= y])
            return 60 * (Pp + 650 * mu) / (S + 650)
        return f
    def sv60(y, pid):
        m = Q.svq.get((y, pid)); i = str(m['id']) if m else None
        return None if not i or i not in D.get(y, {}) else 60 * D[y][i][0] / D[y][i][1]
    res = {}
    ob, sdb, spb = Q.qb_score(psv(False), 'psv60 raw (recomputed)', sv60)
    oc, sdc, spc = Q.qb_score(psv(True), 'psv60 neutral', sv60)
    import harness as H
    res = dict(base=ob, cand=oc, target='predict team (QB block, held out)', **H.paired(spb, spc), describeSide=H.paired(sdb, sdc))
    print(json.dumps(res, indent=1, default=str))
    json.dump(res, open(os.path.join(HERE, 'cfb_neutral.json'), 'w'), indent=1, default=str)
