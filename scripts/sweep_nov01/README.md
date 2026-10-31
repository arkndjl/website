Nov 1 2026 team/game model sweep, NFL / NHL / NBA / soccer (thread "Improve NFL, NHL, NBA, soccer team models").
Only untested ideas with new information (earlier sweeps: data/sweep_oct31, style_research, penalty_research, ...).
Bar: tune t <= -1.5, held t <= 0; vs the close reported. Results in data/sweep_nov01/.

SHIPPED
- nfl_practice.py, nfl_practice_games.py: a questionable non-QB priced by his last practice (nfl_games.PRACTICE_Q).
  Player level (2016-20 rates, 2021-25 held): plays 45% after no practice, 77% limited, 93% full (held 52/76/84%);
  Brier .2080 vs .2202 flat, t -5.8. Game model MAE 2017-20 -.010 (t -1.25), 2021-25 -.004 (t -0.74); the change
  predicts result minus the close (b 2.3, t 1.6 / b 3.7, t 2.5). Refit inj 1.36 -> 1.44; held NFL spread picks CLV
  return +9.6% -> +10.3% (rules unchanged: spread X 4, total X 1.5).

FAILED (don't redo)
- soccer_ou.py: closing O/U 2.5 joined to the 1X2 in the market-goals solve (w .5-8): held LL .96253 -> .96292+.
- soccer_second_legs.py: first-leg aggregate in UEFA second legs (lin / decided tie): tune t -0.5, held -0.7; no pattern.
- nhl_lineup_adj.py: xG / goals / Elo updates cleaned of each side's lineup deviation (NBA lk_opp twin), lk .5-1.5:
  worse both splits (tune t +0.4 to +1.2, held +1.7 to +1.8).
- nba_incentive.py: eliminated / bottom-five / either, late season: vs model tune -1.2 / -0.3 / -1.1 (held -2.5 / -2.4
  / -3.0, held-only again); vs close tune +1.0 / +0.3 / +0.9.
- nba_inj_reason.py: questionable players by the official report's reason (sore, sprain, strain, illness, rest, ...):
  play rates flat .71-.81 and unstable between splits; held Brier worse (t +0.7).
- nfl_stakes.py: late-season out / clinched / top seed locked: n ~100 a split, tune t -0.5 to +1.6, held -0.7 to +0.6.
