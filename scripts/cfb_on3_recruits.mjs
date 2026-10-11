// On3 / Rivals recruiting lists by class, for the recruit FV fit and the future-class tabs.
// Every position's ranking (50 a page) through the last page: Rivals rating and stars, On3's industry
// consensus, size, state, high school, early enrollee, age, the count of schools in on him, commitment.
//
//   node scripts/cfb_on3_recruits.mjs 2023 2024 ...   # cached in scripts/.cache/recruit/on3-<year>.json
//
// Needs Playwright (Chromium): On3 turns away plain requests. A past class is pulled once; the
// classes still being recruited are pulled again when their cache is a day old.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'recruit');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const POSITIONS = ['qb', 'rb', 'wr', 'te', 'ot', 'iol', 'edge', 'dl', 'lb', 'cb', 's', 'ath'];

async function chromium() {
  for (const m of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) {
    try { const pw = await import(m); return pw.chromium || pw.default?.chromium; } catch {}
  }
  return null;
}

function slim(it) {
  const p = it.person || {}, r = p.rating || {}, s = p.status || {};
  return { key: p.key, name: p.name, pos: p.positionAbbreviation, ht: p.height || null, wt: p.weight || null, state: r.stateAbbr || null, hs: p.highSchoolName || null,
    rating: r.rating ?? null, stars: r.stars ?? null, rank: r.nationalRank ?? null, posRank: r.positionRank ?? null,
    cons: r.consensusRating ?? null, consStars: r.consensusStars ?? null, consRank: r.consensusNationalRank ?? null,
    early: !!p.earlyEnrollee, age: p.age ?? null, interest: s.interestCount ?? null, committed: !!s.isCommitted, school: s.committedOrganizationSlug || null };
}

export async function on3Class(year, { fresh = false, offline = false } = {}) {
  const f = path.join(CACHE, `on3-${year}.json`);
  if (fs.existsSync(f) && (offline || (!fresh) || Date.now() - fs.statSync(f).mtimeMs < 20 * 3600e3)) return JSON.parse(fs.readFileSync(f, 'utf8'));
  if (offline) return null;
  const ch = await chromium(); if (!ch) return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : null;
  const b = await ch.launch(fs.existsSync('/opt/pw-browsers/chromium') ? { executablePath: '/opt/pw-browsers/chromium' } : {});
  const out = {};
  try {
    const pages = await Promise.all([0, 1, 2, 3].map(() => b.newPage({ userAgent: UA })));
    const queue = POSITIONS.map(p => [p, 1]);
    const pull = async (pg, pos, n) => {
      const url = `https://www.on3.com/rivals/rankings/player/football/${year}/?position=${pos}${n > 1 ? `&page=${n}` : ''}`;
      for (let i = 0; i < 3; i++) {
        try {
          await pg.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
          const m = /<script id="__NEXT_DATA__"[^>]*>(.*?)<\/script>/s.exec(await pg.content());
          const pd = m && JSON.parse(m[1]).props?.pageProps?.playerData;
          if (pd) return pd;
        } catch {}
        await new Promise(r => setTimeout(r, 2000 * (i + 1)));
      }
      return null;
    };
    await Promise.all(pages.map(async pg => {
      while (queue.length) {
        const [pos, n] = queue.shift();
        const pd = await pull(pg, pos, n); if (!pd) continue;
        for (const it of pd.list || []) { const x = slim(it); if (x.key) out[x.key] = x; }
        if (n === 1) for (let k = 2; k <= (pd.pagination?.pageCount || 1); k++) queue.push([pos, k]);
      }
    }));
  } finally { await b.close(); }
  const list = Object.values(out);
  if (list.length) { fs.mkdirSync(CACHE, { recursive: true }); fs.writeFileSync(f, JSON.stringify(list)); }
  return list;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  for (const y of process.argv.slice(2).map(Number)) { const l = await on3Class(y, { fresh: true }); console.log(y, l?.length ?? 0); }
}
