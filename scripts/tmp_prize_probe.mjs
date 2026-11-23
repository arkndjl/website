const K=process.env.FACEIT_API_KEY, L='a14b8616-45b9-4581-8637-4dfd0b5f6af8';
const H={'User-Agent':'Mozilla/5.0',Accept:'application/json'}, O={Authorization:'Bearer '+K,Accept:'application/json'};
function walk(o,p,out){if(o&&typeof o==='object'){for(const[k,v]of Object.entries(o)){const q=p+'.'+k;if(/prize|reward|promot|relegat|move|qualif|placement|description|rules/i.test(k))out.push(q+' = '+JSON.stringify(v).slice(0,1500));walk(v,q,out)}}}
async function g(u,h){try{const r=await fetch(u,{headers:h});const t=await r.text();console.log('==',r.status,u,t.length);let j;try{j=JSON.parse(t)}catch{console.log(t.slice(0,300));return}const out=[];walk(j,'',out);console.log(out.slice(0,60).join('\n')||t.slice(0,1500));return j}catch(e){console.log('ERR',u,e.message)}}
const lg=await g(`https://open.faceit.com/data/v4/leagues/${L}`,O);
const s=await g(`https://open.faceit.com/data/v4/leagues/${L}/seasons/59`,O);
console.log(JSON.stringify(s).slice(0,4000));
await g(`https://www.faceit.com/api/team-leagues/v1/leagues/${L}`,H);
await g(`https://www.faceit.com/api/team-leagues/v2/leagues/${L}/seasons`,H);
await g(`https://www.faceit.com/api/team-leagues/v1/seasons/71f19bf6`,H);
await g(`https://www.faceit.com/api/team-leagues/v2/conferences/f3e8413f-d07c-44a1-a39c-1045637223d5`,H);
await g(`https://www.faceit.com/api/team-leagues/v1/conferences/f3e8413f-d07c-44a1-a39c-1045637223d5`,H);
