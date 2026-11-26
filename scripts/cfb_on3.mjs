// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// On3 industry (consensus) football recruiting rankings: the live composite for the recruit tabs and the history the
// recruit index is fit on (scripts/cfb_recruit_retarget.py).
//   node scripts/cfb_on3.mjs 2027 2028 2029    # classes to pull -> scripts/.cache/cfb/on3/<class>.json
// On3 sits behind Cloudflare, so this reads each page's server-rendered __NEXT_DATA__ through Chromium, as
// scripts/cbb_on3.mjs does for basketball.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache', 'cfb', 'on3');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function loadPlaywright() {
  for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) {
    try { return await import(spec); } catch {}
  }
  throw new Error('On3 needs playwright: npm i -D playwright && npx playwright install chromium');
}

const { chromium } = await loadPlaywright();
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(proxy ? { proxy: { server: proxy } } : {}), ...(exe ? { executablePath: exe } : {}) });
const ctx = await browser.newContext({ userAgent: UA, ignoreHTTPSErrors: !!proxy });
const page = await ctx.newPage();
await page.route(/\.(png|jpe?g|svg|gif|webp|woff2?|css)(\?|$)|doubleclick|amazon-adsystem|googletag/, r => r.abort());
fs.mkdirSync(OUT, { recursive: true });
const args = process.argv.slice(2), force = args.includes('--force');
for (const y of args.filter(a => /^\d{4}$/.test(a)).map(Number)) {
  const f = path.join(OUT, `${y}.json`);
  if (!force && fs.existsSync(f) && y < new Date().getFullYear()) { console.log(`On3 ${y}: cached`); continue; }
  const out = [];
  for (let pg = 1, pages = 1; pg <= pages; pg++) {
    const url = `https://www.on3.com/rivals/rankings/industry-player/football/${y}/${pg > 1 ? `?page=${pg}` : ''}`;
    let pp = null;
    for (let i = 0; i < 4 && !pp; i++) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
        pp = JSON.parse(await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent)).props.pageProps;
        if (!pp.playerData?.list) pp = null;
      } catch (e) { console.log(`  retry ${url}: ${e.message.slice(0, 60)}`); await sleep(3000 * 2 ** i); }
    }
    if (!pp) throw new Error(`On3 ${y} page ${pg}: blocked`);
    const pd = pp.playerData; pages = pd.pagination.pageCount;
    for (const it of pd.list) {
      const p = it.person, r = p.rating || {};
      out.push({ key: p.key, name: p.name, pos: r.positionAbbr || p.positionAbbreviation, ht: p.height, wt: p.weight,
        cons: r.consensusRating, consRank: r.consensusNationalRank, consStars: r.consensusStars, on3: r.rating, on3Rank: r.nationalRank,
        state: r.stateAbbr, home: p.homeTownName || null, age: p.age ?? null, slug: p.slug || null, team: p.status?.committedOrganizationSlug || null,
        fiveStarPlus: !!r.fiveStarPlus, img: p.defaultAssetUrl || null,
        // age as On3 lists it today (few football recruits have one); each service's grade: [rating, national rank, stars]
        svc: Object.fromEntries((it.ratings || []).filter(x => !['Industry', 'Consensus'].includes(x.type) && x.rating != null).map(x => [x.type.toLowerCase(), [x.rating, x.overallRank ?? null, x.stars ?? null]])),
        hs: p.highSchool?.slug || null, hsType: p.highSchool?.orgType || null,
        signed: !!p.status?.isSigned, commitDate: p.status?.commitmentDate || null, nil: it.nilValue || null,
        rpm: (p.predictions || []).slice(0, 5).map(x => [x.organization?.slug, +(+x.percent).toFixed(1)]),
        interest: p.status?.interestCount ?? null, early: [!!p.earlySignee, !!p.earlyEnrollee] });
    }
    if (pg % 10 === 0 || pg === pages) console.log(`On3 ${y} page ${pg}/${pages}`);
    await sleep(900);
  }
  fs.writeFileSync(f, JSON.stringify(out));
}
await browser.close();
