"""The page /naht: the loops of an outfit as see through layers, to set their seams by eye (2.165.0, layers since 2.167.0).

Metin, 25 Nov 2026, 01:36: "Ich wünschte, ich könnte ein Ende und einen Anfang vor mir haben
wie eine transparente Schablone, die ich übereinander legen könnte, und die Zeit so speichern."
He saw a small shadow where one loop hands over to the next: the two pictures do not lie on
each other. Numbers from outside did not settle it, his eye does.

02:15, after two versions with two fixed stencils: "ich möchte sie ein und ausblenden können,
daher brauche ich Schleifen, die ich einzeln transparent oder nicht transparent machen kann, in
voller Clip Länge, die ich in der Zeitachse kürzen kann, aber nicht alle Schleifen zusammen,
sondern jede Schleife einzeln". So the page is built from layers:

Every loop of the outfit is one layer (`LAY`), and any other clip can be added as one (the touch
clips are named Kopf, Brust, Bauch, Po). A layer is a still picture of its clip that lies over the
others. It has: visible or not (`on`), how see through (`op`), the picture it shows (`t`, its
play head), its begin mark (`s`), its end mark (`e`) and its lead (`ld`). One slider with fine
steps (a picture, 0.01 s, 0.001 s) moves whichever of these four is chosen; moving a mark shows
the picture at that mark. A layer can play on its own from its play head to its end mark.

The time axis at the bottom has one bar per layer over the full length of its clip: the bright
part is what stays, its two edges are dragged to make it shorter or longer, a tap or drag inside
moves the play head. Each bar is on its own.

"Übergabe zeigen" lays two layers on each other the way the app does when a loop hands over
(memory_web.stageShow with TIGHT): the new clip starts at its begin mark `lead` seconds of clip
time before the end mark of the old one and fades in for HAND_FADE seconds, the old clip runs on
to its end mark and holds its last picture. The view is the moment the old one has reached its
last picture: old at its end mark, new at begin + lead (in its own tempo). "So spielt es die App"
plays that hand over once in real time. "Unterschied" shows the difference of the top layer to
what is below: black lies exactly on each other, what glows does not.

One button stores every changed begin and end mark (POST /api/schnitt, in thousandths of a
second) and every changed lead (POST /api/vorlauf). The clip files are never touched. A clip has
ONE begin mark, ONE end mark and ONE lead, used at every hand over, not one per pair. A tempo
curve inside a clip is not taken into account (the stored tempo is).

The lead (2.166.0): how long before the end mark of the old clip the new one comes in was fixed
(HAND_PRE, 0.25 s). It is a value per clip (`l` in /clips.json, `LEAD` in the app, in /ganzes
and here; no entry = HAND_PRE) and belongs to the clip that comes in.

The script is a raw string: keep it free of backslashes and check it with node --check
(tests/test_naht.py does) before every commit. Whoever changes PRE, OFF or the fade of loops
in memory_web.stageShow must change HAND_PRE, HAND_OFF and HAND_FADE here too (a test compares).
"""

HAND_PRE = 0.25   # the next loop starts this long (clip time) before the end mark of the running one
HAND_OFF = 300    # ms after which the old clip begins to fade out
HAND_FADE = 0.8   # seconds the new clip fades in

