/* Network hub (nethub.py). Three small jobs, all optional: (1) the anchor ring numeral ticks each second and a once a minute
   read of /api/v1/network/anchors-eta restarts the ring when a new anchor lands; (2) chips marked data-kit-sub swap the module body in place
   (same fetch and crossfade as the tab swap); (3) nothing runs while the tab is hidden. Reduced motion: no fade, no flash.
   Without script every chip is a normal link and every number is already in the page. */
(function(){var D=document,W=window,RM=W.matchMedia&&W.matchMedia("(prefers-reduced-motion:reduce)").matches;
function age(s){s=Math.max(0,s|0);return s<60?s+"s":s<3600?(s/60|0)+"m":s<86400?(s/3600|0)+"h "+("0"+((s%3600)/60|0)).slice(-2)+"m":(s/86400|0)+"d "+((s%86400)/3600|0)+"h"}
var ring=D.querySelector("[data-aring]");
if(ring){var num=ring.querySelector("[data-aage]"),rp=ring.querySelector(".rp"),skew=(+ring.getAttribute("data-now")||0)*1000-Date.now();
 function paint(){var last=+ring.getAttribute("data-last"),cad=+ring.getAttribute("data-cad");if(!last)return;var a=(Date.now()+skew)/1e3-last;
  var t=age(a);num.textContent=t;num.classList.toggle("long",t.length>5);var f=cad?Math.min(1,a/cad):0;ring.style.setProperty("--f",f.toFixed(4));if(rp)rp.setAttribute("stroke-dasharray",(f*100).toFixed(2)+" 100");ring.classList.toggle("late",!!cad&&a>1.5*cad)}
 function poll(){if(D.hidden)return;fetch("/api/v1/network/anchors-eta",{credentials:"same-origin"}).then(function(r){return r.ok?r.json():null}).then(function(d){
   if(!d||!d.last_anchor_ts)return;var old=+ring.getAttribute("data-last");ring.setAttribute("data-last",d.last_anchor_ts);if(d.cadence_s)ring.setAttribute("data-cad",d.cadence_s);
   if(old&&d.last_anchor_ts>old&&!RM){ring.classList.add("flash");setTimeout(function(){ring.classList.remove("flash")},1400)}paint()}).catch(function(){})}
 setInterval(function(){if(!D.hidden)paint()},1000);setInterval(poll,60000);D.addEventListener("visibilitychange",function(){if(!D.hidden){paint();poll()}})}
/* in module chip swap */
var busy=0;
function mod(){return D.querySelector('.kit-mod[data-kit="tabs"]')}
function swap(url){var m=mod();if(!m||busy)return false;busy=1;var body=m.querySelector(".kit-body"),tools=m.querySelector(".kit-tools"),h=body.offsetHeight;
 var tm=setTimeout(function(){m.classList.add("kit-busy")},160);
 fetch(url,{credentials:"same-origin",headers:{"X-Requested-With":"poakit"}}).then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(t){
  var d=new DOMParser().parseFromString(t,"text/html"),nm=d.querySelector('.kit-mod[data-kit="tabs"]');if(!nm)throw 0;
  var nb=nm.querySelector(".kit-body"),nt=nm.querySelector(".kit-tools");
  function put(){body.style.minHeight=h+"px";body.innerHTML=nb.innerHTML;if(tools&&nt)tools.innerHTML=nt.innerHTML;if(d.title)D.title=d.title;history.pushState({kit:1},"",url);
   body.classList.remove("kit-out");if(!RM){body.classList.add("kit-in");setTimeout(function(){body.classList.remove("kit-in");body.style.minHeight=""},300)}else body.style.minHeight="";
   var K=W.poaKit||{};if(K.lt)K.lt(m);if(K.tips)K.tips();clearTimeout(tm);m.classList.remove("kit-busy");busy=0}
  if(RM)put();else{body.classList.add("kit-out");setTimeout(put,140)}
 }).catch(function(){clearTimeout(tm);busy=0;W.location.href=url});return true}
D.addEventListener("click",function(e){var a=e.target.closest&&e.target.closest("a[data-kit-sub]");if(!a||e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
 if(a.getAttribute("aria-current")==="page"||a.classList.contains("on")&&!a.classList.contains("ovt")){e.preventDefault();return}
 if(swap(a.href))e.preventDefault()});
})();
