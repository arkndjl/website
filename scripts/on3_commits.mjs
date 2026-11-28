// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// On3 team commit lists: every signee a program's class page names, rated or not, with each service's own grade
// (On3/Rivals, 247, ESPN and the industry rating), hometown, high school and size. The source of the unrated and
// low-rated tail the industry table (scripts/cfb_on3.mjs, about 2,500 a class) and ESPN's class lists leave out,
// FCS programs included. Read through Chromium (On3 sits behind Cloudflare), one JSON request a team and class.
//   node scripts/on3_commits.mjs football 2010 2027 [--fcs] [--force]   -> scripts/.cache/on3commits/<sport>/<slug>-<class>.json
//   node scripts/on3_commits.mjs football 2027 2029 --fcs --offers   -> scripts/.cache/on3offers/<sport>/<slug>-<class>.json (each
//     program's offer list, the same rows; the class cards' offers, packed by scripts/class_offboard.py --offers)
// Packed by scripts/arkstars_hist.py.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const args = process.argv.slice(2), sport = args[0] || 'football', force = args.includes('--force');
const [y0, y1] = args.filter(a => /^\d{4}$/.test(a)).map(Number);
const KIND = args.includes('--offers') ? 'offers' : 'commits';
const OUT = path.join(ROOT, 'scripts', '.cache', KIND === 'offers' ? 'on3offers' : 'on3commits', sport);
fs.mkdirSync(OUT, { recursive: true });

async function loadPlaywright() {
  for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) { try { return await import(spec); } catch {} }
  throw new Error('On3 needs playwright');
}
const { chromium } = await loadPlaywright();
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy, exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(proxy ? { proxy: { server: proxy } } : {}), ...(exe ? { executablePath: exe } : {}) });
const ctx = await browser.newContext({ userAgent: UA, ignoreHTTPSErrors: !!proxy });
const seedUrl = sport === 'football' ? 'https://www.on3.com/college/alabama-crimson-tide/football/2024/commits/' : 'https://www.on3.com/college/duke-blue-devils/basketball/2024/commits/';
async function open() {
  const page = await ctx.newPage();
  await page.route(/\.(png|jpe?g|svg|gif|webp|woff2?|css)(\?|$)|doubleclick|amazon-adsystem|googletag/, r => r.abort());
  for (let i = 0; ; i++) {
    try {
      await page.goto(seedUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
      const d = JSON.parse(await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent));
      return { page, bid: d.buildId, pp: d.props.pageProps };
    } catch (e) { if (i >= 3) throw e; await sleep(4000 * 2 ** i); }
  }
}
// ESPN's display names that On3 spells another way
const ALIAS = { 'mcneese-cowboys': 'mcneese-state-cowboys', 'nicholls-colonels': 'nicholls-state-colonels', 'ualbany-great-danes': 'albany-great-danes',
  'long-island-university-sharks': 'liu-sharks', 'central-connecticut-blue-devils': 'central-connecticut-state-blue-devils', 'se-louisiana-lions': 'southeastern-louisiana-lions',
  'ut-martin-skyhawks': 'tennessee-martin-skyhawks', 'east-texas-aandm-lions': 'texas-am-commerce-lions', 'st-thomas-minnesota-tommies': 'st-thomas-tommies' };
