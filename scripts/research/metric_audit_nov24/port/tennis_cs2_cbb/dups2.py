#!/usr/bin/env python3
"""Idea 8 follow-up checks on the dups.py suspects -> dups2.json: (g) a team in two games on one local date (US sports:
UTC minus 7 h; soccer: the row's own day); (h) ESEA / CS2: same ten players and same score the same day under other
team ids or game ids; tennis: alias outside round robins, and the same-score rate of re-meetings within 7 days vs the
same rate a year apart (coincidence baseline)."""
import re, csv, datetime as dt, gzip, json, os, sys
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dups as D

def local(ts):
    ts = re.sub(r'\.\d+', '', ts).replace('Z', '+00:00'); ts = ts if len(ts) > 16 else ts + ':00'
    t = dt.datetime.fromisoformat(ts[:16] + ts[16:]) if 'T' in ts else None
    if t is None: return dt.date.fromisoformat(ts[:10]).toordinal()
    if t.tzinfo is None: return t.date().toordinal()
    return (t - dt.timedelta(hours=7)).date().toordinal()

def g_check(name, rows):
    """rows: (date ord, team, game key, extra)"""
    by = defaultdict(set); ex = {}
    for d, t, k, x in rows:
        by[(d, t)].add(k); ex[k] = x
    bad = [(k, v) for k, v in by.items() if len(v) > 1]
    out = {'teamTwiceSameDate': len(bad), 'examples': [[ex[g] for g in sorted(v)] for _, v in bad[:6]]}
    print(name, out['teamTwiceSameDate'], json.dumps(out['examples'][:3])[:600], flush=True); return out

res = {}
L = json.load(gzip.open(os.path.join(D.S, 'nhl_games_hist.json.gz'), 'rt'))
res['nhl'] = g_check('nhl', [(D.od(g['day']), t, g['id'], [g['id'], g['day'], g['h'], g['a'], g['hs'], g['as']]) for g in L if g.get('final') for t in (g['h'], g['a'])])
d = json.load(gzip.open(os.path.join(D.S, 'nba_games_hist.json.gz'), 'rt'))
res['nba'] = g_check('nba', [(local(g['tip']), t, g['id'], [g['id'], g['tip'], g['h'], g['a'], g['hs'], g['as'], g.get('t')]) for g in d['games'] if g.get('fin') for t in (g['h'], g['a'])])
L = json.load(gzip.open(os.path.join(D.S, 'data', 'cbb_games_hist.json.gz'), 'rt'))
res['cbb'] = g_check('cbb', [(local(g['date']), t, g['id'], [g['id'], g['date'], g['hn'], g['an'], g.get('hs'), g.get('as')]) for g in L if g.get('hs') is not None for t in (g['home'], g['away'])])
h = json.load(gzip.open(os.path.join(D.S, 'data', 'cfb_hist_md.json.gz'), 'rt'))
res['cfb'] = g_check('cfb', [(local(g['startDate']), t, g['id'], [g['id'], g['startDate'], g['homeTeam'], g['awayTeam']]) for L in h['games'].values() for g in L if g.get('completed') for t in (g['homeId'], g['awayId'])])
res['nfl'] = g_check('nfl', [(D.od(r['gameday']), t, r['game_id'], [r['game_id']]) for r in csv.DictReader(open(os.path.join(D.S, '.cache', 'nfl', 'games.csv'))) if r['home_score'] for t in (r['home_team'], r['away_team'])])
L = json.load(gzip.open(os.path.join(D.S, 'soccer_games_hist.json.gz'), 'rt'))
res['soccer'] = g_check('soccer', [(D.od(g['day']), t, g['id'], [g['id'], g['lg'], g['day'], g['h'], g['a'], g.get('hs'), g.get('as')]) for g in L if g.get('hs') is not None for t in (g['h'], g['a'])])
# soccer alias rows (dups.py c): one club under two ids the same day in the same league with the same score
sa = defaultdict(list)
for g in L:
    if g.get('hs') is None: continue
    sa[(g['lg'], g['day'], g['hs'], g['as'], g['h'])].append(g); sa[(g['lg'], g['day'], g['hs'], g['as'], 'A' + g['a'])].append(g)
al = [[x['id'] for x in v] for v in sa.values() if len(v) > 1]
res['soccer']['aliasSameLeagueDayScoreOneSide'] = len(al); res['soccer']['aliasIds'] = al
print('soccer alias', len(al), al[:20])

