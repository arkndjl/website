# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Weekly movement on the player and prospect boards: each row gets its board metric as of the sport's last weekly
post day (scripts/rank_moves.py POST: CBB Mon, NBA Tue, NFL Thu, soccer Fri, tennis Sat, CS2 Sun; on the post day
itself, the one a week back), or 7 days back for a sport with no post day (NHL, hockey prospects).

Run after a board's builders, before the commit. Each board keeps its history in scripts/data/moves/<board>.json
({season, hist: {date: {id: value}}}), stored only when it changes and pruned to the week window plus the snapshot
just before it (scripts/rank_moves.py does the same for the ARK Rankings). Rows get `w0` (the value as of the
last snapshot on or before that day); the row list's file gets `wkFrom` (that snapshot's date). A row with no `w0` while
`wkFrom` is set is new to the board. The page works out the change: FV boards show FV now minus `w0`; leaderboards
re-rank the rows in view by `w0` and show the rank change, so the move counts within the filters, like RK.

  python3 scripts/board_moves.py nfl nba ...   update those boards (all when none named)
  python3 scripts/board_moves.py --seed         rebuild every history from git (needs a non-shallow fetch)
  python3 scripts/board_moves.py --test         self-check
"""
import datetime as dt
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rank_moves import cutoff, today as et_today   # noqa: E402  (the weekly post days, POST)

DAYS = 7
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, 'scripts', 'data', 'moves')


def latest(pattern):
    fs = sorted(glob.glob(os.path.join(ROOT, pattern)))
    return os.path.relpath(fs[-1], ROOT) if fs else None


def _num(v):
    return None if v is None or isinstance(v, bool) or v != v else round(float(v), 4)


# board -> (data file (relative; a glob takes the newest season file), [(list path, id field, value field[, rank])])
# a list path is keys into the file. rank: the page renders server-side and ranks by the value, so the rows also get
# `wr`, their rank by w0 among the board's rows (the rank change = wr - rk)
BOARDS = {
    'cbb': ('static/data/cbb-all.json', [((), ('name', 'team'), 'fv')]),
    'nfl': ('static/data/nfl-war.json', [(('players',), 'id', 'waa')]),
    'nba': ('static/data/nba-xpm/20*.json', [(('players',), 'id', 'vorx')]),
    'nhl': ('static/data/nhl-war/20*.json', [(('players',), 'id', 'war')]),
    'soccer': ('static/data/soccer-war/20*.json', [(('players',), 'p', 'gar')]),
    'hockey': ('data/hockey.json', [(('board',), 'name', 'fv'), (('pipe',), 'id', 'fv')]),
    'soccerp': ('data/soccer_prospects.json', [(('board',), 'id', 'fv')]),
    'tennisp': ('data/tennis_prospects.json', [(('atp', 'board'), 'id', 'fv'), (('wta', 'board'), 'id', 'fv')]),
    'cs2': ('data/cs2_players.json', [(('board',), 'id', 'rwa', True), (('prospects',), 'id', 'fv')]),
}


class Columnar:
    """cbb-all.json: {cols, rows: [[...]]}; rows read as dicts, `w0` written back as a column"""
    def __init__(self, d):
        self.d, self.ci = d, {c: i for i, c in enumerate(d['cols'])}

    def get(self, row, k):
        i = self.ci.get(k)
        return row[i] if i is not None and i < len(row) else None

    def put(self, row, k, v):
        if k not in self.ci:
            self.ci[k] = len(self.d['cols']); self.d['cols'].append(k)
        i = self.ci[k]
        while len(row) <= i:
            row.append(None)
        row[i] = v


def lists(d, spec):
    """(holder, rows, get, put) for each row list the board names"""
    for path, idf, val, *rk in spec:
        if not path:                        # columnar file
            c = Columnar(d)
            yield d, d['rows'], c.get, c.put, idf, val, '', False
            continue
        x = d
        for k in path[:-1]:
            x = x.get(k) or {}
        rows = x.get(path[-1])
        if isinstance(rows, list):
            yield x, rows, lambda r, k: r.get(k), lambda r, k, v: r.__setitem__(k, v), idf, val, '.'.join(path), bool(rk)


def rid(get, r, idf):
    return '|'.join(str(get(r, k)) for k in idf) if isinstance(idf, tuple) else str(get(r, idf))


def season_of(d, path):
    return str(d.get('season') or os.path.basename(path).split('.')[0])


def snap(d, spec):
    out = {}
    for _, rows, get, _, idf, val, name, _ in lists(d, spec):
        out[name] = {rid(get, r, idf): v for r in rows for v in [_num(get(r, val))] if v is not None}
    return out


REGRADE = .5     # FV boards: more than half the grades moving in one run is a model change, not the players


def graded(spec):
    """the row lists ranked by FV (the ones a model change re-grades)"""
    return {'.'.join(path) for path, _, val, *_ in spec if val == 'fv'}


def regrade(hist, cur, names):
    """a model change re-grades the earlier snapshots by the same shift, so the week's moves stay player moves (the
    change on the re-grade day itself is lost). leaderboard metrics move every day and are left as they are"""
    last = hist[max(hist)]
    for name, now in cur.items():
        if name not in names:
            continue
        was = last.get(name) or {}
        com = [k for k in now if k in was]
        if len(com) < 20 or sum(now[k] != was[k] for k in com) <= REGRADE * len(com):
            continue
        shift = {k: now[k] - was[k] for k in com}
        for snap_ in hist.values():
            s = snap_.get(name) or {}
            for k, dv in shift.items():
                if k in s:
                    s[k] = round(s[k] + dv, 4)


def step(h, cur, day, days=DAYS, fv=(), sport=None):
    """adds today's snapshot to history h (on change), prunes, returns (h, base date or None)"""
    hist = dict(sorted((h.get('hist') or {}).items()))
    if fv and hist:
        regrade(hist, cur, fv)
    if not hist or hist[max(hist)] != cur:
        hist[day.isoformat()] = cur
    cut = cutoff(day, sport, days).isoformat()
    back = [k for k in hist if k <= cut]
    h['hist'] = {k: v for k, v in hist.items() if k > cut or (back and k == back[-1])}
    return h, (back[-1] if back else None)


