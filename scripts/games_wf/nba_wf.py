"""NBA walk-forward rows for the games page picks (scripts/games_picks.py): run python3 scripts/nba_games.py --fit first (it writes scripts/.cache/nba/wf_preds.json), then this; opening totals from the ESPN odds cache. Writes scripts/data/games_wf/nba.json.gz."""
import sys, os, json, gzip, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import nba_games as N, nba_espn as E
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'games_wf', 'nba.json.gz')
rows = json.load(open(os.path.join(N.ROOT, 'scripts', '.cache', 'nba', 'wf_preds.json')))

# opening totals don't depend on the model: without the ESPN odds cache (a fresh clone), keep the last file's
PREV = {r['id']: r.get('To') for r in json.load(gzip.open(OUT, 'rt'))} if os.path.exists(OUT) else {}


def open_total(gid):
    fn = os.path.join(E.CACHE, 'odds', gid + '.json')
    if not os.path.exists(fn):
        return PREV.get(gid)
    o = json.load(open(fn)) or []
    op = [b for b in o if b.get('book') == 'Opening' and b.get('total')]
    if op:
        return op[0]['total']
    bk = [b for b in o if b.get('book') and not any(s in b['book'] for s in N.NOT_BOOKS) and b['book'] != 'Opening']
    return N.median([b['open']['total'] for b in bk if b.get('open') and b['open'].get('total')])

out = []
for r in rows:
    if r['S'] < 2015:
        continue
    out.append({'sport': 'nba', 'S': r['S'], 'id': r['id'], 'date': r['tip'], 'home': r['h'], 'away': r['a'],
                'm': r['m'], 'L': r['L'], 'Lo': r.get('Lo'), 'res': r['res'], 'mlH': r.get('mlH'), 'mlA': r.get('mlA'),
                'oH': r.get('oH'), 'oA': r.get('oA'), 'tm': r.get('tm'), 'T': r.get('T') or None, 'To': open_total(r['id']),
                'tot': r['tot'], 'po': r['po']})
with gzip.open(OUT, 'wt') as f:
    json.dump(out, f, separators=(',', ':'))
print('rows', len(out), 'by season', dict(sorted(collections.Counter(r['S'] for r in out).items())))
print('with Lo', sum(r['Lo'] is not None for r in out), 'with To', sum(r['To'] is not None for r in out),
      'with T', sum(r['T'] is not None for r in out), 'with ml', sum(r['mlH'] is not None for r in out), 'po', sum(r['po'] for r in out))
a = lambda k, rs: np.array([r[k] for r in rs], float)
h = [r for r in out if r['S'] >= 2022]
print('2022-26 n', len(h), 'MAE m', round(np.mean(np.abs(a('m', h) - a('res', h))), 3), 'MAE L', round(np.mean(np.abs(a('L', h) - a('res', h))), 3))
ht = [r for r in h if r['T'] and r['tm'] is not None]
print('2022-26 totals n', len(ht), 'MAE tm', round(np.mean(np.abs(a('tm', ht) - a('tot', ht))), 3), 'MAE T', round(np.mean(np.abs(a('T', ht) - a('tot', ht))), 3))
lo = [r for r in out if r['S'] < 2022]
print('2015-21 n', len(lo), 'MAE m', round(np.mean(np.abs(a('m', lo) - a('res', lo))), 3), 'MAE L', round(np.mean(np.abs(a('L', lo) - a('res', lo))), 3))
print('corr(L,res)', round(np.corrcoef(a('L', out), a('res', out))[0, 1], 3), 'corr(m,L)', round(np.corrcoef(a('m', out), a('L', out))[0, 1], 3),
      'corr(m,res)', round(np.corrcoef(a('m', out), a('res', out))[0, 1], 3))
t = [r for r in out if r['T'] and r['tm'] is not None]
print('corr(tm,T)', round(np.corrcoef(a('tm', t), a('T', t))[0, 1], 3), 'corr(T,tot)', round(np.corrcoef(a('T', t), a('tot', t))[0, 1], 3))
w = [r for r in out if r['mlH'] and r['L']]
print('fav-sign check: home ml<0 when L>0:', round(np.mean([(r['mlH'] < 0) == (r['L'] > 0) for r in w if r['L'] != 0]), 3))
