# Results: expert track-record weighting of On3/Rivals picks (Nov 19 2026)

Prereg: prereg.md. Tests: expert_tests.py -> expert_tests.json. CFB LIST model, walk-forward 2018-26, as of the On3
commitment date - 30 days. n 16,934 recruits; recruits with as-of picks by class: 2023 56, 2024 79, 2025 148, 2026 159.

## Track records (every finished class)
1,004 resolved as-of picks, 78 experts, pooled hit rate .643. 12 experts with 20+ picks: hit rates .30-.77.
Spread across those 12: SD .124 observed vs .083 binomial noise (true SD about .09), but it does not repeat:
split-half (classes <= 2024 vs 2025-26, experts with 10+ picks in both) r = -.13, n 5.

## Tests (k = 10)
| test | gain / recruit | t | classes + | result |
|---|---|---|---|---|
| A swap esh -> esha | -.00001 | -0.42 | 1/4 | fail |
| B add esha on top of esh | -.00078 | -2.55 | 0/4 | fail |

Top-1 32.33% in all three; the hot >= .8 tail is unchanged (.944 predicted -> .72 hit).
Gate classes ran 2023-26 (2023 has a record from the 2021-22 picks); on 2024-26 alone A is 1/3, still a fail.
Sensitivity (not gates): k 5 A t -0.46, B t -2.52; k 25 A t -0.38, B t -1.99.

## Verdict
Equal weights stay. With about 1,000 resolved picks the expert-to-expert differences are mostly noise; the
confidence-weighted share already carries the signal. Retest after the 2027 and 2028 classes sign (picks roughly
double), same prereg.

## Sources
On3/Rivals picks: on3.com (robots.txt allows; rivals.com blocks ClaudeBot / anthropic-ai / Claude-Web, not fetched).
247 Crystal Ball: robots.txt allows, but the bot wall blocks plain requests; not bypassed. Google News RSS carries
about 40 Crystal Ball headlines a month (`intitle:"crystal ball" site:247sports.com`), mostly without the pick or
expert. CFBD carries 247 rankings only. No free X read API; 247 main Bluesky account suspended.

## 247 Crystal Ball headlines as a model input (Nov 19, not testable)
Backfill Jan 2023 - Nov 2026 (Google News, `intitle:"crystal ball" site:247sports.com` and `intitle:"crystal ball" 247Sports`,
14-day windows, 8 windows lost to 429s): 451 distinct headlines. 219 player pages ("X's Crystal Ball Predictions",
"Where will X commit to?": the player, never the school or expert), 52 team pages (school, no player), 52 articles
that name a school, of which about 16 name both a high school recruit and the school (3.5%); 6 of those 16 already
have On3 picks in the model. 16 recruits over four classes cannot carry a walk-forward test (the E family needed 442
pick recruits for t 12.5), so headlines ship as alerts only (recruit_news.py k "cb"), not as a lean input.
