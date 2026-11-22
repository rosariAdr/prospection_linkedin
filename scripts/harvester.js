window.__H=[]; window.__R=[]; window.__doneKeys=new Set(); window.__links=[];
try{Clipboard.prototype.writeText=function(t){window.__links.push(String(t)); return Promise.resolve();};}catch(e){}
// Pré-filtre : >>> ADAPTER CES DEUX REGEX AU DOMAINE VISÉ <<<
window.__isCand=function(t){
  return /(recrut|recherch|cherchons|cherche|besoin|rejoign|vivier|réseau d|appel à|candidat|postul)/i.test(t)
      && /(formateur|intervenant|enseignant|vacataire|professeur|jury)/i.test(t);
};
// Date relative : TOUJOURS suivie d'un « • » dans l'en-tête de carte (voir §8)
window.__dateOf=function(card){
  const t=(card.innerText||'').substring(0,600);
  const m=[...t.matchAll(/(\d+)\s*(min|h|j|sem|mois|an)s?\s*(?=•)/g)];
  return m.length ? m[m.length-1][0].trim() : '';
};
window.__proc=async function(){
  const sleep=ms=>new Promise(r=>setTimeout(r,ms)); let n=0;
  for(const card of [...document.querySelectorAll('[role="listitem"]')]){
    const btn=card.querySelector('button[aria-label*="menu de commandes"]'); if(!btn) continue;
    const auteur=(btn.getAttribute('aria-label')||'').replace('Ouvrir le menu de commandes pour le post de ','').trim();
    const txt=(card.innerText||'').trim().replace(/\s+/g,' ');
    const key=auteur+'|'+txt.substring(0,80);
    if(window.__doneKeys.has(key)) continue; window.__doneKeys.add(key); n++;
    const dr=window.__dateOf(card);
    if(!window.__isCand(txt)){ window.__R.push({a:auteur, e:txt.substring(30,95)}); continue; }
    const prof=card.querySelector('a[href*="/in/"], a[href*="/company/"]'); const nb=window.__links.length;
    btn.click(); await sleep(800);
    const item=[...document.querySelectorAll('[role="menuitem"]')].find(e=>/Copier le lien/i.test(e.innerText));
    if(item){item.click(); await sleep(700);}
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); await sleep(300);
    const link=window.__links.length>nb ? window.__links[window.__links.length-1].split('?')[0] : '';
    window.__H.push({auteur, profil: prof?(prof.getAttribute('href')||'').split('?')[0]:'', link, date_rel: dr, texte: txt.substring(0,900)});
  }
  return JSON.stringify({nouveaux:n, candidats:window.__H.length, rejetes:window.__R.length});
};
await window.__proc()
```
```javascript
const p=window.__H[0]; JSON.stringify({i:0,a:p.auteur,pr:p.profil,l:p.link,d:p.date_rel,t:p.texte.substring(0,750)})
