# Pre-registration: injury projections and game models (Nov 14 2026)

Written before any of these tests was run. Lockbox rule holds: no 2026-27 basketball outcome, and no NFL/CFB 2026
game from week 11 on, is read by any fit, choice or score here.

## Splits

| sport | tune | held |
|---|---|---|
| NFL | 2016-20 | 2021-25 (regular season; 2026 not read) |
| NBA | seasons ending 2020-22 | seasons ending 2023-26 |
| CFB games | 2017-20 | 2021-26, 2026 weeks 1-10 only |
| CFB statuses | 2026 games through Oct 3 | 2026 games Oct 4 to week 10 |

Every model is fit on tune only and scored once on held. Scores are paired per row against the base, t clustered
(NFL season-week, NBA and CFB game day), one-sided. Holm at .05 inside each family.

## Family J: availability and return timelines (player level, log loss; 5 tests)

Probabilities clipped to [.005, .995]. Logistic models are ridge on standardized inputs, penalty from
{0.3, 1, 3, 10, 30} by leave-one-season-out on tune.

- **J1 NFL questionable.** Rows: non-QBs listed Questionable on the final report, regular season. Base: the live
  table, last practice (dnp / limited / full / none) x played the team's last game, refit on tune. Candidate:
  logistic on the base cells plus position group (OL, WR/TE, RB, DL, LB, DB, specialist), body-part group
  (nfl_inj_hazard.PARTS on report_primary_injury), last week's listing (not listed / Q and played / Q and sat /
  D or Out), team games missed in a row before this one (0, 1, 2+), the club's share of its Questionables who
  played earlier that season (shrunk to the league rate with 20 pseudo-listings), short week (5 or fewer days since
  the club's last game), the player's snap share in his last four games played, and the club's count of
  Questionables that week.
- **J2 NFL return timeline.** Rows: nfl_inj_hazard.episodes (Questionable, Doubtful, Out each week listed; Reserve)
  followed for the club's next four games, outcome missed game j. Reserve rows are taken at every week on the list,
  not only the week of the move, since live applies the curve every week. Base: the live table, P(miss j | status).
  Candidate: P(miss j | status, games missed in a row before this week 0 / 1 / 2-3 / 4+, last practice), each cell
  shrunk to its parent with 40 pseudo-episodes; Reserve by weeks on the list (0, 1-3, 4-7, 8+, on it since before
  week 1).
- **J3 NBA play chance.** Rows: rotation players (8+ role minutes) in games with an official report, weighted by
  role minutes as the live table is. Base: live rule, status x missed-streak bucket table (with the night-two
  multipliers for unlisted players), refit on tune. Candidate: logistic on status x streak bucket plus night two x
  age/role group, role minutes, age, home, days since the club's last game, the club's season-to-date play share at
  that status (shrunk, 20 pseudo-rows), the player's own share of club games played this season (shrunk to .85
  with 10 games), his status and outcome at the club's previous game, season progress (club game number / 82),
  and club win share after game 55 (0 before). Injury reason is not an input (failed Nov 1).
- **J4 NBA report trajectory.** Same rows, listed players only (Questionable, Doubtful, Probable). Base: the J3
  candidate. Candidate: J3 plus the player's status on the last report of the previous day (not listed / not yet
  submitted / Out / Doubtful / Questionable / Probable / Available), crossed with tonight's status.
- **J5 CFB news statuses.** Rows: FBS offensive skill players with a RotoWire item read as Questionable, Doubtful,
  Probable or Out by the board's reader, newest item before kickoff and after the club's previous game; outcome =
  in the ESPN box score. Base: live rates (data/cfb_avail_fit.json status, as of Oct 14). Candidate: rate by status
  x missed the club's last game, beta-binomial on the live rate with 10 pseudo-listings, fit on the tune dates.

## Family G: game models (absolute error of the margin on lined games; 5 tests)

- **G1 NFL injury term priced with J1.** Run only if J1 passes. Same input, new probabilities; live walk-forward.
- **G2 NBA lineup term priced with J3 (and J4 if it passes).** Run only if J3 passes.
- **G3 NFL later weeks carried with J2.** Run only if J2 passes: nfl_inj_hazard's gameTest (games one to four weeks
  after the report), new table against the live table.
- **G4 CFB market disagreement.** d_team starts at 0 each season; after each lined game e = (close - m) -
  (d_home - d_away) and both sides move 0.2 x e (the CBB setting, not tuned). Input d_home - d_away added to the
  committed walk-forward margin m with a weight fit on the seasons before each season.
- **G5 NFL game control.** Per game, the time-weighted mean of Phi(lead / (13.5 x sqrt(share of game left))) from
  nflverse play-by-play, home side; rating = ridge Massey of probit(control) with home (penalty 2 games, last
  season's rating carried at .5 as the prior), walked game by game; input = rating gap, added to the live inputs.

Pass rules. G1-G3 reprice an input whose calibration passed at the player level: they ship if the game error is not
worse on either split (paired t below +1.0 on both), with the t's reported (the PRACTICE_Q precedent of Nov 1).
G4 and G5 are new inputs: tune t <= -1.5 and held p under Holm across the family's tests that were run.

Shipping. J passes replace the live rates. Any change to a game model's margins reruns its fit, the walk-forward
file and the pick rules. Each shipped item is registered for one season-end lockbox score.

Not tested, and why: CBB (every open lead is season-gated on 2026-27); NBA team terms (the Nov 13 audit closed
the linear terms; no new data source since); terms listed as failed in the project notes.
