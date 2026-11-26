#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Each transaction row's player value, for the transactions and recruit transactions tabs
(layouts/shortcodes/transactions.html, recruitnews.html) -> data/transactions/values.json.

  cfb cbb      FV: the board's headline FV (static/data/cfb-all.json, cbb-all.json)
  nfl          WAR (static/data/nfl-war.json) + SVAR (data/nfl_qb.json, data/nfl_season_value.json; QBs, skill, defense)
  nba          XPM + VORX (static/data/nba-xpm/<latest season>.json)
  nhl          WAR (static/data/nhl-war/<latest>.json)
  soccer       GAR, SVAR (static/data/soccer-war/<latest>.json)
  recruits     ARK stars + FV (year-1 xFV, rounded) from static/data/cfb-recruits.json (full class, future classes) and
               data/cbb_recruits.json (classes, international); a row that is no recruit (a portal move) takes the board FV
Rows join by name through scripts/names.py (club from or to checked first, then the name alone when it is unique);
a pro row with no value this season is left blank.

{asof, <sport>: {"<d>|<n>|<k>": [v, v2]}, rcfb / rcbb: {"<d>|<n>|<k>": [ark, fv(, class when the headline gave none)]}}

  python3 scripts/transaction_values.py
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'transactions', 'values.json')


