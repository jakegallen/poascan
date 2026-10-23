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
function c3(v){var a=Math.abs(v),u=[[1e9,"B"],[1e6,"M"],[1e3,"K"]];for(var i=0;i<3;i++)if(a>=u[i][0]*0.9995){var x=v/u[i][0],d=Math.abs(x)<9.995?2:Math.abs(x)<99.95?1:0;if(Math.abs(+x.toFixed(d))>=1000&&i>0){x=v/u[i-1][0];return x.toFixed(2)+u[i-1][1]}return x.toFixed(d)+u[i][1]}return Math.round(v).toLocaleString("en-US")}
var FMT={int:function(v){return Math.round(v).toLocaleString("en-US")},c2:function(v){return c3(v)},c1:function(v){return c3(v)},p1:function(v){return v.toFixed(1)+"%"}};

/* times */
function upts(root){$$("time[data-upts]",root).forEach(function(t){var ts=+t.dataset.upts;if(!ts||t.dataset.done==ts)return;var d=new Date(ts*1000),z=d.toISOString().slice(11,16)+"Z",l="";
  try{l=new Intl.DateTimeFormat(undefined,{hour:"numeric",minute:"2-digit",timeZoneName:"short"}).format(d)}catch(e){}
  t.textContent=l?l+" \u00b7 "+z:z;t.dataset.done=ts})}
function times(root){upts(root);$$("time.t",root).forEach(function(t){var ts=+t.dataset.ts;if(!ts)return;if(!t.title)t.title=utc(ts)+" · local "+new Date(ts*1000).toLocaleString();if(t.classList.contains("rel"))t.textContent=rel(ts)})}

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

/* digit roll: only the digits that changed slide up into place (transform + opacity, clipped per digit, no reflow).
   Updates from one snapshot are applied in a single animation frame. Reduced motion sets the text directly. */
var prev={},rq=[],rqT=0;
function esc(c){return c==="<"?"&lt;":c==="&"?"&amp;":c}
function roll(n,t){rq.push([n,t]);if(!rqT)rqT=requestAnimationFrame(flushRoll)}
function flushRoll(){rqT=0;var q=rq;rq=[];q.forEach(function(x){var n=x[0],t=x[1],o=n.textContent;if(o===t)return;
 if(RM||D.hidden){n.textContent=t;return}
 if(o.length!==t.length){n.textContent=t;n.classList.remove("rfade");void n.offsetWidth;n.classList.add("rfade");return}
 var h="";for(var i=0;i<t.length;i++){var c=t.charAt(i);h+=c!==o.charAt(i)&&/[0-9]/.test(c)?'<span class="rl"><span>'+c+"</span></span>":esc(c)}
 n.innerHTML=h;clearTimeout(n._rt);n._rt=setTimeout(function(){if(n.textContent===t)n.textContent=t},700)})}
function setNum(key,val,f){if(val==null)return;var old=prev[key];prev[key]=val;if(old===undefined||old===val)return;
 $$('[data-live="'+key+'"]').forEach(function(box){var n=box.matches(".num")?box:box.querySelector(".num");if(!n)return;
  n.title="";roll(n,(FMT[f]||FMT.int)(val))})}

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

/* live tables: when a snapshot shows a new tx or close, fetch only the newest rows from POAScan itself and fade in the ones we lack */
function usdOn(){var b=$('.utog button[aria-pressed="true"]');return !!(b&&b.dataset.u==="usd")}
function rk(r){var a=r.querySelector("a[href]");return a?a.getAttribute("href"):r.textContent}
function liveRows(s){$$("[data-liverows]").forEach(function(box){var k=box.dataset.liverows,top=k==="txs"?((s.feed||"").match(/data-id="([^"]+)"/)||[])[1]:s.last&&s.last.epoch;
  if(top==null||String(top)===box.dataset.top||box._busy)return;box._busy=1;
  fetch("/fragment/rows?t="+k,{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(h){box._busy=0;box.dataset.top=String(top);
   var tb=$("tbody",box);if(!tb)return;var tmp=D.createElement("tbody");tmp.innerHTML=h;var have={},cur=$$("tr:not(.xrow)",tb);cur.forEach(function(r){have[rk(r)]=1});
   var fresh=$$("tr",tmp).filter(function(r){return !have[rk(r)]});if(!fresh.length)return;
   fresh.reverse().forEach(function(r){r.classList.add("in");tb.insertBefore(r,tb.firstChild)});
   if(box.dataset.keep!=="all"){var all=$$("tr:not(.xrow)",tb);for(var i=cur.length;i<all.length;i++){var nx=all[i].nextElementSibling;if(nx&&nx.classList.contains("xrow"))nx.remove();all[i].remove()}}
   paintIds(tb);times(tb);pris(box);if($(".utog"))usdApply(usdOn())}).catch(function(){box._busy=0})})}

/* apply a snapshot (from WS or polling) */
function apply(s){if(!s||s.t&&s.t!=="snap")return;
 var p=$("#livepill");if(p){var f=s.pill||{state:s.live?"live":"stale",label:s.live?"Live":"Stale",why:""};p.className="pill "+f.state;p.hidden=f.state=="up";if(f.href)p.setAttribute("href",f.href);p.title=f.state=="live"?"Status":(f.why||f.label);var l=p.querySelector("span");if(l)l.textContent=f.label}
 var ud=$("#updot");if(ud&&s.pill)ud.hidden=s.pill.state!="up";
 var ul=$("[data-upline]");if(ul&&s.upline!=null){if(s.upline&&ul.innerHTML!==s.upline)ul.innerHTML=s.upline;ul.parentNode.hidden=!s.upline}
 var us=$("[data-upstamp]");if(us&&s.upstamp){var ot=$("time",us);if(!ot||ot.dataset.upts!==(s.upstamp.match(/data-upts="(\d+)"/)||[])[1]){us.innerHTML=s.upstamp;upts(us)}}
 var uv=$("[data-upview]");if(uv&&s.upsig&&s.upsig!==uv.dataset.sig&&!uv._busy){uv._busy=1;fetch("/fragment/upgrade",{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(h){var t=D.createElement("div");t.innerHTML=h;var nv=t.firstElementChild;if(nv){uv.replaceWith(nv);times(nv)}}).catch(function(){uv._busy=0})}
 if(s.routes)$$("[data-hroute]").forEach(function(li){var v=s.routes[li.dataset.hroute];if(!v)return;var t=$(".tag",li);if(!t)return;li.dataset.st=v;t.className="tag "+(v=="open"||v=="responding"?"ok":v=="paused"?"warn":v=="slow"?"warn slow":"");t.textContent=v=="open"?"Open":v=="responding"?"Responding":v=="paused"?"Paused":v=="slow"?"Slow":"Not read yet"});
 if(s.nums)Object.keys(s.nums).forEach(function(k){setNum(k,s.nums[k][0],s.nums[k][1])});
 if(s.cards)Object.keys(s.cards).forEach(function(k){var el=$('.sv[data-live="'+k+'"]');if(!el)return;var tmp=D.createElement("div");tmp.innerHTML=s.cards[k];var nv=$(".sv",tmp);if(!nv)return;if(nv.innerHTML!==el.innerHTML)el.innerHTML=nv.innerHTML;el.className=nv.className;var st=nv.getAttribute("style");if(st)el.setAttribute("style",st);else el.removeAttribute("style")});
 if(s.epoch){$$(".ring,.vessel[data-close]").forEach(function(r){if(s.epoch.start)r.dataset.start=s.epoch.start;if(s.epoch.close)r.dataset.close=s.epoch.close});
  $$(".cd[data-close]").forEach(function(c){if(s.epoch.close)c.dataset.close=s.epoch.close});
  var be=$('[data-live="bm_ep"]');if(be&&s.epoch.n!=null)be.textContent=s.epoch.n}
 if(s.frags)Object.keys(s.frags).forEach(function(id){var el=D.getElementById(id);if(el&&el.dataset.h!==String(s.frags[id].length+":"+s.frags[id].slice(-40))){el.innerHTML=s.frags[id];el.dataset.h=s.frags[id].length+":"+s.frags[id].slice(-40);paintIds(el);times(el);tick()}});
 mergeFeed(s.feed);setTicker(s.ticker);liveRows(s)}

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

/* charts: visible by default and drawn in once by CSS on load. Only charts below the fold are held back (.pre) until they
   scroll into view, so a chart is never left hidden if this script or IntersectionObserver is missing. + crosshair tooltip */
function charts(){if(RM||!("IntersectionObserver" in W))return chartTips();
 var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){var c=e.target;c.classList.remove("pre");void c.getBoundingClientRect();c.classList.add("in");io.unobserve(c)}})},{rootMargin:"0px 0px -40px 0px"});
 $$(".chart").forEach(function(c){if(c.getBoundingClientRect().top>innerHeight){c.classList.add("pre");io.observe(c)}});
 W.addEventListener("beforeprint",function(){$$(".chart.pre").forEach(function(c){c.classList.remove("pre")})});
 /* backstop: if the observer never fires (seen on iOS after a background load or a back/forward restore), a chart that is on or
    above the screen is shown on the next scroll or pageshow */
 var rq=0;function rv(){rq=0;$$(".chart.pre").forEach(function(c){if(c.getBoundingClientRect().top<innerHeight){c.classList.remove("pre");c.classList.add("in");io.unobserve(c)}})}
 W.addEventListener("scroll",function(){if(!rq){rq=1;setTimeout(rv,250)}},{passive:true});W.addEventListener("pageshow",rv);
 chartTips()}
