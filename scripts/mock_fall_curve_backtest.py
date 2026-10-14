"""Fall-board test of the mock's board-to-pick curve (BOARD_PICK in scripts/cfb_teams.mjs, fit on final boards).

    python3 scripts/mock_fall_curve_backtest.py   # uses scripts/cfb_draft_pct_backtest.py's cache; writes data/cfb_mock_fall_backtest.json

The predictive mock runs in the fall on a fall board, so: does a curve refit on fall boards (PFF's dated boards, each
draft's latest Sep-Nov version, declared prospects ranked 1-200, undrafted = 290) predict the real slot better than
the final-board curve? Leave one draft out, |ln pick - ln xPick| and top-32 / top-100 MAE, same for winter and final
boards. Result: fall refit .704 vs .716 ln error, but it wins 3 of 5 drafts and loses both NIL-era ones (2024-25), so
BOARD_PICK stays.
"""
import os, sys, math, datetime, collections, csv, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cfb_draft_pct_backtest as B
picks = collections.defaultdict(list)
for r in csv.DictReader(open(B.fetch('', 'draft_picks.csv'))):
    if int(r['season']) >= 2018:
        f, l = B.parts(r['pfr_player_name']); picks[l].append((int(r['season']), int(r['pick']), f))
dt = B.drafttek(); dtn = collections.defaultdict(list)
for (y, _), n in dt.items(): f, l = B.parts(n); dtn[(y, l)].append(f)
rows = []
for y, v, date, players in B.pff_boards():
    days = (datetime.date.fromisoformat(B.DRAFT_DAY[y]) - datetime.date.fromisoformat(date)).days
    for p in players:
        if not p.get('pff_rank'): continue
        f, l = B.parts(p['name']); c = [x for x in picks.get(l, []) if B.fmatch(f, x[2])]
        if any(x[0] < y for x in c): continue
        same = [x for x in c if x[0] == y]
        dec = bool(same) or any(B.fmatch(f, F) for F in dtn.get((y, l), []))
        rows.append(dict(d=y, days=days, rank=p['pff_rank'], pick=same[0][1] if same else 290, dec=dec))
CUR = (0.375, 0.880, 0.0132)
def lp(r, c): l = math.log(max(1, r)); return c[0] + c[1] * l + c[2] * l * l
def fit(s):
    X = np.array([[1, math.log(r['rank']), math.log(r['rank']) ** 2] for r in s]); y = np.array([math.log(r['pick']) for r in s])
    return tuple(np.linalg.lstsq(X, y, rcond=None)[0])
res = {}
for w, (a, b) in {'fall': (140, 240), 'winter': (50, 139), 'final': (0, 30)}.items():
    latest = {}
    for r in rows:
        if a <= r['days'] <= b and (r['d'] not in latest or r['days'] < latest[r['d']]): latest[r['d']] = r['days']
    S = [r for r in rows if latest.get(r['d']) == r['days'] and r['dec'] and r['rank'] <= 200]
    e = collections.defaultdict(list); folds = {}
    for d in sorted(latest):
        tr = [r for r in S if r['d'] != d]; te = [r for r in S if r['d'] == d]; c = fit(tr)
        folds[d] = {'n': len(te), 'cur': round(float(np.mean([abs(math.log(r['pick']) - lp(r['rank'], CUR)) for r in te])), 3),
                    'refit': round(float(np.mean([abs(math.log(r['pick']) - lp(r['rank'], c)) for r in te])), 3)}
        for r in te:
            for name, cc in (('cur', CUR), ('refit', c)):
                xp = math.exp(lp(r['rank'], cc))
                e[name + '_ln'].append(abs(math.log(r['pick']) - math.log(xp)))
                if r['rank'] <= 32: e[name + '_mae32'].append(abs(r['pick'] - xp))
                if r['rank'] <= 100: e[name + '_mae100'].append(abs(r['pick'] - xp))
    full = fit(S)
    res[w] = dict(drafts=sorted(latest), n=len(S), folds=folds, refitWins=sum(v['refit'] < v['cur'] for v in folds.values()), coef=[round(x, 4) for x in full], **{k: round(float(np.mean(v)), 3) for k, v in e.items()},
                  xp={r: round(math.exp(lp(r, full)), 1) for r in (1, 5, 10, 32, 64, 100)}, xpCur={r: round(math.exp(lp(r, CUR)), 1) for r in (1, 5, 10, 32, 64, 100)})
    print(w, json.dumps(res[w]))
res['current'] = CUR; res['asof'] = datetime.date.today().isoformat()
json.dump(res, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'cfb_mock_fall_backtest.json'), 'w'), indent=1)
