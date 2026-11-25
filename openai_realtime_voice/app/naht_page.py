"""The page /naht: the end of one clip and the beginning of the next as a see through stencil (2.165.0).

Metin, 25 Nov 2026, 01:36: "Ich wünschte, ich könnte ein Ende und einen Anfang vor mir haben
wie eine transparente Schablone, die ich übereinander legen könnte, und die Zeit so speichern."
He saw a small shadow where one loop hands over to the next: the two pictures do not lie on
each other. Numbers from outside did not settle it, his eye does.

The page shows two clips of one outfit as still pictures on top of each other: below the clip
that ends (A), above it, half see through, the clip that begins (B). He moves the end mark of
A and the begin mark of B, by a picture, a hundredth or a thousandth of a second (his wish,
01:43), until the outlines lie on each other, and one
button stores both as cut marks (POST /api/schnitt, the same marks the tester and /ganzes
use; the clip files are never touched). "Unterschied" shows the difference of the two pictures
instead: what is black lies exactly on each other, what glows does not.

The two pictures are the ones the app really shows together. A loop hands over like this
(memory_web.stageShow with TIGHT, see HAND_PRE and HAND_FADE below): the new clip starts at its
begin mark HAND_PRE seconds of clip time before the end mark of the old one and fades in for
HAND_FADE seconds, the old clip runs on to its end mark and holds its last picture there. So
`tau` seconds after the new clip started, the old one shows `min(end, end - HAND_PRE + tau *
rate)` and the new one `begin + tau * rate`. The slider "Stelle in der Übergabe" is that tau;
it starts at HAND_PRE, the moment the old clip has reached its last picture and the new one is
about half there. "So spielt es die App" plays the hand over once in real time.

A third stencil (Metin, 01:45: "dann noch eine dritte Schablone drauf, also die Drück Clips"):
a third clip of the outfit, meant for the touch clips, lies on top with its own see through
slider, either with its beginning (a touch cuts into a loop) or with its end (it hands back to
a loop); its mark is moved and stored the same way. It is left out of "So spielt es die App".

A clip has ONE begin and ONE end mark, used at every hand over, not one per pair: the page
says so. A tempo curve inside a clip is not taken into account (the stored tempo is).

The script is a raw string: keep it free of backslashes and check it with node --check
(tests/test_naht.py does) before every commit. Whoever changes PRE, OFF or the fade of loops
in memory_web.stageShow must change HAND_PRE, HAND_OFF and HAND_FADE here too (a test compares).
"""

HAND_PRE = 0.25   # the next loop starts this long (clip time) before the end mark of the running one
HAND_OFF = 300    # ms after which the old clip begins to fade out
HAND_FADE = 0.8   # seconds the new clip fades in

