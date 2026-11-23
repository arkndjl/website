const K=process.env.FACEIT_API_KEY, C='9ca95311-2810-48a3-a474-a8cc6b480346';
const H={'User-Agent':'Mozilla/5.0',Accept:'application/json'};
async function g(u,h){try{const r=await fetch(u,{headers:h});const t=await r.text();console.log('==',r.status,u);console.log(t.slice(0,6000));}catch(e){console.log('ERR',u,e.message)}}
await g(`https://open.faceit.com/data/v4/championships/${C}?expanded=organizer,game`,{Authorization:'Bearer '+K,Accept:'application/json'});
await g(`https://www.faceit.com/api/championships/v1/championship/${C}`,H);
await g(`https://www.faceit.com/api/championships/v1/championship/${C}/prizes`,H);
await g(`https://www.faceit.com/api/team-leagues/v1/championships/${C}`,H);
