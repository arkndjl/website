#!/usr/bin/env python3
"""Draft-day grades for the all-time CBB list (Noah, Nov 3 2026: "our all-time FV board for CBB has some bad misses").

The all-time list used to show each player at his best PRESEASON grade (static/data/cbb-past.json). A preseason board
never sees the season that follows, so a one-and-done was graded only as a recruit and a breakout sophomore only on
his freshman line (Gilgeous-Alexander 28, Mitchell 28, Booker 31, Tatum 35 E[FV] against 74-80 careers), and the best
of several noisy grades ran hot (each position's all-time top 25 graded 46-50, became 40-50).

This grades every player once, the way the live board grades him in draft week: his career with the season just
played (cbb_live's season-end "now": the board's returner model on next preseason's row), then the June draft boards
(the board stage's inputs: -ln consensus rank of ESPN's and NBADraft.net's final boards, and whether either lists him),
then the mean outcome at that score. A player still in college shows at the end of his latest season. It also writes
the live board's season-end map (end_map -> data/cbb_end_map.json, read by cbb_live).

    python3 scripts/cbb_careers_kit.py   # once per container: scripts/.cache/cbb/careers.json
    python3 scripts/cbb_draftday.py      # -> scripts/data/cbb_draftday.json.gz, data/cbb_end_map.json; then fv_alltime.py
    python3 scripts/cbb_draftday.py --intl   # first re-grade the internationals (needs scripts/cbb_intl_pull.sh's cache)

Out of sample (Nov 3 2026), players whose college ended 2009-16 (6+ NBA seasons), every grade from fits that held out
the player's college class (5 class folds), players graded 30+ or reaching 30+ by either list (681):
  best preseason grade (old list)         MSE 212.0   rank corr .12   stars (60+) graded under 40: 19 of 33
  draft-day, model only                   MSE 165.8   t -6.6, 5/5 folds
  + combine invite/testing                MSE 152.2   t -5.7 on the model, 5/5
  + June boards, stage refit on these     MSE 130.3   t -9.9 on the old list, 5/5; stars under 40: 7 of 33
  + June boards, the live board's stage   final seasons graded 30+ or reaching it (550): MSE 150.9 -> 143.8 against
    (shipped, Nov 3)                      the refit stage (t -5.7, 5/5)
Tested and not used: athletic testing on top of the boards (guard composite t -0.1, 2/5; every group's composite worse;
the boards price it), the combine invite on top of the boards (t +2.9, worse 5/5), the returner model refit on
season-end rows with leavers (MSE +1.4, t 0.9: the shipped model is kept), position recalibration.
Held-out residual audit, Nov 4 2026 (/mnt/project-files/fv/sweep-nov04/cbb/; finals 2009-16 class folds, forward 2017-20,
Holm k 3, none passed): June-rank disagreement term on the map (t -1.1, 4/5, forward and forward top 25 worse), age at
draft x grade (t +1.2, 3/5; forward better t -3.1: retest when the 2021-22 exits have six NBA seasons), a row-level
line for the map's top quarter in place of the last PAV bin and its slope (t +0.4, 1/5).
"""
import gzip, html, json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
import names as N
import fv_scale as FS

OUT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_draftday.json.gz')
END = os.path.join(D.ROOT, 'data', 'cbb_end_map.json')   # the live board's season-end map (cbb_live)
INTL = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_intl_draftday.json.gz')   # internationals at their draft (--intl)
NEXT = {'Fr': 'So', 'So': 'Jr', 'Jr': 'Sr', 'Sr': 'Sr'}
TRAIN = range(2009, 2017)   # season-end boards whose players all left college by 2020 (as cbb_fit's training boards)
LAST = 2026                 # the latest season played
PER_SEASON = 300            # rows kept per season (by grade), as the past boards


def exit_features(c, i):
    """the season-end board for career c's i-th season: next preseason's row, read the day the season ends"""
    s = c['seasons'][i]
    nxt = {'year': s['year'] + 1, 'team': s['team'], 'conf': s['conf'], 'yr': NEXT.get(s['yr'], 'Sr'), 'hti': s['hti'], 'rec': None, 'role': s['role']}
    return F.features(dict(c, seasons=c['seasons'][:i + 1] + [nxt]), i + 1)


