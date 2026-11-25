#!/usr/bin/env python3
"""Season value (SV, as scripts/nfl_qb.py and scripts/nfl_season_value.py, regular season only so it lines up with team
points) and the public nflverse play-by-play numbers, per gsis id, for 2016-25, whole season and weeks 1-9:
  qb    QB SV points over a replacement QB (-0.12 opponent-adjusted EPA a play), dropbacks + QB runs
  sk    RB/WR/TE SV points (aEPA a run / a target less replacement; RB and WR opponent-adjusted, RB weather-adjusted)
  dc    defender credit (EPA of negative plays split over credited defenders, DL/DB offense-adjusted); SV = dc - REPL x snaps
  epa   raw nflverse EPA (qb_epa on dropbacks, epa on runs and targets) credited to passer, rusher and receiver
  cp    CPOE sum and attempts (passer)
Opponent adjustments use only the games inside the scope (weeks 1-9 for the half), so nothing comes from later games.
    python3 scripts/research/metric_audit_nov24/nfl/sv_prep.py   -> scripts/.cache/nfl/audit_sv_<y>.json"""
import csv, gzip, json, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import nfl_season_value as NSV  # noqa: E402
from nfl_qb import REPL as QREPL, K_DEF, FR  # noqa: E402

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
f = NSV.f
NA = ('', 'NA')


def plays(y):
    out = []
    with gzip.open(os.path.join(CACHE, f'play_by_play_{y}.csv.gz'), 'rt', encoding='utf-8') as fh:
        rd = csv.reader(fh); h = next(rd); I = {k: i for i, k in enumerate(h)}
        for r in rd:
            g = lambda k: r[I[k]]  # noqa: E731
            if g('season_type') != 'REG' or g('two_point_attempt') == '1':
                continue
            pt, db = g('play_type'), g('qb_dropback') == '1'
            if pt not in ('run', 'pass') and not db:
                continue
            if g('qb_spike') == '1' or g('qb_kneel') == '1':
                continue
            epa = f(g('epa'))
            if epa is None:
                continue
            qepa = f(g('qb_epa')); qepa = epa if qepa is None else qepa
            wthr = g('weather').lower()
            wx = (f(g('wind')), f(g('temp')), 1 if any(w in wthr for w in ('rain', 'snow', 'shower', 'sleet', 'drizzle')) else 0,
                  g('roof') in ('outdoors', 'open'))
            W = defaultdict(float)
            if g('sack') == '1':
                if g('sack_player_id') not in NA: W[g('sack_player_id')] += 1
                for c in ('half_sack_1_player_id', 'half_sack_2_player_id'):
                    if g(c) not in NA: W[g(c)] += .5
            for c in NSV.SPL:
                if g(c) not in NA: W[g(c)] += 1
            if epa <= 0 and (pt == 'run' or g('complete_pass') == '1'):
                for c in NSV.TK:
                    if g(c) not in NA: W[g(c)] += 1
            out.append({'gid': g('game_id'), 'wk': int(g('week')), 'ot': FR.get(g('posteam'), g('posteam')), 'dt': FR.get(g('defteam'), g('defteam')),
                        'db': db, 'run': pt == 'run' and not db, 'epa': epa, 'qepa': qepa, 'wx': wx,
                        'qb': g('id') if db and g('id') not in NA else (g('passer_player_id') if db and g('passer_player_id') not in NA else ''),
                        'ru': g('rusher_player_id') if g('rusher_player_id') not in NA else '',
                        're': g('receiver_player_id') if g('receiver_player_id') not in NA and g('sack') != '1' else '',
                        'pass': pt == 'pass' and g('sack') != '1',
                        'cpoe': f(g('cpoe')) if g('pass_attempt') == '1' and g('sack') != '1' and g('qb_scramble') != '1' else None,
                        'W': dict(W) if (W and epa < 0) else None})
    return out


