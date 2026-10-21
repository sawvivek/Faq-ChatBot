(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var root = document.documentElement;
  // ---- theme (kept in this file as well so the chat page needs a single script) ----
  try { var saved = localStorage.getItem("theme"); if (saved) root.dataset.theme = saved; else if (matchMedia("(prefers-color-scheme: dark)").matches) root.dataset.theme = "dark"; } catch (e) {}
  function syncThemeLabel() { $("#theme").setAttribute("aria-label", root.dataset.theme === "dark" ? "Switch to light theme" : "Switch to dark theme"); }
  syncThemeLabel();
  $("#theme").addEventListener("click", function () {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
    syncThemeLabel();
  });

  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") el.className = attrs[k]; else if (k === "text") el.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]); else el.setAttribute(k, attrs[k]);
    });
    function appendChild(c) {
      if (c == null) return;
      if (Array.isArray(c)) { c.forEach(appendChild); return; }
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    for (var i = 2; i < arguments.length; i++) appendChild(arguments[i]);
    return el;
  }

  var log = $("#log"), input = $("#composer-input"), send = $("#send"), ctx = null, busy = false, lastQuestion = null;
  var HKEY = "faq_history";
  function loadHistory() { try { return JSON.parse(localStorage.getItem(HKEY) || "[]"); } catch (e) { return []; } }
  function saveHistory(q) {
    var hs = loadHistory().filter(function (x) { return x !== q; }); hs.unshift(q);
    try { localStorage.setItem(HKEY, JSON.stringify(hs.slice(0, 25))); } catch (e) {}
    renderHistory();
  }
  function renderHistory() {
    var ul = $("#history"), hs = loadHistory(); ul.textContent = "";
    if (!hs.length) { ul.appendChild(h("li", { "class": "muted", text: "Nothing asked yet." })); return; }
    hs.forEach(function (q) { ul.appendChild(h("li", {}, h("button", { type: "button", text: q, onclick: function () { closeSide(); ask(q); } }))); });
  }
  $("#clear-history").addEventListener("click", function () { try { localStorage.removeItem(HKEY); } catch (e) {} renderHistory(); });

  // ---- side drawer (mobile) ----
  var side = $("#side"), scrim = $("#scrim"), openBtn = $("#open-side");
  function openSide() { side.classList.add("open"); scrim.hidden = false; openBtn.setAttribute("aria-expanded", "true"); }
  function closeSide() { side.classList.remove("open"); scrim.hidden = true; openBtn.setAttribute("aria-expanded", "false"); }
  openBtn.addEventListener("click", openSide); scrim.addEventListener("click", closeSide);

  // ---- scrolling ----
  var jump = $("#jump");
  function atBottom() { return log.scrollHeight - log.scrollTop - log.clientHeight < 80; }
  function toBottom() { log.scrollTop = log.scrollHeight; jump.hidden = true; }
  log.addEventListener("scroll", function () { jump.hidden = atBottom(); });
  jump.addEventListener("click", toBottom);

  function chip(q) { return h("button", { "class": "chip", type: "button", text: q, onclick: function () { ask(q); } }); }
  function chips(list) { return h("div", { "class": "chips" }, list.map(chip)); }

  function pct(x) { return Math.round(x * 100) + "%"; }

  function rankView(res) {
    var box = h("details", { "class": "why" }, h("summary", { text: "Why this answer?" }));
    if (res.corrected_query) box.appendChild(h("p", { "class": "subtle", text: "Read your question as: \u201C" + res.corrected_query + "\u201D" }));
    if (res.used_context) box.appendChild(h("p", { "class": "subtle", text: "Used your previous question for context: " + res.interpreted_as }));
    box.appendChild(h("p", { "class": "subtle", text: "Language: " + res.language + " \u00B7 intent: " + (res.intent || "n/a") + " \u00B7 " + res.latency_ms + " ms" }));
    var grid = h("div", { "class": "rank" });
    (res.evidence || []).forEach(function (e) {
      var p = e.parts || {};
      grid.appendChild(h("span", { "class": "t", title: e.question, text: e.question }));
      grid.appendChild(h("span", { "class": "n", text: pct(e.score) }));
      var b = h("div", { "class": "bar" }, h("i")); grid.appendChild(b);
      requestAnimationFrame(function () { b.firstChild.style.width = Math.min(100, Math.round(e.score * 100)) + "%"; });
      grid.appendChild(h("span", { "class": "parts", text: "matched \u201C" + e.matched + "\u201D \u00B7 words " + pct(p.word || 0) + ", spelling-tolerant " + pct(p.char || 0) + ", BM25 " + pct(p.bm25 || 0) + ", coverage " + pct(p.cov || 0) }));
    });
    box.appendChild(grid);
    return box;
  }

  function feedbackView(res) {
    var wrap = h("div", { "class": "fb" }), note = h("span", { "class": "subtle", "aria-live": "polite" });
    function vote(helpful) {
      Array.prototype.forEach.call(wrap.querySelectorAll("button"), function (b) { b.disabled = true; });
      fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ log_id: res.log_id, helpful: helpful }) })
        .then(function () { note.textContent = helpful ? "Thanks for the feedback." : "Thanks. An administrator will review this answer."; })
        .catch(function () { note.textContent = "Couldn't send feedback."; });
    }
    wrap.appendChild(h("button", { type: "button", text: "Helpful", onclick: function () { vote(true); } }));
    wrap.appendChild(h("button", { type: "button", text: "Not helpful", onclick: function () { vote(false); } }));
    wrap.appendChild(note);
    return wrap;
  }

  function botCard(res) {
    var kids = [], cls = res.status;
    if (res.status === "answered") {
      kids.push(h("div", { "class": "q", text: res.matched_question }));
      kids.push(h("p", { "class": "a", text: res.answer }));
      var meta = h("div", { "class": "meta" }, h("span", { "class": "badge " + (res.confidence_label || "medium"), text: (res.confidence_label === "high" ? "High" : "Medium") + " confidence \u00B7 " + pct(res.confidence) }));
      var s = res.sources && res.sources[0];
      if (s) meta.appendChild(h("span", { text: "Source: " + (s.source || "FAQ #" + s.faq_id) + " \u00B7 v" + s.version + " \u00B7 updated " + s.updated }));
      kids.push(meta);
      if (res.stale) kids.push(h("div", { "class": "notice", role: "note", text: "This answer hasn't been reviewed recently and may be out of date. Please confirm with the office." }));
      if (res.confidence_label === "medium") kids.push(h("p", { "class": "subtle", text: "If this isn't what you meant, try rephrasing or pick a related question below." }));
      if (res.related && res.related.length) { kids.push(h("p", { "class": "subtle", text: "Related questions" })); kids.push(chips(res.related.map(function (r) { return r.question; }))); }
      else if (res.suggestions && res.suggestions.length) { kids.push(h("p", { "class": "subtle", text: "You might also ask" })); kids.push(chips(res.suggestions.map(function (r) { return r.question; }))); }
    } else if (res.status === "smalltalk") {
      cls = "answered"; kids.push(h("p", { "class": "a", text: res.answer }));
    } else {
      kids.push(h("p", { "class": "a", text: res.message || "I don't have verified information on that." }));
      if (res.suggestions && res.suggestions.length) { kids.push(h("p", { "class": "subtle", text: res.status === "unknown" ? "Closest topics in the FAQ" : "Choose one" })); kids.push(chips(res.suggestions.map(function (r) { return r.question; }))); }
    }
    if (res.status !== "smalltalk" && res.status !== "empty") { kids.push(feedbackView(res)); kids.push(rankView(res)); }
    return h("div", { "class": "card " + cls }, kids);
  }

  function addMsg(node, who) { var wasBottom = atBottom(); var m = h("div", { "class": "msg " + who }, node); log.appendChild(m); if (wasBottom || who === "user") toBottom(); else jump.hidden = false; return m; }

  function ask(q) {
    q = (q || "").trim(); if (!q || busy) return;
    var empty = $("#empty"); if (empty) empty.remove();
    busy = true; send.disabled = true; lastQuestion = q;
    addMsg(h("div", { "class": "bubble", text: q }), "user");
    var typing = addMsg(h("div", { "class": "card", role: "status", "aria-label": "Searching the FAQ" }, h("span", { "class": "dots" }, h("i"), h("i"), h("i"))), "bot");
    input.value = ""; autosize();
    fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q, context: ctx }) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (o) {
        typing.remove();
        if (!o.ok) { addMsg(errCard(o.j.error || "Something went wrong.", q), "bot"); return; }
        var res = o.j;
        if (res.status === "answered") ctx = { last_faq_id: res.faq_id, last_query: q }; else if (res.status !== "smalltalk") ctx = ctx;
        saveHistory(q); addMsg(botCard(res), "bot");
      })
      .catch(function () { typing.remove(); addMsg(errCard("Can't reach the assistant. Check that the server is running, then retry.", q), "bot"); })
      .then(function () { busy = false; send.disabled = false; input.focus(); });
  }
  function errCard(msg, q) { return h("div", { "class": "card error", role: "alert" }, h("p", { "class": "a", text: msg }), h("div", {}, h("button", { "class": "chip", type: "button", text: "Retry", onclick: function () { ask(q); } }))); }

  // ---- composer ----
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); } if (e.key === "Escape") { input.value = ""; autosize(); } });
  $("#composer").addEventListener("submit", function (e) { e.preventDefault(); ask(input.value); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); }
    if (e.key === "Escape") closeSide();
  });

  // ---- voice input (browser feature; many browsers send audio to an online service, so hide offline) ----
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition, mic = $("#mic");
  if (SR) {
    mic.hidden = false;
    mic.addEventListener("click", function () {
      var r = new SR(); r.lang = navigator.language || "en-IN"; r.interimResults = false;
      mic.setAttribute("aria-pressed", "true");
      r.onresult = function (ev) { input.value = ev.results[0][0].transcript; autosize(); input.focus(); };
      r.onend = r.onerror = function () { mic.removeAttribute("aria-pressed"); };
      try { r.start(); } catch (e) {}
    });
  }

  // ---- connectivity banner: the assistant itself is local; only voice input needs the internet ----
  function net() { $("#net").textContent = navigator.onLine ? "" : "Offline: the FAQ still works. Voice input may not."; if (SR) mic.hidden = !navigator.onLine; }
  addEventListener("online", net); addEventListener("offline", net); net();

  // ---- start ----
  fetch("/api/bootstrap").then(function (r) { return r.json(); }).then(function (b) {
    var pop = $("#popular"); pop.textContent = "";
    b.popular.forEach(function (q) { pop.appendChild(h("li", {}, h("button", { type: "button", text: q, onclick: function () { closeSide(); ask(q); } }))); });
    var st = $("#starter"); if (st) b.popular.slice(0, 4).forEach(function (q) { st.appendChild(chip(q)); });
    document.title = b.name;
  }).catch(function () {});
  renderHistory(); input.focus();
})();
