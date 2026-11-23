// temporary: playoff match structure (position, next-round links)
const C = '9ca95311-2810-48a3-a474-a8cc6b480346', KEY = process.env.FACEIT_API_KEY;
const show = (k, v) => console.log(`--- ${k}\n${String(typeof v === 'string' ? v : JSON.stringify(v)).slice(0, 3500)}`);
const r = await fetch(`https://open.faceit.com/data/v4/championships/${C}/matches?type=all&limit=100`, { headers: { Authorization: `Bearer ${KEY}` } });
const j = await r.json(); const it = j.items || [];
show('open n / keys', { n: it.length, keys: Object.keys(it[0] || {}) });
show('open sample', it.slice(0, 2).map(m => ({ ...m, teams: { f1: { id: m.teams?.faction1?.faction_id, n: m.teams?.faction1?.name }, f2: { id: m.teams?.faction2?.faction_id, n: m.teams?.faction2?.name } }, detailed_results: undefined })));
show('open round counts', it.reduce((a, m) => (a[`${m.group}-${m.round}`] = (a[`${m.group}-${m.round}`] || 0) + 1, a), {}));
for (const u of [`championships/v1/matches?championshipId=${C}&limit=100&offset=0`, `championships/v1/championship/${C}/matches?limit=100&offset=0`, `championships/v2/championship/${C}/bracket`, `championships/v1/championship/${C}/bracket`, `championships/v1/bracket?championshipId=${C}`]) {
  const w = await fetch('https://www.faceit.com/api/' + u, { headers: { 'User-Agent': 'Mozilla/5.0', Accept: 'application/json' } }); const t = await w.text();
  let o = null; try { o = JSON.parse(t); } catch {}
  const items = o?.payload?.items || o?.payload || o?.items;
  show(`web ${w.status} ${u}`, Array.isArray(items) ? { n: items.length, keys: Object.keys(items[0] || {}), s0: items[0], s5: items.find(x => /UB ?6\b/.test(JSON.stringify(x))) } : (/<html/i.test(t) ? '[html]' : t.slice(0, 1500)));
}
