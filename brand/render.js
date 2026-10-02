// Renders the share image and favicons into ../static from the HTML templates
// in this folder. Needs Node + Playwright (npm i -D playwright && npx playwright
// install chromium) and, for favicon.ico, ImageMagick's `convert`.
//
//   node brand/render.js
//
// To change the eephus.io icon on the share card, replace brand/eephus-icon.png
// (any square PNG; it is shown at 34px as a circle).
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');

const here = __dirname;
const out = path.join(here, '..', 'static');

(async () => {
  const browser = await chromium.launch();
  const render = async (file, target, w, h) => {
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    await page.goto('file://' + path.join(here, file), { waitUntil: 'networkidle' });
    await page.waitForTimeout(200);
    await page.screenshot({ path: target });
    await page.close();
    console.log('wrote', path.relative(process.cwd(), target), `${w}x${h}`);
  };
  await render('og-image.html', path.join(out, 'og-image.png'), 1200, 627);
  await render('icon.html', path.join(out, 'apple-touch-icon.png'), 180, 180);
  await render('icon.html', path.join(out, 'favicon.png'), 32, 32);
  const icoParts = [];
  for (const s of [16, 32, 48]) {
    const p = path.join(here, `.icon-${s}.png`);
    await render('icon.html', p, s, s);
    icoParts.push(p);
  }
  await browser.close();
  try {
    execFileSync('convert', [...icoParts, path.join(out, 'favicon.ico')]);
    console.log('wrote static/favicon.ico');
  } catch (e) {
    console.warn('favicon.ico not written (ImageMagick `convert` not available)');
  }
  for (const p of icoParts) require('fs').unlinkSync(p);
})().catch(e => { console.error(e); process.exit(1); });