function chartTips(){
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
/* Prompt button counts: a fixed id only ('<card>.<action>'), first-party POST /ops/e, no cookie and nothing about the visitor. The server takes ids from its allowlist and drops the rest. */
function ev(id){if(!id)return;try{var b=JSON.stringify({e:id});if(navigator.sendBeacon&&navigator.sendBeacon("/ops/e",b))return;fetch("/ops/e",{method:"POST",body:b,keepalive:true,credentials:"omit"}).catch(function(){})}catch(_){}}
function pidOf(el){var c=el&&el.closest&&el.closest("[data-pid]");return c?c.dataset.pid:""}
function regOn(pre){return !!(pre&&pre.dataset.regOn==="1")}
function copyText(v){function fb(){var t=D.createElement("textarea");t.value=v;t.setAttribute("readonly","");t.style.cssText="position:fixed;opacity:0;top:0;left:0";(jm&&jm.open?jm:D.body).appendChild(t);t.select();var ok=false;try{ok=D.execCommand("copy")}catch(_){}t.remove();return ok}
 if(navigator.clipboard&&W.isSecureContext)return navigator.clipboard.writeText(v).then(function(){return true},function(){return fb()});return Promise.resolve(fb())}
D.addEventListener("click",function(e){var a=e.target.closest&&e.target.closest("a[data-mcpcopy]");if(!a)return;var pi=pidOf(a);if(pi)ev(pi+".add");copyText(a.dataset.mcpcopy).then(function(ok){if(ok)toast("Copied. Paste in "+a.dataset.app+" if it didn't open.",1)})});
/* Key guard: a PoA key pasted into any field is cleared before anything sees it (search suggest, submit, the prompt) */
(function(){var KR=/(^|[^A-Za-z0-9])(p?sk|pk)_[A-Za-z0-9_\-]{12,}/,MSG="That looks like a PoA key. POAScan never takes keys and sent nothing. Never paste it anywhere.";
 function hit(v){return typeof v==="string"&&KR.test(v)}
 function say(){if(typeof toast==="function")toast(MSG,1);else alert(MSG)}
 D.addEventListener("paste",function(e){var t=e.target,c=e.clipboardData&&e.clipboardData.getData("text");if(t&&(t.tagName==="INPUT"||t.tagName==="TEXTAREA")&&hit(c)){e.preventDefault();e.stopImmediatePropagation();say()}},true);
 D.addEventListener("input",function(e){var t=e.target;if(t&&(t.tagName==="INPUT"||t.tagName==="TEXTAREA")&&hit(t.value)){t.value="";e.stopImmediatePropagation();say()}},true);
 D.addEventListener("submit",function(e){var f=e.target,bad=0;$$("input,textarea",f).forEach(function(i){if(hit(i.value)){i.value="";bad=1}});if(bad){e.preventDefault();e.stopImmediatePropagation();say()}},true);
})();
/* Wallet setup prompts: one browser-made setup code per page load (s_ + 16 of a-z2-7; 256 % 32 == 0, so b&31 is unbiased), filled into the optional registry step before Copy and Open in read the text. Never sent to POAScan, never in a POAScan URL, never stored. */
(function(){var c=W.crypto;if(!c||!c.getRandomValues)return;var A="abcdefghijklmnopqrstuvwxyz234567",b=c.getRandomValues(new Uint8Array(16)),k="s_";for(var i=0;i<16;i++)k+=A[b[i]&31];$$("pre[data-reg]").forEach(function(p){var t=p.textContent,j=t.indexOf("\n\n"+p.dataset.regAt);if(j<0)return;p.textContent=t.slice(0,j)+"\n"+p.dataset.reg.split("{SETUP_CODE}").join(k)+t.slice(j);p.dataset.regOn="1"});
 var sp=$("[data-pid=start] pre[data-reg]");if(regOn(sp))ev("start.regshow");
 D.addEventListener("toggle",function(e){var d=e.target;if(d&&d.id==="xemb"&&d.open){var wp=$("pre[data-reg]",d);if(regOn(wp))ev("wallet.regshow")}},true)})();
/* /swaps#xemb opens the Add Emblem Wallet prompt (its toggle adds the setup code) */
(function(){function op(){if(W.location.hash!=="#xemb")return;var d=D.getElementById("xemb");if(d&&!d.open){d.open=true;d.scrollIntoView({block:"center"})}}op();W.addEventListener("hashchange",op)})();
/* Join name: the prompt carries the full register link; a fresh default name per visit, live-filled from /start's Name field */
(function(){var A="amber brisk cobalt copper dusk ember fable gentle hazel indigo jade lunar maple nimble opal quartz rapid sable tidal velvet".split(" "),N="otter heron lynx falcon badger comet cedar delta finch harbor kestrel lark marten osprey pike raven sparrow tern vole wren".split(" "),
 R=function(a){return a[Math.floor(Math.random()*a.length)]},gen=function(){return R(A)+"-"+R(N)+"-"+(100+Math.floor(Math.random()*900))},nm=gen(),RX=/(register\?label=)[^\s]*/;W.poaNewName=gen;
 function fill(pre,v){if(pre&&RX.test(pre.textContent))pre.textContent=pre.textContent.replace(RX,"$1"+v)}
 function hrefs(c,t){$$("a[data-pre]",c).forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(t)})}
 var jp=$("#jm-prompt");fill(jp,nm);
 var f=$("[data-name]");if(!f)return;var card=f.closest("[data-pcard]"),pre=card&&$(".pc-text",card);
 function upd(){var v=f.value||"";if(!/^[A-Za-z0-9_-]{1,32}$/.test(v))return;fill(pre,v);fill(jp,v);hrefs(card,(pre.textContent||"").trim())}   /* never strips: an invalid name is shown as an error on /start and changes nothing */
 f.value=nm;upd();f.addEventListener("input",upd)})();
