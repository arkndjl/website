# Results (Nov 18 2026)

| Board | No-playing-time path | Fit on | Finding |
|---|---|---|---|
| CBB | cbb_live.prov_fit (unboarded players) | board grade of 2,721 low-information board players (1,978 unranked newcomers, 743 returners under 10% of minutes; 0 rows with missing minutes; no position cells) | 58 players, all 20-22 FV. Clean. Data fix: ESPN box-score lines carry no height, so all 58 showed 6-5; now ESPN's roster height |
| CBB | preseason newcomers | NBA outcomes (cbb_fit) | unranked newcomers grade 23 -> headline 20. Clean |
| NFL | nfl_rookie_prior | rookie WAR rate on ln(pick) by group, 2016-25, n 3,648 (QB 109 the smallest), season-out t -3.15 | outcome-based. Clean (no FV on the pro boards) |
| NBA | nba_games newcomer_level, college_curve | realized first-season XPM | outcome-based. Clean |
| NHL | newcomers at replacement | tested Oct 29 (PR #562) | Clean |
| Hockey prospects | hockey_provisional | 8,608 off-board CHL eligibles 2008-19, realized FV; bands 20/22/24: pred 20.5/22.7/24.7 vs real 20.3/23.1/25.0 | 106 shown, 22-24 FV. Clean. Zero-GP board players take the NHLe expected at their rank |
| Soccer prospects | provLine2 (academy-only), yiLine (youth internationals only) | realized FV, 38,150 and 22,054 rows, slopes .72 and .54 (the Oct 31 fix for "runs hot") | 185 zero-minute players, all provisional, mean 31 on a top-2,000 board. Clean |
| Tennis | unranked = provisional, same hurdle model with `unr` | peak value, births 1979-97 | tested here (tennis_unranked.json): unranked pred 20.32 vs real 20.30 (ATP), 20.44 vs 20.44 (WTA); idle and high-Elo cells not high (WTA Elo 1800+ reads 2.8 low, t -1.98, n 69). Candidates unr x elo, idle flag: fail the gate. No change |
| CS2 | 1,000+ rounds required; missing birth date scored as age 22 | next-year rating, walk-forward | missing-age flag: held MSE .8122 -> .8164, t +1.21. Fails. No change |
