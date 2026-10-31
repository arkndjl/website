// On3 industry (consensus) basketball recruiting rankings for the College Basketball ARKBOARD and its recruit boards.
//   node scripts/cbb_on3.mjs 2026 2027        # classes to pull -> scripts/.cache/cbb/on3/<class>.json
// On3 sits behind Cloudflare, so this reads each page's server-rendered __NEXT_DATA__ through Chromium
// (npm i -D playwright && npx playwright install chromium, as for fetch_cfb.mjs).
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache', 'cbb', 'on3');
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
for (const y of process.argv.slice(2).map(Number)) {
  const out = [];
  for (let pg = 1, pages = 1; pg <= pages; pg++) {
    const url = `https://www.on3.com/rivals/rankings/industry-player/basketball/${y}/${pg > 1 ? `?page=${pg}` : ''}`;
    let pp = null;
    for (let i = 0; i < 4 && !pp; i++) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
        pp = JSON.parse(await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent)).props.pageProps;
      } catch (e) { console.log(`  retry ${url}: ${e.message.slice(0, 60)}`); await sleep(3000 * 2 ** i); }
    }
    if (!pp) throw new Error(`On3 ${y} page ${pg}: blocked`);
    const pd = pp.playerData; pages = pd.pagination.pageCount;
    for (const it of pd.list) {
      const p = it.person, r = p.rating || {};
      out.push({ key: p.key, name: p.name, slug: p.slug, pos: r.positionAbbr || p.positionAbbreviation, ht: p.height, htf: p.formattedHeight, wt: p.weight,
        cons: r.consensusRating, consRank: r.consensusNationalRank, consStars: r.consensusStars, on3: r.rating, on3Rank: r.nationalRank,
        state: r.stateAbbr, home: p.homeTownName || null, team: p.status?.committedOrganizationSlug || null, classYear: p.classYear,
        fiveStarPlus: !!r.fiveStarPlus, img: p.defaultAssetUrl || null,
        // per-service grades (On3 / 247 / ESPN / Rivals), age as On3 lists it today, school, commit + RPM leader (the recruit boards)
        svc: Object.fromEntries((it.ratings || []).filter(x => !['Industry', 'Consensus'].includes(x.type) && x.rating != null).map(x => [x.type.toLowerCase(), [x.rating, x.overallRank ?? null, x.stars ?? null]])),
        age: p.age ?? null, hs: p.highSchoolName || null,
        signed: !!p.status?.isSigned, commitDate: p.status?.commitmentDate || null, nil: it.nilValue || null,
        rpm: (p.predictions || []).slice(0, 2).map(x => [x.organization?.slug, Math.round(x.percent)]),
        // recruitment detail tested as recruit-model drivers (scripts/cbb_recruit_fit.py)
        interest: p.status?.interestCount ?? null, early: [!!p.earlySignee, !!p.earlyEnrollee], hsSlug: p.highSchool?.slug || null,
        hsType: p.highSchool?.orgType || null });
    }
    console.log(`On3 ${y} page ${pg}/${pages}`);
    await sleep(1200);
  }
  fs.writeFileSync(path.join(OUT, `${y}.json`), JSON.stringify(out));
}
await browser.close();
