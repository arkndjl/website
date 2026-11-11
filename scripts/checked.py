# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The 'checked' stamp of a data file a build rewrites only when its content changes.

A writer that keeps the old file (and its asof) when nothing changed leaves the asof at the last change, so a quiet
stretch (an international break, a slate with no new injuries) read as a stale feed. `checked` is the time a run last
confirmed the content; `asof` stays the time the content last changed. scripts/data_health.py and the site's stamps
(layouts/partials/fresh-asof.html) read checked first, then asof.

    out = checked.stamp(old, new, now)    # None: nothing to write; else the dict to write

Unchanged content moves `checked` at most once every EVERY hours, so a half-hourly job adds two commits a day, not 48.
"""
import datetime as dt

EVERY = 12
META = ('asof', 'checked')


def body(d):
    return {k: v for k, v in (d or {}).items() if k not in META}


def parse(a):
    try:
        return dt.datetime.fromisoformat(str(a).replace('Z', '+00:00'))
    except ValueError:
        return None


def stamp(old, new, now, every=EVERY, same=None):
    """`new` with checked = now when its content differs from `old` (`same`: the comparison already made, for a
    writer whose content needs a JSON round trip before it compares); `old` with checked = now when the content is the
    same and its last check is `every` hours old or more; None when the content is the same and was checked lately"""
    t = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    if same is None:
        same = bool(old) and body(old) == body(new)
    if not same:
        return {**new, 'checked': t}
    last = parse(old.get('checked') or old.get('asof'))
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=dt.timezone.utc)
    if last is not None and (now - last).total_seconds() < every * 3600:
        return None
    return {**old, 'checked': t}


if __name__ == '__main__':
    U = dt.timezone.utc
    n = dt.datetime(2026, 11, 11, 14, 0, tzinfo=U)
    old = {'asof': '2026-11-09T16:00:00Z', 'x': 1}
    assert stamp(old, {'asof': '2026-11-11T14:00:00Z', 'x': 1}, n) == {**old, 'checked': '2026-11-11T14:00:00Z'}
    assert stamp({**old, 'checked': '2026-11-11T08:00:00Z'}, {'asof': 'z', 'x': 1}, n) is None
    assert stamp({**old, 'checked': '2026-11-11T01:00:00Z'}, {'asof': 'z', 'x': 1}, n)['asof'] == old['asof']
    assert stamp(old, {'asof': '2026-11-11T14:00:00Z', 'x': 2}, n) == {'asof': '2026-11-11T14:00:00Z', 'x': 2, 'checked': '2026-11-11T14:00:00Z'}
    assert stamp(None, {'asof': 'a', 'x': 2}, n)['checked'] == '2026-11-11T14:00:00Z'
    assert stamp({'asof': '2026-11-11', 'x': 1}, {'x': 1}, n)['checked']
    print('checked.py: ok')
