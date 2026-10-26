#!/usr/bin/env python3
"""CBB ARK Ranking research (Oct 26 2026): new preseason-prior and game-level terms for the college basketball game
model (its ratings are the ARK Ranking), none of them tried before.

    python3 scripts/cbb_ark_research.py [--only lab,lab]    # -> data/cbb_ark_research.json

Prior terms (the preseason regression on final net, walk-forward; each needs a full game walk):
  trkpre   Barttorvik's own preseason rating (T-Rank time machine, the day before the opener, adjoe - adjde, centred
           by season): a second roster model to pool with ours. 2015 on; 2014 rows are left out of the prior fit
  last2    final net two seasons back (program memory beyond last season); missing -> last
  trjump   transfers' projected minutes share x (new team's box margin - old team's) / 10: the level jump
  trlo     transfers' projected minutes share from a weaker team (old box margin < new - 5)
  frtop    projected minutes share of top-40 freshmen (elite freshman minutes, beyond fvfrm)
  star     the roster's best projected BPM (one star counts more than the linear sum?)
  bench    the mean projected BPM of minutes ranks 6-8 (depth for injuries and foul trouble)
  tenxnew  tenure x the minutes share projected for non-returners (an established coach with a new roster)
Game-level terms (added to the margin regression on the shipped walk, no new walk):
  hct      team home edge: the home team's mean walk-forward residual at home minus on the road, three seasons back,
           shrunk with 40 games (venue effects beyond one national home court)
  pri      the preseason prior gap, all season (not faded like the failed 'early')
Ship bar: tune 2016-20 paired t <= -1.5 (clustered by game day and home team-season), 2021-26 no worse.
"""
import json
import math
import os
import sys
from collections import defaultdict

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')        # before numpy: BLAS threads in forked workers make the CBB solves crawl

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cbb_ark_research.json')
TRANK_DIR = os.path.join(HERE, '.cache', 'cbb', 'trank')
FINAL_TERMS = ('last2', 'nolast')


def trank_pre():
    """season -> Barttorvik team -> T-Rank preseason net (the last file before any game), centred by season"""
    from datetime import date, timedelta
    import public_ratings as PR
    out = {}
    for s in range(2015, 2028):
        best = None
        d = date(s - 1, 10, 20)
        while d <= date(s - 1, 11, 16):
            k = d.strftime('%Y%m%d')
            PR.trank_one(k)
            p = os.path.join(TRANK_DIR, k + '.json')
            if os.path.exists(p):
                j = json.load(open(p))
                if j and max(v[3] for v in j.values()) == 0:
                    best = j
            d += timedelta(days=1)
        if best:
            net = {t: v[0] - v[1] for t, v in best.items()}
            m = float(np.mean(list(net.values())))
            out[s] = {t: v - m for t, v in net.items()}
    return out


def roster_terms():
    """season -> Barttorvik team -> the new roster terms, from cbb_roster's walk-forward player models"""
    import cbb_roster as R
    by = R.load_seasons()
    ts = R.team_strength(by)
    _, _, models = R.build(by, ts)
    out = {}
    for y in sorted(by):
        if y - 1 not in by or y not in models:
            continue
        M = models[y]
        T = defaultdict(list)
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            k = R.kind(r, p, h)
            if k not in M:
                continue
            x = R.xrow(k, r, h if h else p, ts, y)
            bw, mw = M[k]
            info = {}
            if k == 'tr':
                info = {'old': x[8], 'new': x[9]}
            if k == 'fr':
                info = {'lr': x[1]}
            T[r['team']].append((k, float(np.dot(bw, x)), max(0.5, float(np.dot(mw, x))), info))
        out[y] = {}
        for team, L in T.items():
            tot = sum(m for _, _, m, _ in L)
            sh = [(k, b, m / tot * 5, i) for k, b, m, i in L]        # share of the 5 floor spots
            byb = sorted(sh, key=lambda q: -q[2])
            out[y][team] = {
                'trjump': sum(s / 5 * (i['new'] - i['old']) for k, b, s, i in sh if k == 'tr') / 10,
                'trup': sum(s / 5 * max(0.0, i['new'] - i['old']) for k, b, s, i in sh if k == 'tr') / 10,
                'trdn': sum(s / 5 * min(0.0, i['new'] - i['old']) for k, b, s, i in sh if k == 'tr') / 10,
                'trlo': sum(s / 5 for k, b, s, i in sh if k == 'tr' and i['old'] < i['new'] - 5),
                'frtop': sum(s / 5 for k, b, s, i in sh if k == 'fr' and i['lr'] > -math.log(40)),
                'star': max(b for _, b, _, _ in sh),
                'bench': float(np.mean([b for _, b, _, _ in byb[5:8]])) if len(byb) >= 8 else -4.0,
                'newsh': sum(s / 5 for k, b, s, i in sh if k not in ('ret', 'back')),
            }
    return out