/* prompt v2.3 check-ins: on /start the copied text carries the picked client's tag in the two check-in URLs
   (data-checkin base + data-tag + "/"); everything else stays byte for byte. Elsewhere the text is untagged. */
W.poaTag=function(c,t){var b=c&&c.dataset&&c.dataset.checkin,r=b&&$("input[name=client]:checked",c),g=r&&r.dataset.tag;return b&&g&&/^[a-z0-9-]{1,24}$/.test(g)?t.split(b).join(b+g+"/"):t};
if(jm){var P=($("#jm-prompt",jm).textContent||"").trim();
 function PF(el){var c=el&&el.closest&&el.closest("[data-pcard]");return c?W.poaTag(c,($(".pc-text",c).textContent||"").trim()):P}
 $$("a[data-pre]",jm).forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(P)});
 $$("[data-pcard] a[data-pre]").forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(PF(a))});
 function jmOpen(){ev("join.open");if(regOn($("#jm-prompt",jm)))ev("join.regshow");if(D.body.classList.contains("navopen")&&typeof navOpen==="function")navOpen(false);if(jm.showModal)jm.showModal();else jm.setAttribute("open","");D.documentElement.classList.add("jmlock")}
 function jmClose(){if(jm.close)jm.close();else jm.removeAttribute("open")}
 jm.addEventListener("close",function(){D.documentElement.classList.remove("jmlock")});
 D.addEventListener("click",function(e){var t=e.target;if(!t.closest)return;
  if(t.closest("[data-join]")){e.preventDefault();e.stopPropagation();jmOpen();return}
  var inCard=!jm.open&&t.closest("[data-pcard]");
  if(!jm.open&&!inCard)return;
  if(!inCard&&(t===jm||t.closest("[data-jmclose]"))){jmClose();return}
  var P=PF(t),pc=inCard||jm,pi=pc.dataset.pid||pidOf(pc),rg=regOn(inCard?$(".pc-text",inCard):$("#jm-prompt",jm));
  var cb=t.closest("[data-copy-prompt]");if(cb){ev(pi&&pi+(rg?".copyreg":".copy"));copyText(P).then(function(ok){cb.classList.remove("ok");void cb.offsetWidth;cb.classList.add("ok");var lb=$(".cpt",cb)||cb,o=cb.dataset.l||(cb.dataset.l=lb.textContent);lb.textContent=ok?"Copied":"Select & copy";setTimeout(function(){cb.classList.remove("ok");lb.textContent=o},1600);if(!ok){var r=D.createRange();r.selectNodeContents(inCard?$(".pc-text",inCard):$("#jm-prompt",jm));var sl=W.getSelection();sl.removeAllRanges();sl.addRange(r)}});return}
  var co=t.closest("[data-cpopen]");if(co){ev(pi&&pi+(rg?".appreg":".app"));var u=co.dataset.cpopen,n=co.dataset.app,pre=co.dataset.pre,pr=copyText(P);if(pre)u=pre+encodeURIComponent(P);if(u)W.open(u,"_blank","noopener,noreferrer");pr.then(function(ok){co.classList.remove("ok");void co.offsetWidth;co.classList.add("ok");setTimeout(function(){co.classList.remove("ok")},1600);toast(ok?"Prompt copied · paste it into "+(u?"the new "+n+" chat":n)+" ("+KEY+") and send":"Copy the prompt above, then paste it into "+n,1)});return}
  var au=t.closest("a.app[data-pre]");if(au){ev(pi&&pi+(rg?".appreg":".app"));copyText(P);toast("Opening "+au.dataset.app+" · prompt also copied");return}
 },true);
}
/* More toggles */
D.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest("[data-more]");if(!b)return;var o=b.getAttribute("aria-expanded")!=="true",p=D.getElementById(b.getAttribute("aria-controls"));b.setAttribute("aria-expanded",o?"true":"false");if(p)p.classList.toggle("open",o)});
/* /start: step 2 picks the client; step 3's main button always copies the prompt first, inside the click, then opens the app
   (prefilled where its link supports it) in the same gesture, so a popup blocker never fires and paste always works.
   Beacons as before: start.app / start.appreg for copy plus open, start.copy / start.copyreg for Copy prompt, mcp-poa.add for connectors. */