def mark(d, spec, base, since):
    for holder, rows, get, put, idf, val, name, rk in lists(d, spec):
        b = (base or {}).get(name) or {}
        for r in rows:
            v = b.get(rid(get, r, idf)) if since else None
            if v is not None or get(r, 'w0') is not None:
                put(r, 'w0', v)
        if rk:                              # competition rank by w0 among the rows that have one
            vs = sorted((get(r, 'w0') for r in rows if get(r, 'w0') is not None), reverse=True)
            first = {}
            for i, v in enumerate(vs):
                first.setdefault(v, i + 1)
            for r in rows:
                v = get(r, 'w0')
                put(r, 'wr', first[v] if v is not None else None)
        holder['wkFrom'] = since


def load_hist(board):
    p = os.path.join(HIST, board + '.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def save_hist(board, h):
    os.makedirs(HIST, exist_ok=True)
    with open(os.path.join(HIST, board + '.json'), 'w') as f:
        json.dump(h, f, separators=(',', ':'), allow_nan=False)


def update(board, day=None, d=None, h=None, write=True):
    pat, spec = BOARDS[board]
    path = latest(pat) if '*' in pat else pat
    if not path or not os.path.exists(os.path.join(ROOT, path)):
        print(board, 'no data file'); return None
    full = os.path.join(ROOT, path)
    raw = open(full, encoding='utf-8').read() if d is None else ''
    d = d if d is not None else json.loads(raw)
    h = h if h is not None else load_hist(board)
    s = season_of(d, path)
    if h.get('season') != s:                # a new season (or a first run) starts the history over
        h = {'season': s, 'hist': {}}
    day = day or et_today()
    h, since = step(h, snap(d, spec), day, fv=graded(spec), sport=board)
    # wkFrom names the post day the moves count from (the values are the last snapshot on or before it)
    mark(d, spec, h['hist'].get(since) if since else None, cutoff(day, board).isoformat() if since else None)
    if write:
        with open(full, 'w', encoding='utf-8') as f:       # the builders' format: compact, UTF-8 as is
            f.write(json.dumps(d, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + ('\n' if raw.endswith('\n') else ''))
        save_hist(board, h)
        n = sum(1 for _, rows, get, *_ in lists(d, spec) for r in rows if get(r, 'w0') is not None)
        print(board, path, 'from', since, 'snapshots', len(h['hist']), 'rows with w0', n)
    return d, h


def _git_versions(path, since):
    revs = subprocess.run(['git', 'log', '--format=%H %cI', f'--since={since}', '--', path], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.split('\n')
    by_day = {}
    for line in reversed([x for x in revs if x]):          # oldest first; the day's last version wins
        hsh, when = line.split()
        by_day[when[:10]] = hsh
    for day, hsh in sorted(by_day.items()):
        try:
            yield day, json.loads(subprocess.run(['git', 'show', f'{hsh}:{path}'], cwd=ROOT, capture_output=True,
                                                 text=True, check=True).stdout)
        except (subprocess.CalledProcessError, ValueError):
            continue


def seed(boards):
    today = et_today()
    since = (today - dt.timedelta(days=DAYS + 3)).isoformat()
    for board in boards:
        pat, spec = BOARDS[board]
        path = latest(pat) if '*' in pat else pat
        if not path:
            continue
        h = {}
        for day, d in _git_versions(path, since):
            if dt.date.fromisoformat(day) >= today:
                continue
            s = season_of(d, path)
            if h.get('season') != s:
                h = {'season': s, 'hist': {}}
            h, _ = step(h, snap(d, spec), dt.date.fromisoformat(day), fv=graded(spec), sport=board)
        save_hist(board, h)
        update(board, today)


def test():
    d = {'season': 1, 'players': [{'id': 'a', 'v': 1.0}, {'id': 'b', 'v': 2.0}]}
    BOARDS['_t'] = ('x', [(('players',), 'id', 'v')])
    h = {}
    for i in range(10):
        d['players'][0]['v'] = 1.0 + i
        if i == 5:
            d['players'].append({'id': 'c', 'v': 9.0})
        h, since = step(h if h else {'season': '1', 'hist': {}}, snap(d, BOARDS['_t'][1]), dt.date(2026, 11, 1) + dt.timedelta(days=i))
        mark(d, BOARDS['_t'][1], h['hist'].get(since) if since else None, since)
    a, b, c = d['players']
    assert d['wkFrom'] == '2026-11-03', d['wkFrom']
    assert a['w0'] == 3.0 and b['w0'] == 2.0 and c.get('w0') is None, d
    assert len(h['hist']) == 8, list(h['hist'])            # the 7 days in the window plus the base
    cc = {'cols': ['name', 'team', 'fv'], 'rows': [['x', 'T', 50], ['y', 'T', 40]]}
    spec = [((), ('name', 'team'), 'fv')]
    h2, since = step({}, snap(cc, spec), dt.date(2026, 11, 1))
    h2, since = step(h2, snap(cc, spec), dt.date(2026, 11, 9))
    mark(cc, spec, h2['hist'][since], since)
    assert cc['cols'][-1] == 'w0' and cc['rows'][0][3] == 50 and cc['wkFrom'] == '2026-11-01', cc
    rr = {'players': [{'id': 'a', 'v': 3.0, 'rk': 1}, {'id': 'b', 'v': 2.0, 'rk': 2}]}
    spec = [(('players',), 'id', 'v', True)]
    h3, since = step({}, snap(rr, spec), dt.date(2026, 11, 1))
    rr['players'][0]['v'], rr['players'][1]['v'] = 1.0, 4.0
    h3, since = step(h3, snap(rr, spec), dt.date(2026, 11, 9))
    mark(rr, spec, h3['hist'][since], since)
    assert [p['wr'] for p in rr['players']] == [1, 2], rr
    del BOARDS['_t']
    print('board_moves ok')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--test' in sys.argv:
        test()
    elif '--seed' in sys.argv:
        seed(args or list(BOARDS))
    else:
        for b in args or list(BOARDS):
            update(b)
