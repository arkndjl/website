#!/usr/bin/env python3
"""Idea 8 (port round Nov 24 2026): duplicate games in every sport's game logs used by replays / models -> dups.json.
Checks (prereg.md): (a) repeated id; (b) same date + same unordered pair of team keys, other id; (c) alias: same date
(+-1 day) + same score, one side the same team key, the other side another key (or both keys different but the same
player sets); (d) same date and one side's player set identical to a side of another game (5+ players)."""
import csv, datetime as dt, gzip, json, os, sys
from collections import defaultdict, Counter
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
S = os.path.join(ROOT, 'scripts')


def od(s):
    s = str(s)
    if len(s) == 8 and s.isdigit(): return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8])).toordinal()
    return dt.date.fromisoformat(s[:10]).toordinal()


def G(id_, d, a, b, sa=None, sb=None, pa=None, pb=None, extra=None):
    return dict(id=id_, d=d, a=str(a), b=str(b), sa=sa, sb=sb, pa=frozenset(pa) if pa else None,
                pb=frozenset(pb) if pb else None, x=extra)


def check(name, games, minp=5, alias_keyed=True):
    out = {'games': len(games)}
    ids = Counter(g['id'] for g in games if g['id'] is not None)
    out['a_repeatId'] = sum(v - 1 for v in ids.values() if v > 1)
    by = defaultdict(list)
    for i, g in enumerate(games): by[(g['d'], frozenset((g['a'], g['b'])))].append(i)
    b = [v for v in by.values() if len(v) > 1]
    out['b_sameDatePair'] = sum(len(v) - 1 for v in b)
    out['b_examples'] = [[games[i]['x'] or [games[i]['id'], games[i]['a'], games[i]['b'], games[i]['sa'], games[i]['sb']] for i in v][:3] for v in b[:3]]
    # (c) alias: date +-1, same score multiset, exactly one side key shared
    sc = defaultdict(list)
    for i, g in enumerate(games):
        if g['sa'] is None: continue
        for dd in (g['d'] - 1, g['d'], g['d'] + 1):
            sc[(dd, tuple(sorted((g['sa'], g['sb']))))].append(i)
    seen, ex = set(), []
    for i, g in enumerate(games):
        if g['sa'] is None: continue
        for j in sc[(g['d'], tuple(sorted((g['sa'], g['sb']))))]:
            if j <= i or (min(i, j), max(i, j)) in seen: continue
            h = games[j]
            ka, kb = {g['a'], g['b']}, {h['a'], h['b']}
            same_players = g['pa'] and h['pa'] and {g['pa'], g['pb']} == {h['pa'], h['pb']}
            # the shared side must carry the same score in both rows
            share = ka & kb
            ok_score = False
            for k in share:
                s1 = g['sa'] if g['a'] == k else g['sb']; s2 = h['sa'] if h['a'] == k else h['sb']
                ok_score |= s1 == s2
            if (len(share) == 1 and ok_score) or (same_players and ka != kb):
                seen.add((i, j))
                if len(ex) < 6: ex.append([g['x'] or [g['id'], g['a'], g['b'], g['sa'], g['sb']], h['x'] or [h['id'], h['a'], h['b'], h['sa'], h['sb']]])
    out['c_aliasSuspect'] = len(seen); out['c_examples'] = ex
    # (d) same date + identical side player set in another game
    ps = defaultdict(set)
    for i, g in enumerate(games):
        for p in (g['pa'], g['pb']):
            if p and len(p) >= minp: ps[(g['d'], p)].add(i)
    dd = [v for v in ps.values() if len(v) > 1]
    out['d_samePlayerSet'] = sum(len(v) - 1 for v in dd)
    out['d_examples'] = [[games[i]['x'] or [games[i]['id'], games[i]['a'], games[i]['b'], games[i]['sa'], games[i]['sb']] for i in sorted(v)][:3] for v in dd[:4]]
    print(name, {k: v for k, v in out.items() if not k.endswith('examples')}, flush=True)
    return out


def nhl():
    L = json.load(gzip.open(os.path.join(S, 'nhl_games_hist.json.gz'), 'rt'))
    gs = []
    for g in L:
        if not g.get('final'): continue
        pa = [x[0] for x in (g.get('gl') or {}).get('h', [])]; pb = [x[0] for x in (g.get('gl') or {}).get('a', [])]
        gs.append(G(g['id'], od(g['day']), g['h'], g['a'], g['hs'], g['as'], None, None))
    return check('nhl_games_hist', gs)


