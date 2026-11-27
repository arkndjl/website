#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Recruit birth dates and age for the class (CFB and CBB recruit tabs, recruit cards).

No free source prints a birth date for most high-school recruits. On3 lists a whole-year age for some (about 9% of the
football top 300, about a third of basketball's), and that age read on a date bounds the birth date to one year. Every
daily pull narrows the bound (scripts/data/recruit_age_<sport>.json keeps it per On3 player key), and the day the listed age
goes up pins the birthday. Day-precise dates come from FIBA youth rosters (basketball, scripts/data/fiba_dob.json.gz)
Wikidata (scripts/data/recruit_wikidata_dob.json, scripts/recruit_wikidata.py) and the hand pins in data/dob_overrides.json ("cbb_recruits" / "cfb_recruits": {"<names.key>|<class>": {"dob": ...}}).

Row fields (fields()): `age` years to one decimal on the as-of date when the birth date is known to 45 days or better,
else On3's whole-year age; `ageRel` years older (+) or younger (-) than the class median, only with that precision;
`dob` when a source gives the day. Age for the class = age on Sep 1 of the class year; MED is its median over the
recruits with a day-precise date in the histories (scripts/research/recruit_age_nov26).

    python3 scripts/recruit_age.py --seed-git     # replay data/cbb_recruits.json's git history into the bounds (once)
    python3 scripts/recruit_age.py --stats
"""
import datetime as dt
import gzip
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'scripts', 'data', 'recruit_age_{}.json')   # one file a sport: each sport's workflow commits its own
PINS = os.path.join(ROOT, 'data', 'dob_overrides.json')
FIBA = os.path.join(ROOT, 'scripts', 'data', 'fiba_dob.json.gz')
WIKI = os.path.join(ROOT, 'scripts', 'data', 'recruit_wikidata_dob.json')   # scripts/recruit_wikidata.py
_R = json.load(open(os.path.join(ROOT, 'data', 'recruit_age_research.json')))
MED = {sp: _R[sp]['median'] for sp in ('cbb', 'cfb')}   # median age on Sep 1 of the class year, day-precise dates (cbb: ranked recruits 2009-16; cfb: top-400 recruits of 2011-19 who reached the NFL)
TIGHT = 45                           # days: a bound this narrow reads to a tenth of a year
_S = None


def _years(d, n):
    """d moved back n years (Feb 29 -> Feb 28)"""
    try: return d.replace(year=d.year - n)
    except ValueError: return d.replace(year=d.year - n, day=28)


def load():
    global _S
    if _S is None:
        _S = {sp: json.load(open(STATE.format(sp))) if os.path.exists(STATE.format(sp)) else {} for sp in ('cbb', 'cfb')}
    return _S


def save(sport):
    d = load()[sport]      # read before the file is opened for writing (an unloaded state would be read back empty)
    with open(STATE.format(sport), 'w') as f: json.dump(d, f, separators=(',', ':'), sort_keys=True)


def observe(sport, key, age, cls, name, on=None):
    """one reading of On3's whole-year age: the birth date lies in (on - age - 1 year, on - age], a day of slack each side"""
    if key is None or age is None or not 13 <= age <= 22: return
    on = on or dt.date.today()
    lo, hi = _years(on, age + 1), _years(on, age) + dt.timedelta(days=1)
    s = load()[sport]; k = str(key); p = s.get(k)
    if p:
        a, b = max(lo, dt.date.fromisoformat(p[0])), min(hi, dt.date.fromisoformat(p[1]))
        if a <= b: lo, hi = a, b      # else On3 changed the age it lists: start again from this reading
    s[k] = [lo.isoformat(), hi.isoformat(), cls, name]


def _exact(sport, name, cls, win):
    """a day-precise date: the pins, then (basketball) a FIBA roster date, then a Wikidata date, each only when one
    person of that name fits the class and On3's bound"""
    global _P, _F, _W
    try: _P
    except NameError:
        _P = json.load(open(PINS)) if os.path.exists(PINS) else {}
        _F = json.load(gzip.open(FIBA, 'rt')) if os.path.exists(FIBA) else {}
        _W = json.load(open(WIKI)) if os.path.exists(WIKI) else {}
    p = (_P.get(sport + '_recruits') or {}).get(f'{N.key(name)}|{cls}')
    if p and p.get('dob'): return p['dob'], 'pin'
    if sport == 'cbb':
        ds = [d for d in _F.get(N.key(name), []) if cls - 20 <= int(d[:4]) <= cls - 17]
        if win: ds = [d for d in ds if win[0] <= d <= win[1]]
        if len(ds) == 1 and (win or len(_F.get(N.key(name), [])) == 1): return ds[0], 'fiba'
    al = (_W.get(sport) or {}).get(N.key(name), [])
    ds = [d for d in al if cls - 20 <= int(d[:4]) <= cls - 17]
    if win: ds = [d for d in ds if win[0] <= d <= win[1]]
    if len(ds) == 1 and (win or len(al) == 1): return ds[0], 'wikidata'
    return None, None


def window(sport, key, name=None, cls=None):
    """(earliest, latest birth date, exact?) or None"""
    p = load()[sport].get(str(key)) if key is not None else None
    win = (p[0], p[1]) if p else None
    if name and cls:
        d, _ = _exact(sport, name, cls, win)
        if d: return d, d, True
    return (p[0], p[1], False) if p else None


def old_share(w, cls):
    """the chance he is 18 or older on Oct 26 of his senior year (the basketball model's 'old'): born on or before
    Oct 26 of class - 19, as a share of the bound"""
    lo, hi = dt.date.fromisoformat(w[0]), dt.date.fromisoformat(w[1]); cut = dt.date(cls - 19, 10, 26)
    if hi <= cut: return 1.0
    if lo > cut: return 0.0
    return round(((cut - lo).days + 1) / ((hi - lo).days + 1), 3)


def fields(sport, key, name, cls, listed=None, asof=None):
    """{'age', 'ageRel', 'dob'} for a recruit row (keys left out when unknown)"""
    asof = asof or dt.date.today()
    w = window(sport, key, name, cls)
    if not w: return {'age': listed} if listed is not None else {}
    lo, hi = dt.date.fromisoformat(w[0]), dt.date.fromisoformat(w[1])
    if (hi - lo).days > TIGHT:
        return {'age': listed} if listed is not None else {}
    b = lo + (hi - lo) / 2
    out = {'age': round((asof - b).days / 365.25, 1), 'ageRel': round((dt.date(cls, 9, 1) - b).days / 365.25 - MED[sport], 1) + 0.0}
    if w[2]: out['dob'] = w[0]
    return out


def seed_git():
    """replay every committed data/cbb_recruits.json (its rows carry On3's age on that file's date)"""
    log = subprocess.run(['git', 'log', '--format=%H', '--reverse', '--', 'data/cbb_recruits.json'], cwd=ROOT, capture_output=True, text=True).stdout.split()
    n = 0
    for h in log:
        try: d = json.loads(subprocess.run(['git', 'show', f'{h}:data/cbb_recruits.json'], cwd=ROOT, capture_output=True, text=True).stdout)
        except ValueError: continue
        try: on = dt.date.fromisoformat(str(d.get('asof'))[:10])
        except ValueError: continue
        for c in d.get('classes') or []:
            for r in c.get('list') or []:
                if r.get('age') is None or not r.get('on3') or not float(r['age']).is_integer(): continue
                observe('cbb', r['on3'].rstrip('/').rsplit('-', 1)[-1], int(r['age']), c['year'], r['name'], on); n += 1
    save('cbb')
    print('replayed', len(log), 'files,', n, 'readings')


def stats():
    for sp, s in load().items():
        w = [(dt.date.fromisoformat(p[1]) - dt.date.fromisoformat(p[0])).days for p in s.values()]
        print(sp, len(w), 'recruits with an age;', sum(x <= TIGHT for x in w), f'bounded to {TIGHT} days')


if __name__ == '__main__':
    if '--seed-git' in sys.argv: seed_git()
    stats()
