/* Dev only (devdemo.py): replays the Bench motion on a local server with ?demo=motion. The archive's latest minutes become the
   last 24 min, its final two minutes play back as new txs (speed=N, default 3x), and the open epoch closes close=N seconds
   after load (default 22) so the last minute, the flip and the summary can be recorded. Events go to app.js as poa:demo, the
   same apply() and strip code the live snapshot uses. Never served on poascan.io. */
(function(){"use strict";var D=document,q=new URLSearchParams(location.search),CLOSE=+(q.get("close")||22),SPEED=+(q.get("speed")||3);
var TY={challenge:["b-answer","ANSWER"],"attest-batch":["b-attest","ATTEST"],"grade-sealed":["b-grade","GRADE"]};
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function FMTI(v){return Math.round(v||0).toLocaleString("en-US")}
function emit(d){D.dispatchEvent(new CustomEvent("poa:demo",{detail:d}))}
function frow(r,i){var a=r[5]||"",t=TY[r[4]]||["b-other","TX"],s=a.slice(0,6)+"\u2026"+a.slice(-4);
 return '<div class="frow" data-id="demo-'+i+'"><span class="badge '+t[0]+'">'+t[1]+'</span><span class="fw"><span class="al"><i class="idn" data-a="'+esc(a)+'" aria-hidden="true"></i>'+
  '<a class="mono addr" href="/address/'+esc(a)+'" title="'+esc(a)+'">'+esc(s)+"</a>"+(r[6]?' <a class="fname aname" href="https://minepoa.com/lableak/#/u/'+esc(a)+'" target="_blank" rel="noopener noreferrer">'+esc(r[6])+"</a>":"")+
  '</span></span><span class="fa"></span><a class="ft" href="/address/'+esc(a)+'"><time class="t rel" data-ts="'+Math.floor(r[1])+'"></time></a></div>'}
fetch("/dev/demo-seed",{cache:"no-store"}).then(function(r){return r.json()}).then(function(S){
 var t0=Date.now()/1000,shift=t0-S.cut,hist=[],fut=[],n=0;
 S.rows.forEach(function(r){var x=r.slice();if(r[1]<=S.cut){x[1]=r[1]+shift;hist.push(x)}else fut.push(x)});
 var rows=hist.slice(),feed=hist.slice(-12).map(function(r){return [r,n++]}).reverse(),ep=S.epoch,ans=S.answers||0,gr=S.graders||0,pool=S.pool,
  close=t0+CLOSE,start=close-S.period,last=S.last,sealers={},qi=0,lap=0,dirty=1;
 hist.forEach(function(r){if(r[0]==="s")sealers[r[5]]=1});
 function snap(){var now=Date.now()/1000;return {t:"snap",live:true,nums:{answers:[ans,"int"],graders:[gr,"int"],epoch:[ep,"int"],pool:[pool,"c2"]},
  epoch:{n:ep,start:start,close:close,period:S.period,pool:pool},last:last,feed:feed.map(function(f){return frow(f[0],f[1])}).join("")}}
 function score(){var now=Date.now()/1000,b=Math.floor(now/60)*60-1440;return {b:b,win:1440,rows:rows.filter(function(r){return r[1]>=now-1560}).map(function(r){return [r[0],Math.floor(r[1]),r[2],r[3]]})}}
 /* the page rendered the live archive's numbers; start the replay from the seed's */
 [["answers",FMTI(ans)],["graders",FMTI(gr)],["epoch",String(ep)]].forEach(function(k){var e=D.querySelector('.bench [data-live="'+k[0]+'"]');if(e)e.textContent=k[1]});
 emit({score:score(),snap:snap()});
 setInterval(function(){if(D.hidden)return;var now=Date.now()/1000,got=0;
  /* the replay: each archived tx at its own pace, sped up; then the same two minutes again */
  while(fut.length){var r=fut[qi],due=t0+lap*(120/SPEED+2)+(r[1]-S.cut)/SPEED;if(due>now)break;
   var x=r.slice();x[1]=now;rows.push(x);feed.unshift([x,n++]);feed=feed.slice(0,12);got=1;
   if(x[0]==="a")ans++;if(x[0]==="s"&&!sealers[x[5]]){sealers[x[5]]=1;gr++}
   qi++;if(qi>=fut.length){qi=0;lap++}}
  /* the close: hold Closing a beat, then the next epoch opens */
  if(now>=close+1.5){last={epoch:ep,settled:ans,minted:null,burned:null};ep++;ans=0;gr=0;sealers={};start=close;close=start+S.period;got=1}
  if(got)emit({score:score(),snap:snap()})},250)})})();
