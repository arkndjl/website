# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 6c (PREREG.md): two-way to standard conversion odds.

    python3 gl_twoway_test.py TWOWAY.json GL_DIR     # -> impl/nba/gl_twoway.json

Rows: players signed to a two-way contract before Jan 15 of season Y and not converted or waived by then; label =
converted from Jan 15 to the season's end. Baseline: age + signing month; candidate adds G League games, minutes a
game and Game Score per 36 through Jan 14. Leave one season out; tune 2018-21, held 2022-25."""
import datetime as dt, json, os, sys
import numpy as np
import common as C
import gleague_callup as GC
import gl_hazard_test as HZ


def main():
    tx = json.load(open(sys.argv[1]))
    rows = []
    for y in range(2018, 2026):
        cut = dt.date(y, 1, 15)
        ev = {}
        for s, d, kind, pid, nm in tx:
            if s == y: ev.setdefault(pid, []).append((dt.date.fromisoformat(d), kind, nm))
        L = HZ.logs(sys.argv[2], y)
        gl = GC.gl_season(y)
        find = C.matcher([(p, v[0][4]) for p, v in L.items()])
        for pid, e in ev.items():
            e.sort()
            sg = [x for x in e if x[1] == 'sign' and x[0] < cut]
            if not sg: continue
            s0 = sg[-1][0]
            if any(x[1] in ('convert', 'waive') and s0 <= x[0] < cut for x in e): continue
            lab = 1.0 if any(x[1] == 'convert' and x[0] >= cut for x in e) else 0.0
            gp = find(e[0][2])
            past = [g for g in L.get(gp, []) if g[0] < cut] if gp else []
            mn = sum(g[1] for g in past)
            age = (gl.get(gp) or {}).get('age') or 23.0
            base = [age, (s0 - dt.date(y - 1, 7, 1)).days / 30.0]
            new = [len(past), mn / len(past) if past else 0.0, 36 * sum(g[2] for g in past) / mn if mn > 0 else 0.0, 0.0 if past else 1.0]
            rows.append((y, base, new, lab))
    S = np.array([r[0] for r in rows]); Y = np.array([r[3] for r in rows])
    XB = np.array([r[1] for r in rows]); XN = np.array([r[1] + r[2] for r in rows])
    print('rows', len(rows), 'converted', int(Y.sum()), {int(s): (int((S == s).sum()), int(Y[S == s].sum())) for s in sorted(set(S))}, flush=True)
    ll = {}
    for nm, X in (('base', XB), ('new', XN)):
        l = np.zeros(len(Y))
        for s in sorted(set(S)):
            tr, te = S != s, S == s
            mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
            b = GC.logit_fit((X[tr] - mu) / sd, Y[tr])
            p = np.clip(GC.sig(GC.lin(b, (X[te] - mu) / sd)), 1e-4, 1 - 1e-4)
            l[te] = -(Y[te] * np.log(p) + (1 - Y[te]) * np.log(1 - p))
        ll[nm] = l
    d = ll['new'] - ll['base']
    res = {'n': len(rows), 'converted': int(Y.sum())}
    for nm, k in (('tune', S <= 2021), ('held', S >= 2022)):
        p = C.paired(d[k], S[k]); ss = sorted(set(S[k]))
        res[nm] = {'n': int(k.sum()), 'll0': round(float(ll['base'][k].mean()), 5), 'll1': round(float(ll['new'][k].mean()), 5), 'd': round(p['d'], 5), 't': round(p['t'], 2),
                   'seasonsLower': int(sum(d[S == s].mean() < 0 for s in ss)), 'seasons': len(ss)}
    res['p'] = C.p2(res['held']['t']) if res['held']['t'] < 0 else 1.0
    res['pass_pre_holm'] = bool(res['held']['t'] <= -2 and res['tune']['d'] < 0 and res['held']['seasonsLower'] * 2 > res['held']['seasons'])
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(C.IMPL, 'gl_twoway.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
