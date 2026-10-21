# odds-cron

GitHub's scheduler fires this repo's crons hours late, so the paper book's odds snapshots (`.github/workflows/odds-snap.yml`)
are started by this Cloudflare Worker's cron instead. Free tier: cron triggers and a few dozen requests a day.

Setup (once):
1. GitHub > Settings > Developer settings > Fine-grained tokens: new token, repository `arkndjl/website`,
   permission **Actions: Read and write**, nothing else. Copy it.
2. Cloudflare > Workers & Pages > Create > Worker, name `arkboard-odds-cron`. Edit code: paste `worker.js`, deploy.
3. The worker > Settings > Variables and Secrets: add secret `GH_TOKEN` = the token.
4. The worker > Settings > Triggers > Cron Triggers: add `5,35 13-23 * * *`, `5,35 0-4 * * *`, `5 8,11 * * *`.
5. Test: open `https://arkboard-odds-cron.<your-subdomain>.workers.dev/run`. It should say `dispatch 204`, and a run
   appears under Actions > odds snap.

(Or from this folder: `npx wrangler deploy` then `npx wrangler secret put GH_TOKEN`.)
The workflow's own schedule stays as a backup; two runs close together are harmless (only changes are written).
