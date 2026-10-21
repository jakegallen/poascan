/* POAScan client: live updates over /ws (fallback: polling), countdown ring, identicons, charts, copy, nav. No deps. */
(function(){
"use strict";
var D=document,W=window,RM=W.matchMedia&&W.matchMedia("(prefers-reduced-motion: reduce)").matches;
function $(s,r){return (r||D).querySelector(s)}function $$(s,r){return Array.prototype.slice.call((r||D).querySelectorAll(s))}
function pad(n){return n<10?"0"+n:""+n}
function utc(ts){var d=new Date(ts*1000);return d.getUTCFullYear()+"-"+pad(d.getUTCMonth()+1)+"-"+pad(d.getUTCDate())+" "+pad(d.getUTCHours())+":"+pad(d.getUTCMinutes())+" UTC"}
function rel(ts){var s=Math.max(0,Math.floor(Date.now()/1000-ts));return s<60?s+"s ago":s<3600?Math.floor(s/60)+"m ago":s<86400?Math.floor(s/3600)+"h "+Math.floor(s%3600/60)+"m ago":Math.floor(s/86400)+"d ago"}
function dur(s){s=Math.max(0,Math.floor(s));return s>=3600?Math.floor(s/3600)+"h "+pad(Math.floor(s%3600/60))+"m":Math.floor(s/60)+"m "+pad(s%60)+"s"}
function compact(v,d){var a=Math.abs(v),u=[[1e9,"B"],[1e6,"M"],[1e3,"K"]];for(var i=0;i<3;i++)if(a>=u[i][0])return (v/u[i][0]).toFixed(d)+u[i][1];return Math.round(v).toLocaleString("en-US")}
var FMT={int:function(v){return Math.round(v).toLocaleString("en-US")},c2:function(v){return compact(v,2)},c1:function(v){return compact(v,1)},p1:function(v){return v.toFixed(1)+"%"}};

/* times */
function times(root){$$("time.t",root).forEach(function(t){var ts=+t.dataset.ts;if(!ts)return;if(!t.title)t.title=utc(ts)+" · local "+new Date(ts*1000).toLocaleString();if(t.classList.contains("rel"))t.textContent=rel(ts)})}

/* hex identicons: deterministic from the address */
function h32(s,seed){var h=seed>>>0;for(var i=0;i<s.length;i++){h=Math.imul(h^s.charCodeAt(i),16777619)>>>0}return h}
var PAL=["#FFB000","#E3A33A","#C8742B","#FFD36B","#8FA3B8","#3DDC97","#6B5420","#2B261C","#F3EDE0"];
function identicon(a){var h1=h32(a,2166136261),h2=h32(a,374761393),c=[];for(var i=0;i<6;i++){var k=((i<3?h1>>>(i*5):h2>>>((i-3)*5))&31)%PAL.length;c.push(PAL[k])}
 var P=[[12,1.5],[21.1,6.75],[21.1,17.25],[12,22.5],[2.9,17.25],[2.9,6.75]],cx=12,cy=12,o="";
 var inner=(h2>>>20)%3;
 for(i=0;i<6;i++){var p=P[i],q=P[(i+1)%6];o+='<path d="M'+cx+' '+cy+'L'+p[0]+' '+p[1]+'L'+q[0]+' '+q[1]+'Z" fill="'+c[i]+'" fill-opacity="'+(0.55+((h1>>>i)&1)*0.45)+'"/>'}
 o+='<path d="M12 1.5 21.1 6.75v10.5L12 22.5 2.9 17.25V6.75z" fill="none" stroke="#0E0D0B" stroke-width="1.2"/>';
 if(inner)o+='<path d="M12 7.5 15.9 9.75v4.5L12 16.5 8.1 14.25v-4.5z" fill="#0E0D0B" fill-opacity="'+(inner==1?.85:.4)+'"/>';
 return '<svg viewBox="0 0 24 24">'+o+'</svg>'}
function paintIds(root){$$(".idn:not(.on)",root).forEach(function(e){var a=e.dataset.a;if(a){e.innerHTML=identicon(a);e.classList.add("on")}})}

/* copy with burst */
D.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest(".cp");if(!b)return;e.preventDefault();
 var v=b.dataset.copy;(navigator.clipboard?navigator.clipboard.writeText(v):Promise.reject()).catch(function(){var t=D.createElement("textarea");t.value=v;D.body.appendChild(t);t.select();try{D.execCommand("copy")}catch(_){}t.remove()});
 b.classList.remove("ok");void b.offsetWidth;b.classList.add("ok");setTimeout(function(){b.classList.remove("ok")},900)});

