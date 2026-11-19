#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The site section's numbers (/site/, layouts/shortcodes/sitestats.html): data/site_stats.json.

    python3 scripts/site_stats.py            # Cloudflare traffic + GitHub merges/commits, merged into the file
    python3 scripts/site_stats.py --seed CSV # add a Cloudflare dashboard export (timestamp,value = daily unique visitors)
    python3 scripts/site_stats.py --test

Cloudflare: zone analytics over GraphQL (httpRequests1dGroups: uniques, requests, page views, bytes, cache, countries,
status codes), last 8 days per run, merged by UTC date so history keeps growing past the API's window. Needs secret
CLOUDFLARE_ANALYTICS_TOKEN (custom token: Zone > Analytics > Read and Zone > Zone > Read, zone arkndjl.net);
CLOUDFLARE_ZONE_ID is optional (looked up by name). Without a token the Cloudflare part is skipped.
GitHub: main commits (data bots vs merges) and merged PRs per UTC day, last 60 days (GITHUB_TOKEN).
Derived: 7-day mean, week over week, log-linear trend (growth a week, doubling days, SE), weekday index
(mean ratio of actual to trend by weekday), record day. Run by .github/workflows/site-stats.yml.
"""
import csv
import datetime as dt
import json
import math
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'site_stats.json')
REPO = os.environ.get('GITHUB_REPOSITORY', 'arkndjl/website')
ZONE = 'arkndjl.net'
NOW = dt.datetime.now(dt.timezone.utc)
MON = {m: i + 1 for i, m in enumerate('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split())}
BOTS = ('arkboard-bot', 'actions', 'github-actions[bot]', 'github-actions')


def load():
    try:
        return json.load(open(OUT))
    except (OSError, ValueError):
        return {'days': {}}


def save(d):
    d['asof'] = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1, sort_keys=True, allow_nan=False)
        f.write('\n')


# ---------------------------------------------------------------- seed (dashboard CSV)
def seed(d, path, year=None):
    """Cloudflare's 'Unique visitors' export: rows like '20 OCT,632' (no year: the latest such date not after today)."""
    n = 0
    for r in csv.DictReader(open(path)):
        day, mon = r['timestamp'].split()
        y = year or NOW.year
        t = dt.date(y, MON[mon.upper()[:3]], int(day))
        if t > NOW.date():
            t = t.replace(year=y - 1)
        row = d['days'].setdefault(t.isoformat(), {})
        row.setdefault('u', int(float(r['value'])))
        n += 1
    return n


# ---------------------------------------------------------------- Cloudflare
def cf(path, token, body=None):
    req = urllib.request.Request('https://api.cloudflare.com/client/v4/' + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=60))


Q = '''query($z:String!,$a:Date!,$b:Date!){viewer{zones(filter:{zoneTag:$z}){httpRequests1dGroups(limit:40,
filter:{date_geq:$a,date_leq:$b},orderBy:[date_ASC]){dimensions{date} uniq{uniques}
sum{requests pageViews bytes cachedBytes cachedRequests threats
countryMap{clientCountryName requests} responseStatusMap{edgeResponseStatus requests}}}}}}'''