PAGE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Naht: Schleifen als Ebenen</title><style>
html,body{margin:0;height:100%;overflow:hidden;background:#000;color:#eee;font:13px system-ui}
h1{font-size:14px;margin:6px 8px}
h2{font-size:13px;margin:0 0 4px;color:#9fe8ff;font-weight:600}
a{color:#9fe8ff}
#st{position:fixed;top:0;right:0;height:100%;aspect-ratio:2/3;max-width:100vw;overflow:hidden;background:#000}
#st video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0}
#panel{position:fixed;top:0;left:0;bottom:var(--axh,100px);width:min(58vw,360px);overflow-y:auto;background:rgba(0,0,0,.30);padding-bottom:10px;z-index:3}
body.hide #panel{display:none}
@media (min-aspect-ratio:1/1){#panel{width:calc(100vw - 100vh*2/3);max-width:none;background:#000}}
#axbar{position:fixed;left:0;right:0;bottom:0;height:var(--axh,100px);z-index:4;background:rgba(0,0,0,.72)}
#ax{width:100%;height:100%;display:block;touch-action:none;cursor:ew-resize}
#top{position:fixed;top:6px;right:6px;z-index:5;display:flex;gap:6px;align-items:center;flex-direction:row-reverse}
#busy{font-size:12px;color:#fd8;background:rgba(0,0,0,.55);padding:4px 7px;border-radius:8px;visibility:hidden}
body.busy #busy{visibility:visible}
.card{margin:6px;padding:6px 8px;border:1px solid #334;border-radius:10px;background:rgba(0,0,0,.42)}
.card.lay.off{opacity:.62}
.bar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:4px 0}
select,button{padding:6px 8px;border-radius:8px;background:rgba(34,34,34,.9);color:#eee;border:1px solid #445;font:inherit}
select{max-width:100%}
button.on{border-color:#2a6;color:#9f9}
.t{font-size:12px;color:#9ab}
.z{color:#9ab;font-size:12px;min-width:44px}
.n{font-weight:600;color:#fff}
.ttl{font-weight:600;color:#9fe8ff;flex:1}
label{display:flex;gap:4px;align-items:center}
input[type=range]{flex:1 1 120px;min-width:120px}
</style></head><body>
<div id="st"></div>
<div id="axbar"><canvas id="ax"></canvas></div>
<div id="top"><button id="tog">☰</button><span id="busy">Bild wird geholt ...</span></div>
<div id="panel"><h1>Naht: Schleifen als Ebenen &nbsp; <a href="/ganzes" style="font-size:12px;font-weight:400">Outfit als Ganzes</a></h1>
<div class="card"><h2>1. Kleid</h2>
<div class="bar"><select id="look"></select></div>
<div class="bar"><span class="z">dazu</span><select id="add"></select></div>
<div class="t">Jede Schleife ist eine eigene Ebene, die über den anderen liegt. Einzeln ein und ausblenden, einzeln durchsichtig, einzeln kürzen. Unten hat jede ihren eigenen Balken in voller Länge.</div></div>
<div class="card"><h2>2. Übergabe ansehen</h2>
<div class="bar"><span class="z">von</span><select id="hf"></select></div>
<div class="bar"><span class="z">nach</span><select id="ht"></select></div>
<div class="bar"><button id="hv">Übergabe zeigen</button><button id="play">So spielt es die App</button><button id="diff">Unterschied</button></div>
<div class="t">Übergabe zeigen legt das Ende der einen und den Anfang der anderen so übereinander wie in der App. Unterschied: was schwarz ist, liegt genau aufeinander.</div></div>
<div class="card"><h2>3. Merken</h2>
<div class="bar"><button id="save">Alle Zeiten merken</button><button id="back">zurück auf gemerkt</button></div>
<div class="t" id="sinfo"></div>
<div class="t">Jeder Clip hat einen Anfang, ein Ende und einen Einsatz. Sie gelten bei jedem Wechsel.</div></div>
<div class="card"><h2>4. Ebenen</h2>
<div class="bar"><button id="pall">▶ alle sichtbaren abspielen</button><button id="gall">alle zum Anfang</button></div>
<div class="t">Alle sichtbaren Ebenen starten im selben Augenblick, jede ab ihrem Bild, und laufen bis zu ihrem Ende. Noch einmal drücken hält alle an.</div></div>
<div id="cards"></div></div>
<script>
const $=id=>document.getElementById(id);
const OUT=[['Kurzes Arbeitskleid','kurz',''],['Kurzes Freizeitkleid','kurz','freizeit'],['Langes Arbeitskleid','schwarz',''],['Langes Freizeitkleid','schwarz','freizeit'],['Nachtkleid','nacht','']];
const ZONES=[['Kopf',['gesicht']],['Brust',['brust']],['Bauch',['bauch']],['Po',['po','povorne']],['Mix',['mix']]];  /* the touch clips, as Metin names them (01:46: Kopf, Brust, Po, Bauch) */
const HAND_PRE=0.25,HAND_OFF=300,HAND_FADE=0.8,FRAME=1/24,MINLEN=0.5,LEAD_MAX=1.5;  /* as the loops of the app hand over (memory_web.stageShow, TIGHT) */
let LOOK='',PRE='',CL=[],VER={},RATE={},KURVE={},SCHNITT={},LEAD={},LAY=[],PLAYING=false,TOK=0,STOK=0,PEND=0,AXD=null,ZTOP=1;
const base=n=>n.replace(/[0-9]+$/,'');
const mine=n=>PRE?n.startsWith(PRE):!n.startsWith('freizeit');
const pth=n=>LOOK+'/'+n;
const rate=n=>RATE[pth(n)]||1;
const r3=x=>Math.round(x*1000)/1000;
const cmp=(x,y)=>x.localeCompare(y,'de',{numeric:true});
const isLoop=n=>base(n)===PRE+'gluecklich';
const lay=n=>LAY.find(L=>L.n===n);
const q=(L,k)=>L.el.querySelector('[data-k='+k+']');
function title(n){const all=CL.filter(mine).sort(cmp),loops=all.filter(isLoop);if(isLoop(n))return 'Schleife '+(loops.indexOf(n)+1);
 for(const [zone,kinds] of ZONES){const zs=all.filter(x=>kinds.includes(base(x).slice(PRE.length))),i=zs.indexOf(n);if(i>=0)return zone+(zs.length>1?' '+(i+1):'');}return n;}
const savedS=L=>{const c=SCHNITT[pth(L.n)];return c&&c[0]>0?c[0]:0;};
const savedE=L=>{const c=SCHNITT[pth(L.n)];return c&&c[1]>0&&c[1]<L.d?c[1]:L.d;};
const savedL=L=>{const l=LEAD[pth(L.n)];return l===undefined?HAND_PRE:l;};
const changed=L=>!!L.d&&(Math.abs(L.s-savedS(L))>0.0004||Math.abs(L.e-savedE(L))>0.0004||Math.abs(L.ld-savedL(L))>0.0004);
const val=(L,k)=>k==='s'?L.s:k==='e'?L.e:k==='l'?L.ld:L.t;
/* one value of one layer; moving a mark shows the picture at that mark */
function setVal(L,k,x){if(!L.d)return;stop();soloStop(L);
 if(k==='s'){L.s=r3(Math.max(0,Math.min(L.e-MINLEN,x)));L.t=L.s;}
 else if(k==='e'){L.e=r3(Math.max(L.s+MINLEN,Math.min(L.d,x)));L.t=L.e;}
 else if(k==='l')L.ld=r3(Math.max(0,Math.min(LEAD_MAX,x)));
 else L.t=r3(Math.max(0,Math.min(L.d,x)));show();}
function busy(){document.body.classList.toggle('busy',LAY.some(L=>L.on&&!L.play&&(L.v.seeking||L.v.readyState<2)));}
function seek(v,t){if(Math.abs(v.currentTime-t)>0.0004){try{v.currentTime=t;}catch(e){}}}
function show(){draw();if(PLAYING)return;clearTimeout(PEND);PEND=setTimeout(()=>{if(PLAYING)return;for(const L of LAY)if(L.on&&L.d&&!L.play)seek(L.v,L.t);busy();},60);}
const top1=()=>LAY.filter(L=>L.on).sort((a,b)=>b.z-a.z)[0];
function draw(){const diff=document.body.classList.contains('diff'),tp=top1();let ch=false;
 for(const L of LAY){if(!PLAYING){L.v.style.transition='none';L.v.style.zIndex=String(L.z);L.v.style.opacity=!L.on?'0':(diff&&L===tp&&LAY.filter(x=>x.on).length>1)?'1':String(L.op/100);
   L.v.style.mixBlendMode=diff&&L.on&&L===tp&&LAY.filter(x=>x.on).length>1?'difference':'normal';}
  if(!L.el)continue;L.el.classList.toggle('off',!L.on);q(L,'on').checked=L.on;q(L,'op').value=String(L.op);q(L,'oplab').textContent=L.op+' %';
  for(const k of ['t','s','e','l'])q(L,'m'+k).classList.toggle('on',L.mode===k);
  const p=q(L,'pos');p.max=String(L.mode==='l'?LEAD_MAX:(L.d||10));p.value=String(val(L,L.mode));
  q(L,'play').textContent=L.play?'⏸ anhalten':'▶ abspielen';const c=changed(L);ch=ch||c;
  q(L,'lab').innerHTML=!L.d?'wird geladen ...':'Bild <span class="n">'+L.t.toFixed(3)+'</span> &nbsp; Anfang <span class="n">'+L.s.toFixed(3)+'</span> &nbsp; Ende <span class="n">'+L.e.toFixed(3)+'</span> von '+L.d.toFixed(3)+' s &nbsp; Einsatz <span class="n">'+L.ld.toFixed(3)+'</span>'+(rate(L.n)!==1?' &nbsp; Tempo '+rate(L.n):'')+(KURVE[pth(L.n)]?' &nbsp; (Tempo Kurve nicht eingerechnet)':'')+(c?' &nbsp; <span style="color:#fd8">noch nicht gemerkt</span>':'');}
 $('save').classList.toggle('on',ch);$('sinfo').textContent=ch?'Noch nicht gemerkt.':'So ist es gemerkt.';$('diff').classList.toggle('on',diff);
 $('play').textContent=PLAYING?'anhalten':'So spielt es die App';$('pall').textContent=LAY.some(L=>L.play)?'⏸ alle anhalten':'▶ alle sichtbaren abspielen';axDraw();}
const HTML='<div class="bar"><label><input type="checkbox" data-k="on">sichtbar</label><span class="ttl" data-k="ttl"></span><button data-k="up" title="nach oben legen">nach oben</button></div>'
 +'<div class="bar"><span class="z">Durchsicht</span><input type="range" data-k="op" min="0" max="100" step="1" value="100"><span data-k="oplab" style="min-width:38px">100 %</span></div>'
 +'<div class="bar"><span class="z">Regler</span><button data-k="mt">Bild</button><button data-k="ms">Anfang</button><button data-k="me">Ende</button><button data-k="ml">Einsatz</button></div>'
 +'<div class="t" data-k="lab"></div>'
 +'<div class="bar"><input type="range" data-k="pos" min="0" max="10" step="0.001" value="0"></div>'
 +'<div class="bar"><button data-k="fm">◀ Bild</button><button data-k="fp">Bild ▶</button><button data-k="m1">− 0,01</button><button data-k="p1">+ 0,01</button><button data-k="m3">− 0,001</button><button data-k="p3">+ 0,001</button></div>'
 +'<div class="bar"><button data-k="play">▶ abspielen</button><button data-k="gs">zum Anfang</button><button data-k="ge">zum Ende</button><button data-k="l0">Einsatz normal</button></div>';
function card(L){const el=document.createElement('div');el.className='card lay';el.dataset.n=L.n;el.innerHTML=HTML;L.el=el;$('cards').appendChild(el);
 q(L,'ttl').textContent=title(L.n)+(title(L.n)===L.n?'':' ('+L.n+')');
 q(L,'on').onchange=()=>{L.on=q(L,'on').checked;if(!L.on)soloStop(L);stop();show();};
 q(L,'op').oninput=()=>{L.op=Number(q(L,'op').value);if(L.op>0&&!L.on)L.on=true;stop();show();};
 q(L,'up').onclick=()=>{L.z=++ZTOP;L.on=true;stop();show();};
 for(const k of ['t','s','e','l'])q(L,'m'+k).onclick=()=>{L.mode=k;if(k==='s'||k==='e')setVal(L,k,val(L,k));else show();};
 q(L,'pos').oninput=()=>setVal(L,L.mode,Number(q(L,'pos').value));
 const st=d=>()=>setVal(L,L.mode,val(L,L.mode)+d);
 q(L,'fm').onclick=st(-FRAME);q(L,'fp').onclick=st(FRAME);q(L,'m1').onclick=st(-0.01);q(L,'p1').onclick=st(0.01);q(L,'m3').onclick=st(-0.001);q(L,'p3').onclick=st(0.001);
 q(L,'play').onclick=()=>solo(L);q(L,'gs').onclick=()=>{L.mode='t';setVal(L,'t',L.s);};q(L,'ge').onclick=()=>{L.mode='t';setVal(L,'t',L.e);};
 q(L,'l0').onclick=()=>setVal(L,'l',HAND_PRE);}
function addLayer(n,on,op){let L=lay(n);if(L)return L;const v=document.createElement('video');v.playsInline=true;v.muted=true;v.preload='auto';
 const c=SCHNITT[pth(n)]||[0,0];L={n,v,on:!!on,op:op===undefined?100:op,t:0,s:c[0]>0?c[0]:0,e:0,ld:0,d:0,play:0,mode:'t',el:null,z:++ZTOP,then:null};L.ld=savedL(L);
 v.onloadedmetadata=()=>{L.d=v.duration||0;L.e=savedE(L);L.t=Math.min(L.t,L.d);if(L.then){const f=L.then;L.then=null;f();}setAx();show();};
 v.onseeked=busy;v.onseeking=busy;v.onloadeddata=busy;
 v.src='/clips/'+pth(n)+'.mp4?v='+(VER[LOOK]||0);$('st').appendChild(v);LAY.push(L);card(L);return L;}
/* when its length is known: f() now or as soon as the clip has told it */
const ready=(L,f)=>{if(L.d)f();else{const g=L.then;L.then=()=>{if(g)g();f();};}};
function setAx(){document.body.style.setProperty('--axh',(26+LAY.length*26)+'px');}
function fillSel(){const names=CL.filter(mine).sort(cmp),rest=names.filter(n=>!lay(n)),a=$('add');a.innerHTML='<option value="">einen anderen Clip als Ebene dazu ...</option>';
 const done={},add=(n,t)=>{const o=document.createElement('option');o.value=n;o.textContent=t;a.appendChild(o);};
 for(const [zone,kinds] of ZONES)rest.filter(n=>kinds.includes(base(n).slice(PRE.length))).forEach(n=>{done[n]=1;add(n,title(n)+' ('+n+')');});
 rest.forEach(n=>{if(!done[n])add(n,n);});
 for(const id of ['hf','ht']){const s=$(id),old=s.value;s.innerHTML='';LAY.forEach(L=>{const o=document.createElement('option');o.value=L.n;o.textContent=title(L.n)+(title(L.n)===L.n?'':' ('+L.n+')');s.appendChild(o);});if(lay(old))s.value=old;}}
/* two layers on each other as the app shows them when the old clip has reached its last picture */
function hand(a,b){if(!a||!b||a===b)return;stop();LAY.forEach(L=>{soloStop(L);L.on=false;});a.on=true;a.op=100;b.on=true;b.op=50;b.z=++ZTOP;a.mode='t';b.mode='t';
 ready(a,()=>ready(b,()=>{a.t=a.e;b.t=r3(Math.min(b.d,b.s+b.ld/rate(a.n)*rate(b.n)));show();}));show();}
function pick(i,a,b){const o=OUT[i];stop();LAY.forEach(L=>{L.play=0;L.v.pause();L.v.removeAttribute('src');L.v.load();L.v.remove();});LAY=[];$('cards').innerHTML='';ZTOP=1;
 LOOK=o[1];PRE=o[2];CL=(window.J.outfits[LOOK]||{}).clips||[];try{localStorage.setItem('lnaht',String(i));}catch(e){}
 const names=CL.filter(mine).sort(cmp),loops=names.filter(isLoop);loops.forEach(n=>addLayer(n,false,100));
 for(const n of [a,b])if(n&&names.includes(n))addLayer(n,false,100);
 if(!LAY.length&&names.length)addLayer(names[0],true,100);setAx();fillSel();
 const la=lay(a)||LAY[0],lb=lay(b)&&lay(b)!==la?lay(b):LAY.find(L=>L!==la);if(la)$('hf').value=la.n;if(lb){$('ht').value=lb.n;hand(la,lb);}else if(la){la.on=true;show();}}
async function start(){const j=await (await fetch('/clips.json?t='+Date.now())).json();window.J=j;const o=j.outfits||{};
 for(const look in o){VER[look]=o[look].v||0;for(const c in (o[look].r||{}))RATE[look+'/'+c]=o[look].r[c];
  for(const c in (o[look].k||{}))KURVE[look+'/'+c]=o[look].k[c];for(const c in (o[look].l||{}))LEAD[look+'/'+c]=o[look].l[c];for(const c in (o[look].s||{}))SCHNITT[look+'/'+c]=o[look].s[c].slice();}
 const s=$('look');OUT.forEach((x,i)=>{if(!o[x[1]])return;const op=document.createElement('option');op.value=String(i);op.textContent=x[0];s.appendChild(op);});
 const qs=new URLSearchParams(location.search),qa=qs.get('a')||'',qb=qs.get('b')||'';let i=-1,a='',b='';
 if(qa.includes('/')){const lk=qa.split('/')[0];a=qa.split('/')[1];b=qb.includes('/')?qb.split('/')[1]:'';i=OUT.findIndex(x=>x[1]===lk&&(x[2]==='freizeit')===a.startsWith('freizeit'));}
 if(i<0){try{i=Number(localStorage.getItem('lnaht')||1);}catch(e){i=1;}}
 if(!OUT[i]||!o[OUT[i][1]])i=Number(s.options[0].value);s.value=String(i);s.onchange=()=>pick(Number(s.value),'','');pick(i,a,b);}
$('add').onchange=()=>{const n=$('add').value;if(!n)return;const L=addLayer(n,true,50);L.z=++ZTOP;setAx();fillSel();stop();show();L.el.scrollIntoView({block:'nearest'});};
$('tog').onclick=()=>document.body.classList.toggle('hide');
$('hv').onclick=()=>hand(lay($('hf').value),lay($('ht').value));
$('diff').onclick=()=>{document.body.classList.toggle('diff');stop();show();};
function soloStop(L){if(!L.play)return;L.play=0;L.v.pause();L.v.playbackRate=1;}
function stop(){if(!PLAYING)return;PLAYING=false;TOK++;for(const L of LAY){L.v.pause();L.v.playbackRate=1;}show();}
const seeked=(v,t)=>new Promise(res=>{if(Math.abs(v.currentTime-t)<0.0004&&!v.seeking)return res();const f=()=>{v.removeEventListener('seeked',f);res();};v.addEventListener('seeked',f);try{v.currentTime=t;}catch(e){res();}});
/* one layer plays on its own from its play head to its end mark, the others stand still; pausing leaves the play head on the picture that stands */
async function solo(L){if(!L.d)return;if(L.play){L.t=r3(Math.min(L.e,L.v.currentTime));soloStop(L);show();return;}stop();const tok=++STOK;L.play=tok;L.on=true;L.mode='t';
 if(L.t>=L.e-0.02||L.t<L.s)L.t=L.s;draw();await seeked(L.v,L.t);if(L.play!==tok)return;busy();L.v.playbackRate=rate(L.n);L.v.play().catch(()=>{});
 const tick=()=>{if(L.play!==tok)return;const t=L.v.currentTime;if(t>=L.e||L.v.ended){L.t=L.e;soloStop(L);show();return;}L.t=r3(t);draw();requestAnimationFrame(tick);};requestAnimationFrame(tick);}
/* all visible layers at once (Metin, 02:29): they start in the same moment, each from its play head, and each stops at its own end mark */
async function allPlay(){if(LAY.some(L=>L.play)){for(const L of LAY)if(L.play){L.t=r3(Math.min(L.e,L.v.currentTime));soloStop(L);}show();return;}
 const on=LAY.filter(L=>L.on&&L.d);if(!on.length)return;stop();const tok=++STOK;for(const L of on){L.play=tok;L.mode='t';if(L.t>=L.e-0.02||L.t<L.s)L.t=L.s;}draw();
 await Promise.all(on.map(L=>seeked(L.v,L.t)));const go=on.filter(L=>L.play===tok);busy();
 for(const L of go)L.v.playbackRate=rate(L.n);for(const L of go)L.v.play().catch(()=>{});
 const tick=()=>{let any=false;for(const L of go){if(L.play!==tok)continue;const t=L.v.currentTime;if(t>=L.e||L.v.ended){L.t=L.e;soloStop(L);}else{L.t=r3(t);any=true;}}
  if(any){draw();requestAnimationFrame(tick);}else show();};requestAnimationFrame(tick);}
$('pall').onclick=allPlay;$('gall').onclick=()=>{stop();for(const L of LAY){if(!L.d)continue;soloStop(L);L.mode='t';L.t=L.s;}show();};
/* the hand over once in real time, the way stageShow does it for a loop */
async function play(){if(PLAYING){stop();return;}const a=lay($('hf').value),b=lay($('ht').value);if(!a||!b||a===b||!a.d||!b.d)return;LAY.forEach(soloStop);PLAYING=true;const tok=++TOK;
 document.body.classList.remove('diff');draw();
 for(const L of LAY){L.v.style.transition='none';L.v.style.mixBlendMode='normal';L.v.style.opacity=L===a?'1':'0';}a.v.style.zIndex='1';b.v.style.zIndex='2';
 document.body.classList.add('busy');await Promise.all([seeked(a.v,Math.max(a.s,a.e-2)),seeked(b.v,b.s)]);document.body.classList.remove('busy');if(tok!==TOK)return;
 a.v.playbackRate=rate(a.n);b.v.playbackRate=rate(b.n);a.v.play().catch(()=>{});let on=false;
 const tick=()=>{if(tok!==TOK)return;
  if(!on&&a.v.currentTime>=a.e-b.ld){on=true;b.v.play().catch(()=>{});b.v.style.transition='opacity '+HAND_FADE+'s';b.v.style.opacity='1';
   setTimeout(()=>{if(tok===TOK){a.v.style.transition='opacity '+HAND_FADE+'s';a.v.style.opacity='0';}},HAND_OFF);
   setTimeout(()=>{if(tok===TOK)stop();},2600);}
  if(a.v.currentTime>=a.e&&!a.v.paused)a.v.pause();requestAnimationFrame(tick);};requestAnimationFrame(tick);}
$('play').onclick=play;
const post=async(url,body)=>{try{return await (await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();}catch(e){return null;}};
/* store every changed begin mark, end mark and lead */
$('save').onclick=async()=>{stop();let ok=true;
 for(const L of LAY){if(!changed(L))continue;const p=pth(L.n),s=L.s<0.0005?0:r3(L.s),e=L.e>=L.d-0.02?0:r3(L.e),o=SCHNITT[p]||[0,0];
  if(s!==(o[0]||0)||e!==(o[1]||0)){const j=await post('/api/schnitt',{name:p,start:s,end:e});if(j&&j.ok){if(s||e)SCHNITT[p]=[s,e];else delete SCHNITT[p];L.s=savedS(L);L.e=savedE(L);}else ok=false;}
  if(Math.abs(L.ld-savedL(L))>0.0004){const l=r3(L.ld),j=await post('/api/vorlauf',{name:p,lead:l});if(j&&j.ok){if(l===HAND_PRE)delete LEAD[p];else LEAD[p]=l;}else ok=false;}}
 draw();$('sinfo').textContent=ok?'Gemerkt. Die App nimmt es beim nächsten Öffnen.':'Ging nicht bei allen. Zwischen Anfang und Ende muss mindestens eine halbe Sekunde bleiben.';};
$('back').onclick=()=>{stop();for(const L of LAY){if(!L.d)continue;soloStop(L);L.s=savedS(L);L.e=savedE(L);L.ld=savedL(L);L.t=Math.max(L.s,Math.min(L.e,L.t));}show();};
/* The time axis: one bar per layer over the full length of its clip (Metin, 02:15: each loop on its own). The bright
   part is what stays; its edges are dragged to make the clip shorter or longer, a tap or drag inside moves the play head. */
const AXP=8,AXT=20,AXR=26;
const axMax=()=>Math.max(1,...LAY.map(L=>L.d||0)),axW=()=>$('ax').clientWidth||1,axPps=()=>(axW()-2*AXP)/axMax(),axX=t=>AXP+t*axPps(),axY=i=>AXT+i*AXR;
function axDraw(){const c=$('ax'),w=axW(),h=c.clientHeight||100,dpr=window.devicePixelRatio||1;if(c.width!==Math.round(w*dpr)||c.height!==Math.round(h*dpr)){c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);}
 const g=c.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,w,h);g.font='11px system-ui';g.textBaseline='middle';g.textAlign='left';
 for(let t=0;t<=axMax();t+=1){g.fillStyle='#345';g.fillRect(axX(t),0,1,h);g.fillStyle='#89a';g.fillText(t+' s',axX(t)+3,8);}
 LAY.forEach((L,i)=>{const y=axY(i),loop=isLoop(L.n);g.globalAlpha=L.on?1:.45;
  g.fillStyle='rgba(120,130,140,.32)';g.fillRect(axX(0),y,Math.max(0,axX(L.d)-axX(0)),20);
  if(L.d){g.fillStyle=loop?'#1b8fb0':'#7a48c8';g.fillRect(axX(L.s),y,Math.max(0,axX(L.e)-axX(L.s)),20);
   g.fillStyle=loop?'#9fe8ff':'#d9c2ff';g.fillRect(axX(L.s),y-2,3,24);g.fillRect(axX(L.e)-3,y-2,3,24);
   g.fillStyle='#fff';g.fillRect(axX(L.t)-0.5,y-4,1.5,28);}
  g.fillStyle='#fff';g.fillText(title(L.n)+(L.d?'  '+L.s.toFixed(3)+' bis '+L.e.toFixed(3)+' s':''),axX(L.s)+8,y+10);g.globalAlpha=1;});}
function axAt(ev){const r=$('ax').getBoundingClientRect();return [ev.clientX-r.left,ev.clientY-r.top];}
$('ax').onpointerdown=ev=>{const [x,y]=axAt(ev),L=LAY[Math.floor((y-AXT+3)/AXR)];if(!L||!L.d)return;const ds=Math.abs(x-axX(L.s)),de=Math.abs(x-axX(L.e));
 const m=Math.min(ds,de)<=10?(ds<de?'s':'e'):'t';AXD={L,m};try{$('ax').setPointerCapture(ev.pointerId);}catch(e){}ev.preventDefault();
 if(m==='t'){L.mode='t';setVal(L,'t',(x-AXP)/axPps());}else L.mode=m;};
$('ax').onpointermove=ev=>{if(!AXD)return;setVal(AXD.L,AXD.m,(axAt(ev)[0]-AXP)/axPps());};
$('ax').onpointerup=$('ax').onpointercancel=()=>{AXD=null;};
window.addEventListener('resize',axDraw);
start();
</script></body></html>
"""
