// temporary: what FACEIT returns for an ESEA playoff championship (public data only)
const KEY = process.env.FACEIT_API_KEY, API = 'https://open.faceit.com/data/v4';
const api = async p => { const r = await fetch(API + p, { headers: { Authorization: `Bearer ${KEY}` } }); return r.ok ? r.json() : { status: r.status }; };
const TEAM = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a';
for (const q of ['S59 NA Main A - Playoffs', 'S58 NA Main A - Playoffs', 'S58 NA Main - Playoffs', 'S59 NA Main - Playoffs'])
  for (const type of ['all', 'upcoming', 'ongoing', 'past']) {
    const r = await api(`/search/championships?name=${encodeURIComponent(q)}&game=cs2&type=${type}&limit=20`);
    console.log('search', q, type, (r.items || []).map(x => `${x.name} [${x.competition_id || x.championship_id}] ${x.status} ${x.organizer_id}`).join(' | ').slice(0, 1500));
  }
const t = await api(`/teams/${TEAM}/tournaments?limit=50`);
console.log('team tournaments', JSON.stringify((t.items || []).map(x => [x.name, x.championship_id || x.tournament_id, x.status])).slice(0, 2000));
const org = '08b06cfc-74d0-454b-9a51-feda4b6b18da';
for (const type of ['upcoming', 'ongoing', 'past', 'all']) {
  let n = 0; const hit = [];
  for (let off = 0; off < 5000; off += 100) {
    const r = await api(`/organizers/${org}/championships?type=${type}&offset=${off}&limit=100`);
    const it = r.items || []; n += it.length;
    for (const x of it) if (/S5[89].*NA.*(Main|Advanced)/i.test(x.name || '')) hit.push(`${x.name} [${x.championship_id}] ${x.status} start=${x.championship_start}`);
    if (it.length < 100) break;
  }
  console.log('org', type, n, hit.join(' | '));
}
const id = process.env.PO_ID;
if (id) {
  const c = await api(`/championships/${id}`); console.log('champ', JSON.stringify(c).slice(0, 1500));
  const m = await api(`/championships/${id}/matches?type=all&limit=100`);
  const it = m.items || [];
  console.log('matches', it.length, 'keys', Object.keys(it[0] || {}).join(','));
  for (const x of it.slice(0, 100)) console.log(JSON.stringify({ id: x.match_id, round: x.round, group: x.group, pos: x.position, status: x.status, at: x.scheduled_at, f1: x.teams?.faction1?.name, f1id: x.teams?.faction1?.faction_id, f2: x.teams?.faction2?.name, w: x.results?.winner, s: x.results?.score, bo: x.best_of, fin: x.finished_at }));
}
