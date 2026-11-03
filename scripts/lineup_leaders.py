"""League-wide lineup leaders (5-man units, trios, pairs) for the basketball ARKBOARD "lineup leaders" tabs.
Shared by scripts/nba_lineups.py and scripts/cbb_lineups.py; layouts/shortcodes/lineupleaders.html shows it.

Input per season: team -> {five (tuple of player keys): [seconds, possessions, points for, points against]}.
Trios and pairs are summed over every five that holds them. sNet pulls Net toward the team's own net with k
possessions per unit size (k from odd/even game splits, see each script's K_LEAD; the team prior beat a prior of 0
out of sample in both leagues for all three sizes).

Season block: {label, games, k: {5, 3, 2}, floor: {5, 3, 2}, teams: {team: [name, logo, conf]}, players: [name, ...],
               rows: {"5" | "3" | "2": [[player indexes], team, MIN, poss, ORtg, DRtg, sNet], ...}}
Rows: every group with floor+ possessions; floor = the lowest of STEPS that keeps MAX_ROWS or fewer (file size), so
any possession filter at or above it ranks the full list.
"""
import itertools
from collections import defaultdict

STEPS = (25, 50, 100, 200, 400, 800)
MAX_ROWS = 1500


def combos(fives, size):
    c = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for five, v in fives.items():
        if len(five) != 5:                         # a missed substitution leaves 4 or 6
            continue
        for k in (itertools.combinations(sorted(five), size) if size < 5 else [tuple(sorted(five))]):
            x = c[k]
            for i in range(4):
                x[i] += v[i]
    return c


def season_block(U, k, name_of, teams, label, games):
    """U: team -> fives; k: {5, 3, 2} possessions; name_of(team, key) -> display name; teams: team -> [name, logo, conf]
    (teams missing from it are left out)"""
    players, pix = [], {}
    rows, floor = {}, {}
    for size in (5, 3, 2):
        out = []
        for t, fives in U.items():
            if t not in teams:
                continue
            tot = [sum(v[i] for v in fives.values()) for i in range(4)]
            tnet = 100 * (tot[2] - tot[3]) / tot[1] if tot[1] > 0 else 0.0
            for ks, (sec, poss, pf, pa) in combos(fives, size).items():
                if poss < STEPS[0]:
                    continue
                net = 100 * (pf - pa) / poss
                ix = []
                for p in ks:
                    nm = name_of(t, p)
                    key = (t, nm)
                    if key not in pix:
                        pix[key] = len(players); players.append(nm)
                    ix.append(pix[key])
                out.append([ix, t, round(sec / 60, 1), round(poss, 1), round(100 * pf / poss, 1), round(100 * pa / poss, 1),
                            round((net * poss + tnet * k[size]) / (poss + k[size]), 1)])
        floor[str(size)] = next((f for f in STEPS if sum(1 for r in out if r[3] >= f) <= MAX_ROWS), STEPS[-1])
        rows[str(size)] = sorted((r for r in out if r[3] >= floor[str(size)]), key=lambda r: -r[6])
    # players in kept rows only, re-indexed
    keep = sorted({i for v in rows.values() for r in v for i in r[0]})
    ix = {o: n for n, o in enumerate(keep)}
    for v in rows.values():
        for r in v:
            r[0] = [ix[i] for i in r[0]]
    used = {r[1] for v in rows.values() for r in v}
    return dict(label=label, games=games, k={str(s): k[s] for s in (5, 3, 2)}, floor=floor,
                teams={t: teams[t] for t in sorted(used)}, players=[players[i] for i in keep], rows=rows)
