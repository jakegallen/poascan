// Preview only: click a column header to sort (the live site does this with server links), lane chips follow the app.
(function(){
  document.querySelectorAll('table[data-pvsort]').forEach(function(t){
    t.querySelectorAll('thead th[data-k]').forEach(function(th,ci){
      th.addEventListener('click',function(e){e.preventDefault();
        var idx=[].indexOf.call(th.parentNode.children,th), num=th.dataset.k!=='text';
        var dir=th.getAttribute('aria-sort')==='descending'?'ascending':'descending';
        t.querySelectorAll('thead th').forEach(function(x){x.classList.remove('on');x.setAttribute('aria-sort','none');var i=x.querySelector('.ha');if(i)i.textContent='\u2195';});
        th.classList.add('on');th.setAttribute('aria-sort',dir);th.querySelector('.ha').textContent=dir==='descending'?'\u2193':'\u2191';
        var tb=t.tBodies[0], rows=[].slice.call(tb.rows);
        rows.sort(function(a,b){var x=a.cells[idx].dataset.v||a.cells[idx].textContent.trim(), y=b.cells[idx].dataset.v||b.cells[idx].textContent.trim();
          if(num){x=parseFloat(x);y=parseFloat(y);if(isNaN(x))return 1;if(isNaN(y))return -1;return dir==='descending'?y-x:x-y;}
          return dir==='descending'?x.localeCompare(y):y.localeCompare(x);});
        rows.forEach(function(r){tb.appendChild(r);});
      });
    });
  });
  var lane={connector:'mcp',full:'hosted',none:''};
  document.querySelectorAll('input[name=client]').forEach(function(r){r.addEventListener('change',function(){
    var l=lane[r.dataset.tier]; if(l){var x=document.querySelector('input[name=lane][value='+l+']'); if(x) x.checked=true;}
  });});
  document.querySelectorAll('[data-more]').forEach(function(b){b.addEventListener('click',function(){var p=document.getElementById(b.getAttribute('aria-controls'));var o=b.getAttribute('aria-expanded')!=='true';b.setAttribute('aria-expanded',o);p.hidden=!o;});});
})();
