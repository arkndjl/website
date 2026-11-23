// temporary: playoff match structure via the web match list (needs a participant)
const C = '9ca95311-2810-48a3-a474-a8cc6b480346', KG = '4f76684c-c780-4028-9946-60d1282a15db', T = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a';
const show = (k, v) => console.log(`--- ${k}\n${String(typeof v === 'string' ? v : JSON.stringify(v)).slice(0, 5000)}`);
for (const [pid, pt] of [[KG, 'TEAM'], [T, 'TEAM'], [KG, 'team'], ['', 'TEAM']]) {
  const u = `championships/v1/matches?championshipId=${C}&participantId=${pid}&participantType=${pt}&limit=10&offset=0`;
  const w = await fetch('https://www.faceit.com/api/' + u, { headers: { 'User-Agent': 'Mozilla/5.0', Accept: 'application/json' } }); const t = await w.text();
  show(`${w.status} ${pid.slice(0, 8)} ${pt}`, /<html/i.test(t) ? '[html]' : t);
}
