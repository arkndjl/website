#!/usr/bin/env python3
"""Awards voter models (scripts/awards_cbb.py): BPM -> rXPM, D-BPM -> D-rXPM in every CBB race's cols and null.
Protocol = scripts/awards_research.py: leave one season out, log P(actual winner), l2 1, depth 1. Paired t over seasons of the
swapped model against the current one. -> awards.json"""
import json, os, sys
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import awards_cbb as A, awards_engine as E
base = A.seasons_data()['wooden']
for s, pool, _ in base:
    for r in pool:
        r['xpm'] = C.get(r['id'], s, 'xpm', r['bpm']); r['dxpm'] = C.get(r['id'], s, 'dxpm', r['dbpm'])
R = dict(A.more_races(base)); R['wooden'] = base
specs = dict({k: (v[1], v[2]) for k, v in A.MORE.items()}, wooden=(A.WOODEN_COLS, ['bpm']))
sw = lambda cs: [{'bpm': 'xpm', 'dbpm': 'dxpm'}.get(c, c) for c in cs]
out = {}
for aw, (cols, null) in specs.items():
    races = R[aw]; S = [s for s, _, _ in races]
    rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
    a, b = E.loso(rr(cols), S, l2=1.0, depth=1), E.loso(rr(sw(cols)), S, l2=1.0, depth=1)
    n0, n1 = E.loso(rr(null), S, l2=1.0, depth=1), E.loso(rr(sw(null)), S, l2=1.0, depth=1)
    pr, pn = E.paired(b, a), E.paired(n1, n0)
    out[aw] = {'n': pr['n'], 'll': [round(sum(x['ll'] for x in a) / len(a), 4), round(sum(x['ll'] for x in b) / len(b), 4)], 't': pr['t'], 'wins': pr['wins'],
               'hit': [sum(x['hit'] for x in a), sum(x['hit'] for x in b)],
               'null_ll': [round(sum(x['ll'] for x in n0) / len(n0), 4), round(sum(x['ll'] for x in n1) / len(n1), 4)], 'null_t': pn['t'], 'null_wins': pn['wins'], 'null_hit': [sum(x['hit'] for x in n0), sum(x['hit'] for x in n1)]}
    print(aw, out[aw], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'awards.json'), 'w'), indent=1)
