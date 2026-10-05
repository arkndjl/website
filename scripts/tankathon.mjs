// Scrape Tankathon's 2027 NFL draft order + mock-derived team needs.
// Node 22, no deps (global fetch). Usage: node tankathon.mjs [out.json]
const BASE = 'https://www.tankathon.com';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';

const GROUPS = {
  QB: 'QB', RB: 'RB', FB: 'RB', HB: 'RB', WR: 'WR', TE: 'TE',
  OT: 'OL', T: 'OL', IOL: 'OL', OG: 'OL', G: 'OL', C: 'OL', OL: 'OL',
  EDGE: 'EDGE', DE: 'EDGE', OLB: 'EDGE',
  DL: 'DL', DT: 'DL', IDL: 'DL', NT: 'DL',
  LB: 'LB', ILB: 'LB', MLB: 'LB',
  CB: 'CB', S: 'S', FS: 'S', SS: 'S', DB: 'CB',
  K: 'ST', P: 'ST', LS: 'ST',
};
// Hybrid labels like "LB/EDGE", "OT/IOL", "S/CB": use the first listed position.
export const toGroup = (label) => GROUPS[String(label).split('/')[0].trim().toUpperCase()] ?? null;

const CITY = { NY: 'New York', LA: 'Los Angeles' };
const decode = (s) => s.replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"').trim();
const nickname = (slug) => slug.charAt(0).toUpperCase() + slug.slice(1);
const abbrFromLogo = (src) => src.match(/\/nfl\/([a-z0-9]+)\.svg/i)[1].toUpperCase();
const https = (u) => u.replace(/^http:/, 'https:');

async function get(path) {
  const res = await fetch(BASE + path, { headers: { 'User-Agent': UA, Accept: 'text/html' }, redirect: 'follow' });
  if (!res.ok) throw new Error(`Tankathon ${path}: HTTP ${res.status}`);
  return res.text();
}

function parseFullDraft(html) {
  const order = [];
  const teams = {};
  // Each round: <div class="round-title">1st Round</div><table class="full-draft"> <tr>...</tr> </table>
  const roundRe = /class="round-title">(\d+)\w*\s+Round<\/div>\s*<table class="full-draft">([\s\S]*?)<\/table>/g;
  for (const [, roundStr, table] of html.matchAll(roundRe)) {
    const round = Number(roundStr);
    for (const [, row] of table.matchAll(/<tr>([\s\S]*?)<\/tr>/g)) {
      const pickCell = row.match(/<td class="pick-number">(\d+)([\s\S]*?)<\/td>/);
      if (!pickCell) continue;
      const owner = row.match(/<div class="team-link"><a href="\/nfl\/([^"]+)">[\s\S]*?<img class="logo-thumb" src="([^"]+)"[\s\S]*?<div class="desktop">([^<]*)<\/div>/);
      const trade = row.match(/<div class="trade">[\s\S]*?<a[^>]*href="\/nfl\/([^"]+)"[\s\S]*?<img class="logo-thumb" src="([^"]+)"/);
      const team = abbrFromLogo(owner[2]);
      const city = decode(owner[3]).replace(/^(NY|LA)\b/, (m) => CITY[m]);
      const logo = https(owner[2]);
      const nick = nickname(owner[1]);
      teams[team] ??= { name: city.endsWith(nick) ? city : `${city} ${nick}`, logo, slug: owner[1] };
      const from = trade ? abbrFromLogo(trade[2]) : null;
      order.push({
        pick: Number(pickCell[1]),
        round,
        team,
        teamName: teams[team].name,
        from,
        logo,
        comp: /Compensatory pick/.test(pickCell[2]),
      });
    }
  }
  return { order, teams };
}

// Tankathon has no explicit team-needs page; its mock (rounds 1-3 + comp) is "need-weighted",
// so a team's mock positions in pick order are the closest published proxy for its needs.
function parseMock(html) {
  const picks = [];
  const blocks = html.split('<div class="mock-row nfl">').slice(1);
  for (const b of blocks) {
    const pick = Number(b.match(/mock-row-pick-number">(\d+)/)?.[1]);
    const team = b.match(/mock-row-logo">[\s\S]*?alt="([^"]+)"/)?.[1];
    const name = b.match(/mock-row-name[^>]*>([^<]*)</)?.[1];
    const pos = b.match(/mock-row-school-position[^>]*>([^|<]+)\|([^<]*)</);
    if (!pick || !team || !pos) continue;
    picks.push({ pick, team, player: decode(name ?? ''), label: pos[1].trim(), school: decode(pos[2]) });
  }
  return picks;
}

export async function fetchTankathon() {
  const [fullHtml, mockHtml] = await Promise.all([get('/nfl/full-draft'), get('/nfl/mock-draft')]);
  const { order, teams } = parseFullDraft(fullHtml);
  if (order.length < 96) throw new Error(`Only parsed ${order.length} picks; Tankathon markup changed?`);
  const mock = parseMock(mockHtml);
  const roundOf = new Map(order.map((o) => [o.pick, o.round]));

  const needs = Object.fromEntries(Object.keys(teams).sort().map((t) => [t, []]));
  for (const m of mock) {
    const list = (needs[m.team] ??= []);
    const group = toGroup(m.label);
    // Keep the first (highest-priority) occurrence of each group.
    if (list.some((n) => n.group === group && group)) continue;
    list.push({ label: m.label, group, pick: m.pick, round: roundOf.get(m.pick) ?? null, player: m.player });
  }

  return {
    source: { order: BASE + '/nfl/full-draft', needs: BASE + '/nfl/mock-draft', fetchedAt: new Date().toISOString() },
    order,
    needs,
    teams,
    mock,
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const data = await fetchTankathon();
  const out = process.argv[2] ?? new URL('./tankathon.json', import.meta.url).pathname;
  const { writeFile } = await import('node:fs/promises');
  await writeFile(out, JSON.stringify(data, null, 2));
  console.log(`picks=${data.order.length} teams=${Object.keys(data.teams).length} mock=${data.mock.length} -> ${out}`);
}