# ---------------------------------------------------------------- walks
_A = {}


def _one(v):
    import cbb_games as C
    lab, pf = v
    games, btname, d1s, tprior, avs, P, feats = _A['args']
    C.PRIOR_F = list(C.PRIOR_F) + pf
    if 'trkpre' in pf and lab not in ('trkfill', 'trk0', 'trkdummy', 'nolast+trk0') and not lab.startswith('trkfill'):
        # T-Rank preseason starts in 2015: leave 2014 out of the prior fit
        orig = C.Walk.prior_coef

        def pc(self, s):
            if s not in self.pcoef:
                self.prior_rows = [r for r in self.prior_rows if r[0] >= 2015]
            return orig(self, s)
        C.Walk.prior_coef = pc
    if lab == 'trkdummy':
        # control: only the 2014 stand-in (a season indicator), no T-Rank
        orig_d = C.Walk.prior_feats

        def pfd(self, s, t, last):
            out = orig_d(self, s, t, last)
            out['trkpre'] = -15.0 if s == 2014 else 0.0
            return out
        C.Walk.prior_feats = pfd
    if lab == 'trkfill':
        # 2014 has no T-Rank preseason: stand in last season's final net (centred) so no prior rows are dropped
        orig_f = C.Walk.prior_feats

        def pff(self, s, t, last):
            out = orig_f(self, s, t, last)
            if s == 2014:
                L = [v['net'] for v in last.values()]
                out['trkpre'] = (last[t]['net'] - float(np.mean(L))) if t in last else -15.0
            return out
        C.Walk.prior_feats = pff
    if any(k in FINAL_TERMS for k in pf):
        orig_pf = C.Walk.prior_feats

        def pfe(self, s, t, last):
            out = orig_pf(self, s, t, last)
            L2 = self.final.get(s - 2, {}).get(t)
            out['last2'] = L2['net'] if L2 else out['last']
            out['nolast'] = 0.0 if last.get(t) else 1.0
            return out
        C.Walk.prior_feats = pfe
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    pc = W.prior_coef(C.LAST + 1)
    res = {'pr': C.walk_pred(Xm, y, S, d1), 'ids': [g['id'] for g, _, _ in D],
           'prior': {k: round(float(pc[k]), 4) for k in C.PRIOR_F}}
    if lab == 'base':
        res.update(Xm=Xm, y=y, S=S, line=line, d1=d1, D=[(g['id'], g['date'][:10], g['season'], g['home'], g['away'], g['neutral']) for g, _, _ in D],
                   final=W.final, pri=game_prior(W, D, d1s))
    return lab, res


def game_prior(W, D, d1s):
    """each game's preseason prior gap (home minus away net), recomputed from the walk's prior coefficients"""
    pri = {}
    for s in sorted({g['season'] for g, _, _ in D}):
        p, _ = W.season_prior(s, sorted(d1s[s]))
        pri[s] = p
    return np.array([pri[g['season']].get(g['home'], {}).get('net', -8.0) - pri[g['season']].get(g['away'], {}).get('net', -8.0) for g, _, _ in D])


def hct_feature(base, k=40.0, back=3):
    """home edge by team from earlier seasons' walk-forward residuals (home games minus road games, halved)"""
    resid = base['y'] - base['pr']
    out = np.zeros(len(resid))
    # team -> season -> [home residual sum, home games, road residual sum (own side), road games]
    hsum = defaultdict(lambda: defaultdict(lambda: [0.0, 0, 0.0, 0]))
    for (gid, day, s, h, a, neu), r in zip(base['D'], resid):
        if neu or np.isnan(r):
            continue
        q = hsum[h][s]; q[0] += r; q[1] += 1
        q = hsum[a][s]; q[2] += -r; q[3] += 1
    for i, (gid, day, s, h, a, neu) in enumerate(base['D']):
        if neu:
            continue
        hsm = sum(hsum[h][ss][0] for ss in range(s - back, s)); hn = sum(hsum[h][ss][1] for ss in range(s - back, s))
        rsm = sum(hsum[h][ss][2] for ss in range(s - back, s)); rn = sum(hsum[h][ss][3] for ss in range(s - back, s))
        if hn and rn:
            out[i] = (hsm / (hn + k) - rsm / (rn + k)) / 2
    return out


