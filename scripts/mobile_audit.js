// Phone-width audit of every ARKBOARD page and tab: page sideways scroll, wide tables with no pinned label column,
// tap targets under 24px, text under 11px, inputs that zoom iOS. Build with --baseURL http://localhost:8765/, serve
// public/ there, then: node scripts/mobile_audit.js <outdir>   (SHOTS=0 skips screenshots, ONLY=nfl,hub limits pages)
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.env.BASE || 'http://localhost:8765';
const OUT = process.argv[2] || 'mobile-audit';
const W = +(process.env.W || 390);
const SHOTS = process.env.SHOTS !== '0';
const pages = ['', 'college-football', 'college-basketball', 'nfl', 'nba', 'nhl', 'hockey-prospects', 'soccer', 'soccer-prospects', 'baseball', 'arklist', 'predictions', 'games'];
const only = process.env.ONLY ? process.env.ONLY.split(',') : null;
fs.mkdirSync(OUT, { recursive: true });

const probe = () => {
  const vw = window.innerWidth;
  const vis = (el) => { const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) return false; const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none' && el.offsetParent !== null || s.position === 'fixed'; };
  const clipped = (el) => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') return true; } return false; };
  const desc = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const r = { pageOverflow: document.documentElement.scrollWidth - vw, overflowers: [], smallTaps: 0, tinyTaps: 0, tapSamples: [], tinyText: 0, textSamples: [], zoomInputs: 0, wideTables: 0, wideNoSticky: 0, tableSamples: [] };
  const all = document.body.querySelectorAll('*');
  const seen = new Set();
  for (const el of all) {
    if (!vis(el)) continue;
    const b = el.getBoundingClientRect();
    if (b.right > vw + 1 && !clipped(el)) { const d = desc(el); if (!seen.has(d) && r.overflowers.length < 8) { seen.add(d); r.overflowers.push(d + ' w' + Math.round(b.width) + ' r' + Math.round(b.right)); } }
  }
  for (const el of document.querySelectorAll('button, select, input, summary, [role=tab], a.btn, .wintabs__tab, label:has(input)')) {
    if (!vis(el)) continue; const b = el.getBoundingClientRect();
    if (b.height < 32 || b.width < 24) { r.smallTaps++; if (b.height < 24) { r.tinyTaps++; if (r.tapSamples.length < 6) r.tapSamples.push(desc(el) + ' ' + Math.round(b.width) + 'x' + Math.round(b.height) + ' "' + (el.textContent || el.value || '').trim().slice(0, 14) + '"'); } }
  }
  for (const el of document.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=range]), select, textarea')) {
    if (!vis(el)) continue; if (parseFloat(getComputedStyle(el).fontSize) < 16) r.zoomInputs++;
  }
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const tset = new Set();
  while (tw.nextNode()) { const n = tw.currentNode; if (!n.textContent.trim()) continue; const el = n.parentElement; if (tset.has(el) || !vis(el)) continue; tset.add(el); const fs = parseFloat(getComputedStyle(el).fontSize); if (fs > 0 && fs < 11) { r.tinyText++; if (r.textSamples.length < 5) r.textSamples.push(desc(el) + ' ' + fs + 'px'); } }
  for (const t of document.querySelectorAll('table')) {
    if (!vis(t)) continue; const b = t.getBoundingClientRect(); if (b.width <= vw) continue;
    r.wideTables++;
    const td = t.querySelector('tbody tr td, tbody tr th');
    const row = [...t.querySelectorAll('tbody tr')].find(r => r.cells.length > 2 && ![...r.cells].some(c => c.colSpan > 1)); const sticky = !row || [...row.cells].slice(0, 4).some(c => getComputedStyle(c).position === 'sticky');
    if (!sticky) { r.wideNoSticky++; if (r.tableSamples.length < 4) r.tableSamples.push(desc(t) + ' w' + Math.round(b.width)); }
  }
  return r;
};

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: W, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' });
  const report = [];
  for (const p of pages) {
    if (only && !only.includes(p || 'hub')) continue;
    const page = await ctx.newPage();
    page.on('pageerror', e => report.push({ page: p, error: String(e).slice(0, 200) }));
    await page.goto(`${BASE}/arkboard/${p ? p + '/' : ''}`, { waitUntil: 'networkidle', timeout: 90000 });
    if (SHOTS) await page.screenshot({ path: `${OUT}/${p || 'hub'}__top.png` });
    const tabs = await page.$$eval('[data-wintabs] > .wintabs__strip .wintabs__tab', els => els.map(e => e.dataset.wintab));
    const list = tabs.length ? tabs : [null];
    for (const [i, t] of list.entries()) {
      if (t !== null) {
        await page.evaluate((t) => { const b = [...document.querySelectorAll('.wintabs__tab')].find(e => e.dataset.wintab === t); b && b.click(); }, t);
        await page.waitForLoadState('networkidle').catch(() => {});
        await page.waitForTimeout(400);
      }
      const r = await page.evaluate(probe);
      r.page = p || 'hub'; r.tab = t;
      report.push(r);
      if (SHOTS) {
        const slug = `${p || 'hub'}__${String(i).padStart(2, '0')}-${(t || 'main').replace(/[^a-z0-9]+/gi, '-')}`;
        // Shot of the active panel's top, not the page header.
        const y = await page.evaluate(() => { const el = document.querySelector('[data-wintabs] > .wintabs__panels > .is-active') || document.querySelector('main') || document.body; return Math.max(0, el.getBoundingClientRect().top + scrollY - 60); });
        await page.evaluate((y) => scrollTo(0, y), y); await page.waitForTimeout(100);
        await page.screenshot({ path: `${OUT}/${slug}.png` });
      }
    }
    await page.close();
  }
  fs.writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 1));
  await browser.close();
})();
