# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""SV (season value) for every past season, for the all-time season lists -> scripts/data/sv_hist.json.gz.

    python3 scripts/sv_history.py nfl        # nflverse play-by-play 1999 on (snap counts, so defenders, 2013 on)
    python3 scripts/sv_history.py cfb        # cfbfastR release 2014 on (QBs; skill players 2025 on, see below)

Same SV as the season tabs (scripts/nfl_qb.py, scripts/nfl_season_value.py, scripts/cfb_season_value.py): points over
replacement a game, opponent-adjusted where the split-half test kept it (NFL QB, RB, WR, DL, DB; CFB QB, RB), weather for
NFL RBs. Era: the replacement line moves with the league each season, by that season's league EPA a play of the kind
(run / dropback) against 2016-25's (defenders: the league's credit a snap against 2016-25's), so a season is measured
against its own league, not today's. CFB receiving needs target ids on incompletions; the release has them on 84-89% of
dropbacks from 2025 but 65-74% before (incompletions missing, so EPA a target runs high), so CFB WR / TE / RB-target SV
starts in 2025 and CFB RBs before 2025 count runs only.
Rows: {y, id (gsis / ESPN), pfr (NFL), n, t, g (group), sv (a game), tot, gp}."""
import csv
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
OUT = os.path.join(ROOT, 'scripts', 'data', 'sv_hist.json.gz')
REF = range(2016, 2026)


def load():
    try:
        return json.load(gzip.open(OUT, 'rt'))
    except (OSError, ValueError):
        return {}


def save(D):
    with gzip.open(OUT, 'wt') as f:
        json.dump(D, f, separators=(',', ':'), allow_nan=False)


# ---------------------------------------------------------------- NFL
def nfl(years):
    import nfl_season_value as V
    from nfl_qb import get, f, REL, REPL as QREPL
    P = {}
    for r in csv.DictReader(open(get('players.csv', f'{REL}/players/players.csv', False), newline='', encoding='utf-8')):
        P[r['gsis_id']] = (r['display_name'], r['position'], r['pfr_id'])
    seas = {}
    for y in years:
        allp, off, dfc = V.plays(y, False)
        # QB plays (as nfl_qb.py: every dropback to the passer, his own runs; spikes out)
        qp = []
        with gzip.open(get(f'play_by_play_{y}.csv.gz', f'{REL}/pbp/play_by_play_{y}.csv.gz', False), 'rt', encoding='utf-8') as fh:
            rd = csv.reader(fh)
            h = next(rd); I = {k: i for i, k in enumerate(h)}
            for r in rd:
                g = lambda k: r[I[k]]  # noqa: E731
                if g('two_point_attempt') == '1' or g('season_type') not in ('REG', 'POST') or g('qb_spike') == '1':
                    continue
                db = g('qb_dropback') == '1'
                run = g('play_type') == 'run' and not db and g('qb_kneel') != '1'
                if not db and not run:
                    continue
                pid = g('id') if db else g('rusher_player_id')
                epa = f(g('qb_epa')) if db else f(g('epa'))
                if epa is None or not pid or pid == 'NA':
                    continue
                if not db and P.get(pid, ('', ''))[1] != 'QB':
                    continue
                qp.append((g('game_id'), pid, int(db), V.tm(g('defteam')), epa, V.tm(g('posteam'))))
        seas[y] = (allp, off, dfc, qp)
        print('nfl sv: read', y, len(allp), flush=True)
    L = {}
    for y, S in seas.items():
        s, n = [0.0, 0.0], [0, 0]
        for gid, ot, dt, k, e in S[0]:
            s[k] += e; n[k] += 1
        L[y] = [s[k] / n[k] for k in (0, 1)]
    ref = [sum(L[y][k] for y in REF if y in L) / max(1, sum(1 for y in REF if y in L)) for k in (0, 1)]
    rows, cred = [], {}
    for y, (allp, off, dfc, qp) in seas.items():
        sh = [L[y][k] - ref[k] for k in (0, 1)]
        A = defaultdict(lambda: [0.0, 0])
        for gid, ot, dt, k, e in allp:
            for key in (('d', dt, k), ('dg', gid, dt, k), ('o', ot, k), ('og', gid, ot, k), ('l', k)):
                A[key][0] += e; A[key][1] += 1

        def rel(side, t, gid, k):
            s, n = A[(side, t, k)]; sg, ng = A[(side + 'g', gid, t, k)]
            m = A[('l', k)][0] / A[('l', k)][1] if A[('l', k)][1] else 0.0
            return ((s - sg) - m * (n - ng)) / (n - ng + V.K_DEF)
        tmof = {}
        Q = defaultdict(lambda: [0.0, Counter()])
        for gid, pid, k, dt, e, ot in qp:
            a = e - rel('d', dt, gid, k)
            Q[pid][0] += a - (QREPL + sh[k]); Q[pid][1][gid] += 1; tmof[pid] = ot
        for pid, (par, gp) in Q.items():
            n = sum(gp.values())
            if n < 100:
                continue
            g10 = sum(1 for v in gp.values() if v >= 10) or 1
            rows.append(dict(y=y, id=pid, g='QB', sv=round(par / g10, 2), tot=round(par, 1), gp=g10, pl=n, t=tmof.get(pid)))
        grp = lambda pid: V.GROUP.get(P.get(pid, ('', ''))[1], '')  # noqa: E731
        X = defaultdict(lambda: [0.0, set(), 0])
        for gid, pid, k, dt, e, wx in off:
            g = grp(pid)
            if g not in ('RB', 'WR', 'TE'):
                continue
            a = e - (rel('d', dt, gid, k) if g in V.OPP else 0.0) - (V.wadj(k, *wx) if g in V.WEA else 0.0)
            X[pid][0] += a - (V.REPL[(g, k)] + sh[k]); X[pid][1].add(gid); X[pid][2] += 1
        for pid, (par, gs, n) in X.items():
            if n >= 50:
                rows.append(dict(y=y, id=pid, g=grp(pid), sv=round(par / len(gs), 2), tot=round(par, 1), gp=len(gs), pl=n))
        if y >= 2013:
            snaps, gms = defaultdict(int), defaultdict(set)
            by_pfr = {v[2]: k for k, v in P.items() if v[2]}
            for r in csv.DictReader(open(get(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv', False), newline='', encoding='utf-8')):
                gs = by_pfr.get(r['pfr_player_id'])
                if gs and (f(r['defense_snaps']) or 0) > 0:
                    snaps[gs] += int(f(r['defense_snaps'])); gms[gs].add(r['game_id'])
            C = defaultdict(float)
            for gid, W, ot, e in dfc:
                tw = sum(W.values())
                for pid, w in W.items():
                    g = grp(pid)
                    if g in ('DL', 'LB', 'DB'):
                        adj = (rel('o', ot, gid, 0) + rel('o', ot, gid, 1)) / 2 if g in V.OPP else 0.0
                        C[pid] += -(e - adj) * w / tw
            cred[y] = (sum(C.values()) / max(1, sum(snaps[p] for p in C)), C, snaps, gms)
    cref = sum(cred[y][0] for y in REF if y in cred) / max(1, sum(1 for y in REF if y in cred))
    for y, (c, C, snaps, gms) in cred.items():
        for pid, cr in C.items():
            g = V.GROUP.get(P.get(pid, ('', ''))[1], '')
            sn = snaps.get(pid, 0)
            if sn < 300:
                continue
            par = cr - V.REPL[g] * (c / cref) * sn
            rows.append(dict(y=y, id=pid, g=g, sv=round(par / len(gms[pid]), 2), tot=round(par, 1), gp=len(gms[pid]), pl=sn))
    for r in rows:
        n, _, pfr = P.get(r['id'], (None, None, None))
        r['n'], r['pfr'] = n, pfr or None
    return nfl_teams(rows)


def nfl_teams(rows):
    """team for each row (QBs carry theirs from the plays): the nflverse season roster's team"""
    from nfl_qb import get, REL, FR
    T = {}
    for y in sorted({r['y'] for r in rows if not r.get('t')}):
        for r in csv.DictReader(open(get(f'roster_{y}.csv', f'{REL}/rosters/roster_{y}.csv', False), newline='', encoding='utf-8')):
            T[(r['gsis_id'], y)] = OLD.get(r['team'], FR.get(r['team'], r['team']))
    for r in rows:
        r['t'] = OLD.get(r.get('t'), r.get('t')) or T.get((r['id'], r['y']))
    return rows


