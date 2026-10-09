#!/usr/bin/env node
// Build the College Football ARKBOARD (data/cfb.json) from public sources.
//
//     node scripts/fetch_cfb.mjs            # fetch everything, rebuild data/cfb.json
//     node scripts/fetch_cfb.mjs --offline  # rebuild from the cached pulls (re-tune the model)
//     node scripts/fetch_cfb.mjs --skip-on3 # refetch PFN + ESPN, reuse cached ON3
//     add --no-dob to skip the date-of-birth lookups
//
// Sources
//   PFN  impact rankings (QB+, RB+, WR+, TE+, OLi, EDGE+, DT+, LB+, CB+, SAF+), every FBS/FCS
//        player and every season since 2019, embedded as packed JSON in each page.
//   ON3  college roster rankings (the On3 college grade), every position, every page. ON3 sits
//        behind Cloudflare, so it is read through headless Chromium (Playwright).
//   ESPN team list (logos, colors) and every FBS roster (class year, height, weight, headshot).
//   Dates of birth (for decimal age) for everyone on the board: Wikidata (P569), then the Wikipedia
//        infobox (Wikidata wins when they disagree).
//        Found dates are kept in data/cfb_dob.json (committed, so each player is looked up once);
//        misses are retried after a week.
//   data/cfb_manual.json  hand-kept dates of birth and player notes (see the file). Grades are the model's only.
//
// Board rules (any one puts a player on the board):
//   PFN score >= 89.5 · ON3 grade >= 95 · (PFN + ON3) / 2 >= 88
//   freshman with an ON3 grade · freshman with PFN >= 80
//
// The FV model (20-80, see FV_* below and the ARKBOARD page) grades every FBS player, not just the
// board, so a grade is a rank against the whole population. Raw pulls are cached in
// scripts/.cache/cfb/ (gitignored). Needs Node 18+ and, for ON3, the playwright package
// (`npm i -D playwright`, or a global install).
import { sameName, variant } from './cfb_names.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { runModel, slimDrives } from './cfb_model.mjs';
import { playerRates, fetchGames, fetchInjuries, cfbd, teamModels, gamesModel, staffModels, mockDraft, fetchNflOrder, fetchNflNeeds } from './cfb_teams.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'cfb');
const OUT = path.join(ROOT, 'data', 'cfb.json');
const MANUAL = path.join(ROOT, 'data', 'cfb_manual.json');
const LOGOS = path.join(ROOT, 'static', 'img', 'cfb', 'logos');
const DOBS = path.join(ROOT, 'data', 'cfb_dob.json');
const CAL = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_calibration.json'), 'utf8'));
const HISTORY = path.join(ROOT, 'data', 'cfb_history.json');
const ALL_OUT = path.join(ROOT, 'static', 'data', 'cfb-all.json');
const TEAMS_OUT = path.join(ROOT, 'data', 'cfb_teams.json');
const MOCK_OUT = path.join(ROOT, 'data', 'cfb_mock.json');
const NFL_LOGOS = path.join(ROOT, 'static', 'img', 'nfl');
const STAFF_IN = path.join(ROOT, 'data', 'cfb_staff.json');
const PROJ_OUT = path.join(ROOT, 'data', 'cfb_proj.json');
const GAMES_OUT = path.join(ROOT, 'data', 'cfb_games.json');
const SEASON = 2026;
const ARGS = new Set(process.argv.slice(2));
const OFFLINE = ARGS.has('--offline');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';

// ---- board rules ---------------------------------------------------------------------------
const RULES = { pfn: 89.5, on3: 95, avg: 88, frPfn: 80 };
const INCLUDE_FCS = false; // PFN grades FBS and FCS on separate curves (rankSeason restarts), so a
                           // 95 at Colgate is not a 95 at Georgia. Flip to put FCS players on the board.

// PFN board slug -> our position group, PFN's score label, matching ON3 position(s)
const POS = [
  { pfn: 'quarterback',      g: 'QB',   label: 'QB+',   on3: ['QB'] },
  { pfn: 'running-back',     g: 'RB',   label: 'RB+',   on3: ['RB'] },
  { pfn: 'wide-receiver',    g: 'WR',   label: 'WR+',   on3: ['WR'] },
  { pfn: 'tight-end',        g: 'TE',   label: 'TE+',   on3: ['TE'] },
  { pfn: 'offensive-line',   g: 'OL',   label: 'OLi',   on3: ['OT', 'IOL'] },
  { pfn: 'edge',             g: 'EDGE', label: 'EDGE+', on3: ['EDGE'] },
  { pfn: 'defensive-tackle', g: 'DL',   label: 'DT+',   on3: ['DL'] },
  { pfn: 'linebacker',       g: 'LB',   label: 'LB+',   on3: ['LB'] },
  { pfn: 'cornerback',       g: 'CB',   label: 'CB+',   on3: ['CB'] },
  { pfn: 'safety',           g: 'S',    label: 'SAF+',  on3: ['S'] },
];
const ON3_POS = ['QB', 'RB', 'WR', 'TE', 'OT', 'IOL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ATH'];
const ON3_TO_G = Object.fromEntries(POS.flatMap(p => p.on3.map(o => [o, p.g])));
ON3_TO_G.ATH = 'ATH';

// ---- FV model --------------------------------------------------------------------------------
// 1. Production: each season's PFN score as a z-score on that season's FBS curve, blended
//    Marcel-style over three seasons (5/4/3, by snaps) and regressed toward average with FV_K
//    weighted snaps, so five games in October can't outvote two full seasons.
// 2. Talent: the ON3 college grade, as a percentile of the FBS population at the position
//    (unranked players share the percentile band below the last ranked player).
// 3. Both turn into z-scores (inverse normal of the percentile); the composite is their
//    weighted mean plus an age term (younger at the same level = more projection), a frame term
//    (height/weight for the position) and a strength-of-schedule term.
// 4. FV is scarcity: within each position, the k-th best composite is compared to how many
//    players per NFL draft class reach each outcome tier, scaled by that position's share of
//    the 22 NFL starting spots. "+" marks talent well ahead of production in a young player.
const FV_WEIGHTS = { 2026: 5, 2025: 4, 2024: 3 };
const FV_K = 1500;            // regression, in weighted snaps (~300 current-season snaps)
// talent vs production: two-predictor regression weights, b1 = (r1 - r12 r2) / (1 - r12^2), with
// scouting-grade validity ~.70 (draft slot tracks NFL careers better than production does),
// production validity ~.62 (backtest, selection-corrected) and ~.5 between them -> .52 / .36,
// normalized to .6 / .4. The other feeders are smaller, capped adjustments on top.
// Weights measured against NFL outcomes (backtest, out of sample): production carries about twice the
// signal of recruiting pedigree (R .54 vs .33 alone); team strength adds ~.12, age ~.10. On3's college
// grade has no history to test, but it is a current scouting read (the closest thing to an NFL board),
// so it shares the load with production: talent .40, production .40, pedigree (247 composite, FV_HS)
// .15 (half when On3 grades the player, since its grade already folds pedigree in), team strength .05.
const FV_W = { on3: 0.40, pfn: 0.40 };
const FV_TEAM = 0.05;           // per SD of last season's SP+ for the player's team
const FV_AGE = { pivot: 21.0, perYear: 0.25, cap: 0.75 };  // z per year younger than pivot
// draft-age effect by position (nflverse 2010-19, outcome-z per year younger at the same pick:
// WR .21, EDGE .18, OL .14, RB .13, pooled .11, QB .07, CB .02), shrunk halfway to the pooled effect
const FV_AGE_POS = { WR: 1.45, EDGE: 1.3, OL: 1.15, RB: 1.1, QB: 0.8, CB: 0.6 };
// frame: z of height and weight against FBS players at the position, weighted by how much the
// NFL pays for each at that spot (CB/QB height, OL/EDGE/DL mass, RB weight). Capped at ±FV_SIZE_CAP.
// [height, weight, BMI] per SD, for the position. Calibration found no size effect once draft slot is
// held constant, but FV predicts careers before the draft: size moves outcomes largely through draft
// capital and opportunity (small QBs go later and start less), so the unconditional effect is the
// right one. Mass helps backs and linemen, leanness receivers and corners; QBs need height and frame.
const FV_SIZE = { QB: [0.15, 0.1, 0.05], RB: [0, 0.05, 0.1], WR: [0.1, 0.05, -0.05], TE: [0.1, 0.05, 0], OL: [0.1, 0.05, 0.05],
                  EDGE: [0.1, 0.1, 0], DL: [0.05, 0.05, 0.1], LB: [0.05, 0.05, 0], CB: [0.15, 0, -0.05], S: [0.05, 0.05, 0] };
const FV_SIZE_CAP = 0.3;
const FV_SOS = { perSd: 0.1, cap: 0.2 };   // PFN strength of schedule, z within the position
// position-specific efficiency stats from PFN's line, beyond its composite score: [name, weight
// (sign = direction), optional getter for a derived rate]. z within the position (FBS, 60+ snaps),
// regressed by snaps (n / (n + 150)). Weights are provisional until the NFL-outcome fit replaces them.
const r1 = x => Math.round(x * 10) / 10;
const nz = v => (typeof v === 'number' && isFinite(v) ? v : null);
const FV_STATS = {
  QB: [['nypa', 1], ['intRate', -0.5, r => nz(r.att) ? 100 * nz(r.int) / r.att : null], ['rushYpg', 0.3, r => nz(r.gp) ? nz(r.ryds) / r.gp : null]],
  RB: [['elu', 1], ['ypc', 0.5], ['recYpg', 0.3, r => nz(r.gp) ? nz(r.recYds) / r.gp : null]],
  WR: [['ypr', 1], ['tgtSh', 0.7], ['epaTar', 0.5]],
  TE: [['epaTar', 1], ['blk', 0.5], ['yac', 0.3]],
  OL: [['prsRate', -1], ['skAllwd', -0.5]],
  EDGE: [['prsRate', 1], ['skRate', 0.5, r => nz(r.snaps) ? 100 * nz(r.sk) / r.snaps : null]],
  DL: [['prsRate', 1], ['skRate', 0.5, r => nz(r.snaps) ? 100 * nz(r.sk) / r.snaps : null]],
  LB: [['tacklePct', 1, r => nz(r.mt) != null ? 100 - r.mt : null], ['rtg', -0.5], ['tflRate', 0.3, r => nz(r.snaps) ? 100 * nz(r.tfl) / r.snaps : null]],
  CB: [['fi', 1], ['catchAllowed', -0.7, r => nz(r.catch)], ['rtg', -0.5]],
  S: [['fi', 1], ['tacklePct', 0.5, r => nz(r.mt) != null ? 100 - r.mt : null], ['rtg', -0.5]],
};
const FV_STAT = { w: 0.15, cap: 0.3 };
const FV_HS = { w: 0.15, cap: 0.3 };
// breakout timing: bonus by the college season of the first top-15% year (1st, 2nd, 3rd, 4th+),
// a small debit for a 4th-year+ player with a track record who never got there; bigger for skill spots
const FV_BREAKOUT = [0.15, 0.1, 0.03, 0];
const FV_BREAK_POS = { WR: 1.3, TE: 1.3, RB: 1.3, QB: 0.8, OL: 0.7, CB: 1, S: 1, EDGE: 1, DL: 1, LB: 1 };        // On3 high school grade: recruiting pedigree, z over graded players
const FV_COHORTS = 4;         // classes in the playing population
const FV_POS_STRENGTH = 0.5;  // how much of a position's talent gap vs other positions carries into FV
let posStrength = {};
// prospect risk: the composite is a noisy read of NFL talent, so grade the expected talent, not the
// observed rank. With a standardized composite c, expected talent is r * c (normal prior and noise),
// and its percentile sets an expected rank: N * (1 - Phi(r * c)). r = 1 would trust the board
// completely; lower r pulls everyone toward the middle of the scale.
// reliability: the out-of-sample correlation of the pre-draft composite with NFL career tier (backtest,
// all FBS, each class predicted from the others), +.05 for On3 and PFN, which it didn't have; OL's .32
// reflects that box scores have no OL production, so OL uses .6 (PFN and On3 grade blocking)
const FV_RELIABILITY = Object.fromEntries(Object.entries(CAL.reliability).map(([g, r]) => [g, g === 'OL' ? 0.6 : Math.round((r + 0.05) * 100) / 100]));
// cumulative players per draft class at or above each grade, all positions, measured on the 2010-19
// drafts (nflverse): 80 = 3+ All-Pro, 75 = 2, 70 = 1, 65 = 3+ Pro Bowls, 60 = 1, 55/50/45 = 6/4/2
// seasons as a starter, 40 = 48+ games, 35 = 16+, 30 = drafted. Undrafted players aren't in the
// data, so the 30-55 counts carry an allowance for undrafted starters (~10-25%).
const FV_TIERS = [[80, 4], [75, 6], [70, 12], [65, 19], [60, 34], [55, 55], [50, 80],
                  [45, 115], [40, 160], [35, 230], [30, 320]];
const STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const STARTER_TOTAL = Object.values(STARTERS).reduce((a, b) => a + b, 0);

// ---- helpers ---------------------------------------------------------------------------------
const sleep = ms => new Promise(r => setTimeout(r, ms));
const cachePath = name => path.join(CACHE, name);
const readCache = name => JSON.parse(fs.readFileSync(cachePath(name), 'utf8'));
const writeCache = (name, v) => fs.writeFileSync(cachePath(name), JSON.stringify(v));
const hasCache = name => fs.existsSync(cachePath(name));

async function get(url, as = 'text') {
  for (let i = 0; ; i++) {
    try {
      const r = await fetch(url, { headers: { 'user-agent': UA } });
      if (!r.ok) throw new Error(`${r.status} ${url}`);
      return as === 'json' ? await r.json() : await r.text();
    } catch (e) {
      if (i >= 3) throw e;
      await sleep(2000 * 2 ** i);
    }
  }
}

export function norm(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/g, '').replace(/[^a-z0-9]/g, '');
}

// scan a JSON value that starts at s[i] and return its end index
function jsonEnd(s, i) {
  let depth = 0, inStr = false;
  for (let j = i; j < s.length; j++) {
    const c = s[j];
    if (inStr) { if (c === '\\') j++; else if (c === '"') inStr = false; continue; }
    if (c === '"') inStr = true;
    else if (c === '{' || c === '[') depth++;
    else if (c === '}' || c === ']') { if (--depth === 0) return j + 1; }
  }
  throw new Error('unterminated JSON');
}

// ---- PFN -------------------------------------------------------------------------------------
async function fetchPfn() {
  const out = {};
  for (const p of POS) {
    const html = await get(`https://www.profootballnetwork.com/cfb-hq/impact-rankings/${p.pfn}`);
    const chunks = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)]
      .map(m => JSON.parse(m[1]));
    const s = chunks.find(c => c.includes('"packed":'));
    if (!s) throw new Error(`PFN ${p.pfn}: no packed data (page layout changed?)`);
    const i = s.indexOf('"packed":') + 9;
    const packed = JSON.parse(s.slice(i, jsonEnd(s, i)));
    out[p.g] = packed.rows.map(r => Object.fromEntries(packed.cols.map((c, k) => [c, r[k]])));
    console.log(`PFN ${p.label.padEnd(5)} ${out[p.g].length} player-seasons`);
  }
  return out;
}

// PFN industry consensus big board for the next draft: one record per prospect with the average rank
// and each analyst's rank, in the page's RSC payload
async function fetchConsensus() {
  const html = await get('https://www.profootballnetwork.com/nfl-draft-hq/industry-consensus-big-board');
  const s = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).join('');
  const out = {};
  for (const m of s.matchAll(/\{"id":"/g)) {
    try { const d = JSON.parse(s.slice(m.index, jsonEnd(s, m.index))); if (d.avgRank != null && d.name) out[d.id] = d; } catch {}
  }
  const list = Object.values(out).sort((a, b) => a.rank - b.rank);
  if (list.length < 50) throw new Error(`consensus board: only ${list.length} prospects (page layout changed?)`);
  console.log(`consensus: ${list.length} prospects`);
  return list.map(d => ({ rank: d.rank, name: d.name, pos: d.position, school: d.school, avg: Math.round(d.avgRank * 10) / 10, ranks: d.analystRanks }));
}

// ---- ON3 -------------------------------------------------------------------------------------
async function loadPlaywright() {
  for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) {
    try { return await import(spec); } catch {}
  }
  throw new Error('ON3 needs playwright: npm i -D playwright && npx playwright install chromium');
}

async function fetchOn3() {
  const { chromium } = await loadPlaywright();
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  const browser = await chromium.launch(proxy ? { proxy: { server: proxy } } : {});
  const ctx = await browser.newContext({ userAgent: UA, ignoreHTTPSErrors: !!proxy });
  const page = await ctx.newPage();
  // skip images, fonts, ads: only the server-rendered __NEXT_DATA__ is needed
  await page.route(/\.(png|jpe?g|svg|gif|webp|woff2?|css)(\?|$)|doubleclick|amazon-adsystem|googletag|ketch|confiant|recurly/,
    r => r.abort());
  const nextData = async url => {
    for (let i = 0; ; i++) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
        const t = await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent);
        if (!t) throw new Error('no __NEXT_DATA__ (blocked?)');
        return JSON.parse(t).props.pageProps;
      } catch (e) {
        if (i >= 3) throw e;
        console.log(`  retry ${url}: ${e.message.slice(0, 80)}`);
        await sleep(3000 * 2 ** i);
      }
    }
  };
  const rows = [];
  for (const pos of ON3_POS) {
    for (let pg = 1, pages = 1; pg <= pages; pg++) {
      const url = `https://www.on3.com/college/rankings/player/football/${SEASON}/?position=${pos.toLowerCase()}${pg > 1 ? `&page=${pg}` : ''}`;
      const { playerRankings: pr } = await nextData(url);
      pages = pr.pagination.pageCount;
      for (const it of pr.list) {
        const p = it.person;
        rows.push({
          name: p.name, slug: p.slug, pos: it.positionAbbreviation || p.positionAbbreviation,
          grade: p.rating?.rating ?? it.ratings?.find(r => r.type === 'On3')?.rating ?? null,
          posRank: it.positionRank, overallRank: it.overallRank, stars: p.rating?.stars,
          classYear: p.classYear, classRank: p.classRank, ht: p.formattedHeight, wt: p.weight,
          team: it.collegeTeam?.fullName || null, teamSlug: it.collegeTeam?.slug || p.status?.committedOrganizationSlug,
          teamLogo: it.collegeTeam?.assetUrl || null, color: it.collegeTeam?.primaryColor || null,
          hsGrade: it.highSchoolRating?.rating ?? null, hsStars: it.highSchoolRating?.stars ?? null,
          hsRank: it.highSchoolRating?.nationalRank ?? null,
          transfer: !!p.status?.isTransfer, headshot: p.defaultAssetUrl || null, nil: it.nilValue ?? null,
        });
      }
      console.log(`ON3 ${pos.padEnd(4)} page ${pg}/${pages}`);
    }
  }
  await browser.close();
  return rows;
}

// ---- ESPN ------------------------------------------------------------------------------------
async function fetchEspn(teamNames) {
  const all = (await get('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000', 'json'))
    .sports[0].leagues[0].teams.map(t => t.team);
  const teams = {};
  for (const t of all) {
    teams[t.id] = { id: t.id, name: t.location, full: t.displayName, abbr: t.abbreviation, color: t.color,
                    logo: t.logos?.[0]?.href || `https://a.espncdn.com/i/teamlogos/ncaa/500/${t.id}.png` };
  }
  const want = new Set(teamNames.map(n => teamIndex(teams).resolve(n)).filter(Boolean));
  const rosters = {};
  for (const id of want) {
    try {
      const d = await get(`https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/${id}/roster?limit=200`, 'json');
      const hc = d.coach?.[0];
      if (hc && teams[id]) teams[id].coach = `${hc.firstName} ${hc.lastName}`.trim();
      rosters[id] = d.athletes.flatMap(g => g.items).map(a => ({
        id: a.id, name: a.fullName, pos: a.position?.abbreviation, ht: a.displayHeight, wt: a.weight,
        cls: a.experience?.abbreviation, years: a.experience?.years, dob: a.dateOfBirth || null,
        headshot: a.headshot?.href || null,
      }));
    } catch (e) { console.log(`ESPN roster ${id}: ${e.message}`); }
    await sleep(150);
  }
  console.log(`ESPN ${Object.keys(rosters).length} rosters`);
  return { teams, rosters };
}

// school names differ between sources; resolve everything to an ESPN team id
const TEAM_ALIAS = {
  'miami(fl)': 'Miami', mississippi: 'Ole Miss', northcarolinastate: 'NC State', connecticut: 'UConn',
  louisianamonroe: 'UL Monroe', usf: 'South Florida', appalachianstate: 'App State',
  floridainternational: 'Florida International', hawaii: "Hawai'i", sanjosestate: 'San José State',
  fiugoldenpanthers: 'Florida International', connecticuthuskies: 'UConn', usfbulls: 'South Florida',
  appalachianstatemountaineers: 'App State', samhoustonstatebearkats: 'Sam Houston', delawarefightinbluehens: 'Delaware',
};
function teamIndex(teams) {
  const byLoc = {}, byFull = {};
  for (const t of Object.values(teams)) {
    (byLoc[norm(t.name)] ||= []).push(t);
    byFull[norm(t.full)] = t;
  }
  return {
    resolve(name) {
      if (!name) return null;
      const n = norm(name), raw = name.toLowerCase().replace(/\s+/g, '');
      const alias = TEAM_ALIAS[raw] || TEAM_ALIAS[n];
      if (alias) return byLoc[norm(alias)]?.[0]?.id ?? null;
      if (byFull[n]) return byFull[n].id;
      // pick the FBS-looking team when a location is shared (lowest id = oldest program entry)
      const hits = byLoc[n];
      return hits?.length ? hits.sort((a, b) => a.id - b.id)[0].id : null;
    },
  };
}

// sample size in snaps. PFN's current season carries snapsQ (or snaps); past seasons only carry
// games for the skill positions and the secondary (see SNAPS_PER_GAME). strict: snaps or nothing.
function volume(r, strict = false, g = null) {
  const n = v => (typeof v === 'number' && isFinite(v) ? v : null);
  const sn = n(r.snapsQ) ?? n(r.snaps);
  if (strict || sn != null) return sn ?? null;
  return (n(r.gp) ?? n(r.gamesQ) ?? 0) * (SNAPS_PER_GAME[g] ?? 55);
}
// past seasons carry games, not snaps, at the skill spots and in the secondary: a typical starter's
// snaps per game there, so a past season doesn't outweigh this one by the wrong units
const SNAPS_PER_GAME = { QB: 65, RB: 30, WR: 40, TE: 40, CB: 55, S: 55, OL: 65, EDGE: 50, DL: 45, LB: 55 };

