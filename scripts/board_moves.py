# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Weekly movement on the player and prospect boards: each row gets its board metric as of the sport's last weekly
post day (scripts/rank_moves.py POST: CBB Mon, NBA Tue, NFL Thu, soccer Fri, tennis Sat, CS2 Sun; on the post day
itself, the one a week back), or 7 days back for a sport with no post day (NHL, hockey prospects).

Run after a board's builders, before the commit. Each board keeps its history in scripts/data/moves/<board>.json
({season, model, hist: {date: {id: value}}}), stored only when it changes and pruned to the week window plus the snapshot
just before it (scripts/rank_moves.py does the same for the ARK Rankings). Rows get `w0` (the value as of the
last snapshot on or before that day); the row list's file gets `wkFrom` (that snapshot's date). A row with no `w0` while
`wkFrom` is set is new to the board. The page works out the change: FV boards show FV now minus `w0`; leaderboards
re-rank the rows in view by `w0` and show the rank change, so the move counts within the filters, like RK.

  python3 scripts/board_moves.py nfl nba ...   update those boards (all when none named)
  python3 scripts/board_moves.py --seed         rebuild every history from git (needs a non-shallow fetch)
  python3 scripts/board_moves.py r-* cbb-*      the view tables (rookies-shaped tabs, VIEWS): rows get `w0`, one
                                                value per view in the season's `wkV`, the season gets `wkFrom`
  python3 scripts/board_moves.py --test         self-check
