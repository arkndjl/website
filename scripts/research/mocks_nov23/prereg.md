# Mock draft driver search, Nov 23 2026: preregistration

Written before any test below was run. Every driver listed here is reported, pass or fail.

## Common rules

- Out of sample: leave one draft out (fit on the other drafts, score the held-out one), as each mock script does.
- Score per row: the model's own loss (below). Paired one-sided t on (base loss - base+driver loss) over all held-out
  rows, p from the normal tail.
- Pass = Holm at .05 across every test in the model's family (list below), gain > 0, and the driver wins more than half
  of the held-out drafts. Only passing drivers ship, and only where the live mock has the input point-in-time.
- Point-in-time: a driver may only use what was public before the board it is added to (awards: the final college
  season's awards, announced Dec-April, so they are tested on boards dated after them: winter and final boards, never
  fall boards). Conviction may use FV-era inputs, still dated before the draft.
- Already tested elsewhere and not redone: team needs (NFL: PR #74/#180/#227/#809, all needs variants; NBA: no
  historical roster/need data), our FV vs consensus gap (NFL: PR #222 model weight .75-.85, shipped; CBB: cbb_mock
  backtest_pred, w = 1.0, model adds nothing), position / class / P5 level / size on final NFL boards (PR #78), the Oct 14
  and Oct 24 FV tests of All-America, Senior Bowl and combine invite (cfb_draft_source_backtest.mjs: FV, not the slot).

## F1 NFL predictive (mock xPick, scripts/cfb_teams.mjs finishPool / BOARD_PICK)

Loss: squared error of ln(pick) (undrafted = 290), top-200 board ranks, K/P/LS out.

Universes:
- **final**: DraftTek final boards 2020-25 (scripts/draft_backtest.py rows). Base = live terms: ln rank, ln rank^2,
  no-combine flag, 40 z (refit in each fold).
- **winter**: PFF's latest board version dated Dec 10 - Feb 28 for each draft 2020-26 (PFF API, cfb_draft_pct_backtest
  cache), declared players (DraftTek final board or drafted). Base = ln rank, ln rank^2 (no combine yet).

Drivers (each added alone to the base):
1. `heis` Heisman voting: in the published voting table of his final college season (Wikipedia FBS season page).
2. `aa` consensus All-American (first team) in his final college season (Wikipedia All-America page).
3. `award` won a national player or position award listed on the season page (Maxwell, Walter Camp, Bednarik,
   Lombardi, Outland, Biletnikoff, Thorpe, Butkus, Doak Walker, Davey O'Brien, Mackey, Nagurski, Rimington, Hendricks,
   Lott, Unitas, etc.).
4. `age` age on draft day (PFF's age field moved to draft day), mean-imputed when missing.
5. `ath` athletic composite beyond the 40 (mean z of speed score, vertical, broad, 3-cone, shuttle; 2+ drills; the
   live fetchCombine composite) - final only.
6. `notest` combine invitee with no drill recorded (medical / skip proxy) - final only.
7. `conf` SEC or Big Ten school (conference strength beyond the failed P5 flag).
8. `disp` board disagreement |ln DraftTek rank - ln PFF final rank| (final only; PFF final = last version before the draft).
9. `move` late board movement: ln(PFF rank on the earlier board) - ln(PFF rank on the later one): winter -> final for
   the final universe, fall (latest Sep-Nov) -> winter for the winter universe; unranked earlier = 300.
10. `grade` PFF final-season grade (grade_1 value), z within position group (production).

Family F1 = 10 final + 8 winter tests = 18 (Holm over 18). Not tested: production trend (PFF's earlier-season grades are
premium-locked; no free college stat history in the container), medical reports (not public), age/class for undrafted
from nflverse (only the drafted carry age there).

## F2 NFL conviction (value beyond the slot)

Universe: nflverse draft picks 2010-21 (careers with 4+ seasons), K/P/LS out. Outcome: w_av (PFR weighted career AV),
centred within the draft. Base: ln pick, ln pick^2, position group dummies. Loss: squared error. Drivers: `heis`, `aa`,
`award`, `age` (nflverse age at draft), `ath`, `forty` (40 z within group), `notest`, `conf`. Family F2 = 8 tests.
Wins needed: 7 of 12 drafts. A passing driver ships to the conviction mock only if FV does not already carry it.

## F3 CBB predictive (scripts/cbb_mock.py pred_order)

Loss: the script's |ln slot - ln real slot| (undrafted 75) after re-ranking each held-out draft's pool by the predicted
ln slot. Base: ln slot = a + b ln consensus rank (re-ranks nothing; equals consensus order).

Universes:
- **final**: ESPN final boards 2017-26 (cbb_mock espnFinal pools).
- **first**: No Ceilings first board of each draft year 2022-26 (Nov-Dec; the backtest_pred pools).

Drivers:
1. `aa` consensus All-American (1st-3rd team) in the final college season - final only.
2. `poy` national POY finalist/winner listed on the season page (Wooden, Naismith, AP, NABC, Oscar Robertson) - final only.
3. `cpoy` conference player of the year (season page) - final only.
4. `age` age on draft day (careers dob; past boards age).
5. `disp` |ln ESPN final - ln NBADraft.net final| (final only; missing on one = 0 with the pool's fill rank).
6. `move` No Ceilings first board -> last version 45+ days out, ln ratio (final only, 2022-26 drafts; 0 elsewhere).
7. `trend` BPM change, final college season minus the one before (0 when one season / international).
8. `hm` high-major conference (ACC, B10, B12, BE, SEC, P12) flag.
9. `comb` combine guard athletic composite (cbb_combine norms; testers only, 0 otherwise) - final only.

On the first board (Nov-Dec, before the season's awards): `age`, `trend` (the two seasons before the board), `hm`, and
`aa_prev` (All-American the season BEFORE the board, the only point-in-time award). Family F3 = 9 final + 4 first = 13.

## F4 CBB conviction (scripts/cbb_mock.py fit_conv)

Base = live kept set (lnpick, bpm3, age), the script's target (career peak XPM, 2017-23 imputed). Add-ons: `aa`, `poy`,
`cpoy`, `trend`, `hm`, `ht` (height), `comb`. Gate as in the script too (LODO RMSE lower, 9+/15 drafts, redraft slot
error not worse) plus Holm over the 7 paired t's.

## F5 hockey predictive (scripts/hockey_mock.py)

Universe: drafted players 2008-26 with a Central Scouting final rank (scripts/data/hockey_rows.json.gz; only picks are
in the committed rows, so this asks where among the drafted a player goes). Base: ln pick on ln CSS rank and its
square by category (NA skater, intl skater, NA goalie, intl goalie). Loss: squared ln pick error. Drivers: `age`
(age on draft day), `ht` height, `nhle` draft-year NHLe (ln), `lg` CHL / USHL-NCAA / Europe dummies, `D` defence flag,
`chl1` CHL priority-selection first-rounder, `trend` ln NHLe growth from the season before. Family F5 = 7 tests,
wins needed 10 of 19 drafts. The live predictive mock reads Tankathon's rank, which has no history: a pass ships only
if the input is on the live board.

## F6 hockey conviction

Conviction = FV (hockey_prospects.py), whose driver search (scripts/hockey_fv_drivers.py) already covers age, height,
weight, league, Central Scouting rank, the season before, CHL priority, NHLe. No new free candidate (junior award lists
are not structured) - not retested.
