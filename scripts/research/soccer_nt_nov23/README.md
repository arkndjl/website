# Soccer prospect FV: national team play (Nov 23 2026), result: nothing shipped

Prereg: prereg.md (blob 4fe0f733, written before scoring). Run: `python3 scripts/research/soccer_nt_nov23/nt_research.py`
after the soccer prospects rebuild + `soccer_prospect_data.py games <senior NTC + youth comps> --seasons 2010-2026`.
Nation strength: nation_strength.py (soccer_intl goal ratings, value strictly before the match day).

Oct 24 snapshot, 49,246 rows 2013-20, cohort-out vs the board's kept OLS inputs (base MSE 54.61):

| cand | t | folds | top-50 MSE | fwd MSE | fwd top-50 MSE | fwd top-50 outcome | verdict |
|---|---|---|---|---|---|---|---|
| snt_opp senior mins x opp strength | 0.12 | 5/8 | -0.45 | -0.012 | -0.79 | -0.32 | fail CV |
| snt_own senior mins x own nation | 0.24 | 5/8 | -0.44 | -0.011 | -0.99 | -0.36 | fail CV |
| snt_ga senior G+A x opp, shrunk | -0.22 | 5/8 | -0.31 | -0.018 | -0.45 | -0.36 | fail CV |
| snt_comp competitive only | 0.57 | 4/8 | -0.44 | -0.003 | -0.90 | -0.41 | fail CV |
| snt_sh12 share of nation's mins, 12 mo x own | 0.42 | 5/8 | -0.22 | -0.024 | -0.73 | +0.22 | fail CV |
| yi_opp youth mins x opp x level | 7.51 | 8/8 | +0.42 | -0.176 | +3.60 | -0.32 | fail top |
| yi_ga youth G+A x opp, shrunk | 1.93 | 6/8 | +1.48 | -0.328 | +2.49 | -0.21 | fail |
| nt_all senior + youth opp-weighted | 6.71 | 8/8 | -0.66 | -0.189 | +1.19 | +0.12 | fail fwd top |

Jan 15 snapshot: same pattern (yi_opp t 6.2, nt_all t 6.0; top-50 outcome -0.23 / -0.25, fwd top-50 -0.21 / -0.34).

Reading: senior national team play adds nothing once market value, club minutes and club strength are in (value
already prices a cap; Oct 31 raw caps failed the same way). Opponent-weighted youth play is the strongest body-of-board
signal found for soccer prospects (t 7.5) but, like every youth-intl term since Oct 24, it misranks the top forward:
the players it lifts are ones the market and club minutes already sort. Not shipped.

Victor Froholdt (Porto, Denmark, 13 senior caps / 860 min, U17+U19): the senior terms would add +0.6 to +1.0 raw OLS
FV, nt_all +2.5 raw OLS (about +1 on the blended headline). Board FV stays 59.

Cross-sport: nothing passed, so no port is owed. Analogues already failed: hockey WJC/U18 before the draft (Oct 24),
CBB FIBA youth production (Nov 3). Lead (not retested now): nt_all forward top-50 when 2021-22 classes mature.
