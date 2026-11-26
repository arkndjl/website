# BPM to XPM swaps, CBB (Nov 26 2026)

Every model outside FV and the game model that read BPM, xBPM, GBPM or 3-season BPM, tested with rXPM (descriptive slots)
and pXPM (predictive slots) in its own held-out protocol. Point-in-time values come from `scripts/cbb_xpm_hist.py`
(pXPM ridge refit walking forward, so a season's pXPM never sees later seasons). Pass rule: paired t >= 2, most folds won,
guard metrics no worse. Ties stay as they were.

| consumer | swap | result | file | shipped |
|---|---|---|---|---|
| Next (next-season value), roster row | pXPM board form for last-season BPM | RMSE 30.17 -> 29.19, t 22.0, 11/11 | next.json | yes |
| Next, value inputs and target | rXPM for BPM | t 4.9, 11/11 | next.json | yes (target is VORX) |
| Next, in-season grid | pXPM board form for 3-season BPM | t 13.1 to 25.6 at every share, 11/11 | next_inseason.json | yes |
| Next up (breakout odds) | pXPM gap added | Brier .20772 -> .20500, t 5.1, 16/16 | breakout.json | yes |
| Transfer% | pXPM board form for BPM | log loss .8999 -> .8862, AUC .710 -> .725, t 6.5 | market.json | yes |
| Transfer% | rXPM for BPM | t -5.1 | market.json | no |
| Landing spot | pXPM board form for BPM | top 10 15.1% -> 16.4%, t 6.0 | market.json | yes |
| Depth chart / backup watch grade | pXPM for last season's BPM | t 45 to 64, 12/12 | backup.json | yes |
| xBPM (returners) | pXPM board form added, rXPM target (xXPM) | whole-roster team R2 .7718 -> .7768, t 7.8, 14/14 | xxpm.json | pending (cbb_fit.py) |
| xBPM (newcomers) | rXPM target | tie (t 1.9 on rXPM, -5.4 on BPM) | xxpm.json | follows the rename |
| Award voter models (10 awards) | rXPM for BPM | t -1.48 to .36 | awards.json | no; conviction and shown stats on XPM |
| Ret% | rXPM / pXPM for BPM | t -.19 / .75 | declare.json | no |
| NBA mock conviction | pXPM board form for 3-season BPM | t -1.44, 2/15 | mock.json | no |
| NBA mock conviction | 3-season rXPM for 3-season BPM | t 2.21, 12/15, slot error .5684 -> .5706 (guard) | mock.json | no |
| School development outcome | rXPM for BPM | rolling gain 2.50% -> 2.04%, reliability .459 -> .409 | school_dev.json | no |
| NBA next up (cross-sport) | pXPM gap added | t 1.42, 9/16 | nba_breakout.json | no |
| CBB WAR, all-time list | renamed VORX, on rXPM | same formula as before; era gate passes | scripts/alltime.py | yes |

Not tested here: FV drivers, roster prior, game model, tourney odds (the FV thread); NHL / CFB next up with a projection-gap
term of this kind; low-division and recruit path targets (the target is a definition, the fit would only be rescaled).
