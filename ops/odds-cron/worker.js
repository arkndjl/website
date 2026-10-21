// Starts the "odds snap" GitHub workflow on a reliable clock (GitHub's own schedule fires hours late on this repo).
// A separate Cloudflare Worker, not the site: its cron (wrangler.toml) calls the workflow_dispatch API.
// Secret: GH_TOKEN, a fine-grained GitHub token for arkndjl/website with "Actions: read and write" only.
const REPO = 'arkndjl/website';
const WORKFLOW = 'odds-snap.yml';

async function dispatch(env) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${env.GH_TOKEN}`,
      accept: 'application/vnd.github+json',
      'user-agent': 'arkboard-odds-cron',
      'x-github-api-version': '2022-11-28',
    },
    body: JSON.stringify({ ref: 'main' }),
  });
  return r.status;                 // 204 on success
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env).then((s) => console.log('dispatch', s)));
  },
  // GET /run starts one by hand (for testing); everything else is a 404
  async fetch(req, env) {
    return new URL(req.url).pathname === '/run'
      ? new Response(`dispatch ${await dispatch(env)}\n`)
      : new Response('not found\n', { status: 404 });
  },
};
