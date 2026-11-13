# Soccer model sweep, Nov 13 2026

Pre-registration and held-out results: prereg.md (sha 75c6724a1dd1 before batch 1, d85b56e4dbd1 before batch 2).
History ends with 2025-26; nothing here reads 2026-27 results.

| test | split | result |
|---|---|---|
| Market totals ratings (totals.py; live in soccer_games.Ratings.total) | held 2023-26, 21,763 matches, 16 leagues | over 2.5 log loss .68265 -> .67531, t -8.93, 4/4 seasons; big five t -2.51; other eleven t -8.66. SHIPPED |
| Club leans on top of the league term | held | -.000415, t -2.55. kept |
| Parity draw boost | held | -.000082, t -0.77. FAIL |
| Match total in the draw chance (draw_total.py) | held | -.000057, t -0.69. FAIL |
| Kalman market ratings (engine.py kq) | tune 2013-22 | .96642 vs .96603. FAIL |
| Squad value x early season (mve) | tune | worse at every setting. FAIL |
| Late-season stakes (stk; shadow_feats.py any3/any6/champ) | tune | close prices it at .075 log goals (t 21); results t -1.3. FAIL |
| Close as teacher, 23 features (shadow.py) | tune walk 2015-22 | best set t -1.3. FAIL |
| Club lean in UEFA matches (keu) | tune | worse. FAIL |
| Settings in the 18 untuned leagues (others.py) | tune | every move <= .0001; same optimum. no change |
| Injured player's value: two seasons pooled, market value, blend (inj_value.py) | tune | t -0.4 / +0.3 / -0.7. FAIL |

Where the game model trails the close (big five, 2013-22): .0129 a match in a club's first four matches, .0167 from
its 36th on, .002-.006 between. The close's distance from the model doubles in the last three rounds (sd .155 vs .07).

Run: `SOCCER_ROWS_PKL=<path> python3 scripts/research/soccer_nov13/<script>.py` (needs the Understat and injury
caches from /mnt/project-files/soccer/*.tgz in scripts/.cache/soccer).
