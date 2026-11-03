/* POAScan interactive API reference. Dependency-free, same-origin only.
   Renders /openapi.json into grouped, expandable endpoint cards with a live
   "Try" for read-only GET endpoints. No external scripts, no eval: works under
   the site's strict Content-Security-Policy (script-src 'self', connect-src 'self'). */
(function () {
  "use strict";
  var root = document.getElementById("apiref");
  if (!root) return;

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === "class") e.className = attrs[k];
      else if (k === "text") e.textContent = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function note(msg, cls) { root.innerHTML = ""; root.appendChild(el("p", { class: cls || "aref-note", text: msg })); }

  note("Loading the API spec…");

  fetch("/openapi.json", { headers: { Accept: "application/json" } })
    .then(function (r) { if (!r.ok) throw new Error("spec " + r.status); return r.json(); })
    .then(render)
    .catch(function (e) { note("Could not load the API spec (" + e.message + "). The raw spec is at /openapi.json.", "aref-err"); });

  function render(spec) {
    root.innerHTML = "";
    var paths = spec.paths || {};
    // flatten operations
    var ops = [];
    Object.keys(paths).forEach(function (p) {
      var item = paths[p];
      Object.keys(item).forEach(function (m) {
        if (["get", "post", "put", "delete", "patch"].indexOf(m) < 0) return;
        var o = item[m] || {};
        var tag = (o.tags && o.tags[0]) || (p.split("/").filter(Boolean)[1]) || "other";
        ops.push({ path: p, method: m.toUpperCase(), op: o, tag: tag, params: o.parameters || [] });
      });
    });

    // controls
    var count = el("span", { class: "aref-count", text: ops.length + " endpoints" });
    var search = el("input", { class: "aref-search", type: "search", placeholder: "Filter by path, method or summary…", "aria-label": "Filter endpoints" });
    var bar = el("div", { class: "aref-bar" }, [search, count]);
    root.appendChild(bar);

    // group by tag, preserving first-seen order
    var order = [], groups = {};
    ops.forEach(function (o) { if (!groups[o.tag]) { groups[o.tag] = []; order.push(o.tag); } groups[o.tag].push(o); });

    var host = el("div", { class: "aref-groups" });
    root.appendChild(host);

    order.forEach(function (tag) {
      var g = el("section", { class: "aref-group" });
      g.appendChild(el("h2", { class: "aref-gh", text: tag }));
      var list = el("div", { class: "aref-list" });
      groups[tag].forEach(function (o) { list.appendChild(row(o, spec)); });
      g.appendChild(list);
      host.appendChild(g);
    });

    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase();
      var shown = 0;
      host.querySelectorAll(".aref-row").forEach(function (r) {
        var hay = r.getAttribute("data-hay");
        var ok = !q || hay.indexOf(q) >= 0;
        r.style.display = ok ? "" : "none";
        if (ok) shown++;
      });
      host.querySelectorAll(".aref-group").forEach(function (sec) {
        var any = sec.querySelector('.aref-row:not([style*="display: none"])');
        sec.style.display = any ? "" : "none";
      });
      count.textContent = (q ? shown + " of " + ops.length : ops.length) + " endpoints";
    });
  }

  function row(o, spec) {
    var hay = (o.method + " " + o.path + " " + (o.op.summary || "")).toLowerCase();
    var r = el("div", { class: "aref-row", "data-hay": hay });
    var head = el("button", { class: "aref-head", type: "button", "aria-expanded": "false" }, [
      el("span", { class: "aref-m m-" + o.method.toLowerCase(), text: o.method }),
      el("code", { class: "aref-path", text: o.path }),
      el("span", { class: "aref-sum", text: o.op.summary || "" })
    ]);
    var body = el("div", { class: "aref-body", hidden: "hidden" });
    var built = false;
    head.addEventListener("click", function () {
      var open = body.hasAttribute("hidden");
      if (open && !built) { buildBody(body, o, spec); built = true; }
      if (open) body.removeAttribute("hidden"); else body.setAttribute("hidden", "hidden");
      head.setAttribute("aria-expanded", open ? "true" : "false");
      r.classList.toggle("open", open);
    });
    r.appendChild(head); r.appendChild(body);
    return r;
  }

  function buildBody(body, o, spec) {
    if (o.op.description) body.appendChild(el("p", { class: "aref-desc", text: o.op.description }));

    var pathParams = o.params.filter(function (p) { return p.in === "path"; });
    var queryParams = o.params.filter(function (p) { return p.in === "query"; });

    if (o.params.length) {
      var tbl = el("table", { class: "aref-params" });
      tbl.appendChild(el("thead", {}, [el("tr", {}, [
        el("th", { text: "Parameter" }), el("th", { text: "In" }), el("th", { text: "Req" }), el("th", { text: "Description" })
      ])]));
      var tb = el("tbody");
      o.params.forEach(function (p) {
        tb.appendChild(el("tr", {}, [
          el("td", {}, [el("code", { text: p.name })]),
          el("td", { text: p.in }),
          el("td", { text: p.required ? "yes" : "" }),
          el("td", { text: p.description || "" })
        ]));
      });
      tbl.appendChild(tb); body.appendChild(tbl);
    }

    if (o.method !== "GET") {
      body.appendChild(el("p", { class: "aref-note", text: "This is a " + o.method + " endpoint. The public API is read-only; use the GET endpoints to try live calls." }));
      return;
    }

    // Try-it panel (GET, read-only)
    var inputs = {};
    var form = el("div", { class: "aref-try" });
    pathParams.concat(queryParams).forEach(function (p) {
      var id = "f_" + o.method + o.path.replace(/\W+/g, "_") + "_" + p.name;
      var inp = el("input", { class: "aref-in", type: "text", id: id, placeholder: (p.in === "path" ? "" : "optional ") + p.name + (p.example != null ? "  e.g. " + p.example : "") });
      if (p.example != null) inp.value = String(p.example);
      inputs[p.name] = { el: inp, in: p.in };
      form.appendChild(el("label", { class: "aref-lab", for: id }, [el("span", { class: "aref-labn", text: p.name + (p.required ? " *" : "") }), inp]));
    });
    var send = el("button", { class: "aref-send", type: "button", text: "Send request" });
    var out = el("pre", { class: "aref-out", hidden: "hidden" });
    form.appendChild(send); body.appendChild(form); body.appendChild(out);

    send.addEventListener("click", function () {
      var url = o.path;
      var missing = false;
      Object.keys(inputs).forEach(function (name) {
        var v = inputs[name].el.value.trim();
        if (inputs[name].in === "path") {
          if (!v) missing = true;
          url = url.replace("{" + name + "}", encodeURIComponent(v));
        }
      });
      if (missing) { out.removeAttribute("hidden"); out.className = "aref-out aref-err"; out.textContent = "Fill in the required path parameters first."; return; }
      var qs = [];
      Object.keys(inputs).forEach(function (name) {
        var it = inputs[name]; var v = it.el.value.trim();
        if (it.in === "query" && v) qs.push(encodeURIComponent(name) + "=" + encodeURIComponent(v));
      });
      if (qs.length) url += (url.indexOf("?") >= 0 ? "&" : "?") + qs.join("&");

      out.removeAttribute("hidden"); out.className = "aref-out"; out.textContent = "GET " + url + "\n…";
      send.disabled = true;
      var t0 = Date.now();
      fetch(url, { headers: { Accept: "application/json" } })
        .then(function (r) {
          return r.text().then(function (txt) {
            var ms = Date.now() - t0;
            var pretty = txt;
            try { pretty = JSON.stringify(JSON.parse(txt), null, 2); } catch (e) {}
            if (pretty.length > 20000) pretty = pretty.slice(0, 20000) + "\n… (truncated; open " + url + " for the full response)";
            out.className = "aref-out" + (r.ok ? "" : " aref-err");
            out.textContent = "GET " + url + "\n" + r.status + " " + r.statusText + "  ·  " + ms + " ms\n\n" + pretty;
          });
        })
        .catch(function (e) { out.className = "aref-out aref-err"; out.textContent = "GET " + url + "\nRequest failed: " + e.message; })
        .then(function () { send.disabled = false; });
    });
  }
})();