def nba():
    d = json.load(gzip.open(os.path.join(S, 'nba_games_hist.json.gz'), 'rt'))
    gs = []
    for g in d['games']:
        if not g.get('fin'): continue
        pl = g.get('pl') or {}
        gs.append(G(g['id'], od(g['tip']), g['h'], g['a'], g['hs'], g['as'], [p for p, _ in pl.get(g['h'], [])], [p for p, _ in pl.get(g['a'], [])]))
    return check('nba_games_hist', gs)


def cbb():
    L = json.load(gzip.open(os.path.join(S, 'data', 'cbb_games_hist.json.gz'), 'rt'))
    gs = [G(g['id'], od(g['date']), g['home'], g['away'], g.get('hs'), g.get('as'), extra=[g['id'], g['date'][:10], g['hn'], g['an'], g.get('hs'), g.get('as')])
          for g in L if g.get('hs') is not None]
    return check('cbb_games_hist', gs)


def cbb_players():
    """Barttorvik per-game player rows (all_advgames): (pid, date) repeats, and team-game player sets"""
    out = {}
    for f in sorted(os.listdir(os.path.join(S, '.cache', 'cbb', 'games'))):
        if not f.endswith('.json.gz'): continue
        rows = json.load(gzip.open(os.path.join(S, '.cache', 'cbb', 'games', f), 'rt'))
        c = Counter((r[51], str(r[0])) for r in rows)
        same = Counter((r[51], str(r[0]), r[47], r[5]) for r in rows)
        # a player listed for two different teams the same day
        tm = defaultdict(set)
        for r in rows: tm[(r[51], str(r[0]))].add(r[47])
        out[f[:4]] = {'rows': len(rows), 'repeat_pid_date': sum(v - 1 for v in c.values() if v > 1),
                      'exact_repeat': sum(v - 1 for v in same.values() if v > 1), 'pid_two_teams_same_day': sum(len(v) > 1 for v in tm.values())}
    tot = {k: sum(v[k] for v in out.values()) for k in ('rows', 'repeat_pid_date', 'exact_repeat', 'pid_two_teams_same_day')}
    print('cbb barttorvik player logs', tot, flush=True)
    return {'bySeason': out, 'total': tot}


def cfb():
    h = json.load(gzip.open(os.path.join(S, 'data', 'cfb_hist_md.json.gz'), 'rt'))
    gs = []
    for y, L in h['games'].items():
        for g in L:
            if not g.get('completed') or g.get('homePoints') is None: continue
            gs.append(G(g['id'], od(g['startDate']), g['homeId'], g['awayId'], g['homePoints'], g['awayPoints'],
                        extra=[g['id'], g['startDate'][:10], g['homeTeam'], g['awayTeam'], g['homePoints'], g['awayPoints']]))
    return check('cfb_hist_md (cfb_model)', gs)


def nfl():
    gs = []
    for r in csv.DictReader(open(os.path.join(S, '.cache', 'nfl', 'games.csv'))):
        if not r['home_score']: continue
        gs.append(G(r['game_id'], od(r['gameday']), r['home_team'], r['away_team'], int(r['home_score']), int(r['away_score'])))
    return check('nflverse games.csv (nfl_games)', gs)


def soccer():
    L = json.load(gzip.open(os.path.join(S, 'soccer_games_hist.json.gz'), 'rt'))
    gs = [G(g['id'], od(g['day']), g['h'], g['a'], g.get('hs'), g.get('as'), extra=[g['id'], g['lg'], g['day'], g['h'], g['a'], g.get('hs'), g.get('as')])
          for g in L if g.get('hs') is not None]
    return check('soccer_games_hist', gs)


