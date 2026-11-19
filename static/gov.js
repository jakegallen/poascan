/* Governance hub (govhub.py). Optional: (1) the Closes in numeral counts down each second, (2) the ring count rises once,
   (3) chips marked data-kit-sub swap the module body in place with a crossfade. Reduced motion: no fade, no count-up. Without script
   every chip is a normal link and every number is already in the page. */
(function(){var D=document,W=window,RM=W.matchMedia&&W.matchMedia("(prefers-reduced-motion:reduce)").matches;
function dur(s){s=Math.max(0,s|0);var d=s/86400|0,h=(s%86400)/3600|0,m=(s%3600)/60|0;return d?d+"d "+h+"h":h?h+"h "+("0"+m).slice(-2)+"m":m+"m "+("0"+(s%60)).slice(-2)+"s"}
var cd=D.querySelector(".gcd[data-left]");
if(cd){var left=+cd.getAttribute("data-left"),at=+cd.getAttribute("data-at");setInterval(function(){if(D.hidden)return;var l=left-(Date.now()/1e3-at);if(l>0)cd.textContent=dur(l)},1000)}
var cu=D.querySelector(".gring [data-cu]");
if(cu&&!RM){var to=+cu.getAttribute("data-cu"),t0=0;function f(t){if(!t0)t0=t;var p=Math.min(1,(t-t0)/900),e=1-Math.pow(1-p,3);cu.textContent=Math.round(to*e).toLocaleString("en-US");if(p<1)requestAnimationFrame(f)}requestAnimationFrame(f)}
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
 if(a.getAttribute("aria-current")==="page"||a.classList.contains("on")){e.preventDefault();return}
 if(swap(a.href))e.preventDefault()});
})();
