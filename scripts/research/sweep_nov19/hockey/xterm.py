# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""xTerm (expected contract length) test and the AFP Analytics head-to-head on 2026 signings (pre-registered H7a, H7c).

usage: xterm.py <capwages signings dir (s_<season>.html)> <afp pages dir> <out.json>
"""
import json, os, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import xaav as X          # noqa: E402
import xaav_lib as L      # noqa: E402
import names as NM        # noqa: E402


def signings(d, cache):
    out = []
    for f in sorted(os.listdir(d)):
        if f.startswith('s_'):
            out += X.next_data(open(os.path.join(d, f), encoding='utf8').read())['signings']
    os.makedirs(cache, exist_ok=True)
    json.dump(out, open(os.path.join(cache, 'nhl_signings.json'), 'w'))


def afp_rows(d):
    out, dec = {}, json.JSONDecoder()
    for f in sorted(os.listdir(d)):
        if not re.match(r'p\d+\.html', f):
            continue
        t = open(os.path.join(d, f), encoding='utf8', errors='replace').read()
        for m in re.finditer(r'(?<=[\[,])\{"', t):
            if '"projectedCh"' not in t[m.start():m.start() + 6000]:
                continue
            try:
                o, _ = dec.raw_decode(t, m.start())
            except ValueError:
                continue
            if isinstance(o, dict) and o.get('player') and o.get('projectedCh') and o.get('timeframe') == 'Offseason 2026':
                out[o['_id']] = o
    return list(out.values())


def pct(s):
    try:
        return float(str(s).replace('%', '')) / 100
    except ValueError:
        return None


def main(cw, afp, outp):
    X.CACHE = os.path.join(os.path.dirname(outp), 'xaav_cache')
    signings(cw, X.CACHE)
    rows = X.nhl_rows()
    forms = X.nhl_forms()
    live = json.load(open(os.path.join(ROOT, 'data', 'xaav_fit.json')))['nhl']['live']
    res = {'rows': len(rows), 'liveForm': live['form']}
    # H7a: length on the live form's inputs, linear target, clipped 1-8; baseline position x age-bin mean
    lr = [dict(r, t=float(r['len'])) for r in rows]
    pa = L.loyo(lr, forms[live['form']], 1.0, 8.0, log=False)
    pb = L.loyo(lr, forms['base'], 1.0, 8.0, log=False)
    res['xterm_loyo'] = L.compare(lr, pa, pb)
    fa = L.forward(lr, forms[live['form']], 2016, 1.0, 8.0, log=False)
    fb = L.forward(lr, forms['base'], 2016, 1.0, 8.0, log=False)
    res['xterm_forward'] = L.compare(lr, fa, fb, sorted(fa))
    # with the AAV form's own price as one more input (reported, not part of the gate)
    # H7c: AFP vs our forward xAAV on 2026 signings (fit on league years before 2026 only)
    log = live['log']
    fx = L.forward(rows, forms[live['form']], 2026, lambda r: X.NHL_MIN[r['y']] / X.NHL_CAP[r['y']], X.NHL_MAX, log=log)
    A = afp_rows(afp)
    by = {}
    for o in A:
        n = o['player'].split(', ', 1)
        by.setdefault(NM.key(f'{n[1]} {n[0]}' if len(n) == 2 else o['player']), []).append(o)
    ours, theirs, act, stat = [], [], [], []
    for i, p in fx.items():
        r = rows[i]
        c = [o for o in by.get(NM.key(r['n']), []) if pct(o.get('actualCapHit1')) is not None]
        if len(c) != 1:
            continue
        o = c[0]
        a = pct(o['actualCapHit1'])
        if abs(a - r['t']) > 0.002:          # the same contract on both sides
            continue
        ours.append(p); theirs.append(pct(o['projectedCh'])); act.append(r['t']); stat.append(o.get('faStatus'))
    ours, theirs, act = map(np.array, (ours, theirs, act))
    d = np.abs(ours - act) - np.abs(theirs - act)
    res['afp'] = {'afpRows': len(A), 'afpSigned': sum(1 for o in A if pct(o.get('actualCapHit1')) is not None),
                  'projectionDates': sorted({str(o.get('projectionDate'))[:10] for o in A}),
                  'n': len(d), 'maeOurs': round(float(np.abs(ours - act).mean() * 100), 3) if len(d) else None,
                  'maeAfp': round(float(np.abs(theirs - act).mean() * 100), 3) if len(d) else None,
                  't': round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2) if len(d) > 2 else None,
                  'byStatus': {s: {'n': int(sum(1 for x in stat if x == s)),
                                   'maeOurs': round(float(np.abs(ours - act)[[x == s for x in stat]].mean() * 100), 3),
                                   'maeAfp': round(float(np.abs(theirs - act)[[x == s for x in stat]].mean() * 100), 3)}
                               for s in sorted({x for x in stat if x})}}
    json.dump(res, open(outp, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:4])