(function(){var go=$("[data-go]");if(!go)return;var card=go.closest("[data-pcard]"),fb=$("[data-gofb]",card),lb=$("[data-golbl]",go),ap=$(".gauto",go),L0="",T,nf=$("[data-name]",card),cpb=$("[data-gocopy]",card),fl=$("[data-gofail]",card);
 function sel(){return $("input[name=client]:checked",card)||$("input[name=client]",card)}
 function txt(){return W.poaTag(card,($(".pc-text",card).textContent||"").trim())}
 function say(m,ok){fb.textContent=m;fb.classList.toggle("ok",!!ok)}
 function url(r,P){var k=r.dataset.kind;if(k=="mcp")return r.dataset.href;var b=r.dataset.base,pre=r.dataset.pre;return pre?pre+encodeURIComponent(P):b||""}
 /* copy now: start navigator.clipboard.writeText, and also run the synchronous textarea copy in the same gesture, so the
    clipboard holds the text before the new tab takes focus. Returns a promise of success. */
 function copyNow(v){var sync=false,t=D.createElement("textarea");t.value=v;t.setAttribute("readonly","");t.style.cssText="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0";
  var p=null;try{if(navigator.clipboard&&W.isSecureContext)p=navigator.clipboard.writeText(v)}catch(_){p=null}
  D.body.appendChild(t);t.select();try{sync=D.execCommand("copy")}catch(_){}t.remove();
  if(sync)return Promise.resolve(true);return p?p.then(function(){return true},function(){return false}):Promise.resolve(false)}
 function fail(P){if(!fl)return;fl.hidden=false;var ta=$("textarea",fl);ta.value=P;ta.focus();ta.select();say("Select and copy this prompt")}
 /* name check, same rule as POASwap: 1 to 32 of A-Z a-z 0-9 _ -; anything else blocks steps 2 and 3 until fixed */
 var er=$("[data-nameerr]",card),more=$("[data-more]",card);
 function nameMsg(v){var a=Array.from(v);if(!a.length)return "Name your agent to continue.";var bad=[];a.forEach(function(c){if(!/[A-Za-z0-9_-]/.test(c)){var w=c===" "?"space":c==="."?"period":c;if(bad.indexOf(w)<0)bad.push(w)}});
  if(bad.length)return "Not allowed: "+(bad.length<2?bad[0]:bad.slice(0,-1).join(", ")+" and "+bad[bad.length-1])+". Use letters, numbers, _ or - (up to 32).";
  return a.length>32?"Too long: up to 32 characters.":""}
 /* taken check: POAScan's own archive (/api/v1/agents/name-available), debounced; a network error or timeout never blocks */
 var tk={v:null,taken:false},tT=null,tSeq=0,dflt=true,tries=0;
 function avail(v){var q=++tSeq,ac=W.AbortController?new AbortController():null,to=setTimeout(function(){if(ac)ac.abort()},3000);
  fetch("/api/v1/agents/name-available?name="+encodeURIComponent(v),{cache:"no-store",credentials:"omit",signal:ac?ac.signal:undefined}).then(function(r){return r.json()}).then(function(d){clearTimeout(to);
   if(q!==tSeq||(nf.value||"")!==v)return;   /* a newer name is being checked */
   if(d&&d.valid&&d.available===false){if(dflt&&tries<5&&W.poaNewName){tries++;setName(W.poaNewName(),true);return}tk={v:v,taken:true,sug:d.suggestion||""}}else tk={v:v,taken:false};
   if(check())setup()}).catch(function(){clearTimeout(to)})}
 function setName(v,isDefault){dflt=!!isDefault;nf.value=v;nf.dispatchEvent(new Event("input",{bubbles:true}));dflt=!!isDefault}
 function queue(){clearTimeout(tT);var v=nf.value||"";if(nameMsg(v))return;tT=setTimeout(function(){avail(v)},300)}
 function check(){if(!nf||!er)return true;var v=nf.value||"",m=nameMsg(v),sg="";if(!m&&tk.taken&&tk.v===v){m="Taken: "+v+" is already an agent. Try another.";sg=tk.sug}var bad=!!m;
  er.textContent=m;if(sg){var u=D.createElement("button");u.type="button";u.className="stuse";u.textContent="Use "+sg;u.addEventListener("click",function(){setName(sg,false);nf.focus()});er.appendChild(D.createTextNode(" "));er.appendChild(u)}er.hidden=!bad;nf.setAttribute("aria-invalid",bad?"true":"false");
  $$("input[name=client]",card).forEach(function(i){i.disabled=bad});if(more)more.disabled=bad;if(cpb)cpb.disabled=bad;
  go.classList.toggle("off",bad);if(bad){go.setAttribute("aria-disabled","true");go.setAttribute("tabindex","-1")}else{go.removeAttribute("aria-disabled");go.removeAttribute("tabindex")}
  card.classList.toggle("namebad",bad);return !bad}
 function setup(){var r=sel();if(!r)return;var k=r.dataset.kind,n=r.dataset.app,P=txt();go.dataset.kind=k;go.classList.remove("ok");if(fl)fl.hidden=true;
  var u=url(r,P);go.href=u||"#";if(k=="mcp"&&!r.dataset.web)go.removeAttribute("target");else go.target="_blank";
  clearTimeout(T);L0=k=="mcp"?["Add to "+n,"Add to "+n]:u?["Copy prompt and open "+n,"Copy and open "+n]:["Copy prompt for "+n,"Copy for "+n];lab(L0);if(ap)ap.hidden=k!="auto";say("")}
 /* feedback lives in the button: green, a short "Copied, opening X" (or "Copied"), then back to its label */
 function lab(a){var x=$(".gll",lb),y=$(".gls",lb);if(x)x.textContent=a[0];if(y)y.textContent=a[1]}   /* long label, and a short one for 390px; the nodes stay, only their text changes */
 function done(m){clearTimeout(T);go.classList.add("ok");lab([m,m]);if(ap)ap.hidden=true;say(m+". Paste with "+KEY+" if it is not filled in.",1);
  T=setTimeout(function(){go.classList.remove("ok");lab(L0);var r=sel();if(ap&&r)ap.hidden=r.dataset.kind!="auto"},2600)}
 card.addEventListener("change",function(e){if(e.target.name==="client")setup()});
 if(nf){nf.addEventListener("input",function(e){if(e.isTrusted)dflt=false;if(check())setup();queue()});nf.addEventListener("keydown",function(e){if(e.key==="Enter"){e.preventDefault();if(!check())return;var r=sel();if(r)r.focus()}})}
 card.addEventListener("keydown",function(e){var t=e.target;if(e.key==="Enter"&&t.name==="client"){e.preventDefault();t.checked=true;setup();go.focus()}});
 go.addEventListener("click",function(e){var r=sel();if(!r||!check()){e.preventDefault();return}var k=r.dataset.kind,n=r.dataset.app,P=txt(),rg=regOn($(".pc-text",card)),u=url(r,P);
  if(k=="mcp"){ev("mcp-poa.add");go.href=u;copyNow(r.dataset.mcpc).then(function(ok){if(ok)done("Copied, adding to "+n)});return}  /* app schemes open by the link itself */
  e.preventDefault();ev("start."+(rg?"appreg":"app"));
  var c=copyNow(P);   /* copy first, synchronously in this click */
  if(u)W.open(u,"_blank","noopener,noreferrer");   /* then open, still inside the same gesture */
  c.then(function(ok){if(ok)done(u?"Copied, opening "+n:"Copied");else fail(P)})});
 if(cpb)cpb.addEventListener("click",function(){if(!check())return;var r=sel(),n=r?r.dataset.app:"your app",P=txt(),rg=regOn($(".pc-text",card));ev("start."+(rg?"copyreg":"copy"));
  copyNow(P).then(function(ok){if(ok){cpb.classList.add("ok");var o=cpb.textContent;cpb.textContent="Copied";setTimeout(function(){cpb.classList.remove("ok");cpb.textContent=o},1800);say("Prompt copied",1)}else fail(P)})});
 check();setup();if(nf)queue()})();
/* /start close: back if we came from this site, else home */
var bk=$("[data-back]");if(bk){var goBack=function(){var r=D.referrer;try{if(r&&new URL(r).origin===location.origin&&history.length>1){history.back();return}}catch(_){}location.href="/"};
 bk.addEventListener("click",function(e){e.preventDefault();goBack()});
 D.addEventListener("keydown",function(e){if(e.key!=="Escape"||e.defaultPrevented||D.querySelector("dialog[open]")||D.body.classList.contains("navopen"))return;var t=e.target;if(t&&(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))return;goBack()},true)}
/* compact desktop search */
var sf=$(".search");if(sf){var si=$("input",sf),sb=$("button",sf);
 function compactS(){return si&&si.getBoundingClientRect().width<8&&!sf.classList.contains("open")}
 sb.addEventListener("click",function(e){if(compactS()){e.preventDefault();sf.classList.add("open");si.focus()}else if(sf.classList.contains("open")&&!si.value.trim()){e.preventDefault();sf.classList.remove("open")}});
 si.addEventListener("blur",function(){setTimeout(function(){if(!sf.contains(D.activeElement)&&!si.value.trim())sf.classList.remove("open")},120)});
 si.addEventListener("keydown",function(e){if(e.key==="Escape"){si.value="";sf.classList.remove("open");sb.focus()}})}