"""
import datetime as dt
import glob
import hashlib
import io
import json
import os
import subprocess
import sys
import tokenize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rank_moves import POST, cutoff, today as et_today   # noqa: E402  (the weekly post days)

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


# FV boards: the files that set the grades (fit, display scale, the script that writes the board). A change in their
# hash between two runs is a model change, and the earlier snapshots are regraded by it (regrade)
MODEL = {
    'cbb': ('data/cbb_fit.json', 'data/cbb_live_fit.json', 'data/fv_dist.json', 'data/fv_scale.json',
            'scripts/fetch_cbb.py', 'scripts/cbb_live.py'),
    'hockey': ('data/hockey_fit.json', 'data/fv_scale.json', 'scripts/hockey_prospects.py'),
    'soccerp': ('data/soccer_prospects_fit.json', 'data/fv_scale.json', 'scripts/soccer_prospects.py'),
    'tennisp': ('data/tennis_prospects_fit.json', 'data/fv_scale.json', 'scripts/tennis_prospects.py'),
    'cs2': ('data/cs2_players_fit.json', 'data/fv_scale.json', 'scripts/cs2_players.py'),
}


def fingerprint(board, rev=None):
    """hash of the board's MODEL files (a script by its tokens, comments left out), from the working tree or (rev) a git commit;
    None for a board with none"""
    files = MODEL.get(board)
    if not files:
        return None
    h = hashlib.sha256()
    for f in files:
        if rev:
            r = subprocess.run(['git', 'show', f'{rev}:{f}'], cwd=ROOT, capture_output=True)
            b = r.stdout if r.returncode == 0 else b''
        else:
            p = os.path.join(ROOT, f)
            b = open(p, 'rb').read() if os.path.exists(p) else b''
        if f.endswith('.py'):                # the code, not its comments or layout
            try:
                b = ' '.join(t.string for t in tokenize.tokenize(io.BytesIO(b).readline)
                             if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING)).encode()
            except (tokenize.TokenError, SyntaxError):
                pass
        h.update(f.encode() + b'\0' + hashlib.sha256(b).digest())
    return h.hexdigest()[:16]


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


REGRADE = .5     # FV boards: more than half the grades moving in one run is a model change even when MODEL misses it


def graded(spec):
    """the row lists ranked by FV (the ones a model change re-grades)"""
    return {'.'.join(path) for path, _, val, *_ in spec if val == 'fv'}


def regrade(hist, cur, names, changed=False):
    """a model change re-grades the earlier snapshots by the same shift, so the week's moves stay player moves (the
    change on the re-grade day itself is lost). changed: the MODEL fingerprint moved since the last run; otherwise
    only a run that moves more than REGRADE of the grades counts. leaderboard metrics move every day and are left
    as they are"""
    last = hist[max(hist)]
    for name, now in cur.items():
        if name not in names:
            continue
        was = last.get(name) or {}
        com = [k for k in now if k in was]
        if len(com) < 20 or (not changed and sum(now[k] != was[k] for k in com) <= REGRADE * len(com)):
            continue
        shift = {k: now[k] - was[k] for k in com}
        for snap_ in hist.values():
            s = snap_.get(name) or {}
            for k, dv in shift.items():
                if k in s:
                    s[k] = round(s[k] + dv, 4)


def step(h, cur, day, days=DAYS, fv=(), sport=None, model=None):
    """adds today's snapshot to history h (on change), prunes, returns (h, base date or None). model: the board's
    MODEL fingerprint now, kept in h['model']"""
    hist = dict(sorted((h.get('hist') or {}).items()))
    if fv and hist:
        regrade(hist, cur, fv, changed=bool(model and h.get('model') and model != h['model']))
    if model:
        h['model'] = model
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


# view tables (the rookies-shaped tabs: scripts/rookies.py, scripts/cbb_tabs.py): {views, seasons: [{s, rows}]}, ranked by
# whichever view is picked. board -> (file, the sport whose post day it counts from, the board whose MODEL re-grades its FV)
VIEWS = {
    'r-nba': ('static/data/rookies/nba.json', 'nba', None),
    'r-nfl': ('static/data/rookies/nfl.json', 'nfl', None),
    'r-nhl': ('static/data/rookies/nhl.json', 'nhl', None),
    'r-soccer': ('static/data/rookies/soccer.json', 'soccer', None),
    'r-cbb': ('static/data/rookies/cbb.json', 'cbb', 'cbb'),
    'r-cfb': ('static/data/rookies/cfb.json', 'cfb', None),
    'r-hockey': ('static/data/rookies/hockey.json', 'hockey', 'hockey'),
    'r-soccerp': ('static/data/rookies/soccerp.json', 'soccerp', 'soccerp'),
    'cbb-draft': ('static/data/cbb/draft.json', 'cbb', 'cbb'),
    'cbb-war': ('static/data/cbb/war.json', 'cbb', None),
    'cbb-stats': ('static/data/cbb/stats.json', 'cbb', None),
    'cbb-breakouts': ('static/data/cbb/breakouts.json', 'cbb', None),
}


def vkey(r):
    return f"{r.get('n')}|{r.get('tm')}"


def vsnap(S, views):
    """{id: [value per view]} for the season's rows (a row with no value in any view left out)"""
    out = {}
    for r in S.get('rows') or []:
        vs = [_num(r.get(v)) for v in views]
        if any(v is not None for v in vs):
            out[vkey(r)] = [None if v is None else round(v, 3) for v in vs]
    return out


