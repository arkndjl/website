#!/usr/bin/env python3
"""Milestones for Process > ARKLOG > milestones: social and site numbers crossing round thresholds, read from files already
in the repo and written to data/milestones.json (layouts/shortcodes/arklogmiles.html). Nothing is typed in.

  followers   every account's follower milestones from data/arkndjl_socials.json and data/laursen_socials.json (hist.ms,
              kept by scripts/arkndjl_socials.mjs and the LAURSEN_111 social pull; dates from before tracking are estimates)
  videos      the first video on a channel to pass 1k, 2.5k, 5k, 10k, 25k, 50k and 100k views (yt.v, sampled each pull)
  posts       the first X post to pass 1k, 5k, 10k, 25k, 50k and 100k views (xp.v)
  site        the first day over 250, 500, 1,000, 1,500 and 2,000 page views or visitors, and total page views and
              visitors passing round numbers (data/site_stats.json days)
  ARKLOG      total changes and tests passing round numbers (static/data/arklog.json rows)
  next        each account's next follower goal with its ETA (goals.next), and the next round number for the rest

A threshold first seen already passed (the first sample is over it) is dated by that sample, and one crossed between two samples
is interpolated; both are marked est when the date could be off by more than a day and a half.
    python3 scripts/milestones.py
"""
import datetime as dt
import json
import pathlib
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
ET = ZoneInfo('America/New_York')
OUT = ROOT / 'data/milestones.json'

ACCOUNTS = {
    'arkndjl': ('ARKNDJL', {'x': '@ARKNDJL on X', 'youtube': 'ARKNDJL on YouTube'}),
    'laursen': ('LAURSEN_111', {'twitch': 'LAURSEN_111 on Twitch', 'youtube': 'LAURSEN_111 on YouTube',
                                'tiktok': 'LAURSEN_111 on TikTok', 'x': '@LAURSEN_111 on X', 'ig': 'LAURSEN_111 on Instagram'}),
}
UNIT = {'twitch': 'followers', 'youtube': 'subscribers', 'tiktok': 'followers', 'x': 'followers', 'ig': 'followers'}
VIEWS = [1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 1000000]
POSTS = [1000, 5000, 10000, 25000, 50000, 100000, 250000, 1000000]
DAY = [250, 500, 1000, 1500, 2000, 2500, 5000, 10000]
TOTAL = [1000, 5000, 10000, 25000, 50000, 75000, 100000, 150000, 200000, 250000, 500000, 1000000]
LOG_CH = [100, 250, 500, 1000, 1500, 2000, 2500, 5000]
LOG_T = [50, 100, 250, 500, 750, 1000]


def day(ms):
    return dt.datetime.fromtimestamp(ms / 1000, ET).strftime('%Y-%m-%d')


def n(v):
    return f'{v:,}'


def first_cross(items, thresholds):
    """items: [(name, [[t, v], ...])]; the first item to pass each threshold and when (by = already over at its first sample)"""
    out = []
    for th in thresholds:
        best = None
        for name, vs in items:
            for i, (t, v) in enumerate(vs):
                if v >= th:
                    est = i == 0
                    if i:                       # between two samples: interpolate, and call it an estimate past 36 hours
                        t0, v0 = vs[i - 1]
                        est = t - t0 > 36 * 3600 * 1000
                        t = t0 + (t - t0) * (th - v0) / max(1, v - v0)
                    if best is None or t < best[1]:
                        best = (name, t, est)
                    break
        if best:
            out.append((th, best))
    return out