/* search typeahead: the "Find my agent" hint plus agent names (replaces /find) */
$$("form[role=search]").forEach(function(f){var inp=$("input",f),box=$(".sopts",f);if(!inp||!box)return;var t=null,seq=0,sel=-1;
 function pick(i){var a=$$("a",box);sel=Math.max(-1,Math.min(a.length-1,i));a.forEach(function(x,j){x.classList.toggle("on",j===sel);x.setAttribute("aria-selected",j===sel?"true":"false")})}
 inp.addEventListener("input",function(){clearTimeout(t);var q=inp.value.trim();if(q.length<2||/^(poa1|[0-9a-fA-F]{6,}$|[Ee]?\d+$)/.test(q)){box.innerHTML="";sel=-1;return}
  t=setTimeout(function(){var n=++seq;fetch("/fragment/suggest?q="+encodeURIComponent(q)).then(function(r){return r.json()}).then(function(xs){if(n!==seq)return;sel=-1;
   var esc=function(t){return String(t).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})};
   box.innerHTML=xs.filter(function(x){return /^poa1[1-9A-HJ-NP-Za-km-z]{20,60}$/.test(x.id)}).map(function(x){return '<a role="option" href="/address/'+esc(x.id)+'"><span class="idn" data-a="'+esc(x.id)+'"></span>'+esc(x.name)+'<small>'+esc(x.id.slice(0,6))+'…'+esc(x.id.slice(-4))+'</small></a>'}).join("");paintIds(box)}).catch(function(){})},180)});
 inp.addEventListener("keydown",function(e){var a=$$("a",box);if(!a.length)return;if(e.key==="ArrowDown"){e.preventDefault();pick(sel+1)}else if(e.key==="ArrowUp"){e.preventDefault();pick(sel-1)}else if(e.key==="Enter"&&sel>=0){e.preventDefault();location.href=a[sel].href}})});
/* narrow header bar: short placeholder (the hint below says what search takes) */
(function(){var i=$(".hdr .search input");if(!i)return;var full=i.placeholder;function fit(){i.placeholder=i.clientWidth&&i.clientWidth<240?"Search":full}fit();addEventListener("resize",fit)})();
if(location.hash==="#find"){var fi=$$(".hsearch input,.search input").filter(function(x){return x.offsetParent!==null})[0];if(fi){var fs=fi.closest("form");if(fs&&fs.classList.contains("search"))fs.classList.add("open");fi.focus()}}

/* ask your agent: shared prompt dialog */
var am=$("#askmodal");
if(am){var amP=$("#am-p",am),amT=$("#am-t",am),amC=$(".am-c",am),cur=[];
 function amSet(i){var x=cur[i];if(!x)return;amP.closest("[data-pcard]").dataset.pid=x[2]||"";amP.textContent=x[1];amT.textContent=x[0];amP.scrollTop=0;
  $$(".chip",amC).forEach(function(c,j){c.classList.toggle("on",j===i);c.setAttribute("aria-pressed",j===i?"true":"false")});
  $$("a[data-pre]",am).forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(x[1])})}
 D.addEventListener("click",function(e){var t=e.target;if(!t.closest)return;var b=t.closest("[data-ask]");
  if(b){e.preventDefault();try{cur=JSON.parse(b.dataset.ask)}catch(_){return}
   amC.innerHTML="";cur.forEach(function(x,i){var c=D.createElement("button");c.type="button";c.className="chip";c.textContent=x[0];c.addEventListener("click",function(){amSet(i)});amC.appendChild(c)});
   var mu=cur.length>1;amC.hidden=!mu;am.classList.toggle("multi",mu);amT.classList.toggle("sr-only",mu);amSet(0);ev(cur[0]&&cur[0][2]&&cur[0][2]+".open");if(am.showModal)am.showModal();else am.setAttribute("open","");D.documentElement.classList.add("jmlock");return}
  if(am.open&&(t===am||t.closest("[data-amclose]"))){if(am.close)am.close();else am.removeAttribute("open")}});
 am.addEventListener("close",function(){D.documentElement.classList.remove("jmlock")})}
/* sortable tables */
function sortables(){$$("table.sortable").forEach(function(tb){$$("th[data-sort]",tb).forEach(function(th,ci){th.tabIndex=0;th.setAttribute("role","button");
 function go(){var asc=th.dataset.dir!=="asc"&&th.dataset.dir!==undefined?true:th.dataset.dir==="desc";if(th.dataset.dir===undefined)asc=th.dataset.sort==="text";
  $$("th",tb).forEach(function(o){delete o.dataset.dir});th.dataset.dir=asc?"asc":"desc";
  var bd=tb.tBodies[0];$$(".xrow",bd).forEach(function(x){x.remove()});$$("tr.open",bd).forEach(function(r){r.classList.remove("open")});var rs=Array.prototype.slice.call(bd.rows),num=th.dataset.sort==="num";
  rs.sort(function(a,b){var x=a.cells[ci]&&a.cells[ci].dataset.v,y=b.cells[ci]&&b.cells[ci].dataset.v;if(num){x=parseFloat(x);y=parseFloat(y);x=isNaN(x)?-1e18:x;y=isNaN(y)?-1e18:y;return asc?x-y:y-x}
   x=(x||"").toLowerCase();y=(y||"").toLowerCase();return asc?(x<y?-1:x>y?1:0):(x<y?1:x>y?-1:0)});
  rs.forEach(function(r){bd.appendChild(r)})}
 th.addEventListener("click",go);th.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();go()}})})})}
/* priority columns at 390px: hidden cells open in a row below on tap or Enter */
function pris(root){$$("table.pri",root).forEach(function(tb){var hs=tb.tHead?Array.prototype.slice.call(tb.tHead.rows[0].cells):[];
 $$("tbody tr:not(.xrow)",tb).forEach(function(tr){if(tr.dataset.pl)return;tr.dataset.pl=1;var ps=$$("td.p",tr);if(ps.length&&ps.length<tr.cells.length){ps[ps.length-1].classList.add("pl");ps[ps.length-1].insertAdjacentHTML("beforeend",'<span class="xi" aria-hidden="true">+</span>')}});
 if(tb.dataset.pri)return;tb.dataset.pri=1;
 function tog(tr){if(!tr||tr.classList.contains("xrow")||!tr.querySelector("td.pl"))return;var nx=tr.nextElementSibling;
  var xi=tr.querySelector(".xi");if(nx&&nx.classList.contains("xrow")){nx.remove();tr.classList.remove("open");tr.setAttribute("aria-expanded","false");if(xi)xi.textContent="+";return}
  var dl="";hs.forEach(function(h,i){if(h.classList.contains("p")||!tr.cells[i])return;dl+="<div><dt>"+h.textContent.replace(/[↕↑↓]/g,"")+"</dt><dd>"+tr.cells[i].innerHTML+"</dd></div>"});
  var x=D.createElement("tr");x.className="xrow";x.innerHTML='<td colspan="'+hs.length+'"><dl>'+dl+"</dl></td>";tr.after(x);tr.classList.add("open");tr.setAttribute("aria-expanded","true");if(xi)xi.textContent="−";paintIds(x)}
 tb.addEventListener("click",function(e){if(innerWidth>640||e.target.closest("a,button,input,summary"))return;tog(e.target.closest("tbody tr"))});
 tb.addEventListener("keydown",function(e){if(innerWidth>640||(e.key!=="Enter"&&e.key!==" ")||e.target.closest("a,button"))return;var tr=e.target.closest("tbody tr");if(tr){e.preventDefault();tog(tr)}});
 function ti(){$$("tbody tr:not(.xrow)",tb).forEach(function(tr){if(innerWidth<=640&&tr.querySelector("td.pl"))tr.tabIndex=0;else tr.removeAttribute("tabindex")})}ti();addEventListener("resize",ti)})}
