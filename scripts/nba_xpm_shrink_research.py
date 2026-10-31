"""Fit for shrunk XPM (nba_xpm.SHRINK_K / SHRINK_MU), Oct 31 2026. Noah: shrink XPM by sample size so players with very
few minutes don't post +8 seasons on 12 minutes.

    shrunk = mu(MP) + (raw - mu(MP)) x MP / (MP + k),   mu(MP) = c0 + c1 x ln(1 + MP82 / 100)

Target: next-season raw XPM of players with 250+ MP next season, weighted by min(next MP, 2000), 2011-26 pairs.
(c0, c1, k) chosen on the other seasons, scored on the held-out one (15 folds). Result: every fold picks
(-1, .5, 300); held-out RMSE 1.259 vs 1.593 raw, 1.266 flat mean 0 / k 300, 1.285 shrunk toward the player's own
history prior (nba_xpm.prior_xpm, best k 400). By minutes this season (shrunk / raw): <100 MP 1.75 / 7.29,
100-250 1.67 / 2.20, 250-500 1.42 / 1.76, 500-1000 1.31 / 1.47, 1000+ 1.22 / 1.26. Split by side at k 300:
O (-.75, .375), D (-.25, .125), which sum to the total's. An odd/even-game split of box XPM 2014-26
(scripts/nba_inseason.py box lines) agrees: within-season best k 200-300 with a mean near -1.

    python3 scripts/nba_xpm_shrink_research.py
Stdlib only."""
import json, math, os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'data', 'nba-xpm')


def pairs():
    D = {}
    for s in range(2010, 2027):
        d = json.load(open(os.path.join(OUT, f'{s}.json')))
        D[s] = {p['id']: p for p in d['players'] if not p.get('pr') and p.get('xpm') is not None}
    out = []
    for s in range(2011, 2026):
        for pid, p in D[s].items():
            n = D[s + 1].get(pid)
            if n and n['mp'] >= 250:
                out.append((s, p['mp'], p['xpm'], n['xpm'], min(n['mp'], 2000)))
    return out


def rmse(rows, c0, c1, k):
    a = b = 0.0
    for _, m, x, y, w in rows:
        mu = c0 + c1 * math.log(1 + m / 100)
        a += w * (mu + (x - mu) * m / (m + k) - y) ** 2; b += w
    return math.sqrt(a / b)


if __name__ == '__main__':
    R = pairs()
    G = [(c0, c1, k) for c0 in (-3, -2.5, -2, -1.5, -1, -.5, 0) for c1 in (0, .25, .5, .75, 1, 1.5) for k in (200, 300, 400, 600)]
    a = r = w = 0.0; picks = set()
    for s in sorted({t[0] for t in R}):
        tr = [t for t in R if t[0] != s]; te = [t for t in R if t[0] == s]
        g = min(G, key=lambda g: rmse(tr, *g)); picks.add(g)
        n = sum(t[4] for t in te); a += rmse(te, *g) ** 2 * n; r += rmse(te, 0, 0, 0) ** 2 * n; w += n
    print('held-out RMSE shrunk', round(math.sqrt(a / w), 3), 'raw', round(math.sqrt(r / w), 3), 'picks', sorted(picks))
