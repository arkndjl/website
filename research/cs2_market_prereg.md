# CS2: market closes in the CS2 models (pre-registration)

Written before any held score below was read. Data: CS2Odds results-by-day pages (per-book last pre-start price,
seen time, result) and match pages (per-book opening price), Sep 19 2026 on. Script: scripts/cs2_market_research.py
-> data/cs2_market_research.json. Lockbox: nothing dated Nov 11 2026 or later is read (Valve series rows already end
~Nov 1 through the snapshot lag).

Base = the live four-term series model (player Elo, VRS points, team map rating, five's RWA), weights by tier fit on
the tune window (Aug 2024 - Jun 2025), as in scripts/cs2_nov13_research.py. Consensus close = mean de-vigged logit
over books seen <= 2 h before the start. Market features use only series on earlier UTC days.

Scoring: rows = Valve series Oct 1 - Nov 10 2026 (Sep 19-30 = burn-in for the features). Each extra term is one
second-stage coefficient on top of the base logit, fit leave-one-day-out; paired log-loss difference vs base, t over
days. Pass = Holm over the family at one-sided .025 on that t, and top-50 rows no worse (mean d <= 0).

Family (Holm over 5):
- H1 market residual (team term): per team, decayed mean of (close logit - base logit) from that team's side over its
  earlier joined series, half-life 30 days, shrunk n / (n + 5); term = resA - resB.
- H2 market rating (ARK-style): ridge Bradley-Terry fit on all earlier consensus closes (logit = rA - rB, decay
  half-life 30 days, ridge 1), refit per day; term = rA - rB.
- H3 newcomer prior: H1 only where either team has under 30 Valve series before the row (term zero elsewhere).
- H4 shown chance outside Thunderpick: on series with no Thunderpick close, chance = a x base logit + b x consensus
  logit of books seen 2-48 h before start (a stand-in for the price a 4-hourly build sees); vs base alone. Rows: all
  joined series Sep 19 - Nov 10 (no feature burn-in needed), LODO, t over days. (Not a model term: display blend like
  the Thunderpick one.)
- H5 picks (CLV): slope k of (close logit - opening logit) on (base logit - opening logit), consensus of books with
  both prices; pass = k > 0 with t over days >= 2 (equivalently one-sided .025 after Holm). A pass only opens paper
  picks work; a fail keeps CS2 picks off.

Not tested, and why: player ratings / RWA (a team-level price cannot be split across players without a lineup-level
market); map and round totals (the site shows no CS2 totals; one market, two books); ARK Ranking itself is the base
model's rating and changes only if H1/H2 ship.

## Round 2 (written before any score below was read)

Same data, rows, features and scoring as above (held Valve series Oct 1 - Nov 10 2026, leave-one-day-out, t over
days, one-sided .025). Family of 4, Holm. Script: `scripts/cs2_market_research.py --round2` -> `round2` in
data/cs2_market_research.json.

- S1 stack residual: base + H2 + H1 vs base + H2 (all rows). Pass adds the H1 term to the live chance.
- S2 stack newcomer: base + H2 + H3 vs base + H2 (all rows).
- A1 ARK Ranking: base + H2 vs base on rows where both teams have 15+ earlier Valve series (the ranking's own
  eligibility count). Pass = the ARK (Bo3 chance vs the top 20) is computed on the market-rated logit.
- P1 Pick'Em and Major event odds: base + H2 vs base on rows where both teams are VRS top 50 (a Major field is drawn
  from them). No Major stage falls inside the data window (Sep 19 - Nov 10 2026), so P(5+) itself cannot be scored;
  this series-level test is the only evidence. Pass = Pick'Em and event odds simulate on the market-rated logit.