/* POA | USD toggle: converts .pc columns with the reference price in the toggle; the choice is remembered */
function sig(v,n){if(!v)return 0;var d=Math.pow(10,n-Math.ceil(Math.log10(Math.abs(v))));return Math.round(v*d)/d}
function money(v,n){v=sig(v,n);var u=[[1e9,"B"],[1e6,"M"],[1e3,"K"]];for(var i=0;i<3;i++)if(Math.abs(v)>=u[i][0])return "$"+(+(v/u[i][0]).toPrecision(n))+u[i][1];return "$"+(+v.toPrecision(n))}
function usdApply(on){$$(".utog").forEach(function(t){var px=+t.dataset.usd,n=+t.dataset.sig||3,cd=t.closest(".card")||D;
  $$("button",t).forEach(function(b){b.setAttribute("aria-pressed",String((b.dataset.u==="usd")===on))});
  $$("table",cd).forEach(function(tb){if(!tb.tHead)return;var idx=[];Array.prototype.forEach.call(tb.tHead.rows[0].cells,function(c,i){if(c.classList.contains("pc"))idx.push(i)});
   Array.prototype.forEach.call(tb.tBodies[0].rows,function(r){idx.forEach(function(i){var td=r.cells[i];if(!td)return;var nm=td.querySelector(".num");if(!nm)return;
    if(nm.dataset.poa===undefined){nm.dataset.poa=nm.textContent;var v=td.dataset.v!==undefined?parseFloat(td.dataset.v):parseFloat((nm.title||nm.textContent).replace(/[^0-9.\-]/g,""));nm.dataset.raw=isNaN(v)?"":v}
    var raw=nm.dataset.raw;nm.textContent=on&&raw!==""?"≈"+money(+raw*px,n):nm.dataset.poa;td.classList.toggle("inusd",on&&raw!=="")})})})})}
function usdInit(){if(!$(".utog"))return;var on=false;try{on=localStorage.getItem("poascan-units")==="usd"}catch(e){}
 $$(".utog button").forEach(function(b){b.addEventListener("click",function(){var u=b.dataset.u==="usd";try{localStorage.setItem("poascan-units",u?"usd":"poa")}catch(e){}usdApply(u)})});if(on)usdApply(true)}
/* old #txs / #grading links open the matching address tab */
(function(){if(!/^\/address\//.test(location.pathname)||/[?&]tab=/.test(location.search))return;var m={"#txs":"txs","#grading":"grading","#rewards":"rewards"}[location.hash];if(m)location.replace(location.pathname+"?tab="+m)})();
paintIds();times();charts();sortables();pris();usdInit();setInterval(tick,1000);tick();
/* Load more: appends the next keyset page to the card's table; the button carries the next cursor */
D.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest(".more-btn");if(!b||b.disabled)return;e.preventDefault();
 var tb=$("tbody",b.closest(".cb"));if(!tb)return;b.disabled=true;b.textContent="Loading";
 /* skeleton rows at the real row height hold the space while the page loads */
 var lr=$$("tr:not(.xrow)",tb).pop(),rh=lr?lr.offsetHeight:44,nc=lr?lr.cells.length:1,sk=[];
 for(var i=0;i<3;i++){var x=D.createElement("tr");x.className="skr";x.setAttribute("aria-hidden","true");x.innerHTML='<td colspan="'+nc+'"><i style="width:'+[88,72,80][i]+'%"></i></td>';x.style.height=rh+"px";tb.appendChild(x);sk.push(x)}
 function unsk(){sk.forEach(function(x){x.remove()})}
 fetch(b.dataset.more,{headers:{Accept:"application/json"}}).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(d){unsk();
  var t=D.createElement("tbody");t.innerHTML=d.html;while(t.firstChild){var r=t.firstChild;if(r.nodeType===1)r.classList.add("in");tb.appendChild(r)}paintIds(tb);times(tb);pris(tb.closest(".cb"));if($(".utog"))usdApply(usdOn());
  if(d.next){b.dataset.more=d.next;b.disabled=false;b.textContent="Load more"}else b.remove()})
 .catch(function(){unsk();b.disabled=false;b.textContent="Retry"})});
/* chart pop-out: a stat or chart card with a chart ([data-chart]) opens a larger chart in a dialog. Data from /fragment/chart
   (POAScan's own archive, chartpop.py). ?chart=<key>&range=<range> opens it on load; the range follows in the URL by
   replaceState and both params go on close. No entrance fade or transform: the dialog and its chart are visible from the first frame. */
/* chartq:begin (tools/chartpop_test.py runs cpParse and cpSearch in node) */
var CPK=["mined","supply","circ","agents","joins","holders","txs","answers"],CPR=["24h","7d","30d","all","epoch"];
function cpParse(search){var q;try{q=new URLSearchParams(search||"")}catch(e){return null}var c=q.getAll("chart"),r=q.getAll("range");
 if(c.length!==1||CPK.indexOf(c[0])<0)return null;return {c:c[0],r:r.length===1&&CPR.indexOf(r[0])>=0?r[0]:""}}
function cpSearch(search,c,r,keep){var q=new URLSearchParams(search||"");
 if(c&&CPK.indexOf(c)>=0){q.set("chart",c);if(r&&CPR.indexOf(r)>=0)q.set("range",r);else q.delete("range")}
 else{q.delete("chart");if(keep)q.set("range",keep);else q.delete("range")}
 var s=q.toString();return s?"?"+s:""}
