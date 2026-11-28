#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Forward logs (Nov 28 2026): dated, append-only snapshots of data the site reads and then overwrites, so a point-in-time
history exists for tests that can only be built going forward. Nothing here is fetched: each log reads a file another
step already wrote, and appends a row only when something changed since its last row (a row's values hold until the
next row for the same key). Folding a log's rows in order gives the state on any date.

    python3 scripts/snapshots.py live     injuries (every sport) and news items; odds-snap.yml, every 30 minutes
    python3 scripts/snapshots.py daily    depth charts (every sport), board vintages, agency ledger rows;
                                          process-refresh.yml, after every board run and every 6 hours
    python3 scripts/snapshots.py offers   CFB recruit offers, commitments and visit counts from ESPN's class lists
                                          (scripts/.cache/cfb/espnclass2-<y>.json); cfb-recruits.yml, daily
    python3 scripts/snapshots.py on3      On3's college player grades, ranks and NIL valuations
                                          (scripts/.cache/cfb/on3.json); cfb-board.yml, each full board run
    python3 scripts/snapshots.py status   only data/snapshots.json (rows, first and last stamp a log; daily writes it too)
    python3 scripts/snapshots.py --test   self-check

Logs (scripts/data/snaps/), every row with t = the run's UTC stamp (scripts/data_push.py merges .jsonl by line on t):
  inj/<yyyy-mm>.jsonl       {t, s, n, tm, c, x}  sport, name key, team, status code (null = off the report), detail
  news/<yyyy-mm>.jsonl      {t, id, d, at, sec, cat, tag, h, s, w}  every news item the first time it is seen
  depth/<sport>-<yyyy-mm>.jsonl {t, k, o}  k = team|unit|slot, o = the names in order (null = slot gone)
  boards/<board>/<date>.json.gz  one board's metric as scripts/board_moves.py stored it that day (scripts/data/moves
                            keeps only the week window): written once, at most one a board a week, rows changed since
                            the last vintage plus `gone` (base = 1 on the first vintage or a new season or model)
  agency/rows.jsonl         {t, p, sp, sch, ag, agent, scope, sd, src}  each ledger row the day it first appears
  offers/cfb-<class>.jsonl  {t, rid, n, add, drop, tid, st, v}  offers added or dropped (ESPN team ids), the committed
                            school, ESPN status and visit count, on change
  on3/cfb-<yyyy>.jsonl      {t, slug, n, g, r, nil, tm}  On3 grade, overall rank, NIL valuation, team, on change
data/snapshots.json: per log, rows, keys and first and last stamp (retests.json `ready` conditions read it).

Public repo: only data the site already shows or reads from public pages. No visitor data, no stakes, no contacts.
"""
import datetime as dt
import glob
import gzip
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, 'scripts', 'data', 'snaps')
OUT = os.path.join(ROOT, 'data', 'snapshots.json')
SPORTS_INJ = ('nfl', 'nba', 'nhl', 'cfb', 'cbb', 'soccer')
DEPTH = ('cfb', 'cbb', 'nfl', 'nba', 'nhl', 'soccer')
BOARD_DAYS = 7


def load(p, default=None):
    try:
        if p.endswith('.gz'):
            with gzip.open(p, 'rt') as f:
                return json.load(f)
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def rows(pattern):
    out = []
    for fn in sorted(glob.glob(os.path.join(SNAP, pattern))):
        with open(fn) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    out.sort(key=lambda r: r.get('t') or '')
    return out


def append(rel, new):
    if not new:
        return 0
    p = os.path.join(SNAP, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'a') as f:
        for r in new:
            f.write(json.dumps(r, separators=(',', ':'), ensure_ascii=False) + '\n')
    return len(new)


def fold(rs, key, val):
    """state after the rows in order: {key(r): val(r)}"""
    st = {}
    for r in rs:
        st[key(r)] = val(r)
    return st


# ---- injuries: static/data/injuries.json (odds-snap rebuilds it every half hour) ------------------------------------

def inj_now(d):
    """{(sport, name key, team): (code, detail)} from the site's injury file"""
    out = {}
    for s in SPORTS_INJ:
        for name, lst in (d.get(s) or {}).items():
            for e in lst or []:
                if not isinstance(e, list) or not e:
                    continue
                tm = e[3] if len(e) > 3 else None
                out[(s, name, tm)] = (e[0], e[1] if len(e) > 1 else None)
    return out