/* nav drawer */
var burger=$(".burger"),navEl=$("#nav");
function setHdr(){var h=$(".hdr");if(h)D.documentElement.style.setProperty("--hdr-h",Math.round(h.getBoundingClientRect().bottom)+"px")}
function navOpen(o){D.body.classList.toggle("navopen",o);D.documentElement.classList.toggle("navlock",o);if(burger)burger.setAttribute("aria-expanded",o?"true":"false");if(o){setHdr();var f=navEl&&navEl.querySelector("a");if(f)f.focus({preventScroll:true})}}
if(burger){burger.addEventListener("click",function(e){e.stopPropagation();navOpen(!D.body.classList.contains("navopen"))});
 D.addEventListener("keydown",function(e){if(e.key==="Escape"&&D.body.classList.contains("navopen")){navOpen(false);burger.focus()}});
 D.addEventListener("click",function(e){if(!D.body.classList.contains("navopen"))return;var a=e.target.closest&&e.target.closest("#nav a");if(a||!e.target.closest("#nav"))navOpen(false)});
 W.addEventListener("resize",function(){if(D.body.classList.contains("navopen")){if(getComputedStyle(burger).display==="none")navOpen(false);else setHdr()}})}

/* countdown ring + molten vessel */
var flashed={};
function tick(){var now=Date.now()/1000;
 $$(".cd[data-close]").forEach(function(c){var e=+c.dataset.close;if(e)c.textContent=dur(e-now)});
 $$(".xcd[data-close]").forEach(function(c){var e=+c.dataset.close;if(e)c.textContent=e>now?dur(e-now):"expired"});
 $$(".ring[data-close]").forEach(function(r){var s=+r.dataset.start,e=+r.dataset.close;if(!s||!e)return;var f=Math.min(1,Math.max(0,(now-s)/(e-s)));
  var p=r.querySelector(".rp");if(p)p.setAttribute("stroke-dasharray",(f*100).toFixed(2)+" 100");
  var left=e-now;r.classList.toggle("final",left>0&&left<=60);
  if(left<=0&&!flashed[e]){flashed[e]=1;r.classList.remove("flash");void r.offsetWidth;r.classList.add("flash")}});
 $$(".vessel[data-close]").forEach(function(v){var s=+v.dataset.start,e=+v.dataset.close;if(!s||!e)return;var f=Math.min(1,Math.max(0,(now-s)/(e-s)));
  var m=v.querySelector(".molten"),t=v.querySelector(".vp");if(m)m.style.width=(f*100).toFixed(2)+"%";if(t)t.textContent=Math.floor(f*100)+"%"});
 times()}

/* number tween (<200ms) */
var prev={};
function tween(el,from,to,f){var fn=FMT[f]||FMT.int,t0=null,DUR=180;
 if(RM||from==null||from===to){return}
 function step(ts){if(!t0)t0=ts;var k=Math.min(1,(ts-t0)/DUR),v=from+(to-from)*(1-Math.pow(1-k,3));el.textContent=fn(v);if(k<1)requestAnimationFrame(step)}
 requestAnimationFrame(step)}
function setNum(key,val,f){if(val==null)return;var old=prev[key];prev[key]=val;if(old===undefined||old===val)return;
 $$('[data-live="'+key+'"]').forEach(function(box){var n=box.matches(".num")?box:box.querySelector(".num");if(!n)return;
  var fn=FMT[f]||FMT.int;n.title="";tween(n,old,val,f);setTimeout(function(){n.textContent=fn(val)},RM?0:190);
  box.classList.remove("bump");void box.offsetWidth;box.classList.add("bump")})}

/* feed merge: new rows slide in */
function mergeFeed(html){var f=$("#feed");if(!f||!html)return;var tmp=D.createElement("div");tmp.innerHTML=html;
 var have={};$$(".frow",f).forEach(function(r){have[r.dataset.id]=1});
 var rows=$$(".frow",tmp),fresh=rows.filter(function(r){return !have[r.dataset.id]});
 if(!$(".frow",f)){f.innerHTML=html;paintIds(f);times(f);return}
 if(!fresh.length)return;
 fresh.reverse().forEach(function(r){r.classList.add("in");f.insertBefore(r,f.firstChild)});
 var all=$$(".frow",f);for(var i=rows.length;i<all.length;i++)all[i].remove();
 paintIds(f);times(f)}
