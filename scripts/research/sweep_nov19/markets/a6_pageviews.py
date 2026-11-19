# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""A6: Wikipedia pageview share as one more column of the NBA MVP voter model (season end, 2016-25).
    python3 a6_pageviews.py fetch <cache dir>     # daily user views per candidate, slow, retries on 429
    python3 a6_pageviews.py score <cache dir> <out.json>"""
import datetime as dt, gzip, json, math, os, subprocess, sys, time, urllib.parse
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import awards_engine as E, awards_nba as A
from awards_research import t_sf
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
SEASONS = range(2016, 2026)
TOP = 30


def races():
    R = [(s, pool, o) for s, pool, o in A.seasons_data()['mvp'] if s in SEASONS and o]
    X = [([[r[c] for c in A.MVP_COLS] for r in pool], o) for _, pool, o in R]
    b, mu, sd = E.fit(X, depth=3)
    top = {}
    for (s, pool, o), (x, _) in zip(R, X):
        p = E.prob(x, b, mu, sd)
        top[s] = sorted(range(len(pool)), key=lambda i: -p[i])[:TOP]
    return R, top


def last_days():
    G = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_games_hist.json.gz')))['games']
    out = {}
    for g in G:
        if g['t'] == 2 and g.get('fin'): out[g['S']] = max(out.get(g['S'], ''), g['tip'][:10])
    out[2020] = '2020-03-11'
    return out


def fetch(cdir):
    os.makedirs(cdir, exist_ok=True)
    R, top = races()
    names = sorted({pool[i]['n'] for s, pool, o in R for i in top[s]})
    print(len(names), 'candidates', flush=True)
    for k, n in enumerate(names):
        fn = os.path.join(cdir, urllib.parse.quote(n, safe='') + '.json')
        if os.path.exists(fn): continue
        t = urllib.parse.quote(n.replace(' ', '_'), safe='')
        u = f'https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{t}/daily/20150701/20250630'
        for a in range(8):
            r = subprocess.run(['curl', '-s', '--compressed', '--max-time', '60', '-A', UA, '-w', '\n%{http_code}', u], capture_output=True, timeout=90)
            body, _, code = r.stdout.decode('utf-8', 'replace').rpartition('\n')
            time.sleep(6)
            if code == '200':
                d = {x['timestamp'][:8]: x['views'] for x in json.loads(body).get('items', [])}
                json.dump(d, open(fn, 'w')); break
            if code == '404': json.dump({}, open(fn, 'w')); break
            time.sleep(6 * (a + 1))
        print(k, n, code, flush=True)


def score(cdir, outfn):
    R, top = races()
    LD = last_days()
    cov = []
    for s, pool, o in R:
        end = dt.date.fromisoformat(LD[s])
        days = [(end - dt.timedelta(days=i)).strftime('%Y%m%d') for i in range(28)]
        v = {}
        for i in top[s]:
            fn = os.path.join(cdir, urllib.parse.quote(pool[i]['n'], safe='') + '.json')
            d = json.load(open(fn)) if os.path.exists(fn) else {}
            tot = sum(d.get(x, 0) for x in days)
            if tot >= 28 * 100: v[i] = tot
        cov.append(len(v))
        t = sum(v.values()) or 1
        lo = min(v.values()) / t if v else 1.0
        for i, r in enumerate(pool): r['lpv'] = math.log(v[i] / t if i in v else lo)
    S = [s for s, _, _ in R]
    rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in R]
    base = E.loso(rr(A.MVP_COLS), S, depth=3)
    full = E.loso(rr(A.MVP_COLS + ['lpv']), S, depth=3)
    pr = E.paired(full, base)
    b, mu, sd = E.fit(rr(A.MVP_COLS + ['lpv']), depth=3)
    out = {'seasons': len(S), 'with_views_per_season': cov, 'll_base': round(sum(x['ll'] for x in base) / len(S), 4),
           'll_full': round(sum(x['ll'] for x in full) / len(S), 4), 'gain': pr['gain'], 't': pr['t'],
           'p': round(t_sf(pr['t'], pr['n'] - 1), 5), 'wins': pr['wins'], 'hits': [sum(x['hit'] for x in base), sum(x['hit'] for x in full)],
           'b_lpv': round(b[-1], 3)}
    out['pass_raw'] = bool(out['p'] < .05 and out['wins'] >= 7 and out['gain'] > 0)
    print(json.dumps(out, indent=1))
    json.dump(out, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    fetch(sys.argv[2]) if sys.argv[1] == 'fetch' else score(sys.argv[2], sys.argv[3])