def score(lab, pr, ref, y, line, masks, cl, extra=None):
    ok = ~np.isnan(line)
    r = {'label': lab, **(extra or {})}
    for nm, k in masks.items():
        e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
        p = H.paired(e, e0, cluster=[c[k] for c in cl])
        kk = k & ok
        r[nm] = {'n': int(k.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4),
                 't': round(p['t'], 2), 'dLined': round(float(np.abs(pr[kk] - y[kk]).mean() - np.abs(ref[kk] - y[kk]).mean()), 4),
                 'tLined': round(H.paired(np.abs(pr[kk] - y[kk]), np.abs(ref[kk] - y[kk]), cluster=[c[kk] for c in cl])['t'], 2)}
    r['pass'] = r['tune']['t'] <= -1.5 and r['held']['d'] <= 0
    print(json.dumps(r), flush=True)
    return r


VARIANTS = [('base', []), ('trkpre', ['trkpre']), ('last2', ['last2']), ('trjump', ['trjump']), ('trlo', ['trlo']),
            ('frtop', ['frtop']), ('star', ['star']), ('bench', ['bench']), ('tenxnew', ['tenxnew']),
            ('trup+trdn', ['trup', 'trdn']), ('trup', ['trup']), ('trjump+trlo', ['trjump', 'trlo']),
            ('trjump+star', ['trjump', 'star']), ('trkfill', ['trkpre']), ('trkfill+trjump', ['trkpre', 'trjump']), ('trkfill+trup+trdn', ['trkpre', 'trup', 'trdn']),
            ('trkfill+star', ['trkpre', 'star']), ('trkfill+last2', ['trkpre', 'last2']),
            ('trk0', ['trkpre']), ('trkdummy', ['trkpre']),
            ('nolast', ['nolast']), ('nolast+trk0', ['nolast', 'trkpre']), ('nolast+trjump', ['nolast', 'trjump']),
            ('nolast+star', ['nolast', 'star'])]


def main():
    import multiprocessing as mp
    import cbb_games as C
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    tk = trank_pre()
    rt = roster_terms()
    for s, T in tprior.items():
        s = int(s)
        for t, f in T.items():
            if s in tk:
                f['trkpre'] = tk[s].get(t, -15.0)
            f.update(rt.get(s, {}).get(t, {}))
            f['tenxnew'] = f.get('tenure', 0.0) * f.get('newsh', 0.0)
    _A['args'] = (games, btname, d1s, tprior, avs, F['params'], list(F['feats']))
    V = VARIANTS
    if '--only' in sys.argv:
        keep = sys.argv[sys.argv.index('--only') + 1].split(',')
        V = [V[0]] + [v for v in V if v[0] in keep]
    with mp.get_context('fork').Pool(int(os.environ.get('PROCS', 4)), maxtasksperchild=1) as pool:
        res = dict(pool.map(_one, V))
    b = res['base']
    ok = ~np.isnan(b['pr']) & b['d1']
    S = b['S']
    k1 = ok & (S >= C.SCORE0) & (S <= C.TUNE_END); k2 = ok & (S > C.TUNE_END)
    day = np.array([d[1] for d in b['D']]); team = np.array([f'{d[3]}|{d[2]}' for d in b['D']])
    early = np.array([d[5:] >= '11-01' and d[5:] <= '12-15' for d in day])
    masks = {'tune': k1, 'held': k2, 'tuneEarly': k1 & early, 'heldEarly': k2 & early,
             'held21_23': k2 & (S <= 2023), 'held24_26': k2 & (S >= 2024)}
    cl = [day, team]
    out = []
    for lab, pf in V[1:]:
        r = res[lab]
        assert r['ids'] == b['ids']
        out.append(score(lab, r['pr'], b['pr'], b['y'], b['line'], masks, cl, {'priorTerms': pf, 'priorCoef': {k: r['prior'][k] for k in pf}}))
    # game-level terms on the shipped walk
    for lab, col in (('hct', hct_feature(b)), ('pri', b['pri'] * 0.69)):
        Xm = np.column_stack([b['Xm'], col])
        pr = C.walk_pred(Xm, b['y'], S, b['d1'], ridge=1e-3)
        out.append(score(lab, pr, b['pr'], b['y'], b['line'], masks, cl, {'game': True}))
    # T-Rank preseason vs our prior and final, by season (a point-in-time check: no jump in fit after the fact)
    chk = {}
    for s in sorted(tk):
        fin = b['final'].get(s) or {}
        pairs = [(tk[s][btname[t]], fin[t]['net']) for t in fin if btname.get(t) in tk[s]]
        if len(pairs) > 50:
            a = np.array(pairs)
            chk[s] = {'n': len(a), 'r': round(float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), 3)}
    print('trank r', chk, flush=True)
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    old = {r['label']: r for r in d.get('results', [])}
    old.update({r['label']: r for r in out})
    d['results'] = list(old.values())
    d['trankFinalR'] = chk or d.get('trankFinalR')
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1)


if __name__ == '__main__':
    main()
