#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Article views and favorites (worker/site.js /api/posts) kept in the repo for ARKLOG milestones: data/post_stats.json.

    python3 scripts/post_stats.py           # read https://arkndjl.net/api/posts and add a sample where a count moved
    python3 scripts/post_stats.py --test

posts.<slug> = {"t": title, "v": views, "f": favorites, "h": [[ms, v, f], ...]}. The Worker holds the live counts (one view a
visitor a day); this file only samples them (site-stats.yml, every 6 hours), so a crossing is dated by the sample after it.
Titles come from content/posts front matter (Hugo lowercases the file name into the slug).
"""
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'data/post_stats.json'
API = 'https://arkndjl.net/api/posts'


def titles():
    out = {}
    for f in (ROOT / 'content/posts').glob('*.md'):
        s = f.read_text(errors='ignore')
        slug = f.stem.lower()
        m = re.search(r'^slug\s*[=:]\s*["\']?([^"\'\n]+)', s, re.M)
        if m:
            slug = m.group(1).strip().lower()
        t = re.search(r'^title\s*[=:]\s*["\'](.+?)["\']\s*$', s, re.M)
        out[slug] = t.group(1) if t else f.stem
    return out


def merge(d, live, now, names):
    ps = d.setdefault('posts', {})
    for slug, c in sorted(live.items()):
        v, f = int(c.get('v') or 0), int(c.get('f') or 0)
        p = ps.setdefault(slug, {'v': 0, 'f': 0, 'h': []})
        p['t'] = names.get(slug.lower(), p.get('t') or slug)
        if not p['h'] or p['h'][-1][1:] != [v, f]:
            p['h'].append([now, v, f])
        p['v'], p['f'] = v, f
    return d


def test():
    d = merge({}, {'a': {'v': 3, 'f': 1}}, 1, {'a': 'A'})
    d = merge(d, {'a': {'v': 3, 'f': 1}}, 2, {})
    assert d['posts']['a']['h'] == [[1, 3, 1]], d
    d = merge(d, {'a': {'v': 5, 'f': 0}, 'b': {'v': 1}}, 3, {})
    assert d['posts']['a']['h'][-1] == [3, 5, 0] and d['posts']['a']['t'] == 'A' and d['posts']['b']['f'] == 0
    assert titles(), 'no posts found'
    print('post_stats: ok')


def main():
    if '--test' in sys.argv:
        return test()
    req = urllib.request.Request(API, headers={'User-Agent': 'arkndjl-site-stats', 'Accept': 'application/json'})
    try:
        live = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:   # the Worker down is not a failed run: keep the file as it is
        print(f'post_stats: {API} unreadable ({e}); file kept')
        return
    d = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    merge(d, live, now, titles())
    d['asof'] = dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + '\n')
    print(f'post_stats: {len(live)} articles, {sum(int(c.get("v") or 0) for c in live.values()):,} views')


if __name__ == '__main__':
    main()
