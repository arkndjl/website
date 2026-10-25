# odds-cron

GitHub's scheduler fires this repo's crons hours late, so the paper book's odds snapshots (`.github/workflows/odds-snap.yml`)
are started by this Cloudflare Worker's cron instead. Free tier: cron triggers and a few dozen requests a day.

Setup (once):
1. GitHub > Settings > Developer settings > Fine-grained tokens: new token, repository `arkndjl/website`,
   permissions **Actions: Read and write** and **Issues: Read and write**, nothing else. Copy it.
2. Cloudflare > Workers & Pages > Create > Worker, name `arkboard-odds-cron`. Edit code: paste `worker.js`, deploy.
3. The worker > Settings > Variables and Secrets: add secret `GH_TOKEN` = the token.
4. The worker > Settings > Triggers > Cron Triggers: add `5,35 13-23 * * *`, `5,35 0-4 * * *`, `5 8,11 * * *` and `50 */6 * * *`.
5. Test: open `https://arkboard-odds-cron.<your-subdomain>.workers.dev/run`. It should say `dispatch 204`, and a run
   appears under Actions > odds snap.

(Or from this folder: `npx wrangler deploy` then `npx wrangler secret put GH_TOKEN`.)
The workflow's own schedule stays as a backup; two runs close together are harmless (only changes are written).

## Stale data check

Every six hours (`50 */6 * * *`) the worker reads https://arkndjl.net/build.json, which the Hugo build fills with each
sport's newest data stamp and the rules in `data/freshness.json` (stale past 36 h in season, past the sport's
`offHours` outside it). For a sport that has gone stale it dispatches that sport's workflow once and opens a GitHub
issue `stale data: <sport>` (label `stale-data`) listing every feed's stamp; while the issue is open it does not
dispatch again, and it closes the issue when the stamp is fresh. `GET /stale` runs the check by hand.
Updating an existing worker: paste the new `worker.js`, add the fourth cron trigger, and give the token
**Issues: Read and write** (GitHub > Settings > Developer settings > the token > Edit).
