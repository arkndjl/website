# ARK reference

Snapshot of this repository at commit `d87841f` (2026-11-16). Numbers quoted from `data/*.json` change when a model
refits; the file named next to each number is the source of truth. Method write-ups for every term live on the
Reference page ([/arkboard/reference/](https://arkndjl.net/arkboard/reference/), built from
[`data/library.json`](../data/library.json) by [`scripts/library_build.py`](../scripts/library_build.py)).

Use of the site's data is governed by [`/terms/`](../content/terms.md) and [`LICENSE`](../LICENSE): no license is
granted, and scraping or automated collection needs written permission (see section 5).

## 1. "ARKDATA"

Nothing in the repository is named ARKDATA: no file, script, workflow, page, issue or pull request uses the word.
This section covers what the name most likely means: the data pipeline and models behind ARKBOARD.

### Game models by sport

| Sport | Builder | Output file | Outputs | Main inputs | Refresh (UTC) |
| --- | --- | --- | --- | --- | --- |
| College football | [`cfb_model.mjs`](../scripts/cfb_model.mjs), [`cfb_teams.mjs`](../scripts/cfb_teams.mjs) via [`fetch_cfb.mjs`](../scripts/fetch_cfb.mjs) | [`cfb_games.json`](../data/cfb_games.json), [`cfb_model.json`](../data/cfb_model.json), [`cfb_rank.json`](../data/cfb_rank.json), [`cfb_cfp.json`](../data/cfb_cfp.json) | spread, pHome, total, projected score, cover/over chance; 10,000-season sim (projW, ccg, title, cfp, bye, semi, natl, seed); CFP odds; ARK Ranking | Elo + opponent-adjusted EPA/play (ridge toward a preseason prior: SP+, 247 talent, returning production, transfers); home, rest, travel, altitude; QB swap; injuries | [`cfb-board.yml`](../.github/workflows/cfb-board.yml), several runs a day Aug-Jan |
| NFL | [`nfl_games.py`](../scripts/nfl_games.py) | [`nfl_games.json`](../data/nfl_games.json) | margin, pHome, total, hs/as, cover/over; `power[]` with rating, wins, playoff, div, seed1, conf, sb, rank range; 10,000 sims | terms `elo, qb, rest, home, inj, mkt, ret, ir`; totals `pts, dome, one, epa, tmkt` | [`nfl.yml`](../.github/workflows/nfl.yml), ~3x daily + Sunday windows, Sep-Feb |
| College basketball | [`cbb_games.py`](../scripts/cbb_games.py), [`cbb_games_live.py`](../scripts/cbb_games_live.py) | [`cbb_games.json`](../data/cbb_games.json) | margin, pHome, total, poss, edge; `power[]` with xW, title, NCAA `nc{bid, seed, r32 … champ}`; 5,000 sims | terms `eff, elo, home, gc, inj, confh, hatt, bpi, pinj, mdis` | [`cbb-board.yml`](../.github/workflows/cbb-board.yml), 3x daily Nov-Apr; injuries re-priced on each odds snapshot |
| NBA | [`nba_games.py`](../scripts/nba_games.py), [`nba_games_build.py`](../scripts/nba_games_build.py) | [`nba_games.json`](../data/nba_games.json) | margin, pHome, total, cover/over, injuries; season sims (10,000) | terms `elo, eff, mkt, lin, rest, b2b, home` (lin = lineup value: XPM x minutes x P(plays)) | [`nba-xpm.yml`](../.github/workflows/nba-xpm.yml), 2x daily in season |
| NHL | [`nhl_games.py`](../scripts/nhl_games.py) | [`nhl_games.json`](../data/nhl_games.json) | pHome, margin, total, puck line `pl`, `pOT`, fair odds, goalie; season sims (10,000) | logistic on `elo, xg, b2b, home, rv` (rv = lineup value); totals `xgT, gT, mtot, gkT` | [`nhl.yml`](../.github/workflows/nhl.yml), 2x daily Oct-Jun; goalies every 30 min |
| Soccer (clubs) | [`soccer_games.py`](../scripts/soccer_games.py) | [`soccer_games.json`](../data/soccer_games.json) | 1X2, projected score, over 2.5, both score; league and UEFA sims (10,000) | Poisson attack/defence per league, cross-league strength, xG (Understat, FotMob), market goals, squad value; Dixon-Coles rho -.04 | [`soccer.yml`](../.github/workflows/soccer.yml), 2x daily |
| National teams | [`soccer_intl.py`](../scripts/soccer_intl.py) | [`soccer_intl.json`](../data/soccer_intl.json) | 1X2 at 90 min, over 2.5, both score, Nations League sims | attack/defence from every international since 1872, Transfermarkt squad value, called-up squads | [`soccer-intl.yml`](../.github/workflows/soccer-intl.yml), 2x daily |
| Tennis | [`tennis_model.py`](../scripts/tennis_model.py) | [`tennis.json`](../data/tennis.json), [`tennis_events.json`](../data/tennis_events.json) | match `p`, fair odds; event odds per round (10,000 draw sims) | surface Elo, games-won rating, serve/return point ratings, match context | [`tennis.yml`](../.github/workflows/tennis.yml), 2x daily Jan-Nov |
| CS2 | [`cs2_model.py`](../scripts/cs2_model.py) | [`cs2.json`](../data/cs2.json) | series `pa`, fair odds, veto, ARK Ranking, event odds, Major Pick'Em | player Elo by map, region offsets, team map rating, Valve VRS, five-player RWA | [`cs2.yml`](../.github/workflows/cs2.yml), every 4 h |
| ESEA (1NT) | [`fetch_esea.mjs`](../scripts/fetch_esea.mjs) | [`esea.json`](../data/esea.json), [`esea_rwa.json`](../data/esea_rwa.json) | match preview win chance, pick/ban tree, season sim | FACEIT elo + talent, RWA gap of expected lineups | [`esea.yml`](../.github/workflows/esea.yml), every 20 min |
| College baseball / MLB draft | none | page content | hand-graded FV | n/a | by hand |

Refits: [`scripts/refit.py`](../scripts/refit.py) via [`model-refits.yml`](../.github/workflows/model-refits.yml)
(Mondays 06:05), each job on its own months and interval; status in [`data/refits.json`](../data/refits.json).
Odds snapshots every 30 min 13:00-04:00 plus 08:00 and 11:00 ([`odds-snap.yml`](../.github/workflows/odds-snap.yml),
started by the Cloudflare Worker in [`ops/odds-cron/`](../ops/odds-cron/worker.js)); picks refresh every 2 h
([`picks-refresh.yml`](../.github/workflows/picks-refresh.yml)). Staleness rules per feed:
[`data/freshness.json`](../data/freshness.json) (in season stale past 36 h), checked every 3 h by
[`scripts/data_health.py`](../scripts/data_health.py), which opens a GitHub issue per stale sport.

### Player models (headline outputs)

| Output | Sports | Source |
| --- | --- | --- |
| FV, 20-80 mean-outcome grade, tier odds | CFB, CBB, hockey, soccer and tennis prospects, CS2 | [`fetch_cfb.mjs`](../scripts/fetch_cfb.mjs), [`fetch_cbb.py`](../scripts/fetch_cbb.py), [`data/hockey.json`](../data/hockey.json), [`data/soccer_prospects.json`](../data/soccer_prospects.json), [`data/tennis_prospects.json`](../data/tennis_prospects.json) |
| WAR / WAA, rate (pXP/60) | NFL, CFB | [`nfl_war.py`](../scripts/nfl_war.py), [`cfb_av.mjs`](../scripts/cfb_av.mjs) |
| rXPM / pXPM / VORX, 1Y/3Y | NBA | [`nba_xpm.py`](../scripts/nba_xpm.py), [`nba_proj.py`](../scripts/nba_proj.py) |
| WAR / pWAR, GAR/60 | NHL | [`data/nhl_war.json`](../data/nhl_war.json) |
| GAR, p/90, xMV | soccer | [`data/soccer_war.json`](../data/soccer_war.json) |
| RWA | CS2, ESEA | [`data/cs2_players.json`](../data/cs2_players.json), [`data/esea_rwa.json`](../data/esea_rwa.json) |
| Fantasy stat lines, week and rest of season (std, half, PPR, K, DST) | NFL | [`nfl_fantasy.py`](../scripts/nfl_fantasy.py) |

### Known limits

- No game model beats the closing market on held-out seasons (table in section 4). Projections are priced as a
  second opinion, not a replacement for the close.
- Live monitors ([`data/model_monitor/`](../data/model_monitor/)), 2026-11-16: NBA `alarm` (197 games, MAE 11.64 vs
  10.20 expected, line 11.18) and CS2 `alarm` (93 series); CBB `watch`; others `ok`.
- NHL win chances run hot in the favourite bins (held-out 70% bin won 66.5%,
  [`nhl_games_fit.json`](../data/nhl_games_fit.json) `calib`).
- Stored basketball closes change source at 2025, so older seasons flatter basketball rules
  ([`scripts/games_picks.py`](../scripts/games_picks.py)).
- The 2026-27 seasons (NFL/CFB from 2026 week 11) are a lockbox: scored once at season end, never tuned on
  (e.g. [`scripts/research/nfl_nov13/PREREG.md`](../scripts/research/nfl_nov13/PREREG.md)).
- Source fragility: Barttorvik blocks GitHub Actions (ESPN fallback), Understat falls back to cache when down or slow ([`soccer_data.py`](../scripts/soccer_data.py)), CFBD is
  capped at 1,000 calls a month. A failed fetch keeps the last good file and opens an issue (open now:
  [#956](https://github.com/arkndjl/website/issues/956), soccer).
- Baseball is hand-graded; no model.

## 2. ARKBOARD

Hub at [/arkboard/](https://arkndjl.net/arkboard/) ([`content/arkboard.md`](../content/arkboard.md)); one page per sport,
each a set of tab groups (tab names are URL hashes; [`layouts/shortcodes/wintabs.html`](../layouts/shortcodes/wintabs.html)).

| Page | Groups (tabs) | Numbers come from |
| --- | --- | --- |
| [Football Prospects / CFB](../content/arkboard-college-football.md) | players, rosters, games, teams, market, recruits, draft, model | `cfb*.json`, `static/data/cfb-all.json` + `cfb-detail.json` |
| [NFL](../content/arkboard-nfl.md) | players, rosters, games, teams, market | `nfl_games.json`, `nfl_war.json`, `nfl_fantasy.json`, `xaav-nfl.json` |
| [Basketball Prospects / CBB](../content/arkboard-college-basketball.md) | as CFB, plus past boards | `cbb*.json`, `static/data/cbb-all.json` |
| [NBA](../content/arkboard-nba.md) | players, rosters, games, teams, market | `nba_games.json`, `nba_xpm.json`, `static/data/nba-proj.json` |
| [NHL](../content/arkboard-nhl.md) / [Hockey Prospects](../content/arkboard-hockey-prospects.md) | players, rosters, games, teams, market / draft board, mock, model | `nhl_games.json`, `nhl_war.json`, `hockey*.json` |
| [Soccer](../content/arkboard-soccer.md) / [Soccer Prospects](../content/arkboard-soccer-prospects.md) | players, rosters, games, teams, leagues / big board, model | `soccer_games.json`, `soccer_war.json`, `soccer_intl.json`, `soccer_prospects.json` |
| [Tennis](../content/arkboard-tennis.md) / [Tennis Prospects](../content/arkboard-tennis-prospects.md) | ATP, WTA, games, event odds, model | `tennis*.json` |
| [Counter-Strike](../content/arkboard-counter-strike.md) | players, games, teams, market, model | `cs2*.json` |
| [College Baseball / MLB Draft](../content/arkboard-baseball.md) | draft hitters, U19 MiLB, org | page content (hand-graded) |
| [Predictions](../content/arkboard-predictions.md) | games, picks, player projections, futures, paper book, backtests, game models | `games_picks_*.json`, `paper_book.json`, `picks_oos.json`, `model_monitor/` |
| [ARKRANKING](../content/arkboard-arkranking.md) | title odds, every sport's ARK Ranking | each sport's `power[]` / rank file |
| [Standings](../content/arkboard-standings.md) | official tables only | [`standings.json`](../data/standings.json) |
| [ARKLIST](../content/arkboard-arklist.md) | owner's hand-picked players, performances | [`arklist.json`](../data/arklist.json), `static/data/arklist-perf.json` |
| [Reference](../content/arkboard-reference.md) | Research, Glossary/Methodology, Data Sources | [`library.json`](../data/library.json), [`data_sources.json`](../data/data_sources.json) |

Picks, lines and props appear only on Predictions; sport pages show projections, season odds and rankings. The
ARK Ranking is the game model's neutral-site rating, ranked.

## 3. arkndjl.net: pages, files, formats

Static Hugo site on Cloudflare ([`hugo.toml`](../hugo.toml), [`wrangler.toml`](../wrangler.toml)). Menu: about/contact,
ST. CLAIRE (`/stclaire/`), ARKBOARD (pages above), ARKLIBRARY, 1NT, LAURSEN_111, eephus.io. Short links
(`/cfb`, `/nfl`, `/picks`, `/reference` …) in [`static/_redirects`](../static/_redirects).

There is no API. Two kinds of data file:

- `data/*.json` (about 500 files): build-time only. Hugo renders them into HTML tables; they are not served as files.
- `static/data/**.json` (93 MB): served at `https://arkndjl.net/data/…`, loaded by the pages on demand. Strict JSON
  (no NaN; [`scripts/check_build.py`](../scripts/check_build.py)), UTF-8, no versioning or schema guarantee.

| URL | Format and fields |
| --- | --- |
| `/build.json` | `{sha, branch, built, hugo, inHours, data{<sport>: {label, asof, feed, phase, season, offHours, workflow, feeds{name: asof}}}}` ([`layouts/index.buildinfo.json`](../layouts/index.buildinfo.json)) |
| `/data/nfl-fantasy.json` | `{season, week, asof, scoring, paTiers, players[]}`; player: `id` (gsis), `n`, `pos`, `t`, `st` status tag, `av` P(plays this week), `w` this week's stat line, `opp`, `home`, `kick`, `imp` implied team points, `r` rest-of-season expected stats, `rg` games left, `eg` expected games, `g` games played, `ppg` [std, half, PPR] to date, `espn` |
| `/data/nfl-war.json` | `players[]`: `n, id, t, pos, g, sn, av, war, xv, waa, pace, age …` |
| `/data/cfb-all.json`, `/data/cbb-all.json` | columnar: `cols[]` + `rows[][]` (CFB: `name, pos, team, cls, age, fv, xnil, draft27 …`; CBB: `name, team, pos, fv, fvx, nbaP, xbpm …`); CFB detail in `cfb-detail.json`, tied by `dk` |
| `/data/nba-proj.json`, `/data/nba-xpm/<season>.json` | NBA projections (`xpm, pxpm, pvorx, p1, p3, sal, sur`) and XPM by season |
| `/data/nhl-war/<season>.json`, `/data/soccer-war/…`, `/data/xaav-*.json`, `/data/pctl-*.json`, `/data/depth/<sport>.json` | player value, contract value, percentiles, depth charts |
| `/index.xml`, `/sitemap.xml` | RSS (posts), sitemap |

Game rows (built into the pages from `data/<sport>_games.json`, not served) share: `id`, `home`, `away`, `neutral`,
`margin` (home minus away), `pHome`, `total`, `hs`/`as` (projected scores), `parts` (each term's points), `elo`,
`line`/`tline` (market spread and total), `ml`, `edge`, `cover`, `over`. Market-line sign conventions differ by
builder; read the builder before joining.

## 4. Methodology

**Ratings.** Each sport's rating is its game model's neutral-site margin (CFB, NFL, CBB, NBA), win logit (NHL), goal
rates (soccer), or chance against a reference opponent (tennis: average top-50; CS2: average top-20). Elo is a
component everywhere except soccer. Full definitions: Reference, "Team ratings".

**How pHome is built.**

- Margin sports: `m = Σ coef_f · x_f` over the terms in section 1; `pHome = Φ(m / σ)`, σ fit walk-forward on the
  miss: NFL 12.85, NBA 12.25, CBB 11.4, CFB 14.2 (`sd` in the `*_games_fit.json` files; `sigma` in
  [`cfb_model.json`](../data/cfb_model.json)). See [`nfl_games.py`](../scripts/nfl_games.py) (`'pHome': phi(mar / sd)`).
  CBB re-prices `m` from the latest injury report between builds.
- CFB without the game model: `pHome = 1 / (1 + 10^(-diff/400))`, diff = Elo + talent and injury adjustments + 55
  home ([`cfb_teams.mjs`](../scripts/cfb_teams.mjs) `gamesModel`).
- NHL: logistic on the NHL terms. Soccer: Poisson goals with Dixon-Coles, home = P(home win at 90). Tennis: three
  ratings blended in log-odds plus context. CS2: player Elo + map veto + VRS in log-odds, blended with Thunderpick's
  price where one exists.

**Testing.** Walk-forward: each game is predicted with a model fit only on earlier games. Seasons split into tuning
(terms enter) and held out (verdict). Every term sits in [`data/model_ledger.json`](../data/model_ledger.json)
(Benjamini-Hochberg over terms: 87 keep, 103 watch, 19 drop, 4 core, 12 candidate).

**Held-out results vs the market** (from each fit file's `test`/`held`/`vsClose`):

| Sport | Held out | Games | Model | Market close |
| --- | --- | --- | --- | --- |
| NFL | 2021-25 | 1,424 | MAE 9.99 | MAE 9.76 |
| NBA | 2022-26 | 6,604 | MAE 10.706, log loss .6024 | MAE 10.564, .5946 |
| CBB | 2021-26 | 29,755 | MAE 9.009, log loss .5256 | MAE 8.986, .5255 |
| CFB | 2025-26 folds | 1,444 | MAE 12.44, log loss .4464 | MAE 11.84, .4363 |
| NHL | 2024-26 | 4,192 | log loss .6685 | .6645 |
| Soccer, big five | 2023 on | 7,076 | 1X2 log loss .9709 | .9663 |
| Tennis | 2023-26 | 9,860 lined | log loss .5977 | .5903 |
| CS2 | walk-forward since Feb 2024 | 21,056 | log loss .561 (ARK + VRS) | no stored close; VRS alone .667; Thunderpick price beats the model (Reference) |
| National teams | close available Jun 2024 on | not stored | log loss .8485 | .8349 |

Files: [`nfl_games_fit`](../data/nfl_games_fit.json), [`nba_games_fit`](../data/nba_games_fit.json),
[`cbb_games_fit`](../data/cbb_games_fit.json), [`cfb_game_backtest`](../data/cfb_game_backtest.json),
[`nhl_games_fit`](../data/nhl_games_fit.json), [`soccer_games_fit`](../data/soccer_games_fit.json),
[`tennis_fit`](../data/tennis_fit.json), [`cs2_fit`](../data/cs2_fit.json); national teams from Reference.

**Calibration.** Stored favourite-side bins, weighted mean |predicted - observed| (computed here from the bins):
NBA .006 (6,605 games), CBB .007 (32,673), tennis .005 (20,328), soccer .013 (8,904), NHL .029 (4,175, overconfident).

**NFL fantasy** ([`nfl_fantasy_fit.json`](../data/nfl_fantasy_fit.json), held out 2021-25, PPR MAE per game vs
season-to-date points a game): QB 6.01 vs 6.51, RB 5.07 vs 5.40, WR 5.23 vs 5.56, TE 4.60 vs 4.99, K 3.55 vs 3.92,
DST 4.17 vs 4.60. Rest of season from weeks 4/8/12: MAE cut 12-17% (DST 38%).

**Picks** ([`picks_oos.json`](../data/picks_oos.json), 2026-11-16): 908 graded live and paper picks, worth at close
-0.17% (t -0.26). Only NBA is live (145 picks, +1.66%, t 1.94); CBB, CFB, NFL, NFL props and tennis are paper. No
book passes Holm.

## 5. What third parties pull today

None found. I searched the repository (code, workflows, content, data) for TLS, TLS Fantasy, ARKDATA and any
consumer of the site's data, and GitHub issues and pull requests for the same; none mention an outside consumer.
Nothing in the repo is built for one:

- No API, feed or export for outside use; the only machine-readable files are those in section 3.
- No CORS header: [`static/_headers`](../static/_headers) sets none, and live `/data/` responses (checked
  2026-11-16) carry no `Access-Control-Allow-Origin`, so another site's browser code cannot fetch them.
- [`robots.txt`](../layouts/robots.txt) disallows `/data/` for every agent and blocks AI crawlers site-wide;
  [`/terms/`](../content/terms.md) bars scraping and reuse without written permission.

The inbound direction is documented: every outside source the site pulls from is in
[`data/data_sources.json`](../data/data_sources.json) (Data Sources tab on Reference).

A TLS Fantasy integration would need the owner's permission and, practically, a server-side fetch of
`/data/nfl-fantasy.json` (or a purpose-built export), plus `/build.json` for freshness.

## 6. Planned or unfinished

- Season-end lockbox scoring of every shipped 2026-27 term (NFL reserve lists, NFL/NBA P(plays), CFB market
  disagreement, soccer call-up squads), scored once (Reference glossary).
- Registered retests in [`scripts/data/ledger/retests_2027.json`](../scripts/data/ledger/retests_2027.json): tennis
  year-end batch, gradient-boosted stacks for hockey and CS2, CBB next-season prior.
- Tennis event odds to be scored against outright prices after the 2027 Australian Open
  ([`tennis_events_2027.json`](../scripts/data/ledger/tennis_events_2027.json)).
- Logging ledgers waiting on outcomes: awards, coaching watch, transfer landing, recruit commitments
  ([`scripts/data/ledger/`](../scripts/data/ledger/)).
- Novig Paper auto-placement ([`scripts/novig_paper.py`](../scripts/novig_paper.py)) is wired into odds-snap but
  has placed nothing: it needs API keys, and its ledger `data/novig_paper.json` does not exist.
- Model ledger: 103 terms on watch, 12 candidates, 4 fits that don't yet emit paired tests (`pending`).
- Manual `deploy-cloudflare` fallback needs Cloudflare secrets (README, "Deploying").
- Open issue [#956](https://github.com/arkndjl/website/issues/956): soccer workflow failing.
