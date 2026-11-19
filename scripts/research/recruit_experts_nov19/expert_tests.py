# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-registered tests (prereg.md): On3/Rivals expert picks weighted by each expert's prior-class track record,
on top of the live CFB LIST model, walk-forward by class.
  python3 scripts/research/recruit_experts_nov19/expert_tests.py [--k 10]"""
import json, math, os, sys
from collections import defaultdict
from datetime import date, timedelta
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'recruit_visits_nov17'))
import recruit_commit_fit as C  # noqa: E402
import recruit_on3_join as J  # noqa: E402
import names  # noqa: E402
import visit_tests as V  # noqa: E402

SP = 'cfb'
BASE = C.data_cols(SP) if hasattr(C, 'data_cols') else ['pull', 'tier', 'gxt', 'gap', 'ld', 'inst'] + C.EXTRA['cfb']['list']
DEC = .75
C.COLS = C.COLS + ['esha']
_feats = C.feats
REL = {}   # class -> {expert: weight multiplier r/p0}


def picks_asof(r, cutoff, smap):
    """[(expert, espn id or None, confidence/100)] as of cutoff, the rule of recruit_on3_join.asof"""
    out = []
    for d, org, ex, conf, frm, pd, pconf in r.get('picks') or []:
        if d and d < cutoff: s, c = org, conf
        elif pd and pd < cutoff: s, c = (frm or org), pconf
        else: continue
        if not s: continue
        out.append((ex, smap[s] if s in smap else None, (c if c else 50) / 100))
    return out


def attach_picks(cls, H=30):
    smap = J.slug_map(SP)
    for y, rows in cls.items():
        on3 = J.read(SP, y)
        by = defaultdict(list)
        for r in on3: by[names.key(r['name'] or '')].append(r)
        for x in rows:
            x['yr'] = y
            if not x.get('ex') or x['chose'] is None: continue   # live uncommitted rows are not used here
            cand = [r for r in by.get(names.key(x['name'] or ''), []) if not x['st'] or not r.get('state') or r['state'] == x['st']]
            if len(cand) != 1: continue
            cd = J.commit_date(cand[0])
            if not cd: continue
            x['pk'] = picks_asof(cand[0], (date.fromisoformat(cd) - timedelta(days=H)).isoformat(), smap)


def records(cls, y, k, upto=None):
    """expert -> (hits, picks), p0, from recruits of classes in [lo, y)"""
    h, n = defaultdict(int), defaultdict(int)
    for c, rows in cls.items():
        if c >= y or (upto and c < upto[0]): continue
        for x in rows:
            for ex, t, _ in x.get('pk') or []:
                n[ex] += 1; h[ex] += int(t == x['chose'])
    N = sum(n.values()); p0 = sum(h.values()) / N if N else None
    return h, n, p0


def rel_table(cls, k):
    out = {}
    for y in cls:
        h, n, p0 = records(cls, y, k)
        out[y] = {e: ((h[e] + k * p0) / (n[e] + k)) / p0 for e in n} if p0 else {}
    return out


def feats(x, alts, st, loc):
    F = _feats(x, alts, st, loc)
    pk = x.get('pk') or []; rel = REL.get(x.get('yr'), {})
    w = defaultdict(float); tot = 0.0
    for ex, t, c in pk:
        v = c * rel.get(ex, 1.0); tot += v
        if t is not None: w[t] += v
    col = np.array([[w[t] / tot if tot else 0.0] for t in alts])
    return np.hstack([F, col])


C.feats = feats


def main():
    k = int(sys.argv[sys.argv.index('--k') + 1]) if '--k' in sys.argv else 10
    loc, cls = C.load(SP)
    cov = J.attach(SP, cls, 30)   # training rows: as of commitment - 30 days (load() set live cutoffs for 2027-29)
    attach_picks(cls)
    REL.clear(); REL.update(rel_table(cls, k))
    out_f = os.path.join(HERE, 'expert_tests.json')
    out = json.load(open(out_f)) if os.path.exists(out_f) else {}
    # track records: who the experts are, and whether reliability is stable (split half)
    h, n, p0 = records(cls, 2027, k)
    h1, n1, p1 = records(cls, 2025, k); h2, n2, p2 = records(cls, 2027, k, upto=(2025,))
    both = [e for e in n1 if n1[e] >= 10 and n2.get(e, 0) >= 10]
    a = np.array([h1[e] / n1[e] for e in both]); b = np.array([h2[e] / n2[e] for e in both])
    # between-expert spread beyond binomial noise: var(observed) - mean(p(1-p)/n)
    big = [e for e in n if n[e] >= 20]; rr = np.array([h[e] / n[e] for e in big])
    noise = float(np.mean([p0 * (1 - p0) / n[e] for e in big])) if big else None
    stab = {'p0': p0, 'experts': len(n), 'picks': sum(n.values()), 'with20': len(big),
            'sdObserved': float(rr.std(ddof=1)) if len(big) > 1 else None, 'sdNoise': math.sqrt(noise) if noise else None,
            'splitHalf': {'n': len(both), 'r': float(np.corrcoef(a, b)[0, 1]) if len(both) > 2 else None},
            'top': sorted([[e, n[e], round(h[e] / n[e], 3)] for e in big], key=lambda z: -z[2])}
    print('records', {kk: v for kk, v in stab.items() if kk != 'top'}, flush=True)
    specs = {'base': (BASE, DEC), 'A swap': ([c if c != 'esh' else 'esha' for c in BASE], DEC), 'B add': (BASE + ['esha'], DEC)}
    r = V.walk(SP, loc, cls, specs)
    pc = {y: sum(1 for x in cls[y] if x.get('pk')) for y in C.HELD[SP]}
    rec_ok = [y for y in C.HELD[SP] if pc[y] >= 20 and records(cls, y, k)[2] is not None]
    sub = np.isin(r['base']['yr'], rec_ok)
    o = {'k': k, 'pickRecruits': pc, 'gateClasses': rec_ok, 'records': stab, 'base': V.summ(r['base']), 'baseCalib': V.calib(r['base'])}
    for t in ('A swap', 'B add'):
        g = V.gate(r['base'], r[t]); g['gateOn'] = V.gate(r['base'], r[t], sub); g['p'] = V.p_one(g['gateOn']['t'])
        g['with'] = V.summ(r[t]); g['calib'] = V.calib(r[t]); g['coefLast'] = r[t]['coef'][-1]; o[t] = g
    hp = V.holm({t: o[t]['p'] for t in ('A swap', 'B add')})
    for t in ('A swap', 'B add'):
        gg = o[t]['gateOn']; o[t]['holm'] = hp[t]; o[t]['pass'] = bool(hp[t] and gg['gain'] > 0 and gg['classesPos'] >= 2 / 3)
        print(t, 'gain', round(o[t]['gain'], 5), 't', round(o[t]['t'], 2), 'gateOn', round(gg['gain'], 5), round(gg['t'], 2), gg['classesPos'],
              gg['byClass'], 'pass', o[t]['pass'], 'top1', round(o[t]['with']['top1'], 4), 'vs', round(o['base']['top1'], 4), o[t]['coefLast'], flush=True)
    out[f'k{k}'] = o
    json.dump(out, open(out_f, 'w'), indent=1, default=float)


if __name__ == '__main__':
    main()
