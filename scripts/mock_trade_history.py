# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Draft-day trade-up shapes by round, 2015-25 (nflverse trades), for calibrating the mock's projected trades.

Per round of the pick moved up to: deals a year, the jump (the
trader-up's best pick sent minus the pick), the share of jumps of 10+ and 16+, the pieces sent this year, and the
share sending a later draft's pick (any, and a first). Writes data/nfl_trade_shapes.json; the mock side is
scripts/mock_trade_calib.mjs.
"""
import csv, collections, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = os.path.join(ROOT, 'scripts', '.cache', 'draft')
R = list(csv.DictReader(open(os.path.join(C, 'trades.csv'))))
n = collections.Counter((r['season'], r['trade_date']) for r in R if r['pick_season'] == r['season'] and r['pick_number'] and r['trade_date'][5:7] in ('04', '05'))
days = {s: set(sorted([d for (y, d) in n if y == str(s)], key=lambda d: -n[(str(s), d)])[:3]) for s in range(2015, 2026)}
deals = collections.defaultdict(list)
for r in R:
    s = int(r['season'])
    if s in days and r['trade_date'] in days[s]: deals[r['trade_id']].append(r)
ups = []
for rs in deals.values():
    s = int(rs[0]['season'])
    if len({r['gave'] for r in rs} | {r['received'] for r in rs}) != 2: continue
    cur = [(int(r['pick_number']), r['received'], r['gave']) for r in rs if r['pick_season'] == str(s) and r['pick_number']]
    if not cur: continue
    b, U, D = min(cur); sent = sorted(p for p, rec, g in cur if g == U)
    if not sent: continue
    fut = [int(r['pick_round']) for r in rs if r['gave'] == U and r['pick_season'] and r['pick_season'] != str(s) and r['pick_round']]
    rnd = 1 + (b - 1) // 32 if b <= 224 else 7
    ups.append(dict(s=s, rd=min(rnd, 7), pick=b, gap=sent[0] - b, cur=len(sent), fut=fut))
def shape(L, yrs):
    g = sorted(u['gap'] for u in L); k = len(L) or 1
    return dict(n=len(L), perYear=round(len(L) / yrs, 2), gapMedian=g[len(g) // 2] if g else None, gapP75=g[int(.75 * len(g))] if g else None,
                gap10=round(sum(x >= 10 for x in g) / k, 3), gap16=round(sum(x >= 16 for x in g) / k, 3),
                futAny=round(sum(bool(u['fut']) for u in L) / k, 3), futR1=round(sum(1 in u['fut'] for u in L) / k, 3),
                futR1perYear=round(sum(1 in u['fut'] for u in L) / yrs, 2), curMean=round(sum(u['cur'] for u in L) / k, 2))
out = {f'R{r}': shape([u for u in ups if u['rd'] == r], 11) for r in range(1, 8)}
out['_readme'] = __doc__.strip().split('\n\n')[0]
if __name__ == '__main__':
    for k, v in out.items(): print(k, v)
    json.dump(out, open(os.path.join(ROOT, 'data', 'nfl_trade_shapes.json'), 'w'), indent=1)
