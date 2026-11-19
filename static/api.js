/* API hub (apihub.py). Optional: (1) the search box filters as you type (it swaps the list and pane, not the box), chips, rows and pages swap the same way;
   (2) Run replays the stored sample with a short typing reveal and shows its stored status (it never calls a live endpoint). Reduced motion: no typing, no fade.
   Without script the search is a plain form, every chip and row is a link, and Run is a link that shows the status. */
(function(){var D=document,W=window,RM=W.matchMedia&&W.matchMedia("(prefers-reduced-motion:reduce)").matches;
var busy=0,tmr=0;
function res(){return D.querySelector("[data-ares]")}
function swap(url,replace){var r=res();if(!r||busy)return false;busy=1;r.classList.add("busy");
 fetch(url,{credentials:"same-origin",headers:{"X-Requested-With":"poakit"}}).then(function(x){if(!x.ok)throw 0;return x.text()}).then(function(t){
  var d=new DOMParser().parseFromString(t,"text/html"),n=d.querySelector("[data-ares]");if(!n)throw 0;
  r.innerHTML=n.innerHTML;r.classList.remove("busy");history[replace?"replaceState":"pushState"]({kit:1},"",url);busy=0;var K=W.poaKit||{};if(K.tips)K.tips()
 }).catch(function(){busy=0;r.classList.remove("busy");W.location.href=url});return true}
D.addEventListener("click",function(e){var a=e.target.closest&&e.target.closest("a[data-aj]");if(a&&!(e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)&&swap(a.href))e.preventDefault();
 var run=e.target.closest&&e.target.closest("a[data-run]");if(run&&!(e.metaKey||e.ctrlKey||e.shiftKey)){e.preventDefault();var p=run.closest("[data-apane]"),pre=p&&p.querySelector("[data-sample]"),st=p&&p.querySelector("[data-status]");if(!pre)return;
  var full=pre.textContent;if(RM){if(st)st.classList.add("on");return}
  if(st)st.classList.remove("on");p.classList.add("typing");pre.textContent="";var i=0,n=Math.max(1,Math.ceil(full.length/40));
  (function step(){i+=n;pre.textContent=full.slice(0,i);if(i<full.length)setTimeout(step,10);else{p.classList.remove("typing");if(st)st.classList.add("on")}})()}});
D.addEventListener("input",function(e){var i=e.target.closest&&e.target.closest("[data-aq]");if(!i)return;clearTimeout(tmr);
 tmr=setTimeout(function(){var f=i.form,u=new URL(f.action,location.href);var tab=f.querySelector('[name=tab]');u.searchParams.set("tab",tab.value);if(i.value.trim())u.searchParams.set("q",i.value.trim());u.searchParams.delete("sel");
  if(tab.value==="rest")u.searchParams.delete("tab");swap(u.pathname+u.search,true)},180)});
})();
