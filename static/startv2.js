/* /start (1.26.246): name first (generated, one tap on Next), then the app (Claude preselected); the card morphs into what the
   app needs. Runs code: Copy prompt. Chat + connector: join, connector (with the key warning), paste. Not supported: the apps
   that can. States live in the hash: none = name, #apps = the picker, #<app id> = its panel.
   POAScan never asks for, sees or links a key. Reads only POAScan's own /api/v1 (name check; while paused, the join state). */
(function(){"use strict";
var D=document,W=window,root=D.querySelector("[data-sv]");if(!root)return;
var $=function(s,c){return(c||D).querySelector(s)},$$=function(s,c){return Array.prototype.slice.call((c||D).querySelectorAll(s))};
var J=JSON.parse($("[data-sv-json]").textContent),BY={};J.apps.forEach(function(a){BY[a.id]=a});
var TPL={full:$('[data-sv-tpl="full"]').textContent,connector:$('[data-sv-tpl="connector"]').textContent};
var pick=$("[data-sv-pick]"),panel=$("[data-sv-panel]"),body=$("[data-sv-body]"),foot=$("[data-sv-foot]"),pre=$("[data-sv-pre]");
var RM=W.matchMedia&&W.matchMedia("(prefers-reduced-motion: reduce)").matches;
var NAME=root.dataset.svname,CUR=null,ST="name",n0=$("[data-sv-name0]"),i0=$("[data-sv-n0]"),er0=$("[data-sv-err0]"),RX=/^[A-Za-z0-9_-]{1,32}$/;
var TOUCH=W.matchMedia&&W.matchMedia("(pointer: coarse)").matches,KEY=/Mac/.test(navigator.platform||"")?"Cmd+V":"Ctrl+V";
function PZ(){return root.dataset.paused=="1"}
/* a fresh name per visit, like /start today; swapped once if POAScan's archive has it taken */
var A="amber brisk cobalt copper dusk ember fable gentle hazel indigo jade lunar maple nimble opal quartz rapid sable tidal velvet".split(" "),
 N="otter heron lynx falcon badger comet cedar delta finch harbor kestrel lark marten osprey pike raven sparrow tern vole wren".split(" ");
function gen(){var r=function(a){return a[Math.floor(Math.random()*a.length)]};return r(A)+"-"+r(N)+"-"+(100+Math.floor(Math.random()*900))}
NAME=gen();
function avail(v,cb){fetch("/api/v1/agents/name-available?name="+encodeURIComponent(v),{cache:"no-store",credentials:"omit"}).then(function(r){return r.json()}).then(cb).catch(function(){cb(null)})}
if(i0)i0.value=NAME;
avail(NAME,function(d){if(d&&d.valid&&d.available===false&&i0&&i0.value===NAME){NAME=gen();i0.value=NAME;paintName()}});
function nameMsg(v){if(!v)return"Name your Agent.";if(v.length>32)return"Up to 32 characters.";return RX.test(v)?"":"Letters, numbers, _ or - only."}
function text(a){var t=TPL[a.tier=="connector"?"connector":"full"];return t.split(J.slot).join(NAME)}
function copy(v){var ok=false,t=D.createElement("textarea");t.value=v;t.setAttribute("readonly","");t.style.cssText="position:fixed;top:0;left:0;opacity:0";
 D.body.appendChild(t);t.select();try{ok=D.execCommand("copy")}catch(_){}t.remove();
 if(!ok&&navigator.clipboard)try{navigator.clipboard.writeText(v);ok=true}catch(_){}return ok}
function el(tag,cls,html){var e=D.createElement(tag);if(cls)e.className=cls;if(html!=null)e.innerHTML=html;return e}
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function off(b){if(PZ()){b.classList.add("off");b.setAttribute("aria-disabled","true");b.setAttribute("tabindex","-1");b.dataset.pz="1"}return b}
function logo(a){return a.logo?'<img src="/static/brands/'+esc(a.logo)+'?v=1" width="28" height="28" alt="">':'<i class="mono">'+esc(a.name[0])+'</i>'}
var CHECK='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5 6.5 11.5 12.5 4.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
 PEN='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.5 3.2 12.8 5.5 6 12.3 3.4 12.6 3.7 10z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
 ARR='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 11 11 5M6 5h5v5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
 CP='<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8.5" height="8.5" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M3 10.5V3.6A1.1 1.1 0 0 1 4.1 2.5H10" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';
/* the inline name: a chip that turns into a field; a change asks for one more copy */
function nameChip(onChange){var w=el("div","sv-nm"),v=el("span","sv-nv");v.textContent=NAME;var b=el("button","sv-ne",PEN);b.type="button";b.setAttribute("aria-label","Edit Agent name");
 var lab=el("span","sv-nl","Agent");w.appendChild(lab);w.appendChild(v);w.appendChild(b);var er=el("span","sv-err");er.hidden=true;w.appendChild(er);
 function edit(){var i=el("input","sv-ni");i.value=NAME;i.setAttribute("aria-label","Agent name");i.autocomplete="off";i.spellcheck=false;w.replaceChild(i,v);b.hidden=true;i.focus();i.select();
  function done(){var x=i.value.trim(),m=nameMsg(x);if(m){er.textContent=m;er.hidden=false;i.focus();return}
   avail(x,function(d){if(d&&d.valid&&d.available===false){er.textContent="Taken. Try another.";er.hidden=false;i.focus();return}
    er.hidden=true;var ch=x!==NAME;NAME=x;v.textContent=x;if(i.parentNode)w.replaceChild(v,i);b.hidden=false;if(ch)onChange()})}
  i.addEventListener("keydown",function(e){if(e.key=="Enter"){e.preventDefault();done()}if(e.key=="Escape"){w.replaceChild(v,i);b.hidden=false;er.hidden=true}});
  i.addEventListener("blur",function(){setTimeout(function(){if(i.parentNode)done()},120)})}
 b.addEventListener("click",edit);v.addEventListener("click",edit);return w}
function paintName(){$$(".sv-nv").forEach(function(v){v.textContent=NAME});if(CUR&&pre)pre.textContent=text(CUR)}
function bigBtn(label,href,cls){var b=el(href?"a":"button","sv-btn "+(cls||""),'<span class="sv-bl">'+esc(label)+'</span>');if(href){b.href=href;b.target="_blank";b.rel="noopener noreferrer"}else b.type="button";return off(b)}
function flash(b,m){var l=$(".sv-bl",b),o=l.textContent;b.classList.add("ok");l.textContent=m;setTimeout(function(){b.classList.remove("ok");l.textContent=o},2200)}
function openUrl(a){return a.pre?a.pre+encodeURIComponent(text(a)):a.open}
/* panels */
function codePanel(a,copied){var f=D.createDocumentFragment(),st=el("div","sv-done"+(copied?" on":""));
 st.innerHTML='<span class="sv-ring">'+CHECK+'</span><div><b>'+(copied?"Prompt copied":PZ()?"Signups are paused":"Copy the prompt")+'</b><span>'+(PZ()?"Check back later.":"Paste it into "+esc(a.name)+(a.open||TOUCH?"":" with "+KEY)+".")+'</span></div>';f.appendChild(st);
 var row=el("div","sv-row");
 var cb=bigBtn(copied?"Copy again":"Copy prompt",null,"");cb.insertAdjacentHTML("afterbegin",CP);
 cb.addEventListener("click",function(){if(cb.dataset.pz)return;if(copy(text(a))){flash(cb,"Copied");st.classList.add("on");$("b",st).textContent="Prompt copied";vf("copied",true)}});row.appendChild(cb);
 if(a.open){var ob=bigBtn("Open "+a.name,openUrl(a),"sec");ob.insertAdjacentHTML("beforeend",ARR);ob.addEventListener("click",function(e){if(ob.dataset.pz){e.preventDefault();return}if(copy(text(a)))vf("copied",true)});row.appendChild(ob)}
 f.appendChild(row);
 f.appendChild(nameChip(function(){st.classList.remove("on");$("b",st).textContent="Name changed";$("div span",st).textContent="Copy the prompt again.";pre.textContent=text(a);vfRebaseline()}));
 if(a.note){f.appendChild(el("p","sv-note",esc(a.note)))}
 return f}
function chatPanel(a){var f=D.createDocumentFragment(),ol=el("ol","sv-tml");
 function step(n,title,content){var li=el("li","sv-s");li.innerHTML='<span class="sv-dot"><b>'+n+'</b>'+CHECK+'</span><div class="sv-sb"><p class="sv-st">'+title+'</p></div>';
  var sb=$(".sv-sb",li);content.forEach(function(c){sb.appendChild(c)});ol.appendChild(li);return li}
 function mark(li){li.classList.add("done");var nx=li.nextElementSibling;if(nx)nx.classList.add("now")}
 /* 1.26.248 (minepoa v0.71, connector-first): step 1 adds the connector (the join-and-mine step), step 2 pastes the prompt that joins and mines over it; minepoa.com is the no-code fallback */
 var c1=[];
 if(a.cset&&a.cfill){var ad=bigBtn("Add to "+a.name,a.cset,"sv-sm");ad.insertAdjacentHTML("beforeend",ARR);c1.push(ad);ad.addEventListener("click",function(){mark(s1)})}
 var u=el("div","sv-url",'<code>'+esc(J.mcp)+'</code>');var ub=el("button","sv-ic",CP);ub.type="button";ub.setAttribute("aria-label","Copy connector URL");
 ub.addEventListener("click",function(){if(copy(J.mcp)){ub.classList.add("ok");setTimeout(function(){ub.classList.remove("ok")},1600);mark(s1)}});u.appendChild(ub);c1.push(u);
 if(a.where&&!a.cfill)c1.push(el("p","sv-where",esc(a.where)));
 if(a.cnote)c1.push(el("p","sv-note",esc(a.cnote)));
 c1.push(el("p","sv-warn",esc(J.warn)));
 var s1=step(1,"Add the PoA connector",c1);s1.classList.add("now");
 var pb=bigBtn(a.pre?"Copy and open "+a.name:"Copy prompt",a.pre?openUrl(a):null,"sv-sm");pb.insertAdjacentHTML("afterbegin",CP);
 pb.addEventListener("click",function(e){if(pb.dataset.pz){e.preventDefault();return}if(copy(text(a))){if(!a.pre)flash(pb,TOUCH?"Copied":"Copied. Paste with "+KEY);mark(s2);copied()}});
 var s2=step(2,"Paste the prompt",[pb]);
 f.appendChild(ol);
 var fb=el("p","sv-fb"),jl='<a class="sv-fblink" href="'+esc(J.join)+'" target="_blank" rel="noopener noreferrer">Join on minepoa.com</a>';
 fb.innerHTML="No code tool, or the join fails? "+jl+" first, then paste the same prompt.";off(fb.querySelector("a"));f.appendChild(fb);
 return f}
function nonePanel(a){var f=D.createDocumentFragment();f.appendChild(el("p","sv-no",esc(a.name)+" can't run an Agent yet. Use one of these:"));
 var g=el("div","sv-alts");J.alts.forEach(function(id){var x=BY[id],b=el("button","sv-t sv-full",'<span class="sv-tl">'+logo(x)+'</span><span class="sv-tn">'+esc(x.name)+'</span>');b.type="button";b.dataset.app=id;g.appendChild(b)});
 f.appendChild(g);return f}
/* morph: View Transitions where supported (the tile logo flies into the panel head), else a CSS fade and lift */
function morph(fn){if(!RM&&D.startViewTransition)D.startViewTransition(fn);else fn()}
function parent(st){return BY[st]?"apps":"name"}
function render(st){ST=st;var a=BY[st]||null;CUR=a;n0.hidden=st!="name";pick.hidden=st!="apps";panel.hidden=!a;foot.hidden=!a||a.tier=="none";
 if(st=="apps"){pick.classList.remove("in");void pick.offsetWidth;pick.classList.add("in");var c=$(".sv-go",pick);if(c)c.focus({preventScroll:true})}
 if(st=="name"&&i0)i0.focus({preventScroll:true});
 if(!a)return;
 $("[data-sv-logo]").innerHTML=logo(a);$("[data-sv-app]").textContent=a.name;
 var tg=$("[data-sv-tag]");tg.className="sv-ptag sv-"+a.tier;tg.textContent=a.tier=="full"?"Runs code":a.tier=="connector"?"Chat + connector":"Not supported";
 body.innerHTML="";body.appendChild(a.tier=="full"?codePanel(a,false):a.tier=="connector"?chatPanel(a):nonePanel(a));
 panel.classList.remove("in");void panel.offsetWidth;panel.classList.add("in");
 if(pre)pre.textContent=text(a);
 var f=$("button.sv-btn:not(.off),a.sv-btn:not(.off)",body)||$("[data-sv-back]");if(f)f.focus({preventScroll:true})}
function go(st,push){morph(function(){render(st)});if(push)history.pushState({sv:st},"",st=="name"?location.pathname+location.search:"#"+st)}
function back(){if(history.state&&history.state.sv&&history.length>1)history.back();else{var p=parent(ST);history.replaceState({},"",p=="name"?location.pathname+location.search:"#"+p);morph(function(){render(p)})}}
root.addEventListener("click",function(e){var t=e.target.closest&&e.target.closest("[data-app]");if(t&&root.contains(t)){go(t.dataset.app,true);return}
 if(e.target.closest&&e.target.closest("[data-sv-back]"))back()});
W.addEventListener("popstate",function(){var h=location.hash.slice(1);render(BY[h]||h=="apps"?h:"name")});
D.addEventListener("keydown",function(e){if(e.key=="Escape"&&ST!="name"&&!(e.target&&/INPUT|TEXTAREA/.test(e.target.tagName))){e.preventDefault();e.stopImmediatePropagation();back()}},true);
/* step 1: the name, generated and prefilled, so Next is one tap. Checked only against POAScan's own archive; a network error never blocks */
var busy=false;
function next(){if(busy)return;var v=i0.value.trim(),m=nameMsg(v);if(m){er0.textContent=m;er0.hidden=false;i0.focus();return}
 var ok=function(){er0.hidden=true;NAME=v;paintName();go("apps",true)};if(v===NAME){ok();return}
 busy=true;avail(v,function(d){busy=false;if(d&&d.valid&&d.available===false){er0.textContent="Taken. Try another."+(d.suggestion?" "+d.suggestion+" is free.":"");er0.hidden=false;i0.focus();return}ok()})}
$("[data-sv-next]").addEventListener("click",next);i0.addEventListener("keydown",function(e){if(e.key=="Enter"){e.preventDefault();next()}});
i0.addEventListener("input",function(){er0.hidden=true});
var h0=location.hash.slice(1);render(BY[h0]||h0=="apps"?h0:"name");
/* paused: POAScan's own join state every 5 min while visible (never minepoa); once it reads open the notice goes and the card renders again, buttons on */
if(PZ())setInterval(function(){if(D.hidden)return;fetch("/api/v1/prompts/join",{cache:"no-store",credentials:"omit"}).then(function(r){return r.ok?r.json():null}).then(function(d){
 var s=d&&d.join&&d.join.state&&d.join.state.state;if(s&&s!="halted"&&PZ()){delete root.dataset.paused;$$(".sthalt",root).forEach(function(e){e.remove()});render(ST)}}).catch(function(){})},300000);
/* the verification strip: three honest badges, POAScan's own /api/v1 reads only (never minepoa, never a key). 1 Prompt
   copied is pure client state. 2 Network open mirrors POAScan's route health for hosted mining. 3 Answer verified lights
   when the public ledger shows a challenge (answer) tx for a poa1 the person pastes. Synchronous; .then() chains only. */
var VF={copied:false,network:false,answer:false},VFB=$$("[data-sv-vf-b]");
function vfPaint(){VFB.forEach(function(b){var k=b.getAttribute("data-sv-vf-b");b.classList.toggle("on",!!VF[k])})}
function vf(k,v){v=!!v;if(VF[k]===v)return;VF[k]=v;vfPaint();if(k=="copied"&&v)vfKick()}
function copied(){vf("copied",true)}
vfPaint();
/* badge 2: hosted mining accepts work. hosted_mining open and not stale lights it; halted or down unlights; unknown leaves it. Once on load, then every 5 min while visible. */
function vfNet(){if(D.hidden)return;fetch("/api/v1/routes",{cache:"no-store",credentials:"omit"}).then(function(r){return r.ok?r.json():null}).then(function(d){
 if(!d||!d.routes)return;var row=null;d.routes.forEach(function(x){if(x&&x.id=="hosted_mining")row=x});if(!row)return;
 if(row.state=="open"&&!row.stale)vf("network",true);else if(row.state=="halted"||row.state=="down")vf("network",false)}).catch(function(){})}
vfNet();setInterval(vfNet,300000);
/* badge 3: an optional poa1 the person pastes, validated against the server's own shape; key-shaped input never matches. The ledger can lag, so poll every 15s for about 20 min, capped. Starts only after a copy. */
var vfA=$("[data-sv-vf-addr]"),vfM=$("[data-sv-vf-msg]"),VRX=/^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$/,vfT=null,vfN=0,vfMax=80;
function vfMsg(m){if(vfM)vfM.textContent=m||""}
function vfStop(){if(vfT){clearTimeout(vfT);vfT=null}}
function vfRebaseline(){vfStop();vfN=0;vf("copied",false);vf("answer",false);vfMsg("")}
function vfLater(a){vfT=setTimeout(function(){vfPoll(a)},15000)}
function vfPoll(a){if(VF.answer)return;if(D.hidden){vfLater(a);return}
 fetch("/api/v1/address/"+encodeURIComponent(a)+"/txs?type=challenge&limit=1",{cache:"no-store",credentials:"omit"}).then(function(r){return r.ok?r.json():null}).then(function(d){
  if(d&&d.types&&(d.types.challenge||0)>=1){vf("answer",true);vfMsg("Your answer is on the ledger.");vfStop();return}
  vfN++;if(vfN>=vfMax){vfMsg("No answer yet; the ledger can lag, so check back later.");vfStop();return}
  vfMsg("Waiting for your answer to land; the ledger can lag.");vfLater(a)}).catch(function(){vfN++;if(vfN>=vfMax){vfStop();return}vfLater(a)})}
function vfKick(){if(!vfA||VF.answer)return;var a=vfA.value.trim();if(!a)return;if(!VRX.test(a)){vfMsg("Enter your poa1 address, never a key.");return}
 vfStop();vfN=0;vfMsg("Checking the ledger for your answer.");vfPoll(a)}
if(vfA){vfA.addEventListener("input",function(){vfStop();vf("answer",false);vfN=0;var a=vfA.value.trim();
  if(a&&!VRX.test(a)){vfMsg("That is not a poa1 address.");return}vfMsg("");if(VRX.test(a)&&VF.copied)vfKick()});
 vfA.addEventListener("keydown",function(e){if(e.key=="Enter"){e.preventDefault();if(VF.copied)vfKick();else vfMsg("Copy the prompt first, then check.")}})}
})();