def snap_inj(stamp, src=None):
    d = load(src or os.path.join(ROOT, 'static', 'data', 'injuries.json'), {})
    now = inj_now(d)
    if not now:
        return 0
    prev = {k: v for k, v in fold(rows('inj/*.jsonl'), lambda r: (r['s'], r['n'], r.get('tm')),
                                  lambda r: (r.get('c'), r.get('x'))).items() if v[0] is not None}
    new = []
    for k, v in sorted(now.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        if prev.get(k) != v:
            new.append({'t': stamp, 's': k[0], 'n': k[1], 'tm': k[2], 'c': v[0], 'x': v[1]})
    live = {s for s in SPORTS_INJ if d.get(s)}       # a sport missing from this build clears nobody
    for k in sorted(prev, key=lambda k: tuple(str(x) for x in k)):
        if k not in now and k[0] in live:
            new.append({'t': stamp, 's': k[0], 'n': k[1], 'tm': k[2], 'c': None, 'x': None})
    return append(f'inj/{stamp[:7]}.jsonl', new)


# ---- news: data/news.json items, first sighting ---------------------------------------------------------------------

def snap_news(stamp, src=None):
    d = load(src or os.path.join(ROOT, 'data', 'news.json'), {})
    seen = {r['id'] for r in rows('news/*.jsonl')}
    new = []
    for it in d.get('items') or []:
        i = it.get('id')
        if not i or i in seen:
            continue
        seen.add(i)
        new.append({'t': stamp, 'id': i, 'd': it.get('d'), 'at': it.get('at'), 'sec': it.get('sec'), 'cat': it.get('cat'),
                    'tag': it.get('tag'), 'h': it.get('t'), 's': it.get('s'), 'w': it.get('w')})
    return append(f'news/{stamp[:7]}.jsonl', new)


# ---- depth charts: static/data/depth/<sport>.json, every slot's names in order --------------------------------------

def depth_now(d):
    out = {}
    for tm in d.get('teams') or []:
        t = tm.get('t') or tm.get('n')
        for u in tm.get('units') or []:
            for slot in u.get('s') or []:
                if not isinstance(slot, list) or len(slot) < 2:
                    continue
                names = [p[0] for p in slot[1] or [] if isinstance(p, list) and p]
                out[f'{t}|{u.get("u") or ""}|{slot[0]}'] = names
    return out


def snap_depth(stamp, sport, src=None):
    d = load(src or os.path.join(ROOT, 'static', 'data', 'depth', f'{sport}.json'), {})
    now = depth_now(d)
    if not now:
        return 0
    prev = {k: v for k, v in fold(rows(f'depth/{sport}-*.jsonl'), lambda r: r['k'], lambda r: r.get('o')).items() if v is not None}
    new = [{'t': stamp, 'k': k, 'o': v} for k, v in sorted(now.items()) if prev.get(k) != v]
    new += [{'t': stamp, 'k': k, 'o': None} for k in sorted(prev) if k not in now]
    return append(f'depth/{sport}-{stamp[:7]}.jsonl', new)


# ---- board vintages: scripts/data/moves/<board>.json hist, one a week, written once ---------------------------------

def vintages(board):
    return sorted(glob.glob(os.path.join(SNAP, 'boards', board, '*.json.gz')))


def board_state(board, season, model):
    """the board as its vintages for this season and model fold to, or None when it has none (the next one is a base)"""
    st = None
    for fn in vintages(board):
        v = load(fn, {})
        if v.get('season') != season or v.get('model') != model:
            st = None
            continue
        if v.get('base') or st is None:
            st = {}
        st.update(v.get('rows') or {})
        for g in v.get('gone') or []:
            st.pop(g, None)
    return st


def snap_board(board, path):
    h = load(path, {})
    hist = h.get('hist') or {}
    if not hist:
        return 0
    day = max(hist)
    vs = vintages(board)
    last = os.path.basename(vs[-1])[:10] if vs else None
    if last and (dt.date.fromisoformat(day) - dt.date.fromisoformat(last)).days < BOARD_DAYS:
        return 0
    season, model = h.get('season'), h.get('model')
    st = board_state(board, season, model) if vs else None
    cur = hist[day]
    base = st is None
    if base:
        ch, gone = cur, []
    else:
        ch = {k: v for k, v in cur.items() if st.get(k) != v}
        gone = sorted(k for k in st if k not in cur)
    out = {'board': board, 'date': day, 'season': season, 'model': model, 'views': h.get('views'), 'base': int(base),
           'n': len(cur), 'rows': ch, 'gone': gone}
    p = os.path.join(SNAP, 'boards', board, f'{day}.json.gz')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with gzip.GzipFile(p, 'wb', mtime=0) as f:        # mtime 0: the same vintage gives the same bytes
        f.write(json.dumps(out, separators=(',', ':'), ensure_ascii=False).encode())
    return len(ch) + len(gone)


def snap_boards():
    n = 0
    for p in sorted(glob.glob(os.path.join(ROOT, 'scripts', 'data', 'moves', '*.json'))):
        n += snap_board(os.path.basename(p)[:-5], p)
    return n


# ---- agency ledger: data/agencies.json rows, the day each first appears --------------------------------------------

def agency_key(r):
    return '|'.join(str(r.get(k) or '') for k in ('player', 'sport', 'agency', 'source'))


def snap_agency(stamp, src=None):
    d = load(src or os.path.join(ROOT, 'data', 'agencies.json'), {})
    seen = {r['k'] for r in rows('agency/rows.jsonl')}
    new = []
    for r in d.get('rows') or []:
        k = agency_key(r)
        if k in seen:
            continue
        seen.add(k)
        new.append({'t': stamp, 'k': k, 'p': r.get('player'), 'sp': r.get('sport'), 'sch': r.get('school'), 'ag': r.get('agency'),
                    'agent': r.get('agent'), 'scope': r.get('scope'), 'sd': r.get('source_date'), 'src': r.get('source')})
    return append('agency/rows.jsonl', new)


# ---- CFB recruit offers: ESPN's class lists as scripts/cfb_recruit.mjs cached them ---------------------------------

def snap_offers(stamp, cache=None):
    cache = cache or os.path.join(ROOT, 'scripts', '.cache', 'cfb')
    n = 0
    for fn in sorted(glob.glob(os.path.join(cache, 'espnclass2-*.json'))):
        y = os.path.basename(fn)[len('espnclass2-'):-5]
        cl = load(fn, [])
        if not cl:
            continue
        prev = {}
        for r in rows(f'offers/cfb-{y}.jsonl'):
            p = prev.setdefault(r['rid'], {'o': set(), 'tid': None, 'st': None, 'v': None})
            p['o'] |= set(r.get('add') or [])
            p['o'] -= set(r.get('drop') or [])
            for k in ('tid', 'st', 'v'):
                if k in r:
                    p[k] = r[k]
        new = []
        for a in cl:
            rid = str(a.get('rid') or '')
            if not rid:
                continue
            offs = {str(t) for t in a.get('offers') or [] if t}
            p = prev.get(rid, {'o': set(), 'tid': None, 'st': None, 'v': None})
            row = {'t': stamp, 'rid': rid, 'n': a.get('name')}
            add, drop = sorted(offs - p['o']), sorted(p['o'] - offs)
            if add:
                row['add'] = add
            if drop:
                row['drop'] = drop
            for k, v in (('tid', a.get('tid')), ('st', a.get('status')), ('v', a.get('visits'))):
                if v != p[k]:
                    row[k] = v
            if len(row) > 3:
                new.append(row)
        n += append(f'offers/cfb-{y}.jsonl', new)
    return n


# ---- On3 college grades and NIL valuations: scripts/.cache/cfb/on3.json from scripts/fetch_cfb.mjs ------------------

def snap_on3(stamp, src=None):
    d = load(src or os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'on3.json'), [])
    if not d:
        return 0
    prev = fold(rows('on3/cfb-*.jsonl'), lambda r: r['slug'], lambda r: (r.get('g'), r.get('r'), r.get('nil'), r.get('tm')))
    new = []
    for p in d:
        s = p.get('slug')
        if not s:
            continue
        v = (p.get('grade'), p.get('overallRank'), p.get('nil'), p.get('team'))
        if prev.get(s) != v:
            prev[s] = v
            new.append({'t': stamp, 'slug': s, 'n': p.get('name'), 'g': v[0], 'r': v[1], 'nil': v[2], 'tm': v[3]})
    return append(f'on3/cfb-{stamp[:4]}.jsonl', new)


