"""Draft-day trade-ups, 2010-25, for the mock draft's projected trades (cfb_teams.mjs, mockDraft).

nflverse's trades file: each draft-day deal with a current-year pick is a trade-up to its earliest pick. The gap
is the trader-up's best pick sent minus that pick. The in-division null for each deal is the share of division
rivals among the teams holding the 20 picks before the trader-up's own (holders from nflverse draft_picks).
Writes data/nfl_trade_history.json.
"""
import csv, collections, json, math, os, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'draft')
SRC = {'trades.csv': 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/trades.csv',
       'draft_picks.csv': 'https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv'}


def load(name):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if not os.path.exists(p):
        urllib.request.urlretrieve(SRC[name], p)
    return list(csv.DictReader(open(p)))


FIX = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA', 'GNB': 'GB', 'KAN': 'KC', 'NWE': 'NE', 'NOR': 'NO',
       'SFO': 'SF', 'TAM': 'TB', 'LVR': 'LV', 'RAM': 'LA', 'SDG': 'LAC', 'RAI': 'LV', 'PHO': 'ARI'}
DIVS = ['BUF MIA NE NYJ', 'BAL CIN CLE PIT', 'HOU IND JAX TEN', 'DEN KC LV LAC',
        'DAL NYG PHI WAS', 'CHI DET GB MIN', 'ATL CAR NO TB', 'ARI LA SEA SF']
DIV = {t: i for i, ts in enumerate(DIVS) for t in ts.split()}
team = lambda t: FIX.get(t, t)

R, DP = load('trades.csv'), load('draft_picks.csv')
hold = {(int(r['season']), int(r['pick'])): team(r['team']) for r in DP}
# the draft's three days: the three late-April/May dates with the most current-year pick deals
n = collections.Counter((r['season'], r['trade_date']) for r in R
                        if r['pick_season'] == r['season'] and r['pick_number'] and r['trade_date'][5:7] in ('04', '05'))
days = {s: set(sorted([d for (y, d) in n if y == str(s)], key=lambda d: -n[(str(s), d)])[:3]) for s in range(2010, 2026)}
deals = collections.defaultdict(list)
for r in R:
    s = int(r['season'])
    if s in days and r['trade_date'] in days[s]:
        deals[r['trade_id']].append(r)
ups = []
for rs in deals.values():
    s = int(rs[0]['season'])
    if len({r['gave'] for r in rs} | {r['received'] for r in rs}) != 2:
        continue
    cur = [(int(r['pick_number']), team(r['received']), team(r['gave'])) for r in rs if r['pick_season'] == str(s) and r['pick_number']]
    if not cur:
        continue
    b, U, D = min(cur)
    sent = [p for p, rec, g in cur if g == U]
    if not sent:
        continue
    a = min(sent)
    cand = {hold.get((s, k)) for k in range(max(1, a - 20), a)} - {U, None}
    ups.append({'season': s, 'pick': b, 'up': U, 'down': D, 'gap': a - b, 'div': DIV.get(U) == DIV.get(D),
                'pDiv': sum(DIV.get(t) == DIV.get(U) for t in cand) / max(1, len(cand))})

out = {}
for lab, lo, hi, y0 in [('R1 2015-25', 1, 32, 2015), ('R2 2015-25', 33, 64, 2015), ('R1-2 2010-25', 1, 64, 2010), ('all 2010-25', 1, 999, 2010)]:
    sel = [u for u in ups if lo <= u['pick'] <= hi and u['season'] >= y0]
    g = sorted(u['gap'] for u in sel)
    obs, exp = sum(u['div'] for u in sel), sum(u['pDiv'] for u in sel)
    var = sum(u['pDiv'] * (1 - u['pDiv']) for u in sel)
    yrs = len({u['season'] for u in ups if u['season'] >= y0})
    out[lab] = {'n': len(sel), 'perYear': round(len(sel) / yrs, 2), 'gapMedian': g[len(g) // 2],
                'gap1': sum(x == 1 for x in g), 'gap<=3': sum(x <= 3 for x in g),
                'inDivision': obs, 'inDivisionExpected': round(exp, 1), 'ratio': round(obs / exp, 2), 'z': round((obs - exp) / math.sqrt(var), 2)}
    print(lab, out[lab])
json.dump(out, open(os.path.join(ROOT, 'data', 'nfl_trade_history.json'), 'w'), indent=1)
