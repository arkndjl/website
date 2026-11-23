"""F1 (prereg.md): new drivers for the NFL predictive mock's xPick (BOARD_PICK in scripts/cfb_teams.mjs), leave one
draft out on DraftTek final boards 2020-25 and PFF winter boards. Run after scripts/draft_backtest.py and
scripts/cfb_draft_pct_backtest.py (their caches) and fetch_wiki.py.

    python3 scripts/research/mocks_nov23/nfl_pred.py   -> scripts/research/mocks_nov23/nfl_pred.json"""
import collections, json, math, os
import numpy as np
from common import ROOT, OUT, paired, holm, ridge
import names as N
import nfl_data as ND

UND = 290.0


def final_rows():
    B = json.load(open(os.path.join(ND.DR, 'boards.json')))
    base = {(r['year'], r['rank']): r for r in json.load(open(os.path.join(ND.DR, 'rows.json')))}
    cmb = ND.combine(); vers = ND.pff_versions()
    out = []
    for y in range(2020, 2026):
        dd = ND.DRAFT_DAY[y]
        fin = ND.pick_board(vers, y, f'{y}-03-01', dd)
        win = ND.pick_board(vers, y, f'{y - 1}-12-10', f'{y}-02-28')
        mf, mw = ND.pff_matcher(fin[1]), ND.pff_matcher(win[1]) if win else None
        depth_f = len(fin[1])
        cm = N.Matcher(cmb[y], name='name', team='school', pos=None)
        for b in [b for b in B if b['year'] == y]:
            r = base.get((y, b['rank']))
            if not r or r['rank'] > 200 or r['g'] == 'K': continue
            nm = N.clean(b['name']) if hasattr(N, 'clean') else b['name']
            nm = nm.split('(')[0].strip()
            pf, _ = mf.find(nm, b['school'])
            pw, _ = mw.find(nm, b['school']) if mw else (None, None)
            c, _ = cm.find(nm, b['school'])
            a = ND.award_feats(nm, b['school'], y - 1)
            rk_f = pf['p']['pff_rank'] if pf else None
            rk_w = pw['p']['pff_rank'] if pw else None
            age = ND.age_at_draft((pf or pw or {'p': {}})['p'], y) if (pf or pw) else None
            g1 = ((pf or pw or {'p': {}})['p'].get('grade_1') or {}).get('value') if (pf or pw) else None
            out.append(dict(year=y, rank=r['rank'], name=nm, g=r['g'], pick=r['pick'], combine=r['combine'], forty_raw=r['forty'],
                            y=math.log(min(r['pick'], UND) if r['pick'] else UND),
                            heis=a['heis'], aa=a['aa'], award=a['award'], age=age, ath=c['ath'] if c else None, notest=c['notest'] if c else 0.0,
                            conf=ND.sec_b10(b['school'], y - 1),
                            disp=abs(math.log(r['rank']) - math.log(rk_f if rk_f else 1.5 * depth_f)),
                            move=(math.log(rk_w if rk_w else 300) - math.log(rk_f if rk_f else 300)) if win else 0.0,
                            grade=g1 if g1 else None))
    return out


def winter_rows():
    vers = ND.pff_versions(); P = ND.picks(); B = json.load(open(os.path.join(ND.DR, 'boards.json')))
    out = []
    for y in range(2020, 2027):
        win = ND.pick_board(vers, y, f'{y - 1}-12-10', f'{y}-02-28')
        if not win: continue
        fall = ND.pick_board(vers, y, f'{y - 1}-09-01', f'{y - 1}-11-30')
        mfa = ND.pff_matcher(fall[1]) if fall else None
        pm = N.Matcher(P[y], name='pfr_player_name', team='college', pos=None)
        dm = N.Matcher([b for b in B if b['year'] == y], name='name', team='school', pos=None) if any(b['year'] == y for b in B) else None
        for p in win[1]:
            rk = p.get('pff_rank')
            if not rk or rk > 200: continue
            g = ND.NGRP.get(p.get('position'), 'X')
            if g == 'K': continue
            nm = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            sch = p.get('college')
            pk, _ = pm.find(nm, sch)
            onb = dm.find(nm, sch)[0] if dm else None
            if pk is None and onb is None: continue      # did not declare (no final board row, not drafted)
            a = ND.award_feats(nm, sch, y - 1)
            pf = mfa.find(nm, sch)[0] if mfa else None
            g1 = (p.get('grade_1') or {}).get('value')
            out.append(dict(year=y, rank=rk, name=nm, g=g, pick=int(pk['pick']) if pk else None,
                            y=math.log(min(int(pk['pick']), UND) if pk else UND), heis=a['heis'], aa=a['aa'], award=a['award'],
                            age=ND.age_at_draft(p, y), conf=ND.sec_b10(sch, y - 1),
                            move=(math.log(pf['p']['pff_rank'] if pf and pf['p'].get('pff_rank') else 300) - math.log(rk)) if fall else 0.0,
                            grade=g1 if g1 else None))
    return out


