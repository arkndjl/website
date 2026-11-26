// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// On3/Rivals recruitment detail for the commitment model (scripts/recruit_commit_fit.py): each recruit's dated
// official/unofficial visits, the schools in his recruitment (status, visit counts, RPM %), his commitment date, and
// the dated RPM expert picks (expert, school, confidence, the pick it replaced).
//   node scripts/recruit_on3_visits.mjs cfb 2027 2028 [--top 600] [--force]
//   node scripts/recruit_on3_visits.mjs cfb 2027 2028 2029 --open   (live: uncommitted only, fresh)
//   node scripts/recruit_on3_visits.mjs cfb 2027 2028 --committed   (committed only, for the cards' visits)
//   -> scripts/.cache/recruit_on3/<sport>-<class>.jsonl (one recruit a line; resumable)
// On3 sits behind Cloudflare: one Chromium page clears it, then the pages' Next.js JSON routes are fetched from inside it.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache', 'recruit_on3');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
const SPORT = { cfb: 'football', cbb: 'basketball' };
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function loadPlaywright() {
  for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) {
    try { return await import(spec); } catch {}
  }
  throw new Error('needs playwright');
}

const args = process.argv.slice(2);
const sp = args[0]; if (!SPORT[sp]) throw new Error('sport: cfb | cbb');
const years = args.filter(a => /^\d{4}$/.test(a)).map(Number);
const ti = args.indexOf('--top'), TOP = ti > 0 ? +args[ti + 1] : (sp === 'cfb' ? 600 : 150);
// --open: uncommitted recruits only, always re-pulled (the live classes); --committed: committed recruits only, into
// <sport>-<class>-committed.jsonl (their visits for the GFX cards)
const force = args.includes('--force'), open = args.includes('--open'), committed = args.includes('--committed');
const PAR = 6;

const { chromium } = await loadPlaywright();
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(proxy ? { proxy: { server: proxy } } : {}), ...(exe ? { executablePath: exe } : {}) });
const ctx = await browser.newContext({ userAgent: UA, ignoreHTTPSErrors: !!proxy });
const page = await ctx.newPage();
await page.route(/\.(png|jpe?g|svg|gif|webp|woff2?|css)(\?|$)|doubleclick|amazon-adsystem|googletag/, r => r.abort());
let bid = null;

async function boot(url) {
  for (let i = 0; i < 4; i++) {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
      const nd = JSON.parse(await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent));
      bid = nd.buildId; return nd.props.pageProps;
    } catch (e) { console.log(`  retry ${url}: ${e.message.slice(0, 60)}`); await sleep(3000 * 2 ** i); }
  }
  throw new Error(`blocked: ${url}`);
}

async function data(route, id) {
  for (let i = 0; i < 4; i++) {
    const r = await page.evaluate(async u => {
      try { const x = await fetch(u); return [x.status, x.status === 200 ? await x.text() : '']; } catch (e) { return [0, '']; }
    }, `/_next/data/${bid}/${route}.json?id=${id}`);
    if (r[0] === 200) {
      const pp = JSON.parse(r[1]).pageProps || {};
      if (pp.__N_REDIRECT) return { redirect: pp.__N_REDIRECT };
      return pp;
    }
    if (r[0] === 404) { await boot(`https://www.on3.com/${route}/`); continue; }   // new build id
    await sleep(2000 * 2 ** i);
  }
  return null;
}

const ts = v => v == null ? null : (typeof v === 'number' ? new Date(v * 1000).toISOString().slice(0, 10) : String(v).slice(0, 10));
const day0 = d => !d || d.startsWith('0001') ? null : d.slice(0, 10);

