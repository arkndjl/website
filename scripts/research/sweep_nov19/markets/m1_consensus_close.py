# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""M1: stored close (scripts/data/games_wf) vs a multi-book consensus close (Hugging Face minmaxxxer CSVs, CC BY 4.0).
    python3 m1_consensus_close.py <dir with the four CSVs> <out.json>
Join = start hour (UTC) or day + final score. Paired per game, clustered by game day."""
import csv, gzip, json, math, os, sys, collections
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
WF = os.path.join(ROOT, 'scripts', 'data', 'games_wf')


def clt(d, days):
    """mean, t clustered by day (cluster sums), n"""
    by = collections.defaultdict(float); n = len(d)
    m = sum(d) / n
    for x, k in zip(d, days): by[k] += x - m
    G = len(by)
    v = sum(s * s for s in by.values()) * G / (G - 1) / n / n
    return m, (m / math.sqrt(v) if v > 0 else 0.0), n


def nv(a, b):
    f = lambda o: (-o / (-o + 100)) if o < 0 else 100 / (o + 100)
    pa, pb = f(a), f(b)
    return pa / (pa + pb)


def ll(p, y):
    p = min(max(p, 1e-3), 1 - 1e-3)
    return -math.log(p if y else 1 - p)


def run(csvdir):
    out = {}
    rd = lambda f: list(csv.DictReader(open(os.path.join(csvdir, f))))
    # NBA and NFL: spread + total
    for sp, files in (('nba', {2025: 'nba_2024_25_closing_lines_ats.csv', 2026: 'nba_2025_26_closing_lines_ats.csv'}),
                      ('nfl', {2025: 'nfl_2025_closing_lines_ats.csv'})):
        W = json.load(gzip.open(os.path.join(WF, sp + '.json.gz')))
        for S, f in files.items():
            idx = {}
            for g in W:
                if g['S'] != S or g.get('res') is None or g.get('tot') is None: continue
                hs, as_ = (g['tot'] + g['res']) / 2, (g['tot'] - g['res']) / 2
                idx.setdefault((g['date'][:10], int(hs), int(as_)), []).append(g)
            ds, dt_, days, gaps, n_csv, dml = [], [], [], [], 0, []
            for r in rd(f):
                if not r['home_score'] or not r['close_spread_home']: continue
                n_csv += 1
                key = (r['start_time_utc'][:10] if sp == 'nba' else r['date_et'], int(r['home_score']), int(r['away_score']))
                c = idx.get(key) or (idx.get((r['date_et'], key[1], key[2])) if sp == 'nba' else None)
                if not c or len(c) != 1: continue
                g = c[0]
                if g.get('L') is None: continue
                cl = -float(r['close_spread_home'])
                gaps.append(g['L'] - cl)
                ds.append(abs(g['res'] - g['L']) - abs(g['res'] - cl))
                if g.get('T') is not None and r['close_total']:
                    dt_.append((abs(g['tot'] - g['T']) - abs(g['tot'] - float(r['close_total'])), r['date_et']))
                if g.get('mlH') and g.get('mlA') and r['close_home_win_prob']:
                    y = g['res'] > 0
                    dml.append((ll(nv(g['mlH'], g['mlA']), y) - ll(float(r['close_home_win_prob']), y), r['date_et']))
                days.append(r['date_et'])
            m, t, n = clt(ds, days)
            ag = [abs(x) for x in gaps]
            res = {'csv': n_csv, 'n': n, 'spread_mae_stored_minus_cons': round(m, 4), 't': round(t, 2),
                   'gap_mean_abs': round(sum(ag) / n, 3), 'gap_same': round(sum(x < .01 for x in ag) / n, 3),
                   'gap_gt3': round(sum(x > 3 for x in ag) / n, 4)}
            if dt_:
                m2, t2, n2 = clt([x for x, _ in dt_], [k for _, k in dt_]); res['total'] = {'n': n2, 'd': round(m2, 4), 't': round(t2, 2)}
            if dml:
                m3, t3, n3 = clt([x for x, _ in dml], [k for _, k in dml]); res['ml_ll'] = {'n': n3, 'd': round(m3, 5), 't': round(t3, 2)}
            out[f'{sp}_{S}'] = res
            out.setdefault('_rows', {})[f'{sp}_{S}'] = (ds, days)
    ds = out['_rows']['nba_2025'][0] + out['_rows']['nba_2026'][0]
    dy = out['_rows']['nba_2025'][1] + out['_rows']['nba_2026'][1]
    m, t, n = clt(ds, dy)
    out['nba_pooled'] = {'n': n, 'spread_mae_stored_minus_cons': round(m, 4), 't': round(t, 2)}
    del out['_rows']
    # NHL: moneyline log loss + total
    W = json.load(gzip.open(os.path.join(WF, 'nhl.json.gz')))
    idx = {}
    for g in W:
        if g['S'] == 2026 and g.get('c'): idx.setdefault((g['day'], g['hs'], g['as']), []).append(g)
    dm, dt_, days, gp, n_csv = [], [], [], [], 0
    for r in rd('nhl_2025_26_closing_odds.csv'):
        if not r['home_score'] or not r['close_home_win_prob']: continue
        n_csv += 1
        c = idx.get((r['date_et'], int(r['home_score']), int(r['away_score'])))
        if not c or len(c) != 1: continue
        g = c[0]
        if g['c'].get('p') is None: continue
        y = g['hs'] > g['as']
        pc = float(r['close_home_win_prob'])
        dm.append(ll(g['c']['p'], y) - ll(pc, y)); gp.append(abs(g['c']['p'] - pc)); days.append(r['date_et'])
        if g['c'].get('t') and r['close_total']:
            tot = g['hs'] + g['as']
            dt_.append((abs(tot - g['c']['t']) - abs(tot - float(r['close_total'])), r['date_et']))
    m, t, n = clt(dm, days)
    out['nhl_2026'] = {'csv': n_csv, 'n': n, 'ml_ll_stored_minus_cons': round(m, 5), 't': round(t, 2),
                       'p_gap_mean_abs': round(sum(gp) / n, 4), 'p_gap_gt10': round(sum(x > .10 for x in gp) / n, 4)}
    if dt_:
        m2, t2, n2 = clt([x for x, _ in dt_], [k for _, k in dt_]); out['nhl_2026']['total'] = {'n': n2, 'd': round(m2, 4), 't': round(t2, 2)}
    return out


if __name__ == '__main__':
    o = run(sys.argv[1])
    print(json.dumps(o, indent=1))
    if len(sys.argv) > 2: json.dump(o, open(sys.argv[2], 'w'), indent=1)
