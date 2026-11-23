// temporary: league-page ids -> championship ids
const T = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a', L = 'a14b8616-45b9-4581-8637-4dfd0b5f6af8', S = '71f19bf6-4032-4b65-8b4a-6f98a6d271d3';
const R = '422d07b7-5bd7-4a63-8aec-23d7d9335a36', D = 'f610b5c3-6c61-4f0b-89c7-6f7e2a552227', ST = '057c8ad5-617e-40c0-bf90-434fa8b3a24d', CF = 'f3e8413f-d07c-44a1-a39c-1045637223d5';
const KEY = process.env.FACEIT_API_KEY;
const show = (k, v) => console.log(`--- ${k}\n${String(typeof v === 'string' ? v : JSON.stringify(v)).slice(0, 1500)}`);
const web = async u => { try { const r = await fetch('https://www.faceit.com/api/' + u, { headers: { 'User-Agent': 'Mozilla/5.0', Accept: 'application/json' } }); const t = await r.text(); return { s: r.status, t: /<html/i.test(t) ? '[html]' : t }; } catch (e) { return { e: e.message }; } };
const open = async p => { const r = await fetch('https://open.faceit.com/data/v4' + p, { headers: { Authorization: `Bearer ${KEY}` } }); return { s: r.status, t: (await r.text()) }; };
for (const id of [CF, ST, D]) show('open champ ' + id.slice(0, 8), await open(`/championships/${id}`));
for (const u of [`team-leagues/v2/teams/${T}/leagues/${L}/seasons/${S}`, `team-leagues/v1/teams/${T}/leagues/${L}/seasons/${S}`, `team-leagues/v2/leagues/${L}/seasons/${S}`, `team-leagues/v1/leagues/${L}/seasons/${S}`,
  `team-leagues/v2/seasons/${S}/regions/${R}/divisions/${D}/stages/${ST}/conferences/${CF}`, `team-leagues/v2/conferences/${CF}`, `team-leagues/v1/conferences/${CF}`, `team-leagues/v2/stages/${ST}`, `team-leagues/v2/standings?entityId=${CF}&entityType=conference&offset=0&limit=5`,
  `team-leagues/v1/seasons/${S}`, `team-leagues/v2/leagues/${L}/seasons/${S}/regions/${R}/divisions/${D}`]) { const r = await web(u); show(`${r.s} ${u.slice(0, 90)}`, r.t || r.e); }
