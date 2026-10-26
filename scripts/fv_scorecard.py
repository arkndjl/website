#!/usr/bin/env python3
"""FV scorecards: does a board's FV mean what it says? Held-out rows only (each player graded by a fit that never saw
him), pooled in FV bands: the mean FV the band was given against the mean FV its careers reached, and the predicted
odds of each outcome tier against the share that got there. Shared by every prospect board, read by
layouts/shortcodes/fvcard.html:

    CFB, CBB   python3 scripts/fv_dist_fit.py --scorecard      -> data/fv_dist.json cfb.scorecard, cbb.scorecard
    hockey     python3 scripts/hockey_prospects.py --scorecard -> data/hockey_fit.json scorecard
    soccer     python3 scripts/soccer_prospects.py --scorecard -> data/soccer_prospects_fit.json scorecard

--scorecard reruns a board's held-out pass and writes only the scorecard key; the fit itself is left as it is.
Tier odds: CFB and CBB from the FV distribution (the ordered probit each player's outlook shows, held out); hockey
and soccer from a logistic on the held-out grade, the form their boards use, fit with the player's class left out.
Intervals: 90%, Wilson for shares, normal for the band's mean FV. The top bands are thin (a class holds a few 65s), so
the scorecard says how wide its own evidence is there rather than reading one bust or one star as miscalibration.
"""
import math
import numpy as np

TIERS = [30, 40, 50, 60]
LOWS = [20, 25, 30, 35, 40, 45, 50, 55, 60, 65]        # bands of 5; the last holds every grade of 65 or more
Z90 = 1.645


def wilson(k, n, z=Z90):
    if not n: return [None, None]
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def basis(x, hinges=()):
    return np.c_[np.ones(len(x)), x, *[np.maximum(0, x - h) for h in hinges]]


def logit_x(X, y):
    w = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        H = (X * (p * (1 - p))[:, None]).T @ X + 1e-6 * np.eye(len(w))
        w = w + np.linalg.solve(H, X.T @ (y - p))
    return w


def class_out_odds(grade, real, cls, tiers=TIERS, hinges=None):
    """P(outcome >= tier) for each row from a logistic on the grade minus the tier (with the board's slope changes,
    hinges = {tier: (offsets...)}), fit on the other classes"""
    out = np.zeros((len(grade), len(tiers)))
    for c in np.unique(cls):
        m = cls == c
        for j, t in enumerate(tiers):
            h = (hinges or {}).get(t, ())
            w = logit_x(basis(grade[~m] - t, h), (real[~m] >= t).astype(float))
            out[m, j] = 1 / (1 + np.exp(-np.clip(basis(grade[m] - t, h) @ w, -30, 30)))
    return out


def card(grade, real, odds=None, cls=None, tiers=TIERS, note=None, hinges=None):
    """grade: each row's held-out headline FV; real: the FV its career reached; odds: rows x tiers held-out
    P(real >= tier), or None to fit them class-out (cls needed)"""
    g = np.asarray(grade, float); y = np.asarray(real, float)
    P = np.asarray(odds, float) if odds is not None else class_out_odds(g, y, np.asarray(cls), tiers, hinges)
    bands = []
    for i, lo in enumerate(LOWS):
        hi = LOWS[i + 1] if i + 1 < len(LOWS) else 81
        m = (g >= lo) & (g < hi) if lo > LOWS[0] else g < hi
        n = int(m.sum())
        if not n: continue
        sd = float(y[m].std(ddof=1)) if n > 1 else 0.0
        mu = float(y[m].mean()); h = Z90 * sd / math.sqrt(n)
        bands.append({'lo': lo, 'hi': None if hi > 80 else hi - 1, 'n': n, 'pred': round(float(g[m].mean()), 1),
                      'real': round(mu, 1), 'ci': [round(mu - h, 1), round(mu + h, 1)],
                      'odds': [{'t': t, 'pred': round(float(P[m, j].mean()), 3), 'real': round(float((y[m] >= t).mean()), 3),
                                'ci': wilson(int((y[m] >= t).sum()), n)} for j, t in enumerate(tiers)]})
    # summary: slope of the outcome on the grade (1 = an FV point is worth a point), the mean miss, and per tier the
    # expected calibration error (|predicted - realized| share, weighted by band size) and the share of bands whose
    # 90% interval holds the prediction (about .9 if calibrated)
    b = np.polyfit(g, y, 1)
    summ = {'n': int(len(g)), 'slope': round(float(b[0]), 3), 'bias': round(float((y - g).mean()), 2),
            'tiers': [{'t': t, 'ece': round(float(sum(x['n'] * abs(x['odds'][j]['pred'] - x['odds'][j]['real']) for x in bands) / len(g)), 4),
                       'brier': round(float(((P[:, j] - (y >= t)) ** 2).mean()), 4),
                       'covered': round(float(np.mean([x['odds'][j]['ci'][0] <= x['odds'][j]['pred'] <= x['odds'][j]['ci'][1] for x in bands])), 2)}
                      for j, t in enumerate(tiers)]}
    out = {'tiers': list(tiers), 'bands': bands, 'summary': summ}
    if note: out['note'] = note
    return out