# ---- summary ------------------------------------------------------------------------------------------------------

def status(stamp):
    logs = {}
    for name, pat, key in (('inj', 'inj/*.jsonl', lambda r: (r['s'], r['n'], r.get('tm'))),
                           ('news', 'news/*.jsonl', lambda r: r['id']),
                           ('depth', 'depth/*.jsonl', lambda r: r['k']),
                           ('agency', 'agency/rows.jsonl', lambda r: r['k']),
                           ('offers', 'offers/*.jsonl', lambda r: r['rid']),
                           ('on3', 'on3/*.jsonl', lambda r: r['slug'])):
        rs = rows(pat)
        if not rs:
            logs[name] = {'rows': 0, 'keys': 0, 'first': None, 'last': None, 'days': 0}
            continue
        first, last = rs[0]['t'], rs[-1]['t']
        logs[name] = {'rows': len(rs), 'keys': len({key(r) for r in rs}), 'first': first, 'last': last,
                      'days': (dt.date.fromisoformat(last[:10]) - dt.date.fromisoformat(first[:10])).days}
    bs = {}
    for d in sorted(glob.glob(os.path.join(SNAP, 'boards', '*'))):
        vs = vintages(os.path.basename(d))
        if vs:
            bs[os.path.basename(d)] = {'vintages': len(vs), 'first': os.path.basename(vs[0])[:10], 'last': os.path.basename(vs[-1])[:10]}
    weeks = max((v['vintages'] for v in bs.values()), default=0)
    logs['boards'] = {'boards': len(bs), 'weeks': weeks, 'by': bs}
    out = {'asof': stamp, 'logs': logs}
    old = load(OUT, {}) or {}
    if old.get('logs') == logs:         # no log moved: keep the file, so process-refresh has nothing to commit and deploy
        return old
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
        f.write('\n')
    return out


