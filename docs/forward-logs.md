# Forward logs

A point-in-time history can only be built going forward. This is the list of what the site logs as dated,
append-only snapshots, what each one is for, and what is not logged yet. Swept Nov 28 2026.

## Started Nov 28 2026 (`scripts/snapshots.py`, `scripts/data/snaps/`)

| Log | From | Cadence | What it makes possible | Retest |
|---|---|---|---|---|
| injury statuses, every sport | static/data/injuries.json | 30 min (odds-snap) | when a status changed against when the line moved; return hazards for NHL and soccer, which have no official history | fwd_injury_line_lag |
| news items | data/news.json | 30 min (odds-snap) | news timing against line, FV and board moves; news weight calibration | fwd_news_weight |
| depth charts, every sport | static/data/depth/*.json | after each board run | in-season promotions as a next-up and FV input; who started when | fwd_depth_promotion |
| board vintages | scripts/data/moves/*.json (pruned to a week) | weekly, a board | FV and board metrics as they stood, for drift, momentum and calibration tests | fwd_fv_vintage_drift |
| agency ledger rows | data/agencies.json | after each board run | first-seen dates beside source dates, for the signed-before-the-process rule | fwd_agency_sign_date |
| CFB recruit offers, commitments, visit counts | ESPN class lists (scripts/.cache/cfb) | daily (cfb-recruits) | offer momentum for leans and the recruit index | fwd_offer_momentum |
| On3 college grades, ranks, NIL valuations | scripts/.cache/cfb/on3.json | each full CFB board run | whether yNIL leads On3 and reported deals | fwd_on3_nil_lead |
| NHL game lines | ESPN, Polymarket, Novig | 30 min (odds-snap, `odds_dense`) | NHL close model and bet timing, as the other four sports have | fwd_nhl_close |

`data/snapshots.json` counts every log (rows, keys, first and last stamp); the retests' `ready` conditions read it.

## Already logged before Nov 28

Game lines and ladders (CFB, NFL, CBB, NBA; tennis and CS2 match prices), props, futures, Polymarket award and title
history, the model's number at every line row, the lockbox and awards ledgers, model monitors, NBA referee crews, NBA
official injury reports, the CBB injury log, CFB availability reports, CFB coordinator changes, recruit visits and
expert picks (On3), portal and transaction dates, the NIL deals ledger, daily site visitors, social follower counts,
article views and favorites, DARKO and DRatings snapshots, NHL projected lines, RotoWire news.

## Not logged yet

| Item | Why not | Needs |
|---|---|---|
| per-page traffic and referrers | no token on the runners | CLOUDFLARE_ANALYTICS_TOKEN |
| per-video YouTube views, Twitch streams | no keys | YOUTUBE_API_KEY, TWITCH_CLIENT_ID/SECRET |
| soccer match lines | ESPN serves no soccer odds; no free source in the stack yet | a Polymarket soccer check |
| ticket prices | no key | TICKETMASTER_API_KEY (optional) |
| pro coach changes (NFL, NBA, NHL, managers) | rebuildable later from Wikipedia and the Reference sites | nothing |
| ESPN BPI / matchup predictor | one call a game; past values are rebuildable for FPI only | a cost call |
