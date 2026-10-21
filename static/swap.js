/* /swaps panel: estimate from the live open offers, then hand a prefilled prompt to the visitor's agent. Read-only: nothing is signed here. */
(function(){var D=document,W=window,$=function(s,r){return (r||D).querySelector(s)},$$=function(s,r){return [].slice.call((r||D).querySelectorAll(s))};
var xp=$("#xp");if(!xp)return;var T={};try{T=JSON.parse(xp.dataset.tpl)}catch(_){}
var fee=(+xp.dataset.fee||100)/1e4,side="buy",amt=$("#xamt"),out=$("#xout"),sel=$("#xpair"),btn=$("#xgo"),xh=$("#xh"),pre=$(".pc-text",xh);
var CN={solana:"Solana",base:"Base",ethereum:"Ethereum"},LS="poascan.swap.connected",pick=null;
function conn(){try{return W.localStorage.getItem(LS)==="1"}catch(_){return false}}
function setConn(){try{W.localStorage.setItem(LS,"1")}catch(_){}}
function bk(){var b=$("#xbook");try{return JSON.parse(b.dataset.book)}catch(_){return {asks:[],last:{}}}}
function f(v,d){if(!isFinite(v)||v<=0)return "0";return (+v.toPrecision(d||6)).toLocaleString("en-US",{maximumFractionDigits:8})}
function asset(){return sel.value}function chain(){var o=sel.options[sel.selectedIndex];return (o&&o.dataset.chain)||"solana"}
function est(){var a=asset(),B=bk(),asks=B.asks.filter(function(o){return o.asset===a}).sort(function(x,y){return x.px-y.px}),v=parseFloat((amt.value||"").replace(/,/g,""))||0,r={out:0,ids:[],px:null,min:null,route:"···"};
 if(side==="buy"){if(pick)asks=asks.filter(function(o){return o.id===pick}).concat(asks.filter(function(o){return o.id!==pick}));
  var left=v;asks.forEach(function(o){if(o.want<=left+1e-12){left-=o.want;r.out+=o.poa*(1-fee);r.ids.push(o.id)}});
  if(asks.length)r.min=asks.reduce(function(m,o){return Math.min(m,o.want)},Infinity);
  var spent=v-left;r.px=r.out?spent/(r.out/(1-fee))*1e6:(asks[0]?asks[0].px:null);r.route=r.ids.length?r.ids.length+(r.ids.length>1?" offers":" offer"):"···"}
 else{var px=asks.length?asks[0].px:(B.last[a]||null);r.px=px;r.out=px?v*px/1e6:0;r.route="New offer"}
 return r}
function prompt(r){var a=asset(),c=chain(),v=amt.value||"[AMOUNT]",t=side==="buy"?T.buy:T.sell;
 return t.split("{IN}").join(v).split("{ASSET}").join(a).split("{CHAIN}").join(c).split("{CHAINNAME}").join(CN[c]||c)
  .split("{OFFERS}").join(r.ids.length?r.ids.join(", "):"[OFFER_ID]").split("{OUT}").join(r.out?f(r.out):(side==="buy"?"[POA_AMOUNT]":"["+a+"_AMOUNT]"))}
function setPrompt(t){pre.textContent=t;$$("a[data-pre]",xh).forEach(function(x){x.href=x.dataset.pre+encodeURIComponent(t)})}
function render(){var r=est(),a=asset();$("#xu-in").textContent=side==="buy"?a:"POA";$("#xu-out").textContent=side==="buy"?"POA":a;
 $("#xl-in").textContent="You pay";$("#xl-out").textContent="You get";out.textContent=f(r.out);
 $("#xpx").textContent=r.px?f(r.px,5)+" "+a:"···";$("#xroute").textContent=r.route;
 if(side==="buy"&&r.min!=null&&!r.ids.length&&amt.value)$("#xroute").textContent="Min "+f(r.min)+" "+a;
 $$(".xbk,.pgrid>[data-asset]").forEach(function(b){b.hidden=b.dataset.asset!==a});
 if(btn.dataset.up==="1")btn.textContent=conn()?"Swap":"Connect";
 if(!xh.hidden&&xh.dataset.k!=="connect")setPrompt(prompt(r));return r}
$$(".xtabs button").forEach(function(b){b.addEventListener("click",function(){side=b.dataset.side;pick=null;$$(".xtabs button").forEach(function(x){var on=x===b;x.classList.toggle("on",on);x.setAttribute("aria-selected",on?"true":"false")});xp.dataset.side=side;render()})});
amt.addEventListener("input",function(){pick=null;render()});sel.addEventListener("change",render);
D.addEventListener("click",function(e){var tr=e.target.closest&&e.target.closest("tr.ask[data-offer]");if(!tr)return;var o=bk().asks.filter(function(x){return x.id===tr.dataset.offer})[0];if(!o)return;
 side="buy";$$(".xtabs button").forEach(function(x){var on=x.dataset.side==="buy";x.classList.toggle("on",on);x.setAttribute("aria-selected",on?"true":"false")});
 if(sel.value!==o.asset)sel.value=o.asset;amt.value=String(o.want);pick=o.id;render();xp.scrollIntoView({behavior:"smooth",block:"start"})});
D.addEventListener("keydown",function(e){if(e.key==="Enter"&&e.target.matches&&e.target.matches("tr.ask"))e.target.click()});
btn.addEventListener("click",function(){if(btn.dataset.up!=="1")return;
 if(!conn()){xh.dataset.k="connect";setPrompt(T.connect);xh.hidden=false;setConn();btn.textContent="Swap";return}
 if(!(parseFloat(amt.value)>0)){amt.focus();return}
 xh.dataset.k="swap";xh.hidden=false;setPrompt(prompt(est()))});
var so=$("#swapsopen");if(so&&W.MutationObserver)new MutationObserver(function(){render()}).observe(so,{childList:true});
render()})();