PAGE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Naht: Ende und Anfang</title><style>
html,body{margin:0;height:100%;overflow:hidden;background:#000;color:#eee;font:13px system-ui}
h1{font-size:14px;margin:6px 8px}
h2{font-size:13px;margin:0 0 4px;color:#9fe8ff;font-weight:600}
a{color:#9fe8ff}
#st{position:fixed;top:0;right:0;height:100%;aspect-ratio:2/3;max-width:100vw;overflow:hidden;background:#000}
#st video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
#vb{opacity:.5}
#vc{opacity:0}
body.diff #vb{mix-blend-mode:difference}
#panel{position:fixed;top:0;left:0;bottom:0;width:min(58vw,360px);overflow-y:auto;background:rgba(0,0,0,.30);padding-bottom:10px;z-index:3}
body.hide #panel{display:none}
@media (min-aspect-ratio:1/1){#panel{width:calc(100vw - 100vh*2/3);max-width:none;background:#000}}
#top{position:fixed;top:6px;right:6px;z-index:4;display:flex;gap:6px;align-items:center;flex-direction:row-reverse}
#busy{font-size:12px;color:#fd8;background:rgba(0,0,0,.55);padding:4px 7px;border-radius:8px;visibility:hidden}
body.busy #busy{visibility:visible}
.card{margin:6px;padding:6px 8px;border:1px solid #334;border-radius:10px;background:rgba(0,0,0,.42)}
.bar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:4px 0}
select,button{padding:6px 8px;border-radius:8px;background:rgba(34,34,34,.9);color:#eee;border:1px solid #445;font:inherit}
select{max-width:100%}
button.on{border-color:#2a6;color:#9f9}
.t{font-size:12px;color:#9ab}
.z{color:#9ab;font-size:12px;min-width:44px}
.n{font-weight:600;color:#fff}
input[type=range]{flex:1 1 120px;min-width:120px}
</style></head><body>
<div id="st"><video id="va" playsinline muted preload="auto"></video><video id="vb" playsinline muted preload="auto"></video><video id="vc" playsinline muted preload="auto"></video></div>
<div id="top"><button id="tog">☰</button><span id="busy">Bild wird geholt ...</span></div>
<div id="panel"><h1>Naht: Ende und Anfang &nbsp; <a href="/ganzes" style="font-size:12px;font-weight:400">Outfit als Ganzes</a></h1>
<div class="card"><h2>1. Welche zwei Clips</h2>
<div class="bar"><span class="z">Kleid</span><select id="look"></select></div>
<div class="bar"><span class="z">Ende von</span><select id="sa"></select></div>
<div class="bar"><span class="z">Anfang von</span><select id="sb"></select></div>
<div class="t">Unten liegt der Clip, der endet. Darüber, durchsichtig, der Clip, der anfängt.</div></div>
<div class="card"><h2>2. Schablone</h2>
<div class="bar"><span class="z">Durchsicht</span><input type="range" id="op" min="0" max="100" step="1" value="50"><span id="oplab" style="min-width:34px">50 %</span></div>
<div class="bar"><button id="o0">nur das Ende</button><button id="o50">halb</button><button id="o100">nur der Anfang</button><button id="diff">Unterschied</button></div>
<div class="t">Unterschied: was schwarz ist, liegt genau aufeinander. Was leuchtet, liegt daneben.</div></div>
<div class="card"><h2>3. Ende schieben (Clip unten)</h2>
<div class="t" id="alab"></div>
<div class="bar"><input type="range" id="ea" min="0" max="10" step="0.001" value="10"></div>
<div class="bar"><button id="am">◀ Bild</button><button id="ap">Bild ▶</button><button id="am1">− 0,01</button><button id="ap1">+ 0,01</button><button id="am3">− 0,001</button><button id="ap3">+ 0,001</button></div>
<div class="t">Nach links wird der Clip kürzer, hinten fällt mehr weg. Nach rechts wird er wieder länger.</div></div>
<div class="card"><h2>4. Anfang schieben (Clip oben)</h2>
<div class="t" id="blab"></div>
<div class="bar"><input type="range" id="bb" min="0" max="10" step="0.001" value="0"></div>
<div class="bar"><button id="bm">◀ Bild</button><button id="bp">Bild ▶</button><button id="bm1">− 0,01</button><button id="bp1">+ 0,01</button><button id="bm3">− 0,001</button><button id="bp3">+ 0,001</button></div>
<div class="t">Nach rechts fällt vorne mehr weg. Nach links wird der Clip wieder länger.</div></div>
<div class="card"><h2>5. Dritte Schablone: Kopf, Brust, Bauch, Po</h2>
<div class="bar"><span class="z">Clip</span><select id="sc"></select></div>
<div id="cbox" style="display:none"><div class="bar"><button id="cbeg" class="on">sein Anfang</button><button id="cend">sein Ende</button></div>
<div class="bar"><span class="z">Durchsicht</span><input type="range" id="opc" min="0" max="100" step="1" value="50"><span id="opclab" style="min-width:34px">50 %</span></div>
<div class="t" id="clab"></div>
<div class="bar"><input type="range" id="cc" min="0" max="10" step="0.001" value="0"></div>
<div class="bar"><button id="cm">◀ Bild</button><button id="cp">Bild ▶</button><button id="cm1">− 0,01</button><button id="cp1">+ 0,01</button><button id="cm3">− 0,001</button><button id="cp3">+ 0,001</button></div></div></div>
<div class="card"><h2>6. Prüfen und merken</h2>
<div class="bar"><button id="play">So spielt es die App</button><button id="save">Diese Zeiten merken</button><button id="back">zurück auf gemerkt</button></div>
<div class="t" id="sinfo"></div>
<div class="bar"><span class="z">Stelle</span><input type="range" id="tau" min="0" max="0.8" step="0.01" value="0.25"><span id="taulab" style="min-width:44px">0.25 s</span></div>
<div class="t">Stelle in der Übergabe: so viele Sekunden läuft der neue Clip schon. Bei 0,25 steht der alte auf seinem letzten Bild und der neue ist halb zu sehen.</div>
<div class="t">Jeder Clip hat nur einen Anfang und ein Ende. Sie gelten bei jedem Wechsel, nicht nur für dieses Paar.</div></div></div>
<script>
const $=id=>document.getElementById(id);
const OUT=[['Kurzes Arbeitskleid','kurz',''],['Kurzes Freizeitkleid','kurz','freizeit'],['Langes Arbeitskleid','schwarz',''],['Langes Freizeitkleid','schwarz','freizeit'],['Nachtkleid','nacht','']];
const ZONES=[['Kopf',['gesicht']],['Brust',['brust']],['Bauch',['bauch']],['Po',['po','povorne']],['Mix',['mix']]];  /* the touch clips, as Metin names them (01:46: Kopf, Brust, Po, Bauch) */
const HAND_PRE=0.25,HAND_OFF=300,HAND_FADE=0.8,FRAME=1/24;  /* as the loops of the app hand over (memory_web.stageShow, TIGHT) */
let LOOK='',PRE='',CL=[],VER={},RATE={},KURVE={},SCHNITT={},A='',B='',C='',CEND=false,PLAYING=false,TOK=0;  /* C: the third stencil, CEND: with its end instead of its beginning */
const va=$('va'),vb=$('vb'),vc=$('vc');
const base=n=>n.replace(/[0-9]+$/,'');
const mine=n=>PRE?n.startsWith(PRE):!n.startsWith('freizeit');
const pth=n=>LOOK+'/'+n;
const rate=n=>RATE[pth(n)]||1;
const dur=v=>v.duration||10;
const r3=x=>Math.round(x*1000)/1000;  /* marks in thousandths of a second (Metin, 01:43) */
const eA=()=>Number($('ea').value),bB=()=>Number($('bb').value),cC=()=>Number($('cc').value),tau=()=>Number($('tau').value);
/* the two pictures the app shows together `tau` seconds after the new clip started */
function want(){return [Math.max(0,Math.min(eA(),eA()-HAND_PRE+tau()*rate(A))),Math.min(dur(vb),bB()+tau()*rate(B)),
  !C?0:CEND?Math.max(0,Math.min(cC(),cC()-HAND_PRE+tau()*rate(C))):Math.min(dur(vc),cC()+tau()*rate(C))];}
function busy(){document.body.classList.toggle('busy',va.seeking||vb.seeking||va.readyState<2||vb.readyState<2||(!!C&&(vc.seeking||vc.readyState<2)));}
function seek(v,t){if(Math.abs(v.currentTime-t)>0.0004){try{v.currentTime=t;}catch(e){}}}
let PEND=0;
function show(){if(PLAYING)return;label();clearTimeout(PEND);PEND=setTimeout(()=>{if(PLAYING)return;const w=want();seek(va,w[0]);seek(vb,w[1]);if(C)seek(vc,w[2]);busy();},60);}
function label(){const sa=(SCHNITT[pth(A)]||[0,0]),sb=(SCHNITT[pth(B)]||[0,0]);
 $('alab').innerHTML='Ende: <span class="n">'+eA().toFixed(3)+' s</span> von '+dur(va).toFixed(2)+' s &nbsp; gemerkt: '+(sa[1]?sa[1].toFixed(3)+' s':'bis zum Schluss')+(rate(A)!==1?' &nbsp; Tempo '+rate(A):'')+(KURVE[pth(A)]?' &nbsp; (Tempo Kurve nicht eingerechnet)':'');
 $('blab').innerHTML='Anfang: <span class="n">'+bB().toFixed(3)+' s</span> &nbsp; gemerkt: '+(sb[0]?sb[0].toFixed(3)+' s':'von vorne')+(rate(B)!==1?' &nbsp; Tempo '+rate(B):'')+(KURVE[pth(B)]?' &nbsp; (Tempo Kurve nicht eingerechnet)':'');
 $('taulab').textContent=tau().toFixed(2)+' s';$('oplab').textContent=$('op').value+' %';$('opclab').textContent=$('opc').value+' %';
 if(C){const sc=(SCHNITT[pth(C)]||[0,0]);$('clab').innerHTML=(CEND?'Ende: ':'Anfang: ')+'<span class="n">'+cC().toFixed(3)+' s</span>'+(CEND?' von '+dur(vc).toFixed(2)+' s':'')+' &nbsp; gemerkt: '+(CEND?(sc[1]?sc[1].toFixed(3)+' s':'bis zum Schluss'):(sc[0]?sc[0].toFixed(3)+' s':'von vorne'))+(rate(C)!==1?' &nbsp; Tempo '+rate(C):'');}
 const ch=Math.abs(eA()-savedEnd())>0.0004||Math.abs(bB()-savedStart())>0.0004||(!!C&&Math.abs(cC()-savedC())>0.0004);$('save').classList.toggle('on',ch);
 $('sinfo').textContent=ch?'Noch nicht gemerkt.':'So ist es gemerkt.';}
const savedEnd=()=>{const c=SCHNITT[pth(A)];return c&&c[1]>0&&c[1]<dur(va)?c[1]:dur(va);};
const savedStart=()=>{const c=SCHNITT[pth(B)];return c&&c[0]>0?c[0]:0;};
const savedC=()=>{const c=SCHNITT[pth(C)];return CEND?(c&&c[1]>0&&c[1]<dur(vc)?c[1]:dur(vc)):(c&&c[0]>0?c[0]:0);};
function opac(){if(PLAYING)return;vb.style.transition='none';va.style.transition='none';va.style.opacity='1';
 vb.style.opacity=document.body.classList.contains('diff')?'1':String(Number($('op').value)/100);
 vc.style.transition='none';vc.style.opacity=C?String(Number($('opc').value)/100):'0';label();}
function load(v,n,then){v.onloadedmetadata=()=>{v.onloadedmetadata=null;then();};v.src='/clips/'+pth(n)+'.mp4?v='+(VER[LOOK]||0);v.load();}
function setA(n){A=n;stop();load(va,n,()=>{$('ea').max=String(dur(va));$('ea').value=String(savedEnd());show();});}
function setB(n){B=n;stop();load(vb,n,()=>{$('bb').max=String(Math.max(0.5,dur(vb)-0.5));$('bb').value=String(savedStart());show();});}
function setC(n){C=n;stop();$('cbox').style.display=n?'':'none';$('cbeg').classList.toggle('on',!CEND);$('cend').classList.toggle('on',CEND);
 if(!n){vc.removeAttribute('src');vc.load();opac();busy();return;}
 load(vc,n,()=>{$('cc').max=String(CEND?dur(vc):Math.max(0.5,dur(vc)-0.5));$('cc').value=String(savedC());opac();show();});}
function fill(){const names=CL.filter(mine).slice().sort((x,y)=>{const lx=base(x)===PRE+'gluecklich'?0:1,ly=base(y)===PRE+'gluecklich'?0:1;return lx-ly||x.localeCompare(y,'de',{numeric:true});});
 for(const id of ['sa','sb']){const s=$(id);s.innerHTML='';names.forEach(n=>{const o=document.createElement('option');o.value=n;const l=base(n)===PRE+'gluecklich';
   o.textContent=(l?'Schleife '+(names.filter(x=>base(x)===PRE+'gluecklich').indexOf(n)+1)+' ('+n+')':n);s.appendChild(o);});}
 const c=$('sc');c.innerHTML='<option value="">keine</option>';const add=(n,t)=>{const o=document.createElement('option');o.value=n;o.textContent=t;c.appendChild(o);},done={};
 for(const [zone,kinds] of ZONES){const zs=names.filter(n=>kinds.includes(base(n).slice(PRE.length)));zs.forEach((n,i)=>{done[n]=1;add(n,zone+(zs.length>1?' '+(i+1):'')+' ('+n+')');});}
 names.forEach(n=>{if(!done[n])add(n,n);});
 return names;}
function pick(i,a,b){const o=OUT[i];LOOK=o[1];PRE=o[2];CL=(window.J.outfits[LOOK]||{}).clips||[];const names=fill();if(!names.length)return;
 try{localStorage.setItem('lnaht',String(i));}catch(e){}
 const na=names.includes(a)?a:names[0],nb=names.includes(b)?b:(names[1]||names[0]);$('sa').value=na;$('sb').value=nb;setA(na);setB(nb);$('sc').value='';setC('');}
async function start(){const j=await (await fetch('/clips.json?t='+Date.now())).json();window.J=j;const o=j.outfits||{};
 for(const look in o){VER[look]=o[look].v||0;for(const c in (o[look].r||{}))RATE[look+'/'+c]=o[look].r[c];
  for(const c in (o[look].k||{}))KURVE[look+'/'+c]=o[look].k[c];for(const c in (o[look].s||{}))SCHNITT[look+'/'+c]=o[look].s[c].slice();}
 const s=$('look');OUT.forEach((x,i)=>{if(!o[x[1]])return;const op=document.createElement('option');op.value=String(i);op.textContent=x[0];s.appendChild(op);});
 const q=new URLSearchParams(location.search),qa=q.get('a')||'',qb=q.get('b')||'';let i=-1,a='',b='';
 if(qa.includes('/')){const lk=qa.split('/')[0];a=qa.split('/')[1];b=qb.includes('/')?qb.split('/')[1]:'';i=OUT.findIndex(x=>x[1]===lk&&(x[2]==='freizeit')===a.startsWith('freizeit'));}
 if(i<0){try{i=Number(localStorage.getItem('lnaht')||1);}catch(e){i=1;}}
 if(!OUT[i]||!o[OUT[i][1]])i=Number(s.options[0].value);s.value=String(i);s.onchange=()=>pick(Number(s.value),'','');pick(i,a,b);}
$('sa').onchange=()=>setA($('sa').value);$('sb').onchange=()=>setB($('sb').value);$('sc').onchange=()=>setC($('sc').value);
$('cbeg').onclick=()=>{CEND=false;setC(C);};$('cend').onclick=()=>{CEND=true;setC(C);};$('opc').oninput=opac;
$('tog').onclick=()=>document.body.classList.toggle('hide');
$('op').oninput=()=>{document.body.classList.remove('diff');$('diff').classList.remove('on');opac();};
const setOp=x=>{$('op').value=String(x);$('op').oninput();};
$('o0').onclick=()=>setOp(0);$('o50').onclick=()=>setOp(50);$('o100').onclick=()=>setOp(100);
$('diff').onclick=()=>{$('diff').classList.toggle('on',document.body.classList.toggle('diff'));opac();};
const step=(id,d)=>()=>{const s=$(id);s.value=String(Math.max(Number(s.min),Math.min(Number(s.max),r3(Number(s.value)+d))));stop();show();};
$('am').onclick=step('ea',-FRAME);$('ap').onclick=step('ea',FRAME);$('am1').onclick=step('ea',-0.01);$('ap1').onclick=step('ea',0.01);$('am3').onclick=step('ea',-0.001);$('ap3').onclick=step('ea',0.001);
$('bm').onclick=step('bb',-FRAME);$('bp').onclick=step('bb',FRAME);$('bm1').onclick=step('bb',-0.01);$('bp1').onclick=step('bb',0.01);$('bm3').onclick=step('bb',-0.001);$('bp3').onclick=step('bb',0.001);
$('cm').onclick=step('cc',-FRAME);$('cp').onclick=step('cc',FRAME);$('cm1').onclick=step('cc',-0.01);$('cp1').onclick=step('cc',0.01);$('cm3').onclick=step('cc',-0.001);$('cp3').onclick=step('cc',0.001);
for(const id of ['ea','bb','cc','tau'])$(id).oninput=()=>{stop();show();};
for(const v of [va,vb,vc]){v.onseeked=busy;v.onseeking=busy;v.onloadeddata=busy;}
function stop(){if(!PLAYING)return;PLAYING=false;TOK++;va.pause();vb.pause();va.playbackRate=1;vb.playbackRate=1;$('play').textContent='So spielt es die App';opac();}
const seeked=(v,t)=>new Promise(res=>{if(Math.abs(v.currentTime-t)<0.0004&&!v.seeking)return res();const f=()=>{v.removeEventListener('seeked',f);res();};v.addEventListener('seeked',f);try{v.currentTime=t;}catch(e){res();}});
/* the hand over once in real time, the way stageShow does it for a loop */
async function play(){if(PLAYING){stop();show();return;}PLAYING=true;const tok=++TOK,e=eA(),b=bB();$('play').textContent='anhalten';
 document.body.classList.remove('diff');$('diff').classList.remove('on');
 vb.style.transition='none';va.style.transition='none';vb.style.opacity='0';va.style.opacity='1';vc.style.opacity='0';
 document.body.classList.add('busy');await Promise.all([seeked(va,Math.max(0,e-2)),seeked(vb,b)]);document.body.classList.remove('busy');if(tok!==TOK)return;
 va.playbackRate=rate(A);vb.playbackRate=rate(B);va.play().catch(()=>{});let on=false;
 const tick=()=>{if(tok!==TOK)return;
  if(!on&&va.currentTime>=e-HAND_PRE){on=true;vb.play().catch(()=>{});vb.style.transition='opacity '+HAND_FADE+'s';vb.style.opacity='1';
   setTimeout(()=>{if(tok===TOK){va.style.transition='opacity '+HAND_FADE+'s';va.style.opacity='0';}},HAND_OFF);
   setTimeout(()=>{if(tok===TOK){stop();show();}},2600);}
  if(va.currentTime>=e&&!va.paused)va.pause();requestAnimationFrame(tick);};requestAnimationFrame(tick);}
$('play').onclick=play;
const post=async(url,body)=>{try{return await (await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();}catch(e){return null;}};
/* store the end of A, the begin of B and the mark of the third stencil; every other mark of these clips stays as it is */
$('save').onclick=async()=>{stop();const M={},get=p=>M[p]||(M[p]=(SCHNITT[p]||[0,0]).slice(0,2));
 get(pth(A))[1]=eA()>=dur(va)-0.02?0:r3(eA());get(pth(B))[0]=bB()<0.0005?0:r3(bB());
 if(C){if(CEND){if(C!==A)get(pth(C))[1]=cC()>=dur(vc)-0.02?0:r3(cC());}else if(C!==B)get(pth(C))[0]=cC()<0.0005?0:r3(cC());}
 let ok=true;
 for(const n in M){const s=M[n][0]||0,x=M[n][1]||0,o=SCHNITT[n]||[0,0];if(s===(o[0]||0)&&x===(o[1]||0))continue;
  const j=await post('/api/schnitt',{name:n,start:s,end:x});if(j&&j.ok){if(s||x)SCHNITT[n]=[s,x];else delete SCHNITT[n];}else ok=false;}
 label();$('sinfo').textContent=ok?'Gemerkt. Die App nimmt es beim nächsten Öffnen.':'Ging nicht: zwischen Anfang und Ende muss mindestens eine halbe Sekunde bleiben.';};
$('back').onclick=()=>{stop();$('ea').value=String(savedEnd());$('bb').value=String(savedStart());if(C)$('cc').value=String(savedC());show();};
start();
</script></body></html>
"""
