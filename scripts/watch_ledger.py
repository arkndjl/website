#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-registered forward ledgers for the coaching watch and the transfer watch (college football and basketball).

    python3 scripts/watch_ledger.py coaches             freeze every head coach's Leave% and likeliest jobs, once
    python3 scripts/watch_ledger.py players cfb|cbb     freeze Xfer% and the Lean / 2nd / 3rd schools today
    python3 scripts/watch_ledger.py players cfb --due   the same, only inside a freeze window (the board workflows)
    python3 scripts/watch_ledger.py --test              self-check

The watch tabs (data/cfb_watch.json, data/cbb_watch.json) have no held-out destination test: the pages changed after
the last cycle the models were fit on. A forecast written down before the moves and scored after them is the test,
so this file freezes what the pages said and fixes how it will be scored.

Stores (append-only; nothing here is rewritten once its window has passed):
  scripts/data/ledger/coach_watch_2027.json            both sports, frozen once (a second run refuses)
  scripts/data/ledger/<sport>/xfer_2027/<date>.json.gz one file per freeze day; a rerun the same day replaces it.
                                                       gzip mtime 0, so an unchanged page writes the same bytes.

PRE-REGISTERED SCORING, COACHES
  population  every head coach in the frozen list except `excl` rows: jobs that had already opened this season before
              the freeze (an interim sits in the chair, or the season's first head coach is gone).
  outcome     leave = 1 if the frozen coach is not the head coach of the frozen team on the cut date
              (CFB 2027-02-15, CBB 2027-05-15), for any reason. Names join through scripts/names.py.
  1 leave     log loss of Leave% (clipped .01-.99) against a constant at the frozen list's own mean Leave%; paired
              by coach, pass t <= -2. Brier skill and a five-bin reliability table are reported.
  2 jobs      among coaches who are head coach of another team in the frozen list on the cut date: top-1 and top-3
              hit of the frozen jobs (`dest`, P(job | hired away)). Null: a job drawn in proportion to every other
              team's frozen Leave%. Pass: top-3 hits above the null's expected count, one-sided p < .05 from 20,000
              draws of the null (seed 2027). Coaches with an empty `dest` count as misses.

PRE-REGISTERED SCORING, PLAYERS
  freezes     `fall` = the first file; `final` = the last file on or before the day the winter window opens
              (CFB 2027-01-02; CBB the last file before its spring window, see FINAL). Both are scored; `final` decides.
  outcome     moved = 1 if the player is on another school's roster for the next season (CFB: ESPN 2027 rosters, about
              May 2027; CBB: 2027-28 rosters, about October 2027). Players join through scripts/names.py with the
              frozen team and position checked. A player on no roster (draft, graduation, out of the sport) is dropped.
  1 Xfer%     watch rows: log loss and Brier of `tp` against the rows' realized rate. The `all` table (every rostered
              player's stay / transfer odds) is scored the same way against its own base rate; pass skill > 0 with
              paired t <= -2 by player.
  2 schools   watch rows who moved: top-1 and top-3 hit of the frozen schools. Null: 1 / N and 3 / N with N = the
              schools at the destination's level (FBS 138; D-I 364). Pass: top-3 hits above the null, exact binomial
              one-sided p < .05. Calibration: mean frozen share of the top school against its hit rate.
A failed test is a result: it is reported, not tuned away. Results go to data/watch_ledger_2027.json."""
import datetime as dt
import gzip
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, 'scripts', 'data', 'ledger')
COACH = os.path.join(STORE, 'coach_watch_2027.json')
CUT = {'cfb': '2027-02-15', 'cbb': '2027-05-15'}
# freeze windows (month, day) inclusive: the last week before the winter transfer window, and for basketball the
# weeks before its spring window as well
WINDOWS = {'cfb': [((12, 25), (12, 31)), ((1, 1), (1, 1))],
           'cbb': [((12, 25), (12, 31)), ((1, 1), (1, 1)), ((3, 15), (4, 5))]}
FINAL = {'cfb': '2027-01-01', 'cbb': '2027-04-05'}
LEVEL_N = {'cfb': 138, 'cbb': 364}


def load(rel):
    with open(os.path.join(ROOT, rel)) as h:
        return json.load(h)


def r4(x):
    return None if x is None else round(float(x), 4)


def dests(row):
    return [[d.get('team'), r4(d.get('p'))] for d in (row.get('dest') or [])]


def coach_rows(sport):
    """[team, coach, leave, out, moved, [[job, share], ...], excl] from the sport's watch file"""
    w = load(f'data/{sport}_watch.json')
    gone = {}
    if sport == 'cfb':      # the season's first head coach by team id, to catch a job that opened without an interim flag
        try:
            sys.path.insert(0, os.path.join(ROOT, 'scripts'))
            import names
            start = load('scripts/data/cfb_hc_start.json')
            mk = load('data/cfb_coach_market.json')
            if start.get('season') == w.get('season'):
                for t in mk['teams']:
                    first = start['coaches'].get(str(t['tid']))
                    if first and not any(names.same(t['hc'], f) for f in first):
                        gone[t['team']] = 1
        except Exception as e:
            print('coach start list not read:', e)
    rows = []
    for c in w['coaches']:
        excl = 'opened' if (c.get('interim') or gone.get(c['team'])) else None
        rows.append([c['team'], c['name'], r4(c.get('leave')), r4(c.get('out')), r4(c.get('moved')), dests(c), excl])
    return {'asof': w.get('asof'), 'season': w.get('season'), 'cut': CUT[sport],
            'cols': ['team', 'coach', 'leave', 'out', 'moved', 'dest', 'excl'], 'rows': rows}