def load(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def latest(pattern):
    fs = sorted(glob.glob(os.path.join(ROOT, pattern)))
    return os.path.relpath(fs[-1], ROOT) if fs else None


def cols(d):
    return [dict(zip(d['cols'], r)) for r in d['rows']]


def any_team(want, t):
    """want: the row's clubs (from, to); t: the source's club"""
    return any(names.same_team(w, t) or (w and t and str(w).upper() == str(t).upper()) for w in want if w)


def lookup(m, r, sport='football'):
    if m is None: return None
    hit, _ = m.find(r['n'], team=tuple(x for x in (r.get('fr'), r.get('to')) if x) or None, pos=r.get('pos') or None)
    return hit


def rnd(x, n=2):
    return None if x is None else round(float(x), n)


def college(sport):
    d = load(f'static/data/{sport}-all.json')
    if not d: return None
    rows = [r for r in cols(d) if r.get('fv') is not None]
    return names.Matcher(rows, name='name', team='team', pos='pos', sport='football' if sport == 'cfb' else 'basketball',
                         team_eq=lambda want, t: any_team(want, t))


def matcher(rows, team, sport='football'):
    return names.Matcher(rows, name='n', team=team, pos='pos', sport=sport, team_eq=lambda want, t: any_team(want, t))


def pro_values():
    out = {}
    tx = {s: (load(f'data/transactions/{s}.json') or {}).get('rows') or [] for s in ('nfl', 'nba', 'nhl', 'soccer')}

    d = load('static/data/nfl-war.json') or {}
    mw = matcher(d.get('players') or [], 't')
    sv = [dict(r, pos='QB') for r in (load('data/nfl_qb.json') or {}).get('rows') or []]
    s2 = load('data/nfl_season_value.json') or {}
    sv += (s2.get('skill') or []) + (s2.get('defense') or [])
    ms = matcher(sv, 't')
    o = {}
    for r in tx['nfl']:
        w, s = lookup(mw, r), lookup(ms, r)
        v = [rnd(w and w.get('war')), rnd(s and s.get('svar'))]
        if v != [None, None]: o[f"{r['d']}|{r['n']}|{r['k']}"] = v
    out['nfl'] = o

    p = latest('static/data/nba-xpm/*.json')
    m = matcher((load(p) or {}).get('players') or [], 'tm', 'basketball') if p else None
    o = {}
    for r in tx['nba']:
        h = lookup(m, r)
        if h: o[f"{r['d']}|{r['n']}|{r['k']}"] = [rnd(h.get('txpm', h.get('xpm')), 1), rnd(h.get('vorx'))]
    out['nba'] = o

    p = latest('static/data/nhl-war/*.json')
    m = names.Matcher((load(p) or {}).get('players') or [], name='n', team='tm', pos=None, sport='hockey',
                      team_eq=lambda want, t: any_team(want, t)) if p else None
    o = {}
    for r in tx['nhl']:
        h = m and m.find(r['n'], team=tuple(x for x in (r.get('fr'), r.get('to')) if x) or None)[0]
        if h: o[f"{r['d']}|{r['n']}|{r['k']}"] = [rnd(h.get('war')), None]
    out['nhl'] = o

    p = latest('static/data/soccer-war/*.json')
    m = names.Matcher((load(p) or {}).get('players') or [], name='n', team='team', pos=None, sport='soccer',
                      team_eq=lambda want, t: any_team(want, t)) if p else None
    o = {}
    for r in tx['soccer']:
        h = m and m.find(r['n'], team=tuple(x for x in (r.get('fr'), r.get('to')) if x) or None)[0]
        if h and h.get('gar') is not None: o[f"{r['d']}|{r['n']}|{r['k']}"] = [rnd(h.get('gar')), rnd(h.get('svar'))]
    out['soccer'] = o
    return out


def college_values():
    out = {}
    for s in ('cfb', 'cbb'):
        m = college(s)
        o = {}
        for r in (load(f'data/transactions/{s}.json') or {}).get('rows') or []:
            h = lookup(m, r)
            if h: o[f"{r['d']}|{r['n']}|{r['k']}"] = [h['fv'], None]
        out[s] = o
    return out


def recruit_pool(sport):
    """[{n, team, pos, cls, ark, fv}] every recruit on the class tabs"""
    if sport == 'cfb':
        d = load('static/data/cfb-recruits.json') or load('data/cfb_recruits.json') or {}
        rows = [dict(r, cls=d.get('next')) for r in d.get('class') or []]
        for f in d.get('future') or []:
            rows += [dict(r, cls=f.get('year')) for r in f.get('list') or []]
        return [{'n': r['name'], 'team': r.get('team'), 'pos': r.get('pos'), 'cls': r.get('cls'), 'ark': r.get('ark'),
                 'fv': None if r.get('xfv') is None else int(round(r['xfv']))} for r in rows]
    d = load('data/cbb_recruits.json') or {}
    rows = []
    for c in d.get('classes') or []:
        rows += [dict(r, cls=c.get('year')) for r in c.get('list') or []]
    rows += d.get('intl') or []
    return [{'n': r['name'], 'team': r.get('team'), 'pos': r.get('pos'), 'cls': r.get('cls'), 'ark': r.get('ark'),
             'fv': r.get('fv')} for r in rows]


def recruit_values():
    news = load('data/recruit_news.json') or {}
    out = {}
    for s in ('cfb', 'cbb'):
        sp = 'football' if s == 'cfb' else 'basketball'
        rec = names.Matcher(recruit_pool(s), name='n', team='team', pos='pos', cls='cls', sport=sp,
                            team_eq=lambda want, t: any_team(want, t))
        board = college(s)
        o = {}
        for r in news.get(s) or []:
            cls = r.get('cls')
            want = tuple(x for x in (r.get('fr'), r.get('to')) if x) or None
            h, _ = rec.find(r['n'], team=want, pos=r.get('pos') or None, cls=(lambda c, y=cls: c == y) if cls else None)
            if h:
                o[f"{r['d']}|{r['n']}|{r['k']}"] = [h.get('ark'), h.get('fv')] + ([h['cls']] if not cls and h.get('cls') else [])
                continue
            b = lookup(board, r)
            if b: o[f"{r['d']}|{r['n']}|{r['k']}"] = [None, b['fv']]
        out['r' + s] = o
    return out


def main():
    out = {'asof': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    for f in (college_values, pro_values, recruit_values):
        try:
            out.update(f())
        except Exception as e:  # noqa: BLE001
            print(f'transaction values {f.__name__}: skipped ({e!r})')
    old = load(os.path.relpath(OUT, ROOT)) or {}
    for k, v in old.items():      # a source down keeps its last values
        out.setdefault(k, v)
    with open(OUT + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(OUT + '.tmp', OUT)
    tx = {s: len((load(f'data/transactions/{s}.json') or {}).get('rows') or []) for s in ('cfb', 'cbb', 'nfl', 'nba', 'nhl', 'soccer')}
    news = load('data/recruit_news.json') or {}
    tx.update({'rcfb': len(news.get('cfb') or []), 'rcbb': len(news.get('cbb') or [])})
    print('transaction values:', ', '.join(f'{k} {len(out.get(k) or {})}/{n}' for k, n in tx.items()))


if __name__ == '__main__':
    main()