function pack(slug, rec, pred) {
  const r = rec.recruit || {}, cs = r.committedStatus || {};
  const tt = (rec.topTeams?.list || []).map(t => [t.team?.slug, t.status, t.prediction == null ? null : +(+t.prediction).toFixed(2),
    t.officialVisitCount || 0, t.unOfficialVisitCount || 0, day0(t.committedDate)]);
  const vis = (rec.visits?.visits || []).map(v => [v.organization?.slug, v.type, ts(v.dateOccurred)]);
  const picks = (pred?.rpmPicks || []).filter(x => x.type === 'Pick').map(x => [day0(x.dateAdded), x.organization?.slug || null, x.expert?.key ?? null,
    x.confidence ?? null, x.flippedFromOrganization?.slug || null, day0(x.previousDateAdded), x.previousConfidence ?? null]);
  const lead = (pred?.rpmPicks || []).filter(x => x.type === 'NewLeader').map(x => [day0(x.dateAdded),
    (x.topTeams || []).map(t => [t.organization?.slug, +(+t.currentPercentage).toFixed(1), t.previousPercentage == null ? null : +(+t.previousPercentage).toFixed(1)])]);
  const pl = rec.player || {};
  return { slug, key: pl.key, name: pl.name, cls: r.classYear || pl.classYear, state: pl.hometownState?.abbreviation || null, home: pl.hometownName || null,
    pos: pl.positionAbbreviation || null, rating: r.rating?.rating ?? null, rank: r.rating?.nationalRank ?? null,
    commit: cs.committedAsset?.slug || null, cstatus: cs.type || null, cdate: day0(cs.date), interest: rec.recruitments?.find(x => x.isCurrent)?.interestCount ?? null,
    nvis: rec.visits?.counts || null, teams: tt, visits: vis, picks, lead };
}

fs.mkdirSync(OUT, { recursive: true });
await boot(`https://www.on3.com/rivals/rankings/industry-player/${SPORT[sp]}/${years[0] || 2027}/`);
for (const y of years) {
  const f = path.join(OUT, `${sp}-${y}${committed ? '-committed' : ''}.jsonl`);
  if ((force || open) && fs.existsSync(f)) fs.unlinkSync(f);
  const done = new Set(fs.existsSync(f) ? fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l).slug) : []);
  const slugs = [];
  for (let pg = 1, pages = 1, seen = 0; pg <= pages && seen < TOP; pg++) {
    // page 1 through the JSON route; later pages through the full URL (the data route ignores ?page)
    const list = pg === 1 ? (await data(`rivals/rankings/industry-player/${SPORT[sp]}/${y}`, ''))?.playerData
      : (await boot(`https://www.on3.com/rivals/rankings/industry-player/${SPORT[sp]}/${y}/?page=${pg}`)).playerData;
    if (!list) throw new Error(`On3 ${sp} ${y} rankings: blocked`);
    pages = list.pagination.pageCount;
    for (const it of list.list) {
      if (++seen > TOP) break;
      const com = !!it.person.status?.committedOrganizationSlug;
      if (committed ? com : !open || !com) slugs.push(it.person.slug);
    }
  }
  const todo = slugs.filter(s => !done.has(s));
  console.log(`${sp} ${y}: ${slugs.length} ranked, ${done.size} cached, ${todo.length} to pull`);
  const fd = fs.openSync(f, 'a');
  let n = 0;
  for (let i = 0; i < todo.length; i += PAR) {
    await Promise.all(todo.slice(i, i + PAR).map(async s => {
      let rec = await data(`rivals/${s}/recruiting`, s);
      if (rec?.redirect) rec = await data(`rivals/${s}`, s);
      const pred = await data(`rivals/${s}/predictions`, s);
      if (!rec || !rec.player) return;
      fs.writeSync(fd, JSON.stringify(pack(s, rec, pred)) + '\n'); n++;
    }));
    if ((i / PAR) % 20 === 0) console.log(`  ${sp} ${y}: ${n}/${todo.length}`);
  }
  fs.closeSync(fd);
  console.log(`${sp} ${y}: wrote ${n}`);
}
await browser.close();
