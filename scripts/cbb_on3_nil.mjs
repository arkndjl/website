// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// On3's basketball NIL 100 (player valuations), one of the two On3 lists the CBB xNIL / yNIL fit is checked against.
//   node scripts/cbb_on3_nil.mjs        -> scripts/.cache/cbbmkt/on3_nil100.json, read by scripts/cbb_market_pull.py
// (the other list, the transfer portal, comes from On3's public API in that script).
// On3 sits behind Cloudflare, so each page's server-rendered __NEXT_DATA__ is read through Chromium (playwright).
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const OUT = path.join(ROOT, 'scripts', '.cache', 'cbbmkt', 'on3_nil100.json');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function loadPlaywright() {
  for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) { try { return await import(spec); } catch {} }
  throw new Error('needs playwright: npm i -D playwright && npx playwright install chromium');
}
const { chromium } = await loadPlaywright();
const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
const browser = await chromium.launch({ ...(proxy ? { proxy: { server: proxy } } : {}), ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) });
const ctx = await browser.newContext({ userAgent: UA, ignoreHTTPSErrors: !!proxy });
const page = await ctx.newPage();
await page.route(/\.(png|jpe?g|svg|gif|webp|woff2?|css)(\?|$)|doubleclick|amazon-adsystem|googletag/, r => r.abort());
async function next(url) {
  for (let i = 0; i < 4; i++) {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
      const t = await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent || '');
      if (t) return JSON.parse(t).props.pageProps;
    } catch (e) { /* retry */ }
    await sleep(2000 * (i + 1));
  }
  return null;
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
const out = { asof: new Date().toISOString().slice(0, 10), nil100: [] };
const pp = await next('https://www.on3.com/nil/rankings/player/college/basketball/');
for (const x of pp?.nilRankings?.list || []) {
  const p = x.person || {}, st = p.status || {};
  out.nil100.push({ name: p.name || p.fullName, val: x.valuation?.valuation ?? null, team: st.committedOrganizationSlug || null,
    pos: p.rating?.positionAbbr || null, ht: p.height ?? null });
}
await browser.close();
fs.writeFileSync(OUT, JSON.stringify(out));
console.log('nil100', out.nil100.length);
