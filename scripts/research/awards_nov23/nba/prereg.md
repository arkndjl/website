# NBA awards, Nov 23 2026: preregistration (written before any of these were run)

Engine, gate and history as scripts/awards_research.py / scripts/awards_more.py: rank-ordered logit, L2 1,
leave-one-season-out, one-sided paired t vs the null on held-out log-likelihood, Holm at .05 over the sport's WHOLE
list (MVP, DPOY, ROY, All-NBA p-values already in data/awards_fit.json + the new races below = 9), gain > 0, most
seasons won. History: Basketball-Reference award pages (voting order), per-game pages (games, games started) and
standings, joined by bbref id to static/data/nba-xpm/<season>.json. Seasons 2010-2026 unless said.

## New races

| key | award | pool | voter model cols | null | depth / k |
|---|---|---|---|---|---|
| smoy | Sixth Man | mp >= 500 and games started < games / 2 (bbref's rule) | vorx, xpm, ppg, mpg, wp, gfrac | vorx | 3 |
| mip | Most Improved | mp >= 1000, has a row in last season's XPM file (2011-26) | d_vorx, d_ppg, vorx, ppg, d_mpg, wp, gfrac | d_vorx | 3 |
| alldef | All-Defensive (10 named) | mp >= 1200 | dxpm, stocks, rpg, big, wp, mpg, gfrac, prev_alldef | dxpm | k 10 |
| allrookie | All-Rookie (10 named) | rookies, mp >= 300 (2012-26) | vorx, xpm, ppg, mpg, gfrac, wp | vorx | k 10 |
| coy | Coach of the Year | the 30 teams (the voted coach's team) | wp, d_wp, ovr, seed1 | wp | 3 |

- d_x = this season's x minus last season's (last season's published XPM file / per-game page). d_vorx is the MIP null
  because "improvement in value" is the value-metric analogue of the other races' null.
- ovr = final win share minus the preseason over/under (Basketball-Reference's preseason odds page, point-in-time:
  set before opening night). If the page is not available for most seasons, coy runs with wp, d_wp, seed1 and says so.
- Clutch Player of the Year: not modelled (first awarded 2023: 4 seasons, and clutch splits are not in our data).

## Conviction (P(lead), season-only value)

- smoy: VORX in the bench pool (games started < games / 2 at the time).
- mip: this season's VORX minus last season's published VORX (a fixed baseline; only this season's value is simulated).
- alldef: top 10 on D-XPM (mp pool as All-NBA's conviction, 20+ mpg). allrookie: top 10 on VORX among rookies.
- coy: none (no player value metric; a team's own win share is not "our value").

## Driver tests (add-on to the award's own voter model; paired held-out t vs that model; Holm over this list)

| award | driver | definition (point-in-time) |
|---|---|---|
| mvp | pre_vorx | last season's VORX (0 if no row) |
| mvp | pre_sxpm | last season's shrunk XPM (sxpm; the board's preseason expectation; -2 if no row) |
| mvp | prev_share | last season's MVP vote share |
| mvp | age | age |
| mvp | ppg_title | 1 if he leads the pool in points a game |
| allnba | pre_vorx | as above |
| allnba | pre_sxpm | as above |
| allnba | age | age |
| dpoy | pre_dxpm | last season's D-XPM (0 if no row) |
| dpoy | prev_share | last season's DPOY vote share |
| roy | ln_pick | ln draft slot (undrafted 61) from scripts/nba_draft_picks.json |
| roy | cons | -ln of the mean rank on the final pre-draft boards (ESPN, NBADraft.net; /mnt/project-files/cbb/boards; -ln 150 if on neither) |
| roy | cbb_fv | FV on the CBB past board for his last college season (static/data/cbb-past.json; 20 if not on it) + flag no_college |
| roy | age | age |
| smoy | pre_vorx | as above |
| smoy | prev_share | last season's 6MOY vote share |
| mip | bo | last season's held-out next-up BO% (the NBA breakout model's own leave-one-season-out prediction for this season, replicated from scripts/nba_breakout_research.py stage 1; 0 if not in its population) + flag bo_out (already broke out) |
| mip | age | age |
| allrookie | ln_pick | as ROY |
| allrookie | cons | as ROY |
| alldef | pre_dxpm | as DPOY |
| coy | pre_wp | last season's win share alone (d_wp minus wp collinear; tested as its own column) |

A driver ships only if it passes (Holm over the 22 tests, gain > 0, most seasons won) on an award whose voter model passes.
