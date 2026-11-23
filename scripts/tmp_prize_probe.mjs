const L='a14b8616-45b9-4581-8637-4dfd0b5f6af8';
const H={'User-Agent':'Mozilla/5.0',Accept:'application/json'};
async function g(u){try{const r=await fetch(u,{headers:H});const t=await r.text();console.log('==',r.status,u,t.length);return [r.status,t]}catch(e){console.log('ERR',u,e.message);return [0,'']}}
const [,t]=await g(`https://www.faceit.com/api/team-leagues/v2/leagues/${L}/seasons`);
const P=JSON.parse(t).payload;
console.log('FIELDS',Object.keys(P[0]).join(','));
console.log(P.map(x=>[x.season_number??x.number??x.name,x.id,x.rules_id,x.total_prize_pool].join(' ')).join('\n'));
const s=P.find(x=>JSON.stringify(x).includes('59'))&&P.find(x=>(x.season_number??x.number)==59)||P[0];
console.log('S59',JSON.stringify(s).slice(0,9000));
for(const p of [`team-leagues/v2/seasons/${s.id}`,`team-leagues/v2/seasons/${s.id}/stages`,`team-leagues/v2/seasons/${s.id}/divisions`,`team-leagues/v2/seasons/${s.id}/prizes`,`team-leagues/v2/rules/${s.rules_id}`,`team-leagues/v1/rules/${s.rules_id}`,`rules/v1/rules/${s.rules_id}`,`team-leagues/v2/stages/057c8ad5-617e-40c0-bf90-434fa8b3a24d`]){const [st,b]=await g('https://www.faceit.com/api/'+p);if(st===200)console.log(b.slice(0,12000));}
