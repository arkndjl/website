# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Rate metrics, held out: does a predictive (Marcel-shrunk) rate forecast next season's rate better than the raw
rate, a one-season shrink, or the incumbent projection?

  python3 scripts/rate_metrics_research.py soccer|nhl   -> data/rate_metrics_research.json (one key per sport)

Rows: (player, season, exposure e, rate v, position). Target: next season's rate, weighted by next season's
exposure, players at or over the qualifying line next season. Every predictor gets a linear calibration fit on the
training seasons; Marcel weights / K are chosen on the training seasons too (leave one target season out). Paired t on
per-player weighted squared error (negative = the candidate is better)."""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'rate_metrics_research.json')


def load_soccer():
    rows = {}
    d = os.path.join(ROOT, 'static', 'data', 'soccer-war')
    for fn in sorted(os.listdir(d)):
        S = int(fn[:4])
        js = json.load(open(os.path.join(d, fn)))
        if js.get('label', '').endswith(str(S)[2:]) and S == 2027:
            pass
        for p in js['players']:
            if not p.get('min'):
                continue
            k = (p['p'], S)
            e = p['min'] / 90
            o = rows.get(k)
            if o:   # two clubs in a season: pool
                tot = o['e'] + e
                o['v'] = (o['v'] * o['e'] + p['gar'] / e * e) / tot if e else o['v']
                o['e'] = tot
            else:
                rows[k] = {'id': p['p'], 'S': S, 'e': e, 'v': p['gar'] / e, 'pos': p.get('pos') or 'M',
                           'inc': None, 'tm': p.get('team')}
    return rows, 900 / 90, 2027


def load_nhl():
    rows = {}
    d = os.path.join(ROOT, 'static', 'data', 'nhl-war')
    for fn in sorted(os.listdir(d)):
        S = int(fn[:4])
        js = json.load(open(os.path.join(d, fn)))
        for p in js['players']:
            if not p.get('toi') or p.get('gar') is None:
                continue
            e = p['toi'] / 60
            g = 'G' if p.get('pos') == 'G' else ('D' if p.get('pos') == 'D' else 'F')
            rows[(p['id'], S)] = {'id': p['id'], 'S': S, 'e': e, 'v': p['gar'] / e, 'pos': g, 'inc': p.get('hpm'), 'tm': p.get('tm')}
    return rows, 500 / 60, 2027


def wls_pos(xs, ys, ws, ps):
    """y ~ a[pos] + b x, weighted"""
    keys = sorted(set(ps))
    mx = {}; my = {}; sw = {}
    for x, y, w, p in zip(xs, ys, ws, ps):
        sw[p] = sw.get(p, 0) + w; mx[p] = mx.get(p, 0) + w * x; my[p] = my.get(p, 0) + w * y
    for k in keys: mx[k] /= sw[k]; my[k] /= sw[k]
    sxx = sum(w * (x - mx[p]) ** 2 for x, w, p in zip(xs, ws, ps))
    sxy = sum(w * (x - mx[p]) * (y - my[p]) for x, y, w, p in zip(xs, ys, ws, ps))
    b = sxy / sxx if sxx > 0 else 0.0
    return {k: my[k] - b * mx[k] for k in keys}, b


def wls(xs, ys, ws):
    sw = sum(ws); mx = sum(w * x for x, w in zip(xs, ws)) / sw; my = sum(w * y for y, w in zip(ys, ws)) / sw
    sxx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws)); sxy = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws))
    b = sxy / sxx if sxx > 0 else 0.0
    return my - b * mx, b


def build_cases(rows, qual, cur):
    cases = []
    for (pid, S), r in rows.items():
        nxt = rows.get((pid, S + 1))
        if not nxt or S + 1 >= cur or nxt['e'] < qual:
            continue
        hist = [rows.get((pid, S - j)) for j in range(3)]
        cases.append({'S': S + 1, 'pos': r['pos'], 'h': hist, 'y': nxt['v'], 'w': nxt['e'], 'inc': r['inc'],
                      'mv': r.get('tm') is not None and r.get('tm') != nxt.get('tm')})
    return cases


def pos_means(rows, seasons):
    acc = {}
    for r in rows.values():
        if r['S'] in seasons:
            a = acc.setdefault(r['pos'], [0.0, 0.0]); a[0] += r['v'] * r['e']; a[1] += r['e']
    return {k: a[0] / a[1] for k, a in acc.items()}


def marcel(c, mu, K, wts):
    if isinstance(K, dict): K = K.get(c['pos'], K.get('*', 0))
    num = K * mu.get(c['pos'], 0.0); den = K
    for j, h in enumerate(c['h']):
        if h and j < len(wts):
            num += wts[j] * h['v'] * h['e']; den += wts[j] * h['e']
    return num / den


def evaluate(rows, qual, cur):
    cases = build_cases(rows, qual, cur)
    tseasons = sorted({c['S'] for c in cases})
    Ks = [0, 2, 5, 10, 20, 40, 80, 160]
    W2 = [(1,), (1, .7, .5), (1, .5, .25), (1, .8, .6), (1, .6, .3)]
    preds = {k: {} for k in ('raw', 'shrink1', 'marcel', 'inc')}
    picks = {}
    for T in tseasons:
        tr = [c for c in cases if c['S'] != T]
        mu = pos_means(rows, {c['S'] - 1 for c in tr})

        def fitc(f, cs):
            xs = [f(c) for c in cs]; return wls_pos(xs, [c['y'] for c in cs], [c['w'] for c in cs], [c['pos'] for c in cs])

        def sse(f, cs):
            a, b = fitc(f, cs); return sum(c['w'] * (c['y'] - a.get(c['pos'], 0) - b * f(c)) ** 2 for c in cs)
        cand = {}
        cand['raw'] = lambda c: c['h'][0]['v']
        bestK1 = min(Ks, key=lambda K: sse(lambda c: marcel(c, mu, K, (1,)), tr))
        cand['shrink1'] = lambda c, K=bestK1: marcel(c, mu, K, (1,))
        bestM = min(((K, w) for K in Ks for w in W2), key=lambda kw: sse(lambda c: marcel(c, mu, kw[0], kw[1]), tr))
        Kg = {}
        for g in sorted({c['pos'] for c in tr}):
            sub = [c for c in tr if c['pos'] == g]
            Kg[g] = min(Ks + [320, 640], key=lambda K: sse(lambda c: marcel(c, mu, K, bestM[1]), sub))
        cand['marcel'] = lambda c, kw=bestM, Kg=Kg: marcel(c, mu, Kg, kw[1])
        if all(c['inc'] is not None for c in cases):
            cand['inc'] = lambda c: c['inc']
        picks[T] = {'K1': bestK1, 'K': bestM[0], 'Kg': Kg, 'w': list(bestM[1])}
        te = [i for i, c in enumerate(cases) if c['S'] == T]
        for k, f in cand.items():
            a, b = fitc(f, tr)
            for i in te:
                c = cases[i]; preds[k][i] = c['w'] * (c['y'] - a.get(c['pos'], 0) - b * f(c)) ** 2
    out = {'n': len(cases), 'seasons': tseasons, 'picks': picks}
    base = preds['marcel']
    W = sum(c['w'] for c in cases)
    for k, p in preds.items():
        if not p:
            continue
        out[k] = {'mse': round(sum(p.values()) / W, 5)}
    for k in ('raw', 'shrink1', 'inc'):
        if not preds[k]:
            continue
        d = [base[i] - preds[k][i] for i in base]
        m = sum(d) / len(d); sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1))
        better = sum(1 for T in tseasons if sum(base[i] for i, c in enumerate(cases) if c['S'] == T)
                     < sum(preds[k][i] for i, c in enumerate(cases) if c['S'] == T))
        out['marcel_vs_' + k] = {'t': round(m / (sd / math.sqrt(len(d))), 2), 'seasonsBetter': better,
                                 'of': len(tseasons)}
    mv = [i for i, c in enumerate(cases) if c.get('mv')]
    for k in ('raw', 'inc'):
        if preds[k] and mv:
            d = [base[i] - preds[k][i] for i in mv]
            m = sum(d) / len(d); sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1))
            out['movers_marcel_vs_' + k] = {'n': len(mv), 't': round(m / (sd / math.sqrt(len(d))), 2)}
    # the live setting: fit on every season
    mu = pos_means(rows, set(r['S'] for r in rows.values()))
    out['muPos'] = {k: round(v, 4) for k, v in mu.items()}
    return out


def main():
    sport = sys.argv[1]
    rows, qual, cur = {'soccer': load_soccer, 'nhl': load_nhl}[sport]()
    res = evaluate(rows, qual, cur)
    try:
        allr = json.load(open(OUT))
    except OSError:
        allr = {}
    allr[sport] = res
    open(OUT, 'w').write(json.dumps(allr, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != 'picks'}, indent=1))
    print('picks', res['picks'])


if __name__ == '__main__':
    main()