def scope(P, pos, keep):
    P = [p for p in P if keep(p['wk'])]
    A = defaultdict(lambda: [0.0, 0])
    for p in P:
        kind = 1 if p['db'] else 0
        for key in (('d', p['dt'], kind), ('dg', p['gid'], p['dt'], kind), ('o', p['ot'], kind), ('og', p['gid'], p['ot'], kind), ('l', kind),
                    ('qd', p['dt']), ('qdg', p['gid'], p['dt']), ('ql',)):
            A[key][0] += p['qepa'] if key[0] in ('qd', 'qdg', 'ql') else p['epa']; A[key][1] += 1

    def rel(side, t, gid, kind):
        s, n = A[(side, t, kind)]; sg, ng = A[(side + 'g', gid, t, kind)]
        m = A[('l', kind)][0] / A[('l', kind)][1] if A[('l', kind)][1] else 0.0
        return ((s - sg) - m * (n - ng)) / (n - ng + K_DEF)

    def qrel(t, gid):
        s, n = A[('qd', t)]; sg, ng = A[('qdg', gid, t)]
        m = A[('ql',)][0] / A[('ql',)][1] if A[('ql',)][1] else 0.0
        return ((s - sg) - m * (n - ng)) / (n - ng + K_DEF)
    V = defaultdict(lambda: defaultdict(float))
    for p in P:
        kind = 1 if p['db'] else 0
        # QB SV: dropbacks (qb_epa) and his own runs
        q = p['qb'] if p['db'] else (p['ru'] if p['run'] and pos.get(p['ru']) == 'QB' else '')
        if q and pos.get(q) == 'QB':
            e = p['qepa'] if p['db'] else p['epa']
            V[(q, p['ot'])]['qb'] += e - qrel(p['dt'], p['gid']) - QREPL
        # skill SV
        who = p['ru'] if p['run'] else (p['re'] if p['pass'] else '')
        g = NSV.GROUP.get(pos.get(who, ''), '')
        if who and g in ('RB', 'WR', 'TE'):
            a = p['epa'] - (rel('d', p['dt'], p['gid'], kind) if g in NSV.OPP else 0.0) - (NSV.wadj(kind, *p['wx']) if g in NSV.WEA else 0.0)
            V[(who, p['ot'])]['sk'] += a - NSV.REPL[(g, kind)]
        # public raw EPA: passer (qb_epa), rusher, receiver (EPA of the target)
        if p['db'] and p['qb']: V[(p['qb'], p['ot'])]['epa'] += p['qepa']
        if p['run'] and p['ru']: V[(p['ru'], p['ot'])]['epa'] += p['epa']
        if p['pass'] and p['re']: V[(p['re'], p['ot'])]['epa'] += p['epa']
        if p['cpoe'] is not None and p['qb']:
            V[(p['qb'], p['ot'])]['cp'] += p['cpoe']; V[(p['qb'], p['ot'])]['cpn'] += 1
        if p['W']:
            tw = sum(p['W'].values())
            for pid, w in p['W'].items():
                g = NSV.GROUP.get(pos.get(pid, ''), '')
                if g not in ('DL', 'LB', 'DB'):
                    continue
                adj = (rel('o', p['ot'], p['gid'], 0) + rel('o', p['ot'], p['gid'], 1)) / 2 if g in NSV.OPP else 0.0
                V[(pid, p['dt'])]['dc'] += -(p['epa'] - adj) * w / tw
    return {f'{k[0]}|{k[1]}': {a: round(b, 4) for a, b in v.items()} for k, v in V.items()}


def main(ys):
    for y in ys:
        pos = {}
        for r in csv.DictReader(open(os.path.join(CACHE, f'roster_{y}.csv'), newline='', encoding='utf-8')):
            if r['gsis_id']:
                pos[r['gsis_id']] = r.get('depth_chart_position') if r.get('position') in ('LB', 'DL', 'DB') and r.get('depth_chart_position') else r['position']
        for r in csv.DictReader(open(os.path.join(CACHE, f'stats_player_week_{y}.csv'), newline='', encoding='utf-8')):
            pos.setdefault(r['player_id'], r.get('position') or '')
        P = plays(y)
        out = {'full': scope(P, pos, lambda w: True), 'h1': scope(P, pos, lambda w: w < 10)}
        with open(os.path.join(CACHE, f'audit_sv_{y}.json'), 'w') as fh:
            json.dump(out, fh, separators=(',', ':'))
        print(y, len(P), len(out['full']), flush=True)


if __name__ == '__main__':
    main([int(a) for a in sys.argv[1:]] or list(range(2016, 2026)))
