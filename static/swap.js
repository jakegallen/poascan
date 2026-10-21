/* /swaps panel: estimate from the live open offers, then hand a prefilled prompt to the visitor's agent. Read-only: nothing is signed here. */
(function(){var D=document,W=window,$=function(s,r){return (r||D).querySelector(s)},$$=function(s,r){return [].slice.call((r||D).querySelectorAll(s))};
var xp=$("#xp");if(!xp)return;var T={};try{T=JSON.parse(xp.dataset.tpl)}catch(_){}
var fee=(+xp.dataset.fee||100)/1e4,side="buy",amt=$("#xamt"),out=$("#xout"),sel=$("#xpair"),btn=$("#xgo"),xh=$("#xh"),pre=$(".pc-text",xh),emb=$("#xemb"),hint=$("#xhint"),sellMax=+xp.dataset.sellmax||0;
var CN={solana:"Solana",base:"Base",ethereum:"Ethereum"},LS="poascan.swap.connected",pick=null;
function conn(){try{return W.localStorage.getItem(LS)==="1"}catch(_){return false}}
function setConn(){try{W.localStorage.setItem(LS,"1")}catch(_){}}
function bk(){var b=$("#xbook");try{return JSON.parse(b.dataset.book)}catch(_){return {asks:[],last:{}}}}
function f(v,d){if(!isFinite(v)||v<=0)return "0";return (+v.toPrecision(d||6)).toLocaleString("en-US",{maximumFractionDigits:8})}
function asset(){return sel.value.split("|")[0]}function chain(){return sel.value.split("|")[1]||"solana"}function pairKey(){return sel.value}
var NATIVE={SOL:1,ETH:1};
function num(){return parseFloat((amt.value||"").replace(/,/g,""))||0}
function est(){var a=asset(),B=bk(),c=chain(),asks=B.asks.filter(function(o){return o.asset===a&&(o.chain||"").toLowerCase()===c}).sort(function(x,y){return x.px-y.px}),v=num(),r={out:0,ids:[],px:null,min:null,max:0,spend:0,route:"···",over:false};
 if(side==="buy"){if(pick)asks=asks.filter(function(o){return o.id===pick}).concat(asks.filter(function(o){return o.id!==pick}));
  r.max=asks.reduce(function(s,o){return s+o.want},0);if(asks.length)r.min=asks.reduce(function(m,o){return Math.min(m,o.want)},Infinity);
  var left=Math.min(v,r.max);asks.forEach(function(o){if(o.want<=left+1e-12){left-=o.want;r.spend+=o.want;r.out+=o.poa*(1-fee);r.ids.push(o.id)}});
  r.over=v>r.max+1e-12;r.px=r.out?r.spend/(r.out/(1-fee))*1e6:(asks[0]?asks[0].px:null);r.route=r.ids.length?r.ids.length+(r.ids.length>1?" offers":" offer"):"···"}
 else{var px=asks.length?asks[0].px:(B.last[a+"|"+c]||null);r.max=sellMax;r.spend=sellMax?Math.min(v,sellMax):v;r.over=!!sellMax&&v>sellMax;r.px=px;r.out=px?r.spend*px/1e6:0;r.route="New offer"}
 return r}
function prompt(r){var a=asset(),c=chain(),v=r.spend>0?f(r.spend).replace(/,/g,""):"[AMOUNT]",t=side==="buy"?(NATIVE[a]?T.buy:T.buy_token):T.sell;
 return t.split("{IN}").join(v).split("{ASSET}").join(a).split("{CHAIN}").join(c).split("{CHAINNAME}").join(CN[c]||c)
  .split("{OFFERS}").join(r.ids.length?r.ids.join(", "):"[OFFER_ID]").split("{OUT}").join(r.out?f(r.out):(side==="buy"?"[POA_AMOUNT]":"["+a+"_AMOUNT]"))}
function setPrompt(t){pre.textContent=t;$$("a[data-pre]",xh).forEach(function(x){x.href=x.dataset.pre+encodeURIComponent(t)})}
function render(){var r=est(),a=asset();$("#xu-in").textContent=side==="buy"?a:"POA";$("#xu-out").textContent=side==="buy"?"POA":a;
 $("#xl-in").textContent="You pay";$("#xl-out").textContent="You get";out.textContent=f(r.out);
 $("#xpx").textContent=r.px?f(r.px,5)+" "+a:"···";$("#xroute").textContent=r.route;
 var u=side==="buy"?a:"POA",h="";if(r.over&&r.max>0)h='Max <button type="button" data-fill="'+r.max+'">'+f(r.max)+" "+u+"</button>";
 else if(side==="buy"&&r.min!=null&&!r.ids.length&&amt.value)h='Min <button type="button" data-fill="'+r.min+'">'+f(r.min)+" "+u+"</button>";
 $$(".xbk").forEach(function(b){b.hidden=b.dataset.pair!==pairKey()});$$(".pgrid>[data-asset]").forEach(function(b){b.hidden=b.dataset.asset!==a});
 var none=side==="buy"&&!r.max;
 if(btn.dataset.up==="1"){btn.disabled=none;btn.classList.toggle("off",none);btn.textContent=none?"No offers":(conn()?"Swap":"Connect")}
 if(none&&btn.dataset.up==="1")h='Switch to <button type="button" data-goside="sell">Sell</button> or check back';
 hint.innerHTML=h;hint.hidden=!h;
 if(!xh.hidden)setPrompt(prompt(r));return r}
$$(".xtabs button").forEach(function(b){b.addEventListener("click",function(){side=b.dataset.side;pick=null;$$(".xtabs button").forEach(function(x){var on=x===b;x.classList.toggle("on",on);x.setAttribute("aria-selected",on?"true":"false")});xp.dataset.side=side;render()})});
amt.addEventListener("input",function(){pick=null;render()});emb.addEventListener("toggle",function(){if(emb.open)setConn();render()});
D.addEventListener("click",function(e){var tr=e.target.closest&&e.target.closest("tr.ask[data-offer]");if(!tr)return;var o=bk().asks.filter(function(x){return x.id===tr.dataset.offer})[0];if(!o)return;
 side="buy";$$(".xtabs button").forEach(function(x){var on=x.dataset.side==="buy";x.classList.toggle("on",on);x.setAttribute("aria-selected",on?"true":"false")});
 var k=o.asset+"|"+(o.chain||"").toLowerCase();if(sel.value!==k)setPair(k);amt.value=String(o.want);pick=o.id;render();xp.scrollIntoView({behavior:"smooth",block:"start"})});
D.addEventListener("keydown",function(e){if(e.key==="Enter"&&e.target.matches&&e.target.matches("tr.ask"))e.target.click()});
hint.addEventListener("click",function(e){var g=e.target.closest&&e.target.closest("[data-goside]");if(g){var t=$('.xtabs button[data-side="'+g.dataset.goside+'"]');if(t)t.click();return}var b=e.target.closest&&e.target.closest("[data-fill]");if(!b)return;amt.value=(+(+b.dataset.fill).toPrecision(8)).toLocaleString("en-US",{maximumFractionDigits:12,useGrouping:false});render()});
btn.addEventListener("click",function(){if(btn.dataset.up!=="1")return;
 if(!conn()){emb.open=true;setConn();btn.textContent="Swap";emb.scrollIntoView({behavior:"smooth",block:"nearest"});return}
 var r=est();if(!(r.spend>0)||(side==="buy"&&!r.ids.length)){amt.focus();return}
 xh.hidden=false;xh.open=true;setPrompt(prompt(r));xh.scrollIntoView({behavior:"smooth",block:"nearest"})});
var sb=$("#xselb"),ul=$("#xopts");
function setPair(v){sel.value=v;$$("li",ul).forEach(function(li){li.setAttribute("aria-selected",li.dataset.v===v?"true":"false")});var li=$('li[data-v="'+v+'"]',ul);
 if(li){$("#xsell").innerHTML=$(".netl",li).outerHTML;$("#xselt").textContent=$("b",li).textContent}pick=null;render()}
function openL(o){ul.hidden=!o;sb.setAttribute("aria-expanded",o?"true":"false");if(o){var c=$('li[aria-selected="true"]',ul)||$("li",ul);if(c)c.focus()}}
sb.addEventListener("click",function(e){e.stopPropagation();openL(ul.hidden)});
ul.addEventListener("click",function(e){var li=e.target.closest("li[data-v]");if(!li)return;setPair(li.dataset.v);openL(false);sb.focus()});
ul.addEventListener("keydown",function(e){var ls=$$("li",ul),i=ls.indexOf(D.activeElement);if(e.key==="ArrowDown"){e.preventDefault();(ls[i+1]||ls[0]).focus()}else if(e.key==="ArrowUp"){e.preventDefault();(ls[i-1]||ls[ls.length-1]).focus()}
 else if(e.key==="Enter"||e.key===" "){e.preventDefault();if(ls[i])ls[i].click()}else if(e.key==="Escape"){openL(false);sb.focus()}});
D.addEventListener("click",function(e){if(!ul.hidden&&!e.target.closest(".xpair"))openL(false)});
var so=$("#swapsopen");if(so&&W.MutationObserver)new MutationObserver(function(){render()}).observe(so,{childList:true});
render()})();