function setTicker(html){var t=$("#ticker");if(!t||!html)return;var tmp=D.createElement("div");tmp.innerHTML=html;var n=$(".tk-track",tmp),o=$(".tk-track",t);
 if(o&&n&&o.dataset.sig===n.dataset.sig)return;t.innerHTML=html;paintIds(t);times(t)}

/* apply a snapshot (from WS or polling) */
function apply(s){if(!s||s.t&&s.t!=="snap")return;
 var p=$("#livepill");if(p){p.className="pill "+(s.live?"live":"stale");var l=p.querySelector("span");if(l)l.textContent=s.live?"Live":"Stale"}
 if(s.nums)Object.keys(s.nums).forEach(function(k){setNum(k,s.nums[k][0],s.nums[k][1])});
 if(s.cards)Object.keys(s.cards).forEach(function(k){var el=$('.sv[data-live="'+k+'"]');if(!el)return;var tmp=D.createElement("div");tmp.innerHTML=s.cards[k];var nv=$(".sv",tmp);if(nv&&nv.innerHTML!==el.innerHTML)el.innerHTML=nv.innerHTML});
 if(s.epoch){$$(".ring,.vessel[data-close]").forEach(function(r){if(s.epoch.start)r.dataset.start=s.epoch.start;if(s.epoch.close)r.dataset.close=s.epoch.close});
  $$(".cd[data-close]").forEach(function(c){if(s.epoch.close)c.dataset.close=s.epoch.close});
  var be=$('[data-live="bm_ep"]');if(be&&s.epoch.n!=null)be.textContent=s.epoch.n}
 if(s.frags)Object.keys(s.frags).forEach(function(id){var el=D.getElementById(id);if(el&&el.dataset.h!==String(s.frags[id].length+":"+s.frags[id].slice(-40))){el.innerHTML=s.frags[id];el.dataset.h=s.frags[id].length+":"+s.frags[id].slice(-40);paintIds(el);times(el);tick()}});
 mergeFeed(s.feed);setTicker(s.ticker)}

/* transport: WebSocket with backoff, polling fallback */
var ws=null,fails=0,pollT=null,wantLive=!!($("#feed")||$("#tracker")||$("#ticker")||$("[data-live]"));
function poll(){fetch("/api/summary",{cache:"no-store"}).then(function(r){return r.json()}).then(apply).catch(function(){})}
function startPoll(){if(!pollT){poll();pollT=setInterval(poll,15000)}}
function stopPoll(){if(pollT){clearInterval(pollT);pollT=null}}
function connect(){if(!("WebSocket" in W)){startPoll();return}
 try{ws=new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host+"/ws")}catch(e){fails++;startPoll();return retry()}
 var opened=false;
 ws.onopen=function(){opened=true;fails=0;stopPoll()};
 ws.onmessage=function(m){try{apply(JSON.parse(m.data))}catch(e){}};
 ws.onclose=function(){ws=null;if(!opened)fails++;if(fails>=2)startPoll();retry()};
 ws.onerror=function(){try{ws.close()}catch(e){}}}
function retry(){var d=Math.min(30000,1000*Math.pow(2,Math.min(fails,5)))*(0.7+Math.random()*0.6);setTimeout(function(){if(!D.hidden)connect();else D.addEventListener("visibilitychange",function v(){if(!D.hidden){D.removeEventListener("visibilitychange",v);connect()}})},d)}

