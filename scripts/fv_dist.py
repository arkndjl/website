"""FV as a distribution (data/fv_dist.json, fit by scripts/fv_dist_fit.py): for a graded FV and a player's spread
group, the chance of each outcome tier, the 80% range and the expected value. Same rules as fvDist in
scripts/fv_dist.mjs; layouts/partials/fvoutlook.html draws the result."""
import json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIT = None


def fit():
    global _FIT
    if _FIT is None:
        try:
            _FIT = json.load(open(os.path.join(ROOT, 'data', 'fv_dist.json')))
        except (OSError, ValueError):
            _FIT = {}
    return _FIT


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# the shared value scale (scripts/fv_value.py, Oct 26 2026): FV of a peak team share, 20 = replacement, 50 = 5% of a
# team, 80 = 80%. Kept here without numpy so the board builds stay stdlib; fv_value.py --test checks both agree
SHARE_C, SHARE_BASE = 1 / 280, 15.0


def fv_of_share(ts):
    return min(80.0, 20 + 30 * math.log1p(max(0.0, ts) / SHARE_C) / math.log(SHARE_BASE))


def share_of_fv(fv):
    return SHARE_C * math.expm1((max(20.0, fv) - 20) * math.log(SHARE_BASE) / 30)


def rarity_of(board, v):
    """the old outcome ladder's FV for a value-scale FV (the share curve read backwards), for models fit on that ladder"""
    K = fit().get(board, {}).get('shareCurve')
    if v is None or not K: return v
    return _interp(v, [fv_of_share(k[1]) for k in K], [k[0] for k in K])


def _interp(x, xs, ys):
    if x <= xs[0]: return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]: return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / max(1e-12, xs[i] - xs[i - 1])
    return ys[-1]


