# Soccer GAR / SVAR on FotMob (Nov 26 2026)

Understat's league endpoint has served a "come back soon" page since Nov 1 2026, so GAR, SV / SVAR and everything read
from them stood still. `scripts/soccer_fm_gar.py` rebuilds them from FotMob's season lists; this folder is its test.

- `prereg.md` (sha in `prereg.sha256`): candidates and gates, written before any result.
- `pull.py`: every FotMob season list of the big five as served (cache `scripts/.cache/soccer/fmg_raw`).
- `snaps.py`: Understat as it stood at .25 / .5 / .75 of each season, GAR and SV per player (needs the match cache:
  untar `/mnt/project-files/soccer/understat_cache.tgz` into `scripts/.cache/soccer`).
- `test.py` -> `results.json`. Seasons 2021..2026 (FotMob lists xG for every player from 2020-21); 2027 never read.

Model: ridge per position, FotMob rates a 90 (league-relative, shrunk by minutes) + the side's xG for / against ->
the player's league-relative Understat value a 90. GAR form adds his Understat value from the season before. Every
outer fold picked ridge 3 and 450 shrink minutes on its training seasons (the top of the ridge grid and the bottom of
the shrink grid; not widened after the fact).

Held out by season, 14,342 player-seasons, 98.9% of Understat minutes matched to a FotMob player:

| | r with Understat (a 90, minutes-weighted) |
|---|---|
| GAR | .928 |
| SV | .950 |

Season totals, RMSE in goals, Understat frozen at share f of the season and scored at its end:

| metric, f | C0 frozen total | C1 frozen rate x minutes | C2 FotMob alone | C3 blend | t C3 vs C1 | seasons |
|---|---|---|---|---|---|---|
| GAR .25 | 1.650 | .913 | .667 | **.596** | -28.8 | 6/6 |
| GAR .50 | 1.159 | .663 | .667 | **.507** | -22.3 | 6/6 |
| GAR .75 | .668 | .433 | .667 | **.386** | -18.4 | 6/6 |
| SVAR .25 | 1.655 | 1.126 | .538 | **.527** | -28.9 | 6/6 |
| SVAR .50 | 1.186 | .760 | .538 | **.480** | -24.7 | 6/6 |
| SVAR .75 | .700 | .494 | .538 | **.396** | -20.9 | 6/6 |

Top 150 by SVAR, Spearman with the final order: .40 -> .85 at f .25, .65 -> .87 at .5, .78 -> .88 at .75.
Roster sum against the side's goal difference (R2, centred by league-season): blend .90-.92 SVAR, .87-.88 GAR; the
full-season Understat values .894 and .876.

Gate 1 (fallback): passes for both metrics at every depth. Shipped as C3; blend weights w = a x umin / (umin + k) per
depth in `data/soccer_fm_gar_fit.json` (GAR a .4 / .6 / .8, SV .4 / .4 / .6), straight lines between and on to a = 1
at depth 1.
Gate 2 (blended in while Understat is up): fails. Next-season team R2 .568 -> .569, t .7, 4 of 5 pairs; FotMob alone
.559. Understat stays the only source when it is in step.

Limits. FotMob's past seasons exist only as end-of-season totals, so each freeze is scored at the end of the season:
the live case (10 rounds seen of 12-13) is read off the .75 row by the share of matches seen, not simulated at its
own sample size. No on-pitch data from FotMob: the split of a side's xG between its players is the frozen Understat
split plus what the box rates and the side's totals say. A match-page pull (shot maps + substitutions) would give a
real on/off, but it is a new fetcher on fotmob.com/api (robots: Noah's Nov 19 rule), not built.
The first run of test.py matched 96% of minutes; club pairing by vote, two rules in scripts/names.py (mononyms, a
dropped leading given name) and 33 soccer aliases took it to 98.9%. No gate changed side.