/* charts: draw-in on view + crosshair tooltip */
function charts(){var io="IntersectionObserver" in W?new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add("in");io.unobserve(e.target)}})},{rootMargin:"0px 0px -40px 0px"}):null;
 $$(".chart").forEach(function(c){if(io&&!RM)io.observe(c);else c.classList.add("in")});
 $$(".chartbox").forEach(function(b){var svg=$("svg",b);if(!svg)return;var items=$$("[data-tip]",svg);if(!items.length)return;
  var xh=D.createElement("i"),xt=D.createElement("div");xh.className="xh";xt.className="xt";b.appendChild(xh);b.appendChild(xt);var on=null;
  function move(e){var r=svg.getBoundingClientRect(),vb=svg.viewBox.baseVal,sx=r.width/vb.width,x=(e.clientX-r.left)/sx,best=null,bd=1e9;
   items.forEach(function(it){var d=Math.abs(+it.dataset.cx-x);if(d<bd){bd=d;best=it}});if(!best)return;
   if(on!==best){if(on)on.classList.remove("on");best.classList.add("on");on=best;xt.textContent=best.dataset.tip}
   var px=+best.dataset.cx*sx+(r.left-b.getBoundingClientRect().left)+b.scrollLeft;xh.style.left=px+"px";
   var w=xt.offsetWidth/2,bw=b.clientWidth+b.scrollLeft;xt.style.left=Math.max(w+b.scrollLeft,Math.min(bw-w,px))+"px";b.classList.add("hov")}
  b.addEventListener("pointermove",move);b.addEventListener("pointerdown",move);
  b.addEventListener("pointerleave",function(){b.classList.remove("hov");if(on)on.classList.remove("on");on=null})})}

/* join modal */
var jm=$("#joinmodal"),toastEl=$("#toast"),toastT;
var KEY=/Mac|iPhone|iPad/.test(navigator.platform||navigator.userAgent)?"⌘V":"Ctrl+V";
function toast(m,big){if(!toastEl)return;var am0=D.getElementById("askmodal"),host=(jm&&jm.open)?jm:(am0&&am0.open)?am0:D.body;if(toastEl.parentNode!==host)host.appendChild(toastEl);toastEl.textContent=m;toastEl.classList.toggle("big",!!big);toastEl.classList.remove("on");void toastEl.offsetWidth;toastEl.classList.add("on");clearTimeout(toastT);toastT=setTimeout(function(){toastEl.classList.remove("on")},big?7000:2600)}
function copyText(v){function fb(){var t=D.createElement("textarea");t.value=v;t.setAttribute("readonly","");t.style.cssText="position:fixed;opacity:0;top:0;left:0";(jm&&jm.open?jm:D.body).appendChild(t);t.select();var ok=false;try{ok=D.execCommand("copy")}catch(_){}t.remove();return ok}
 if(navigator.clipboard&&W.isSecureContext)return navigator.clipboard.writeText(v).then(function(){return true},function(){return fb()});return Promise.resolve(fb())}
if(jm){var P=($("#jm-prompt",jm).textContent||"").trim();
 function PF(el){var c=el&&el.closest&&el.closest("[data-pcard]");return c?($(".pc-text",c).textContent||"").trim():P}
 $$("a[data-pre]",jm).forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(P)});
 $$("[data-pcard] a[data-pre]").forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(PF(a))});
 function jmOpen(){if(D.body.classList.contains("navopen")&&typeof navOpen==="function")navOpen(false);if(jm.showModal)jm.showModal();else jm.setAttribute("open","");D.documentElement.classList.add("jmlock")}
 function jmClose(){if(jm.close)jm.close();else jm.removeAttribute("open")}
 jm.addEventListener("close",function(){D.documentElement.classList.remove("jmlock")});
 D.addEventListener("click",function(e){var t=e.target;if(!t.closest)return;
  if(t.closest("[data-join]")){e.preventDefault();e.stopPropagation();jmOpen();return}
  var inCard=!jm.open&&t.closest("[data-pcard]");
  if(!jm.open&&!inCard)return;
  if(!inCard&&(t===jm||t.closest("[data-jmclose]"))){jmClose();return}
  var P=PF(t);
  var cb=t.closest("[data-copy-prompt]");if(cb){copyText(P).then(function(ok){cb.classList.remove("ok");void cb.offsetWidth;cb.classList.add("ok");cb.textContent=ok?"Copied":"Select & copy";setTimeout(function(){cb.classList.remove("ok");cb.textContent="Copy prompt"},1600);if(!ok){var r=D.createRange();r.selectNodeContents(inCard?$(".pc-text",inCard):$("#jm-prompt",jm));var sl=W.getSelection();sl.removeAllRanges();sl.addRange(r)}});return}
  var co=t.closest("[data-cpopen]");if(co){var u=co.dataset.cpopen,n=co.dataset.app,pre=co.dataset.pre,pr=copyText(P);if(pre)u=pre+encodeURIComponent(P);if(u)W.open(u,"_blank","noopener");pr.then(function(ok){co.classList.remove("ok");void co.offsetWidth;co.classList.add("ok");setTimeout(function(){co.classList.remove("ok")},1600);toast(ok?"Prompt copied · paste it into "+(u?"the new "+n+" chat":n)+" ("+KEY+") and send":"Copy the prompt above, then paste it into "+n,1)});return}
  var au=t.closest("a.app[data-pre]");if(au){copyText(P);toast("Opening "+au.dataset.app+" · prompt also copied");return}
 },true);
}
/* compact desktop search */
var sf=$(".search");if(sf){var si=$("input",sf),sb=$("button",sf);
 function compactS(){return si&&si.getBoundingClientRect().width<8&&!sf.classList.contains("open")}
 sb.addEventListener("click",function(e){if(compactS()){e.preventDefault();sf.classList.add("open");si.focus()}else if(sf.classList.contains("open")&&!si.value.trim()){e.preventDefault();sf.classList.remove("open")}});
 si.addEventListener("blur",function(){setTimeout(function(){if(!sf.contains(D.activeElement)&&!si.value.trim())sf.classList.remove("open")},120)});
 si.addEventListener("keydown",function(e){if(e.key==="Escape"){si.value="";sf.classList.remove("open");sb.focus()}})}

