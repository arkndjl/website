// Renders brand/exports/pixelart/sheet.html (written by make-pixel-art.py) to
// sheet.png at 1x device pixels, so every sprite pixel is exactly 4x4 screen
// pixels. The live "loop" previews are paused on frame 0 for the still image.
// Needs Node + Playwright with Chromium (see render.js):
//
//   node brand/render-pixelart.js
//   NODE_PATH=/path/to/node_modules node brand/render-pixelart.js   (global install)
const path = require('path');
const { chromium } = require('playwright');

const dir = path.join(__dirname, 'exports', 'pixelart');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1232, height: 800 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(dir, 'sheet.html'), { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  // freeze every loop preview on frame 0
  await page.evaluate(() => new Promise(done => {
    for (const a of document.getAnimations()) { a.pause(); a.currentTime = 40; }
    requestAnimationFrame(() => requestAnimationFrame(done));
  }));
  const target = path.join(dir, 'sheet.png');
  await page.screenshot({ path: target, fullPage: true });
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  console.log('wrote', path.relative(process.cwd(), target), `1232x${height}`);
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
