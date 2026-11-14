# Soccer leads, Nov 14 2026

Prereg and results: /mnt/project-files/leads-nov14/soccer/ (prereg.md, results.md, the result JSONs).

| Script | Test | Result |
|---|---|---|
| intl_squads_pull.py, s1_intl.py, intl_squads_freeze.py | S1 called-up squads in the national-team model | held 2016 to Jul 2026 .85898 -> .85676, t -3.09 by match day: shipped (soccer_intl.py sqc .24, sqr .04) |
| s2_snaps.py, s2_xmv.py | S2 top-GAR hinge x age in the xMV log fit | 60m+ band +.0019 log MSE, t +0.49: failed |
| gsxg.py, s3_games.py | S3-i game-state xG in the club game model | held +.00016, t +1.32: failed |
| gsxg.py, s3_gar.py | S3-ii game-state npxG / xA in GAR | nested LOSO -.0002, t -0.48: failed |

Caches: untar /mnt/project-files/soccer/{understat_cache,tminj_cache}.tgz into scripts/.cache/soccer; the
Transfermarkt dump into scripts/.cache/soccer_prospects/dump; the squad pull writes scripts/.cache/soccer/intl/tm.
