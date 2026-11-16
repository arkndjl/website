# tls-feed

Private feed of ARK model output for TLS Fantasy: a Cloudflare Worker (`worker.js`) in front of an R2 bucket
(`ark-tls-feed`). It is not part of arkndjl.net, and the season-sim draws it serves are never committed to this public
repo. Every request needs a token; tokens live only in Cloudflare and in this repo's Actions secrets.

## What it serves

| Key | From | Refreshed by |
| --- | --- | --- |
| `nfl/games.json`, `nfl/fantasy.json`, `nfl/draws.json.gz` | `data/nfl_games.json`, `static/data/nfl-fantasy.json`, NFL season sims | `nfl.yml` |
| `nba/games.json`, `nba/projections.json`, `nba/draws.json.gz` | `data/nba_games.json`, `static/data/nba-proj.json`, NBA season sims | `nba-xpm.yml` |
| `cbb/games.json`, `cbb/draws.json.gz` | `data/cbb_games.json`, CBB regular-season sims | `cbb-board.yml` |
| `cfb/games.json`, `cfb/model.json`, `cfb/rank.json`, `cfb/draws.json.gz` | `data/cfb_games.json`, `data/cfb_model.json`, `data/cfb_rank.json`, CFB season sims | `cfb-board.yml` |
| `<sport>/weekly/<YYYY-Www>/draws.json.gz` | the first draws upload of each ISO week, kept | the worker |

A file goes up after each run of its sport's workflow (`scripts/tls_upload.py`), so it is as fresh as the site.

Draws (`scripts/sim_draws.py`): gzip JSON `{sport, season, asof, sims, teams, fields, draws}`. `draws[field]` is one
row per simulated season, one value per team in `teams` order; row k of every field is the same season. `fields`
says what each value means. NFL and NBA: `wins, seed, stage, pick` (10,000 sims). CFB: `wins, ccg, seed, stage`
(10,000, FBS teams by ESPN id). CBB: `wins, cwins, ctitle` (5,000; regular season only, the NCAA tournament sims are
not kept per draw).

## Reading it

```sh
curl -H "Authorization: Bearer $TOKEN" https://ark-tls-feed.<subdomain>.workers.dev/v1/              # file list
curl -H "Authorization: Bearer $TOKEN" https://ark-tls-feed.<subdomain>.workers.dev/v1/nfl/games.json
curl -H "Authorization: Bearer $TOKEN" https://ark-tls-feed.<subdomain>.workers.dev/v1/nfl/draws.json.gz | gunzip
```

Responses carry `x-asof` (the file's own build stamp). No CORS: call it from a server, not a browser, so the token
stays private. The read token cannot write and the upload token cannot read.

## Setup (once, from a computer)

1. Cloudflare dashboard > R2 > enable R2 (free tier: 10 GB, no charge at this size; Cloudflare asks for a card once).
2. My Profile > API Tokens > Create Token > template "Edit Cloudflare Workers" > add permission
   Account > Workers R2 Storage > Edit > Create. Copy it. The Account ID is on the Workers & Pages overview.
3. Make two random tokens of 40+ characters (a password manager's generator), one to give TLS (read), one for uploads.
4. github.com/arkndjl/website > Settings > Secrets and variables > Actions > New repository secret, five times:
   `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `TLS_READ_TOKEN`, `TLS_UPLOAD_TOKEN`, and after step 5
   `TLS_FEED_URL`.
5. Actions > tls feed > Run workflow. It creates the bucket, deploys the worker and sets both tokens; the log prints the
   worker's `https://ark-tls-feed.<subdomain>.workers.dev` address. Add that as `TLS_FEED_URL`.
6. The next NFL, NBA, CBB or CFB build uploads. Give TLS Fantasy the address and the read token privately.

Rotating a token: put `old,new` in the secret, run the workflow, switch the client, then set just `new` and run again.
The same `CLOUDFLARE_*` secrets also turn on the site's manual `deploy cloudflare` fallback.