def social(rows, nxt):
    for key, (sec, names) in ACCOUNTS.items():
        f = ROOT / f'data/{key}_socials.json'
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        for net, h in (d.get('hist') or {}).items():
            for m in h.get('ms') or []:
                if m.get('hit'):
                    rows.append({'d': day(m['hit']), 'sec': sec, 'k': 'followers', 'est': bool(m.get('est')),
                                 't': f'{names.get(net, net)} reached {n(m["goal"])} {UNIT.get(net, "followers")}'})
        last = (d.get('series') or [{}])[-1]
        for net, g in (d.get('goals') or {}).items():
            x = g.get('next')
            if x and last.get(net) is not None:
                nxt.append({'sec': sec, 't': f'{names.get(net, net)}: {n(x["goal"])} {UNIT.get(net, "followers")}',
                            'now': last[net], 'goal': x['goal'], 'eta': x.get('eta'), 'p': x.get('p90')})
        # videos: long-form and shorts apart, the first on the channel to pass each mark
        yt = d.get('yt') or {}
        for short, kind in ((False, 'video'), (True, 'short')):
            items = [(y['title'], y['v']) for y in yt.values() if bool(y.get('short')) == short and y.get('v')]
            for th, (name, t, by) in first_cross(items, VIEWS):
                rows.append({'d': day(t), 'sec': sec, 'k': 'views', 'est': by,
                             't': f'First {sec} YouTube {kind} over {n(th)} views: {name}'})
            if items:
                top = max(items, key=lambda it: it[1][-1][1])
                up = next((th for th in VIEWS if th > top[1][-1][1]), None)
                if up:
                    nxt.append({'sec': sec, 't': f'{sec} YouTube {kind}: {n(up)} views', 'now': top[1][-1][1], 'goal': up,
                                'eta': None, 'p': None, 'of': top[0]})
        xp = d.get('xp') or {}
        items = [(p['text'], p['v']) for p in xp.values() if p.get('v')]
        for th, (name, t, by) in first_cross(items, POSTS):
            short = name if len(name) <= 70 else name[:67].rsplit(' ', 1)[0] + '...'
            rows.append({'d': day(t), 'sec': sec, 'k': 'views', 'est': by, 't': f'First {sec} X post over {n(th)} views: "{short}"'})


def site(rows, nxt):
    f = ROOT / 'data/site_stats.json'
    if not f.exists():
        return
    days = sorted((json.loads(f.read_text()).get('days') or {}).items())
    tot = {'pv': 0, 'u': 0}
    seen_day = {'pv': set(), 'u': set()}
    seen_tot = {'pv': set(), 'u': set()}
    lab = {'pv': 'page views', 'u': 'visitors'}
    for d, v in days:
        for k in ('pv', 'u'):
            x = v.get(k) or 0
            for th in DAY:
                if x >= th and th not in seen_day[k]:
                    seen_day[k].add(th)
                    rows.append({'d': d, 'sec': 'site', 'k': 'traffic', 'est': False, 't': f'First day over {n(th)} {lab[k]} ({n(x)})'})
            before = tot[k]
            tot[k] += x
            for th in TOTAL:
                if before < th <= tot[k] and th not in seen_tot[k]:
                    seen_tot[k].add(th)
                    rows.append({'d': d, 'sec': 'site', 'k': 'traffic', 'est': False, 't': f'{n(th)} total {lab[k]}'})
    if days:
        avg = sum((v.get('pv') or 0) for _, v in days[-7:]) / min(7, len(days))
        for k in ('pv', 'u'):
            up = next((th for th in TOTAL if th > tot[k]), None)
            if up:
                rate = sum((v.get(k) or 0) for _, v in days[-7:]) / min(7, len(days))
                eta = (dt.date.fromisoformat(days[-1][0]) + dt.timedelta(days=round((up - tot[k]) / rate))).isoformat() if rate else None
                nxt.append({'sec': 'site', 't': f'{n(up)} total {lab[k]}', 'now': tot[k], 'goal': up, 'eta': eta, 'p': None})
        del avg


def arklog(rows, nxt):
    f = ROOT / 'static/data/arklog.json'
    if not f.exists():
        return
    rs = sorted(json.loads(f.read_text()).get('rows') or [], key=lambda r: r['d'])
    c = t = 0
    for r in rs:
        if r.get('k') == 'study':
            continue
        c += 1
        if c in LOG_CH:
            rows.append({'d': r['d'][:10], 'sec': 'ARKLOG', 'k': 'log', 'est': False, 't': f'{n(c)} changes logged'})
        if r.get('v') in ('s', 'm', 'f'):
            t += 1
            if t in LOG_T:
                rows.append({'d': r['d'][:10], 'sec': 'ARKLOG', 'k': 'log', 'est': False, 't': f'{n(t)} tests logged'})
    for v, ths, lab in ((c, LOG_CH, 'changes logged'), (t, LOG_T, 'tests logged')):
        up = next((th for th in ths if th > v), None)
        if up:
            nxt.append({'sec': 'ARKLOG', 't': f'{n(up)} {lab}', 'now': v, 'goal': up, 'eta': None, 'p': None})


def main():
    rows, nxt = [], []
    social(rows, nxt)
    site(rows, nxt)
    arklog(rows, nxt)
    rows.sort(key=lambda r: (r['d'], r['t']), reverse=True)
    nxt.sort(key=lambda x: (x['eta'] or '9999', -x['now'] / x['goal']))
    OUT.write_text(json.dumps({'asof': dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'), 'rows': rows, 'next': nxt},
                              ensure_ascii=False, indent=1, allow_nan=False) + '\n')
    print(f'milestones: {len(rows)} reached, {len(nxt)} next')


if __name__ == '__main__':
    main()