def freeze_coaches(force=False):
    if os.path.exists(COACH) and not force:
        print('coach watch ledger: already frozen, not rewritten'); return None
    out = {'frozen': dt.datetime.now(dt.timezone.utc).date().isoformat(), 'cycle': 2027,
           'scoring': 'scripts/watch_ledger.py docstring, PRE-REGISTERED SCORING, COACHES',
           'rule': {'population': 'rows with excl null', 'leave': 'not head coach of the frozen team on `cut`',
                    'leaveTest': 'log loss (clip .01-.99) vs a constant at the frozen mean Leave%, paired by coach, pass t <= -2',
                    'jobsTest': 'movers to another frozen team: top-1 / top-3 hit of dest vs jobs drawn by frozen Leave%, 20000 draws, seed 2027, pass one-sided p < .05 on top-3'},
           'cfb': coach_rows('cfb'), 'cbb': coach_rows('cbb')}
    os.makedirs(STORE, exist_ok=True)
    with open(COACH, 'w') as h:
        json.dump(out, h, separators=(',', ':'), ensure_ascii=False)
        h.write('\n')
    for s in ('cfb', 'cbb'):
        r = out[s]['rows']
        print(f'coach watch ledger {s}: {len(r)} coaches, {sum(1 for x in r if x[6])} excluded (already open), '
              f'expected leavers {sum(x[2] or 0 for x in r if not x[6]):.1f}')
    return out


def player_snap(sport):
    w = load(f'data/{sport}_watch.json')
    cols = ['name', 'team', 'pos', 'cls', 'fv', 'tp', 'dest']
    rows = [[p.get('name'), p.get('team'), p.get('pos'), p.get('cls'), p.get('fv'), r4(p.get('tp')), dests(p)] for p in w['players']]
    if sport == 'cfb':
        b = load('static/data/cfb-builder.json')
        acols = ['team', 'name', 'room', 'cls', 'fv', 'stay']
        allp = [[t['team'], r.get('name'), g.get('g'), r.get('cls'), r.get('fv'), r4(r.get('stay'))]
                for t in b['teams'] for g in t.get('positions', []) for r in g.get('depth', []) if r.get('name')]
    else:
        m = load('data/cbb_market.json')
        acols = ['team', 'name', 'pos', 'cls', 'fv', 'tp', 'back']
        seen, allp = set(), []
        for r in m.get('transfer', []) + m.get('nil', []):
            k = (r.get('team'), r.get('name'))
            if k in seen or r.get('tp') is None:
                continue
            seen.add(k)
            allp.append([r.get('team'), r.get('name'), r.get('pos'), r.get('cls'), r.get('fv'), r4(r.get('tp')), r4(r.get('back'))])
    return {'sport': sport, 'cycle': 2027, 'asof': w.get('asof'), 'season': w.get('season'), 'levelN': LEVEL_N[sport], 'final': FINAL[sport],
            'scoring': 'scripts/watch_ledger.py docstring, PRE-REGISTERED SCORING, PLAYERS',
            'cols': cols, 'rows': rows, 'allCols': acols, 'all': allp}


def in_window(sport, day):
    md = (day.month, day.day)
    return any(a <= md <= b for a, b in WINDOWS[sport])


def gz_bytes(obj):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0) as g:
        g.write(json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode())
    return buf.getvalue()


def freeze_players(sport, due=False, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    if today.isoformat() > FINAL[sport]:
        print(f'transfer watch ledger {sport}: the window has opened, not frozen'); return None
    if due and not in_window(sport, today):
        print(f'transfer watch ledger {sport}: not in a freeze window'); return None
    s = player_snap(sport)
    if not s['rows']:
        print(f'transfer watch ledger {sport}: the watch is empty, not frozen'); return None
    folder = os.path.join(STORE, sport, 'xfer_2027')
    os.makedirs(folder, exist_ok=True)
    f = os.path.join(folder, today.isoformat() + '.json.gz')
    with open(f, 'wb') as h:
        h.write(gz_bytes(s))
    print(f'transfer watch ledger {sport}: {len(s["rows"])} watch rows, {len(s["all"])} players -> {os.path.relpath(f, ROOT)}')
    return f


def test():
    d = dt.date
    assert in_window('cfb', d(2026, 12, 25)) and in_window('cfb', d(2026, 12, 31)) and in_window('cfb', d(2027, 1, 1))
    assert not in_window('cfb', d(2026, 12, 24)) and not in_window('cfb', d(2027, 1, 2)) and not in_window('cfb', d(2027, 3, 20))
    assert in_window('cbb', d(2027, 3, 20)) and not in_window('cbb', d(2027, 2, 1))
    a = gz_bytes({'x': 1}); b = gz_bytes({'x': 1})
    assert a == b and json.loads(gzip.decompress(a)) == {'x': 1}
    for s in ('cfb', 'cbb'):
        c = coach_rows(s); p = player_snap(s)
        assert c['rows'] and all(len(r) == len(c['cols']) for r in c['rows'])
        assert all(0 <= r[2] <= 1 for r in c['rows'])
        assert p['rows'] and all(len(r) == len(p['cols']) for r in p['rows']) and all(len(r) == len(p['allCols']) for r in p['all'])
    print('watch_ledger: ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--test' in a:
        test()
    elif a[:1] == ['coaches']:
        freeze_coaches('--force' in a)
    elif a[:1] == ['players'] and len(a) > 1 and a[1] in WINDOWS:
        freeze_players(a[1], '--due' in a)
    else:
        print(__doc__); sys.exit(2)
