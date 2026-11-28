#!/usr/bin/env python3
"""Flip replay on the 2026-27 files as they stand (no outcome read). The runs that flipped in production (history.py)
were the ones where Barttorvik's season file came through against the ones where the runner got a page instead, with
the same game logs. Each board player with a line is graded four ways on today's logs: the old rule (his file when
within a game, else rebuilt) with his file read and with a page, and the new one (cbb_live.line_of) with his file read
and with a page (his row kept from the last read, BT_LINES). Counts the players whose FV differs between the two runs.

    python3 scripts/research/cbb_live_nov28/replay.py      # -> replay.json
"""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_data as D
import cbb_fit as F
import cbb_live as L
from fv_dist import cbb_z, at_mean
import fv_scale as FS

C = L.C


def old_rule(a, o, team, recon):
    if o and o['gp'] and abs(o['gp'] - a['gp']) <= 1 and o['team'] == team and o.get('bpm') is not None:
        return {k: o.get(k) for k in L.KEEP}
    return L.line(a, recon, {'team': team, 'conf': o['conf'] if o else None, 'role': o['role'] if o else None})


def main():
    prior = json.load(gzip.open(L.PRIOR))
    fit = json.load(open(F.OUT)); lf = json.load(open(L.LIVE_FIT))
    F.VALIDITY = fit.get('validity', 1.0)
    keep, ci = prior['keep'], {c: j for j, c in enumerate(prior['cols'])}
    L.repair_links(prior, ci)
    F.set_context([{'pid': m['pid'], 'name': row[ci['name']], 'rec': m['rec'], 'seasons': [dict(zip(keep, q)) for q in m['seasons']]}
                   for row, m in zip(prior['rows'], prior['careers'])])
    games = json.load(gzip.open(os.path.join(D.CACHE, 'games', f'{L.SEASON}.json.gz')))
    off = {r['pid']: r for r in D.load_bt(L.SEASON)}
    recon = lf['recon']
    by_p, td = defaultdict(list), defaultdict(set)
    for g in games:
        if g[C['year']] != L.SEASON: continue
        by_p[str(g[C['pid']])].append(g); td[g[C['team']]].add((g[C['date']], g[C['muid']]))
    nk = {(D.norm(rs[-1][C['name']]), rs[-1][C['team']]): pid for pid, rs in by_p.items()}
    ARMS = [('old', 'file'), ('old', 'page'), ('new', 'file'), ('new', 'page')]
    seqs, fs = [], []
    for row, m in zip(prior['rows'], prior['careers']):
        pid = m.get('pid') or nk.get((m['key'], m.get('bt')))
        o = off.get(pid) if pid else None
        rs = sorted(by_p.get(str(pid), []), key=lambda g: g[C['date']]) if pid else []
        if not o or not rs: continue
        team = rs[-1][C['team']]
        if m.get('bt') and team != m['bt']: continue
        tg = len(td[team]) or 1
        a = L.summed(rs, tg)
        if a['mp'] * a['gp'] <= 0: continue
        cc = {'pid': pid, 'name': row[ci['name']], 'dob': m['dob'], 'rec': m['rec'], 'seasons': [dict(zip(keep, s)) for s in m['seasons']]}
        i = len(cc['seasons']) - 1
        f_pre = F.features(cc, i)
        grp = 'newcomer' if f_pre['newcomer'] else 'returner'
        kept = dict(zip(L.SNAP_COLS, [o[c] for c in L.SNAP_COLS])) if L.usable(o, team, a) else None
        arms = []
        for rule, run in ARMS:
            if rule == 'old': ln = old_rule(a, o if run == 'file' else None, team, recon)
            else: ln = L.line_of(rs, a, o if run == 'file' else kept, team, td[team], recon)
            ln = dict(ln, yr=o.get('yr'), n=a['mp'] * a['gp'], team_g=tg)
            if not ln.get('role'): ln['role'] = o.get('role')
            gp_full = ln['gp'] * lf['fullGames'] / tg if lf['now'][grp] == 'projected' and tg < lf['fullGames'] else None
            fs.append(F.features(L.next_career(cc, ln, gp_full), i + 1))
            arms.append((L.weight(ln['n'], lf['k'][grp]), ln['bpm']))
        seqs.append((row, f_pre, arms))
    E0 = L.score_many([f for _, f, _ in seqs], fit)[0]
    E1 = L.score_many(fs, fit)[0]
    blend = [(1 - w) * E0[k] + w * E1[4 * k + j] for k, (_, _, arms) in enumerate(seqs) for j, (w, _) in enumerate(arms)]
    fvx = F.live_grade(np.array(blend), fit)[2]
    out = {'players': len(seqs), 'old': {'fvDiffers': 0, 'bpmDiffers1': 0}, 'new': {'fvDiffers': 0, 'bpmDiffers1': 0}, 'examples': []}
    for k, (row, _, arms) in enumerate(seqs):
        fv = []
        for j in range(4):
            g = float(fvx[4 * k + j])
            fv.append(FS.fv_of('cbb', at_mean('cbb', g, cbb_z(row[ci['cls']], row[ci['new']], row[ci['pos']], g))))
        for r, (x, y) in (('old', (0, 1)), ('new', (2, 3))):
            out[r]['fvDiffers'] += fv[x] != fv[y]
            out[r]['bpmDiffers1'] += abs(arms[x][1] - arms[y][1]) >= 1
        if row[ci['name']] == 'Ethan Brown' and row[ci['team']] == 'Illinois':
            out['examples'].append({'name': 'Ethan Brown', 'team': 'Illinois',
                                    **{f'{a}, {b}': {'bpm': round(arms[j][1], 1), 'fv': fv[j]} for j, (a, b) in enumerate(ARMS)}})
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.path.join(HERE, 'replay.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