def run(mode, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    done = {}
    if mode == 'live':
        done['inj'] = snap_inj(stamp)
        done['news'] = snap_news(stamp)
    elif mode == 'daily':
        for s in DEPTH:
            done[f'depth {s}'] = snap_depth(stamp, s)
        done['boards'] = snap_boards()
        done['agency'] = snap_agency(stamp)
    elif mode == 'offers':
        done['offers'] = snap_offers(stamp)
    elif mode == 'on3':
        done['on3'] = snap_on3(stamp)
    elif mode != 'status':
        raise SystemExit(__doc__)
    if mode in ('daily', 'status'):     # one writer for the summary (process-refresh), so no two pushes race on it
        status(stamp)
    print('snapshots:', ', '.join(f'{k} {v}' for k, v in done.items()) or 'status only')


def selftest():
    import tempfile
    global SNAP, OUT
    keep = SNAP, OUT
    with tempfile.TemporaryDirectory() as tmp:
        SNAP, OUT = os.path.join(tmp, 'snaps'), os.path.join(tmp, 'snapshots.json')
        try:
            ij = os.path.join(tmp, 'inj.json')
            json.dump({'nfl': {'a b': [['Q', 'questionable', '', 'ARI']]}, 'nba': {'c d': [['O', 'out', '', 'BOS']]}}, open(ij, 'w'))
            assert snap_inj('2026-11-28T00:00:00Z', ij) == 2
            assert snap_inj('2026-11-28T00:30:00Z', ij) == 0                        # unchanged: nothing
            json.dump({'nfl': {'a b': [['O', 'out', '', 'ARI']]}, 'nba': {'x': [['O', 'out', '', 'BOS']]}}, open(ij, 'w'))
            assert snap_inj('2026-11-28T01:00:00Z', ij) == 3                        # a change, a new one, a clear
            json.dump({'nfl': {'a b': [['O', 'out', '', 'ARI']]}}, open(ij, 'w'))
            assert snap_inj('2026-11-28T01:30:00Z', ij) == 0                        # nba missing: nobody cleared
            st = fold(rows('inj/*.jsonl'), lambda r: (r['s'], r['n']), lambda r: r['c'])
            assert st[('nfl', 'a b')] == 'O' and st[('nba', 'c d')] is None and st[('nba', 'x')] == 'O'
            nj = os.path.join(tmp, 'news.json')
            json.dump({'items': [{'id': 'a', 't': 'x'}, {'id': 'b', 't': 'y'}]}, open(nj, 'w'))
            assert snap_news('2026-11-28T00:00:00Z', nj) == 2 and snap_news('2026-11-28T00:30:00Z', nj) == 0
            dj = os.path.join(tmp, 'depth.json')
            team = lambda qb: {'teams': [{'t': 'ARI', 'units': [{'u': 'offense', 's': [['QB', [[qb], ['Z']]]]}]}]}
            json.dump(team('A'), open(dj, 'w'))
            assert snap_depth('2026-11-28T00:00:00Z', 'nfl', dj) == 1 and snap_depth('2026-11-29T00:00:00Z', 'nfl', dj) == 0
            json.dump(team('B'), open(dj, 'w'))
            assert snap_depth('2026-11-30T00:00:00Z', 'nfl', dj) == 1
            assert fold(rows('depth/nfl-*.jsonl'), lambda r: r['k'], lambda r: r['o'])['ARI|offense|QB'] == ['B', 'Z']
            mv = os.path.join(tmp, 'b.json')
            json.dump({'season': '2027', 'model': 'm', 'hist': {'2026-11-20': {'p1': 50, 'p2': 40}}}, open(mv, 'w'))
            assert snap_board('b', mv) == 2
            json.dump({'season': '2027', 'model': 'm', 'hist': {'2026-11-20': {'p1': 50, 'p2': 40}, '2026-11-24': {'p1': 51, 'p2': 40}}}, open(mv, 'w'))
            assert snap_board('b', mv) == 0                                          # inside the week
            json.dump({'season': '2027', 'model': 'm', 'hist': {'2026-11-27': {'p1': 52, 'p3': 30}}}, open(mv, 'w'))
            assert snap_board('b', mv) == 3                                          # p1 moved, p3 new, p2 gone
            assert board_state('b', '2027', 'm') == {'p1': 52, 'p3': 30}
            json.dump({'season': '2028', 'model': 'm', 'hist': {'2027-08-01': {'q': 1}}}, open(mv, 'w'))
            assert snap_board('b', mv) == 1 and board_state('b', '2028', 'm') == {'q': 1}
            aj = os.path.join(tmp, 'ag.json')
            json.dump({'rows': [{'player': 'P', 'sport': 'cfb', 'agency': 'A', 'source': 'u'}]}, open(aj, 'w'))
            assert snap_agency('2026-11-28T00:00:00Z', aj) == 1 and snap_agency('2026-11-29T00:00:00Z', aj) == 0
            cdir = os.path.join(tmp, 'cache')
            os.makedirs(cdir)
            cf = os.path.join(cdir, 'espnclass2-2027.json')
            json.dump([{'rid': 1, 'name': 'R', 'offers': ['5', '6'], 'tid': None, 'status': None, 'visits': 0}], open(cf, 'w'))
            assert snap_offers('2026-11-28T00:00:00Z', cdir) == 1 and snap_offers('2026-11-29T00:00:00Z', cdir) == 0
            json.dump([{'rid': 1, 'name': 'R', 'offers': ['5', '7'], 'tid': '7', 'status': 'Committed', 'visits': 1}], open(cf, 'w'))
            assert snap_offers('2026-11-30T00:00:00Z', cdir) == 1
            r = rows('offers/cfb-2027.jsonl')[-1]
            assert r['add'] == ['7'] and r['drop'] == ['6'] and r['tid'] == '7' and r['v'] == 1
            oj = os.path.join(tmp, 'on3.json')
            json.dump([{'slug': 's', 'name': 'S', 'grade': 90, 'overallRank': 4, 'nil': 1000000, 'team': 'T'}], open(oj, 'w'))
            assert snap_on3('2026-11-28T00:00:00Z', oj) == 1 and snap_on3('2026-11-29T00:00:00Z', oj) == 0
            s = status('2026-11-30T00:00:00Z')['logs']
            assert s['inj']['rows'] == 5 and s['boards']['boards'] == 1 and s['offers']['keys'] == 1
        finally:
            SNAP, OUT = keep
    print('snapshots: self-check ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--test' in a:
        selftest()
    else:
        run(a[0] if a else 'status')
