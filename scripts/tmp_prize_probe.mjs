const C='9ca95311-2810-48a3-a474-a8cc6b480346';
const H={'User-Agent':'Mozilla/5.0',Accept:'application/json'};
const r=await fetch(`https://www.faceit.com/api/championships/v1/championship/${C}`,{headers:H});const j=(await r.json()).payload;
console.log('KEYS',Object.keys(j).join(','));
for(const k of Object.keys(j)) if(k!=='roles'){const s=JSON.stringify(j[k]);console.log('##',k,s.slice(0,3000));}
