const H={'User-Agent':'Mozilla/5.0',Accept:'application/json'};
const r=await fetch('https://www.faceit.com/api/rules/v1/rules/662ad366-dcdc-401a-bb8b-e7571048f946',{headers:H});
const b=(await r.json()).payload.body;
const i=b.indexOf('# Playoffs');const seg=b.slice(i,i+26000);
for(const ln of seg.split('\n'))console.log('|'+ln);
const j=b.search(/# Prize/i);console.log('PRIZE AT',j);if(j>=0)for(const ln of b.slice(j,j+8000).split('\n'))console.log('$'+ln);
