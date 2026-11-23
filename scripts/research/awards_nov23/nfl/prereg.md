# NFL awards, Nov 23 2026: pre-registration (written before any of these runs)

Engine, gate and data as scripts/awards_research.py / awards_more.py: rank-ordered logit (winner only for AP awards: no
public vote order is free; PFR's voting pages answer 403 from the container), L2 1, leave one season out (2005-25),
held-out log P(winner), one-sided paired t vs the null, Holm at .05 across the NFL's whole list (MVP, OPOY, DPOY, OROY,
DROY already in data/awards_fit.json plus every new p-value below), gain > 0 and most seasons won.
Pools: the ESPN history pool (scripts/awards_football.py build_pool, leaders + every named winner / All-Pro), each
player's ESPN line of the season before (same ESPN id). Everything point-in-time: a feature uses only the award's own
season through the end of the regular season, or earlier seasons.

## New awards

1. CPOY (AP Comeback Player of the Year). Pool: offence (yds >= 400) and defence (tackles >= 30 or sacks >= 4 or
   INT >= 3), as the MVP and DPOY pools together. Winner = first named (2005 co-winners: Bruschi first).
   Model: yds, td, sacks, dint, wp, qb, def, prev_gp (games played the season before, 0 if no line), prev_yds (pass +
   rush + rec yards the season before), prev_def (sacks + INT the season before), prev_ap (AP first-team All-Pro
   selections before the season). Null: yds, td.
2. COY (AP Coach of the Year). Pool: the 32 head coaches (nflverse games: home/away coach, the coach of most games).
   Model: w (wins), dtot (wins - preseason win total, sportsoddshistory / covers closing totals), dprev (wins - last
   season's wins), first (first season with the team), bye (top-2 seed proxy: best or second-best record in the
   conference). Null: w. If no free preseason win totals: dtot dropped and reported blocked.
3. All-Pro (AP first team), one top-k test across six position races, scored as the sum over races of the held-out
   log-likelihood of the named (exploded logit down k slots), per season; one p-value enters Holm.
   Races (pool by ESPN position; named = AP first team from Wikipedia "<year> All-Pro Team", tag AP):
   QB k1 (yds, td, int, wp, prev_ap; null yds, td), RB k1 (scrim, rtd+ctd, rec, wp, prev_ap; null scrim, td),
   WR k2 (rec_y, ctd, rec, wp, prev_ap; null rec_y, ctd), TE k1 (same as WR), FRONT = DL + LB, k = fewest named in a
   season over EDGE + IDL + LB (sacks, tfl, qbh, tackles, ff, dint, wp, prev_ap; null sacks, tackles),
   DB = CB + S, k = fewest named over CB + S (dint, pd, tackles, itd, ff, wp, prev_ap; null dint, pd).
   Shipped (predictive subtab, top-k P(named) per race) only if the joint test passes.

## DPOY retry (the Nov 14 model failed, t .8)

4. DPOY v2: sacks, dint, tfl, pd, ff, wp, + qbh (ESPN QB hits), + drank (team points allowed, rank 1-32, as 33-rank),
   + prev_dpoy (DPOY wins before), + prev_ap (All-Pro first-team before). Null: sacks, dint. Both the Nov 14 p-value and
   this one stay in the Holm list. SVAR has no history before 2026 (data/nfl_season_value.json is this season only), so
   it cannot be a driver.

## Driver add-ons on the passing voter models (MVP, OPOY, OROY, DROY), paired held-out t vs the current model, Holm
## across all add-on tests below at .05, gain > 0, most seasons won

5. MVP + prev_yds (last season's yards, a preseason-profile proxy)
6. MVP + tot (team preseason win total)
7. MVP + prev_ap
8. OPOY + prev_yds
9. OPOY + tot
10. OPOY + prev_ap
11. OROY + pick (draft slot: log of overall pick, undrafted 260; nflverse draft_picks)
12. OROY + tot
13. DROY + pick (log overall pick)
14. DROY + tot

Not testable, reported as such: FV (no point-in-time NFL board history: the NFL board files are this season only),
next-up BO% (data/nfl_breakout_fit.json rows cover WR/TE/RB who have not broken out; there are no stored point-in-time
predictions per past season, and the award winners are mostly players already past the bar), SVAR (2026 only).

## Conviction

P(lead) on SVAR (scripts/awards.py war_lead, data/nfl_qb.json + nfl_season_value.json) for: CPOY (pool = SV players with
fewer than 9 games the season before, from nflverse weekly lines; the season before is finished, so point-in-time),
All-Pro by race (top-k on SVAR: QB, RB, WR, TE, FRONT = DL + LB, DB). COY: coaches have no SV, no conviction view.
