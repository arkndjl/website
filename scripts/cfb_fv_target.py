"""NFL outcomes for the CFB FV retarget (audit #24): every drafted player's seasons on the NFL WAR scale, and his
second contract. The FV harness (scripts/cfb_fv_refit.mjs --target) joins these by PFR id.
  war   NFL WAR a season, sub-position lines (data/nfl_war_pos.json: missed games + contracts + AV, holdout r .73
        against .43 for AV's own line), the board's formula (scripts/nfl_war.py war_of), seasons 2016-25
  av    the same seasons' model AV (the old target's unit, for the side-by-side)
  apy   second contract: the first OTC contract signed 3+ years after the draft (nflverse historical_contracts, signed
        through mid-2022, so classes 2012-18 only), APY as a share of the cap; no contract = 0. Joined on draft year and
        overall pick, so no name matching
  python3 scripts/cfb_fv_target.py -> scripts/.cache/fvrefit/nfl_targets.json (about 10 minutes on a cold cache)
"""
import csv
import gzip
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_war as W   # noqa: E402

OUT = os.path.join(W.ROOT, 'scripts', '.cache', 'fvrefit', 'nfl_targets.json')
YEARS = range(2016, 2026)


def main():
    with open(W.FIT) as f:
        b = json.load(f)['coef']
    line, value, spread = W.sub_lines()
    picks = list(W.rows(W.get('draft_picks.csv', f'{W.REL}/draft_picks/draft_picks.csv')))
    by_slot = {(r['season'], r['pick']): r['pfr_player_id'] for r in picks if r['pfr_player_id']}
    want = {r['pfr_player_id']: int(r['season']) for r in picks if r['pfr_player_id'] and 2012 <= int(r['season']) <= 2024}
    seasons = defaultdict(dict)
    for y in YEARS:
        sd = W.season_data(y)
        ros, by_name = W.rosters(y)
        for (pfr, t), s_ in sd['snaps'].items():
            if pfr not in ros and (s_['name'].lower(), t) in by_name:
                ros[pfr] = by_name[(s_['name'].lower(), t)]
        for o in W.team_rows(sd, b, ros):
            if o['pfr'] not in want:
                continue
            a = seasons[o['pfr']].setdefault(str(y), [0.0, 0.0, 0.0, {}])
            a[0] += o['av']; a[1] += W.war_of(o['av'], o['share'], o['sub'], line, value, spread); a[2] += o['share']
            a[3][o['sub']] = a[3].get(o['sub'], 0) + o['share']
        print('season', y, len(seasons), flush=True)
    apy = {}
    with gzip.open(W.get('historical_contracts.csv.gz', W.CONTRACTS), 'rt') as f:
        for c in csv.DictReader(f):
            try:
                ys, cap, dy = int(c['year_signed']), float(c['apy_cap_pct']), int(c['draft_year'])
            except ValueError:
                continue
            pid = by_slot.get((c['draft_year'], c['draft_overall']))
            if pid and ys - dy >= 3 and (pid not in apy or ys < apy[pid][0]):
                apy[pid] = [ys, cap]
    out = {}
    for pid, d in want.items():
        s = seasons.get(pid, {})
        out[pid] = {'draft': d, 'seasons': {y: [round(v[0], 3), round(v[1], 4), round(v[2], 3), max(v[3], key=v[3].get)] for y, v in s.items()},
                    'apy': apy[pid][1] if pid in apy else 0.0, 'apyYear': apy[pid][0] if pid in apy else None}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f)
    print('players', len(out), 'with seasons', sum(1 for v in out.values() if v['seasons']), 'second contracts', len(apy))


if __name__ == '__main__':
    main()
