#!/usr/bin/env node
// Build the College Football ARKBOARD (data/cfb.json) from public sources.
//
//     node scripts/fetch_cfb.mjs            # fetch everything, rebuild data/cfb.json
//     node scripts/fetch_cfb.mjs --offline  # rebuild from the cached pulls (re-tune the model)
//     node scripts/fetch_cfb.mjs --skip-on3 # refetch PFN + ESPN, reuse cached ON3
//
// Sources
//   PFN  impact rankings (QB+, RB+, WR+, TE+, OLi, EDGE+, DT+, LB+, CB+, SAF+), every FBS/FCS
//        player and every season since 2019, embedded as packed JSON in each page.
//   ON3  college roster rankings (the On3 college grade), every position, every page. ON3 sits
//        behind Cloudflare, so it is read through headless Chromium (Playwright).
//   ESPN team list (logos, colors) and every FBS roster (class year, height, weight, headshot).
//   data/cfb_manual.json  hand-kept overrides: dates of birth, FV grades, notes (see the file).
//
// Board rules (any one puts a player on the board):
//   PFN score >= 89.5 · ON3 grade >= 95 · (PFN + ON3) / 2 >= 88
//   freshman with an ON3 grade · freshman with PFN >= 80
//
// The FV model (20-80, see FV_* below and the ARKBOARD page) grades every FBS player, not just the
// board, so a grade is a rank against the whole population. Raw pulls are cached in
// scripts/.cache/cfb/ (gitignored). Needs Node 18+ and, for ON3, the playwright package
// (`npm i -D playwright`, or a global install).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'cfb');
const OUT = path.join(ROOT, 'data', 'cfb.json');
const MANUAL = path.join(ROOT, 'data', 'cfb_manual.json');
const LOGOS = path.join(ROOT, 'static', 'img', 'cfb', 'logos');
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
// 1. Production: PFN scores blended Marcel-style over three seasons (5/4/3, by snaps) and
//    regressed toward the position mean with FV_K snaps of league average, so five games in
//    October can't outvote two full seasons.
// 2. Talent: the ON3 college grade, as a percentile of the FBS population at the position
//    (unranked players share the percentile band below the last ranked player).
// 3. Both turn into z-scores (inverse normal of the percentile); the composite is their
//    weighted mean plus an age term: younger at the same level = more projection.
// 4. FV is scarcity: within each position, the k-th best composite is compared to how many
//    players per NFL draft class reach each outcome tier, scaled by that position's share of
//    the 22 NFL starting spots. "+" marks talent well ahead of production in a young player.
const FV_WEIGHTS = { 2026: 5, 2025: 4, 2024: 3 };
const FV_K = 1500;            // regression, in weighted snaps (~300 current-season snaps)
const FV_W = { on3: 0.5, pfn: 0.5 };
const FV_AGE = { pivot: 21.0, perYear: 0.2 };   // z per year younger than pivot (capped ±0.5)
const FV_COHORTS = 4;         // classes in the playing population
// cumulative players per draft class at or above each grade, all positions
const FV_TIERS = [[80, 1], [75, 2], [70, 5], [65, 10], [60, 18], [55, 40], [50, 90],
                  [45, 175], [40, 260], [35, 350], [30, 500]];
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
      const d = await get(`https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/${id}/roster`, 'json');
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

// ---- model -----------------------------------------------------------------------------------
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

function fvFromRank(rankPerClass, share) {
  for (const [fv, n] of FV_TIERS) if (rankPerClass <= n * share) return fv;
  return 20;
}