def zgroup(rows, k):
    """z within position group, missing -> 0"""
    by = collections.defaultdict(list)
    for r in rows:
        if r.get(k) is not None: by[r['g']].append(r[k])
    st = {g: (np.mean(v), np.std(v) or 1) for g, v in by.items()}
    for r in rows: r[k + '_z'] = (r[k] - st[r['g']][0]) / st[r['g']][1] if r.get(k) is not None and r['g'] in st else 0.0


def feats(r, base, extra):
    lr = math.log(r['rank']); f = [1, lr, lr * lr]
    if base == 'final':
        f += [0.0 if r['combine'] else 1.0, r['forty_z']]
    for k in extra:
        v = r.get(k)
        f.append(v if v is not None else 0.0)
    return f


def lodo(rows, base, extra):
    yrs = sorted({r['year'] for r in rows}); loss = np.zeros(len(rows)); pred = np.zeros(len(rows))
    for t in yrs:
        tr = [r for r in rows if r['year'] != t]; te = [i for i, r in enumerate(rows) if r['year'] == t]
        b = ridge(np.array([feats(r, base, extra) for r in tr]), np.array([r['y'] for r in tr]))
        for i in te:
            p = float(np.dot(feats(rows[i], base, extra), b)); pred[i] = p
            loss[i] = (min(p, math.log(UND)) - rows[i]['y']) ** 2
    return loss, pred


def mae(rows, pred, top):
    e = [abs(min(math.exp(p), UND) - math.exp(r['y'])) for r, p in zip(rows, pred) if r['rank'] <= top]
    return round(float(np.mean(e)), 2)


def main():
    F = final_rows(); W = winter_rows()
    # 40 z on the live definition (within group, invitees with a 40)
    fz = collections.defaultdict(list)
    for r in F:
        if r['forty_raw']: fz[r['g']].append(r['forty_raw'])
    st = {g: (np.mean(v), np.std(v)) for g, v in fz.items()}
    for r in F: r['forty_z'] = (r['forty_raw'] - st[r['g']][0]) / st[r['g']][1] if r['forty_raw'] and r['g'] in st else 0.0
    for R in (F, W):
        zgroup(R, 'grade')
        ages = [r['age'] for r in R if r['age'] is not None]; m = float(np.mean(ages))
        for r in R: r['age_c'] = (r['age'] - m) if r['age'] is not None else 0.0
    cover = {'final': {'n': len(F), 'age': sum(r['age'] is not None for r in F), 'heis': sum(r['heis'] for r in F), 'aa': sum(r['aa'] for r in F),
                       'award': sum(r['award'] for r in F), 'ath': sum(r['ath'] is not None for r in F), 'notest': sum(r['notest'] for r in F),
                       'grade': sum(r['grade'] is not None for r in F), 'conf': sum(r['conf'] for r in F)},
             'winter': {'n': len(W), 'years': sorted({r['year'] for r in W}), 'age': sum(r['age'] is not None for r in W),
                        'heis': sum(r['heis'] for r in W), 'aa': sum(r['aa'] for r in W), 'award': sum(r['award'] for r in W)}}
    tests = []
    for uni, R, drivers in (('final', F, ['heis', 'aa', 'award', 'age_c', 'ath', 'notest', 'conf', 'disp', 'move', 'grade_z']),
                            ('winter', W, ['heis', 'aa', 'award', 'age_c', 'conf', 'move', 'grade_z'])):
        l0, p0 = lodo(R, uni, [])
        for d in drivers:
            l1, p1 = lodo(R, uni, [d])
            b = ridge(np.array([feats(r, uni, [d]) for r in R]), np.array([r['y'] for r in R]))
            res = paired(l0, l1, [r['year'] for r in R])
            res.update({'model': 'F1', 'universe': uni, 'driver': d, 'coef': round(float(b[-1]), 4), 'n': len(R),
                        'lnErr2': [round(float(l0.mean()), 4), round(float(l1.mean()), 4)],
                        'mae100': [mae(R, p0, 100), mae(R, p1, 100)], 'mae32': [mae(R, p0, 32), mae(R, p1, 32)]})
            tests.append(res)
    holm(tests)
    out = {'_readme': 'prereg.md F1: NFL predictive xPick drivers, leave one draft out; loss = squared ln pick error (undrafted 290); '
                      'gain = base - base+driver; coef = full-sample ln-pick units per unit of the driver.', 'coverage': cover, 'tests': tests}
    json.dump(out, open(os.path.join(OUT, 'nfl_pred.json'), 'w'), indent=1)
    print(json.dumps(cover))
    for t in tests:
        print(f"{t['universe']:6} {t['driver']:8} coef {t['coef']:+.3f} gain {t['gain']:+.5f} t {t['t']:+.2f} p {t['p']:.4f} won {t['won']}/{t['of']} "
              f"mae100 {t['mae100']} mae32 {t['mae32']} pass {t['pass']}")


if __name__ == '__main__':
    main()