def vstep(h, cur, views, day, sport, model=None):
    """step() for a view table: one list of value arrays per snapshot. A board with a post day keeps only the base and the
    newest snapshot (the newest is the only one that can become the next base); a rolling one keeps the 7-day window"""
    hist = dict(sorted((h.get('hist') or {}).items()))
    was = h.get('views')
    if hist and was != views:              # a view added or dropped: the snapshots are re-laid to the new views
        ix = [was.index(v) if was and v in was else None for v in views]
        hist = {k: {i: [None if j is None or j >= len(a) else a[j] for j in ix] for i, a in s_.items()} for k, s_ in hist.items()}
    fv = [i for i, v in enumerate(views) if v == 'fv']
    if fv and hist:
        last = hist[max(hist)]
        com = [k for k in cur if k in last]
        for i in fv:
            pairs = [(k, cur[k][i], last[k][i]) for k in com if cur[k][i] is not None and last[k][i] is not None]
            moved = sum(a != b for _, a, b in pairs)
            if len(pairs) >= 20 and ((model and h.get('model') and model != h['model']) or moved > REGRADE * len(pairs)):
                shift = {k: a - b for k, a, b in pairs}
                for s_ in hist.values():
                    for k, dv in shift.items():
                        if k in s_ and s_[k][i] is not None:
                            s_[k][i] = round(s_[k][i] + dv, 3)
    if model:
        h['model'] = model
    h['views'] = views
    if not hist or hist[max(hist)] != cur:
        hist[day.isoformat()] = cur
    cut = cutoff(day, sport).isoformat()
    back = [k for k in hist if k <= cut]
    post = sport in POST
    keep = {k for k in hist if k > cut}
    if post and keep:
        keep = {max(keep)}
    if back:
        keep.add(back[-1])
    h['hist'] = {k: hist[k] for k in sorted(keep)}
    return h, (back[-1] if back else None)


def vmark(S, views, base, since):
    """rows get `w0` (their values as of `since`, one per view in the season's `wkV`); a name that changed teams is
    matched by name when it is the only one"""
    S.pop('wkFrom', None); S.pop('wkV', None)
    for r in S.get('rows') or []:
        r.pop('w0', None)
    if not since or base is None:
        return
    byname, dup = {}, set()
    for k in base:
        n = k.rsplit('|', 1)[0]
        if n in byname:
            dup.add(n)
        byname[n] = k
    for r in S.get('rows') or []:
        k = vkey(r)
        if k not in base and r.get('n') in byname and r.get('n') not in dup:
            k = byname[r['n']]
        if k in base:
            r['w0'] = base[k]
    S['wkFrom'], S['wkV'] = since, views


