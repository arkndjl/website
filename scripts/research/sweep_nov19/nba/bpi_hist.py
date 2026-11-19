# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ESPN predictor history sample for the stack test and its point-in-time gate (PREREG.md lead 4).

    python3 bpi_hist.py core OUT.json     # predictor rows for the seeded sample (480 lined games a season, 2022-2026)
    python3 bpi_hist.py wp OUT.json       # gate G2: the first 40 of each season's sample, summary winprobability[0]

Sample order is fixed by seed 20261119; resumable."""
import gzip, json, os, random, sys, time, urllib.request
import common as C


def sample():
    G = json.load(gzip.open(os.path.join(C.SCRIPTS, 'nba_games_hist.json.gz')))['games']
    rng = random.Random(20261119)
    out = {}
    for S in range(2022, 2027):
        ids = sorted(g['id'] for g in G if g['S'] == S and g.get('fin') and g.get('L') is not None)
        rng.shuffle(ids)
        out[S] = ids[:480]
    return out


def get(url):
    for k in range(3):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40))
            time.sleep(1.1)
            return r
        except Exception as e:
            err = str(e); time.sleep(4 * (k + 1))
    return {'error': err}


def main():
    mode, fn = sys.argv[1], sys.argv[2]
    res = json.load(open(fn)) if os.path.exists(fn) else {}
    smp = sample()
    order = [i for k in range(480) for S in smp for i in smp[S][k:k + 1]] if mode == 'core' else [i for S in smp for i in smp[S][:40]]
    for n, gid in enumerate(order):
        if gid in res: continue
        if mode == 'core':
            p = get(f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{gid}/competitions/{gid}/predictor')
            st = lambda side: {s['name']: s.get('value') for s in (p.get(side) or {}).get('statistics', [])}
            res[gid] = {'lm': p.get('lastModified'), 'home': st('homeTeam'), 'away': st('awayTeam'), 'error': p.get('error')}
        else:
            s = get(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}')
            wp = s.get('winprobability') or []
            res[gid] = {'wp0': wp[0].get('homeWinPercentage') if wp else None, 'n': len(wp)}
        if n % 50 == 0:
            json.dump(res, open(fn, 'w'))
    json.dump(res, open(fn, 'w'))
    print(mode, len(res))


if __name__ == '__main__':
    main()
