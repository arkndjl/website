// Renders the share image and favicons into ../static, and the X/Twitter and
// YouTube banners plus the X profile picture into ./exports, from the HTML
// templates in this folder. Needs Node + Playwright (npm i -D playwright &&
// npx playwright install chromium) and ImageMagick's `convert` (used for the
// 2x -> 1x downscale and favicon.ico).
//
//   node brand/render.js
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');

const here = __dirname;
const out = path.join(here, '..', 'static');
const exportsDir = path.join(here, 'exports');
fs.mkdirSync(exportsDir, { recursive: true });

let hasConvert = true;
try { execFileSync('convert', ['-version'], { stdio: 'ignore' }); } catch { hasConvert = false; }

(async () => {
  const browser = await chromium.launch();

  // Large images: render at 2x device pixels, then downscale 50% with a box
  // filter. Text and the badge get clean anti-aliasing and the pixel glyph
  // keeps hard edges. Falls back to a 1x render without ImageMagick.
  const renderSharp = async (file, target, w, h) => {
    const scale = hasConvert ? 2 : 1;
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: scale });
    await page.goto('file://' + path.join(here, file), { waitUntil: 'networkidle' });
    await page.waitForTimeout(200);
    if (scale === 2) {
      const tmp = target + '.2x.png';
      await page.screenshot({ path: tmp });
      execFileSync('convert', [tmp, '-filter', 'Box', '-resize', '50%', '-strip', 'PNG24:' + target]);
      fs.unlinkSync(tmp);
    } else {
      await page.screenshot({ path: target });
    }
    await page.close();
    console.log('wrote', path.relative(process.cwd(), target), `${w}x${h}`);
  };
  // Small icons: render at 1x so the glyph stays on the pixel grid.
  const renderIcon = async (file, target, size) => {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    await page.goto('file://' + path.join(here, file), { waitUntil: 'networkidle' });
    await page.waitForTimeout(100);
    await page.screenshot({ path: target });
    await page.close();
    console.log('wrote', path.relative(process.cwd(), target), `${size}x${size}`);
  };

  await renderSharp('og-image.html', path.join(out, 'og-image.png'), 1200, 627);
  await renderSharp('twitter-banner.html', path.join(exportsDir, 'twitter-banner.png'), 1500, 500);
  await renderSharp('youtube-banner.html', path.join(exportsDir, 'youtube-banner.png'), 2560, 1440);
  await renderSharp('avatar.html', path.join(exportsDir, 'twitter-avatar.png'), 1000, 1000);
  await renderSharp('avatar.html#inverse', path.join(exportsDir, 'twitter-avatar-inverse.png'), 1000, 1000);

  await renderIcon('icon.html', path.join(out, 'apple-touch-icon.png'), 180);
  await renderIcon('icon.html', path.join(out, 'favicon.png'), 32);
  const icoParts = [];
  for (const s of [16, 32, 48]) {
    const p = path.join(here, `.icon-${s}.png`);
    await renderIcon('icon.html', p, s);
    icoParts.push(p);
  }
  await browser.close();
  if (hasConvert) {
    execFileSync('convert', [...icoParts, path.join(out, 'favicon.ico')]);
    console.log('wrote static/favicon.ico');
  } else {
    console.warn('favicon.ico not written (ImageMagick `convert` not available)');
  }
  for (const p of icoParts) fs.unlinkSync(p);
})().catch(e => { console.error(e); process.exit(1); });
