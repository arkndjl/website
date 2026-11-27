#!/usr/bin/env python3
"""Understat as it stood part-way through each finished season (the freeze an outage leaves): GAR and SV per player
after share f of each league's matches, rebuilt from the cached match files with only the matches before the cut
(soccer_proj_research.snapshot's method, plus SV and the box totals at the cut).
    python3 scripts/research/soccer_fotmob_nov26/snaps.py     -> scripts/.cache/soccer/fm_snaps_<S>.json.gz (gitignored)"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import soccer_data as D, soccer_players as SP, soccer_sv as SV  # noqa: E402

OUT = os.path.join(D.CACHE, 'fm_snaps.json.gz')
FS = [0.25, 0.5, 0.75]


def snapshot(S, f, F, FS_, LS, prev):
    rows, fl, cut = [], {}, {}
    keep = D.BIG5
    for lg in keep:
        d = D.us_league(lg, S)
        if not d:
            continue
        ms = sorted((m for m in d['matches'] if m['res']), key=lambda m: m['t'] or '')
        k = int(round(f * len(d['matches'])))
        if k >= len(ms):
            continue
        cut[lg] = ms[k]['t']; fl[lg] = k / len(d['matches'])
        D.BIG5 = [lg]
        try:
            rows += SP.build_rows(S, S, before=cut[lg])
        finally:
            D.BIG5 = keep
    segs = {s_: SP.segments(s_) for s_ in (S - 2, S - 1)}
    segs[S] = []
    for lg in cut:
        D.BIG5 = [lg]
        try:
            segs[S] += SP.segments(S, before=cut[lg])
        finally:
            D.BIG5 = keep
    SP.rapm([r for r in prev if r['S'] in (S - 1, S - 2)] + rows, [S], segs)
    SV.season_rapm(rows, segs, [S], FS_['rapmLam'])
    SP.prep(rows, F['shrink'])
    sv = {(r['p'], r['tid']): r for r in SV.sv_rows(rows, FS_['shrink'], FS_)}
    out = []
    for r in rows:
        if r['min'] < 1:
            continue
        v = SP.value(r, F) + (F.get('lgScale') or {}).get('k', 0.0) * SP.lg_of(LS, r['lg'], S - 1)
        q = sv[(r['p'], r['tid'])]
        s = SV.value(q, FS_) + FS_['lgScale']['k'] * SP.lg_of(LS, r['lg'], S - 1) - FS_['repl'][r['pos']]
        out.append({'p': r['p'], 'n': r['n'], 'team': r['team'], 'lg': r['lg'], 'pos': r['pos'], 'min': r['min'], 'mp': r['mp'],
                    'gar90': round(v - F['repl'][r['pos']], 4), 'sv': round(s, 4),
                    'g': r['g'], 'a': r['as'], 'xg': round(r['x'], 3), 'xa': round(r['xA'], 3), 'sh': r['sh'], 'kp': r['kp']})
    return out, fl


if __name__ == '__main__':
    D._us_down[0] = True
    F = json.load(open(SP.FIT)); FS_ = json.load(open(SV.FIT)); LS = SP.league_strength()
    prev = D.load(SP.ROWS)
    for S in [int(a) for a in sys.argv[1:]] or range(2018, 2027):       # one file a season (seasons can run side by side)
        o = OUT.replace('.json.gz', f'_{S}.json.gz')
        if os.path.exists(o):
            continue
        res = {}
        for f in FS:
            pl, fl = snapshot(S, f, F, FS_, LS, prev)
            res[str(f)] = {'p': pl, 'f': fl}
            print(S, f, len(pl), fl, flush=True)
        D.save(o, res)