# ESEA: same ten players + same score the same day
E = json.load(gzip.open(os.path.join(D.ROOT, 'research', 'esea_matches.json.gz'), 'rt'))
c = Counter(); ex = defaultdict(list)
for m in E['matches']:
    if m['f1']['id'] == 'bye' or m['f2']['id'] == 'bye' or not m.get('maps'): continue
    sc = m.get('score') or {}
    k = (dt.datetime.fromtimestamp(m['at'], dt.timezone.utc).date(), frozenset((frozenset(p[0] for p in m['f1']['roster']), frozenset(p[0] for p in m['f2']['roster']))),
         tuple(sorted((sc.get('faction1'), sc.get('faction2')), key=str)))
    c[k] += 1; ex[k].append([m['id'], m['champ'][:8], m['stage'], m['f1']['name'], m['f2']['name']])
res['esea'] = {'sameTenSameScoreSameDay': sum(v - 1 for v in c.values() if v > 1), 'examples': [ex[k] for k, v in c.items() if v > 1][:6]}
print('esea same ten + score', res['esea'])

# CS2 maps: the 90 same ten + same map + same rounds rows: same bo3 match id or another?
sys.path.insert(0, D.S)
import _cs2_players_frozen as P
import cs2_bo3
bo3 = cs2_bo3.load(); gm = {g[0]: g for g in bo3['games']}; mt = {m[0]: m for m in bo3['matches']}
M = P.Maps(bo3)
k = defaultdict(list)
for gi, g in enumerate(M.games):
    a = frozenset(int(M.p_raw[i]) for i in M.five[gi, 0]); b = frozenset(int(M.p_raw[i]) for i in M.five[gi, 1])
    k[(frozenset((a, b)), (g[7] or '').lower().removeprefix('de_'), tuple(sorted((g[4], g[5]))), g[1])].append(gi)
dd = [v for v in k.values() if len(v) > 1]
same_match = sum(1 for v in dd if len({gm[M.games[i][0]][1] for i in v}) == 1)
exs = [[[M.games[i][0], gm[M.games[i][0]][1], M.games[i][1], M.games[i][2], M.games[i][3], M.games[i][4], M.games[i][5], M.games[i][7],
         (mt.get(gm[M.games[i][0]][1]) or [None] * 11)[10]] for i in v] for v in dd[:8]]
extra_rows = sum(len(v) - 1 for v in dd)
res['cs2_maps'] = {'groups': len(dd), 'extraRows': extra_rows, 'groupsWithinOneMatch': same_match, 'examples': exs, 'maps': len(M.games)}
print('cs2', res['cs2_maps']['groups'], extra_rows, same_match, json.dumps(exs[:4])[:1500])

# tennis: alias outside RR; re-meeting same-score rate within 7 days vs 300-430 days apart
gs = []
with gzip.open('/mnt/project-files/tennis/matches.csv.gz', 'rt') as fh:
    rd = csv.reader(fh); next(rd)
    for x in rd:
        if int(x[0]) > 20261110: continue
        gs.append(x)
by = defaultdict(list)
for x in gs:
    if x[4] != 'RR' and len(x[9]) > 4: by[(x[6], x[4], x[9])].append(x)
al = [v for v in by.values() if len(v) > 1 and any(len({a[7], a[8]} & {b[7], b[8]}) == 1 for a in v for b in v if a is not b)]
bp = defaultdict(list)
for x in gs:
    if len(x[9]) > 4 and 'RET' not in x[9] and 'W/O' not in x[9].upper(): bp[frozenset((x[7], x[8]))].append(x)
near = [0, 0]; far = [0, 0]; nex = []
for v in bp.values():
    v.sort(key=lambda x: x[0])
    for i in range(len(v)):
        for j in range(i + 1, len(v)):
            dd_ = D.od(v[j][0]) - D.od(v[i][0])
            if v[j][6] == v[i][6]: continue
            same = v[i][9] == v[j][9] and v[i][7] == v[j][7]
            if dd_ <= 7:
                near[0] += 1; near[1] += same
                if same and len(nex) < 8: nex.append([v[i][:10], v[j][:10]])
            elif 300 <= dd_ <= 430:
                far[0] += 1; far[1] += same
res['tennis'] = {'aliasNonRR': len(al), 'aliasExamples': [[a[:10] for a in v] for v in al[:5]],
                 'remeet7d': near, 'remeet7d_sameScoreRate': near[1] / max(near[0], 1),
                 'remeetYear': far, 'remeetYear_sameScoreRate': far[1] / max(far[0], 1), 'sameScoreExamples': nex}
print('tennis', {k: v for k, v in res['tennis'].items() if 'xamples' not in k}, json.dumps(nex[:4])[:1200])
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dups2.json'), 'w'), indent=1, default=str)
