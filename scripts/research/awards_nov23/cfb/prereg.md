# CFB awards, Nov 23 2026: pre-registration (written before any of these runs)

Engine, gate and data as scripts/awards_research.py: rank-ordered logit (Heisman depth 3 on the vote order, the rest
winner only), L2 1, leave one season out, held-out log P(winner), one-sided paired t vs the null, Holm at .05 across the
CFB's whole list (the 13 races in data/awards_fit.json plus every new p-value below), gain > 0 and most seasons won.
Pool: ESPN history (scripts/awards_football.py build_pool). Point-in-time: end of the regular season or earlier only.

New team / profile features (all point-in-time):
- p5: team in a power conference that season (ESPN group of the team-season; ACC, Big 12, Big East to 2012, Big Ten,
  Pac-12 to 2023, SEC, plus Notre Dame)
- ap_end: AP poll after the last regular-season week (ESPN core rankings, type 2 last week), (26 - rank) / 25, 0 unranked
- ap_pre: preseason AP poll (week 1), same scale
- fv_pre: the player's FV at the end of the season before (scripts/data/cfb_alltime_rows.json.gz, the board graded at
  each season's end under the shipped weights; 2014 rows = the 2015 preseason, so seasons 2015-25 only), joined by
  name + team + position through scripts/names.py (exact name across teams for transfers); missing = 20 and fv_na = 1
- stars: recruiting stars on that alltime row (0 = missing)
- sr: ESPN experience 4+ years (senior)

## New awards

1. Unitas Golden Arm (senior QB): pool QB, pass_y >= 1000, sr. Model = O'Brien's (pass_y, ptd, int, ypa, rush_y, wp);
   null pass_y, ptd.
2. Paul Hornung (most versatile, 2010-25): pool apy (rush + rec + kick/punt return yards) >= 500 or two-way (100+
   offensive yards and 10+ tackles or 1+ INT). Model: apy, ret_y, two_way, td, wp; null apy, td.
3. Lombardi (lineman / LB): pool DL + LB (ESPN position DE, DT, NT, DL, LB, ILB, OLB, MLB). Model = Bednarik's (sacks,
   dint, tfl, pd, tackles, ff, wp); null sacks, tfl. Winners outside the pool (OL, and 2017+ when it opened to every
   position: Bryce Love, Burrow, Ugo Amadi) drop their season.
Not modelled, why:
- Outland (interior linemen): 14 of 21 winners 2005-25 are offensive linemen, who have no free box stats.
- Rimington (centers): no stats at all for centers.
- Broyles (assistant coaches): no free coordinator-by-team history joined to unit results.
- Burlsworth (former walk-ons): walk-on status is not in any free structured source, so the eligible pool is unknown.
- Wuerffel (community service): not a performance award; nothing to model.

## Retries of the failing races (Doak, Biletnikoff, Mackey, Bednarik, Nagurski, Butkus, Thorpe, Groza)

4-11. v2 of each = its Nov 14 model + p5 + ap_end + prev_top5 (top-5 Heisman vote the season before). Same pool,
   null, seasons 2005-25. The Nov 14 p-values stay in the Holm list; the v2 p-values join it.

## Driver add-ons (paired held-out t vs the current model, Holm across all of these at .05, gain > 0, most seasons won)

On Heisman, Maxwell, Walter Camp, O'Brien (passing), each with:
12-15. + p5        16-19. + ap_end      20-23. + ap_pre
24-27. + fv_pre, fv_na (2015-25: the current model refit on the same seasons is the base)
28-31. + stars (2015-25, same base)

Not testable, reported: next-up BO% (data/cfb_breakout_fit.json is PFN 2019-26; no stored point-in-time predictions
per player and season, and the PFN season cache is not in the repo, so at most six seasons, 2020-25, could be rebuilt);
draft slot (no draft before college awards).

## Awards -> FV (Noah: "projected Heisman finalist")

32. drv_heis = held-out P(Heisman top 4) = P(in the top four of a Plackett-Luce draw from the Heisman voter model's
    utilities) for the player's season, from the model fit leaving that season out. The Heisman model's columns
    (yds, td, int, wp, qb, def, prev_top5) hold no FV, so no circularity.
33. drv_pos = held-out P(win) of his position award (O'Brien QB, Doak RB, Biletnikoff WR, Mackey TE, Nagurski
    EDGE/DL/LB), current Nov 14 model columns (no FV), leaving that season out.
Test on scripts/data/cfb_alltime_rows.json.gz last-season rows (final), drafts 2015-23 (matured outcomes), outcome
NFL AV a season (av) and draft capital (pick -> the board's AV a slot is not in the rows, so -log(pick), undrafted
log(300)). Candidate grade fm' = fm + w * logit-scaled driver, w fit by least squares inside the training classes
(leave one draft class out). Score per held-out class: within-position Pearson r of fm' with AV (mean over positions).
Pass: one-sided paired t over classes > Holm threshold (2 tests), gain > 0, most classes won, and the top 32 of each
class by fm' not worse in mean AV than by fm (the gate the Oct 31 all-conference test failed).
Ship only if it passes: then the term goes into scripts/fetch_cfb.mjs and the board is rebuilt the way the repo does.