/* ask your agent: shared prompt dialog */
var am=$("#askmodal");
if(am){var amP=$("#am-p",am),amT=$("#am-t",am),amC=$(".am-c",am),cur=[];
 function amSet(i){var x=cur[i];if(!x)return;amP.textContent=x[1];amT.textContent=x[0];amP.scrollTop=0;
  $$(".chip",amC).forEach(function(c,j){c.classList.toggle("on",j===i);c.setAttribute("aria-pressed",j===i?"true":"false")});
  $$("a[data-pre]",am).forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(x[1])})}
 D.addEventListener("click",function(e){var t=e.target;if(!t.closest)return;var b=t.closest("[data-ask]");
  if(b){e.preventDefault();try{cur=JSON.parse(b.dataset.ask)}catch(_){return}
   amC.innerHTML="";cur.forEach(function(x,i){var c=D.createElement("button");c.type="button";c.className="chip";c.textContent=x[0];c.addEventListener("click",function(){amSet(i)});amC.appendChild(c)});
   amC.hidden=cur.length<2;amSet(0);if(am.showModal)am.showModal();else am.setAttribute("open","");D.documentElement.classList.add("jmlock");return}
  if(am.open&&(t===am||t.closest("[data-amclose]"))){if(am.close)am.close();else am.removeAttribute("open")}});
 am.addEventListener("close",function(){D.documentElement.classList.remove("jmlock")})}
/* sortable tables */
function sortables(){$$("table.sortable").forEach(function(tb){$$("th[data-sort]",tb).forEach(function(th,ci){th.tabIndex=0;th.setAttribute("role","button");
 function go(){var asc=th.dataset.dir!=="asc"&&th.dataset.dir!==undefined?true:th.dataset.dir==="desc";if(th.dataset.dir===undefined)asc=th.dataset.sort==="text";
  $$("th",tb).forEach(function(o){delete o.dataset.dir});th.dataset.dir=asc?"asc":"desc";
  var bd=tb.tBodies[0],rs=Array.prototype.slice.call(bd.rows),num=th.dataset.sort==="num";
  rs.sort(function(a,b){var x=a.cells[ci]&&a.cells[ci].dataset.v,y=b.cells[ci]&&b.cells[ci].dataset.v;if(num){x=parseFloat(x);y=parseFloat(y);x=isNaN(x)?-1e18:x;y=isNaN(y)?-1e18:y;return asc?x-y:y-x}
   x=(x||"").toLowerCase();y=(y||"").toLowerCase();return asc?(x<y?-1:x>y?1:0):(x<y?1:x>y?-1:0)});
  rs.forEach(function(r){bd.appendChild(r)})}
 th.addEventListener("click",go);th.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();go()}})})})}
paintIds();times();charts();sortables();setInterval(tick,1000);tick();
if(wantLive)connect();
})();
/* one "Ask agent" label per page: later Ask buttons keep the icon, title and aria-label */
(function(){var b=[].slice.call(document.querySelectorAll(".askb"));b.slice(1).forEach(function(x){x.classList.add("ico")})})();
