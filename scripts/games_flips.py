"""Held-out record of flips (Noah, Oct 30 2026): games where the model's winner is the market's underdog (the model's
margin and the closing spread name different favorites). Bet the model's winner on the closing moneyline, 1 unit
flat, every held-out game in the walk-forward files (scripts/data/games_wf/<sport>.json.gz, seasons from
games_picks.HELD on). Moneylines past +-300 left out, as on the picks (games_picks.ML_CAP); games where the spread and the
moneyline name different favorites are skipped (bad lines). Writes data/games_flips.json for the picks tab.
    python3 scripts/games_flips.py
NBA is an upper bound: its walk-forward model saw tip-time injury news."""
import gzip
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from games_picks import HELD, ML_CAP, ROOT, SPORTS, WF, dec, novig, price

OUT = os.path.join(ROOT, 'data', 'games_flips.json')


def flips(rows, held):
    out = []
    for g in rows:
        m, L, res = g.get('m'), g.get('L'), g.get('res')
        mh, ma = price(g.get('mlH')), price(g.get('mlA'))
        if g['S'] < held or None in (m, L, res, mh, ma) or not m or not L or (m > 0) == (L > 0):
            continue
        if abs(L) >= 3 and (mh < ma) != (L > 0):
            continue
        home = m > 0
        o, q = (mh, novig(mh, ma)) if home else (ma, novig(ma, mh))
        r = res if home else -res
        if abs(o) > ML_CAP or not r:
            continue
        out.append((r > 0, dec(o) - 1 if r > 0 else -1.0, q, o))
    return out


def summary(b):
    n = len(b)
    if n < 2:
        return {'n': n}
    rets = [x[1] for x in b]
    mu = sum(rets) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / (n - 1))
    return {'n': n, 'w': sum(x[0] for x in b), 'hit': round(sum(x[0] for x in b) / n, 3),
            'mkt': round(sum(x[2] for x in b) / n, 3), 'roi': round(mu, 4), 't': round(mu / sd * math.sqrt(n), 2)}


def main():
    out, pool, pool200 = {'sports': {}}, [], []
    for s in SPORTS:
        b = flips(json.load(gzip.open(os.path.join(WF, f'{s}.json.gz'))), HELD[s])
        b200 = [x for x in b if -200 <= x[3] <= 200]
        out['sports'][s] = {'held': HELD[s], **summary(b), 'ml200': summary(b200)}
        pool += b
        pool200 += b200
    out['all'] = {**summary(pool), 'ml200': summary(pool200)}
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    for k, v in list(out['sports'].items()) + [('all', out['all'])]:
        print(k, {x: v[x] for x in ('n', 'hit', 'mkt', 'roi', 't') if x in v})


if __name__ == '__main__':
    main()
