# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""A1 / B1: the in-season award layer against Polymarket (global) closed-market prices.
    python3 a1_award_market.py <rows dir (rows_nba.json, rows_nfl.json[, rows_cfb.json])> <Nov 14 rows dir> <out.json>
Benchmark (winner log loss model vs market by race-checkpoint), the market-anchored temperature (A1) and the
log-linear market blend (B1). Market price = poly_hist.asof(event, checkpoint day + 1)."""
import collections, datetime as dt, gzip, json, math, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as NM, poly_hist as PH
FLOOR = 1e-3
SHARES = (.25, .5, .75)
TUNE = {('nba', 2025), ('nfl', 2024), ('cfb', 2024)}
HELD = {('nba', 2026), ('nfl', 2025), ('nhl', 2026), ('cfb', 2025)}
AW_KIND = {'heisman': 'heisman'}


def plus1(day):
    return (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()


def nfl_days():
    W = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'nfl.json.gz')))
    out = collections.defaultdict(str)
    for g in W:
        if g.get('po'): continue
        for w in range(g['wk'], 23): out[(g['S'], w)] = max(out[(g['S'], w)], g['date'][:10])
    return out


def nhl_days():
    G = [g for g in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nhl_games_hist.json.gz'))) if g['po'] == 0 and g.get('final')]
    days = collections.defaultdict(list)
    for g in G: days[g['S']].append(g['day'])
    return {S: [sorted(d)[int(len(d) * f) - 1] for f in SHARES] for S, d in days.items()}


def temper(p, T):
    q = [max(v, 1e-300) ** (1 / T) for v in p]
    t = sum(q)
    return [v / t for v in q]


def market(sp, aw, S, day):
    ev = PH.load(sp, AW_KIND.get(aw, aw), S)
    if not ev: return None, None
    px = PH.asof(ev, plus1(day))
    if len(px) < 2 or not PH.liquid(px): return None, None
    t = sum(px.values())
    win = [m['name'] for m in ev['markets'] if m['won']]
    return {k: v / t for k, v in px.items()}, (win[0] if win else None)


def match(names, mk):
    """index in names -> market name"""
    keys = {NM.key(k): k for k in mk if k.lower() != 'other'}
    out = {}
    for i, n in enumerate(names):
        k = keys.get(NM.key(n)) or next((m for m in keys.values() if NM.same(m, n)), None)
        if k and k not in out.values(): out[i] = k
    return out


def blend(r, mk, w):
    """log-linear blend over the union; returns P(winner) (winner by market flag when outside the model pool)"""
    mt = match(r['n'], mk)
    other = mk.get('Other', mk.get('other', min(mk.values())))
    un = [i for i in range(len(r['n'])) if i not in mt]
    z, wi = [], None
    for i, p in enumerate(r['p']):
        pm = mk[mt[i]] if i in mt else other / max(len(un), 1)
        z.append(max(p, 1e-6) ** (1 - w) * max(pm, 1e-6) ** w)
        if i == r['w']: wi = len(z) - 1
    used = set(mt.values())
    for k, v in mk.items():
        if k in used or k.lower() == 'other': continue
        z.append(FLOOR ** (1 - w) * max(v, 1e-6) ** w)
        if r['w'] is None and k == r.get('mwin'): wi = len(z) - 1
    return (z[wi] / sum(z)) if wi is not None else FLOOR


def tstat(d):
    n = len(d); m = sum(d) / n
    if n < 2: return m, 0.0
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    return m, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0)


def main(rdir, olddir, outfn):
    ND, HD = nfl_days(), nhl_days()
    rows = []
    for sp in ('nba', 'nfl', 'cfb'):
        fn = os.path.join(rdir, f'rows_{sp}.json')
        if not os.path.exists(fn): continue
        for r in json.load(open(fn)):
            if r['var'] != 'box': continue
            if sp == 'nfl': r['day'] = ND[(r['s'], int(r['day'][2:]))]
            rows.append(r)
    for r in json.load(open(os.path.join(olddir, 'rows_nhl.json'))):
        if r['var'] == 'box' and r['s'] == 2026:
            r['day'] = HD[2026][r['cp']]; r['n'] = None; rows.append(r)
    bench = []
    for r in rows:
        key = (r['sp'], r['s'])
        if key not in TUNE and key not in HELD: continue
        mk, mwin = market(r['sp'], r['aw'], r['s'], r['day'])
        if not mk or not mwin: continue
        r['mk'], r['mwin'] = mk, mwin
        r['pm'] = max(r['p'][r['w']], FLOOR) if r['w'] is not None else FLOOR
        r['pk'] = max(mk.get(mwin, 0), FLOOR)
        r['split'] = 'tune' if key in TUNE else 'held'
        bench.append(r)
    print('race-checkpoints with a market:', len(bench))
    for r in bench:
        print(r['split'], r['sp'], r['s'], r['aw'], r['cp'], r['day'], 'model', round(r['pm'], 3), 'market', round(r['pk'], 3),
              'fav', r['top'][0], 'winner', r['mwin'])
    out = {'bench': [{k: r[k] for k in ('split', 'sp', 's', 'aw', 'cp', 'day', 'pm', 'pk', 'mwin')} for r in bench]}
    for split in ('tune', 'held'):
        B = [r for r in bench if r['split'] == split]
        if not B: continue
        race = collections.defaultdict(list)
        for r in B: race[(r['sp'], r['s'], r['aw'])].append(math.log(r['pk']) - math.log(r['pm']))   # >0: market better
        d = [sum(v) / len(v) for v in race.values()]
        m, t = tstat(d)
        out['bench_' + split] = {'rows': len(B), 'races': len(d), 'll_model': round(-sum(math.log(r['pm']) for r in B) / len(B), 4),
                                 'll_market': round(-sum(math.log(r['pk']) for r in B) / len(B), 4), 'd_model_minus_market': round(m, 4),
                                 't': round(t, 2), 'races_market_better': sum(x > 0 for x in d)}
        print(split, out['bench_' + split])
    # A1: constant T against market probabilities on tune rows with names
    def xent(T):
        s, k = 0.0, 0
        for r in bench:
            if r['split'] != 'tune' or not r['n'] or r['sp'] == 'cfb': continue
            mt = match(r['n'], r['mk'])
            if len(mt) < 2: continue
            p = temper(r['p'], T)
            zp = sum(p[i] for i in mt); zm = sum(r['mk'][v] for v in mt.values())
            s += -sum(r['mk'][v] / zm * math.log(max(p[i] / zp, 1e-9)) for i, v in mt.items()); k += 1
        return s / max(k, 1)
    grid = [1 + x / 10 for x in range(0, 21)]
    T = min(grid, key=xent)
    print('A1 T fit to market on tune:', T, {g: round(xent(g), 4) for g in (1.0, 1.5, 2.0, 2.5, 3.0)})
    pw = lambda r, T: max(temper(r['p'], T)[r['w']], FLOOR) if r['w'] is not None else FLOOR
    res = {'T': T}
    for split in ('tune', 'held'):
        race = collections.defaultdict(list)
        for r in bench:
            if r['split'] == split and r['sp'] != 'cfb': race[(r['sp'], r['s'], r['aw'])].append(math.log(r['pm']) - math.log(pw(r, T)))  # <0: T better
        d = [sum(v) / len(v) for v in race.values()]
        m, t = tstat(d)
        bysp = collections.defaultdict(list)
        for k, v in race.items(): bysp[k[0]].append(sum(v) / len(v))
        res[split] = {'races': len(d), 'd': round(m, 4), 't': round(t, 2), 'better': sum(x < 0 for x in d),
                      'by_sport': {k: round(sum(v) / len(v), 4) for k, v in bysp.items()}}
    # long history guard (Nov 14 rows before the market seasons)
    hist = []
    for sp, last in (('nba', 2024), ('nhl', 2024), ('nfl', 2023)):
        for r in json.load(open(os.path.join(olddir, f'rows_{sp}.json'))):
            if r['var'] == 'box' and r['s'] <= last:
                hist.append(math.log(max(r['p'][r['w']], FLOOR) if r['w'] is not None else FLOOR) - math.log(pw(r, T)))
    res['history'] = {'rows': len(hist), 'd': round(sum(hist) / len(hist), 4)}
    h = res.get('held', {})
    res['pass'] = bool(T > 1 and h and h['t'] <= -2 and res['tune']['d'] <= 0 and h['better'] >= .6 * h['races']
                       and sum(v < 0 for v in h['by_sport'].values()) >= 2 and res['history']['d'] <= 0)
    print('A1', res)
    out['A1'] = res
    # B1 blend
    named = [r for r in bench if r['n']]
    ll = lambda R, w: sum(-math.log(max(blend(r, r['mk'], w), FLOOR)) for r in R)
    wg = [x / 20 for x in range(21)]
    tune = [r for r in named if r['split'] == 'tune']; held = [r for r in named if r['split'] == 'held']
    if tune and held:
        w = min(wg, key=lambda w: ll(tune, w))
        b = {'w': w}
        for nm, R in (('tune', tune), ('held', held)):
            race = collections.defaultdict(list); rm = collections.defaultdict(list)
            for r in R:
                pb = max(blend(r, r['mk'], w), FLOOR)
                race[(r['sp'], r['s'], r['aw'])].append(math.log(r['pm']) - math.log(pb))        # <0: blend better than model
                rm[(r['sp'], r['s'], r['aw'])].append(math.log(r['pk']) - math.log(pb))          # <0: blend better than market
            d = [sum(v) / len(v) for v in race.values()]; d2 = [sum(v) / len(v) for v in rm.values()]
            m, t = tstat(d); m2, t2 = tstat(d2)
            b[nm] = {'rows': len(R), 'races': len(d), 'll_model': round(-sum(math.log(r['pm']) for r in R) / len(R), 4),
                     'll_market': round(-sum(math.log(r['pk']) for r in R) / len(R), 4), 'll_blend': round(ll(R, w) / len(R), 4),
                     'd_vs_model': round(m, 4), 't_vs_model': round(t, 2), 'better_vs_model': sum(x < 0 for x in d),
                     'd_vs_market': round(m2, 4), 't_vs_market': round(t2, 2)}
        b['pass'] = bool(b['held']['t_vs_model'] <= -2 and b['tune']['d_vs_model'] < 0)
        print('B1', b)
        out['B1'] = b
    json.dump(out, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    main(*sys.argv[1:4])