OLD = {'ARZ': 'ARI', 'BLT': 'BAL', 'CLV': 'CLE', 'HST': 'HOU', 'SL': 'LA'}     # nflverse's old roster codes


# ---------------------------------------------------------------- CFB
def cfb(years):
    import cfb_mirror
    import cfb_season_value as C
    rows = []
    for y in years:
        p = os.path.join(ROOT, 'scripts', '.cache', 'cfb', f'cfbfastr_pbp_{y}.parquet')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not os.path.exists(p):
            cfb_mirror.download(y, p)
        Pl, fbs, tid = C.plays(p)
        rec_ok = y >= 2025
        pc, nm = defaultdict(Counter), {}
        for gid, ot, dt, db, epa, qb, qbn, ru, rup, run, rec, recp, recn in Pl:
            if qb:
                pc[qb]['QB'] += 1; nm[qb] = (qbn, ot)
            if ru and rup:
                pc[ru][rup] += 1; nm[ru] = (run, ot)
            if rec and recp:
                pc[rec][recp] += 1; nm.setdefault(rec, (recn, ot))
        POS = {}
        for i, c in pc.items():
            q = c.most_common(1)[0][0]
            POS[i] = 'QB' if q == 'QB' else 'RB' if q in ('RB', 'FB') else q if q in ('WR', 'TE') else ''
        A = defaultdict(lambda: [0.0, 0])
        for gid, ot, dt, db, epa, *_ in Pl:
            for key in (('d', dt, db), ('dg', gid, dt, db), ('l', db)):
                A[key][0] += epa; A[key][1] += 1
        Ly = [A[('l', k)][0] / A[('l', k)][1] for k in (0, 1)]

        def rel(t, gid, k):
            s, n = A[('d', t, k)]; sg, ng = A[('dg', gid, t, k)]; m = Ly[k]
            return ((s - sg) - m * (n - ng)) / (n - ng + C.K_DEF)
        V_ = defaultdict(lambda: [0.0, Counter(), 0])
        for gid, ot, dt, db, epa, qb, qbn, ru, rup, run, rec, recp, recn in Pl:
            for i in {x for x in ((qb if db else None), ru, (rec if rec_ok else None)) if x}:
                g = POS.get(i)
                if g not in ('QB', 'RB', 'WR', 'TE') or (g in ('WR', 'TE') and not rec_ok):
                    continue
                a = epa - (rel(dt, gid, db) if g in C.OPP else 0.0)
                rp = C.REPL['QB'] if g == 'QB' else C.REPL[(g, db)]
                V_[i][0] += a - rp; V_[i][1][gid] += 1; V_[i][2] += 1
        rows.append(dict(y=y, lg=Ly))
        for i, (par, gp, n) in V_.items():
            g = POS[i]
            if nm.get(i, (0, 0))[1] not in fbs or n < (100 if g == 'QB' else 50):
                continue
            g10 = sum(1 for v in gp.values() if v >= (10 if g == 'QB' else 1)) or 1
            rows.append(dict(y=y, id=i, g=g, n=nm[i][0], t=nm[i][1], sv=par / g10, tot=par, gp=g10, pl=n))
        os.remove(p)
        print('cfb sv:', y, sum(1 for r in rows if r.get('y') == y), flush=True)
    # era: replacement moves with the league; CFB's REPL is set on 2025, so the shift is against 2025's league EPA a play
    ref = next((r['lg'] for r in rows if r.get('y') == 2025 and 'lg' in r), None)
    lg = {r['y']: r['lg'] for r in rows if 'lg' in r}
    out = []
    for r in rows:
        if 'lg' in r:
            continue
        if ref:
            # every play of the season moved by the shift of its kind; a QB's plays are mostly dropbacks, a RB's runs
            k = 1 if r['g'] in ('QB', 'WR', 'TE') else 0
            d = lg[r['y']][k] - ref[k]
            r['tot'] -= d * r['pl']; r['sv'] = r['tot'] / r['gp']
        r['sv'], r['tot'] = round(r['sv'], 2), round(r['tot'], 1)
        out.append(r)
    return out


def main():
    D = load()
    if 'nfl' in sys.argv:
        D['nfl'] = nfl(range(1999, 2026))
    elif 'nflteams' in sys.argv:
        D['nfl'] = nfl_teams(D.get('nfl') or [])
    if 'cfb' in sys.argv:
        D['cfb'] = cfb(range(2014, 2026))
    save(D)
    for k, v in D.items():
        print('sv_hist', k, len(v), 'rows', min(r['y'] for r in v), '-', max(r['y'] for r in v))


if __name__ == '__main__':
    main()