def fv_dist(board, fv, z=None):
    """{'p': bin chances, 'tiers': [<30, 30s, 40s, 50s, 60+], 'p10', 'p50', 'p90', 'mean', 'ev'} or None, all on the
    board's old outcome ladder; with the value scale fit (binShare, shareCurve): 'share' (expected peak team share),
    'vfv' (its FV, the headline), and 'tiersV', 'p10v', 'p50v', 'p90v' on the value scale."""
    M = fit().get(board)
    if not M or fv is None: return None
    z = z or {}
    H = M.get('hinges') or [45, 60]   # the location: the grade per 10 points from 40, plus a slope change at each hinge
    mu = sum(c * ((max(0, fv - H[i - 1]) if i else fv - 40) / 10) for i, c in enumerate(M['loc']))
    s = math.exp(max(-3, min(3, sum(g * z.get(k, 0) for k, g in (M.get('scale') or {}).items()))))
    F = [ncdf((c - mu) / s) for c in M['cuts']]
    p = [max(0.0, (F[k] if k < len(F) else 1) - (F[k - 1] if k else 0)) for k in range(len(F) + 1)]
    edges = M['edges']; lo = [20] + edges; hi = edges + [80]; fl = M['floorShare']

    def q(x):
        if x <= p[0] * fl: return 20.0
        if x <= p[0]: return 20 + 10 * (x / p[0] - fl) / max(1e-9, 1 - fl)
        c = p[0]
        for j in range(1, len(p)):
            if x <= c + p[j] or j == len(p) - 1: return lo[j] + (hi[j] - lo[j]) * min(1.0, (x - c) / max(1e-12, p[j]))
            c += p[j]
        return 80.0
    tiers = [0.0] * 5
    for j, v in enumerate(p): tiers[min(4, max(0, (lo[j] - 20) // 10))] += v
    bv = M.get('binValue')
    out = {'p': p, 'tiers': tiers, 'p10': q(0.1), 'p50': q(0.5), 'p90': q(0.9), 'mean': sum(v * m for v, m in zip(p, M['binMean'])),
           'ev': sum(v * m for v, m in zip(p, bv)) if bv else None}
    bs, sc = M.get('binShare'), M.get('shareCurve')
    if bs and sc:
        # the value scale: the headline is the FV of the expected peak share (each bin's mean share among past careers),
        # and the range and tier odds are the old ladder's, read through the share curve (monotone, so quantiles carry)
        xs, ys = [k[0] for k in sc], [fv_of_share(k[1]) for k in sc]
        K = lambda x: _interp(x, xs, ys)

        def cdf(y):     # P(old outcome < y), the inverse of q
            if y <= 20: return 0.0
            if y < lo[1]: return p[0] * fl + p[0] * (1 - fl) * (y - 20) / 10
            c = p[0]
            for j in range(1, len(p)):
                if y < hi[j] or j == len(p) - 1: return min(1.0, c + p[j] * min(1.0, (y - lo[j]) / max(1e-12, hi[j] - lo[j])))
                c += p[j]
            return 1.0
        cuts = [cdf(_interp(t, ys, xs)) if t > ys[0] else 0.0 for t in (30, 40, 50, 60)]
        cuts = [0.0] + cuts + [1.0]
        out['share'] = sum(v * m for v, m in zip(p, bs))
        out['vfv'] = fv_of_share(out['share'])
        bt = M.get('binTiers')
        if bt:   # each bin's careers that reached each value tier (they pile at the top bin's cap, not spread evenly)
            up = [sum(v * b[k] for v, b in zip(p, bt)) for k in range(4)]
            cuts = [0.0] + [1 - u for u in up] + [1.0]
        out['tiersV'] = [max(0.0, cuts[j + 1] - cuts[j]) for j in range(5)]
        out['p10v'], out['p50v'], out['p90v'] = K(out['p10']), K(out['p50']), K(out['p90'])
    return out


def cbb_z(cls=None, new=False, pos=None, fv=45):
    """a basketball player's spread terms (data/fv_dist.json cbb.scale), the fit's candidates (fv_dist_fit.cbb_terms):
    cls is the class this season, new a newcomer to D-I."""
    return {'pos_G': float(pos == 'G'), 'pos_C': float(pos == 'C'), 'new': float(bool(new)), 'fr': float(cls == 'Fr' and not new),
            'sr': float(cls in ('Sr', 'Gr')), 'level': ((fv if fv is not None else 45) - 45) / 10}


def at_mean(board, fv, z=None, scale='value'):
    """the headline FV for a graded FV: the mean of its outcome odds (both boards since Oct 21 2026; the grade, fvg on
    the boards, sat above the mean at the top: CBB 2010-16 boards graded 45+ averaged 51.0, their odds' mean 46.8,
    their careers 47.4). Since Oct 26 2026 (scripts/fv_value.py) the mean of the VALUE, the FV of the expected peak team
    share; scale='rarity' keeps the old ladder's mean (the CBB game prior was fit on it). The grade itself when there's
    no fit."""
    d = fv_dist(board, fv, z)
    if d is None: return fv
    return max(20.0, min(80.0, d['vfv'] if scale == 'value' and 'vfv' in d else d['mean']))


def fvd_of(d):
    """the board's compact field: [P <30, P 30s, P 40s, P 50s, P 60+, 10th pct, 90th pct], on the value scale when fit."""
    if not d: return None
    v = 'tiersV' in d
    return [round(x, 3) for x in d['tiersV' if v else 'tiers']] + [round(d['p10v' if v else 'p10'], 1), round(d['p90v' if v else 'p90'], 1)]


if __name__ == '__main__':
    # python3 scripts/fv_dist.py --annotate: refresh the fvd column of static/data/cbb-all.json in place (after a refit)
    import sys
    if '--past' in sys.argv:
        # once, and after cbb_fit.py rewrites static/data/cbb-past.json: the past boards at the mean (fvg the grade),
        # and the board's calibration table keyed by the headline FV (data/cbb_fit.json calibMean; calib stays keyed by
        # the grade, which cbb_intl's outcome map reads), from the 2010-16 boards' top PAST_N; the floor row (everyone
        # under 30, tens of thousands of players) is cbb_fit's
        f = os.path.join(ROOT, 'static', 'data', 'cbb-past.json')
        A = json.load(open(f)); ci = {c: i for i, c in enumerate(A['cols'])}
        if 'fvg' not in ci:
            A['cols'].append('fvg'); ci['fvg'] = len(A['cols']) - 1
            for r in A['rows']: r.append(r[ci['fvx']])
        for r in A['rows']:
            g = r[ci['fvg']]
            m = at_mean('cbb', g, cbb_z(r[ci['cls']], r[ci['new']], r[ci['pos']], g))
            r[ci['fvx']], r[ci['fv']], r[ci['plus']] = round(m, 2), int(round(m)), False
        # the career on the value scale too (outv: the FV of the peak share its outcome rung averaged, the share curve;
        # outcome stays the rung, the fit's target)
        K = fit().get('cbb', {}).get('shareCurve')
        if K:
            if 'outv' not in ci:
                A['cols'].append('outv'); ci['outv'] = len(A['cols']) - 1
                for r in A['rows']: r.append(None)
            xs, ys = [k[0] for k in K], [k[1] for k in K]
            for r in A['rows']:
                y = r[ci['outcome']]
                r[ci['outv']] = None if y is None else int(round(fv_of_share(_interp(y, xs, ys))))
        json.dump(A, open(f, 'w'), separators=(',', ':'))
        tier = lambda x: 20 if x < 30 else min(80, int(x // 5 * 5))
        cal = {}
        for r in A['rows']:
            y = r[ci['outcome']]
            if r[ci['season']] <= 2016 and y is not None and r[ci['fv']] >= 30: cal.setdefault(tier(r[ci['fv']]), []).append((y, r[ci['outv']] if 'outv' in ci else y))
        fn = os.path.join(ROOT, 'data', 'cbb_fit.json'); F = json.load(open(fn))
        floor = F['calib'].get('20')
        mean = lambda v: sum(v) / len(v)
        # meanFv: the careers' mean value (the FV of their mean share); the role odds stay on the rungs
        sh = lambda v: fv_of_share(sum(share_of_fv(o) for _, o in v) / len(v))
        calib = {str(t): {'n': len(v), 'meanFv': round(sh(v), 1), 'nba': round(mean([x >= 30 for x, _ in v]), 3),
                          'starter': round(mean([x >= 45 for x, _ in v]), 3), 'star': round(mean([x >= 60 for x, _ in v]), 3)}
                 for t, v in sorted(cal.items(), reverse=True)}
        if floor: calib['20'] = floor
        F['calibMean'] = calib
        json.dump(F, open(fn, 'w'), indent=1)
        print(len(A['rows']), 'past rows at the mean; calib', calib)
    if '--annotate' in sys.argv:
        f = os.path.join(ROOT, 'static', 'data', 'cbb-all.json')
        A = json.load(open(f))
        if 'fvd' not in A['cols']:
            A['cols'].append('fvd')
            for r in A['rows']: r.append(None)
        ci = {c: i for i, c in enumerate(A['cols'])}
        for r in A['rows']:
            g = r[ci['fvg']] if 'fvg' in ci and r[ci['fvg']] is not None else r[ci['fvx']]   # the odds come off the grade
            d = fv_dist('cbb', g, cbb_z(r[ci['cls']], r[ci['new']], r[ci['pos']], g))
            r[ci['fvd']] = fvd_of(d)
            if d is not None and 'fvg' in ci and r[ci['fvg']] is not None and 'vfv' in d:   # the headline on the value scale
                r[ci['fvx']] = round(max(20.0, min(80.0, d['vfv'])), 2); r[ci['fv']] = int(round(r[ci['fvx']]))
        json.dump(A, open(f, 'w'), separators=(',', ':'))
        print('fvd on', sum(1 for r in A['rows'] if r[ci['fvd']]), 'of', len(A['rows']), 'rows')
