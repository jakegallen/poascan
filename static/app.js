/* POAScan client: live updates over /ws (fallback: polling), countdown ring, identicons, charts, copy, nav. No deps. */
(function(){
"use strict";
var D=document,W=window,RM=W.matchMedia&&W.matchMedia("(prefers-reduced-motion: reduce)").matches;
function $(s,r){return (r||D).querySelector(s)}function $$(s,r){return Array.prototype.slice.call((r||D).querySelectorAll(s))}
function pad(n){return n<10?"0"+n:""+n}
function utc(ts){var d=new Date(ts*1000);return d.getUTCFullYear()+"-"+pad(d.getUTCMonth()+1)+"-"+pad(d.getUTCDate())+" "+pad(d.getUTCHours())+":"+pad(d.getUTCMinutes())+" UTC"}
function rel(ts){var s=Math.max(0,Math.floor(Date.now()/1000-ts));return s<10?"just now":s<60?Math.floor(s/10)*10+"s ago":s<3600?Math.floor(s/60)+"m ago":s<86400?Math.floor(s/3600)+"h "+Math.floor(s%3600/60)+"m ago":Math.floor(s/86400)+"d ago"}
function dur(s){s=Math.max(0,Math.floor(s));return s>=3600?Math.floor(s/3600)+"h "+pad(Math.floor(s%3600/60))+"m":Math.floor(s/60)+"m "+pad(s%60)+"s"}
function compact(v,d){var a=Math.abs(v),u=[[1e9,"B"],[1e6,"M"],[1e3,"K"]];for(var i=0;i<3;i++)if(a>=u[i][0])return (v/u[i][0]).toFixed(d)+u[i][1];return Math.round(v).toLocaleString("en-US")}
function c3(v){var a=Math.abs(v),u=[[1e9,"B"],[1e6,"M"],[1e3,"K"]];for(var i=0;i<3;i++)if(a>=u[i][0]*0.9995){var x=v/u[i][0],d=Math.abs(x)<9.995?2:Math.abs(x)<99.95?1:0;if(Math.abs(+x.toFixed(d))>=1000&&i>0){x=v/u[i-1][0];return x.toFixed(2)+u[i-1][1]}return x.toFixed(d)+u[i][1]}return Math.round(v).toLocaleString("en-US")}
var FMT={int:function(v){return Math.round(v).toLocaleString("en-US")},c2:function(v){return c3(v)},c1:function(v){return c3(v)},p1:function(v){return v.toFixed(1)+"%"}};

/* times */
function upts(root){$$("time[data-upts]",root).forEach(function(t){var ts=+t.dataset.upts;if(!ts||t.dataset.done==ts)return;var d=new Date(ts*1000),z=d.toISOString().slice(11,16)+"Z",l="";
  try{l=ltf(ts,"dt")+" "+tzn()}catch(e){}
  t.textContent=l.trim()?l.trim():z;t.title=ltf(ts,"dt",1);t.dataset.done=ts})}
/* 1.26.122 visitor-local times: one formatter for every displayed time. The server sends <time class="lt" datetime=ISO UTC
   data-f=kind> with UTC text (the no-JS fallback); here it reads in the browser's zone and hour cycle ("Oct 25, 8:48 AM"),
   the year only when it is not this year. Headers that name the zone carry .tzn ("Time (PDT)"); titles hold the full time. */
var LTY=new Date().getFullYear(),TZN=null;
function ltf(ts,f,full){var d=new Date(ts*1000),o={};if(f!=="t"){o.month="short";o.day="numeric";if(full||d.getFullYear()!==LTY)o.year="numeric"}
 if(f!=="d"){o.hour="numeric";o.minute="2-digit";if(f==="dts")o.second="2-digit"}if(full)o.timeZoneName="short";
 try{return new Intl.DateTimeFormat(undefined,o).format(d)}catch(e){return utc(ts)}}
function tzn(){if(TZN!==null)return TZN;TZN="";try{var p=new Intl.DateTimeFormat(undefined,{timeZoneName:"short"}).formatToParts(new Date());for(var i=0;i<p.length;i++)if(p[i].type==="timeZoneName")TZN=p[i].value}catch(e){}return TZN}
function ltt(s){return s.replace(/\{t:(\d+)(?::(\w+))?\}/g,function(_,ts,f){return ltf(+ts,f||"dt")}).replace(/ \(UTC\)$/,"")}
function lt(root){pheat(root);$$("time.lt",root).forEach(function(t){var ts=+t.dataset.ts;if(!ts||t.dataset.lz==ts)return;t.textContent=ltf(ts,t.dataset.f||"dt");t.dataset.lz=ts});
 var z=tzn();if(z)$$(".tzn",root).forEach(function(s){s.textContent=z});
 $$("[data-ltt]",root).forEach(function(e){e.title=ltt(e.dataset.ltt);e.removeAttribute("data-ltt")});
 $$("[data-lts]",root).forEach(function(e){e.textContent=ltf(+e.dataset.lts,e.dataset.f||"dt");e.removeAttribute("data-lts")});
 $$("[title*=' UTC']",root).forEach(function(e){e.title=ltx(e.title)})}
/* the Agent activity map (profile.py activity): the server draws UTC days and hours and ships the counts in 15 minute UTC slots
   (data-q "slot:n"). Here they are rebucketed by the visitor's own hours and days, so half and quarter hour zones land right, and
   the header and label name the zone. Same five steps of gold as the server. */
function pstep(n,mx){return !n?0:mx>1?1+Math.min(3,Math.floor(4*(n-1)/mx)):4}
function pbucket(q0,days,dq,t){var st=[],g={},mx=0,i;
  for(i=0;i<=days;i++)st.push(new Date(t.getFullYear(),t.getMonth(),t.getDate()-(days-1)+i).getTime()/1000);
  dq.split(" ").forEach(function(p){var k=p.split(":"),ts=q0+(+k[0])*900,n=+k[1];if(!n||ts<st[0]||ts>=st[days])return;
   for(var d=0;d<days&&ts>=st[d+1];d++);var key=d*24+new Date(ts*1000).getHours();g[key]=(g[key]||0)+n;if(g[key]>mx)mx=g[key]});
  return {st:st,g:g,mx:mx}}
function pheat(root){$$(".pheat[data-q]",root).forEach(function(el){if(el.dataset.lz)return;el.dataset.lz="1";
  var days=+el.dataset.days||7,B=pbucket(+el.dataset.q0,days,el.dataset.q,new Date()),st=B.st,g=B.g,mx=B.mx,i,h;
  var o="";for(i=0;i<days;i++){var ds=new Date(st[i]*1000),day=ltf(st[i],"d");o+='<div class="phr"><span>'+day+'</span>';
   for(h=0;h<24;h++){var n=g[i*24+h]||0,cs=new Date(ds.getFullYear(),ds.getMonth(),ds.getDate(),h).getTime()/1000;
    o+='<i class="l'+pstep(n,mx)+'" title="'+ltf(cs,"dt")+": "+n+" tx"+(n===1?"":"s")+'"></i>'}o+="</div>"}
  var ax=$(".phax",el);$$(".phr",el).forEach(function(r){r.remove()});el.insertAdjacentHTML("afterbegin",o);if(ax)el.appendChild(ax);
  var z=tzn()||"local";el.setAttribute("aria-label","Txs by hour, last "+days+" days, "+z);
  var c=el.closest(".card"),lb=c&&$(".phz",c);if(lb)lb.textContent=z})}
/* a dated UTC time inside hover text ("Oct 25, 15:48 UTC", ui.utc_text) reads local too; a bare "15:48 UTC" has no date and stays */
var LTMON="JanFebMarAprMayJunJulAugSepOctNovDec";
function ltx(s){return s.replace(/\b([A-Z][a-z]{2}) (\d{1,2})(?:, (\d{4}))?, (\d{2}):(\d{2})(?::(\d{2}))? UTC\b/g,function(m,mo,d,y,h,mi,se){var k=LTMON.indexOf(mo);if(k<0||k%3)return m;
 var ts=Date.UTC(y?+y:new Date().getUTCFullYear(),k/3,+d,+h,+mi,se?+se:0)/1000;if(!y&&ts>Date.now()/1000+40*86400)ts=Date.UTC(new Date().getUTCFullYear()-1,k/3,+d,+h,+mi,se?+se:0)/1000;return ltf(ts,se?"dts":"dt")})}
function times(root){upts(root);lt(root);$$("time.t",root).forEach(function(t){var ts=+t.dataset.ts;if(!ts)return;if(!t.title)t.title=ltf(ts,t.dataset.f==="dts"?"dts":"dt",1);if(t.classList.contains("rel"))t.textContent=rel(ts)})}

/* hex identicons: deterministic from the address */
function h32(s,seed){var h=seed>>>0;for(var i=0;i<s.length;i++){h=Math.imul(h^s.charCodeAt(i),16777619)>>>0}return h}
var PAL=["#FFB000","#E3A33A","#C8742B","#FFD36B","#8FA3B8","#4FC59A","#6B5420","#272219","#F6F0E2"];   /* style.css tokens */
function identicon(a){var h1=h32(a,2166136261),h2=h32(a,374761393),c=[];for(var i=0;i<6;i++){var k=((i<3?h1>>>(i*5):h2>>>((i-3)*5))&31)%PAL.length;c.push(PAL[k])}
 var P=[[12,1.5],[21.1,6.75],[21.1,17.25],[12,22.5],[2.9,17.25],[2.9,6.75]],cx=12,cy=12,o="";
 var inner=(h2>>>20)%3;
 for(i=0;i<6;i++){var p=P[i],q=P[(i+1)%6];o+='<path d="M'+cx+' '+cy+'L'+p[0]+' '+p[1]+'L'+q[0]+' '+q[1]+'Z" fill="'+c[i]+'" fill-opacity="'+(0.55+((h1>>>i)&1)*0.45)+'"/>'}
 o+='<path d="M12 1.5 21.1 6.75v10.5L12 22.5 2.9 17.25V6.75z" fill="none" stroke="#100E0A" stroke-width="1.2"/>';
 if(inner)o+='<path d="M12 7.5 15.9 9.75v4.5L12 16.5 8.1 14.25v-4.5z" fill="#100E0A" fill-opacity="'+(inner==1?.85:.4)+'"/>';
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
 $$(".bezel[data-close]").forEach(function(z){var s=+z.dataset.start,e=+z.dataset.close;if(!s||!e)return;var f=Math.min(1,Math.max(0,(now-s)/(e-s))),L=z.querySelectorAll("line"),n=L.length;
  for(var i=0;i<n;i++){var on=i/(n-1)<=f;if(L[i].classList.contains("on")!==on)L[i].classList.toggle("on",on)}
  if(z._k!==s+":"+e){z._k=s+":"+e;var T=z.querySelectorAll(".bez-ax time");if(T.length===2){T[0].dataset.ts=s;T[1].dataset.ts=e}}   /* the axis follows a new epoch */
  var w=z.querySelector(".bzw");if(w){var o=+w.style.getPropertyValue("--f");if(f<o-.01){w.classList.add("bzrs");setTimeout(function(){w.classList.remove("bzrs")},900)}w.style.setProperty("--f",f.toFixed(5))}});
 $$(".vessel[data-close]").forEach(function(v){var s=+v.dataset.start,e=+v.dataset.close;if(!s||!e)return;var f=Math.min(1,Math.max(0,(now-s)/(e-s)));
  var m=v.querySelector(".molten"),t=v.querySelector(".vp");if(m)m.style.width=(f*100).toFixed(2)+"%";if(t)t.textContent=Math.floor(f*100)+"%"});
 if(BM.on)benchTick(now);times()}

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
  if(BM.on&&n.closest(".bench")){if(n.classList.contains("bn"))benchFlip(n,FMT.int(old),FMT.int(val));else benchNum(n,key,old,val,f);return}
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

/* the Bench strip (bench.py): marks sit at x = ts - b in a 1440 s wide viewBox. Every 5 s the group slides left with time; a new tx in
   the snapshot refetches the window (/fragment/score, cached 10 s), at most once per 20 s. Marks newer than what we had fade in. */
var SC={top:null,t:0,busy:0,max:0,tm:0};
function scoreSlide(){var now=Date.now()/1000;$$("#score .lane").forEach(function(l){var sk=$(".sk",l);if(sk){sealSlide(l,sk,now);return}var g=$(".mk",l);if(!g)return;var tx=+g.dataset.b-(now-1440),n=0;
  g.setAttribute("transform","translate("+tx.toFixed(1)+" 0)");$$("line",g).forEach(function(m){var x=+m.getAttribute("x1")+tx;if(x<-60)m.remove();else if(x>=0)n++});g._tx=tx;
  var c=$(".c",l);if(c&&odv(c)!==String(n))laneCount(c,n)})}
/* the Seals lane (bench.py seal_clusters, the same algorithm): seals come in bursts, so neighbours closer than their widths plus 4 px
   merge into one capsule with a count at their weighted centre, reclustered at the lane's real width (and on resize). The newest is
   held inside the now line. Hover, or tap on touch, shows the count and the times in the visitor's zone. */
function sealW(n){return n===1?6:12+6*String(n).length}
function sealCluster(ts,pxs,right,left){var st=[],i,a,b,n;ts=ts.slice().sort(function(x,y){return x-y});
  for(i=0;i<ts.length;i++){st.push([ts[i],1,ts[i],ts[i]]);
   while(st.length>1){b=st[st.length-1];a=st[st.length-2];if((b[0]-a[0])*pxs>=(sealW(b[1])+sealW(a[1]))/2+4)break;st.pop();n=a[1]+b[1];st[st.length-1]=[(a[0]*a[1]+b[0]*b[1])/n,n,Math.min(a[2],b[2]),Math.max(a[3],b[3])]}}
  if(right!=null&&st.length){var lim=right-(sealW(st[st.length-1][1])/2+1)/pxs;for(i=st.length-1;i>=0;i--){if(st[i][0]<=lim)break;st[i][0]=lim;if(i)lim-=((sealW(st[i][1])+sealW(st[i-1][1]))/2+4)/pxs}}
  if(left!=null&&st.length){lim=left+(sealW(st[0][1])/2+1)/pxs;for(i=0;i<st.length;i++){if(st[i][0]>=lim)break;st[i][0]=lim;if(i+1<st.length)lim+=((sealW(st[i][1])+sealW(st[i+1][1]))/2+4)/pxs}}
  return st}
function sealTs(sk){if(!sk._s){var b=+sk.dataset.b,o=[];(sk.dataset.s||"").split(" ").forEach(function(p){if(!p)return;var q=p.split("*"),k=q[1]?+q[1]:1;for(var j=0;j<k;j++)o.push(b+(+q[0]))});sk._s=o}return sk._s}
function sealDraw(sk,old){var w=sk.parentNode.clientWidth;if(!w)return;sk._w=w;var b=+sk.dataset.b,h="";
  /* epoch tips: only seals inside the window, the oldest held inside its start, so the capsules add up to the lane total */
  var now=Date.now()/1000,lo=now-1440,inw=sealTs(sk).filter(function(t){return t>=lo});sk._n=inw.length;sk._d=1;sealCluster(inw,w/1440,now,lo).forEach(function(c){var nw=(old&&c[3]>old&&!RM?" nw":"")+((c[0]-(now-1440))*w/1440<sealW(c[1])/2?" out":"");
   h+='<i class="sm'+(c[1]===1?" s1":"")+nw+'" style="left:'+(100*(c[0]-b)/1440).toFixed(2)+'%" data-x="'+c[0].toFixed(1)+'" data-n="'+c[1]+'" data-t0="'+c[2]+'" data-t1="'+c[3]+'">'+(c[1]>1?c[1]:"")+'</i>'});
  sk.innerHTML=h;sealSlide(sk.closest(".lane"),sk,now);sk._d=0}
function sealSlide(l,sk,now){if(!sk._w)sealDraw(sk);sk._p=null;sk.style.transform="translateX("+(100*(+sk.dataset.b-(now-1440))/1440).toFixed(3)+"%)";
  var w=sk._w||0;$$(".sm",sk).forEach(function(m){var o=(+m.dataset.x-(now-1440))*w/1440<sealW(+m.dataset.n)/2;if(m.classList.contains("out")!==o){m.classList.toggle("out",o);if(o&&STIP&&STIP._m===m)sealUntip()}});   /* a mark leaves whole at the window's start */
  var n=0,ot=0;sealTs(sk).forEach(function(t){if(t>=now-1440)n++});$$(".sm.out",sk).forEach(function(){ot++});
  if(!sk._d&&sk._w&&(n!==sk._n||ot)){if(STIP&&STIP._m&&sk.contains(STIP._m))sealUntip();sealDraw(sk);return}   /* a seal left the window or a capsule reached its start: recluster */
  var c=$(".c",l);if(c&&odv(c)!==String(n))laneCount(c,n)}
function sealHms(ts){try{return new Intl.DateTimeFormat(undefined,{hour:"numeric",minute:"2-digit",second:"2-digit"}).format(new Date(ts*1000))}catch(e){return utc(ts)}}
var STIP=null;
function sealTip(m,pin){var sc=$("#score");if(!sc)return;if(!STIP){STIP=D.createElement("div");STIP.className="stip";STIP.setAttribute("aria-hidden","true");sc.appendChild(STIP)}
  var n=+m.dataset.n,t0=+m.dataset.t0,t1=+m.dataset.t1;STIP.textContent=(n===1?"Seal":n+" Seals")+" · "+sealHms(t0)+(t1>t0?" to "+sealHms(t1):"");
  var r=sc.getBoundingClientRect(),q=m.getBoundingClientRect(),tw=STIP.offsetWidth,th=STIP.offsetHeight;
  STIP.style.left=Math.max(0,Math.min(r.width-tw,q.left+q.width/2-r.left-tw/2)).toFixed(0)+"px";STIP.style.top=(q.top-r.top-th-8).toFixed(0)+"px";
  if(STIP._m&&STIP._m!==m)STIP._m.classList.remove("on");STIP._m=m;STIP._pin=!!pin;m.classList.add("on");STIP.classList.add("on")}
function sealUntip(){if(!STIP)return;STIP.classList.remove("on");if(STIP._m)STIP._m.classList.remove("on");STIP._m=null;STIP._pin=false}
D.addEventListener("pointerover",function(e){var m=e.target.closest&&e.target.closest("#score .sm");if(m&&e.pointerType==="mouse")sealTip(m)});
D.addEventListener("pointerout",function(e){var m=e.target.closest&&e.target.closest("#score .sm");if(m&&STIP&&!STIP._pin&&!(e.relatedTarget&&m.contains(e.relatedTarget)))sealUntip()});
D.addEventListener("click",function(e){var m=e.target.closest&&e.target.closest("#score .sm");if(m){if(STIP&&STIP._pin&&STIP._m===m)sealUntip();else sealTip(m,1);return}if(STIP&&STIP._m)sealUntip()});
var sealRT=0;W.addEventListener("resize",function(){clearTimeout(sealRT);sealRT=setTimeout(function(){sealUntip();$$("#score .sk").forEach(function(sk){if(sk.parentNode.clientWidth!==sk._w)sealDraw(sk)})},150)});
function scoreMark(r,b,nw){var x=r[1]-b,k=r[0],c=nw?" nw":"";if(k==="a")return '<line class="ma'+(r[3]?" f":"")+c+'" x1="'+x+'" x2="'+x+'" y1="12" y2="40"/>';
  if(k==="t"){var h=6+30*Math.min(1,Math.log(r[2]+1)/Math.log(51));return '<line class="mt'+c+'" x1="'+x+'" x2="'+x+'" y1="'+(26-h/2).toFixed(1)+'" y2="'+(26+h/2).toFixed(1)+'"/>'}
  return '<line class="ms'+c+'" x1="'+x+'" x2="'+x+'" y1="23" y2="29"/>'}
function scoreFetch(){SC.busy=1;SC.t=Date.now();fetch("/fragment/score",{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(d){SC.busy=0;scoreIngest(d)}).catch(function(){SC.busy=0})}
function scoreIngest(d){var old=SC.max,ks={};if(old&&!RM)d.rows.forEach(function(r){if(r[1]>old)ks[r[0]]=1});$$("#score .lane").forEach(function(l){var k=l.dataset.k,sk=$(".sk",l);if(sk){sk._s=d.rows.filter(function(r){return r[0]===k}).map(function(r){return r[1]});sk.dataset.b=d.b;sealUntip();sealDraw(sk,old);return}
   var g=$(".mk",l);if(!g)return;var h="";
   d.rows.forEach(function(r){if(r[0]===k)h+=scoreMark(r,d.b,old&&r[1]>old&&!RM)});g.dataset.b=d.b;g.innerHTML=h});
  d.rows.forEach(function(r){if(r[1]>SC.max)SC.max=r[1]});scoreSlide();benchSpark(ks)}
/* the Pour: when a snapshot shows a new close, the card fetches its body, the pool bar starts whole and splits into minted gold and
   burned slag (600 ms), and the new close's hallmark draws in as its row lands in Closes (CSS, 1.2 s in all). */
function pourLive(s){var p=$("#pour");if(!p||!s.last||s.last.epoch==null||String(s.last.epoch)===p.dataset.ep||p._busy)return;p._busy=1;
  fetch("/fragment/pour",{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(h){var t=D.createElement("div");t.innerHTML=h;var n=t.firstElementChild;if(!n)throw 0;
   var m=$(".pm",n),w=m?m.style.width:"";if(m&&!RM){m.style.width="100%"}p.replaceWith(n);
   var hd=n.closest(".card")&&$(".cx .lbl",n.closest(".card"));if(hd&&s.last.epoch!=null){hd.textContent="Epoch "+s.last.epoch;hd.setAttribute("href","/epoch/"+s.last.epoch)}
   if(m&&!RM)requestAnimationFrame(function(){requestAnimationFrame(function(){m.style.width=w})})}).catch(function(){p._busy=0})}
function scoreLive(s){if(!$("#score")||!s.feed||BM.demo)return;var top=(s.feed.match(/data-id="([^"]+)"/)||[])[1];if(!top||top===SC.top)return;SC.top=top;
  if(!SC.max){$$("#score line.ma,#score line.mt").forEach(function(m){var g=m.parentNode,t=+m.getAttribute("x1")+(+g.dataset.b);if(t>SC.max)SC.max=t});
   $$("#score .sk").forEach(function(sk){sealTs(sk).forEach(function(t){if(t>SC.max)SC.max=t})})}
  var w=20000-(Date.now()-SC.t);if(SC.busy)return;if(w>0){clearTimeout(SC.tm);SC.tm=setTimeout(scoreFetch,w);return}scoreFetch()}

/* 1.26.145 Bench motion (bench.py): the strip drifts with the clock, new marks slide in at the now line with a short glow,
   Answers, Graders, Pool and the lane counts roll digit by digit with a +N chip, the bezel head glides to now and the last
   minute ticks each second, a close flips the numeral and slides a one line summary into the ticker, and the ticker cycles the
   latest txs from the snapshot feed. Every number comes from the snapshot and /fragment/score the page already polls, so this
   adds no requests. Transforms and opacity only; one requestAnimationFrame loop that stops while the tab is hidden. Reduced
   motion keeps the static Bench: values change in place, nothing slides, pulses or cycles. */
var BM={on:!!$(".bench #score"),demo:D.documentElement.dataset.demo==="motion",raf:0,live:0,items:[],seen:{},cur:-1,next:0,hold:0,pend:null,lead:0,lk:null};
function escH(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return c==="&"?"&amp;":c==="<"?"&lt;":c===">"?"&gt;":"&quot;"})}
/* odometer: each changed digit rolls, the old one up and out, the new one up and in, rightmost first */
/* epoch tips: mid roll the text holds the outgoing digits too ("6523" for 653), so a second update reads the value it is heading to */
function odv(n){return n._v!=null&&$(".od",n)?n._v:n.textContent}
function odo(n,t){var o=odv(n);if(o===t)return;n._v=t;if(RM||D.hidden){clearTimeout(n._ot);n.textContent=t;return}
 var h="",k=0,d=o.length-t.length;for(var i=t.length-1;i>=0;i--){var c=t.charAt(i),oc=o.charAt(i+d)||"";
  if(c===oc||!/[0-9]/.test(c))h=esc(c)+h;else{h='<span class="od" style="--d:'+(k*55)+'ms">'+(oc&&/[0-9]/.test(oc)?'<span class="o" aria-hidden="true">'+oc+"</span>":"")+"<span>"+c+"</span></span>"+h;k++}}
 n.innerHTML=h;clearTimeout(n._ot);n._ot=setTimeout(function(){if(n.textContent!==t||$(".od",n))n.textContent=t},620+k*55)}
/* +N chip: beside the number when it fits in its cell, else on the label row; fades out on its own */
function bump(n,txt,lane){if(RM||D.hidden||!BM.live)return;var host=lane||n.parentNode,c=D.createElement("i");c.className="bump";c.textContent=txt;c.setAttribute("aria-hidden","true");
 var old=$(".bump",host);if(old)old.remove();host.appendChild(c);
 if(!lane){var x=n.offsetLeft+n.offsetWidth+8,sm=n.nextElementSibling;if(sm&&sm.tagName==="SMALL")x=sm.offsetLeft+sm.offsetWidth+8;
  if(x+c.offsetWidth<=host.clientWidth){c.style.left=x+"px";c.style.top=(n.offsetTop+(n.offsetHeight-c.offsetHeight)/2).toFixed(0)+"px"}else{c.style.right="0";c.style.top="0"}}
 c.addEventListener("animationend",function(){c.remove()})}
/* Answers, Graders and Pool: an int climbs through its steps (at most 6, 90 ms apart), a compact value rolls once */
function benchNum(n,key,old,val,f){var fm=FMT[f]||FMT.int;clearInterval(n._tw);
 if(val>old)bump(n,"+"+(f==="int"?Math.round(val-old).toLocaleString("en-US"):c3(val-old)));
 if(f!=="int"||RM||D.hidden||val<old||val-old<2){odo(n,fm(val));return}
 var st=Math.min(6,val-old),i=0;n._tw=setInterval(function(){i++;odo(n,fm(i>=st?val:Math.round(old+(val-old)*i/st)));if(i>=st)clearInterval(n._tw)},90)}
/* the numeral flips at a close */
function benchFlip(n,o,v){if(RM||D.hidden){n.textContent=v;return}
 n.innerHTML='<span class="flp"><span class="fo">'+escH(o)+'</span><span class="fi">'+escH(v)+"</span></span>";clearTimeout(n._ft);n._ft=setTimeout(function(){n.textContent=v},1100);
 var b=n.closest(".bench");if(b){b.classList.remove("bclose");void b.offsetWidth;b.classList.add("bclose");setTimeout(function(){b.classList.remove("bclose")},1900)}}
/* lane totals */
function laneCount(c,n,k){var o=+odv(c)||0;if(o===n)return;if(n<o){clearTimeout(c._ot);c._v=String(n);c.textContent=c._v;return}odo(c,String(n));bump(c,"+"+(n-o),c.parentNode)}
/* the drift: mark groups follow the clock every frame they would move a quarter pixel or more */
function benchFrame(){BM.raf=0;if(D.hidden||RM)return;var now=Date.now()/1000;
 $$("#score .lane").forEach(function(l){var g=l._g||(l._g=$(".mk",l)),sk=l._sk||(l._sk=$(".sk",l)),w=l._w||(l._w=(l.querySelector("svg")||l).clientWidth||1);
  if(g){var tx=+g.dataset.b-(now-1440);if(g._tx==null||Math.abs(tx-g._tx)*w/1440>=.25){g.setAttribute("transform","translate("+tx.toFixed(2)+" 0)");g._tx=tx}}
  if(sk){var p=100*(+sk.dataset.b-(now-1440))/1440;if(sk._p==null||Math.abs(p-sk._p)*w/100>=.25){sk.style.transform="translateX("+p.toFixed(3)+"%)";sk._p=p}}});
 BM.raf=requestAnimationFrame(benchFrame)}
function benchGo(){if(BM.on&&!RM&&!BM.raf&&!D.hidden)BM.raf=requestAnimationFrame(benchFrame)}
function benchSize(){var sc=$("#score");if(!sc)return;$$("#score .lane").forEach(function(l){l._w=0;l._g=0;l._sk=0;var g=$(".mk",l);if(g)g._tx=null;var sk=$(".sk",l);if(sk)sk._p=null});
 var s=$("#score .lane svg");if(s&&s.clientWidth)sc.style.setProperty("--u",(1440/s.clientWidth).toFixed(3))}
/* a short flare at the now line of each lane that just got a mark */
function benchSpark(ks){if(RM||D.hidden)return;Object.keys(ks).forEach(function(k){var l=$('#score .lane[data-k="'+k+'"]');if(!l)return;var s=D.createElement("i");s.className="lspk";s.setAttribute("aria-hidden","true");l.appendChild(s);s.addEventListener("animationend",function(){s.remove()})})}
/* the ticker: one line, the newest tx first, then the latest few in turn every 3.2 s (1.4 s while new ones queue) */
var TKV={ANSWER:["answered","a"],ATTEST:["attested","t"],GRADE:["sealed a grade","s"],JOIN:["joined","j"]};
function tkAgo(ts){var d=Math.max(0,Math.floor(Date.now()/1000-ts));return d<60?d+"s ago":d<3600?Math.floor(d/60)+"m ago":d<86400?Math.floor(d/3600)+"h ago":Math.floor(d/86400)+"d ago"}
function tkHtml(it){var who=escH(it.n||(it.a?it.a.slice(0,6)+"\u2026"+it.a.slice(-4):"An Agent"));
 var nm=it.a?'<a class="tkn" href="https://minepoa.com/lableak/#/u/'+encodeURIComponent(it.a)+'" target="_blank" rel="noopener noreferrer" title="LabLeak profile">'+who+"</a>":'<span class="tkn">'+who+"</span>";
 return '<i class="sw '+it.k+'"></i>'+nm+" "+it.v+' <time class="tkt" data-ts="'+it.ts+'">'+tkAgo(it.ts)+"</time>"}
function tkFeed(html){if(!html)return[];var t=D.createElement("div");t.innerHTML=html;return $$(".frow",t).map(function(r){var bd=$(".badge",r),v=TKV[bd?bd.textContent.trim():""];if(!v)return null;
  var ad=$("a.addr",r),a=ad?ad.getAttribute("title")||"":"",nm=$(".aname,.fname",r),tm=$("time[data-ts]",r),ts=tm?+tm.dataset.ts:0;
  return {key:v[1]+":"+a+":"+ts,k:v[1],v:v[0],a:a,n:nm?nm.textContent.trim():"",ts:ts}}).filter(Boolean)}
function tkShow(html,cls,ts){var box=$("#btk");if(!box)return;BM.sts=ts||0;var old=$$(".tki",box),el=D.createElement("span");el.className="tki"+(cls?" "+cls:"");el.innerHTML=html;
 if(RM||D.hidden){old.forEach(function(o){o.remove()});el.classList.add("on");box.appendChild(el);times(el);tkTimes();return}
 box.appendChild(el);void el.offsetWidth;el.classList.add("on");tkTimes();
 old.forEach(function(o){o.classList.remove("on");o.classList.add("out");setTimeout(function(){o.remove()},520)})}
function tkTimes(){$$("#btk time.tkt").forEach(function(t){var ts=+t.dataset.ts;if(!ts)return;var x=tkAgo(ts);if(t.textContent!==x)t.textContent=x;if(!t.title)t.title=ltf(ts,"dts",1)})}
function tkIngest(list){var fresh=[];list.forEach(function(it){if(BM.seen[it.key])return;BM.seen[it.key]=1;fresh.push(it)});if(!fresh.length)return;
 BM.items=fresh.concat(BM.items).sort(function(a,b){return b.ts-a.ts}).slice(0,8);
 var top=BM.items[0],t=Date.now();if(t<BM.hold){BM.lead=1;return}   /* the close summary keeps the line; the newest leads once it ends */
 if(BM.live||(BM.sts!=null&&top.ts-BM.sts>60))tkLead(t)}   /* a new tx leads at once; a stale line (a cached page) gives way too */
/* the newest tx takes the line and holds it 6 s; older ones rotate only while nothing new comes in */
function tkLead(t){var top=BM.items[0];BM.lead=0;if(top&&BM.lk!==top.key){BM.cur=0;BM.next=t+6000;BM.lk=top.key;tkShow(tkHtml(top),"",top.ts)}}
function tkStep(){if(!$("#btk")||D.hidden)return;var t=Date.now();if(RM){if(BM.hold&&t>=BM.hold&&BM.items[0]){BM.hold=0;BM.lead=0;BM.lk=BM.items[0].key;tkShow(tkHtml(BM.items[0]),"",BM.items[0].ts)}return}
 if(t<BM.hold||t<BM.next)return;if(BM.lead)return tkLead(t);
 var n=Math.min(5,BM.items.length);if(n<2){BM.next=t+3200;return}BM.cur=(BM.cur+1)%n;var it=BM.items[BM.cur];BM.next=t+3200;BM.lk=it.key;
 tkShow(tkHtml(it),"",it.ts)}
/* a close: the summary takes the ticker for 7 s, then the line returns to live txs */
function benchClose(oe,ne,ans,last){var st=last&&last.epoch===oe&&last.settled!=null?last.settled:null,
  txt='<i class="sw a"></i><a class="tkn" href="/epoch/'+escH(oe)+'">Epoch '+escH(oe)+" closed</a>, "+(st!=null?Math.round(st).toLocaleString("en-US")+" answers settled":ans!=null?Math.round(ans).toLocaleString("en-US")+" answers in":"settling now");
 tkShow(txt,"tks");BM.hold=Date.now()+7000;BM.next=BM.hold;BM.lk=null;BM.lead=1}
function benchTick(now){var c=$(".bench .cd[data-close]");if(!c)return;var b=c.closest(".bench"),e=+c.dataset.close,left=e-now,fin=e&&left>0&&left<=60;
 b.classList.toggle("final",!!fin);b.classList.toggle("closing",!!(e&&left<=0&&left>-1800));if(e&&left<=0&&left>-1800)c.textContent="Closing";
 if(fin&&!RM){var a=c.classList.contains("ta");c.classList.toggle("ta",!a);c.classList.toggle("tb",a)}else c.classList.remove("ta","tb");
 tkTimes();tkStep()}
function benchInit(){if(!BM.on)return;benchSize();
 $$("#btk .tki").forEach(function(s,i){var a=$("a.tkn",s),h=a?a.getAttribute("href")||"":"",ad=decodeURIComponent(h.split("/u/")[1]||""),tm=$("time",s),k=($(".sw",s)||{className:""}).className.split(" ")[1]||"a",v=[];
  for(var x in TKV)if(TKV[x][1]===k)v=TKV[x];if(!tm)return;var it={key:k+":"+ad+":"+tm.dataset.ts,k:k,v:v[0],a:ad,n:a?a.textContent:"",ts:+tm.dataset.ts};BM.seen[it.key]=1;BM.items.push(it);if(i)s.remove()});
 BM.cur=0;BM.next=Date.now()+3200;BM.sts=BM.items.length?BM.items[0].ts:null;BM.lk=BM.items.length?BM.items[0].key:null;tkTimes();
 var rt=0;W.addEventListener("resize",function(){clearTimeout(rt);rt=setTimeout(benchSize,150)});
 D.addEventListener("visibilitychange",function(){if(!D.hidden){benchSize();scoreSlide();tick();benchGo()}});
 setTimeout(function(){BM.live=1},1500);benchGo()}

/* apply a snapshot (from WS or polling) */
function apply(s){if(!s||s.t&&s.t!=="snap")return;
 var p=$("#livepill");if(p){var f=s.pill||{state:s.live?"live":"stale",label:s.live?"Live":"Stale",why:""};p.className="pill "+f.state;p.hidden=f.state=="up";if(f.href)p.setAttribute("href",f.href);p.title=f.state=="live"?"Status":(f.why||f.label);var l=p.querySelector("span");if(l)l.textContent=f.label}
 var ud=$("#updot");if(ud&&s.pill)ud.hidden=s.pill.state!="up";
 var ul=$("[data-upline]");if(ul&&s.upline!=null){if(s.upline&&ul.innerHTML!==s.upline)ul.innerHTML=s.upline;ul.parentNode.hidden=!s.upline}
 var us=$("[data-upstamp]");if(us&&s.upstamp){var ot=$("time",us);if(!ot||ot.dataset.upts!==(s.upstamp.match(/data-upts="(\d+)"/)||[])[1]){us.innerHTML=s.upstamp;upts(us)}}
 var uv=$("[data-upview]");if(uv&&s.upsig&&s.upsig!==uv.dataset.sig&&!uv._busy){uv._busy=1;fetch("/fragment/upgrade",{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(h){var t=D.createElement("div");t.innerHTML=h;var nv=t.firstElementChild;if(nv){uv.replaceWith(nv);times(nv)}}).catch(function(){uv._busy=0})}
 if(s.routes)$$("[data-hroute]").forEach(function(li){var v=s.routes[li.dataset.hroute];if(!v)return;var t=$(".tag",li);if(!t)return;li.dataset.st=v;t.className="tag "+(v=="open"||v=="responding"?"ok":v=="paused"?"warn":v=="slow"?"warn slow":"");t.textContent=v=="open"?"Open":v=="responding"?"Responding":v=="paused"?"Paused":v=="slow"?"Slow":"Not read yet"});
 if(BM.on&&s.nums&&s.nums.epoch&&prev.epoch!=null&&s.nums.epoch[0]>prev.epoch)benchClose(prev.epoch,s.nums.epoch[0],prev.answers,s.last);
 if(s.nums)Object.keys(s.nums).forEach(function(k){setNum(k,s.nums[k][0],s.nums[k][1])});
 if(s.cards)Object.keys(s.cards).forEach(function(k){var el=$('.sv[data-live="'+k+'"]');if(!el)return;var tmp=D.createElement("div");tmp.innerHTML=s.cards[k];var nv=$(".sv",tmp);if(!nv)return;if(nv.innerHTML!==el.innerHTML)el.innerHTML=nv.innerHTML;el.className=nv.className;var st=nv.getAttribute("style");if(st)el.setAttribute("style",st);else el.removeAttribute("style")});
 if(s.epoch){$$(".ring,.vessel[data-close],.bezel").forEach(function(r){if(s.epoch.start)r.dataset.start=s.epoch.start;if(s.epoch.close)r.dataset.close=s.epoch.close});
  $$(".cd[data-close]").forEach(function(c){if(s.epoch.close)c.dataset.close=s.epoch.close});
  var be=$('[data-live="bm_ep"]');if(be&&s.epoch.n!=null)be.textContent=s.epoch.n}
 if(s.frags)Object.keys(s.frags).forEach(function(id){var el=D.getElementById(id);if(el&&el.dataset.h!==String(s.frags[id].length+":"+s.frags[id].slice(-40))){el.innerHTML=s.frags[id];el.dataset.h=s.frags[id].length+":"+s.frags[id].slice(-40);paintIds(el);times(el);tick()}});
 var bq=$(".bench");if(bq)bq.classList.toggle("quiet",s.live===false);
 mergeFeed(s.feed);setTicker(s.ticker);liveRows(s);scoreLive(s);if(BM.on)tkIngest(tkFeed(s.feed));pourLive(s)}

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
  var xh=D.createElement("i"),xt=D.createElement("div"),xd=D.createElement("i");xh.className="xh";xt.className="xt";xd.className="xd";b.appendChild(xh);b.appendChild(xt);b.appendChild(xd);var on=null;
  /* one chart spec (1.26.119): the SVG is stretched to its plot box, so x and y scale separately; a dot marks the hovered point */
  function move(e){var r=svg.getBoundingClientRect(),br=b.getBoundingClientRect(),vb=svg.viewBox.baseVal,sx=r.width/vb.width,sy=r.height/vb.height,x=(e.clientX-r.left)/sx,best=null,bd=1e9;
   items.forEach(function(it){var d=Math.abs(+it.dataset.cx-x);if(d<bd){bd=d;best=it}});if(!best)return;
   if(on!==best){if(on)on.classList.remove("on");best.classList.add("on");on=best;var q=best.dataset;xt.textContent=q.ts?(q.tf==="t"?ltf(+q.ts,"t"):ltf(+q.ts,"dt"))+" \u00b7 "+q.tv:q.tip}
   var px=+best.dataset.cx*sx+(r.left-br.left)+b.scrollLeft,top=r.top-br.top;xh.style.left=px+"px";xh.style.top=top+"px";xh.style.height=r.height+"px";xt.style.top=(top+4)+"px";
   if(best.dataset.cy!=null&&!best.classList.contains("col")){xd.style.display="";xd.style.left=px+"px";xd.style.top=(top+(+best.dataset.cy)*sy)+"px"}else xd.style.display="none";
   var w=xt.offsetWidth/2,bw=b.clientWidth+b.scrollLeft;xt.style.left=Math.max(w+b.scrollLeft,Math.min(bw-w,px))+"px";b.classList.add("hov")}
  b.addEventListener("pointermove",move);b.addEventListener("pointerdown",move);
  b.addEventListener("pointerleave",function(){b.classList.remove("hov");if(on)on.classList.remove("on");on=null})})}

