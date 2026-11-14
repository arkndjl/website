#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Tennis event odds (the tennis ARKBOARD "event odds" tab): every ATP / WTA tour-level singles event whose draw
ESPN lists, simulated from the match model (scripts/tennis_model.py) -> data/tennis_events.json.

    python3 scripts/tennis_events.py              # live, after tennis_data.py and tennis_model.py
    python3 scripts/tennis_events.py --backtest   # past draws rebuilt from results -> prints the comparison

Live: the main-draw matches ESPN lists (scripts/tennis_data.py load_espn) give the field and every pairing made so
far; played matches are fixed. Each simulation plays the rest round by round: listed pairings as drawn, and pairings
ESPN has not listed yet (it lists a match once both players are known) by the seeding principle, the better-ranked
half of the players left in a round against the other half at random. Match chances are the live model's (surface,
context, best of 5 for men at the Slams). An event is shown once its field is complete: players entering in round 1
count one slot, players with a bye two, and the slots must fill a draw of 8, 16, ... 128. Round-robin events (the
tour Finals) are left out.

Backtest (a sanity check, not a site claim): each past tour-level draw rebuilt from its results (the real bracket),
title chances computed exactly from the ratings before the event's first main-draw match, scored against the same
bracket on Elo alone and on ranking alone.
"""
import datetime as dt
import gzip
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tennis_model as TM  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'tennis_events.json')
LEDGER = os.path.join(HERE, 'data', 'ledger', 'tennis_events_2027.json')
EXPORT = '/mnt/project-files/tennis/matches.csv.gz'
NSIM = 10000
LVN = {'G': 'Grand Slam', 'M': '1000', 'A': '250 / 500', 'F': 'Finals', 'O': 'Olympics'}
LATE = {'QF': 3, 'SF': 2, 'F': 1}            # rounds from the end
RNAME = {1: 'F', 2: 'SF', 3: 'QF'}


def round_names(nr):
    """labels of the rounds a player can reach after the first, then the title: R2, R3, ... QF, SF, F, W"""
    return [RNAME.get(nr - k, f'R{k + 1}') for k in range(1, nr)] + ['W']


def field(matches, size=None):
    """matches: [(round label, a, b, winner or None)] of one main draw -> (nr, level, alive, pending) or None when
    the field is not complete. level[p] = index of the round p plays next (for a player who is out, the round lost);
    pending[r] = listed, unplayed pairs. A player's slots are 2 ** level (a bye into round 2 holds two), and the
    players still in must fill a draw of 2 ** nr: nr is the smallest that fits, or log2(size) when the size is known
    (early rounds drop off ESPN's listing in the second week)."""
    nums = [int(m[0][1:]) for m in matches if m[0] not in LATE]
    if any(not (m[0] in LATE or (m[0].startswith('R') and m[0][1:].isdigit())) for m in matches) or not matches:
        return None
    lo = max([3] + [n + (3 if any(m[0] in LATE for m in matches) else 0) for n in nums] + nums)
    for nr in ([int(math.log2(size))] if size else range(lo, 8)):
        idx = lambda rd: nr - LATE[rd] if rd in LATE else int(rd[1:]) - 1  # noqa: E731
        if any(not 0 <= idx(m[0]) < nr for m in matches):
            continue
        level, alive, pending, ok = {}, set(), {}, True
        for rd, a, b, w in sorted(matches, key=lambda m: idx(m[0])):
            r = idx(rd)
            for q in (a, b):
                if q in level and (q not in alive or level[q] != r):
                    ok = False                                 # a player listed again after losing, or out of step
                level[q] = r
                alive.add(q)
            if w in (a, b):
                level[w] = r + 1
                alive.discard(b if w == a else a)
            else:
                pending.setdefault(r, []).append((a, b))
        if ok and sum(2 ** level[q] for q in alive) == 2 ** nr:
            return nr, level, alive, pending
    return None


def simulate(nr, level, alive, pending, win, rank, n=NSIM, seed=3):
    """-> {player: [P(reach round 2), ..., P(title)]} for the players still in. win(a, b) = P(a beats b)."""
    rng = random.Random(seed)
    cnt = {p: [0] * nr for p in alive}
    base = {r: [p for p in alive if level[p] == r] for r in range(nr + 1)}
    order = {p: (rank.get(p) or 9999, p) for p in alive}
    for _ in range(n):
        carry = []
        for r in range(nr):
            ent = base[r] + carry
            carry = []
            fixed = pending.get(r, ())
            used = {p for ab in fixed for p in ab}
            rest = sorted((p for p in ent if p not in used), key=order.get)
            h = len(rest) // 2
            low = rest[h:]
            rng.shuffle(low)
            for a, b in list(fixed) + list(zip(rest[:h], low)):
                w = a if rng.random() < win(a, b) else b
                cnt[w][r] += 1
                carry.append(w)
    out = {}
    for p in alive:
        out[p] = [1.0 if level[p] > r else cnt[p][r] / n for r in range(nr)]
    return out


def fair(q):
    q = min(max(q, 0.0005), 0.9995)
    return round(-100 * q / (1 - q)) if q >= 0.5 else round(100 * (1 - q) / q)


def live():
    import tennis_data as T
    rows, players, tn = T.load()
    comps, eid, kind = T.load_espn()
    fitp = {}
    try:
        fitp = json.load(open(TM.FIT))
    except (OSError, ValueError):
        pass
    m = TM.Model(dict(TM.DEFAULT, **fitp.get('params', {})))
    TM.mark_two_week(rows)
    for r in rows:
        m.update(r)
    today = dt.date.today()
    tday = (today - TM.DAY0).days
    ark = {}
    try:
        tj = json.load(open(TM.OUT))
        for t in tj['tours'].values():
            for r in t['players']:
                ark[r['id']] = r
    except (OSError, ValueError, KeyError):
        pass
    ev = {}
    for c in comps:
        rd = T.espn_round(c['rd'])
        if not c.get('date') or (rd.startswith('Q') and rd != 'QF'):
            continue
        ev.setdefault((c['tour'], c['tid']), []).append((rd, c))
    sizes = {}                                                 # draw sizes already on record (the ledger)
    try:
        for k, v in json.load(open(LEDGER))['events'].items():
            if abs((today - dt.date.fromisoformat(v['start'])).days) < 30:
                sizes[k.rsplit(':', 1)[0]] = v['size']
    except (OSError, ValueError, KeyError):
        pass
    out = []
    for (tour, tid), cs in sorted(ev.items()):
        lv, sf = kind.get(tid, ('A', 'H'))
        name = cs[0][1]['tn']
        if lv not in ('G', 'M', 'A') or any(rd == 'RR' for rd, _ in cs):
            continue
        names, ms, bad = {}, [], False
        for rd, c in cs:
            a, b = c['players']
            ids = []
            for x in (a, b):
                if not x[0] or x[0] == 'None' or not x[1]:
                    bad = True
                pid = eid.get(x[0]) or f'{tour[0]}x{x[0]}'
                names.setdefault(pid, (x[1], T.iso2(x[2], x[3])))
                ids.append(pid)
            w = None
            if c['done']:
                w = ids[0] if a[4] else ids[1] if b[4] else None
                if w is None:
                    bad = True
            ms.append((rd, ids[0], ids[1], w))
        hint = sizes.get(f"{tour}:{tid}")
        if lv == 'M' and not hint and all(x[0] == 'R1' for x in ms):
            print(f'events: {tour} {name}: waiting for the seeds with a bye')    # 1000s: the byes show from round 2
            continue
        f = None if bad else field(ms, hint)
        if not f:
            print(f'events: {tour} {name}: field not complete ({len(ms)} main-draw matches listed)')
            continue
        nr, level, alive, pending = f
        if len(alive) < 2:
            continue                                            # decided
        bo = 5 if (lv == 'G' and tour == 'atp') else 3
        cache = {}

        def win(a, b):
            k = (a, b)
            if k not in cache:
                cache[k] = m.predict(a, b, tour, sf, tday, bo)[0]
                cache[(b, a)] = 1 - cache[k]
            return cache[k]
        rank = {p: (players.get(p) or {}).get('rank') for p in names}
        P = simulate(nr, level, alive, pending, win, rank)
        rs = []
        for p in names:
            pl = players.get(p) or {}
            a_ = ark.get(p) or {}
            row = {'id': p, 'n': pl.get('n') or names[p][0], 'nat': pl.get('nat') or names[p][1], 'rank': pl.get('rank'),
                   'rk': a_.get('rk'), 'ph': a_.get('ph'), 'wph': a_.get('wph'), 'in': p in alive}
            if p in alive:
                row['p'] = [round(x, 4) for x in P[p]]
                row['fair'] = fair(P[p][-1])
            else:
                row['p'] = [1.0 if level[p] > r else 0.0 for r in range(nr)]
            rs.append(row)
        rs.sort(key=lambda r: (-r['p'][-1], [-x for x in reversed(r['p'])], r['rank'] or 9999))
        dates = sorted(c['date'] for _, c in cs)
        drawn = sum(len(v) for v in pending.values())
        out.append({'tour': tour, 'tid': tid, 'name': name, 'lv': lv, 'level': LVN.get(lv, lv), 'sf': sf, 'bo': bo,
                    'size': 2 ** nr, 'field': len(names), 'left': len(alive), 'rounds': round_names(nr),
                    'start': dates[0][:10], 'listed': drawn, 'players': rs})
        print(f"events: {tour} {name}: {len(names)} players, {len(alive)} left, favourite {rs[0]['n']} {rs[0]['p'][-1]:.3f}")
    out.sort(key=lambda e: ({'G': 0, 'M': 1, 'A': 2}[e['lv']], e['tour'], e['name']))
    ledger(out)
    res = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'nsim': NSIM, 'events': out}
    json.dump(res, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
    print(f'tennis_events.json: {len(out)} events')


def ledger(events):
    """Append-only forecast record (rule in the file): the first complete-field odds of each event, kept as written."""
    try:
        led = json.load(open(LEDGER))
    except (OSError, ValueError):
        return
    new = 0
    for e in events:
        k = f"{e['tour']}:{e['tid']}:{e['start'][:4]}"
        if k in led['events']:
            continue
        led['events'][k] = {'name': e['name'], 'tour': e['tour'], 'lv': e['lv'], 'sf': e['sf'], 'size': e['size'],
                            'start': e['start'], 'at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                            'played': e['field'] - e['left'], 'rounds': e['rounds'],
                            'p': {r['id']: r['p'] for r in e['players'] if r['in']},
                            'names': {r['id']: r['n'] for r in e['players']}}
        new += 1
    if new:
        json.dump(led, open(LEDGER, 'w'), separators=(',', ':'), allow_nan=False)
        print(f'ledger: {new} events recorded')


# ---------------------------------------------------------------------------------------------------- backtest
def export_rows():
    """history rows from the exported csv (the local run has no hist cache)"""
    import csv
    rows = []
    with gzip.open(EXPORT, 'rt') as fh:
        rd = csv.reader(fh)
        next(rd)
        for r in rd:
            def st(x):
                return [int(float(v)) if v != '' else 0 for v in x] if x[0] != '' else None
            num = lambda v, f=int: f(float(v)) if v != '' else None  # noqa: E731
            rows.append([int(r[0]), r[1], r[2], r[3], r[4], int(r[5]), r[6], r[7], r[8], r[9], st(r[11:20]), st(r[20:29]),
                         num(r[29]), num(r[30]), num(r[31], float), num(r[32], float)])
    return rows


def title_exact(node, win):
    """node: a player id or (node, node) -> {player: P(wins this subtree)}"""
    if not isinstance(node, tuple):
        return {node: 1.0}
    da, db = title_exact(node[0], win), title_exact(node[1], win)
    out = {}
    for a, pa in da.items():
        out[a] = pa * sum(pb * win(a, b) for b, pb in db.items())
    for b, pb in db.items():
        out[b] = pb * sum(pa * win(b, a) for a, pa in da.items())
    return out


def backtest(y0=20230101, y1=20261110):
    import numpy as np
    try:
        import tennis_data as T
        rows = T.load()[0]
    except (OSError, ValueError):
        rows = export_rows()
    rows = [r for r in rows if r[0] <= y1]
    fitp = json.load(open(TM.FIT))
    m = TM.Model(dict(TM.DEFAULT, **fitp.get('params', {})))
    TM.mark_two_week(rows)
    main = {}
    for r in rows:
        if y0 <= r[0] and (r[4] in ('QF', 'SF', 'F') or (r[4][:1] == 'R' and r[4][1:].isdigit())):
            main.setdefault(r[6], []).append(r)
    # the event's level is its final's (the history files quarterfinal rows under the qualifying level)
    main = {t: v for t, v in main.items() if any(x[4] == 'F' and x[2] in ('G', 'M', 'A') for x in v)}
    lvl = {t: next(x[2] for x in v if x[4] == 'F') for t, v in main.items()}
    events, seen, rk_fit = [], set(), []
    for r in rows:
        tid = r[6]
        if tid in main and tid not in seen and (r[4] == 'QF' or not r[4].startswith('Q')):
            seen.add(tid)
            ms = sorted(main[tid], key=lambda x: {'QF': 500, 'SF': 600, 'F': 700}.get(x[4], 0) - (int(x[4][1:]) if x[4][1:].isdigit() else 0))
            unit, rank = {}, {}
            for x in ms:
                w, l = x[7], x[8]
                rank.setdefault(w, x[12])
                rank.setdefault(l, x[13])
                unit[w] = (unit.get(w, w), unit.pop(l, l))
            fin = [x for x in ms if x[4] == 'F']
            if len(unit) == 1 and len(fin) == 1 and len(rank) >= 8:
                root = next(iter(unit.values()))
                ps = list(rank)
                tour, sf, bo = r[1], r[3], max(x[5] for x in ms)
                day = (TM.ymd(r[0]) - TM.DAY0).days + 1
                pm, pe = {}, {}
                for i, a in enumerate(ps):
                    for b in ps[i + 1:]:
                        q = m.predict(a, b, tour, sf, day, bo)
                        e = q[1]
                        pm[(a, b)], pm[(b, a)] = q[0], 1 - q[0]
                        pe[(a, b)], pe[(b, a)] = e, 1 - e
                events.append({'tid': tid, 'd': r[0], 'tour': tour, 'lv': lvl[tid], 'root': root, 'rank': rank, 'champ': fin[0][7],
                               'pm': pm, 'pe': pe, 'n': len(ps)})
        if 20150101 <= r[0] < y0 and r[2] in ('G', 'M', 'A') and r[12] and r[13] and not r[4].startswith('Q'):
            rk_fit.append(math.log(r[13]) - math.log(r[12]))          # winner's edge in log rank
        m.update(r)
    x = np.array(rk_fit)
    grid = np.arange(0.3, 1.6, 0.05)
    e = float(grid[int(np.argmin([np.mean(np.log1p(np.exp(-g * x))) for g in grid]))])

    def rank_win(rank):
        return lambda a, b: 1 / (1 + math.exp(-e * (math.log(rank[b] or 1500) - math.log(rank[a] or 1500))))
    res = []
    for ev in events:
        row = {'tid': ev['tid'], 'd': ev['d'], 'tour': ev['tour'], 'lv': ev['lv'], 'n': ev['n']}
        for nm, win in (('model', lambda a, b: ev['pm'][(a, b)]), ('elo', lambda a, b: ev['pe'][(a, b)]), ('rank', rank_win(ev['rank']))):
            P = title_exact(ev['root'], win)
            row[nm] = (-math.log(max(P[ev['champ']], 1e-6)), sum((q - (p == ev['champ'])) ** 2 for p, q in P.items()))
        res.append(row)

    def summ(rr):
        o = {'n': len(rr)}
        for j, met in enumerate(('ll', 'brier')):
            for nm in ('model', 'elo', 'rank'):
                o[f'{met}_{nm}'] = round(float(np.mean([r[nm][j] for r in rr])), 4)
            for nm in ('elo', 'rank'):
                d = np.array([r['model'][j] - r[nm][j] for r in rr])
                o[f'{met}_t_vs_{nm}'] = round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2) if len(d) > 2 else None
        return o
    out = {'window': [y0, y1], 'last': max(r['d'] for r in res), 'rankExp': round(e, 2), 'all': summ(res)}
    for k in ('G', 'M', 'A'):
        out[k] = summ([r for r in res if r['lv'] == k])
    for k in ('atp', 'wta'):
        out[k] = summ([r for r in res if r['tour'] == k])
    print(json.dumps(out, indent=1))
    return out


if __name__ == '__main__':
    if '--backtest' in sys.argv:
        backtest()
    else:
        live()