function build({ pfn, on3, espn, manual }) {
  const asof = new Date();
  const idx = teamIndex(espn.teams);
  const rosterByTeam = {};
  for (const [tid, list] of Object.entries(espn.rosters)) {
    rosterByTeam[tid] = {};
    for (const a of list) (rosterByTeam[tid][norm(a.name)] ||= []).push(a);
  }
  const espnFind = (tid, name) => rosterByTeam[tid]?.[norm(name)]?.[0] || null;

  // ON3 by normalized name, disambiguated by team
  const on3ByName = {};
  for (const o of on3) {
    o.tid = idx.resolve(o.team) || idx.resolve((o.teamSlug || '').replace(/-/g, ' '));
    (on3ByName[norm(o.name)] ||= []).push(o);
  }
  const on3Find = (name, tid, g) => {
    const hits = on3ByName[norm(name)] || [];
    return hits.find(o => o.tid === tid) || (hits.length === 1 && hits[0].tid == null ? hits[0] : null)
        || hits.find(o => ON3_TO_G[o.pos] === g && hits.length === 1) || null;
  };

  const players = [];
  const usedOn3 = new Set();
  for (const p of POS) {
    const seasons = pfn[p.g];
    const hist = {};
    for (const r of seasons) if (FV_WEIGHTS[r.season]) (hist[r.id] ||= []).push(r);
    const cur = seasons.filter(r => r.season === SEASON);
    const fbs = cur.filter(r => r.division === 'FBS');
    const mean = fbs.reduce((a, r) => a + r.score, 0) / Math.max(1, fbs.length);
    for (const r of cur) {
      if (r.division !== 'FBS' && !INCLUDE_FCS) continue;
      const tid = idx.resolve(r.team);
      const snaps = r.snapsQ ?? r.snaps ?? null;
      let num = FV_K * mean, den = FV_K;
      for (const h of hist[r.id] || []) {
        const sn = h.snapsQ ?? h.snaps ?? 0;
        num += FV_WEIGHTS[h.season] * sn * h.score; den += FV_WEIGHTS[h.season] * sn;
      }
      const o = on3Find(r.name, tid, p.g);
      if (o) usedOn3.add(o);
      players.push({ name: r.name, g: p.g, label: p.label, pfnId: r.id, pfnPos: r.pos || null,
        team: r.team, tid, conf: r.conf, div: r.division, pfn: r.score, snaps, gp: r.gp ?? r.gamesQ ?? null,
        marcel: num / den, on3: o });
    }
  }
  // ON3-ranked FBS players with no PFN line this season (injured, not yet playing, ATH)
  for (const o of on3) {
    if (usedOn3.has(o) || o.grade == null) continue;
    const g = ON3_TO_G[o.pos] || 'ATH';
    players.push({ name: o.name, g, label: POS.find(p => p.g === g)?.label || null, team: o.team, tid: o.tid,
      conf: null, div: 'FBS', pfn: null, snaps: null, gp: null, marcel: null, on3: o });
  }

  // percentiles within position: production (Marcel PFN) and talent (ON3)
  for (const g of [...new Set(players.map(p => p.g))]) {
    const grp = players.filter(p => p.g === g);
    const N = grp.length;
    const prod = grp.filter(p => p.marcel != null).sort((a, b) => b.marcel - a.marcel);
    const fallback = prod.length ? prod.reduce((a, p) => a + p.marcel, 0) / prod.length : 50;
    prod.forEach((p, i) => { p.zPfn = probit(1 - (i + 0.5) / prod.length); });
    grp.filter(p => p.marcel == null).forEach(p => { p.zPfn = 0; p.marcel = fallback; });
    const ranked = grp.filter(p => p.on3?.grade != null).sort((a, b) => b.on3.grade - a.on3.grade);
    ranked.forEach((p, i) => { p.zOn3 = probit(1 - (i + 0.5) / N); });
    const unrankedP = (N - ranked.length) / 2 / N;    // midpoint of the band below the last ranked
    grp.filter(p => p.on3?.grade == null).forEach(p => { p.zOn3 = probit(unrankedP); });
  }

  // identity, class, age
  const dobs = manual.dob || {};
  for (const p of players) {
    const e = p.tid ? espnFind(p.tid, p.name) : null;
    const t = p.tid ? espn.teams[p.tid] : null;
    const o = p.on3;
    let cls = null;
    if (o?.classYear) cls = classFrom(o.classYear, /redshirt/i.test(o.classRank || ''));
    else if (e?.years) cls = { years: e.years, elig: e.years, label: CLASS_NAMES[Math.min(e.years, 5) - 1] };
    const key = `${p.name}|${t?.name || p.team}`;
    const dob = dobs[key] || dobs[p.name] || e?.dob || null;
    const age = dob ? ageOn(dob, asof) : null;
    const ageEst = age ?? (cls ? 17.9 + cls.years : null);       // ~18.9 for a first-year in October
    Object.assign(p, { espn: e, team: t?.name || p.team, logo: t?.logo || o?.teamLogo || null,
      color: t?.color ? `#${t.color}` : o?.color || null, cls, dob, age, ageEst });
  }

  // composite and FV
  for (const p of players) {
    const ageZ = p.ageEst == null ? 0
      : Math.max(-0.5, Math.min(0.5, (FV_AGE.pivot - p.ageEst) * FV_AGE.perYear));
    p.comp = FV_W.on3 * p.zOn3 + FV_W.pfn * p.zPfn + ageZ;
  }
  for (const g of Object.keys(STARTERS)) {
    const share = STARTERS[g] / STARTER_TOTAL;
    players.filter(p => p.g === g).sort((a, b) => b.comp - a.comp)
      .forEach((p, i) => { p.fv = fvFromRank((i + 1) / FV_COHORTS, share); p.posRank = i + 1; });
  }
  for (const p of players) {
    if (p.fv == null) p.fv = null;                  // ATH: no NFL position to grade against yet
    p.plus = p.fv != null && p.fv < 80 && p.ageEst != null && p.ageEst <= 20.5 && p.zOn3 - p.zPfn >= 0.75;
  }

  // board rules
  const board = [];
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
    if (!why.length) continue;
    const m = manual.players?.[`${p.name}|${p.team}`] || manual.players?.[p.name] || {};
    board.push({
      name: p.name, pos: p.g, spot: p.pfnPos || (p.on3?.pos && p.on3.pos !== p.g ? p.on3.pos : null),
      team: p.team, logo: p.logo, color: p.color, conf: p.conf, div: p.div,
      cls: p.cls?.label ?? null, elig: p.cls?.elig ?? null, rs: !!p.cls?.label?.startsWith('RS'),
      age: p.age, ageEst: p.age == null && p.ageEst != null ? Math.round(p.ageEst * 10) / 10 : null, dob: p.dob,
      ht: p.on3?.ht || p.espn?.ht?.replace(/[' "]+/g, '-').replace(/-$/, '') || null, wt: p.on3?.wt || p.espn?.wt || null,
      pfn: p.pfn, pfnLabel: p.label, snaps: p.snaps, gp: p.gp,
      on3: on3g, on3Rank: p.on3?.overallRank ?? null, on3PosRank: p.on3?.posRank ?? null,
      hsStars: p.on3?.hsStars ?? null, transfer: p.on3?.transfer ?? null,
      avg: avg == null ? null : Math.round(avg * 10) / 10,
      fv: m.fv ?? p.fv, plus: m.fv != null ? !!m.plus : p.plus, fvModel: p.fv, fvManual: m.fv != null,
      comp: Math.round(p.comp * 1000) / 1000, prodZ: Math.round(p.zPfn * 100) / 100, talentZ: Math.round(p.zOn3 * 100) / 100,
      draft27: p.cls ? p.cls.years >= 3 : null,
      note: m.note || null, why,
      links: {
        on3: p.on3 ? `https://www.on3.com/rivals/${p.on3.slug}/` : null,
        espn: p.espn ? `https://www.espn.com/college-football/player/_/id/${p.espn.id}` : null,
        pfn: p.label ? `https://www.profootballnetwork.com/cfb-hq/impact-rankings/${POS.find(x => x.g === p.g)?.pfn}` : null,
      },
    });
  }
  board.sort((a, b) => (b.fv ?? 0) - (a.fv ?? 0) || (b.plus - a.plus) || b.comp - a.comp);
  board.forEach((p, i) => { p.rk = i + 1; });
  const unmatched = players.filter(p => !p.tid).map(p => p.team);
  if (unmatched.length) console.log('teams without an ESPN match:', [...new Set(unmatched)].join(', '));
  return {
    asof: asof.toISOString().slice(0, 10), season: SEASON, rules: RULES, includeFcs: INCLUDE_FCS,
    population: players.length, count: board.length,
    model: { weights: FV_WEIGHTS, k: FV_K, w: FV_W, age: FV_AGE, cohorts: FV_COHORTS, tiers: FV_TIERS, starters: STARTERS },
    players: board,
  };
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
  for (const p of out.players) {
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
const out = build({ pfn, on3, espn, manual });
await pixelLogos(out);
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
const byFv = {};
for (const p of out.players) byFv[p.fv + (p.plus ? '+' : '')] = (byFv[p.fv + (p.plus ? '+' : '')] || 0) + 1;
console.log(`board: ${out.count} players of ${out.population} graded · FV`, byFv);