def cloudflare(d):
    tok = os.environ.get('CLOUDFLARE_ANALYTICS_TOKEN') or os.environ.get('CLOUDFLARE_API_TOKEN')
    if not tok:
        print('cloudflare: no token, skipped')
        return 0
    z = os.environ.get('CLOUDFLARE_ZONE_ID')
    if not z:
        r = cf('zones?name=' + urllib.parse.quote(ZONE), tok)
        z = r['result'][0]['id']
    a = (NOW.date() - dt.timedelta(days=7)).isoformat()
    b = NOW.date().isoformat()
    r = cf('graphql', tok, {'query': Q, 'variables': {'z': z, 'a': a, 'b': b}})
    if r.get('errors'):
        raise SystemExit('cloudflare: %s' % r['errors'])
    n = 0
    for g in r['data']['viewer']['zones'][0]['httpRequests1dGroups']:
        s = g['sum']
        st = {}
        for x in s.get('responseStatusMap') or []:
            k = '%dxx' % (int(x['edgeResponseStatus']) // 100)
            st[k] = st.get(k, 0) + x['requests']
        cc = sorted(s.get('countryMap') or [], key=lambda x: -x['requests'])[:20]
        d['days'][g['dimensions']['date']] = {
            **d['days'].get(g['dimensions']['date'], {}),
            'u': g['uniq']['uniques'], 'req': s['requests'], 'pv': s['pageViews'], 'b': s['bytes'],
            'cb': s['cachedBytes'], 'creq': s['cachedRequests'], 'thr': s['threats'], 'st': st,
            'cc': {x['clientCountryName']: x['requests'] for x in cc}}
        n += 1
    print('cloudflare: %d days' % n)
    return n


# ---------------------------------------------------------------- GitHub
def gh(path):
    h = {'Accept': 'application/vnd.github+json', 'User-Agent': 'site-stats'}
    t = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if t:
        h['Authorization'] = 'Bearer ' + t
    return json.load(urllib.request.urlopen(urllib.request.Request('https://api.github.com/' + path, headers=h), timeout=60))


def github(d, days=60):
    since = (NOW - dt.timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    com = {}
    for p in range(1, 60):
        rows = gh('repos/%s/commits?sha=main&per_page=100&page=%d&since=%s' % (REPO, p, since.strftime('%Y-%m-%dT%H:%M:%SZ')))
        for c in rows:
            day = c['commit']['committer']['date'][:10]
            who = c['commit']['author']['name'] if c['commit']['author']['name'] in BOTS else ((c.get('author') or {}).get('login') or '')
            k = 'bot' if who in BOTS or who.endswith('[bot]') else 'dev'
            e = com.setdefault(day, {'bot': 0, 'dev': 0, 'skip': 0})
            e[k] += 1
            if '[skip ci]' in c['commit']['message']:
                e['skip'] += 1
        if len(rows) < 100:
            break
    prs = {}
    for p in range(1, 30):
        rows = gh('repos/%s/pulls?state=closed&sort=updated&direction=desc&per_page=100&page=%d' % (REPO, p))
        for x in rows:
            if x.get('merged_at') and x['merged_at'] >= since.strftime('%Y-%m-%dT%H:%M:%SZ'):
                prs[x['merged_at'][:10]] = prs.get(x['merged_at'][:10], 0) + 1
        if len(rows) < 100 or rows[-1]['updated_at'] < since.strftime('%Y-%m-%dT%H:%M:%SZ'):
            break
    for day in set(com) | set(prs):
        row = d['days'].setdefault(day, {})
        c = com.get(day, {'bot': 0, 'dev': 0, 'skip': 0})
        row.update({'cbot': c['bot'], 'cdev': c['dev'], 'cskip': c['skip'], 'pr': prs.get(day, 0)})
    print('github: %d commit days, %d PRs' % (len(com), sum(prs.values())))


# ---------------------------------------------------------------- derived
def fit(us):
    """Log-linear OLS of daily uniques on day index: (slope a day, its SE, residuals)."""
    n = len(us)
    if n < 8:
        return None
    x = list(range(n))
    y = [math.log(max(u, 1)) for u in us]
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx
    res = [c - (my + b * (a - mx)) for a, c in zip(x, y)]
    se = math.sqrt(sum(e * e for e in res) / (n - 2) / sxx)
    return b, se, res


def derive(d):
    days = sorted(k for k, v in d['days'].items() if v.get('u') is not None)
    if not days:
        return
    # the dashboard's day for today is partial; leave it out of the summary until it closes
    if days[-1] >= NOW.date().isoformat():
        days = days[:-1]
    us = [d['days'][k]['u'] for k in days]
    s = {'first': days[0], 'last': days[-1], 'n': len(days), 'lastU': us[-1]}
    s['avg7'] = round(sum(us[-7:]) / min(7, len(us)), 1)
    if len(us) >= 14:
        p = sum(us[-14:-7]) / 7
        s['prev7'] = round(p, 1)
        s['wow'] = round(100 * (s['avg7'] / p - 1), 1)
    s['sum30'] = sum(us[-30:])
    i = max(range(len(us)), key=lambda j: us[j])
    s['rec'], s['recDay'] = us[i], days[i]
    w = us[-60:]
    f = fit(w)
    if f:
        b, se, res = f
        s['g7'] = round(100 * (math.exp(7 * b) - 1), 1)
        s['g7lo'] = round(100 * (math.exp(7 * (b - 2 * se)) - 1), 1)
        s['g7hi'] = round(100 * (math.exp(7 * (b + 2 * se)) - 1), 1)
        s['dbl'] = round(math.log(2) / b) if b > 0 else None
        s['sd'] = round(math.exp(math.sqrt(sum(e * e for e in res) / len(res))) - 1, 3)
        wd = {}
        for k, e in zip(days[-60:], res):
            wd.setdefault(dt.date.fromisoformat(k).weekday(), []).append(math.exp(e))
        s['wd'] = [round(sum(wd.get(j, [1])) / max(len(wd.get(j, [])), 1), 3) for j in range(7)]
    # 30-day Cloudflare totals, once the API has written them
    cfd = [d['days'][k] for k in days[-30:] if 'req' in d['days'][k]]
    if cfd:
        req = sum(x['req'] for x in cfd)
        s['cf'] = {'n': len(cfd), 'req': req, 'pv': sum(x['pv'] for x in cfd), 'b': sum(x['b'] for x in cfd),
                   'hit': round(100 * sum(x['creq'] for x in cfd) / max(req, 1), 1),
                   'thr': sum(x['thr'] for x in cfd)}
        st, cc = {}, {}
        for x in cfd:
            for k, v in (x.get('st') or {}).items():
                st[k] = st.get(k, 0) + v
            for k, v in (x.get('cc') or {}).items():
                cc[k] = cc.get(k, 0) + v
        s['cf']['st'] = st
        s['cf']['cc'] = [[k, v] for k, v in sorted(cc.items(), key=lambda t: -t[1])[:10]]
    gd = [d['days'][k] for k in sorted(d['days'])[-30:] if 'cbot' in d['days'][k]]
    if gd:
        s['gh'] = {'pr': sum(x['pr'] for x in gd), 'dev': sum(x['cdev'] for x in gd), 'bot': sum(x['cbot'] for x in gd),
                   'builds': sum(x['cbot'] + x['cdev'] - x['cskip'] for x in gd)}
    # data files: count and size of data/**/*.json (what Hugo reads)
    n = size = 0
    for dp, _, fs in os.walk(os.path.join(ROOT, 'data')):
        for fn in fs:
            if fn.endswith('.json'):
                n += 1
                size += os.path.getsize(os.path.join(dp, fn))
    s['dataFiles'], s['dataMB'] = n, round(size / 2 ** 20, 1)
    d['summary'] = s


def test():
    d = {'days': {}}
    base = dt.date(2026, 1, 1)
    for i in range(28):
        d['days'][(base + dt.timedelta(i)).isoformat()] = {'u': round(500 * 1.02 ** i)}
    derive(d)
    s = d['summary']
    assert abs(s['g7'] - 100 * (1.02 ** 7 - 1)) < 0.3, s['g7']
    assert s['dbl'] == 35, s['dbl']
    assert s['rec'] == round(500 * 1.02 ** 27)
    assert all(abs(x - 1) < 0.01 for x in s['wd'])
    json.dumps(d, allow_nan=False)
    print('ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
        sys.exit()
    d = load()
    d.setdefault('days', {})
    if '--seed' in sys.argv:
        print('seed: %d days' % seed(d, sys.argv[sys.argv.index('--seed') + 1]))
    else:
        cloudflare(d)
        github(d)
    derive(d)
    save(d)