def vupdate(board, day=None, d=None, h=None, write=True):
    path, sport, mb = VIEWS[board]
    full = os.path.join(ROOT, path)
    if d is None and not os.path.exists(full):
        print(board, 'no data file'); return None
    raw = open(full, encoding='utf-8').read() if d is None else ''
    d = d if d is not None else json.loads(raw)
    S = (d.get('seasons') or [None])[0]
    if not S:
        return None
    views = [v[0] for v in d.get('views') or []]
    h = h if h is not None else load_hist(board)
    s = str(S.get('s'))
    if h.get('season') != s:
        h = {'season': s, 'hist': {}}
    day = day or et_today()
    h, since = vstep(h, vsnap(S, views), views, day, sport, model=fingerprint(mb) if mb else None)
    vmark(S, views, h['hist'].get(since) if since else None, cutoff(day, sport).isoformat() if since else None)
    if write:
        with open(full, 'w', encoding='utf-8') as f:
            f.write(json.dumps(d, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + ('\n' if raw.endswith('\n') else ''))
        save_hist(board, h)
        print(board, path, 'from', since, 'snapshots', len(h['hist']), 'rows with w0', sum('w0' in r for r in S['rows']))
    return d, h


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
    h, since = step(h, snap(d, spec), day, fv=graded(spec), sport=board, model=fingerprint(board))
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
            yield day, hsh, json.loads(subprocess.run(['git', 'show', f'{hsh}:{path}'], cwd=ROOT, capture_output=True,
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
        for day, rev, d in _git_versions(path, since):
            if dt.date.fromisoformat(day) >= today:
                continue
            s = season_of(d, path)
            if h.get('season') != s:
                h = {'season': s, 'hist': {}}
            h, _ = step(h, snap(d, spec), dt.date.fromisoformat(day), fv=graded(spec), sport=board, model=fingerprint(board, rev))
        save_hist(board, h)
        update(board, today)


def vseed(boards):
    today = et_today()
    since = (today - dt.timedelta(days=DAYS + 3)).isoformat()
    for board in boards:
        path, sport, mb = VIEWS[board]
        h = {}
        for day, rev, d in _git_versions(path, since):
            day = dt.date.fromisoformat(day)
            S = (d.get('seasons') or [None])[0]
            if day >= today or not S:
                continue
            views = [v[0] for v in d.get('views') or []]
            if h.get('season') != str(S.get('s')):
                h = {'season': str(S.get('s')), 'hist': {}}
            h, _ = vstep(h, vsnap(S, views), views, day, sport, model=fingerprint(mb, rev) if mb else None)
        save_hist(board, h)
        vupdate(board, today)


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
    # a model change that moves under half the grades (most rows at the floor) is regraded on the fingerprint
    fb = {'rows': [{'id': str(i), 'fv': 20 if i < 30 else 50} for i in range(40)]}
    spec = [(('rows',), 'id', 'fv')]
    h4, _ = step({}, snap(fb, spec), dt.date(2026, 11, 1), fv={'rows'}, model='a')
    for r in fb['rows'][30:]:
        r['fv'] = 55
    h4, since = step(h4, snap(fb, spec), dt.date(2026, 11, 9), fv={'rows'}, model='b')
    mark(fb, spec, h4['hist'][since], since)
    assert h4['model'] == 'b' and all(r['w0'] == r['fv'] for r in fb['rows']), fb['rows'][-1]
    for r in fb['rows'][30:]:                                # same model, same share: player moves, kept
        r['fv'] = 58
    h4, since = step(h4, snap(fb, spec), dt.date(2026, 11, 10), fv={'rows'}, model='b')
    mark(fb, spec, h4['hist'][since], since)
    assert fb['rows'][-1]['w0'] == 55 and fb['rows'][0]['w0'] == 20, fb['rows'][-1]
    h5, _ = step({}, snap(fb, spec), dt.date(2026, 11, 1), fv={'rows'})   # no fingerprint stored yet: the share rule
    for r in fb['rows'][30:]:
        r['fv'] = 60
    h5, since = step(h5, snap(fb, spec), dt.date(2026, 11, 9), fv={'rows'}, model='c')
    mark(fb, spec, h5['hist'][since], since)
    assert fb['rows'][-1]['w0'] == 58 and h5['model'] == 'c', fb['rows'][-1]
    assert fingerprint('tennisp') and fingerprint('nfl') is None
    del BOARDS['_t']
    # view tables: a post-day board keeps the base and the newest snapshot; a traded player is matched by name
    vt = {'views': [['fv', 'FV'], ['war', 'WAR']], 'seasons': [{'s': 2027, 'rows': [
        {'n': 'A', 'tm': 'X', 'fv': 50, 'war': 1.0}, {'n': 'B', 'tm': 'Y', 'fv': 40, 'war': 2.0}]}]}
    V = ['fv', 'war']
    S = vt['seasons'][0]
    hv = {}
    for i in range(10):                     # Nov 1 2026 is a Sunday; cbb posts Monday
        S['rows'][1]['war'] = 2.0 + i
        if i == 6:
            S['rows'][0]['tm'] = 'Z'
        hv, since = vstep(hv, vsnap(S, V), V, dt.date(2026, 11, 1) + dt.timedelta(days=i), 'cbb')
    vmark(S, V, hv['hist'][since], since)
    assert since == '2026-11-09' and len(hv['hist']) == 2, (since, list(hv['hist']))
    assert S['rows'][1]['w0'] == [40, 10.0] and S['rows'][0]['w0'] == [50, 1.0] and S['wkV'] == V, S
    print('board_moves ok')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--test' in sys.argv:
        test()
    elif '--seed' in sys.argv:
        seed([b for b in args or list(BOARDS) if b in BOARDS])
        vseed([b for b in args or list(VIEWS) if b in VIEWS])
    else:
        for b in args or list(BOARDS) + list(VIEWS):
            if b in VIEWS:
                vupdate(b)
            elif b.endswith('*'):               # a prefix: every view table of it (r-*, cbb-*)
                for v in VIEWS:
                    if v.startswith(b[:-1]):
                        vupdate(v)
            else:
                update(b)