const slugify0 = s => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/&/g, 'and').replace(/['.()]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const slugify = s => { const x = slugify0(s).replace(/aandm/g, 'am').replace(/aandt/g, 'at').replace(/-and-/g, '-'); return ALIAS[x] || x; };
const first = await open();
// teams: On3's own menu (FBS; every D-I conference for basketball), plus ESPN's FCS programs by name for football
const teams = new Map();
for (const c of first.pp.teams || []) for (const t of c.teams) teams.set(t.slug, { slug: t.slug, url: t.urlSlug, conf: c.conferenceAbbr });
if (args.includes('--fcs') || sport !== 'football') {
  const grp = sport === 'football' ? ['football/college-football', 81] : ['basketball/mens-college-basketball', 50];
  const j = await (await fetch(`https://site.api.espn.com/apis/site/v2/sports/${grp[0]}/teams?groups=${grp[1]}&limit=500`, { headers: { 'user-agent': UA } })).json();
  // ESPN's group holds lower divisions too: ON3_TEAMS (a JSON file of ESPN team ids, e.g. the board's programs) keeps the pull to those
  const only = process.env.ON3_TEAMS ? new Set(Object.keys(JSON.parse(fs.readFileSync(process.env.ON3_TEAMS)))) : null;
  for (const { team: t } of j.sports[0].leagues[0].teams) { if (only && !only.has(String(t.id))) continue; const s = slugify(t.displayName); if (!teams.has(s)) teams.set(s, { slug: s, espn: t.id, conf: sport === 'football' ? 'FCS' : null }); }
}
// ON3_EXTRA: a JSON file of {On3 slug: ESPN team id} for programs ESPN's group list leaves out
if (process.env.ON3_EXTRA) for (const [s, id] of Object.entries(JSON.parse(fs.readFileSync(process.env.ON3_EXTRA)))) if (!teams.has(s)) teams.set(s, { slug: s, espn: id, conf: 'FCS' });
const tf = path.join(OUT, '_teams.json'); const known = fs.existsSync(tf) ? JSON.parse(fs.readFileSync(tf)) : {};
for (const t of teams.values()) if (!t.url && known[t.slug]?.url) t.url = known[t.slug].url;
const jobs = [];
for (const t of teams.values()) for (let y = y1; y >= y0; y--) if (force || !fs.existsSync(path.join(OUT, `${t.slug}-${y}.json`))) jobs.push([t, y]);
console.log(`${sport}: ${teams.size} teams, ${jobs.length} team-classes to pull`);

const pick = it => {
  const p = it.player || {}, r = it.rating || {}, st = it.status || {};
  return { key: p.key, name: p.fullName, first: p.firstName, last: p.lastName, slug: p.slug, cls: p.classYear, pos: p.position?.abbr || r.positionAbbr || null,
    ht: p.height || null, wt: p.weight || null, home: p.hometown?.abbr || null, state: p.state?.abbr || r.stateAbbr || null,
    hs: p.highSchool?.slug || null, hsName: p.highSchoolName || null, hsType: p.highSchool?.orgType || null, dob: p.dateOfBirth || null,
    status: st.type || null, date: st.date || null, xfer: !!st.transfer, year: st.recruitmentYear ?? null,
    org: st.committedOrganization?.slug || st.organization?.slug || it.committedOrganization?.slug || null, rk: r.nationalRank ?? r.overallRank ?? null, rating: r.rating ?? r.consensusRating ?? null,
    svc: Object.fromEntries((it.industryComparison || []).filter(x => x.rating != null).map(x => [x.type.toLowerCase(), [x.rating, x.stars ?? null, x.overallRank ?? null, x.positionRank ?? null]])) };
};
let done = 0, miss = 0, shown = 0;
// the offers page's player list, wherever the page keeps it: the first {list: [{player, ...}]} in its props
function listIn(o, d = 0) {
  if (!o || typeof o !== 'object' || d > 4) return null;
  if (Array.isArray(o.list) && o.list.length && o.list[0] && (o.list[0].player || o.list[0].person)) return { list: o.list.map(x => x.player ? x : { ...x, player: x.person }), pagination: o.pagination };
  for (const v of Object.values(o)) { const f = listIn(v, d + 1); if (f) return f; }
  return null;
}
async function worker(w) {
  let { page, bid } = w === 0 ? first : await open();
  const get = async u => page.evaluate(async u => { try { const r = await fetch(u); return [r.status, await r.text()]; } catch (e) { return [0, String(e)]; } }, u);
  while (jobs.length) {
    const [t, y] = jobs.shift(), f = path.join(OUT, `${t.slug}-${y}.json`);
    if (t.dead || (!force && fs.existsSync(f))) continue;
    let out = null;
    for (let i = 0; i < 4 && out == null; i++) {
      const [s, txt] = await get(`/_next/data/${bid}/college/${t.url || t.slug}/${sport}/${y}/${KIND}.json`);
      let j = null; try { j = JSON.parse(txt).pageProps; } catch {}
      if (j && !j.playerList && KIND === 'offers') { j.playerList = listIn(j); if (!shown++) console.log('  offers page keys:', Object.keys(j).join(', ')); }
      if (j?.__N_REDIRECT) { const m = j.__N_REDIRECT.match(/college\/([^/]+)\//); if (m && m[1] !== (t.url || t.slug)) { t.url = m[1]; i--; continue; } }
      if (j?.playerList) {
        out = j.playerList.list.map(pick);
        const pc = j.playerList.pagination?.pageCount || 1;
        for (let pg = 2; pg <= pc; pg++) { const [, t2] = await get(`/_next/data/${bid}/college/${t.url || t.slug}/${sport}/${y}/${KIND}.json?page=${pg}`); try { const p2 = JSON.parse(t2).pageProps; out.push(...(p2.playerList || listIn(p2)).list.map(pick)); } catch {} }
      } else if (s === 404 || j?.notFound || (j && !j.playerList && !j.__N_REDIRECT)) { if (!t.url) { t.dead = true; console.log(`  no On3 page: ${t.slug}`); } out = []; miss++; }
      else {   // a new deploy changes the build id; a block needs a pause
        await sleep(3000 * 2 ** i);
        try { await page.goto(seedUrl, { waitUntil: 'domcontentloaded', timeout: 90000 }); bid = JSON.parse(await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent)).buildId; } catch {}
      }
    }
    if (out != null && !t.dead) fs.writeFileSync(f, JSON.stringify(out));
    if (++done % 200 === 0) console.log(`  ${done} done, ${jobs.length} left, ${miss} empty`);
    await sleep(250);
  }
}
await Promise.all([...Array(+(process.env.ON3_WORKERS || 3)).keys()].map(worker));
fs.writeFileSync(tf, JSON.stringify({ ...known, ...Object.fromEntries([...teams.values()].map(t => [t.slug, { url: t.url || null, conf: t.conf, espn: t.espn || null, dead: !!t.dead }])) }, null, 0));
console.log(`done: ${done}, empty ${miss}, teams without a page: ${[...teams.values()].filter(t => t.dead).map(t => t.slug).join(', ')}`);
await browser.close();