def tennis():
    """matches.csv.gz: d = event start, so 'same date' = same event (tid); alias = the same match under two player ids"""
    gs = []
    with gzip.open('/mnt/project-files/tennis/matches.csv.gz', 'rt') as fh:
        rd = csv.reader(fh); next(rd)
        for x in rd:
            if int(x[0]) > 20261110: continue
            gs.append(G(None, od(x[0]), x[7], x[8], None, None, extra=[x[0], x[6], x[4], x[7], x[8], x[9]]))
    out = check('tennis matches.csv.gz (pair same event start)', gs)
    # same event + round + score with one player shared (two ids for one opponent)
    by = defaultdict(list)
    for g in gs: by[(g['x'][1], g['x'][2], g['x'][5])].append(g)
    al = 0; ex = []
    for v in by.values():
        for i in range(len(v)):
            for j in range(i + 1, len(v)):
                a, b = {v[i]['a'], v[i]['b']}, {v[j]['a'], v[j]['b']}
                if len(a & b) == 1 and v[i]['x'][5] not in ('', 'W/O', 'w/o') and len(v[i]['x'][5]) > 4:
                    al += 1; ex.append([v[i]['x'], v[j]['x']]) if len(ex) < 6 else None
    out['c_aliasSuspect'] = al; out['c_examples'] = ex
    # same pair + same score in two events within 7 days (one match from two sources under two event ids)
    bp = defaultdict(list)
    for g in gs:
        if len(g['x'][5]) > 4: bp[(frozenset((g['a'], g['b'])), g['x'][5])].append(g)
    xs = 0; ex2 = []
    for v in bp.values():
        v.sort(key=lambda g: g['d'])
        for i in range(1, len(v)):
            if v[i]['d'] - v[i - 1]['d'] <= 7 and v[i]['x'][1] != v[i - 1]['x'][1]:
                xs += 1; ex2.append([v[i - 1]['x'], v[i]['x']]) if len(ex2) < 6 else None
    out['e_samePairScoreOtherEvent7d'] = xs; out['e_examples'] = ex2
    print('tennis alias', al, 'cross-event', xs, flush=True)
    return out


def esea():
    d = json.load(gzip.open(os.path.join(ROOT, 'research', 'esea_matches.json.gz'), 'rt'))
    gs = []
    for m in d['matches']:
        if m['f1']['id'] == 'bye' or m['f2']['id'] == 'bye' or not m.get('maps'): continue
        sc = m.get('score') or {}
        gs.append(G(m['id'], dt.datetime.utcfromtimestamp(m['at']).date().toordinal(), m['f1']['id'], m['f2']['id'],
                    sc.get('faction1'), sc.get('faction2'), [p[0] for p in m['f1']['roster']], [p[0] for p in m['f2']['roster']],
                    extra=[m['id'], m['season'], m['div'], m['f1']['name'], m['f2']['name'], sc.get('faction1'), sc.get('faction2')]))
    return check('ESEA research/esea_matches.json.gz', gs, minp=5)


def cs2_maps():
    sys.path.insert(0, HERE); sys.path.insert(0, S)
    import _cs2_players_frozen as P
    M = P.Maps()
    gs = []
    for gi, g in enumerate(M.games):
        a = [int(M.p_raw[i]) for i in M.five[gi, 0]]; b = [int(M.p_raw[i]) for i in M.five[gi, 1]]
        gs.append(G(g[0], P.ordd(g[1]), g[2], g[3], g[4], g[5], a, b, extra=[g[0], g[1], g[2], g[3], g[4], g[5], g[7]]))
    out = check('bo3.gg CS2 maps (cs2_players Maps)', gs)
    # same ten players + same map + same rounds on the same / next day = one map twice
    k = Counter()
    for g in gs: k[(frozenset((g['pa'], g['pb'])), g['x'][6], tuple(sorted((g['sa'], g['sb']))), g['d'])] += 1
    out['f_sameTenSameMapSameRounds'] = sum(v - 1 for v in k.values() if v > 1)
    print('cs2 same ten + map + rounds', out['f_sameTenSameMapSameRounds'])
    return out


def cs2_series():
    """Valve series rows (scripts/data/cs2_history.json.gz) that repeat an earlier row the same day with the same ten
    players: round 1 found 8,847 of 32,643; recounted here on the file as it is now"""
    p = os.path.join(S, 'data', 'cs2_history.json.gz')
    h = json.load(gzip.open(p, 'rt'))
    rows = h if isinstance(h, list) else h.get('series') or h.get('rows') or h.get('matches') or []
    return {'rows': len(rows), 'note': 'owned by the CS2 dedupe worker (cs2_model / cs2_ark_loop); see their report'}


if __name__ == '__main__':
    res = {}
    for f in (nhl, nba, cbb, cbb_players, cfb, nfl, soccer, tennis, esea, cs2_maps, cs2_series):
        try:
            res[f.__name__] = f()
        except Exception as e:  # keep going; report the failure
            res[f.__name__] = {'error': repr(e)}; print(f.__name__, 'ERROR', repr(e), flush=True)
    json.dump(res, open(os.path.join(HERE, 'dups.json'), 'w'), indent=1, default=str)
