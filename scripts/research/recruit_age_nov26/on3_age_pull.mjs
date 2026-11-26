import fs from 'fs';
const { chromium } = await import('/opt/node22/lib/node_modules/playwright/index.mjs');
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
const browser = await chromium.launch({ ...(proxy ? { proxy: { server: proxy } } : {}) });
const [sport, npages, ...years] = process.argv.slice(2);
const jobs = []; for (const y of years) for (let pg = 1; pg <= +npages; pg++) jobs.push([y, pg]);
const out = {};
async function worker() {
  const ctx = await browser.newContext({ userAgent: UA, ignoreHTTPSErrors: !!proxy });
  const page = await ctx.newPage();
  await page.route(/\.(png|jpe?g|svg|gif|webp|woff2?|css|js)(\?|$)|doubleclick|amazon-adsystem|googletag/, r => r.abort());
  while (jobs.length) {
    const [y, pg] = jobs.shift();
    const url = `https://www.on3.com/rivals/rankings/industry-player/${sport}/${y}/${pg > 1 ? `?page=${pg}` : ''}`;
    for (let i = 0; i < 3; i++) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
        const pp = JSON.parse(await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent)).props.pageProps;
        (out[y] ||= []).push(...pp.playerData.list.map(it => { const p = it.person, r = p.rating || {}; return { key: p.key, slug: p.slug, name: p.name, age: p.age ?? null, pos: r.positionAbbr, rk: r.consensusNationalRank, cons: r.consensusRating, state: r.stateAbbr, team: p.status?.committedOrganizationSlug || null, ht: p.height, wt: p.weight }; }));
        console.log(y, pg, 'ok'); break;
      } catch (e) { console.log('retry', y, pg, e.message.slice(0, 50)); }
    }
  }
}
await Promise.all(Array.from({ length: 6 }, worker));
fs.writeFileSync(`on3_${sport}_${years[0]}_${years.at(-1)}.json`, JSON.stringify(out));
await browser.close();