/* prompt cards ([data-pcard]): Copy, Open in, toast */
var toastEl=$("#toast"),toastT;
var KEY=/Mac|iPhone|iPad/.test(navigator.platform||navigator.userAgent)?"⌘V":"Ctrl+V";
function toast(m,big,href,lt){if(!toastEl)return;var am0=D.getElementById("askmodal"),host=(am0&&am0.open)?am0:D.body;if(toastEl.parentNode!==host)host.appendChild(toastEl);toastEl.textContent=m;if(href&&/^https:\/\//.test(href)){var la=D.createElement("a");la.href=href;la.target="_blank";la.rel="noopener noreferrer";la.textContent=lt||href;toastEl.appendChild(D.createTextNode(" "));toastEl.appendChild(la)}toastEl.classList.toggle("big",!!big);toastEl.classList.remove("on");void toastEl.offsetWidth;toastEl.classList.add("on");clearTimeout(toastT);toastT=setTimeout(function(){toastEl.classList.remove("on")},big?7000:2600)}
/* Prompt button counts: a fixed id only ('<card>.<action>'), first-party POST /ops/e, no cookie and nothing about the visitor. The server takes ids from its allowlist and drops the rest. */
function ev(id){if(!id)return;try{var b=JSON.stringify({e:id});if(navigator.sendBeacon&&navigator.sendBeacon("/ops/e",b))return;fetch("/ops/e",{method:"POST",body:b,keepalive:true,credentials:"omit"}).catch(function(){})}catch(_){}}
function pidOf(el){var c=el&&el.closest&&el.closest("[data-pid]");return c?c.dataset.pid:""}
function regOn(pre){return !!(pre&&pre.dataset.regOn==="1")}
function copyText(v){function fb(){var t=D.createElement("textarea");t.value=v;t.setAttribute("readonly","");t.style.cssText="position:fixed;opacity:0;top:0;left:0";(D.querySelector("dialog[open]")||D.body).appendChild(t);t.select();var ok=false;try{ok=D.execCommand("copy")}catch(_){}t.remove();return ok}
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
 R=function(a){return a[Math.floor(Math.random()*a.length)]},gen=function(){return R(A)+"-"+R(N)+"-"+(100+Math.floor(Math.random()*900))},nm=gen(),RX=/(register\?label=)[^\s`]*/;W.poaNewName=gen;
 function fill(pre,v){if(pre&&RX.test(pre.textContent))pre.textContent=pre.textContent.replace(RX,"$1"+v)}
 function hrefs(c,t){$$("a[data-pre]",c).forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(t)})}
 W.poaName=nm;
 var f=$("[data-name]");if(!f)return;var card=f.closest("[data-pcard]"),pre=card&&$(".pc-text",card);
 function upd(){var v=f.value||"";if(!/^[A-Za-z0-9_-]{1,32}$/.test(v))return;W.poaName=v;fill(pre,v);hrefs(card,(pre.textContent||"").trim())}   /* never strips: an invalid name is shown as an error on /start and changes nothing */
 f.value=nm;upd();f.addEventListener("input",upd)})();
/* prompt v2.3 to v2.4 check-ins (v2.5 has none and no data-checkin, so this returns the text unchanged): on /start the copied text carries the picked client's tag in the two check-in URLs
   (data-checkin base + data-tag + "/"); everything else stays byte for byte. Elsewhere the text is untagged. */
W.poaTag=function(c,t){var b=c&&c.dataset&&c.dataset.checkin,r=b&&$("input[type=radio]:checked",c),g=r&&r.dataset.tag;return b&&g&&/^[a-z0-9-]{1,24}$/.test(g)?t.split(b).join(b+g+"/"):t};
/* 1.26.86: the Join dialog is gone (the header Start goes to /start); an old /#join link lands on /start. */
if(W.location.hash==="#join")location.replace("/start");W.addEventListener("hashchange",function(){if(W.location.hash==="#join")location.href="/start"});
(function(){
 function PF(el){var c=el&&el.closest&&el.closest("[data-pcard]");return c?W.poaTag(c,($(".pc-text",c).textContent||"").trim()):""}
 $$("[data-pcard] a[data-pre]").forEach(function(a){a.href=a.dataset.pre+encodeURIComponent(PF(a))});
 D.addEventListener("click",function(e){var t=e.target;if(!t.closest)return;
  var inCard=t.closest("[data-pcard]");if(!inCard)return;
  var P=PF(t),pc=inCard,pi=pc.dataset.pid||pidOf(pc),rg=regOn($(".pc-text",inCard));
  var cb=t.closest("[data-copy-prompt]");if(cb){ev(pi&&pi+(rg?".copyreg":".copy"));copyText(P).then(function(ok){cb.classList.remove("ok");void cb.offsetWidth;cb.classList.add("ok");var lb=$(".cpt",cb)||cb,o=cb.dataset.l||(cb.dataset.l=lb.textContent);lb.textContent=ok?"Copied":"Select & copy";setTimeout(function(){cb.classList.remove("ok");lb.textContent=o},1600);if(!ok){var r=D.createRange();r.selectNodeContents($(".pc-text",inCard));var sl=W.getSelection();sl.removeAllRanges();sl.addRange(r)}});return}
  var co=t.closest("[data-cpopen]");if(co){ev(pi&&pi+(rg?".appreg":".app"));var u=co.dataset.cpopen,n=co.dataset.app,pre=co.dataset.pre,pr=copyText(P),ua=navigator.userAgent||"",ios=co.dataset.ios&&(/iPhone|iPad|iPod/.test(ua)||(/Macintosh/.test(ua)&&navigator.maxTouchPoints>1)),and=co.dataset.android&&/Android/.test(ua);if(pre)u=pre+encodeURIComponent(P);if(ios){pr.then(function(ok){toast(ok?co.dataset.iosmsg:"Copy the prompt above, then paste it into Muse from Meta",1,co.dataset.ios,"App Store")});return}if(and)u=co.dataset.android;if(u)W.open(u,"_blank","noopener,noreferrer");pr.then(function(ok){co.classList.remove("ok");void co.offsetWidth;co.classList.add("ok");setTimeout(function(){co.classList.remove("ok")},1600);toast(ok?"Prompt copied · paste it into "+(u?"the new "+n+" chat":n)+" ("+KEY+") and send":"Copy the prompt above, then paste it into "+n,1)});return}
  var au=t.closest("a.app[data-pre]");if(au){ev(pi&&pi+(rg?".appreg":".app"));copyText(P);toast("Opening "+au.dataset.app+" · prompt also copied");return}
 },true);
})();
/* More toggles */
D.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest("[data-more]");if(!b)return;var o=b.getAttribute("aria-expanded")!=="true",p=D.getElementById(b.getAttribute("aria-controls"));b.setAttribute("aria-expanded",o?"true":"false");if(p)p.classList.toggle("open",o)});
/* /start step 3 (one button): step 2 picks the client; step 3 is one button that always copies the prompt
   first, inside the click. Auto apps (the link carries the prompt): one click copies and opens, in the same gesture, so a
   popup blocker never fires. Paste apps: the first click copies and the button turns into "Copied. Open X"; the second opens.
   No open URL (Grok Bot, Codex): one click copies, "Copied. Paste it into X". A connector app adds one small text link.
   Beacons: <pid>.app / .appreg for copy plus open, <pid>.copy / .copyreg for a copy alone, <pid>.add for the connector link,
   mcp-poa.add for the connector options under More. The second click of a paste app copies again but sends no beacon. */
function goInit(go){var card=go.closest("[data-pcard]");if(!card||go.dataset.goOn)return;go.dataset.goOn="1";var PID=card.dataset.pid||"start",RN=card.dataset.rname||"client",
 dlg=card.closest("dialog"),fb=$("[data-gofb]",card),lb=$("[data-golbl]",go),ap=$(".gauto",go),L0=["",""],I0="a",T,ARM=false,nf=$("[data-name]",card),fl=$("[data-gofail]",card);
 /* v2.4: one prompt variant per client tier (full, chat-browse, connector) from the page's templates; a no-path client (tier none) gets the panel instead of a prompt. */
 var TPL={},pv=$(".pc-text",card),crow=$("[data-conrow]",card),con=$("[data-gocon]",card),clb=$("[data-conlbl]",card),grow=$("[data-gorow]",card),np=$("[data-nopath]",card),stk=$("[data-stkey]",card),stv=$("[data-stview]",card),C0="",CT;
 $$("pre[data-variant]").forEach(function(p){TPL[p.dataset.variant]=p.textContent});
 function nameV(){return nf?nf.value||"":W.poaName||""}
 function render(r){var t=TPL[r.dataset.tier],v=nameV();if(t&&pv&&/^[A-Za-z0-9_-]{1,32}$/.test(v))pv.textContent=t.split("{NAME}").join(v)}
 function hide(el,h){if(el)el.hidden=!!h}
 function radios(){return $$("input[name='"+RN+"']",card)}
 function sel(){return $("input[name='"+RN+"']:checked",card)||radios()[0]}
 function txt(){return W.poaTag(card,($(".pc-text",card).textContent||"").trim())}
 function say(m,ok){if(!fb)return;fb.textContent=m;fb.classList.toggle("ok",!!ok)}
 function url(r,P){var k=r.dataset.kind;if(k=="mcp")return r.dataset.href;var b=r.dataset.base,pre=r.dataset.pre;return pre?pre+encodeURIComponent(P):b||""}
 /* copy now: start navigator.clipboard.writeText, and also run the synchronous textarea copy in the same gesture, so the
    clipboard holds the text before the new tab takes focus. Inside the dialog the textarea goes into the dialog (the rest
    of the page is inert). Returns a promise of success. */
 function copyNow(v){var sync=false,t=D.createElement("textarea");t.value=v;t.setAttribute("readonly","");t.style.cssText="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0";
  var p=null;try{if(navigator.clipboard&&W.isSecureContext)p=navigator.clipboard.writeText(v)}catch(_){p=null}
  (dlg||D.body).appendChild(t);t.select();try{sync=D.execCommand("copy")}catch(_){}t.remove();
  if(sync)return Promise.resolve(true);return p?p.then(function(){return true},function(){return false}):Promise.resolve(false)}
 function fail(P){if(!fl)return;fl.hidden=false;var ta=$("textarea",fl);ta.value=P;ta.focus();ta.select();say("Select and copy this prompt")}
 /* name check (/start only), same rule as POASwap: 1 to 32 of A-Z a-z 0-9 _ -; anything else blocks steps 2 and 3 until fixed */
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
 function off(el,bad){if(!el)return;el.classList.toggle("off",bad);if(bad){el.setAttribute("aria-disabled","true");el.setAttribute("tabindex","-1")}else{el.removeAttribute("aria-disabled");el.removeAttribute("tabindex")}}
 function check(){if(!nf||!er)return true;var v=nf.value||"",m=nameMsg(v),sg="";if(!m&&tk.taken&&tk.v===v){m="Taken: "+v+" is already an agent. Try another.";sg=tk.sug}var bad=!!m;
  er.textContent=m;if(sg){var u=D.createElement("button");u.type="button";u.className="stuse";u.textContent="Use "+sg;u.addEventListener("click",function(){setName(sg,false);nf.focus()});er.appendChild(D.createTextNode(" "));er.appendChild(u)}er.hidden=!bad;nf.setAttribute("aria-invalid",bad?"true":"false");
  radios().forEach(function(i){i.disabled=bad});if(more)more.disabled=bad;off(go,bad);off(con,bad);
  card.classList.toggle("namebad",bad);return !bad}
 /* the button: label (long, and a short one for 390px; the nodes stay, only their text changes) and one icon: a arrow, c copy, k check */
 function lab(a){var x=$(".gll",lb),y=$(".gls",lb);if(x)x.textContent=a[0];if(y)y.textContent=a[1]}
 function icon(i){$$("[data-gi]",go).forEach(function(s){s.hidden=s.dataset.gi!==i})}
 function rest(){var r=sel();clearTimeout(T);ARM=false;go.classList.remove("ok");lab(L0);icon(I0);if(ap)ap.hidden=!(r&&r.dataset.kind=="auto")}
 function setup(){var r=sel();if(!r)return;var tier=r.dataset.tier||"full",none=tier=="none",n=r.dataset.app,k=r.dataset.kind;render(r);
  var cl=r.dataset.cset?"Or add the PoA connector to "+n:r.dataset.ccopy?"Or copy the "+n+" connector command":"";
  hide(grow,none);hide(np,!none);hide(stk,none);hide(stv,none);hide(crow,none||!cl||k=="mcp");if(fl)fl.hidden=true;say("");if(none)return;
  clearTimeout(CT);C0=cl;if(clb)clb.textContent=cl;if(con){con.classList.remove("ok");con.href=r.dataset.cset||"#"}
  var P=txt(),u=url(r,P);go.dataset.kind=k;go.href=u||"#";if(k=="mcp"&&!r.dataset.web)go.removeAttribute("target");else go.target="_blank";
  L0=k=="mcp"?["Add to "+n,"Add to "+n]:k=="auto"?["Copy prompt and open "+n,"Copy and open "+n]:["Copy prompt for "+n,"Copy for "+n];I0=k=="mcp"||k=="auto"?"a":"c";rest()}
 function flash(m,i){clearTimeout(T);go.classList.add("ok");lab([m,m]);icon(i||"k");if(ap)ap.hidden=true;T=setTimeout(rest,2600)}
 card.addEventListener("change",function(e){if(e.target.name===RN)setup()});
 card.addEventListener("poa:refresh",function(){setup()});
 if(nf){nf.addEventListener("input",function(e){if(e.isTrusted)dflt=false;if(check())setup();queue()});nf.addEventListener("keydown",function(e){if(e.key==="Enter"){e.preventDefault();if(!check())return;var r=sel();if(r)r.focus()}})}
 card.addEventListener("keydown",function(e){var t=e.target;if(e.key==="Enter"&&t.name===RN){e.preventDefault();t.checked=true;setup();go.focus()}});
 go.addEventListener("click",function(e){var r=sel();if(!r||!check()){e.preventDefault();return}var k=r.dataset.kind,n=r.dataset.app,P=txt(),rg=regOn($(".pc-text",card)),u=url(r,P);
  if(k=="mcp"){ev("mcp-poa.add");go.href=u;copyNow(r.dataset.mcpc).then(function(ok){if(ok)flash("Copied. Adding to "+n)});return}  /* app schemes open by the link itself */
  e.preventDefault();
  if(k=="auto"){ev(PID+"."+(rg?"appreg":"app"));var c=copyNow(P);if(u)W.open(u,"_blank","noopener,noreferrer");c.then(function(ok){if(ok)flash("Copied. Opening "+n);else fail(P)});return}
  if(ARM&&u){copyNow(P);W.open(u,"_blank","noopener,noreferrer");flash("Opening "+n,"a");return}   /* second click: open (the prompt is copied again) */
  ev(PID+"."+(rg?"copyreg":"copy"));
  copyNow(P).then(function(ok){if(!ok){fail(P);return}
   if(u){clearTimeout(T);ARM=true;go.classList.add("ok");lab(["Copied. Open "+n,"Copied. Open "+n]);icon("k");say("Prompt copied. Open "+n+" and paste with "+KEY+".",1)}
   else{flash("Copied. Paste it into "+n);say("Prompt copied. Paste it into "+n+" with "+KEY+".",1)}})});
 if(con)con.addEventListener("click",function(e){e.preventDefault();var r=sel();if(!r||!check())return;var n=r.dataset.app,u=r.dataset.cset,v=r.dataset.ccopy||"";ev(PID+".add");
  var c=copyNow(v);if(u)W.open(u,"_blank","noopener,noreferrer");
  c.then(function(ok){if(!ok){fail(v);return}clearTimeout(CT);con.classList.add("ok");if(clb)clb.textContent=u?"Connector URL copied. Opening "+n:"Connector command copied";
   CT=setTimeout(function(){con.classList.remove("ok");if(clb)clb.textContent=C0},2600)})});
 if(np)np.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest("[data-pick]");if(!b)return;
  var r=radios().filter(function(i){return i.value===b.dataset.pick})[0];if(!r)return;
  var mp=r.closest(".morep");if(mp&&!mp.classList.contains("open")){var t=$("[data-more][aria-controls='"+mp.id+"']",card);if(t)t.click()}
  r.checked=true;setup();go.focus()});
 check();setup();if(nf)queue()}
$$("[data-go]").forEach(goInit);
/* v2.7 prompt hash: the button copies the full template sha256 (also in its title) and says Copied for a moment */
D.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest("[data-phash]");if(!b)return;var s=$("code",b),o=s.textContent;
 copyText(b.dataset.phash).then(function(ok){b.classList.add("ok");s.textContent=ok?"copied":b.dataset.phash.slice(0,12);setTimeout(function(){b.classList.remove("ok");s.textContent=o},1400)})});
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
/* sortable column headers (1.26.117): each header is a link the server sorts by (?sort=&dir=); Space activates it like a
   button, and the phone sort menu follows the option picked */
function sortables(){$$("th.hs .hsb").forEach(function(a){if(a.dataset.hk)return;a.dataset.hk=1;a.addEventListener("keydown",function(e){if(e.key===" "){e.preventDefault();a.click()}})});
 $$("select[data-nav]").forEach(function(s){if(s.dataset.hk)return;s.dataset.hk=1;s.addEventListener("change",function(){var v=s.value;if(v&&v.charAt(0)==="/")location.href=v})})}
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
paintIds();times();charts();sortables();pris();usdInit();tick();
(function clk(){setTimeout(function(){tick();clk()},1000-Date.now()%1000+8)})();   /* on the second, so the last minute ticks evenly */
if($("#score")){scoreSlide();setInterval(scoreSlide,BM.on&&!RM?1000:5000);benchInit()}
if(BM.demo)D.addEventListener("poa:demo",function(e){var d=e.detail||{};if(d.score)scoreIngest(d.score);if(d.snap)apply(d.snap)});   /* dev only: the server sets data-demo only with POASCAN_DEV_DEMO=1 */
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
var CPK=["mined","supply","circ","agents","joins","active","holders","txs","answers"],CPR=["24h","7d","30d","all","epoch"];
function cpParse(search){var q;try{q=new URLSearchParams(search||"")}catch(e){return null}var c=q.getAll("chart"),r=q.getAll("range");
 if(c.length!==1||CPK.indexOf(c[0])<0)return null;return {c:c[0],r:r.length===1&&CPR.indexOf(r[0])>=0?r[0]:""}}
function cpSearch(search,c,r,keep){var q=new URLSearchParams(search||"");
 if(c&&CPK.indexOf(c)>=0){q.set("chart",c);if(r&&CPR.indexOf(r)>=0)q.set("range",r);else q.delete("range")}
 else{q.delete("chart");if(keep)q.set("range",keep);else q.delete("range")}
 var s=q.toString();return s?"?"+s:""}
/* chartq:end */
(function(){
 var CPT={mined:"Total mined",supply:"Supply",circ:"Circulating supply",agents:"Agents",joins:"Agents / hr",active:"Active Agents",holders:"Holders",txs:"Txs / hour",answers:"Answers / epoch"},
  CPL={"24h":"24h","7d":"7d","30d":"30d",all:"All",epoch:"Epoch"},MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
  XSVG='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  pr0=new URLSearchParams(location.search).get("range"),KEEP=location.pathname==="/network"&&/^(24h|7d|all)$/.test(pr0||"")?pr0:null,
  cp=null,cq,box,svgW=0,cur=null,data=null,opener=null,seq=0,geo=null,idx=-1,live,tip,xh,rng,ttl,now,lg,rT=0;
 function fv(v){if(v==null)return "···";var s=data&&data.fmt==="c"?c3(v):Math.round(v).toLocaleString("en-US");return data&&data.unit?s+" "+data.unit:s}
 function dtf(o,d){try{return new Intl.DateTimeFormat(undefined,o).format(d)}catch(e){return ""}}
 /* the one site time format (1.26.122), in the reader's zone with its short name: "Oct 25, 8:48 AM PDT" */
 function when(ts,long){var z=tzn();return ltf(ts,"dt")+(z?" "+z:"")}
 function build(){cp=D.createElement("dialog");cp.className="cpop";cp.setAttribute("aria-labelledby","cp-t");cp.setAttribute("aria-modal","true");
  cp.innerHTML='<div class="cp-in"><div class="cp-hd"><h2 id="cp-t"></h2><span class="cp-q"></span><span class="cp-now num"></span><button type="button" class="jm-x cp-x" aria-label="Close" data-cpclose>'+XSVG+'</button></div>'
   +'<div class="chips cp-rng" role="group" aria-label="Range"></div><div class="chartbox cp-box" tabindex="0" role="group" aria-roledescription="chart"></div>'
   +'<div class="legend cp-lg" hidden></div><p class="sr-only" aria-live="polite"></p></div>';
  D.body.appendChild(cp);box=$(".cp-box",cp);rng=$(".cp-rng",cp);ttl=$("#cp-t",cp);now=$(".cp-now",cp);lg=$(".cp-lg",cp);live=$("p[aria-live]",cp);cq=$(".cp-q",cp);
  /* the chart's ? (qtip pattern: tap, click or keyboard; a mouse hover opens it too and leaving closes what the hover opened).
     Escape closes an open note first, then the dialog. */
  cq.addEventListener("pointerenter",function(e){var q=$("details",cq);if(e.pointerType==="mouse"&&q&&!q.open){q.open=true;q.dataset.hv="1"}});
  cq.addEventListener("pointerleave",function(e){var q=$("details",cq);if(e.pointerType==="mouse"&&q&&q.dataset.hv){q.open=false;delete q.dataset.hv}});
  cq.addEventListener("click",function(e){var q=$("details",cq);if(q&&q.dataset.hv&&e.target.closest("summary")){e.preventDefault();delete q.dataset.hv}});
  cp.addEventListener("keydown",function(e){var q=e.key==="Escape"&&$("details[open]",cq);if(q){e.preventDefault();e.stopPropagation();q.open=false;var s=$("summary",q);if(s)s.focus()}},true);
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
 function load(c,r){var n=++seq;if(!cur||cur.c!==c)cq.innerHTML="";cur={c:c,r:r||""};ttl.textContent=CPT[c]||"";now.textContent="";hide();geo=null;
  box.innerHTML='<div class="skel cskel" aria-busy="true"><i></i></div>';box.setAttribute("aria-label",CPT[c]||"Chart");
  var w=Math.max(200,Math.round(box.clientWidth||800));
  fetch("/fragment/chart?c="+encodeURIComponent(c)+(r?"&r="+encodeURIComponent(r):"")+"&w="+w,{credentials:"omit"}).then(function(x){if(!x.ok)throw 0;return x.json()}).then(function(d){
   if(n!==seq)return;data=d;cur.r=d.range;ttl.textContent=d.title;qt(d);chips();draw();
   try{history.replaceState(history.state,"",location.pathname+cpSearch(location.search,c,d.range)+location.hash)}catch(_){}})
  .catch(function(){if(n!==seq)return;box.innerHTML='<div class="naBox">Chart did not load</div>'})}
 /* a one line definition from the server (chartpop.TIPS) with its Method link */
 function qt(d){if(!d.tip){cq.innerHTML="";return}if($("details",cq))return;
  cq.innerHTML='<details class="qtip cp-tip"><summary aria-label="About '+esc2(d.title)+'">?</summary><span class="qbox" role="note">'+esc2(d.tip)+(d.method?' <a href="'+esc2(d.method)+'">Method</a>':"")+'</span></details>'}
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
  /* upgrade milestone labels sit in lanes above the plot, so they never cover the line, each other or the axis labels.
     Each label is centred on its line and kept inside the plot; one that fits no lane keeps its line and its title. */
  var ML=[];if(!bars&&d.marks.length){var mt0=d.pts[0][0],mt1=d.pts[d.pts.length-1][0],cw=mob?6.9:7.5,ends=[];
   d.marks.forEach(function(m){var mx=pl+(Wd-pl-pr)*(m[0]-mt0)/((mt1-mt0)||1),lw=Math.round(m[1].length*cw+14),x0=Math.max(pl+2,Math.min(Wd-pr-lw-2,mx-lw/2)),ln=-1;
    for(var q=0;q<4;q++){if(ends[q]==null||x0>=ends[q]+6){ln=q;break}}if(ln>=0)ends[ln]=x0+lw;ML.push({mx:mx,x0:x0,w:lw,ln:ln,t:m[1],ti:ltx(m[2]||m[1])})});
   pt=8+20*ends.length+10}
  o.push('<svg class="cpchart" viewBox="0 0 '+Wd+' '+H+'" width="'+Wd+'" height="'+H+'" aria-hidden="true"><defs><linearGradient id="cpg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+d.color+'" stop-opacity=".22"/><stop offset="1" stop-color="'+d.color+'" stop-opacity="0"/></linearGradient></defs>');
  for(var i=0;i<5;i++){var gy=Y(lo+(hi-lo)*i/4);o.push('<line x1="'+pl+'" x2="'+(Wd-pr)+'" y1="'+gy.toFixed(1)+'" y2="'+gy.toFixed(1)+'" class="grid"/><text x="'+(pl-8)+'" y="'+(gy+4).toFixed(1)+'" class="ax" text-anchor="end">'+yl[i]+'</text>')}
  if(bars){var n=d.bars.length,step=(Wd-pl-pr)/n,bw=Math.max(2,step*.62),k=d.bars[0][2].length,cols=d.colors.length?d.colors:[d.color],every=Math.max(1,Math.ceil(n/Math.max(1,Math.floor((Wd-pl)/(mob?44:56))))),cx=[];
   d.bars.forEach(function(b,j){var x=pl+step*j+(step-bw)/2,w2=bw/k;o.push('<g class="col">');b[2].forEach(function(v,m){var h=(H-pt-pb)*((v-lo)/(hi-lo));o.push('<rect x="'+(x+m*w2).toFixed(1)+'" y="'+(H-pb-h).toFixed(1)+'" width="'+w2.toFixed(1)+'" height="'+Math.max(0,h).toFixed(1)+'" fill="'+cols[m%cols.length]+'"/>')});o.push("</g>");
    cx.push(x+bw/2);if(j%every===0)o.push('<text x="'+(x+bw/2).toFixed(1)+'" y="'+(H-8)+'" class="ax" text-anchor="middle">'+esc2(b[0])+'</text>')});
   geo={n:n,x:cx,y:d.bars.map(function(b){return Y(Math.max.apply(null,b[2]))})};
   var lb=d.bars[n-1];now.textContent=d.legend.length?"":fv(lb[2][0]);
   lg.hidden=!d.legend.length;lg.innerHTML=d.legend.map(function(l,m){return '<span><i style="background:'+cols[m%cols.length]+'"></i>'+esc2(l)+'</span>'}).join("")}
  else{var P=d.pts,t0=P[0][0],t1=P[P.length-1][0],X=function(t){return pl+(Wd-pl-pr)*(t-t0)/((t1-t0)||1)},long=t1-t0>36*3600,
    BK=d.breaks||[],gap=function(a,b){return BK.some(function(k){return a<k&&k<=b})},runs=[[]];
   P.forEach(function(p,j){if(j&&gap(P[j-1][0],p[0]))runs.push([]);runs[runs.length-1].push(p)});
   /* a counter that restarted at a segment boundary: one subpath per run, never a line across the break */
   var pa=runs.map(function(r){return r.map(function(p,j){return (j?"L":"M")+X(p[0]).toFixed(1)+","+Y(p[1]).toFixed(1)}).join("")}).join("");
   runs.forEach(function(r){if(r.length<2)return;var rp=r.map(function(p,j){return (j?"L":"M")+X(p[0]).toFixed(1)+","+Y(p[1]).toFixed(1)}).join("");
    o.push('<path d="'+rp+"L"+X(r[r.length-1][0]).toFixed(1)+","+(H-pb)+"L"+X(r[0][0]).toFixed(1)+","+(H-pb)+'Z" fill="url(#cpg)"/>')});
   /* upgrade milestones, grouped on the server with milestones.group at this plot width (the Network > Charts rule) */
   ML.forEach(function(m){var ly=8+20*m.ln;
    o.push('<g class="mk"><title>'+esc2(m.ti)+'</title><line x1="'+m.mx.toFixed(1)+'" x2="'+m.mx.toFixed(1)+'" y1="'+(m.ln<0?pt:ly+17)+'" y2="'+(H-pb)+'"/>'+
     (m.ln<0?'':'<rect class="mkb" x="'+m.x0.toFixed(1)+'" y="'+ly+'" width="'+m.w+'" height="17" rx="4"/><text x="'+(m.x0+7).toFixed(1)+'" y="'+(ly+12.5)+'" class="ax mkl">'+esc2(m.t)+'</text>')+'</g>')});
   o.push('<path d="'+pa+'" fill="none" stroke="'+d.color+'" stroke-width="2" stroke-linejoin="round"/>');
   var nt=Math.max(2,Math.min(7,Math.floor((Wd-pl)/(long?96:110))));
   for(i=0;i<nt;i++){var tt=t0+(t1-t0)*i/(nt-1),dd=new Date(tt*1000),lab=long?dtf({month:"short",day:"numeric"},dd)+" "+dtf({hour:"numeric"},dd).replace(/\s/g,"").toLowerCase():dtf({hour:"numeric",minute:"2-digit"},dd);
    o.push('<text x="'+X(tt).toFixed(1)+'" y="'+(H-8)+'" class="ax" text-anchor="'+(i===0?"start":i===nt-1?"end":"middle")+'">'+esc2(lab)+'</text>')}
   geo={n:P.length,x:P.map(function(p){return X(p[0])}),y:P.map(function(p){return Y(p[1])}),long:long};now.textContent=fv(P[P.length-1][1]);lg.hidden=true}
  o.push('<circle class="cp-dot" r="4" cx="-20" cy="-20" fill="'+d.color+'"/></svg>');
  box.innerHTML=o.join("")+'<i class="xh"></i><div class="xt" aria-hidden="true"></div>';xh=$(".xh",box);tip=$(".xt",box);xh.style.top=pt+"px";tip.style.top=(ML.length?pt+4:10)+"px";   /* the tip sits below the milestone label lanes, never over a label */
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
if(BM.demo)wantLive=false;   /* the dev demo feeds apply() itself */
if(wantLive)connect();
})();
/* one "Ask agent" label per page: later Ask buttons keep the icon, title and aria-label */
(function(){var b=[].slice.call(document.querySelectorAll(".askb"));b.slice(1).forEach(function(x){x.classList.add("ico")})})();
/* charts marked .end (the upgrade milestones on Supply) open scrolled to the newest end where 390px makes them scroll */
(function(){[].slice.call(document.querySelectorAll(".chartbox.end")).forEach(function(b){b.scrollLeft=b.scrollWidth})})();
/* 1.26.108 qtip: close an open tooltip on Escape (focus back on its ? button) or a tap outside it */
(function(){var D=document;function shut(k){[].slice.call(D.querySelectorAll("details.qtip[open]")).forEach(function(d){if(d!==k)d.removeAttribute("open")})}
D.addEventListener("click",function(e){shut(e.target.closest?e.target.closest("details.qtip"):null)});
[].slice.call(D.querySelectorAll("details.qtip")).forEach(function(q){q.addEventListener("click",function(e){e.stopPropagation();shut(q)})});   /* a ? inside a sortable header never sorts the table (1.26.112) */
D.addEventListener("keydown",function(e){if(e.key!=="Escape")return;var o=D.querySelector("details.qtip[open]");if(o){o.removeAttribute("open");var s=o.querySelector("summary");if(s)s.focus()}})
/* Epoch card tips: pointerdown outside closes too, since iOS sends no click for a tap on plain text. A .qtip.hv also opens
   on a mouse hover and leaving closes what the hover opened; a click on its ? pins it. Its note opens right by its ?, below it or
   above when there is no room, inside the viewport and never over the ? itself, at every width. */
D.addEventListener("pointerdown",function(e){var k=e.target.closest?e.target.closest("details.qtip"):null;if(e.pointerType!=="mouse")shut(k)},true);
function place(q){var b=q.querySelector(".qbox");if(!b)return;if(!q.classList.contains("hv")){b.style.left=b.style.top=b.style.transform=b.style.maxHeight="";return}
 var vw=window.innerWidth,vh=window.innerHeight,r=q.querySelector("summary").getBoundingClientRect();b.style.transform="none";b.style.maxHeight=b.style.overflowY="";
 var w=b.offsetWidth,h=b.offsetHeight,x=Math.max(8,Math.min(vw-w-8,r.left+r.width/2-w/2)),dn=vh-r.bottom-16,up=r.top-16,y,below=h<=dn||(h>up&&dn>=up);
 if(!below&&h>up){b.style.maxHeight=up+"px";b.style.overflowY="auto"}else if(below&&h>dn){b.style.maxHeight=dn+"px";b.style.overflowY="auto"}   /* never over its own ? */
 h=Math.min(h,below?dn:up);y=below?r.bottom+8:r.top-8-h;q.classList.toggle("up",!below);b.style.left=x.toFixed(0)+"px";b.style.top=y.toFixed(0)+"px";q.dataset.pl="1"}
D.addEventListener("toggle",function(e){var q=e.target;if(!(q.matches&&q.matches("details.qtip")))return;if(q.open)place(q);else delete q.dataset.pl},true);
/* the note is fixed to the viewport, so it follows its ? while the page scrolls or resizes */
function qtPlaceAll(){[].slice.call(D.querySelectorAll("details.qtip.hv[open]")).forEach(place)}
window.addEventListener("scroll",qtPlaceAll,{passive:true});window.addEventListener("resize",qtPlaceAll);
D.addEventListener("pointerover",function(e){if(e.pointerType!=="mouse")return;var q=e.target.closest&&e.target.closest("details.qtip.hv");if(!q||q.open||(e.relatedTarget&&q.contains(e.relatedTarget)))return;shut(q);q.open=true;q.dataset.hv="1"});
D.addEventListener("pointerout",function(e){if(e.pointerType!=="mouse")return;var q=e.target.closest&&e.target.closest("details.qtip.hv");if(!q||!q.dataset.hv||(e.relatedTarget&&q.contains(e.relatedTarget)))return;q.open=false;delete q.dataset.hv});
D.addEventListener("click",function(e){var q=e.target.closest&&e.target.closest("details.qtip.hv");if(q&&q.dataset.hv&&e.target.closest("summary")){e.preventDefault();delete q.dataset.hv}},true)})();
