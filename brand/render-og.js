// Renders one share card per ARKBOARD page into ../static/og/<page>.png from og-board.html, with frame 0 of the
// page's pixel hero. Each content/arkboard-*.md sets cover = "/og/<page>.png" (layouts/partials/head.html).
// Needs Node + Playwright and ImageMagick's `convert` (2x render, box downscale, like render.js).
//
//   node brand/render-og.js
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');

const here = __dirname, root = path.join(here, '..'), out = path.join(root, 'static', 'og');
fs.mkdirSync(out, { recursive: true });
// page, sport, what the page grades (<i> = lilac), the scale line under the hero, the short link (static/_redirects), the hero
const CARDS = [
  ['college-football', 'college football', 'every FBS + FCS player graded on the <i>20-80 FV</i> scale. 2027 draft board, mocks, recruits, portal, games.', 'FV = the mean outcome', 'cfb', 'hero-football'],
  ['college-basketball', 'college basketball', 'every D-I player and the internationals on the <i>20-80 FV</i> scale. mocks, games, power rankings.', 'FV = the mean outcome', 'cbb', 'hero-basketball'],
  ['hockey-prospects', 'hockey prospects', 'the 2027 NHL draft and every drafted prospect on the <i>20-80 FV</i> scale. NHLe, mocks.', 'FV = the mean outcome', 'hockey', 'hero-hockey'],
  ['soccer-prospects', 'soccer prospects', 'every under-22 in 33 leagues on the <i>20-80 FV</i> scale. GAR, market value, xMV.', 'FV = the mean outcome', 'u22', 'hero-soccer'],
  ['baseball', 'baseball', 'high school and college players for the MLB draft on the <i>20-80 FV</i> scale.', 'FV = the mean outcome', 'baseball', 'hero-baseball'],
  ['nfl', 'NFL', 'every player in <i>WAR</i>. game projections, season odds, power rankings, injuries.', 'WAR · xWins · odds', 'nfl', 'hero-football'],
  ['nba', 'NBA', 'every player in <i>XPM</i> and contract value. game projections, season odds.', 'XPM · xWins · odds', 'nba', 'hero-basketball'],
  ['nhl', 'NHL', 'every player in <i>WAR</i>, goalies in GSAx. game projections, season odds.', 'WAR · xWins · odds', 'nhl', 'hero-hockey'],
  ['soccer', 'soccer', "Europe's big five and the UEFA cups: players in <i>GAR</i>, game projections, season odds.", 'GAR · xPts · odds', 'soccer', 'hero-soccer'],
  ['predictions', 'predictions', 'every pick on every sport, staked in <i>DU</i> and graded against the closing line.', 'edge · DU · CLV', 'picks', 'hero-predictions'],
];
function frame0(name) {
  const svg = fs.readFileSync(path.join(root, 'layouts', 'partials', 'px', name + '.html'), 'utf8');
  const head = /<svg[^>]*>/.exec(svg)[0].replace(/ width="\d+" height="\d+"/, '').replace(/class="[^"]*"/, '');
  const f = /<g class="px__f" style="--i:0">[\s\S]*?<\/g>/.exec(svg)[0];
  return head + f + '</svg>';
}
(async () => {
  let hasConvert = true;
  try { execFileSync('convert', ['-version'], { stdio: 'ignore' }); } catch { hasConvert = false; }
  const browser = await chromium.launch();
  for (const [page, sport, sub, scale, link, hero] of CARDS) {
    const p = await browser.newPage({ viewport: { width: 1200, height: 627 }, deviceScaleFactor: hasConvert ? 2 : 1 });
    await p.goto('file://' + path.join(here, 'og-board.html'), { waitUntil: 'networkidle' });
    await p.evaluate(({ sport, sub, scale, link, svg }) => {
      const s = document.getElementById('sport'); s.textContent = sport; if (sport.length > 14) s.classList.add('long');
      document.getElementById('sub').innerHTML = sub;
      document.getElementById('scale').textContent = scale;
      const a = document.getElementById('link'); a.textContent = 'arkndjl.net/' + link; a.href = 'https://arkndjl.net/' + link;
      document.getElementById('hero').innerHTML = svg;
    }, { sport, sub, scale, link, svg: frame0(hero) });
    await document_fonts(p);
    const target = path.join(out, page + '.png');
    if (hasConvert) {
      const tmp = target + '.2x.png';
      await p.screenshot({ path: tmp });
      execFileSync('convert', [tmp, '-filter', 'Box', '-resize', '50%', '-strip', 'PNG24:' + target]);
      fs.unlinkSync(tmp);
    } else await p.screenshot({ path: target });
    await p.close();
    console.log('wrote', path.relative(process.cwd(), target));
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
async function document_fonts(p) { await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(150); }
