// ESPN play-by-play for college games, slimmed to the fields sitByGame (cfb_model.mjs) reads from CFBD plays, so the
// game model's situational splits can be built without CFBD's monthly quota. ESPN event and team ids are CFBD's.
//   node scripts/cfb_espn_plays.mjs <md.json.gz> <out.json.gz>     # every FBS game in the dump's 2025 and 2026 seasons
// Slim plays are cached per game in scripts/.cache/cfb/espnplays/<id>.json.
import zlib from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DIR = path.join(ROOT, 'scripts', '.cache', 'cfb', 'espnplays');
const UA = 'Mozilla/5.0 (arkndjl.net arkboard)';

export function slim(d, gid, nameOf) {
  const out = [];
  for (const dr of d?.drives?.previous || []) for (const p of dr.plays || []) {
    const o = p.start?.team?.id, s = p.start || {};
    if (!o) continue;
    const ho = String(o) === String(d.header?.competitions?.[0]?.competitors?.find(c => c.homeAway === 'home')?.id);
    out.push({ g: gid, o: nameOf[String(o)] || String(o), q: p.period?.number, ytg: s.yardsToEndzone, dn: s.down, ds: s.distance,
      y: p.statYardage, t: p.type?.text, sm: ho ? (p.homeScore ?? 0) - (p.awayScore ?? 0) : (p.awayScore ?? 0) - (p.homeScore ?? 0), x: p.text });
  }
  return out;
}

async function pull(id) {
  const f = path.join(DIR, `${id}.json`);
  if (fs.existsSync(f)) return JSON.parse(fs.readFileSync(f, 'utf8'));
  for (let i = 0; i < 3; i++) {
    try {
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event=${id}`, { headers: { 'user-agent': UA } });
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json();
      fs.writeFileSync(f, JSON.stringify(d.drives ? { drives: d.drives, header: { competitions: d.header?.competitions?.map(c => ({ competitors: c.competitors?.map(x => ({ id: x.id, homeAway: x.homeAway })) })) } } : {}));
      return JSON.parse(fs.readFileSync(f, 'utf8'));
    } catch (e) { await new Promise(r => setTimeout(r, 1000 * (i + 1))); }
  }
  return null;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [mdPath, outPath] = process.argv.slice(2);
  const data = JSON.parse(zlib.gunzipSync(fs.readFileSync(mdPath)));
  fs.mkdirSync(DIR, { recursive: true });
  const nameOf = {};
  const games = [];
  for (const S of [2025, 2026]) for (const g of data.games[S] || []) {
    nameOf[String(g.homeId)] = g.homeTeam; nameOf[String(g.awayId)] = g.awayTeam;
    if (g.completed && (g.homeClassification === 'fbs' || g.awayClassification === 'fbs')) games.push(g);
  }
  const plays = {};
  let i = 0, miss = 0;
  const work = async () => { while (i < games.length) { const g = games[i++]; const d = await pull(g.id); if (!d?.drives) { miss++; continue; } (plays[g.season] ||= []).push(...slim(d, g.id, nameOf)); } };
  await Promise.all(Array.from({ length: 12 }, work));
  console.log(`${games.length} games, ${miss} without plays;`, Object.entries(plays).map(([S, l]) => `${S} ${l.length} plays`).join(', '));
  fs.writeFileSync(outPath, zlib.gzipSync(JSON.stringify(plays)));
}
