/* Start hub (starthub.py). Optional: (1) the Answer in numeral counts down each second; (2) on the Check tab, while a stage is still waiting, the stepper
   re-reads the same page every 30 s (only while the tab is visible) and swaps the list when a stage lands. Reduced motion: no animation. Without script
   every number is already in the page and Check is a plain form. */
(function(){var D=document;
function dur(s){s=Math.max(0,s|0);var h=s/3600|0,m=(s%3600)/60|0;return h?h+"h "+("0"+m).slice(-2)+"m":m+"m "+("0"+(s%60)).slice(-2)+"s"}
var cd=D.querySelector(".stcd[data-left]");
if(cd){var left=+cd.getAttribute("data-left"),at=+cd.getAttribute("data-at");setInterval(function(){if(D.hidden)return;var l=left-(Date.now()/1e3-at);if(l>0)cd.textContent=dur(l)},1000)}
var sp=D.querySelector("[data-stper][data-watch='1']");
if(sp){setInterval(function(){if(D.hidden)return;fetch(location.href,{credentials:"same-origin"}).then(function(r){return r.ok?r.text():""}).then(function(t){if(!t)return;
 var d=new DOMParser().parseFromString(t,"text/html"),n=d.querySelector("[data-stper]"),w=d.querySelector(".stw"),cur=D.querySelector("[data-stper]"),cw=D.querySelector(".stw");
 if(n&&cur&&n.innerHTML!==cur.innerHTML){cur.innerHTML=n.innerHTML;cur.setAttribute("data-watch",n.getAttribute("data-watch"));if(w&&cw)cw.outerHTML=w.outerHTML}}).catch(function(){})},30000)}
})();
