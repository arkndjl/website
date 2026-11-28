# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""FV against OVR (Nov 28 2026): does a rookie's draft-year FV line up with the OVR he reaches as a pro, and does an OVR
target say anything the FV outcome ladder does not? NBA only: the one league with FV on file for past rookies
(static/data/rookies/nba.json pfv, the draft-year CBB board) and OVR for past seasons (pXPM by season).
  outcome  OVR at the end of his third NBA season (pXPM -> OVR on today's points); out of the league = below every OVR
  tests    Spearman r of FV with the outcome; mean outcome by FV band; FV vs the pre-draft rank (preL) on the same rows
python3 scripts/research/ovr_nov28/fv_anchor.py -> research/ovr_research.json 'fvAnchor'"""
import json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import ovr as O
import names as NM
from engine import paired_t

RES = os.path.join(ROOT, 'research', 'ovr_research.json')
K = json.load(open(os.path.join(ROOT, 'data', 'ovr_fit.json')))['anchors']['nba']


def ranks(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]: j += 1
        for k in range(i, j + 1): r[o[k]] = (i + j) / 2
        i = j + 1
    return r


def spear(a, b):
    ra, rb = ranks(a), ranks(b); ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)); den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** .5
    return num / den if den else 0.0


def main():
    F = O.nba_files()
    seas = {s: {NM.key(p['n']): p for p in json.load(open(f))['players'] if p.get('xpm') is not None and not p.get('pr')} for s, f in F.items()}
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'rookies', 'nba.json')))
    rows = []
    for c in d['seasons']:
        s = c['s']
        if s + 2 not in seas or s + 2 >= max(F): continue
        for r in c['rows']:
            if r.get('pfv') is None: continue
            p = seas[s + 2].get(NM.key(r['n']))
            ovr = O.grade(p.get('sxpm'), K) if p and p.get('sxpm') is not None and p['mp'] >= 250 else None
            pre = r.get('preL'); pre = int(pre[1:]) if pre and pre.startswith('#') and pre[1:].isdigit() else None
            rows.append({'s': s, 'n': r['n'], 'fv': r['pfv'], 'ovr': ovr, 'pre': pre})
    out_v = [r['ovr'] if r['ovr'] is not None else 0.0 for r in rows]
    res = {'n': len(rows), 'classes': [min(r['s'] for r in rows), max(r['s'] for r in rows)],
           'inLeague': round(sum(1 for r in rows if r['ovr'] is not None) / len(rows), 3),
           'spearFV': round(spear([r['fv'] for r in rows], out_v), 3)}
    both = [r for r in rows if r['pre'] is not None]
    bv = [r['ovr'] if r['ovr'] is not None else 0.0 for r in both]
    res['withPre'] = len(both); res['spearFVpre'] = round(spear([r['fv'] for r in both], bv), 3); res['spearPre'] = round(spear([-r['pre'] for r in both], bv), 3)
    # per class, FV against pre-draft rank (paired t over classes)
    a, b = [], []
    for s in sorted({r['s'] for r in both}):
        cr = [r for r in both if r['s'] == s]
        if len(cr) < 15: continue
        v = [r['ovr'] if r['ovr'] is not None else 0.0 for r in cr]
        a.append(spear([r['fv'] for r in cr], v)); b.append(spear([-r['pre'] for r in cr], v))
    res['fvVsPre'] = {'t': paired_t(a, b), 'wins': sum(1 for x, y in zip(a, b) if x > y), 'of': len(a)}
    bands = {}
    for r in rows:
        k = min(70, max(30, int(r['fv'] // 5 * 5)))
        bands.setdefault(k, []).append(r['ovr'])
    res['bands'] = {str(k): {'n': len(v), 'inLeague': round(sum(1 for x in v if x is not None) / len(v), 2),
                             'ovr': round(st.mean([x for x in v if x is not None]), 1) if any(x is not None for x in v) else None,
                             'starter': round(sum(1 for x in v if x is not None and x >= 75) / len(v), 2)} for k, v in sorted(bands.items())}
    return res


if __name__ == '__main__':
    R = json.load(open(RES)); R['fvAnchor'] = main(); print(json.dumps(R['fvAnchor'], indent=1))
    json.dump(R, open(RES, 'w'), indent=1)
