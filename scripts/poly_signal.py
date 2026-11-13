#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Polymarket as an edge signal for the Predictions picks: does Polymarket's price when a pick was flagged say anything
about the pick's value at the close that our model and the Novig line did not? Research; writes data/poly_signal.json.

    python3 scripts/poly_signal.py        # pulls Polymarket histories (cached in scripts/.cache/poly_signal)

Pre-registered before the first run (Nov 13 2026). For every judged live game pick (NBA, CBB, CFB, NFL; spread, total,
moneyline) matched to the Polymarket (polymarket.com, gamma-api + clob prices-history) market at the SAME team, side
and line, s = Polymarket's chance of our side at the flag time minus the chance the posted price implies (1 / decimal).
  T1  clvRet on s (day-clustered slope, t >= 2): Polymarket carries information the pick's price did not.
  T2  the filter "skip a pick when s < 0": kept picks' clvRet > all picks' (day-clustered paired t >= 2 on the dropped
      picks being worse) and kept picks beat the close (t >= 1.65).
  T3  the forecast: Polymarket's flag-time chance against the posted price's chance, squared error to the close's
      chance (paired by day, t >= 2).
Pass any of T1/T2 -> the filter or a blend goes to the pick rule under the usual clock; fail -> Polymarket stays a
comparison venue only. Global Polymarket stands in for Polymarket US here (US has no price history); the US book is
the one a pick would be placed on (scripts/polymarket.py).
"""
import datetime
import gzip
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names  # noqa: E402
import rule_monitor as RM  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'poly_signal.json')
CACHE = os.path.join(HERE, '.cache', 'poly_signal')
GAMMA = 'https://gamma-api.polymarket.com/events'
CLOB = 'https://clob.polymarket.com/prices-history'
TAG = {'nba': 'nba', 'cbb': 'ncaa-basketball', 'cfb': 'cfb', 'nfl': 'nfl'}
ESPN = {'cfb': 'football/college-football', 'nfl': 'football/nfl', 'cbb': 'basketball/mens-college-basketball', 'nba': 'basketball/nba'}
EQ = {'cfb': '&groups=80&limit=400', 'nfl': '&limit=100', 'cbb': '&groups=50&limit=500', 'nba': '&limit=100'}


def get(url, cache=True, gz=False):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, str(abs(hash(url)) % 10 ** 12) + '.json')
    import hashlib
    fn = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if cache and os.path.exists(fn):
        return json.load(open(fn))
    for k in range(4):
        try:
            r = subprocess.run(['curl', '-sS', '--compressed', '-m', '40', '-A', 'arkndjl.net arkboard (odds research)', url],
                               capture_output=True, text=True, timeout=60)
            d = json.loads(r.stdout)
            json.dump(d, open(fn, 'w'))
            return d
        except (ValueError, subprocess.TimeoutExpired):
            time.sleep(2 * (k + 1))
    return None


def dec(o):
    o = float(o)
    return 1 + (o / 100 if o > 0 else 100 / -o)


def et_date(t):
    d = datetime.datetime.strptime(t[:19], '%Y-%m-%dT%H:%M:%S') - datetime.timedelta(hours=5)
    return d.strftime('%Y-%m-%d')


def ts(t):
    return int(datetime.datetime.strptime(t[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=datetime.timezone.utc).timestamp())


def espn_teams(sport, dates):
    """{espn id: {'home': [names], 'away': [names]}}"""
    out = {}
    for d in sorted(dates):
        j = get(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/scoreboard?dates={d.replace('-', '')}{EQ[sport]}")
        for ev in (j or {}).get('events', []):
            c = (ev.get('competitions') or [{}])[0]
            row = {}
            for t in c.get('competitors', []):
                tm = t.get('team') or {}
                row[t.get('homeAway')] = [x for x in (tm.get('location'), tm.get('displayName'), tm.get('shortDisplayName'),
                                                       tm.get('name'), tm.get('abbreviation')) if x]
            out[str(ev['id'])] = row
    return out


def pm_events(sport, lo, hi):
    evs, off = [], 0
    while True:
        j = get(f'{GAMMA}?tag_slug={TAG[sport]}&end_date_min={lo}T00:00:00Z&end_date_max={hi}T00:00:00Z&limit=100&offset={off}')
        if not isinstance(j, list) or not j:
            break
        evs += [e for e in j if any(m.get('sportsMarketType') in ('spreads', 'totals', 'moneyline') for m in e.get('markets', []))]
        if len(j) < 100:
            break
        off += 100
    return evs


def pm_names(t):
    return [x for x in (t.get('alias'), t.get('name'), t.get('abbreviation')) if x]


def fits(espn_names, pm):
    ks = {names.team_key(x) for x in espn_names}
    return any(names.team_key(x) in ks for x in pm)


def match(pick, row, evs):
    """the Polymarket event for a pick (both teams fit, start within 36 h)"""
    k = ts(pick['kick'])
    for e in evs:
        st = e.get('startTime') or e.get('endDate')
        if not st or abs(ts(st.replace(' ', 'T')) - k) > 36 * 3600:
            continue
        tms = e.get('teams') or []
        if len(tms) < 2:
            continue
        h = [t for t in tms if fits(row.get('home', []), pm_names(t))]
        a = [t for t in tms if fits(row.get('away', []), pm_names(t))]
        if h and a and h[0] is not a[0]:
            return e, h[0], a[0]
    return None


def token(pick, e, th, ta):
    """(token id, label) of our side at our line in the event, or None"""
    side, mk = pick['side'], pick['mk']
    ours = th if side == 'home' else ta
    for m in e.get('markets', []):
        smt = m.get('sportsMarketType')
        try:
            outs, toks = json.loads(m.get('outcomes') or '[]'), json.loads(m.get('clobTokenIds') or '[]')
        except ValueError:
            continue
        if len(outs) != 2 or len(toks) != 2:
            continue
        if mk == 'total' and smt == 'totals' and m.get('line') is not None and abs(float(m['line']) - pick['line']) < 1e-6:
            i = 0 if outs[0].lower().startswith('over') else 1
            return toks[i if side == 'over' else 1 - i]
        if mk in ('spread', 'ml'):
            want = 'spreads' if mk == 'spread' else 'moneyline'
            if smt != want:
                continue
            i0 = 0 if any(names.team_key(outs[0]) == names.team_key(x) for x in pm_names(ours)) else \
                (1 if any(names.team_key(outs[1]) == names.team_key(x) for x in pm_names(ours)) else None)
            if i0 is None:
                continue
            if mk == 'ml':
                return toks[i0]
            ln = m.get('line')
            if ln is None:
                continue
            ln = float(ln) if i0 == 0 else -float(ln)      # the line belongs to the first outcome
            if abs(ln - pick['line']) < 1e-6:
                return toks[i0]
    return None


def price_at(tok, t, back=6 * 3600):
    """the last Polymarket price at or before t (within `back` seconds)"""
    j = get(f'{CLOB}?market={tok}&startTs={t - back}&endTs={t}&fidelity=5')
    hs = (j or {}).get('history') or []
    hs = [h for h in hs if h.get('t', 0) <= t and 0.02 <= float(h.get('p', 0)) <= 0.98]
    return float(hs[-1]['p']) if hs else None


def books():
    out = []
    for s in ('nba', 'cbb', 'cfb', 'nfl'):
        d = json.load(open(os.path.join(ROOT, 'data', f'games_picks_{s}.json')))
        for e in (d.get('log') or []) + (d.get('withdrawnLog') or []):
            if RM.judged(e) and e.get('clvRet') is not None and e.get('price') is not None and e.get('flagged'):
                if e['mk'] in ('spread', 'total') and e.get('line') is None:
                    continue
                out.append(e)
    return out


def build():
    ps = books()
    rows, miss = [], {}
    for s in ('nba', 'cbb', 'cfb', 'nfl'):
        sp = [p for p in ps if p['sport'] == s]
        if not sp:
            continue
        dates = {et_date(p['kick']) for p in sp}
        lo = (min(datetime.date.fromisoformat(d) for d in dates) - datetime.timedelta(days=2)).isoformat()
        hi = (max(datetime.date.fromisoformat(d) for d in dates) + datetime.timedelta(days=3)).isoformat()
        teams = espn_teams(s, dates)
        evs = pm_events(s, lo, hi)
        print(f'{s}: {len(sp)} picks, {len(evs)} Polymarket games')
        for p in sp:
            row = teams.get(str(p['espn']))
            m = match(p, row, evs) if row else None
            if not m:
                miss[s] = miss.get(s, 0) + 1
                continue
            tok = token(p, *m)
            if not tok:
                miss[s + ' line'] = miss.get(s + ' line', 0) + 1
                continue
            pf = price_at(tok, ts(p['flagged']))
            pk = price_at(tok, ts(p['kick']) - 120)
            if pf is None:
                miss[s + ' price'] = miss.get(s + ' price', 0) + 1
                continue
            imp = 1 / dec(p['price'])
            q = min(0.999, max(0.001, (p['clvRet'] + 1) / dec(p['price'])))
            rows.append({'sport': s, 'mk': p['mk'], 'kick': p['kick'], 'day': RM.day(p['kick']), 'clvRet': p['clvRet'],
                         'evDU': p.get('evDU'), 'imp': round(imp, 4), 'pmFlag': pf, 'pmKick': pk, 'q': round(q, 4),
                         's': round(pf - imp, 4)})
    return rows, miss


def slope(xs, ys, days):
    """OLS slope of y on x with intercept, day-clustered se: (b, se, t)"""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None, None, None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    acc = {}
    for x, y, d in zip(xs, ys, days):
        acc[d] = acc.get(d, 0.0) + (x - mx) * (y - a - b * x)
    G = len(acc)
    se = math.sqrt(sum(v * v for v in acc.values()) * G / max(1, G - 1)) / sxx
    return b, se, (b / se if se else None)


def report(rows, miss):
    days = [r['day'] for r in rows]
    out = {'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'n': len(rows), 'miss': miss}
    b, se, t = slope([r['s'] for r in rows], [r['clvRet'] for r in rows], days)
    out['T1'] = {'slope': b and round(b, 4), 'se': se and round(se, 4), 't': t and round(t, 2), 'pass': bool(t and t >= 2)}
    keep = [r for r in rows if r['s'] >= 0]
    drop = [r for r in rows if r['s'] < 0]
    mk_, sk, tk, gk = RM.clustered([r['clvRet'] for r in keep], [r['day'] for r in keep])
    md, sd_, td, gd = RM.clustered([r['clvRet'] for r in drop], [r['day'] for r in drop])
    ma, sa, ta, ga = RM.clustered([r['clvRet'] for r in rows], days)
    # paired by day: keep minus drop within days that have both
    by = {}
    for r in rows:
        by.setdefault(r['day'], [[], []])[0 if r['s'] >= 0 else 1].append(r['clvRet'])
    diffs = [sum(k) / len(k) - sum(d) / len(d) for k, d in by.values() if k and d]
    if len(diffs) > 1:
        md_ = sum(diffs) / len(diffs)
        sdd = math.sqrt(sum((x - md_) ** 2 for x in diffs) / (len(diffs) - 1) / len(diffs))
        pt = md_ / sdd if sdd else None
    else:
        md_, pt = None, None
    out['T2'] = {'all': [len(rows), ma and round(ma, 4), ta and round(ta, 2)], 'keep': [len(keep), mk_ and round(mk_, 4), tk and round(tk, 2)],
                 'drop': [len(drop), md and round(md, 4), td and round(td, 2)], 'pairedDays': len(diffs),
                 'pairedDiff': md_ and round(md_, 4), 'pairedT': pt and round(pt, 2),
                 'pass': bool(pt and pt >= 2 and tk and tk >= 1.65 and (mk_ or 0) > 0)}
    e_pm = [(r['pmFlag'] - r['q']) ** 2 for r in rows]
    e_px = [(r['imp'] - r['q']) ** 2 for r in rows]
    m3, s3, t3, g3 = RM.clustered([a - b_ for a, b_ in zip(e_px, e_pm)], days)
    out['T3'] = {'msePm': round(sum(e_pm) / len(e_pm), 5), 'msePrice': round(sum(e_px) / len(e_px), 5),
                 'gain': m3 and round(m3, 5), 't': t3 and round(t3, 2), 'pass': bool(t3 and t3 >= 2)}
    out['bySport'] = {}
    for s in sorted({r['sport'] for r in rows}):
        rs = [r for r in rows if r['sport'] == s]
        b, se, t = slope([r['s'] for r in rs], [r['clvRet'] for r in rs], [r['day'] for r in rs]) if len(rs) > 5 else (None, None, None)
        out['bySport'][s] = {'n': len(rs), 'meanS': round(sum(r['s'] for r in rs) / len(rs), 4), 'slope': b and round(b, 3), 't': t and round(t, 2),
                             'keep': sum(1 for r in rs if r['s'] >= 0)}
    return out


if __name__ == '__main__':
    rows, miss = build()
    out = report(rows, miss) if rows else {'n': 0, 'miss': miss}
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
