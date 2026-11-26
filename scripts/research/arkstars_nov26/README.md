# ARKSTARS top tier, Nov 26 2026: results (prereg.md committed first)

Run: `python3 scripts/research/recruits_cfb_nov16/build.py` (needs nflverse draft_picks.csv + players.csv in
scripts/.cache/statplus), then `cfb_top.py`, `cbb_top.py`, `pack.py` (writes data/arkstars_research.json for Process).

## CFB, family ELITE (top-64 pick on the elite pool, leave one class out 2011-21, 1,292 recruits, 237 hits)
| test | log-loss gain | t (school) | classes | 2022 class | verdict |
| --- | --- | --- | --- | --- | --- |
| E1 industry top end (ln industry rank, rating past 95) | .0066 | 2.22 (p .013, Holm ok) | 9/11 | + .022 | PASS |
| E3 position (QB, line flags) | -.0006 | -0.63 | 5/11 | + .003 | FAIL |

Top-64 rate of the top 3 a class: 79% with E1, 58% index alone, 70% industry rank. Top 6: 55 / 52 / 55%.

## CFB line (even-odds rule)
5-star+ = five-star with held-out P(top 64) >= .5: 5.9 a class, 52% top 64 (90% CI 43-62%), 43% top 32, 74% drafted;
the shipped top 6: 52% (38-65%), 38%, 73%. Plain five-stars 30%. Within one recruit a class of the shipped count, so by
the rule the count stays at about 6, and the tier is now chosen by E1's chance instead of index order. 2022 class: 4 of
4 top-64 (shipped top 6: 5 of 6). Shipped: scripts/cfb_recruit_retarget.py elite_block, scripts/cfb_recruit.mjs idxStars.
History tiers (data/cfb_recruit_retarget.json): 5-star+ 6.4 a class, drafted 79%, top 64 57% (was 76%, 52%).

## CBB
- B3 position (big, point guard) on FV 45+: t -0.92, 4/8, forward -. FAIL.
- Even-odds line: FV 43.5 (3.2 a class), held out 69% FV 45+ vs the shipped FV 41.43 (5 a class) 62%. The rule's
  conditions hold, but the 14 recruits between the two lines hit 50% (forward 2017-20: 3 of 7) and the six-tier
  held-out R2 of realized FV falls .318 -> .297 (a check added after the line result, not in the prereg). A tier that
  drops recruits who are themselves at even odds is not better: line kept at 5 a class, as Nov 16 found.

## Other sports
Hockey, soccer, tennis and CS2 prospect boards have no star tiers or recruiting classes; the only shared input tested
here (position at the top) failed in both sports, so there is nothing to port.

## Look
5-star+ draws in platinum on boards and cards (Noah, Nov 26: platinum over gold): silver to white, stepped pixel shimmer, dark pixel
outline, pale glow, white pixel glint by the plus (static/style.css .cfbrc__glow; assets/js/gfx.js plusStars, which the
card preview animates; saved PNG is the still frame). Reduced-motion users get the still look.