/* chartq:end */
(function(){
 var CPT={mined:"Total mined",supply:"Supply",circ:"Circulating supply",agents:"Agents",joins:"Agents / hr",holders:"Holders",txs:"Txs / hour",answers:"Answers / epoch"},
  CPL={"24h":"24h","7d":"7d","30d":"30d",all:"All",epoch:"Epoch"},MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
  XSVG='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  pr0=new URLSearchParams(location.search).get("range"),KEEP=location.pathname==="/network"&&/^(24h|7d|all)$/.test(pr0||"")?pr0:null,
  cp=null,box,svgW=0,cur=null,data=null,opener=null,seq=0,geo=null,idx=-1,live,tip,xh,rng,ttl,now,lg,rT=0;
 function fv(v){if(v==null)return "···";var s=data&&data.fmt==="c"?c3(v):Math.round(v).toLocaleString("en-US");return data&&data.unit?s+" "+data.unit:s}
 function dtf(o,d){try{return new Intl.DateTimeFormat(undefined,o).format(d)}catch(e){return ""}}
 /* reader's local time plus UTC, like the rest of the site: "6:35 PM PT · 01:35Z"; a date on both sides past 24h */
 function when(ts,long){var d=new Date(ts*1000),o={hour:"numeric",minute:"2-digit",timeZoneName:"shortGeneric"};if(long){o.month="short";o.day="numeric"}
  var l=dtf(o,d);if(!l){o.timeZoneName="short";l=dtf(o,d)}var z=d.toISOString().slice(11,16)+"Z";
  if(long&&(d.getUTCDate()!==d.getDate()||d.getUTCMonth()!==d.getMonth()))z=MON[d.getUTCMonth()]+" "+d.getUTCDate()+" "+z;
  return l?l+" \u00b7 "+z:z}
 function build(){cp=D.createElement("dialog");cp.className="cpop";cp.setAttribute("aria-labelledby","cp-t");cp.setAttribute("aria-modal","true");
  cp.innerHTML='<div class="cp-in"><div class="cp-hd"><h2 id="cp-t"></h2><span class="cp-now num"></span><button type="button" class="jm-x cp-x" aria-label="Close" data-cpclose>'+XSVG+'</button></div>'
   +'<div class="chips cp-rng" role="group" aria-label="Range"></div><div class="chartbox cp-box" tabindex="0" role="group" aria-roledescription="chart"></div>'
   +'<div class="legend cp-lg" hidden></div><p class="sr-only" aria-live="polite"></p></div>';
  D.body.appendChild(cp);box=$(".cp-box",cp);rng=$(".cp-rng",cp);ttl=$("#cp-t",cp);now=$(".cp-now",cp);lg=$(".cp-lg",cp);live=$("p[aria-live]",cp);
  cp.addEventListener("cancel",function(e){e.preventDefault();close()});
  cp.addEventListener("close",closed);
  cp.addEventListener("click",function(e){if(e.target===cp||e.target.closest("[data-cpclose]"))close();var b=e.target.closest(".cp-rng button");if(b&&cur&&b.dataset.r!==cur.r)load(cur.c,b.dataset.r)});
  /* focus stays inside while open */
  cp.addEventListener("keydown",function(e){if(e.key!=="Tab")return;var f=$$("button,[tabindex='0']",cp).filter(function(x){return !x.disabled&&x.getClientRects().length});if(!f.length)return;
   var i=f.indexOf(D.activeElement);if(e.shiftKey&&i<=0){e.preventDefault();f[f.length-1].focus()}else if(!e.shiftKey&&(i<0||i===f.length-1)){e.preventDefault();f[0].focus()}});
  /* hover, touch scrub (the box takes the gesture: touch-action none) and arrow keys */
  function mv(e){if(!geo)return;var r=box.getBoundingClientRect();at(near(e.clientX-r.left),false)}
  box.addEventListener("pointermove",mv);
  box.addEventListener("pointerdown",function(e){if(e.pointerType!=="mouse"&&box.setPointerCapture)try{box.setPointerCapture(e.pointerId)}catch(_){}mv(e)});
  box.addEventListener("pointerleave",function(e){if(e.pointerType==="mouse")hide()});
  box.addEventListener("keydown",function(e){if(!geo)return;var n=geo.n,k=e.key,i=idx<0?n-1:idx;
   if(k==="ArrowLeft")i=Math.max(0,i-1);else if(k==="ArrowRight")i=Math.min(n-1,i+1);else if(k==="Home")i=0;else if(k==="End")i=n-1;else return;e.preventDefault();at(i,true)});
  box.addEventListener("blur",function(){if(idx>=0&&!box.matches(":hover"))hide()});
  W.addEventListener("resize",function(){if(!cp.open||!data)return;clearTimeout(rT);rT=setTimeout(function(){var w=box.clientWidth;if(Math.abs(w-svgW)>80)load(cur.c,cur.r);else draw()},150)})}
 function open(c,r,op){if(!cp)build();opener=op||D.activeElement;if(D.body.classList.contains("navopen")&&typeof navOpen==="function")navOpen(false);
  if(!cp.open){if(cp.showModal)cp.showModal();else cp.setAttribute("open","");D.documentElement.classList.add("jmlock")}
  var x=$(".cp-x",cp);try{x.focus({preventScroll:true,focusVisible:false})}catch(_){x.focus()}load(c,r)}
 function close(){if(!cp||!cp.hasAttribute("open"))return;if(cp.close)cp.close();else{cp.removeAttribute("open");closed()}}
 function closed(){D.documentElement.classList.remove("jmlock");seq++;cur=null;data=null;geo=null;
  try{history.replaceState(history.state,"",location.pathname+cpSearch(location.search,null,null,KEEP)+location.hash)}catch(_){}
  var o=opener;opener=null;if(o&&o.isConnected&&o.focus)try{o.focus({preventScroll:true})}catch(_){o.focus()}}
 function load(c,r){var n=++seq;cur={c:c,r:r||""};ttl.textContent=CPT[c]||"";now.textContent="";hide();geo=null;
  box.innerHTML='<div class="skel cskel" aria-busy="true"><i></i></div>';box.setAttribute("aria-label",CPT[c]||"Chart");
  var w=Math.max(200,Math.round(box.clientWidth||800));
  fetch("/fragment/chart?c="+encodeURIComponent(c)+(r?"&r="+encodeURIComponent(r):"")+"&w="+w,{credentials:"omit"}).then(function(x){if(!x.ok)throw 0;return x.json()}).then(function(d){
   if(n!==seq)return;data=d;cur.r=d.range;ttl.textContent=d.title;chips();draw();
   try{history.replaceState(history.state,"",location.pathname+cpSearch(location.search,c,d.range)+location.hash)}catch(_){}})
  .catch(function(){if(n!==seq)return;box.innerHTML='<div class="naBox">Chart did not load</div>'})}
 function chips(){rng.innerHTML="";data.ranges.forEach(function(k){var b=D.createElement("button");b.type="button";b.className="chip"+(k===data.range?" on":"");b.dataset.r=k;b.textContent=CPL[k]||k;b.setAttribute("aria-pressed",k===data.range?"true":"false");rng.appendChild(b)});
  rng.hidden=data.ranges.length<2}
 function esc2(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
 function draw(){var d=data;if(!d)return;var Wd=Math.max(200,Math.round(box.clientWidth)),H=Math.max(180,Math.round(box.clientHeight)),bars=d.kind==="bars",
   vals=bars?[].concat.apply([],d.bars.map(function(b){return b[2]})):d.pts.map(function(p){return p[1]});svgW=Wd;idx=-1;
  if(!vals.length||(!bars&&d.pts.length<2)){box.innerHTML='<div class="naBox">No data for this range yet</div>';geo=null;return}
  var lo=d.y0?0:Math.min.apply(null,vals),hi=Math.max.apply(null,vals);if(hi===lo)hi=lo+1;if(d.fmt!=="c"){lo=Math.floor(lo);hi=lo+4*Math.max(1,Math.ceil((hi-lo)/4))}   /* whole-number ticks for counts */
  var yl=[0,1,2,3,4].map(function(i){var v=lo+(hi-lo)*i/4;return d.fmt==="c"?c3(v):Math.round(v).toLocaleString("en-US")}),
   pl=Math.max(36,Math.max.apply(null,yl.map(function(s){return s.length}))*7.4+14),pr=12,pt=14,pb=26,mob=Wd<560,
   Y=function(v){return pt+(H-pt-pb)*(1-(v-lo)/(hi-lo))},o=[];
  o.push('<svg class="cpchart" viewBox="0 0 '+Wd+' '+H+'" width="'+Wd+'" height="'+H+'" aria-hidden="true"><defs><linearGradient id="cpg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+d.color+'" stop-opacity=".22"/><stop offset="1" stop-color="'+d.color+'" stop-opacity="0"/></linearGradient></defs>');
  for(var i=0;i<5;i++){var gy=Y(lo+(hi-lo)*i/4);o.push('<line x1="'+pl+'" x2="'+(Wd-pr)+'" y1="'+gy.toFixed(1)+'" y2="'+gy.toFixed(1)+'" class="grid"/><text x="'+(pl-8)+'" y="'+(gy+4).toFixed(1)+'" class="ax" text-anchor="end">'+yl[i]+'</text>')}
  if(bars){var n=d.bars.length,step=(Wd-pl-pr)/n,bw=Math.max(2,step*.62),k=d.bars[0][2].length,cols=d.colors.length?d.colors:[d.color],every=Math.max(1,Math.ceil(n/Math.max(1,Math.floor((Wd-pl)/(mob?44:56))))),cx=[];
   d.bars.forEach(function(b,j){var x=pl+step*j+(step-bw)/2,w2=bw/k;o.push('<g class="col">');b[2].forEach(function(v,m){var h=(H-pt-pb)*((v-lo)/(hi-lo));o.push('<rect x="'+(x+m*w2).toFixed(1)+'" y="'+(H-pb-h).toFixed(1)+'" width="'+w2.toFixed(1)+'" height="'+Math.max(0,h).toFixed(1)+'" fill="'+cols[m%cols.length]+'"/>')});o.push("</g>");
    cx.push(x+bw/2);if(j%every===0)o.push('<text x="'+(x+bw/2).toFixed(1)+'" y="'+(H-8)+'" class="ax" text-anchor="middle">'+esc2(b[0])+'</text>')});
   geo={n:n,x:cx,y:d.bars.map(function(b){return Y(Math.max.apply(null,b[2]))})};
   var lb=d.bars[n-1];now.textContent=d.legend.length?"":fv(lb[2][0]);
   lg.hidden=!d.legend.length;lg.innerHTML=d.legend.map(function(l,m){return '<span><i style="background:'+cols[m%cols.length]+'"></i>'+esc2(l)+'</span>'}).join("")}
  else{var P=d.pts,t0=P[0][0],t1=P[P.length-1][0],X=function(t){return pl+(Wd-pl-pr)*(t-t0)/((t1-t0)||1)},long=t1-t0>36*3600,
    pa=P.map(function(p,j){return (j?"L":"M")+X(p[0]).toFixed(1)+","+Y(p[1]).toFixed(1)}).join("");
   o.push('<path d="'+pa+"L"+X(t1).toFixed(1)+","+(H-pb)+"L"+X(t0).toFixed(1)+","+(H-pb)+'Z" fill="url(#cpg)"/>');
   /* upgrade milestones, grouped on the server with milestones.group at this plot width (the Network > Charts rule) */
   d.marks.forEach(function(m,j){var mx=X(m[0]),end=mx>Wd-pr-Math.min(180,m[1].length*7.2+8);
    o.push('<g class="mk"><title>'+esc2(m[2]||m[1])+'</title><line x1="'+mx.toFixed(1)+'" x2="'+mx.toFixed(1)+'" y1="'+pt+'" y2="'+(H-pb)+'"/><text x="'+(end?mx-4:mx+4).toFixed(1)+'" y="'+(H-pb-8-(j%2)*14)+'" class="ax mkl"'+(end?' text-anchor="end"':'')+'>'+esc2(m[1])+'</text></g>')});
   o.push('<path d="'+pa+'" fill="none" stroke="'+d.color+'" stroke-width="2" stroke-linejoin="round"/>');
   var nt=Math.max(2,Math.min(7,Math.floor((Wd-pl)/(long?96:110))));
   for(i=0;i<nt;i++){var tt=t0+(t1-t0)*i/(nt-1),dd=new Date(tt*1000),lab=long?dtf({month:"short",day:"numeric"},dd)+" "+dtf({hour:"numeric"},dd).replace(/\s/g,"").toLowerCase():dtf({hour:"numeric",minute:"2-digit"},dd);
    o.push('<text x="'+X(tt).toFixed(1)+'" y="'+(H-8)+'" class="ax" text-anchor="'+(i===0?"start":i===nt-1?"end":"middle")+'">'+esc2(lab)+'</text>')}
   geo={n:P.length,x:P.map(function(p){return X(p[0])}),y:P.map(function(p){return Y(p[1])}),long:long};now.textContent=fv(P[P.length-1][1]);lg.hidden=true}
  o.push('<circle class="cp-dot" r="4" cx="-20" cy="-20" fill="'+d.color+'"/></svg>');
  box.innerHTML=o.join("")+'<i class="xh"></i><div class="xt" aria-hidden="true"></div>';xh=$(".xh",box);tip=$(".xt",box);
  box.setAttribute("aria-label",d.title+", "+(CPL[d.range]||d.range)+". Arrow keys read values.")}
 function near(px){var x=geo.x,lo2=0,hi2=x.length-1;while(hi2-lo2>1){var m=(lo2+hi2)>>1;if(x[m]<px)lo2=m;else hi2=m}return Math.abs(x[lo2]-px)<=Math.abs(x[hi2]-px)?lo2:hi2}
 function at(i,say){if(!geo||!data)return;idx=i;var px=geo.x[i],t,s,sep=svgW<560?"\n":" \u00b7 ";
  if(data.kind==="bars"){var b=data.bars[i];s=b[0]+" \u00b7 "+(data.legend.length?b[2].map(function(v,m){return data.legend[m]+" "+fv(v)}).join(" \u00b7 "):fv(b[2][0]))+sep+when(b[1],true);
   $$(".col",box).forEach(function(g,j){g.classList.toggle("on",j===i)});box.classList.add("bh")}
  else{var p=data.pts[i];s=fv(p[1])+sep+when(p[0],geo.long);var dot=$(".cp-dot",box);dot.setAttribute("cx",px.toFixed(1));dot.setAttribute("cy",geo.y[i].toFixed(1))}
  tip.textContent=s;xh.style.left=px+"px";var w=tip.offsetWidth/2,bw=box.clientWidth;tip.style.left=Math.max(w+4,Math.min(bw-w-4,px))+"px";box.classList.add("hov");if(say)live.textContent=s.replace("\n"," \u00b7 ")}
 function hide(){idx=-1;if(box){box.classList.remove("hov","bh");$$(".col.on",box).forEach(function(g){g.classList.remove("on")});var dot=box&&$(".cp-dot",box);if(dot){dot.setAttribute("cx","-20");dot.setAttribute("cy","-20")}}}
 /* openers: any [data-chart] (a stat card is a role=button, a chart card body or its Expand button); links inside keep working */
 D.addEventListener("click",function(e){var t=e.target.closest&&e.target.closest("[data-chart]");if(!t||CPK.indexOf(t.dataset.chart)<0||(cp&&cp.contains(t)))return;
  var a=e.target.closest("a,button,input,summary,select,textarea");if(a&&a!==t&&t.contains(a))return;e.preventDefault();open(t.dataset.chart,t.dataset.chartRange||"",t)});
 D.addEventListener("keydown",function(e){if(e.key!=="Enter"&&e.key!==" ")return;var t=e.target;if(!t||!t.matches||!t.matches(".cpt[data-chart]"))return;e.preventDefault();open(t.dataset.chart,"",t)});
 var q0=cpParse(location.search);if(q0)open(q0.c,q0.r,$('[data-chart="'+q0.c+'"]'));
})();
if(wantLive)connect();
})();
/* one "Ask agent" label per page: later Ask buttons keep the icon, title and aria-label */
(function(){var b=[].slice.call(document.querySelectorAll(".askb"));b.slice(1).forEach(function(x){x.classList.add("ico")})})();
/* charts marked .end (the upgrade milestones on Supply) open scrolled to the newest end where 390px makes them scroll */
(function(){[].slice.call(document.querySelectorAll(".chartbox.end")).forEach(function(b){b.scrollLeft=b.scrollWidth})})();
