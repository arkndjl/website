#!/usr/bin/env python3
"""Re-attach recruiting grades to the frozen preseason board (scripts/cbb_prior.json.gz), then rebuild the board.

    node scripts/cbb_on3.mjs 2025 2026        # the incoming classes (scripts/.cache/cbb/on3/)
    python3 scripts/cbb_prior_rec.py          # patch the prior's newcomers, then: python3 scripts/cbb_live.py

Why: the Oct 2026 preseason board was built (scripts/fetch_cbb.py) without the On3 cache for the 2025 and 2026 classes,
so every newcomer (all 1,378 freshmen) was graded as an unranked recruit (recruiting rank at the -ln 600 floor): the
No. 4 and No. 7 recruits sat at FV 22 with a 2% NBA chance. This gives each newcomer the grade fetch_cbb.py would
have: On3 consensus rating and rank by name key, else through the shared matcher (scripts/names.py), incoming class
first. 247's rank comes from On3's per-service ranks (247's own pages answer 406 here); 247's composite score is left
out (On3 carries 247's own rating, not the composite the r247 driver reads, and no newcomer driver uses it).
cbb_live.py then re-grades every player from the career and grades the prior holds, so nothing else moves.
"""
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D   # noqa: E402
import names as N      # noqa: E402

PRIOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cbb_prior.json.gz')


def main():
    prior = json.load(gzip.open(PRIOR, 'rt'))
    season = prior['season']
    rec = {}
    for cls in (season - 2, season - 1):     # the class before first (prep years, reclassed), the incoming class wins
        rows = D.load_on3(cls)
        if not rows: sys.exit(f'no On3 {cls} class in the cache: node scripts/cbb_on3.mjs {cls}')
        for r in rows:
            g = {'on3': r['cons'], 'on3rk': r['consRank'], 'on3slug': r['slug'], 'cls': cls}
            rk247 = ((r.get('svc') or {}).get('247') or [None, None])[1]
            if rk247: g['rk247'] = rk247
            rec[r['key']] = g
    m_rec = N.Matcher([dict(v, name=k) for k, v in rec.items()], name='name', team=None, pos=None, sport='basketball')
    ci = {c: j for j, c in enumerate(prior['cols'])}
    hit = 0
    for row, m in zip(prior['rows'], prior['careers']):
        if not row[ci['new']] or m.get('rec'): continue
        g = rec.get(D.norm(row[ci['name']]))
        if g is None:
            h, _ = m_rec.find(row[ci['name']])
            g = {k: v for k, v in h.items() if k != 'name'} if h else None
        if not g: continue
        m['rec'] = {k: v for k, v in g.items() if k != 'on3slug'}
        row[ci['rec']] = dict(m['rec'])
        if g.get('on3slug'):
            links = row[ci['links']] or {}
            links['on3'] = f"https://www.on3.com/rivals/{g['on3slug']}/"
            row[ci['links']] = links
        hit += 1
    print(f'recruiting grades attached to {hit} of {sum(1 for r in prior["rows"] if r[ci["new"]])} newcomers')
    with gzip.open(PRIOR, 'wt') as fh:
        json.dump(prior, fh, separators=(',', ':'))


if __name__ == '__main__':
    main()