def calmap(e, y):
    """the mean outcome at each score: quantile bins (finer at the top), PAV, the top quarter's slope past the last knot"""
    qs = np.unique(np.quantile(e, np.r_[np.linspace(0, .9, 10), 1 - np.geomspace(.1, 1.5e-3, 50)]))
    b = np.clip(np.searchsorted(qs, e, side='right') - 1, 0, len(qs) - 1)
    kx, ky, kw = [], [], []
    for j in np.unique(b):
        m = b == j; kx.append(float(e[m].mean())); ky.append(float(y[m].mean())); kw.append(float(m.sum()))
    o = np.argsort(kx)
    kx, ky = F.pav(np.array(kx)[o], np.array(ky)[o], np.array(kw)[o])
    n = max(2, len(kx) // 4)
    return kx, ky, max(0.0, float(np.polyfit(kx[-n:], ky[-n:], 1)[0]))


def apply_map(M, e):
    kx, ky, sl = M
    return np.clip(np.interp(e, kx, ky) + sl * np.maximum(0, e - kx[-1]), F.FLOOR, 80.0)


def build():
    """season-end rows with E[FV], the June boards and the stage score s (out of fold for the training rows)"""
    fit = json.load(open(F.OUT))
    mod = fit['models']['returner']
    F.TOP_MEAN = mod['topMean']
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    # the live board (next season's rosters): a 2026 player on it came back
    A = json.load(open(os.path.join(D.ROOT, 'static', 'data', 'cbb-all.json'))); ci = {k: i for i, k in enumerate(A['cols'])}
    live = N.Matcher([{'name': r[ci['name']], 'team': r[ci['team']]} for r in A['rows']], name='name', team='team', pos=None, sport='basketball')
    pre, ex = [], []
    for c in careers:
        y = c['nba']['fvx']
        for i, s in enumerate(c['seasons']):
            if s['year'] < 2009: continue
            base = {'pid': c['pid'], 'name': c['name'], 'team': s['team'], 'brole': s['role'], 'yr': s['yr'], 'year': s['year'], 'last': c['last'],
                    'y': y, 'cls': (c['last'] - 2009) % F.FOLDS, 'nba': c['nba'], 'final': i == len(c['seasons']) - 1}
            if i and s['year'] in TRAIN and c['last'] <= 2020: pre.append(dict(base, f=F.features(c, i)))
            ex.append(dict(base, f=exit_features(c, i)))
    # who left after 2026: drafted that June, or not on the 2026-27 board
    for r in ex:
        if r['year'] == LAST and r['final']:
            r['final'] = r['nba'].get('draft') == LAST or live.find(r['name'], r['team'])[0] is None
    tr = [r for r in ex if r['year'] in TRAIN and r['last'] <= 2020]
    trid = {id(r) for r in tr}
    fwd = [r for r in ex if id(r) not in trid]
    print(f'season-end rows {len(ex)}: training {len(tr)} (finals {sum(r["final"] for r in tr)}), forward {len(fwd)}')

    # E[FV] at season's end: out of fold for the training rows (the returner model refit with the player's class held
    # out, shipped drivers and penalties), the shipped model for later seasons
    Xp, Xt, Xf = (F.matrix(rs, mod['kept']) for rs in (pre, tr, fwd))
    fp, ft = np.array([r['cls'] for r in pre]), np.array([r['cls'] for r in tr])
    idx = list(range(len(mod['kept'])))
    for k in range(F.FOLDS):
        m = F.fit([r for r, t in zip(pre, fp != k) if t], Xp[fp != k], idx, mod['lam'])
        for r, e in zip([r for r, t in zip(tr, ft == k) if t], F.predict(m, Xt[ft == k])[2]): r['f']['e'] = float(e)
    full = {'std': F.Std(np.zeros((1, len(idx)))), 'idx': idx, 'w': [np.array(w) for w in mod['w']]}
    full['std'].m, full['std'].s = np.array(mod['mean']), np.array(mod['sd'])
    for r, e in zip(fwd, F.predict(full, Xf)[2]): r['f']['e'] = float(e)

    # the June boards
    jr, sch, seen = F.june_ranks(), F.june_schools(), defaultdict(int)
    for r in ex: seen[(r['year'], D.norm(r['name']))] += 1
    for r in ex:
        k = (r['year'], D.norm(r['name'])); v = jr.get(k)
        if v is not None and seen[k] > 1 and not any(N.same_team(r['team'], x) for x in sch.get(k, ())): v = None
        r['f']['lr'] = v if v is not None else F.CONS_FILL; r['f']['on'] = float(v is not None)

    # the board stage as the live board applies it in draft week (cbb_fit.board_stage, fit on preseason E and the June
    # boards; the late preseason -> June map at 3 days out, cbb_boards.att_at). A stage refit on season-end rows ranked
    # worse (Nov 3 2026: final seasons MSE +7.6, t +2.3, worse in 5/5 class folds): the shipped one is kept
    import cbb_boards as CBd
    att = CBd.att_at(json.load(open(CBd.ATT))['fit'], 3)
    for r in ex: r['s'] = F.board_e(r['f']['e'], r['f']['lr'] if r['f']['on'] else None, fit['boards'], att)[0]
    y = np.array([r['y'] for r in tr], float); fin = np.array([r['final'] for r in tr])
    return ex, tr, fwd, ft, fin, y, fit


def end_map(tr, fit):
    """the live board's E[FV] -> grade at season's end (cbb_live blends it in by each player's weight on this season):
    the grade whose headline (fv_dist.at_mean) is the mean outcome at that E on every 2009-16 season-end row (who
    leaves isn't known yet), as cbb_fit.emap_cal. The preseason map (emap.stage, fit on simulated preseason boards)
    left draft week's top 10 a season 3.6 FV under what they became (48.6 given, 52.2 became; top 25 44.9 / 47.7).
    Class held out: top 10 52.2 / 51.3, top 25 48.5 / 47.7 (bias smaller in 6 of 8 seasons), MSE 208.0 -> 206.9
    (t -0.8, better in 4 of 5 folds). Nov 4 2026, class held out (all 2009-16 season-end rows, Holm k 3, none passed;
    the map's own 30+ slope is .97, centers 30+ -0.5): headline top-slope term (t -0.2, 3/5), centers' slope term
    (t +0.6, 2/5; forward better t -2.7), coarser top bins (tail 2e-2: t +5.2, 0/5)."""
    RR = [dict(r, yr=NEXT.get(r['yr'], 'Sr'), f=dict(r['f'], newcomer=False)) for r in tr]
    M = F.emap_cal(RR, np.array([r['s'] for r in tr])[None, :])
    M['kind'] = 'calibration (season-end rows 2009-16, the board stage at draft week; scripts/cbb_draftday.py)'
    return M


def main():
    ex, tr, fwd, ft, fin, y, fit = build()
    M = end_map(tr, fit)
    json.dump(M, open(END, 'w'), indent=1)
    print('season-end map ->', END, list(zip(M['e'][-4:], M['g'][-4:])))

    # the mean outcome at each stage score: one map for finals (he left), one for season-ends he came back from;
    # cross-fitted for the training rows
    s = np.array([r['s'] for r in tr])
    for want in (True, False):
        on = fin == want
        for k in range(F.FOLDS):
            te = on & (ft == k); M = calmap(s[on & (ft != k)], y[on & (ft != k)])
            for r, v in zip([r for r, t in zip(tr, te) if t], apply_map(M, s[te])): r['fvx'] = float(v)
        M = calmap(s[on], y[on])
        F_ = [r for r in fwd if r['final'] == want]
        for r, v in zip(F_, apply_map(M, np.array([r['s'] for r in F_]))): r['fvx'] = float(v)

    # the headline's stretched top (scripts/fv_scale.py), on these grades' own history: draft-day means spread wider
    # than preseason ones (the preseason board's knot 46.6 would show every lottery pick as 80), so K = the mean about
    # three players a season reach at the draft and T = one every five seasons, capped at the reach of a sure 80
    vals = [r['fvx'] for r in tr if r['final']]
    K, th, T = FS.tail_values(vals, len(TRAIN))
    reach = FS.scale()['cbb']['reach']
    J = json.load(open(FS.FILE))
    J['boards']['cbbx'] = {'K': round(K, 2), 'T': round(min(T, reach), 2), 'tail': round(th, 2), 'tailT': round(T, 2), 'reach': reach, 'seasons': len(TRAIN),
                           'src': 'held-out draft-day grades, college exits 2009-16 (scripts/cbb_draftday.py)'}
    json.dump(J, open(FS.FILE, 'w'), indent=1); FS._S = None
    print('draft-day scale', J['boards']['cbbx'])

    # one row per player: his last season if he left, his latest season-end if he's still in college
    pick = {}
    for r in ex:
        if r['pid'] not in pick or r['year'] > pick[r['pid']]['year']: pick[r['pid']] = r
    by = defaultdict(list)
    for r in pick.values(): by[r['year']].append(r)
    out = []
    for yr in sorted(by):
        for r in sorted(by[yr], key=lambda r: -r['fvx'])[:PER_SEASON]:
            n = r['nba']; mature = r['last'] <= 2020   # six NBA seasons or more (the fit's outcome window)
            out.append({'name': r['name'], 'season': yr, 'team': r['team'], 'pos': F.POS3.get(r['brole'], 'F'), 'cls': r['yr'],
                        'fvx': round(r['fvx'], 2), 'fv': FS.fv_of('cbbx', r['fvx']), 'out': int(r['y']) if mature else None,
                        'role': ((('peak XPM %+.1f, ' % n['peakXpm']) if r['y'] > 20 and n.get('peakXpm') is not None else '') + n['role']) if mature else None,
                        'pick': n.get('pick') or None, 'draft': n.get('draft') or None, 'status': None if r['final'] else 'college',
                        'june': round(math.exp(-r['f']['lr'])) if r['f']['on'] else None})
    out += intl_rows()
    with gzip.open(OUT, 'wt') as f: json.dump({'asof': __import__('datetime').date.today().isoformat(), 'rows': out}, f, separators=(',', ':'))
    print('wrote', OUT, len(out), 'rows')


def intl_snapshot():
    """the internationals on the 2009-26 final boards at their draft (cbb_intl.draft_history; needs the
    Basketball-Reference cache, scripts/cbb_intl_pull.sh) -> INTL, so the list rebuilds without it"""
    import cbb_intl as I
    R = I.draft_history(LAST)
    keep = [{'pid': r['pid'], 'name': html.unescape(r['name']), 'year': r['year'], 'club': html.unescape(r['club'] or ''), 'pos': r['pos'], 'e': round(r['e'], 3),
             'oof': r['oof'], 'y': r['y'], 'xpm': r['xpm'], 'june': round(math.exp(-r['f']['lr']), 1)} for r in R]
    with gzip.open(INTL, 'wt') as f: json.dump({'asof': __import__('datetime').date.today().isoformat(), 'rows': keep}, f, separators=(',', ':'))
    print('wrote', INTL, len(keep), 'rows')


def intl_rows():
    """internationals on the list (Noah, Nov 3 2026: Doncic, Wembanyama), at the mean outcome their draft-day E[FV]
    predicts: the international model's out-of-fold line (realized - 20 = b (E - 20), as cbb_intl.fv_of), b refit with
    each player's fold held out for the 2009-20 classes, the full fit after. Held out (277 internationals 2009-20) the
    line beats a PAV map (dMSE +6.1, t +1.3), the D-I June-rank curve (t +1.1; it graded the top 15 54.2, they became
    48.6) and that curve plus the model's production news (t +1.5); the top 15 by rank graded 47.0 and became 48.6"""
    if not os.path.exists(INTL): return []
    R = json.load(gzip.open(INTL))['rows']
    tr = [r for r in R if r['oof']]
    e = np.array([r['e'] for r in tr]); y = np.array([r['y'] for r in tr], float); fo = np.array([F.fold_of(r['pid']) for r in tr])
    b_of = lambda m: float(((e[m] - F.FLOOR) * (y[m] - F.FLOOR)).sum() / ((e[m] - F.FLOOR) ** 2).sum())
    bk = {k: b_of(fo != k) for k in range(F.FOLDS)}; b = b_of(np.ones(len(tr), bool))
    pick = {}
    for r in R:
        if r['pid'] not in pick or r['year'] > pick[r['pid']]['year']: pick[r['pid']] = r
    out = []
    for r in sorted(pick.values(), key=lambda r: (r['year'], -r['e'])):
        fvx = float(np.clip(F.FLOOR + (bk[F.fold_of(r['pid'])] if r['oof'] else b) * (r['e'] - F.FLOOR), F.FLOOR, 80.0))
        mature = r['year'] <= 2020
        out.append({'name': r['name'], 'season': r['year'], 'team': r['club'], 'pos': r['pos'], 'cls': 'Intl', 'fvx': round(fvx, 2), 'fv': FS.fv_of('cbbx', fvx),
                    'out': int(r['y']) if mature else None, 'role': (('peak XPM %+.1f' % r['xpm']) if r['xpm'] is not None and r['y'] > 20 else 'non-NBA') if mature else None,
                    'pick': None, 'draft': r['year'], 'status': None, 'june': round(r['june']) if r['june'] < 150 else None})
    print('internationals', len(out), 'line b', round(b, 3))
    return out


if __name__ == '__main__':
    if '--intl' in sys.argv: intl_snapshot()
    main()