// ---- model -----------------------------------------------------------------------------------
// standard normal CDF (Abramowitz-Stegun 7.1.26)
function phi(z) {
  const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
  const e = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z / 2);
  return z >= 0 ? (1 + e) / 2 : (1 - e) / 2;
}

// Acklam's inverse normal CDF
function probit(p) {
  p = Math.min(Math.max(p, 1e-4), 1 - 1e-4);
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  const lo = 0.02425;
  if (p < lo) { const q = Math.sqrt(-2 * Math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  if (p > 1 - lo) { const q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  const q = p - 0.5, r = q * q;
  return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
}

const CLASS_NAMES = ['Fr', 'So', 'Jr', 'Sr', 'Gr'];
// eligibility class for fall SEASON from the high school class year and the redshirt flag
function classFrom(classYear, redshirt) {
  const years = SEASON + 1 - classYear;               // seasons on campus, this one included
  const elig = Math.max(1, years - (redshirt ? 1 : 0));
  return { years, elig, label: (redshirt ? 'RS-' : '') + CLASS_NAMES[Math.min(elig, 5) - 1] };
}

function ageOn(dob, when) {
  return Math.round(((when - new Date(dob)) / (365.2425 * 864e5)) * 10) / 10;
}

// FV from an expected rank, per position, against measured outcome counts: CAL.tiers[g] holds the mean
// number of players per draft class at or above each grade at that position (drafts 2012-18: QBs ~2.9
// Pro Bowlers a class, OL ~6.4, TEs ~1.7). A rank between two anchors interpolates on a log scale; the
// bottom anchor (20) is the whole graded pool at the position per class.
// The measured counts are noisy at the top (one Pro Bowl more or less in seven drafts moves a tier), so
// each position's curve is smoothed: log-linear in FV over 30-55, where every position has plenty of
// players; above 55 it falls at the pooled rate of all positions (-0.115 log points per FV point,
// measured over 60-80), and then is scaled by positional value: an elite RB or LB is worth less on the
// NFL draft board than an equally rare QB, EDGE or tackle (APY and draft-slot value by position).
const FV_POS_VALUE = { QB: 1, OL: 1, EDGE: 1, WR: 1, CB: 1, DL: 0.7, TE: 0.75, S: 0.75, LB: 0.7, RB: 0.7 };
// the 35-50 tiers are games-played thresholds, which undercount QBs: one plays, so a starter-quality
// backup can sit for years. QB counts there x1.6, easing back to the measured curve by 55.
const FV_QB_MID = 1.6;
// scouting consensus: PFN's industry consensus big board (the average of seven analyst boards: PFN,
// CBS, ESPN, James Foster, NBC, The Athletic, Yahoo). In the backtest (2015-19 drafts, players on a
// pre-draft board) consensus rank alone explained 34% of NFL outcome (R .52) against 4% for box-score
// production and recruiting, so it is blended into FV rather than added to the composite: the rank
// maps onto the FV scale by the measured per-class counts (rank 2.7 -> 80, 27 -> 60, 126 -> 45:
// 80 - 8.7 ln(rank / 2.7)), weighted CONS_W at full coverage, less when fewer analysts rank him.
const CONS_W = 0.35, CONS_BOARDS = 7;
// xNIL program budgets (football, per season) and the fitted split (see the xNIL block in build())
const XNIL = { p4: 20e6, g5: 3e6, tilt: 0.3, k: 1.1 };
const consFV = avg => Math.max(30, Math.min(80, 80 - 8.7 * Math.log(Math.max(1, avg) / 2.7)));
const FV_TOP_SLOPE = -0.115;
const TIERS = Object.fromEntries(Object.entries(CAL.tiers).map(([g, a]) => {
  const pts = a.filter(([f, n]) => f >= 30 && f <= 55 && n > 0).map(([f, n]) => [f, Math.log(n)]);
  const mx = pts.reduce((s, p) => s + p[0], 0) / pts.length, my = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  const b = pts.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0) / pts.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
  const at = f => f <= 55 ? Math.exp(my + b * (f - mx)) : Math.exp(my + b * (55 - mx) + FV_TOP_SLOPE * (f - 55));
  const pv = f => (1 - (1 - (FV_POS_VALUE[g] ?? 1)) * Math.min(1, Math.max(0, (f - 50) / 10)))
    * (g === 'QB' ? 1 + (FV_QB_MID - 1) * Math.min(1, Math.max(0, (55 - f) / 10)) : 1);
  return [g, [80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30].map(f => [f, Math.round(at(f) * pv(f) * 1000) / 1000])];
}));
function fvFromRank(rankPerClass, g, poolPerClass) {
  const anchors = [...(TIERS[g] || [])].map(([f, n]) => [f, n]);
  anchors.push([20, Math.max(poolPerClass, (anchors.at(-1)?.[1] ?? 1) * 2)]);
  for (let i = 1; i < anchors.length; i++) anchors[i][1] = Math.max(anchors[i][1], anchors[i - 1][1] * 1.08);   // strictly rising
  const x = Math.log(rankPerClass);
  if (x <= Math.log(anchors[0][1])) return anchors[0][0];
  for (let i = 1; i < anchors.length; i++) {
    const [f0, n0] = anchors[i - 1], [f1, n1] = anchors[i];
    if (x <= Math.log(n1)) return Math.round(f0 + (f1 - f0) * (x - Math.log(n0)) / (Math.log(n1) - Math.log(n0)));
  }
  return 20;
}

// NFL frame: FV points from the draft-slot effect of size against drafted players at the position
// (combine 2010-25): below the 10th percentile costs per SD short, between p10 and p90 a small slope,
// above p90 (EDGE weight, RB/TE height) costs too. Halved: size moves draft slot more than careers.
function frameFV(p) {
  const key = p.g === 'OL' ? (/T$/.test(p.pfnPos || '') ? 'OT' : 'IOL') : p.g, n = CAL.size[key];
  if (!n || !p.htIn || !p.wtLb) return 0;
  let fv = 0;
  for (const [m, x] of [['ht', p.htIn], ['wt', p.wtLb]]) {
    const q = n[m], h = n.hinge || {};
    if (!q) continue;
    if (x < q.p10) fv -= Math.abs(h[m + '_lo'] ?? 0) * (q.p10 - x) / q.sd;
    else if (x > q.p90) fv += (h[m + '_hi'] ?? 0) < 0 ? h[m + '_hi'] * (x - q.p90) / q.sd : 0;
    else fv += Math.max(0, h[m + '_mid'] ?? 0) * (x - q.p50) / q.sd * 0.5;
  }
  return Math.max(-8, Math.min(3, fv * 0.5));
}

function build({ pfn, on3, espn, manual, dobStore = {}, recruits = {}, teamSp = {}, consensus = [] }) {
  const asof = new Date();
  const idx = teamIndex(espn.teams);
  const rosterByTeam = {};
  for (const [tid, list] of Object.entries(espn.rosters)) {
    rosterByTeam[tid] = {};
    for (const a of list) (rosterByTeam[tid][norm(a.name)] ||= []).push(a);
  }
  const espnFind = (tid, name) => rosterByTeam[tid]?.[norm(name)]?.[0] || variant(espn.rosters[tid], name);

  // ON3 by normalized name, disambiguated by team
  const on3ByName = {}, on3ByTeam = {};
  for (const o of on3) {
    o.tid = idx.resolve(o.team) || idx.resolve((o.teamSlug || '').replace(/-/g, ' '));
    (on3ByName[norm(o.name)] ||= []).push(o);
    if (o.tid) (on3ByTeam[o.tid] ||= []).push(o);
  }
  const on3Find = (name, tid, g) => {
    const hits = on3ByName[norm(name)] || [];
    return hits.find(o => o.tid === tid) || (hits.length === 1 && hits[0].tid == null ? hits[0] : null)
        || hits.find(o => ON3_TO_G[o.pos] === g && hits.length === 1)
        || (tid ? variant((on3ByTeam[tid] || []).filter(o => !ON3_TO_G[o.pos] || ON3_TO_G[o.pos] === g), name) : null) || null;   // "Sammy" on PFN, "Samuel" on On3
  };

  const players = [];
  const usedOn3 = new Set();
  // every FBS season since 2019, by player name, on its own curve: z within (position, season). PFN
  // changes ids (Jr. suffixes) and positions (S to CB), so careers are keyed by name and checked by school
  const careers = {};
  for (const p of POS) {
    const seasons = pfn[p.g], curve = {};
    for (const r of seasons) if (r.division === 'FBS') (curve[r.season] ||= []).push(r.score);
    for (const k of Object.keys(curve)) {
      const xs = curve[k], m = xs.reduce((a, b) => a + b, 0) / xs.length;
      curve[k] = { m, sd: Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length) || 1 };
    }
    for (const r of seasons) if (r.division === 'FBS' && curve[r.season])
      (careers[norm(r.name)] ||= []).push({ g: p.g, team: r.team, tid: idx.resolve(r.team), season: r.season,
        z: (r.score - curve[r.season].m) / curve[r.season].sd, vol: volume(r, false, p.g) });
    for (const r of seasons.filter(x => x.season === SEASON)) {
      if (r.division !== 'FBS' && !INCLUDE_FCS) continue;
      const tid = idx.resolve(r.team);
      const o = on3Find(r.name, tid, p.g);
      if (o) usedOn3.add(o);
      players.push({ name: r.name, g: p.g, label: p.label, pfnId: r.id, pfnPos: r.pos || null,
        team: r.team, tid, conf: r.conf, div: r.division, pfn: r.score, snaps: volume(r, true), gp: r.gp ?? r.gamesQ ?? null,
        sos: typeof r.sos === 'number' ? r.sos : null, row: r, on3: o });
    }
  }
  // a player PFN lists at two positions (EDGE and LB, S and CB) is one player: keep the line with
  // more snaps this season, so he isn't double-counted in either pool or drafted twice
  {
    const best = new Map();
    for (const p of players) {
      const k = norm(p.name) + '|' + p.tid, cur = best.get(k);
      if (!cur || (p.snaps ?? 0) > (cur.snaps ?? 0)) best.set(k, p);
    }
    const keep = new Set(best.values());
    for (let i = players.length - 1; i >= 0; i--) if (!keep.has(players[i])) players.splice(i, 1);
  }
  // ON3-ranked FBS players with no PFN line this season (injured, not yet playing, ATH)
  for (const o of on3) {
    if (usedOn3.has(o) || o.grade == null) continue;
    // already on the board under another spelling ("Samuel" on On3, "Sammy" on PFN): attach, don't add
    const dup = o.tid && players.find(q => q.tid === o.tid && !q.on3 && sameName(q.name, o.name) && (!ON3_TO_G[o.pos] || ON3_TO_G[o.pos] === q.g));
    if (dup) { dup.on3 = o; usedOn3.add(o); continue; }
    const g = ON3_TO_G[o.pos] || 'ATH';
    players.push({ name: o.name, g, label: POS.find(p => p.g === g)?.label || null, team: o.team, tid: o.tid,
      conf: null, div: 'FBS', pfn: null, snaps: null, gp: null, on3: o, noLine: true });
  }

  // production, Marcel-style for everyone: the last three seasons (5/4/3, by snaps), any position,
  // regressed to average (z = 0) with FV_K weighted snaps. A season counts when it was at the player's
  // current school, or when his name is unique in FBS that season (so transfers keep their history
  // and namesakes don't share it). A player with no line at all sits at average production.
  const nameCount = {};
  for (const [n, list] of Object.entries(careers)) for (const h of list) {
    const k = n + '|' + h.season; nameCount[k] = (nameCount[k] || new Set()).add(h.tid);
  }
  for (const p of players) {
    const n = norm(p.name), bySeason = {};
    for (const h of careers[n] || []) {
      if (!FV_WEIGHTS[h.season]) continue;
      if (h.tid !== p.tid && nameCount[n + '|' + h.season].size > 1) continue;
      if (!bySeason[h.season] || h.vol > bySeason[h.season].vol) bySeason[h.season] = h;   // one line per season
    }
    let num = 0, w = 0;
    for (const h of Object.values(bySeason)) { const x = FV_WEIGHTS[h.season] * h.vol; num += x * h.z; w += x; }
    p.marcel = num / (w + FV_K); p.marcelW = w; p.seasons = Object.keys(bySeason).length;
    p.priorOnly = !!p.noLine && p.seasons > 0;
  }
  // production z: the regressed blend standardized within the position (no rank step, so the
  // regression survives: a small sample stays near the middle)
  for (const g of [...new Set(players.map(p => p.g))]) {
    const grp = players.filter(p => p.g === g), xs = grp.map(p => p.marcel);
    const m = xs.reduce((a, b) => a + b, 0) / xs.length, sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length) || 1;
    for (const p of grp) p.zPfn = (p.marcel - m) / sd;
  }
  // breakout: the first college season at a top-15% level (z >= 1.04 on that season's curve, real
  // volume) and how early it came, counted from the high school class
  for (const p of players) {
    const first = (careers[norm(p.name)] || []).filter(h => h.z >= 1.04 && h.vol >= 150 && (h.tid === p.tid || nameCount[norm(p.name) + '|' + h.season].size === 1))
      .map(h => h.season).sort()[0];
    p.firstBreak = first ?? null;
  }

  // identity, class, age
  const dobs = manual.dob || {};
  for (const p of players) {
    const e = p.tid ? espnFind(p.tid, p.name) : null;
    const t = p.tid ? espn.teams[p.tid] : null;
    const o = p.on3;
    let cls = null;
    if (o?.classYear) cls = classFrom(o.classYear, /redshirt/i.test(o.classRank || ''));
    // ESPN's class is eligibility with no redshirt flag (about half of players are a year further
    // along): half a year added for age, and draft eligibility read off the eligibility class
    else if (e?.years) cls = { years: e.years + 0.5, elig: e.years, label: CLASS_NAMES[Math.min(e.years, 5) - 1] };
    const key = `${p.name}|${t?.name || p.team}`;
    const dob = dobs[key] || dobs[p.name] || (plausible(dobStore[key]?.dob) ? dobStore[key].dob : null) || e?.dob || null;
    const age = dob ? ageOn(dob, asof) : null;
    const ageEst = age ?? (cls ? 17.9 + cls.years : null);       // ~18.9 for a first-year in October
    p.rec = e ? recruits[e.id] || null : null;   // CFBD 247 composite, by ESPN athlete id
    Object.assign(p, { espn: e, team: t?.name || p.team, logo: t?.logo || o?.teamLogo || null,
      color: t?.color ? `#${t.color}` : o?.color || null, cls, dob, age, ageEst });
  }

  // talent: On3's order within the position as a normal score (rank-normal, so every position has the
  // same shape). Grade ties at 99 break by On3's overall rank, then position rank. Unranked players fill
  // the band below (see the unranked note).
  const tieKey = o => o.overallRank ?? 1e4 + (o.posRank ?? 99) * 11;
  for (const g of [...new Set(players.map(p => p.g))]) {
    const grp = players.filter(p => p.g === g), N = grp.length;
    const ranked = grp.filter(p => p.on3?.grade != null).sort((a, b) => b.on3.grade - a.on3.grade || tieKey(a.on3) - tieKey(b.on3));
    ranked.forEach((p, i) => { p.zOn3 = probit(1 - (i + 0.5) / N); });
    // unranked isn't "bad": On3 grades 75 per position and can miss. Order them by production and
    // recruiting pedigree together and spread them through their band at 0.8 strength, so a productive,
    // well-recruited unranked player sits near the cutoff instead of in a flat block
    const pm = grp.reduce((a, p) => a + p.marcel, 0) / N, psd = Math.sqrt(grp.reduce((a, p) => a + (p.marcel - pm) ** 2, 0) / N) || 1;
    const key = p => 0.6 * (p.marcel - pm) / psd + 0.4 * (p.rec?.rating != null ? (p.rec.rating - 0.85) / 0.04 : -1);
    const rest = grp.filter(p => p.on3?.grade == null).sort((a, b) => key(b) - key(a));
    const zMid = probit((N - ranked.length) / 2 / N);
    rest.forEach((p, j) => { const zr = probit(1 - (ranked.length + j + 0.5) / N); p.zOn3 = zMid + 0.8 * (zr - zMid); });
  }
  // position strength uses the On3 grade itself (one scale across positions): the mean grade->z of
  // each position's top (5 x starting spots) ranked players against the average position
  {
    const pts = players.filter(p => p.on3?.grade != null && p.zOn3 != null);
    const mx = pts.reduce((a, p) => a + p.on3.grade, 0) / pts.length, my = pts.reduce((a, p) => a + p.zOn3, 0) / pts.length;
    const b = pts.reduce((a, p) => a + (p.on3.grade - mx) * (p.zOn3 - my), 0) / pts.reduce((a, p) => a + (p.on3.grade - mx) ** 2, 0);
    for (const p of pts) p.zGrade = my + b * (p.on3.grade - mx);
  }

  for (const p of players) {
    const classYear = p.on3?.classYear ?? (p.cls ? Math.round(SEASON + 1 - p.cls.years) : null);
    p.breakYear = p.firstBreak && classYear ? p.firstBreak - classYear + 1 : null;     // 1 = first season on campus
    const m = FV_BREAK_POS[p.g] ?? 1;
    p.breakZ = p.breakYear == null ? (p.cls?.years >= 4 && p.seasons >= 2 ? -0.05 * m : 0)
      : (FV_BREAKOUT[Math.max(1, Math.min(p.breakYear, 4)) - 1] ?? 0) * m;
  }

  // composite and FV
  const inches = h => { const m = /^(\d)\D+(\d+(?:\.\d+)?)/.exec(h || ''); return m ? +m[1] * 12 + +m[2] : null; };
  const zOf = (xs, x) => {
    const v = xs.filter(n => n != null);
    const m = v.reduce((a, b) => a + b, 0) / v.length, sd = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / v.length) || 1;
    return x == null ? 0 : (x - m) / sd;
  };
  const clamp = (x, c) => Math.max(-c, Math.min(c, x));
  for (const p of players) {
    p.htIn = inches(p.on3?.ht) ?? inches(p.espn?.ht) ?? (p.rec?.ht || null);
    p.wtLb = p.on3?.wt || p.espn?.wt || p.rec?.wt || null;
  }
  for (const p of players) p.bmi = p.htIn && p.wtLb ? 703 * p.wtLb / p.htIn ** 2 : null;
  const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
  // recruiting pedigree: the 247 composite rating (CFBD) for nearly every scholarship player, else On3's
  // high school grade rescaled; no record at all (walk-on) sits at the bottom of the recruited range
  const hsAll = players.map(p => p.rec?.rating ?? null).filter(v => v != null);
  const hsMean = hsAll.reduce((a, b) => a + b, 0) / Math.max(1, hsAll.length);
  const hsSd = Math.sqrt(hsAll.reduce((a, b) => a + (b - hsMean) ** 2, 0) / Math.max(1, hsAll.length)) || 1;
  for (const p of players) {
    p.hsRaw = p.rec?.rating != null ? (p.rec.rating - hsMean) / hsSd
      : p.on3?.hsGrade != null ? (p.on3.hsGrade / 100 - hsMean) / hsSd : p.espn ? -1.5 : null;
  }
  for (const g of Object.keys(FV_SIZE)) {
    const grp = players.filter(p => p.g === g), [cH, cW, cB] = FV_SIZE[g];
    const hs = grp.map(p => p.htIn), ws = grp.map(p => p.wtLb), bs = grp.map(p => p.bmi), ss = grp.map(p => p.sos);
    // efficiency stats: z among FBS players at the position with 60+ snaps this season
    const qual = grp.filter(p => (p.snaps ?? 0) >= 60);
    const cols = (FV_STATS[g] || []).map(([f, w, get]) => {
      const val = r => (r ? (get ? nz(get(r)) : num(r[f])) : null);
      return { w, f, val, xs: qual.map(p => val(p.row)) };
    });
    for (const p of grp) {
      p.sizeZ = clamp(cH * zOf(hs, p.htIn) + cW * zOf(ws, p.wtLb) + cB * zOf(bs, p.bmi), FV_SIZE_CAP);
      // PFN's grades already adjust for opponents everywhere but QB (score and SOS correlate +.24 to
      // +.46 at other spots, -.29 at QB), so schedule only counts for quarterbacks
      p.sosZ = g === 'QB' ? clamp(FV_SOS.perSd * zOf(ss, p.sos), FV_SOS.cap) : 0;
      let sz = 0, sw = 0;
      p.statDetail = [];
      if (p.row && (p.snaps ?? 0) >= 60) for (const c of cols) {
        const v = c.val(p.row); if (v == null) continue;
        const z = zOf(c.xs, v);
        sz += c.w * z; sw += Math.abs(c.w);
        p.statDetail.push({ f: c.f, v, z: Math.sign(c.w) * z });   // z signed so + is always good
      }
      const rel = (p.snaps ?? 0) / ((p.snaps ?? 0) + 150);
      p.statZ = sw ? clamp(FV_STAT.w * rel * sz / sw, FV_STAT.cap) : 0;
      p.hsZ = p.hsRaw != null ? clamp(FV_HS.w * p.hsRaw, FV_HS.cap) * (p.on3?.grade != null ? 0.5 : 1) : 0;
    }
  }
  for (const p of players) {
    const am = FV_AGE_POS[p.g] ?? 1;
    p.ageZ = p.ageEst == null ? 0 : clamp((FV_AGE.pivot - p.ageEst) * FV_AGE.perYear * am, FV_AGE.cap * am);
    // youth is worth something when the player is already producing: the bonus scales with production
    // (age-adjusted production); being old for the class costs in full either way
    if (p.ageZ > 0) p.ageZ *= Math.min(1, Math.max(0, (p.zPfn + 1) / 2.5));
    p.sizeZ ??= 0; p.sosZ ??= 0; p.statZ ??= 0; p.hsZ ??= 0; p.breakZ ??= 0;
    // production counts less for players who were never blue-chips (backtest: tier = 22.5 + 3.2 prod +
    // 3.1 bluechip + 3.2 prod x bluechip, i.e. half as much); On3 and PFN partly re-rate them, so 0.75
    const blue = (p.rec?.stars ?? 0) >= 4 || p.on3?.grade != null;
    p.prodEff = p.zPfn * (blue || p.zPfn < 0 ? 1 : 0.75);
    p.teamZ = clamp(FV_TEAM * (teamSp[p.tid] ?? 0), 0.15);
    p.comp = FV_W.on3 * p.zOn3 + FV_W.pfn * p.prodEff + p.ageZ + p.breakZ + p.sosZ + p.statZ + p.hsZ + p.teamZ;
  }
  // the composite as a rank-normal score within the position (every position the same shape, honest
  // tails), shifted by position strength: a position whose top players grade lower on On3's one scale
  // gets fewer high grades (FV_POS_STRENGTH of the gap). Then expected talent = r * z, where r is the
  // composite's validity, and its percentile sets an expected rank for the scarcity tiers.
  const topTalent = {};
  for (const g of Object.keys(STARTERS)) {
    const top = players.filter(p => p.g === g && p.zGrade != null).map(p => p.zGrade).sort((a, b) => b - a).slice(0, 5 * STARTERS[g]);
    topTalent[g] = top.reduce((a, b) => a + b, 0) / Math.max(1, top.length);
  }
  const avgTop = Object.values(topTalent).reduce((a, b) => a + b, 0) / Object.keys(topTalent).length;
  for (const g of Object.keys(STARTERS)) {
    const grp = players.filter(p => p.g === g).sort((a, b) => b.comp - a.comp), N = grp.length;
    // standardized, not ranked: a player far ahead of the next one (a Jeremiah Smith) keeps the gap
    const m = grp.reduce((a, q) => a + q.comp, 0) / N, sd = Math.sqrt(grp.reduce((a, q) => a + (q.comp - m) ** 2, 0) / N) || 1;
    const shift = FV_POS_STRENGTH * (topTalent[g] - avgTop), r = FV_RELIABILITY[g];
    grp.forEach((p, i) => {
      p.compZ = (p.comp - m) / sd + shift;
      const expRank = Math.max(0.5, N * (1 - phi(r * p.compZ)));
      p.fvBase = fvFromRank(expRank / FV_COHORTS, g, N / FV_COHORTS);
      // after the scarcity grade: NFL frame, and time spent in college (-1 per year past three, -2 at
      // QB and S: each extra year at the same draft slot costs ~0.8-2 tiers in the backtest)
      p.frameFV = Math.round(frameFV(p) * 10) / 10;
      const extra = Math.max(0, (p.cls?.years ?? 3) - 3);
      p.yearsFV = -extra * (g === 'QB' || g === 'S' ? 2 : 1);
      p.fv = Math.max(20, Math.min(80, Math.round(p.fvBase + p.frameFV + p.yearsFV)));
      p.posRank = i + 1;
    });
  }
  // scouting consensus (draft-eligible prospects on PFN's industry board): FV moves toward the grade
  // the consensus rank implies, by CONS_W x sqrt(share of the seven boards that rank him)
  const byName = {};
  for (const p of players) (byName[norm(p.name)] ||= []).push(p);
  for (const c of consensus || []) {
    const cands = byName[norm(c.name)] || [], tid = idx.resolve(c.school);
    const p = cands.find(q => q.tid === tid) || (cands.length === 1 ? cands[0] : null) || variant(players.filter(q => q.tid === tid), c.name);
    if (!p || p.fv == null) continue;
    const n = Object.keys(c.ranks || {}).length, w = CONS_W * Math.sqrt(Math.min(n, CONS_BOARDS) / CONS_BOARDS), cf = consFV(c.avg);
    p.cons = { rank: c.rank, avg: c.avg, n, fv: Math.round(cf) };
    p.fvModel = p.fv; p.consAdj = Math.round((cf - p.fv) * w * 10) / 10;
    p.fv = Math.max(20, Math.min(80, Math.round(p.fv + (cf - p.fv) * w)));
  }
  // position rank by the final grade (the composite breaks ties)
  for (const g of Object.keys(STARTERS)) players.filter(p => p.g === g && p.fv != null)
    .sort((a, b) => b.fv - a.fv || b.comp - a.comp).forEach((p, i) => { p.posRank = i + 1; });
  posStrength = Object.fromEntries(Object.entries(topTalent).map(([g, v]) => [g, Math.round((v - avgTop) * 100) / 100]));
  for (const p of players) {
    if (p.fv == null) p.fv = null;                  // ATH: no NFL position to grade against yet
    // "+": a young, highly ranked talent whose production hasn't caught up yet
    p.plus = p.fv != null && p.fv < 80 && p.on3?.grade != null && p.zOn3 >= 1.5 && p.ageEst != null && p.ageEst <= 20.5 && p.zOn3 - p.zPfn >= 0.75;
  }

  // xNIL (expected NIL): what the market should pay a player, as a share of his program's budget.
  // 1) market index: log(On3 NIL valuation) fitted (ridge) on FV, FV^2, Power-4 status, position,
  //    FV x QB (QBs' value climbs faster with grade), snap share, On3 grade and consensus rank, over
  //    the ~270 players On3 values (cross-validated R^2 .42 -> .46 over FV and position alone).
  // 2) budgets: those 270 are the top of the market, so a fit on them alone prices walk-ons at $500K+
  //    (selection bias). Each program instead splits a budget anchored outside the data: the House
  //    settlement revenue-share cap ($20.5M, ~75% to football) plus outside NIL, ~$20M at Power 4 and
  //    Notre Dame, ~$3M in the Group of Five, tilted by roster talent (x e^(.3 z)). Shares follow
  //    e^(1.1 x index), fitted to On3's valuations (R^2 .47, mean error ~0; FBS total ~$2B).
  {
    const P4 = new Set(['SEC', 'Big Ten', 'Big 12', 'ACC', 'IND (FBS)']);
    const posList = Object.keys(STARTERS);
    const feats = p => { const f = (p.fv - 50) / 10; return [1, f, f * f, P4.has(p.conf) ? 1 : 0, ...posList.slice(1).map(g => (p.g === g ? 1 : 0)),
      p.g === 'QB' ? f : 0, Math.min(1, (p.snaps ?? 0) / 250), ((p.on3?.grade ?? 85) - 90) / 5, Math.log(p.cons?.avg ?? 300)]; };
    const train = players.filter(p => p.fv != null && p.on3?.nil > 0);
    if (train.length > 50) {
      const X = train.map(feats), y = train.map(p => Math.log(p.on3.nil)), k = X[0].length;
      const A = Array.from({ length: k }, (_, i) => Array.from({ length: k }, (_, j) => X.reduce((a, r) => a + r[i] * r[j], 0) + (i === j && i ? 0.5 : 0)));
      const bv = Array.from({ length: k }, (_, i) => X.reduce((a, r, n) => a + r[i] * y[n], 0));
      for (let c = 0; c < k; c++) {           // Gauss-Jordan
        const piv = A[c][c] || 1e-9;
        for (let j = c; j < k; j++) A[c][j] /= piv; bv[c] /= piv;
        for (let r = 0; r < k; r++) if (r !== c) { const f = A[r][c]; for (let j = c; j < k; j++) A[r][j] -= f * A[c][j]; bv[r] -= f * bv[c]; }
      }
      const byTeam = {};
      for (const p of players) if (p.fv != null && p.tid) (byTeam[p.tid] ||= []).push(p);
      // roster talent: mean On3 talent z of each team's projected starters, as z across FBS
      const tal = Object.fromEntries(Object.entries(byTeam).map(([tid, ps]) => {
        const st = [];
        for (const [g, n] of Object.entries(STARTERS)) st.push(...ps.filter(p => p.g === g).sort((a, b) => b.zOn3 - a.zOn3).slice(0, n));
        return [tid, st.reduce((a, p) => a + p.zOn3, 0) / Math.max(1, st.length)];
      }));
      const tv = Object.values(tal), tm = tv.reduce((a, b) => a + b, 0) / tv.length, tsd = Math.sqrt(tv.reduce((a, b) => a + (b - tm) ** 2, 0) / tv.length) || 1;
      for (const [tid, ps] of Object.entries(byTeam)) {
        const budget = (P4.has(ps[0].conf) ? XNIL.p4 : XNIL.g5) * Math.exp(XNIL.tilt * (tal[tid] - tm) / tsd);
        const w = ps.map(p => Math.exp(XNIL.k * feats(p).reduce((a, x, i) => a + x * bv[i], 0))), sw = w.reduce((a, b) => a + b, 0);
        ps.forEach((p, i) => { p.xnil = Math.round(budget * w[i] / sw / 1000) * 1000; });
      }
    }
  }

  // one row per graded player; the board is the subset that meets a board rule
  const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100;
  const rows = [];
  for (const p of players) {
    const on3g = p.on3?.grade ?? null;
    const fr = p.cls ? p.cls.elig === 1 : false;
    const avg = p.pfn != null && on3g != null ? (p.pfn + on3g) / 2 : null;
    const why = [];
    if (p.pfn != null && p.pfn >= RULES.pfn) why.push('pfn');
    if (on3g != null && on3g >= RULES.on3) why.push('on3');
    if (avg != null && avg >= RULES.avg) why.push('avg');
    if (fr && on3g != null) why.push('fr-on3');
    if (fr && p.pfn != null && p.pfn >= RULES.frPfn) why.push('fr-pfn');
    const m = manual.players?.[`${p.name}|${p.team}`] || manual.players?.[p.name] || {};
    rows.push({
      name: p.name, pos: p.g, spot: p.pfnPos || (p.on3?.pos && p.on3.pos !== p.g ? p.on3.pos : null),
      team: p.team, tid: p.tid || null, logo: p.logo, color: p.color, conf: p.conf, div: p.div,
      cls: p.cls?.label ?? null, elig: p.cls?.elig ?? null, rs: !!p.cls?.label?.startsWith('RS'),
      age: p.age, ageEst: p.age == null && p.ageEst != null ? r1(p.ageEst) : null, dob: p.dob,
      ht: p.on3?.ht || p.espn?.ht?.replace(/[' "]+/g, '-').replace(/-$/, '') || null, wt: p.on3?.wt || p.espn?.wt || null,
      pfn: p.pfn, pfnLabel: p.label, snaps: p.snaps, gp: p.gp,
      on3: on3g, on3Rank: p.on3?.overallRank ?? null, on3PosRank: p.on3?.posRank ?? null,
      hsStars: p.on3?.hsStars ?? null, hsGrade: p.on3?.hsGrade ?? null, transfer: p.on3?.transfer ?? null,
      xnil: p.xnil ?? null,
      cons: p.cons?.avg ?? null, consRk: p.cons?.rank ?? null, consN: p.cons?.n ?? null, fvModel: p.fvModel ?? null, consAdj: p.consAdj ?? null,
      avg: avg == null ? null : r1(avg),
      fv: p.fv, plus: p.plus,
      posRank: p.posRank ?? null,
      comp: Math.round(p.comp * 1000) / 1000, prodZ: r2(p.zPfn), talentZ: r2(p.zOn3),
      ageZ: r2(p.ageZ), sizeZ: r2(p.sizeZ), sosZ: r2(p.sosZ), statZ: r2(p.statZ), hsZ: r2(p.hsZ),
      // what each feeder adds to the composite (weighted), in the order the breakdown shows them
      parts: [FV_W.on3 * p.zOn3, FV_W.pfn * p.prodEff, p.ageZ, p.breakZ, p.statZ, p.hsZ, p.sosZ + p.teamZ, p.frameFV / 10].map(r2),
      fvBase: p.fvBase, frameFV: p.frameFV, yearsFV: p.yearsFV,
      breakYear: p.breakYear, priorOnly: !!p.priorOnly,
      report: scoutReport(p),
      bmi: p.bmi ? r1(p.bmi) : null,
      draft27: p.cls ? p.cls.years >= 3 : null,
      note: m.note || null, why,
      links: {
        on3: p.on3 ? `https://www.on3.com/rivals/${p.on3.slug}/` : null,
        espn: p.espn ? `https://www.espn.com/college-football/player/_/id/${p.espn.id}` : null,
      },
    });
  }
  const byFv = (a, b) => (b.fv ?? -1) - (a.fv ?? -1) || (b.plus - a.plus) || b.comp - a.comp;
  rows.sort(byFv);
  // positional rank by grade (hand grades included), e.g. WR3
  const seen = {};
  for (const r of rows) r.posRank = r.fv == null ? null : (seen[r.pos] = (seen[r.pos] || 0) + 1);
  rows.forEach((r, i) => { r.ovr = i + 1; });
  // the players worth exact birthdates and a place in data/cfb.json: the top 400 by FV
  const board = rows.filter(r => r.fv != null).slice(0, 400);
  board.forEach((p, i) => { p.rk = i + 1; });
  // FV distribution, 5-point tiers: the whole graded population and the board
  const dist = (list) => {
    const d = {};
    for (const r of list) if (r.fv != null) { const t = Math.min(80, Math.floor(r.fv / 5) * 5); d[t] = (d[t] || 0) + 1; }
    return d;
  };
  const unmatched = players.filter(p => !p.tid).map(p => p.team);
  if (unmatched.length) console.log('teams without an ESPN match:', [...new Set(unmatched)].join(', '));
  return {
    asof: asof.toISOString().slice(0, 10), season: SEASON, rules: RULES, includeFcs: INCLUDE_FCS,
    population: rows.filter(r => r.fv != null).length, count: board.length,
    dist: { all: dist(rows), draft: dist(rows.filter(r => r.draft27)) },
    summary: { graded: rows.filter(r => r.fv != null).length, n60: rows.filter(r => r.fv >= 60).length, n50: rows.filter(r => r.fv >= 50).length,
      draft: rows.filter(r => r.draft27 && r.fv != null).length, fr: rows.filter(r => r.elig === 1 && r.fv != null).length },
    posStrength, model: { stats: Object.fromEntries(Object.entries(FV_STATS).map(([g, l]) => [g, l.map(([f, w]) => [f, w])])), stat: FV_STAT, hs: FV_HS, weights: FV_WEIGHTS, k: FV_K, w: FV_W, age: FV_AGE, agePos: FV_AGE_POS, size: FV_SIZE, sos: FV_SOS, cohorts: FV_COHORTS, reliability: FV_RELIABILITY, consensus: { w: CONS_W, boards: CONS_BOARDS }, tiers: TIERS, posValue: FV_POS_VALUE, starters: STARTERS, team: FV_TEAM },
    players: board,
    all: rows,
  };
}

// ---- scouting report ------------------------------------------------------------------------------
// The FV feeders as a short report: a role projection from the football FV chart, then strengths (+)
// and concerns (-), each with the number behind it. Thresholds are on the same z scale as the model.
const ROLE = [[80, 'an MVP-level, generational talent'], [75, 'a perennial All-Pro'], [70, 'an All-Pro, top 3 at the position'],
  [65, 'a multi-time Pro Bowler'], [60, 'a Pro Bowler'], [55, 'an above-average starter'], [50, 'an average starter'],
  [45, 'a low-end starter or top rotational player'], [40, 'a rotational player / spot starter'], [35, 'a backup'],
  [30, 'a practice-squad type'], [20, 'a non-NFL player']];
const STAT_NAME = { ypr: 'yards per route run', intRate: 'INT rate', rushYpg: 'rushing yards per game', recYpg: 'receiving yards per game', yac: 'YAC',
  skAllwd: 'sacks allowed', skRate: 'sack rate', tacklePct: 'tackle %', tflRate: 'TFL rate', catchAllowed: 'catch % allowed', nypa: 'yards per attempt', cmpPct: 'completion %', elu: 'elusiveness', ypc: 'yards per carry', tgtSh: 'target share',
  epaTar: 'EPA per target', blk: 'blocking grade', prsRate: 'pressure rate', rbScore: 'run-block score', mt: 'missed tackles',
  rtg: 'passer rating allowed', fi: 'forced incompletion rate' };
const SPOT = { OL: 'lineman', EDGE: 'edge rusher', DL: 'interior lineman', LB: 'linebacker', CB: 'corner', S: 'safety',
  QB: 'quarterback', RB: 'back', WR: 'receiver', TE: 'tight end' };
function scoutReport(p) {
  const plus = [], minus = [], pct = z => Math.max(1, Math.round(100 * (1 - phi(z))));
  const role = p.fv == null ? null : ROLE.find(([f]) => p.fv >= f)?.[1];
  const o = p.on3, spot = SPOT[p.g] || 'player', a = /^[aeiou]/.test(spot) ? 'an' : 'a';
  // talent
  if (o?.grade != null) {
    const where = o.posRank ? `#${o.posRank} ${o.pos}` : '';
    if (p.zOn3 >= 2) plus.push(`Elite talent grade: On3 ${o.grade}${where ? ` (${where})` : ''}`);
    else if (p.zOn3 >= 1) plus.push(`Strong talent grade: On3 ${o.grade}${where ? ` (${where})` : ''}`);
    else minus.push(`Middling talent grade for a ranked ${spot}: On3 ${o.grade}`);
  } else minus.push(`Not in On3's top 75 at the position: production has to carry the grade`);
  // scouting consensus (moves FV after the model grade)
  if (p.cons) {
    const line = `#${p.cons.rank} on the industry consensus board (avg rank ${p.cons.avg}, ${p.cons.n} of ${CONS_BOARDS} boards): model ${p.fvModel}, ${p.consAdj >= 0 ? '+' : ''}${Math.round(p.consAdj)} FV`;
    if (p.consAdj >= 1) plus.push(`Scouts rate him higher: ${line}`);
    else if (p.consAdj <= -1) minus.push(`Scouts rate him lower: ${line}`);
    else if (p.cons.n <= 2) minus.push(`Thin scouting support: ${line}`);
    else plus.push(`Scouting consensus agrees: ${line}`);
  }
  // production: this season's score and the regressed blend's standing are separate facts
  const span = p.seasons > 1 ? `${p.seasons}-season blend` : 'this season, regressed';
  if (p.pfn != null || p.priorOnly) {
    const now = p.pfn != null ? `${p.pfn.toFixed(1)} ${p.label} this season; ` : '';
    if (p.zPfn >= 1.5) plus.push(`Dominant production: ${now}top ${pct(p.zPfn)}% at the position (${span})`);
    else if (p.zPfn >= 0.75) plus.push(`Productive: ${now}top ${pct(p.zPfn)}% at the position (${span})`);
    else if (p.zPfn < 0) minus.push(`Production lags the profile: ${now}bottom half at the position (${span})`);
    if (p.marcelW < 1000) minus.push(`Thin sample: ${p.snaps ?? 0} snaps this season${p.seasons > 1 ? '' : ' and no earlier line'}, so production is regressed hard toward average`);
  }
  if (p.priorOnly) minus.push(`No PFN line this season: graded on ${p.seasons} earlier season${p.seasons > 1 ? 's' : ''}`);
  else if (p.pfn == null) minus.push('No PFN production line this season or before (injury, depth chart or redshirt)');
  // efficiency stats
  for (const d of p.statDetail || []) {
    const v = Number.isInteger(d.v) ? d.v : d.v.toFixed(1), name = STAT_NAME[d.f] || d.f;
    if (d.z >= 1.25) plus.push(`Plus ${name}: ${v} (+${d.z.toFixed(1)} SD)`);
    else if (d.z <= -1) minus.push(`Below-average ${name}: ${v} (${d.z.toFixed(1)} SD)`);
  }
  // age
  const age = p.age ?? p.ageEst, est = p.age == null ? '~' : '';
  if (age != null) {
    if (p.ageZ >= 0.3) plus.push(`Young for his production: ${est}${age.toFixed(1)}, which raises the ceiling`);
    else if (p.ageZ <= -0.3) minus.push(`Old for a prospect: ${est}${age.toFixed(1)}, less projection left`);
  }
  // pedigree and development: the model credits the high school grade (hsZ); the rise since is shown
  // as context, never as a plus the model doesn't give
  if (o?.hsGrade != null && o.grade != null) {
    const dev = o.grade - o.hsGrade, stars = o.hsStars ? `${o.hsStars}-star` : 'recruit';
    if (p.hsZ >= 0.05) plus.push(dev >= 6 ? `Pedigree and growth: ${stars} (${Math.round(o.hsGrade)}) now graded ${o.grade}` : `Blue-chip pedigree: ${stars} (${Math.round(o.hsGrade)})`);
    else if (p.hsZ <= -0.05) minus.push(dev >= 6 ? `Modest recruiting pedigree (${stars}, ${Math.round(o.hsGrade)}), though he's risen to ${o.grade}` : `Modest recruiting pedigree: ${stars} (${Math.round(o.hsGrade)})`);
    if (dev <= -4) minus.push(`Hasn't matched his recruiting grade: ${Math.round(o.hsGrade)} out of high school, ${o.grade} now`);
  }
  // schedule and frame
  if (p.sosZ >= 0.12) plus.push('Production came against a tough schedule');          // QBs only (see sosZ)
  else if (p.sosZ <= -0.12) minus.push('Soft schedule: production came against weaker competition');
  const frame = [p.on3?.ht || p.espn?.ht?.replace(/[' "]+/g, '-').replace(/-$/, ''), p.wtLb ? `${p.wtLb} lb` : null,
    p.bmi ? `BMI ${p.bmi.toFixed(1)}` : null].filter(Boolean).join(', ');
  if (p.sizeZ >= 0.06) plus.push(`Prototype frame for ${a} ${spot}: ${frame}`);
  else if (p.sizeZ <= -0.06) minus.push(`Undersized for ${a} ${spot}: ${frame}`);
  if (p.plus) plus.push('Upside: talent grade well ahead of production in a young player (the "+")');
  return { role, plus, minus };
}

// ---- pixel logos -----------------------------------------------------------------------------
// ESPN's 500 px logos squeezed to a 20 px grid, 24 colours, then doubled with nearest-neighbour so
// they read as pixel art at 20 css px (crisp on 2x screens). Needs ImageMagick; without it the
// board hotlinks ESPN's logo instead.
async function pixelLogos(out) {
  let im = null;
  for (const bin of ['magick', 'convert']) {
    try { execFileSync(bin, ['-version'], { stdio: 'ignore' }); im = bin; break; } catch {}
  }
  if (!im) { console.log('no ImageMagick: hotlinking ESPN logos'); return; }
  fs.mkdirSync(LOGOS, { recursive: true });
  const done = {};
  for (const p of out.all) {
    const m = /teamlogos\/ncaa\/500\/(\d+)\.png/.exec(p.logo || '');
    if (!m) continue;
    const id = m[1], file = path.join(LOGOS, `${id}.png`);
    if (!(id in done)) {
      done[id] = fs.existsSync(file);
      if (!done[id]) {
        try {
          const r = await fetch(p.logo, { headers: { 'user-agent': UA } });
          if (!r.ok) throw new Error(r.status);
          const tmp = path.join(CACHE, `logo-${id}.png`);
          fs.writeFileSync(tmp, Buffer.from(await r.arrayBuffer()));
          execFileSync(im, [tmp, '-trim', '+repage', '-resize', '20x20', '-background', 'none', '-gravity', 'center',
            '-extent', '20x20', '-channel', 'A', '-threshold', '50%', '+channel', '-colors', '24',
            '-filter', 'point', '-resize', '40x40', '-strip', file]);
          done[id] = true;
        } catch (e) { console.log(`logo ${id}: ${e.message}`); }
      }
    }
    if (done[id]) p.logo = `/img/cfb/logos/${id}.png`;
  }
  console.log(`logos: ${Object.values(done).filter(Boolean).length} pixel logos`);
}

// NFL team logos for the mock draft: ESPN's PNGs through the same pixel step
async function nflLogos(picks) {
  let im = null;
  for (const bin of ['magick', 'convert']) { try { execFileSync(bin, ['-version'], { stdio: 'ignore' }); im = bin; break; } catch {} }
  fs.mkdirSync(NFL_LOGOS, { recursive: true });
  const done = {};
  for (const k of picks) {
    const a = k.team.toLowerCase(), file = path.join(NFL_LOGOS, `${a}.png`), url = `https://a.espncdn.com/i/teamlogos/nfl/500/${a}.png`;
    if (!(a in done)) {
      done[a] = fs.existsSync(file);
      if (!done[a] && im) {
        try {
          const r = await fetch(url, { headers: { 'user-agent': UA } }); if (!r.ok) throw new Error(r.status);
          const tmp = path.join(CACHE, `nfl-${a}.png`); fs.writeFileSync(tmp, Buffer.from(await r.arrayBuffer()));
          execFileSync(im, [tmp, '-trim', '+repage', '-resize', '20x20', '-background', 'none', '-gravity', 'center', '-extent', '20x20',
            '-channel', 'A', '-threshold', '50%', '+channel', '-colors', '24', '-filter', 'point', '-resize', '40x40', '-strip', file]);
          done[a] = true;
        } catch (e) { console.log(`nfl logo ${a}: ${e.message}`); }
      }
    }
    k.teamLogo = done[a] ? `/img/nfl/${a}.png` : url;
  }
}

// ---- dates of birth --------------------------------------------------------------------------
const WIKI_UA = 'arkndjl.net ARKBOARD (https://arkndjl.net; site maintenance)';
async function getRetry(url, ua = WIKI_UA) {
  for (let i = 0; ; i++) {
    const r = await fetch(url, { headers: { 'user-agent': ua, accept: 'application/json,text/html' } });
    if (r.status === 404) return null;
    if (r.status === 429 && i < 4) { await sleep(1000 * (+r.headers.get('retry-after') || 20)); continue; }
    if (!r.ok) throw new Error(`${r.status} ${url.slice(0, 80)}`);
    return r.text();
  }
}

async function wikidataDobs(names) {
  const vals = names.map(n => JSON.stringify(n) + '@en').join(' ');
  const q = `SELECT ?name ?dob (GROUP_CONCAT(DISTINCT ?tl; separator="|") AS ?teams) WHERE {
    VALUES ?name { ${vals} } ?p rdfs:label ?name; wdt:P106 wd:Q19204627; wdt:P569 ?dob.
    OPTIONAL { ?p wdt:P54|wdt:P69 ?t. ?t rdfs:label ?tl FILTER(lang(?tl)="en") } } GROUP BY ?name ?p ?dob`;
  const t = await getRetry('https://query.wikidata.org/sparql?format=json&query=' + encodeURIComponent(q));
  const out = {};
  for (const b of JSON.parse(t).results.bindings)
    (out[b.name.value] ||= []).push({ dob: b.dob.value.slice(0, 10), teams: b.teams.value.toLowerCase() });
  return out;
}

async function wikipediaDobs(titles) {
  const u = 'https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&rvsection=0'
    + '&redirects=1&format=json&formatversion=2&titles=' + encodeURIComponent(titles.join('|'));
  const r = JSON.parse(await getRetry(u)).query;
  const back = {};
  for (const x of [...(r.redirects || []), ...(r.normalized || [])]) back[x.to] = back[x.from] || x.from;
  const out = {};
  for (const p of r.pages || []) {
    const wt = p.revisions?.[0]?.slots?.main?.content || '';
    const m = /\{\{\s*birth[ _]date(?: and age)?\s*\|(?:\s*\w+\s*=[^|}]*\|)*\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})/i.exec(wt);
    out[back[p.title] || p.title] = { dob: m ? `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}` : null, wt: wt.toLowerCase() };
  }
  return out;
}

const dayGap = (a, b) => Math.abs(new Date(a) - new Date(b)) / 864e5;
// a college player is 16-27; anything else is a namesake
const plausible = d => !!d && +d.slice(0, 4) >= SEASON - 27 && +d.slice(0, 4) <= SEASON - 16;

async function fetchDobs(players, store) {
  const today = new Date().toISOString().slice(0, 10);
  const todo = players.filter(p => {
    const s = store[`${p.name}|${p.team}`];
    return !s || (!s.dob && dayGap(s.checked, today) >= 7);
  });
  if (!todo.length) return 0;
  const names = [...new Set(todo.map(p => p.name))];
  const wd = {}, wp = {};
  for (let i = 0; i < names.length; i += 60) {
    try { Object.assign(wd, await wikidataDobs(names.slice(i, i + 60))); } catch (e) { console.log(`wikidata: ${e.message}`); }
  }
  const titles = names.flatMap(n => [`${n} (American football)`, n]);
  for (let i = 0; i < titles.length; i += 50) {
    try { Object.assign(wp, await wikipediaDobs(titles.slice(i, i + 50))); } catch (e) { console.log(`wikipedia: ${e.message}`); }
    await sleep(1000);
  }
  let found = 0;
  for (const p of todo) {
    const school = p.team.toLowerCase(), first = school.split(' ')[0];
    const hits = wd[p.name] || [];
    let a = hits.find(h => h.teams.includes(school) || h.teams.includes(`${first} `))?.dob || null;  // school must match
    if (!plausible(a)) a = null;
    let b = null;
    for (const t of [`${p.name} (American football)`, p.name]) {
      const w = wp[t];
      if (plausible(w?.dob) && w.wt.includes('football') && w.wt.includes(first)) { b = w.dob; break; }
    }
    let dob = a || b, src = a ? 'wikidata' : b ? 'wikipedia' : null;
    if (a && b && dayGap(a, b) > 3) src = 'wikidata (wikipedia disagrees)';   // structured source wins
    store[`${p.name}|${p.team}`] = dob ? { dob, src } : { dob: null, checked: today };
    if (dob) found++;
  }
  console.log(`dates of birth: ${found} found of ${todo.length} looked up`);
  return todo.length;
}

// ---- main ------------------------------------------------------------------------------------
fs.mkdirSync(CACHE, { recursive: true });
const manual = fs.existsSync(MANUAL) ? JSON.parse(fs.readFileSync(MANUAL, 'utf8')) : {};
let pfn, on3, espn;
if (OFFLINE) {
  pfn = readCache('pfn.json'); on3 = readCache('on3.json'); espn = readCache('espn.json');
} else {
  pfn = await fetchPfn(); writeCache('pfn.json', pfn);
  if (ARGS.has('--skip-on3') && hasCache('on3.json')) on3 = readCache('on3.json');
  else {
    try { on3 = await fetchOn3(); }
    catch (e) {   // a Cloudflare challenge shouldn't sink the update: reuse the last good pull
      if (!hasCache('on3.json')) throw e;
      console.log(`ON3 failed (${e.message.slice(0, 120)}); using the cached pull`);
      on3 = readCache('on3.json');
    }
  }
  writeCache('on3.json', on3);
  const names = [...new Set([...Object.values(pfn).flat().filter(r => r.season === SEASON && (INCLUDE_FCS || r.division === 'FBS')).map(r => r.team),
                             ...on3.map(o => o.team).filter(Boolean)])];
  espn = await fetchEspn(names); writeCache('espn.json', espn);
}
// team-level inputs: games, the projected draft order and needs, coaching staffs. Each falls back
// to its last good pull (cache) so one bad source doesn't stop the update.
async function source(name, fn) {
  if (OFFLINE && hasCache(name)) return readCache(name);
  try { const v = await fn(); writeCache(name, v); return v; }
  catch (e) { console.log(`${name}: ${e.message.slice(0, 120)}${hasCache(name) ? '; using the cached pull' : ''}`); return hasCache(name) ? readCache(name) : null; }
}
const games = await source('games.json', () => fetchGames(SEASON));
const lastGames = await source(`games${SEASON - 1}.json`, () => hasCache(`games${SEASON - 1}.json`) ? readCache(`games${SEASON - 1}.json`) : fetchGames(SEASON - 1));
const injuries = await source('injuries.json', fetchInjuries);
// CFBD: last season's SP+ (once; it doesn't change) and this season's advanced team stats (each run)
const spLast = await source(`sp${SEASON - 1}.json`, () => hasCache(`sp${SEASON - 1}.json`) ? readCache(`sp${SEASON - 1}.json`) : cfbd(`ratings/sp?year=${SEASON - 1}`));
const advanced = await source('advanced.json', () => cfbd(`stats/season/advanced?year=${SEASON}&excludeGarbageTime=true`));
// 2027 draft order (projected from current NFL standings) and team needs (depth charts + contracts), ESPN
const tank = await source('nfl_order.json', async () => { const o = await fetchNflOrder(SEASON); o.needs = await fetchNflNeeds(o.teams); return o; });
// recruiting (CFBD, 247 composite): every high school and JUCO class since 2019, keyed by ESPN athlete id.
// Past classes never change, so each is fetched once and cached; the newest class refreshes each run.
async function fetchRecruits() {
  const out = {};
  for (let y = SEASON - 7; y <= SEASON; y++) for (const kind of ['HighSchool', 'JUCO']) {
    const name = `recruits-${y}-${kind}.json`;
    let list = hasCache(name) && y < SEASON ? readCache(name) : null;
    if (!list) { try { list = await cfbd(`recruiting/players?year=${y}&classification=${kind}`); writeCache(name, list); } catch (e) { console.log(`recruits ${y} ${kind}: ${e.message}`); list = hasCache(name) ? readCache(name) : []; } }
    for (const r of list) if (r.athleteId) out[r.athleteId] = { year: r.year, kind, stars: r.stars, rating: r.rating, rank: r.ranking, pos: r.position, ht: r.height, wt: r.weight };
  }
  return out;
}
// team strength for the FV composite: last season's SP+ by ESPN team id, as z across FBS
const teamSp = (() => {
  const ix = teamIndex(espn.teams), list = (spLast || []).filter(x => x.rating != null);
  const m = list.reduce((a, x) => a + x.rating, 0) / Math.max(1, list.length), sd = Math.sqrt(list.reduce((a, x) => a + (x.rating - m) ** 2, 0) / Math.max(1, list.length)) || 1;
  return Object.fromEntries(list.map(x => [ix.resolve(x.team), (x.rating - m) / sd]).filter(([k]) => k));
})();
const recruits = process.env.CFBD_API_KEY || hasCache(`recruits-${SEASON - 1}-HighSchool.json`) ? await fetchRecruits() : {};
console.log(`recruits: ${Object.keys(recruits).length} with ESPN ids`);
const staffData = fs.existsSync(STAFF_IN) ? JSON.parse(fs.readFileSync(STAFF_IN, 'utf8')) : null;
const dobStore = fs.existsSync(DOBS) ? JSON.parse(fs.readFileSync(DOBS, 'utf8')) : {};
const consensus = await source('consensus.json', fetchConsensus) || [];
let out = build({ pfn, on3, espn, manual, dobStore, recruits, teamSp, consensus });
if (!ARGS.has('--no-dob') && await fetchDobs(out.players, dobStore)) {
  const sorted = Object.fromEntries(Object.entries(dobStore).sort(([a], [b]) => a.localeCompare(b)));
  fs.writeFileSync(DOBS, JSON.stringify(sorted, null, 1) + '\n');
  out = build({ pfn, on3, espn, manual, dobStore, recruits, teamSp, consensus });   // ages feed the model, so grade again
}
await pixelLogos(out);

// movers: each update keeps a snapshot of every grade; the board shows the change since the last
// snapshot from an earlier day (re-runs on the same day replace that day's snapshot). Snapshots carry
// the model version, so a model change starts the movers over instead of reporting its own churn.
const MODEL_VERSION = 'cal-2026-10';
const key = r => `${r.name}|${r.team}|${r.pos}`;
const hist = fs.existsSync(HISTORY) ? JSON.parse(fs.readFileSync(HISTORY, 'utf8')) : { snapshots: [] };
const base = hist.snapshots.filter(h => h.date < out.asof && h.v === MODEL_VERSION).at(-1);
out.since = base?.date ?? null;
for (const r of out.all) {
  const was = base?.fv[key(r)];
  r.delta = base && r.fv != null ? (was == null ? 'new' : r.fv - was) : null;
}
hist.snapshots = hist.snapshots.filter(h => h.date !== out.asof);
hist.snapshots.push({ date: out.asof, v: MODEL_VERSION, fv: Object.fromEntries(out.all.filter(r => r.fv != null).map(r => [key(r), r.fv])) });
hist.snapshots = hist.snapshots.slice(-6);
fs.writeFileSync(HISTORY, JSON.stringify(hist) + '\n');

// every graded player, for the database view: column arrays keep it small (fetched by the page)
for (const r of out.all) { r.on3l = r.links.on3; r.espnl = r.links.espn; }
const COLS = ['report', 'on3l', 'espnl', 'name', 'pos', 'spot', 'team', 'logo', 'conf', 'cls', 'elig', 'age', 'ageEst', 'ht', 'wt', 'pfn', 'pfnLabel',
              'snaps', 'on3', 'cons', 'consRk', 'consN', 'xnil', 'fv', 'plus', 'posRank', 'ovr', 'draft27', 'parts', 'bmi', 'delta'];
fs.mkdirSync(path.dirname(ALL_OUT), { recursive: true });
fs.writeFileSync(ALL_OUT, JSON.stringify({ asof: out.asof, cols: COLS,
  rows: out.all.map(r => COLS.map(c => r[c] ?? null)) }));
// teams, staff, mock draft
const fbsIds = new Set(Object.keys(espn.rosters));
const idxTeams = teamIndex(espn.teams);
const byEspn = (list, f) => Object.fromEntries((list || []).map(x => [idxTeams.resolve(x.team), f(x)]).filter(([k]) => k));
const teamList = games ? teamModels(out.all, espn.teams, games, fbsIds, {
  lastGames, sp: byEspn(spLast, x => x.rating), adv: byEspn(advanced, x => x) }) : [];
// the coming week: the earliest week with unplayed games
const nextWeek = games?.filter(g => !g.done).map(g => g.week).sort((a, b) => a - b)[0] ?? null;
// projected top performers: this season's player stat lines (CFBD, one call a run)
// the game model (scripts/cfb_model.mjs): CFBD games, advanced box scores and closing lines for this season
// and the two before (past seasons pulled once), venues, talent, returning production, QB EPA; weather from
// Open-Meteo, cached by game. A failed source falls back to its cache; with none, the slate keeps Elo alone.
const once = (name, q) => source(name, () => hasCache(name) ? readCache(name) : cfbd(q));
const cur = (name, q) => source(name, () => cfbd(q));
const MD = { games: {}, adv: {}, lines: {}, sp: {}, talent: {}, returning: {}, drives: {} };
for (const S of [SEASON - 2, SEASON - 1, SEASON]) {
  const get = S === SEASON ? cur : once;
  MD.games[S] = await get(`games${S}cfbd.json`, `games?year=${S}&seasonType=both`);
  MD.adv[S] = await get(`gameadv${S}.json`, `stats/game/advanced?year=${S}&excludeGarbageTime=true`);
  // drives (special teams), kept slim: a season of raw drives is ~15 MB
  MD.drives[S] = await source(`drives${S}.json`, async () => S < SEASON && hasCache(`drives${S}.json`) ? readCache(`drives${S}.json`) : slimDrives(await cfbd(`drives?year=${S}`)));
  if (S > SEASON - 2) {
    MD.lines[S] = await get(`lines${S}.json`, `lines?year=${S}`);
    MD.talent[S] = await once(`talent${S}.json`, `talent?year=${S}`);
    MD.returning[S] = await once(`returning${S}.json`, `player/returning?year=${S}`);
  }
  if (S < SEASON) MD.sp[S] = await once(`sp${S}.json`, `ratings/sp?year=${S}`);
}
MD.venues = await once('venues.json', 'venues');
MD.teamsFbs = await once(`teamsfbs.json`, `teams/fbs?year=${SEASON}`);
MD.ppaqb = await cur(`ppaqb${SEASON}.json`, `ppa/players/season?year=${SEASON}&position=QB&excludeGarbageTime=true`);
MD.weather = hasCache('weather.json') ? readCache('weather.json') : {};
let model = null;
try {
  if (Object.values(MD.games).every(x => x?.length) && Object.values(MD.adv).every(x => x?.length)) {
    // FV team talent (projected starters' expected NFL value), z across FBS: the model's live talent input
    const tl = teamList.filter(t => t.talent != null), tm = tl.reduce((x, t) => x + t.talent, 0) / Math.max(1, tl.length);
    const ts = Math.sqrt(tl.reduce((x, t) => x + (t.talent - tm) ** 2, 0) / Math.max(1, tl.length)) || 1;
    model = await runModel(MD, SEASON, { talentZ: Object.fromEntries(tl.map(t => [String(t.tid), (t.talent - tm) / ts])) });
    writeCache('weather.json', MD.weather);
    const t = model.report.test || model.report.train;
    console.log(`model: test ${model.report.seasons.test ?? model.report.seasons.train} log loss ${t.logLoss} · MAE ${t.mae} (market ${t.maeMarket}) · ATS ${t.ats.all.pct}`);
  }
} catch (e) { console.log(`model: ${e.stack?.slice(0, 400)}`); }
const pstats = await source('player_stats.json', () => cfbd(`stats/player/season?year=${SEASON}`));
const gp = {}; for (const g of games || []) if (g.done) for (const id of [g.home, g.away]) gp[id] = (gp[id] || 0) + 1;
const slate = nextWeek ? gamesModel(games.filter(g => g.week === nextWeek && !g.done), teamList, out.all, injuries || {},
  { adv: byEspn(advanced, x => x), rates: playerRates(pstats, n => idxTeams.resolve(n), games), gp, model }) : [];
fs.writeFileSync(GAMES_OUT, JSON.stringify({ asof: out.asof, week: nextWeek, injuriesAsof: injuries ? out.asof : null, games: slate }, null, 1) + '\n');
// edge log (data/cfb_edges.json): each run records the model's line on every coming game with a market line,
// replacing the earlier entry until kickoff; played games are graded against the closing line (CFBD), so the
// record by edge size is the model's, at the price it would have been bet
const EDGES = path.join(ROOT, 'data', 'cfb_edges.json');
const edgeLog = fs.existsSync(EDGES) ? JSON.parse(fs.readFileSync(EDGES, 'utf8')) : { games: {} };
for (const g of slate) if (g.proj && g.market != null && Date.parse(g.date) > Date.now())
  edgeLog.games[g.id] = { week: nextWeek, date: g.date, home: g.home.name, away: g.away.name, model: r1(-g.proj.margin), market: g.market,
    total: g.proj.total, ou: g.total ?? null, at: out.asof };
const closing = Object.fromEntries((MD.lines[SEASON] || []).map(l => [String(l.id), l]));
const bucket = e => e < 3 ? '0-3' : e < 7 ? '3-7' : '7+';
const rec = { all: { w: 0, l: 0, p: 0 }, '0-3': { w: 0, l: 0, p: 0 }, '3-7': { w: 0, l: 0, p: 0 }, '7+': { w: 0, l: 0, p: 0 } }, ouRec = { w: 0, l: 0, p: 0 };
for (const [id, e] of Object.entries(edgeLog.games)) {
  const c = closing[id], ln = c?.lines?.find(l => l.provider === 'consensus') || c?.lines?.find(l => l.provider === 'ESPN Bet') || c?.lines?.find(l => l.spread != null);
  if (!c || c.homeScore == null || c.awayScore == null || ln?.spread == null) continue;
  // spreads from the home side, negative = home favoured; the model's side is the one it likes more than the close
  const edge = ln.spread - e.model, cover = (c.homeScore - c.awayScore) + ln.spread;
  e.close = ln.spread; e.result = `${c.awayScore}-${c.homeScore}`; e.edge = r1(Math.abs(edge));
  e.ats = Math.abs(edge) < 0.5 ? null : cover === 0 ? 'P' : Math.sign(edge) === Math.sign(cover) ? 'W' : 'L';
  if (e.ats) for (const k of ['all', bucket(Math.abs(edge))]) rec[k][e.ats.toLowerCase()]++;
  if (e.total != null && ln.overUnder != null) {
    const d = e.total - ln.overUnder, actual = c.homeScore + c.awayScore - ln.overUnder;
    e.ou = Math.abs(d) < 1 ? null : actual === 0 ? 'P' : Math.sign(d) === Math.sign(actual) ? 'W' : 'L';
    if (e.ou) ouRec[e.ou.toLowerCase()]++;
  }
}
edgeLog.record = rec; edgeLog.ou = ouRec; edgeLog.asof = out.asof;
fs.writeFileSync(EDGES, JSON.stringify(edgeLog, null, 1) + '\n');
// the model report and season simulation: data/cfb_model.json
if (model) {
  const T = Object.fromEntries(teamList.map(t => [t.tid, t]));
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_model.json'), JSON.stringify({ asof: out.asof, report: model.report, live: { record: rec, ou: ouRec },
    sim: model.sim.filter(s => T[s.tid]).map(s => ({ ...s, team: T[s.tid].team, abbr: T[s.tid].abbr, logo: T[s.tid].logo, rating: r1(model.rating[s.tid] ?? 0),
      ratingRk: null })).sort((a, b) => b.rating - a.rating).map((s, i) => ({ ...s, ratingRk: i + 1 })) }, null, 1) + '\n');
}
// player projections for the week (PPR), top 300: data/cfb_proj.json
fs.writeFileSync(PROJ_OUT, JSON.stringify({ asof: out.asof, week: nextWeek, players: (slate.players || []).slice(0, 300) }) + '\n');
const coaches = teamList.length ? staffModels(out.all, teamList, staffData?.teams) : [];
fs.writeFileSync(TEAMS_OUT, JSON.stringify({ asof: out.asof, games: games?.filter(g => g.done).length ?? 0,
  weeks: games?.length ? Math.max(...games.filter(g => g.done).map(g => g.week)) : 0, teams: teamList, coaches }, null, 1) + '\n');
if (tank) {
  const PRIORS = path.join(ROOT, 'data', 'cfb_draft_priors.json');
  const picks = mockDraft(out.all, tank, 7, fs.existsSync(PRIORS) ? JSON.parse(fs.readFileSync(PRIORS, 'utf8')) : undefined);
  await nflLogos(picks);
  fs.writeFileSync(MOCK_OUT, JSON.stringify({ asof: out.asof, rounds: Math.max(...picks.map(p => p.round)), picks }, null, 1) + '\n');
}
console.log(`teams: ${teamList.length} (${games?.length ?? 0} games) · coaches: ${coaches.length} · mock: ${tank ? 'yes' : 'no'}`);
const { all, ...boardOut } = out;
fs.writeFileSync(OUT, JSON.stringify(boardOut, null, 1) + '\n');
const tiers = {};
for (const p of out.players) { const t = Math.floor(p.fv / 5) * 5; tiers[t] = (tiers[t] || 0) + 1; }
console.log(`board: ${out.count} players of ${out.population} graded · FV tiers`, tiers);
