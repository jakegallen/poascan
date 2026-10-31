/* /start v2 preview (POASCAN_STARTV2=1). Pick first; the card morphs into what the app needs. Runs code: the tap copies the
   prompt. Chat + connector: join, connector (with the key warning), paste. Not supported: the apps that can.
   POAScan never asks for, sees or links a key. Reads only POAScan's own /api/v1 (name check; while paused, the join state). */
(function(){"use strict";
var D=document,W=window,root=D.querySelector("[data-sv]");if(!root)return;
var $=function(s,c){return(c||D).querySelector(s)},$$=function(s,c){return Array.prototype.slice.call((c||D).querySelectorAll(s))};
var J=JSON.parse($("[data-sv-json]").textContent),BY={};J.apps.forEach(function(a){BY[a.id]=a});
var TPL={full:$('[data-sv-tpl="full"]').textContent,connector:$('[data-sv-tpl="connector"]').textContent};
var pick=$("[data-sv-pick]"),panel=$("[data-sv-panel]"),body=$("[data-sv-body]"),foot=$("[data-sv-foot]"),pre=$("[data-sv-pre]");
var RM=W.matchMedia&&W.matchMedia("(prefers-reduced-motion: reduce)").matches,FLOW=/[?&]flow=name\b/.test(location.search);
var NAME=root.dataset.svname,CUR=null,RX=/^[A-Za-z0-9_-]{1,32}$/;
var TOUCH=W.matchMedia&&W.matchMedia("(pointer: coarse)").matches,KEY=/Mac/.test(navigator.platform||"")?"Cmd+V":"Ctrl+V";
function PZ(){return root.dataset.paused=="1"}
/* a fresh name per visit, like /start today; swapped once if POAScan's archive has it taken */
var A="amber brisk cobalt copper dusk ember fable gentle hazel indigo jade lunar maple nimble opal quartz rapid sable tidal velvet".split(" "),
 N="otter heron lynx falcon badger comet cedar delta finch harbor kestrel lark marten osprey pike raven sparrow tern vole wren".split(" ");
function gen(){var r=function(a){return a[Math.floor(Math.random()*a.length)]};return r(A)+"-"+r(N)+"-"+(100+Math.floor(Math.random()*900))}
NAME=gen();
function avail(v,cb){fetch("/api/v1/agents/name-available?name="+encodeURIComponent(v),{cache:"no-store",credentials:"omit"}).then(function(r){return r.json()}).then(cb).catch(function(){cb(null)})}
avail(NAME,function(d){if(d&&d.valid&&d.available===false){NAME=gen();paintName()}});
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
 var cb=bigBtn(copied?"Copy again":"Copy prompt",null,a.open?"sec":"");cb.insertAdjacentHTML("afterbegin",CP);
 cb.addEventListener("click",function(){if(cb.dataset.pz)return;if(copy(text(a))){flash(cb,"Copied");st.classList.add("on");$("b",st).textContent="Prompt copied"}});row.appendChild(cb);
 if(a.open){var ob=bigBtn("Open "+a.name,openUrl(a));ob.insertAdjacentHTML("beforeend",ARR);ob.addEventListener("click",function(e){if(ob.dataset.pz){e.preventDefault();return}copy(text(a))});row.appendChild(ob)}
 f.appendChild(row);
 f.appendChild(nameChip(function(){st.classList.remove("on");$("b",st).textContent="Name changed";$("div span",st).textContent="Copy the prompt again.";pre.textContent=text(a)}));
 if(a.note){f.appendChild(el("p","sv-note",esc(a.note)))}
 return f}
function chatPanel(a){var f=D.createDocumentFragment(),ol=el("ol","sv-tml");
 function step(n,title,content){var li=el("li","sv-s");li.innerHTML='<span class="sv-dot"><b>'+n+'</b>'+CHECK+'</span><div class="sv-sb"><p class="sv-st">'+title+'</p></div>';
  var sb=$(".sv-sb",li);content.forEach(function(c){sb.appendChild(c)});ol.appendChild(li);return li}
 function mark(li){li.classList.add("done");var nx=li.nextElementSibling;if(nx)nx.classList.add("now")}
 var j=bigBtn("Join on minepoa.com",J.join,"sv-sm");j.insertAdjacentHTML("beforeend",ARR);
 var s1=step(1,"Create your Agent",[j]);s1.classList.add("now");j.addEventListener("click",function(e){if(j.dataset.pz){e.preventDefault();return}mark(s1)});
 var c2=[];
 if(a.cset&&a.cfill){var ad=bigBtn("Add to "+a.name,a.cset,"sv-sm");ad.insertAdjacentHTML("beforeend",ARR);c2.push(ad);ad.addEventListener("click",function(){mark(s2)})}
 var u=el("div","sv-url",'<code>'+esc(J.mcp)+'</code>');var ub=el("button","sv-ic",CP);ub.type="button";ub.setAttribute("aria-label","Copy connector URL");
 ub.addEventListener("click",function(){if(copy(J.mcp)){ub.classList.add("ok");setTimeout(function(){ub.classList.remove("ok")},1600);mark(s2)}});u.appendChild(ub);c2.push(u);
 if(a.where&&!a.cfill)c2.push(el("p","sv-where",esc(a.where)));
 if(a.cnote)c2.push(el("p","sv-note",esc(a.cnote)));
 c2.push(el("p","sv-warn",esc(J.warn)));
 var s2=step(2,"Add the connector",c2);
 var pb=bigBtn(a.pre?"Copy and open "+a.name:"Copy prompt",a.pre?openUrl(a):null,"sv-sm");pb.insertAdjacentHTML("afterbegin",CP);
 pb.addEventListener("click",function(e){if(pb.dataset.pz){e.preventDefault();return}if(copy(text(a))){if(!a.pre)flash(pb,TOUCH?"Copied":"Copied. Paste with "+KEY);mark(s3)}});
 var s3=step(3,"Paste the prompt",[pb]);
 f.appendChild(ol);return f}
function nonePanel(a){var f=D.createDocumentFragment();f.appendChild(el("p","sv-no",esc(a.name)+" can't run an Agent yet. Use one of these:"));
 var g=el("div","sv-alts");J.alts.forEach(function(id){var x=BY[id],b=el("button","sv-t sv-full",'<span class="sv-tl">'+logo(x)+'</span><span class="sv-tn">'+esc(x.name)+'</span>');b.type="button";b.dataset.app=id;g.appendChild(b)});
 f.appendChild(g);return f}
/* morph: View Transitions where supported (the tile logo flies into the panel head), else a CSS fade and lift */
function morph(fn){if(!RM&&D.startViewTransition)D.startViewTransition(fn);else fn()}
function show(id,push,fromTap){var a=BY[id];if(!a)return;var copied=false;
 if(fromTap&&a.tier=="full"&&!PZ())copied=copy(text(a));   /* one tap: the copy runs inside the click */
 morph(function(){CUR=a;pick.hidden=true;panel.hidden=false;foot.hidden=a.tier=="none";
  $("[data-sv-logo]").innerHTML=logo(a);$("[data-sv-app]").textContent=a.name;
  var tg=$("[data-sv-tag]");tg.className="sv-ptag sv-"+a.tier;tg.textContent=a.tier=="full"?"Runs code":a.tier=="connector"?"Chat + connector":"Not supported";
  body.innerHTML="";body.appendChild(a.tier=="full"?codePanel(a,copied):a.tier=="connector"?chatPanel(a):nonePanel(a));
  panel.classList.remove("in");void panel.offsetWidth;panel.classList.add("in");
  if(pre)pre.textContent=text(a);
  var f=$("button.sv-btn:not(.off),a.sv-btn:not(.off)",body)||$("[data-sv-back]");if(f)f.focus({preventScroll:true})});
 if(push)history.pushState({sv:id},"","#"+id)}
function back(push){morph(function(){CUR=null;panel.hidden=true;foot.hidden=true;pick.hidden=false;pick.classList.remove("in");void pick.offsetWidth;pick.classList.add("in");
 var t=$('.sv-grid [data-app]');if(t)t.focus({preventScroll:true})});if(push)history.pushState({},"",location.pathname+location.search)}
root.addEventListener("click",function(e){var t=e.target.closest&&e.target.closest("[data-app]");if(t&&root.contains(t)){show(t.dataset.app,true,true);return}
 if(e.target.closest&&e.target.closest("[data-sv-back]"))back(true)});
W.addEventListener("popstate",function(){var h=location.hash.slice(1);if(BY[h])show(h,false,false);else back(false)});
D.addEventListener("keydown",function(e){if(e.key=="Escape"&&CUR&&!(e.target&&/INPUT|TEXTAREA/.test(e.target.tagName))){e.preventDefault();e.stopImmediatePropagation();history.back()}},true);
/* ?flow=name: the name first variant (name, Next, then the picker) for comparison */
if(FLOW){var n0=$("[data-sv-name0]"),i0=$("[data-sv-n0]"),er0=$("[data-sv-err0]");n0.hidden=false;pick.hidden=true;i0.value=NAME;
 function next(){var v=i0.value.trim(),m=nameMsg(v);if(m){er0.textContent=m;er0.hidden=false;return}NAME=v;morph(function(){n0.hidden=true;pick.hidden=false;pick.classList.add("in")})}
 $("[data-sv-next]").addEventListener("click",next);i0.addEventListener("keydown",function(e){if(e.key=="Enter"){e.preventDefault();next()}})}
var h0=location.hash.slice(1);if(BY[h0])show(h0,false,false);
/* paused: POAScan's own join state every 5 min while visible (never minepoa); reload once it opens */
if(PZ())setInterval(function(){if(D.hidden)return;fetch("/api/v1/prompts/join",{cache:"no-store",credentials:"omit"}).then(function(r){return r.ok?r.json():null}).then(function(d){
 var s=d&&d.join&&d.join.state&&d.join.state.state;if(s&&s!="halted")location.reload()}).catch(function(){})},300000);
})();
