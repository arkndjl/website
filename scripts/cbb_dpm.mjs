// databallr DPM by NBA season, read from its public stats page (databallr.com/stats?season=<year>), for the College
// Basketball ARKBOARD's NBA outcome test.
//   node scripts/cbb_dpm.mjs 2010 2026     # seasons from..to -> scripts/.cache/cbb/dpm/<season>.json
// The table renders as you scroll, so the page is scrolled to the end and every player row collected.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache', 'cbb', 'dpm');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
async function loadPlaywright() {
  for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) { try { return await import(spec); } catch {} }
  throw new Error('needs playwright: npm i -D playwright && npx playwright install chromium');
}
const { chromium } = await loadPlaywright();
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
const exe = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ ...(proxy ? { proxy: { server: proxy } } : {}), ...(exe ? { executablePath: exe } : {}) });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 2000 }, userAgent: UA, ignoreHTTPSErrors: !!proxy });
const page = await ctx.newPage();
fs.mkdirSync(OUT, { recursive: true });
const [a, b] = process.argv.slice(2).map(Number);
for (let y = a; y <= (b || a); y++) {
  await page.goto(`https://databallr.com/stats?season=${y}`, { waitUntil: 'networkidle', timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(4000);
  const seen = new Map();
  let still = 0;
  for (let i = 0; i < 200 && still < 8; i++) {
    const rows = await page.evaluate(() => [...document.querySelectorAll('tr')].map(r => r.innerText.replace(/\s+/g, ' ').trim()).filter(t => /•/.test(t)));
    const n0 = seen.size;
    rows.forEach(r => seen.set(r.split(' • ').slice(0, 2).join('|'), r));
    still = seen.size === n0 ? still + 1 : 0;
    await page.mouse.wheel(0, 1500);
    await page.evaluate(() => { document.querySelectorAll('*').forEach(e => { if (e.scrollHeight > e.clientHeight + 50 && getComputedStyle(e).overflowY !== 'visible') e.scrollTop += 1500; }); });
    await page.waitForTimeout(350);
  }
  const out = [];
  for (const t of seen.values()) {
    // age reads "-" in the first weeks of a season
    // "Chris Paul LAC • PG • 2015 82 2858 34.9 29.0 48.0% 95 +8.0 100 +6.0 99 +2.0 94 ..."
    const m = /^(.*?) ([A-Z]{2,3}(?:\/[A-Z]{2,3})*|\d?TM) • ([A-Z-]+) • (\d{4}) (\d+) (\d+) ([\d.]+) ([\d.]+|-) (?:[\d.]+|-)%(?: \d+)? ([+-]?[\d.]+)(?: \d+)? ([+-]?[\d.]+)(?: \d+)? ([+-]?[\d.]+)/.exec(t);
    if (!m) continue;
    out.push({ name: m[1], team: m[2], pos: m[3], season: +m[4], gp: +m[5], min: +m[6], age: m[8] === '-' ? null : +m[8], dpm: +m[9], odpm: +m[10], ddpm: +m[11] });
  }
  fs.writeFileSync(path.join(OUT, `${y}.json`), JSON.stringify(out));
  console.log(`databallr ${y}: ${out.length} of ${seen.size} rows parsed`);
}
await browser.close();
