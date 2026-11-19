# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""M2: TIMING curve by hours to start from Polymarket (global) moneyline paths vs the walk-forward model number.
    python3 m2_timing.py <paths dir> <out.json>"""
import bisect, collections, gzip, json, math, os, sys, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as NM
HS = (24, 12, 6, 3, 1)
FEE = .095
NICK = {'Ducks': 'ANA', 'Bruins': 'BOS', 'Sabres': 'BUF', 'Hurricanes': 'CAR', 'Blue Jackets': 'CBJ', 'Flames': 'CGY',
        'Blackhawks': 'CHI', 'Avalanche': 'COL', 'Stars': 'DAL', 'Red Wings': 'DET', 'Oilers': 'EDM', 'Panthers': 'FLA',
        'Kings': 'LAK', 'Wild': 'MIN', 'Canadiens': 'MTL', 'Devils': 'NJD', 'Predators': 'NSH', 'Islanders': 'NYI',
        'Rangers': 'NYR', 'Senators': 'OTT', 'Flyers': 'PHI', 'Penguins': 'PIT', 'Kraken': 'SEA', 'Sharks': 'SJS',
        'Blues': 'STL', 'Lightning': 'TBL', 'Maple Leafs': 'TOR', 'Mammoth': 'UTA', 'Utah': 'UTA', 'Canucks': 'VAN',
        'Golden Knights': 'VGK', 'Jets': 'WPG', 'Capitals': 'WSH'}


def phi(x): return .5 * (1 + math.erf(x / math.sqrt(2)))


def et_day(ts): return time.strftime('%Y-%m-%d', time.gmtime(ts - 5 * 3600))


def load(pdir, tag):
    ev = {e['slug']: e for e in json.load(open(os.path.join(pdir, tag + '_events.json')))}
    out = []
    for l in open(os.path.join(pdir, tag + '_paths.jsonl')):
        p = json.loads(l)
        e = ev.get(p['slug'])
        if e and p['h']: out.append((e, p['h']))
    return out


def model_nhl():
    W = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'nhl.json.gz')))
    return {(g['day'], g['h'], g['a']): g['p'] for g in W if g['S'] == 2026 and g['po'] == 0 and g.get('p') is not None}


def model_cbb(sd):
    W = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'cbb.json.gz')))
    by = collections.defaultdict(list)
    for g in W:
        if g['S'] == 2026 and not g.get('po') and g.get('m') is not None: by[g['date'][:10]].append(g)
    return by, sd


def rows(pdir):
    R = []
    M = model_nhl()
    for e, h in load(pdir, 'nhl'):
        a, b = (NICK.get(x) for x in e['oc'])
        d = et_day(e['start'])
        if (d, a, b) in M: pm, flip = M[(d, a, b)], False            # outcome 0 is the home side
        elif (d, b, a) in M: pm, flip = M[(d, b, a)], True
        else: continue
        R.append(('nhl', e, h, pm, flip))
    if os.path.exists(os.path.join(pdir, 'cbb_paths.jsonl')):
        sd = json.load(open(os.path.join(ROOT, 'data', 'clv_fit.json')))['sports']['cbb']['sd']
        by, sd = model_cbb(sd)
        for e, h in load(pdir, 'cbb'):
            d = et_day(e['start'])
            hit = None
            for g in by.get(d, []):
                o0, o1 = e['oc']
                st = lambda full, short: full == short or full.startswith(short + ' ') or NM.team_key(full) == NM.team_key(short)
                if st(o0, g['home']) and st(o1, g['away']): hit = (g, False)
                elif st(o1, g['home']) and st(o0, g['away']): hit = (g, True)
                if hit: break
            if not hit: continue
            g, flip = hit
            R.append(('cbb', e, h, phi(g['m'] / sd), flip))
    out = []
    for sp, e, h, pm, flip in R:
        ts = [x[0] for x in h]
        def at(t, maxage):
            i = bisect.bisect_right(ts, t) - 1
            if i < 0 or t - ts[i] > maxage: return None
            return h[i][1]
        c = at(e['start'] - 300, 3600)
        if c is None or not (.02 < c < .98): continue
        pm0 = 1 - pm if flip else pm            # model chance of outcome 0
        r = {'sp': sp, 'day': et_day(e['start']), 'mon': et_day(e['start'])[:7], 'pm': pm0, 'c': c, 'win': e['win'], 'q': {}}
        for hh in HS:
            q = at(e['start'] - hh * 3600, 6 * 3600)
            if q is not None and .02 < q < .98: r['q'][hh] = q
        out.append(r)
    return out


def clt(d, days):
    by = collections.defaultdict(float); n = len(d)
    if n < 3: return 0.0, 0.0, n
    m = sum(d) / n
    for x, k in zip(d, days): by[k] += x - m
    G = len(by)
    v = sum(s * s for s in by.values()) * G / max(G - 1, 1) / n / n
    return m, (m / math.sqrt(v) if v > 0 else 0.0), n


def slope(x, y, days):
    """through-origin slope with a day-clustered t"""
    sxx = sum(a * a for a in x)
    if sxx <= 0: return 0.0, 0.0
    b = sum(a * c for a, c in zip(x, y)) / sxx
    by = collections.defaultdict(float)
    for a, c, k in zip(x, y, days): by[k] += a * (c - b * a)
    G = len(by)
    se = math.sqrt(sum(s * s for s in by.values()) * G / max(G - 1, 1)) / sxx
    return b, (b / se if se > 0 else 0.0)


def main(pdir, outfn):
    R = rows(pdir)
    tune = lambda r: '2025-11' <= r['mon'] <= '2026-01'
    held = lambda r: '2026-02' <= r['mon'] <= '2026-04'
    out = {'n': collections.Counter(r['sp'] for r in R), 'curve': {}, 'rule': {}}
    print('rows', dict(out['n']))
    ok_curve = True
    for sp in sorted(out['n']):
        for hh in HS:
            A = [r for r in R if r['sp'] == sp and hh in r['q']]
            T, H = [r for r in A if tune(r)], [r for r in A if held(r)]
            if len(T) < 50 or len(H) < 50: continue
            g = lambda S: ([r['pm'] - r['q'][hh] for r in S], [r['c'] - r['q'][hh] for r in S], [r['day'] for r in S])
            b, tb = slope(*g(T))
            xh, yh, dh = g(H)
            s, ts_ = slope([b * v for v in xh], yh, dh) if abs(b) > 1e-9 else (0.0, 0.0)
            bh, tbh = slope(xh, yh, dh)
            out['curve'][f'{sp}_{hh}'] = {'n_tune': len(T), 'n_held': len(H), 'b_tune': round(b, 4), 't_tune': round(tb, 2),
                                          'b_held': round(bh, 4), 't_held': round(tbh, 2), 'held_slope_on_pred': round(s, 3)}
            if abs(s - 1) > .15: ok_curve = False
            print(sp, hh, out['curve'][f'{sp}_{hh}'])
    out['curve_pass'] = bool(ok_curve and out['curve'])
    def bets(S, hh, X):
        d, days, mon = [], [], []
        for r in S:
            if hh not in r['q']: continue
            gap = r['pm'] - r['q'][hh]
            if abs(gap) < X: continue
            q, c = (r['q'][hh], r['c']) if gap > 0 else (1 - r['q'][hh], 1 - r['c'])
            d.append((c - q - FEE * q * (1 - q)) / q); days.append(r['day']); mon.append(r['mon'])
        return d, days, mon
    for sp in sorted(out['n']):
        for hh in (24, 6, 1):
            best = None
            for X in (.02, .04, .06, .08):
                d, days, _ = bets([r for r in R if r['sp'] == sp and tune(r)], hh, X)
                m, t, n = clt(d, days)
                if n >= 40 and m > 0 and t >= 1 and (best is None or m > best[1]): best = (X, m, t, n)
            key = f'{sp}_{hh}'
            if not best:
                d, days, _ = bets([r for r in R if r['sp'] == sp and tune(r)], hh, .04)
                m, t, n = clt(d, days)
                out['rule'][key] = {'tune': 'no cell qualifies', 'tune_at_.04': {'n': n, 'ret': round(m, 4), 't': round(t, 2)}}
            else:
                d, days, mon = bets([r for r in R if r['sp'] == sp and held(r)], hh, best[0])
                m, t, n = clt(d, days)
                bm = {k: round(sum(x for x, mm in zip(d, mon) if mm == k) / max(sum(mm == k for mm in mon), 1), 4) for k in sorted(set(mon))}
                out['rule'][key] = {'X': best[0], 'tune': {'n': best[3], 'ret': round(best[1], 4), 't': round(best[2], 2)},
                                    'held': {'n': n, 'ret': round(m, 4), 't': round(t, 2), 'by_month': bm},
                                    'pass': bool(t >= 2 and bm.get('2026-02', -1) > 0 and bm.get('2026-03', -1) > 0)}
            print('rule', key, out['rule'][key])
    out['n'] = dict(out['n'])
    json.dump(out, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
