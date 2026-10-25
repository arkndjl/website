#!/usr/bin/env python3
"""Refit the college basketball injury SIT rates (scripts/cbb_games_live.py) on our own logged listings.

    python3 scripts/cbb_sit_refit.py [season]      -> data/cbb_sit_fit.json

SIT is borrowed from the NBA (no college status history exists). scripts/cbb_games_live.py appends each day's matched
Covers listings to scripts/data/cbb_injury_log/<season>.jsonl, so the history builds up from 2026-27 on.

PRE-REGISTERED (fixed 2026-10-25, before any college listing was logged):
  listing   one line of the log: [date, team, Barttorvik pid, name, status], first listing per player per status a day
  outcome   the team's first game on or after the listing date (within 7 days; later games drop the listing):
            sat = the player has no minutes in that game's Barttorvik box
  groups    out (out, out for season, suspended), doubtful, questionable (questionable, day to day, game time
            decision), probable
  when      only once n >= 400 scored listings in all; below that it reports the count and changes nothing
  fit       each group's sit rate = (sat + 20 x NBA rate) / (n + 20)  (shrunk to the NBA rate, 20 listings of prior)
  test      chronological: fit on the first half of listing dates, log loss (p clipped .01-.99) on the second half
            against the NBA rates; paired t on per-listing loss differences
  ship      held-out log loss lower and t <= -2: write the full-sample fit with ship true; cbb_games_live.py then
            uses it in place of SIT. Otherwise ship false and the NBA rates stay.
"""
import json, math, os, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_games as C                    # noqa: E402

GROUP = {'out': 'out', 'out for season': 'out', 'suspended': 'out', 'doubtful': 'doubtful', 'questionable': 'questionable',
         'day to day': 'questionable', 'game time decision': 'questionable', 'probable': 'probable'}
NBA = {'out': 1.0, 'doubtful': 0.975, 'questionable': 0.44, 'probable': 0.05}
MIN_N, K = 400, 20


def scored(season):
    p = os.path.join(C.ROOT, 'scripts', 'data', 'cbb_injury_log', f'{season}.jsonl')
    if not os.path.exists(p):
        return []
    logs = C.bt_logs(season)
    out = []
    for line in open(p):
        d, team, pid, _, st = json.loads(line)
        g = GROUP.get(st)
        gl = logs.get(team)
        if not g or not gl:
            continue
        nxt = next(((gd, pl) for gd, pl in gl if gd >= d), None)
        if not nxt or date.fromisoformat(nxt[0]) - date.fromisoformat(d) > timedelta(days=7):
            continue
        out.append((d, g, 0 if pid in nxt[1] else 1))
    return out


def rates(rows):
    n = {g: 0 for g in NBA}; s = dict(n)
    for _, g, y in rows:
        n[g] += 1; s[g] += y
    return {g: round((s[g] + K * NBA[g]) / (n[g] + K), 4) for g in NBA}, n


def loss(p, y):
    p = min(max(p, .01), .99)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def main():
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2027
    rows = sorted(scored(season))
    out = {'season': season, 'n': len(rows), 'minN': MIN_N, 'ship': False, 'nba': NBA}
    if len(rows) >= MIN_N:
        days = sorted({d for d, _, _ in rows})
        cut = days[len(days) // 2]
        fit, _ = rates([r for r in rows if r[0] < cut])
        test = [r for r in rows if r[0] >= cut]
        diff = [loss(fit[g], y) - loss(NBA[g], y) for _, g, y in test]
        m = sum(diff) / len(diff)
        sd = math.sqrt(sum((x - m) ** 2 for x in diff) / max(len(diff) - 1, 1))
        t = m / (sd / math.sqrt(len(diff))) if sd else 0.0
        full, n = rates(rows)
        out.update({'heldN': len(test), 'heldLossDiff': round(m, 5), 't': round(t, 2), 'byGroup': n,
                    'ship': bool(m < 0 and t <= -2), 'sit': {st: full[g] for st, g in GROUP.items()}})
    with open(os.path.join(C.ROOT, 'data', 'cbb_sit_fit.json'), 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out))


if __name__ == '__main__':
    main()
