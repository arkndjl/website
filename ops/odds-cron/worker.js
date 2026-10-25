// Starts the "odds snap" GitHub workflow on a reliable clock (GitHub's own schedule fires hours late on this repo).
// A separate Cloudflare Worker, not the site: its cron (wrangler.toml) calls the workflow_dispatch API.
// Secret: GH_TOKEN, a fine-grained GitHub token for arkndjl/website with "Actions: read and write" and
// "Issues: read and write" only.
//
// Every six hours it also checks the site's data stamps (audit #29): https://arkndjl.net/build.json carries each
// sport's newest data asof and the staleness rules from data/freshness.json (in season past inHours, else past
// offHours). A sport that has gone stale gets one dispatch of the workflow that refreshes it and one open GitHub
// issue ("stale data: <sport>"); while that issue is open nothing is dispatched again, and the issue closes itself
// once the stamp is fresh. (The NHL feed was frozen 28+ hours on Oct 24 before anyone saw it.)
const REPO = 'arkndjl/website';
const WORKFLOW = 'odds-snap.yml';
const SITE = 'https://arkndjl.net';
const STALE_CRON = '50 */6 * * *';

function gh(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${env.GH_TOKEN}`,
      accept: 'application/vnd.github+json',
      'user-agent': 'arkboard-odds-cron',
      'x-github-api-version': '2022-11-28',
      ...(init.body ? { 'content-type': 'application/json' } : {}),
    },
  });
}

async function dispatch(env, workflow = WORKFLOW) {
  const r = await gh(env, `/actions/workflows/${workflow}/dispatches`, { method: 'POST', body: JSON.stringify({ ref: 'main' }) });
  return r.status;                 // 204 on success
}

// the same rules as assets/js/fresh.js: a date-only asof counts from the end of that day (UTC)
const at = (a) => Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(a) ? a + 'T23:59:59Z' : a);
function inSeason(season, d) {
  if (!season) return true;
  const md = String(d.getUTCMonth() + 1).padStart(2, '0') + '-' + String(d.getUTCDate()).padStart(2, '0');
  const [a, b] = season;
  return a <= b ? md >= a && md <= b : md >= a || md <= b;
}

// {sport: {label, hours, limit, workflow, feeds}} for every sport past its threshold
export function staleSports(build, now = new Date()) {
  const out = {};
  for (const [k, s] of Object.entries(build.data || {})) {
    if (!s.asof) continue;
    const hours = (now - at(s.asof)) / 3.6e6;
    const limit = inSeason(s.season, now) ? build.inHours || 36 : s.offHours || build.inHours || 36;
    if (hours > limit) out[k] = { label: s.label || k, hours: Math.round(hours), limit, workflow: s.workflow, asof: s.asof, feeds: s.feeds };
  }
  return out;
}

async function openIssues(env) {
  const r = await gh(env, '/issues?state=open&labels=stale-data&per_page=100');
  return r.ok ? r.json() : [];
}

async function checkStale(env) {
  const r = await fetch(`${SITE}/build.json?t=${Date.now()}`, { headers: { 'cache-control': 'no-cache' } });
  if (!r.ok) return `build.json ${r.status}`;
  const build = await r.json(), stale = staleSports(build), open = await openIssues(env), log = [];
  const title = (k) => `stale data: ${k}`;
  for (const [k, s] of Object.entries(stale)) {
    if (open.some((i) => i.title === title(k))) { log.push(`${k} stale, issue open`); continue; }
    const d = s.workflow ? await dispatch(env, s.workflow) : null;
    const feeds = Object.entries(s.feeds || {}).sort((a, b) => at(a[1]) - at(b[1])).map(([n, a]) => `- ${n}: ${a}`).join('\n');
    const body = `The site's ${s.label} data was last updated ${s.asof}, ${s.hours} h ago (stale past ${s.limit} h).\n\n` +
      (s.workflow ? `Dispatched \`${s.workflow}\` once (status ${d}). If it fails, open its latest run under Actions.\n\n` : '') +
      `Feeds, oldest first:\n${feeds}\n\nThis issue closes itself when the stamp is fresh again (checked every six hours by ops/odds-cron).`;
    await gh(env, '/issues', { method: 'POST', body: JSON.stringify({ title: title(k), body, labels: ['stale-data'] }) });
    log.push(`${k} stale ${s.hours} h: dispatch ${d}, issue opened`);
  }
  for (const i of open) {
    const k = i.title.replace(/^stale data: /, '');
    if (stale[k] || !build.data?.[k]) continue;
    await gh(env, `/issues/${i.number}/comments`, { method: 'POST', body: JSON.stringify({ body: `Fresh again: ${build.data[k].asof}.` }) });
    await gh(env, `/issues/${i.number}`, { method: 'PATCH', body: JSON.stringify({ state: 'closed', state_reason: 'completed' }) });
    log.push(`${k} fresh, issue #${i.number} closed`);
  }
  return log.join('; ') || 'all fresh';
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(event.cron === STALE_CRON
      ? checkStale(env).then((s) => console.log('stale check', s))
      : dispatch(env).then((s) => console.log('dispatch', s)));
  },
  // GET /run starts one odds snap by hand (for testing), GET /stale runs the staleness check; everything else is a 404
  async fetch(req, env) {
    const p = new URL(req.url).pathname;
    if (p === '/run') return new Response(`dispatch ${await dispatch(env)}\n`);
    if (p === '/stale') return new Response(`${await checkStale(env)}\n`);
    return new Response('not found\n', { status: 404 });
  },
};
