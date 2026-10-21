(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var csrf = $('meta[name="csrf"]').content, root = document.documentElement;
  try { var t = localStorage.getItem("theme"); if (t) root.dataset.theme = t; } catch (e) {}
  $("#theme").addEventListener("click", function () { root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark"; try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {} });

  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (k === "class") el.className = v; else if (k === "style") el.style.cssText = v; else if (k === "text") el.textContent = v; else if (k === "value") el.value = v;
      else if (k === "checked") el.checked = !!v; else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
    });
    for (var i = 2; i < arguments.length; i++) { var c = arguments[i]; if (c == null) continue; if (Array.isArray(c)) c.forEach(function (x) { if (x != null) el.appendChild(typeof x === "string" ? document.createTextNode(x) : x); }); else el.appendChild(typeof c === "string" ? document.createTextNode(c) : c); }
    return el;
  }
  function api(path, opt) {
    opt = opt || {}; var o = { method: opt.method || "GET", headers: { "X-CSRF-Token": csrf }, credentials: "same-origin" };
    if (opt.json !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opt.json); }
    if (opt.form) o.body = opt.form;
    return fetch("/admin/api/" + path, o).then(function (r) {
      if (r.status === 401) { location.href = "/admin/login"; throw new Error("login"); }
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || "Request failed"); return j; });
    });
  }
  var toastT; function toast(msg, bad) { var t = $("#toast"); t.textContent = msg; t.className = "toast show" + (bad ? " bad" : ""); clearTimeout(toastT); toastT = setTimeout(function () { t.className = "toast"; }, 3500); }
  function fail(e) { if (e.message !== "login") toast(e.message, true); }
  function table(head, rows, empty) {
    if (!rows.length) return h("p", { "class": "muted", text: empty || "Nothing to show yet." });
    return h("table", {}, h("thead", {}, h("tr", {}, head.map(function (x) { return h("th", { scope: "col", text: x }); }))), h("tbody", {}, rows.map(function (r) { return h("tr", {}, r.map(function (c) { return h("td", {}, c); })); })));
  }
  var pct = function (x) { return x == null ? "n/a" : Math.round(x * 100) + "%"; };

  var TABS = [["overview", "Overview"], ["kb", "Knowledge base"], ["gaps", "Unanswered"], ["review", "Review"], ["quality", "Quality"], ["play", "Test the engine"], ["settings", "Settings"], ["activity", "Activity"]];
  var tabs = $("#tabs"), panel = $("#panel"), current = "overview";
  TABS.forEach(function (t) { tabs.appendChild(h("button", { role: "tab", id: "tab-" + t[0], "aria-selected": "false", text: t[1], onclick: function () { show(t[0]); } })); });
  function show(name) {
    current = name; Array.prototype.forEach.call(tabs.children, function (b) { b.setAttribute("aria-selected", b.id === "tab-" + name ? "true" : "false"); });
    panel.textContent = ""; panel.appendChild(h("p", { "class": "muted", text: "Loading…" })); history.replaceState(null, "", "#" + name);
    VIEWS[name]().then(function (nodes) { panel.textContent = ""; nodes.forEach(function (n) { panel.appendChild(n); }); }).catch(fail);
  }
  $("#logout").addEventListener("click", function () { fetch("/admin/logout", { method: "POST", headers: { "X-CSRF-Token": csrf } }).then(function () { location.href = "/admin/login"; }); });

  // ------------------------------------------------------------ views
  var VIEWS = {};
  VIEWS.overview = function () {
    return api("summary").then(function (s) {
      var bs = s.by_status || {}, miss = (bs.unknown || 0) + (bs.clarify || 0) + (bs.ambiguous || 0), real = (bs.answered || 0) + miss;
      var stat = function (v, l) { return h("div", { "class": "stat" }, h("b", { text: String(v) }), h("span", { text: l })); };
      var max = Math.max.apply(null, s.daily.map(function (d) { return d.n; }).concat([1]));
      var spark = h("div", { "class": "spark", role: "img", "aria-label": "Questions per day, last 14 days" }, s.daily.map(function (d) { var c = h("div", { title: d.d + ": " + d.n + " questions" }, h("i")); c.style.height = Math.max(6, d.n / max * 100) + "%"; c.firstChild.style.height = (d.n ? d.ans / d.n * 100 : 0) + "%"; return c; }));
      return [
        h("div", { "class": "grid" }, [stat(s.total, "questions asked"), stat(real ? pct((bs.answered || 0) / real) : "n/a", "answered"), stat(real ? pct(miss / real) : "n/a", "not answered / unclear"), stat(s.feedback.n ? pct(s.feedback.helpful / s.feedback.n) : "n/a", "found helpful (" + s.feedback.n + " votes)"), stat(s.faqs, "active FAQs"), stat(s.latency_p50 == null ? "n/a" : s.latency_p50 + " ms", "median response" + (s.latency_p95 ? " (p95 " + s.latency_p95 + " ms)" : ""))]),
        h("div", { "class": "box" }, h("h3", { text: "Questions per day (dark part = answered)" }), s.daily.length ? spark : h("p", { "class": "muted", text: "No questions yet. Open the assistant and ask something." })),
        h("div", { "class": "two" },
          h("div", { "class": "box" }, h("h3", { text: "Most asked FAQs" }), table(["FAQ", "Times"], s.top_faqs.map(function (f) { return [f.question, String(f.n)]; }), "No answered questions yet.")),
          h("div", { "class": "box" }, h("h3", { text: "Languages seen" }), table(["Language", "Questions"], Object.keys(s.languages).map(function (k) { return [k || "unknown", String(s.languages[k])]; }), "No data yet."), h("p", { "class": "fine", text: "Semantic engine: " + (s.dense ? "sentence embeddings on" : "lexical hybrid (offline, no model download)") })))
      ];
    });
  };

  var faqCache = [];
  VIEWS.kb = function () {
    return api("faqs").then(function (faqs) {
      faqCache = faqs;
      var cats = Array.from(new Set(faqs.map(function (f) { return f.category; }))).sort();
      var q = h("input", { type: "search", placeholder: "Search FAQs", "aria-label": "Search FAQs" }), cat = h("select", { "aria-label": "Filter by category" }, h("option", { value: "", text: "All categories" }), cats.map(function (c) { return h("option", { value: c, text: c }); }));
      var holder = h("div", { "class": "box" });
      function draw() {
        var t = q.value.toLowerCase(), c = cat.value;
        var rows = faqs.filter(function (f) { return (!c || f.category === c) && (!t || (f.question + " " + f.answer + " " + f.keywords).toLowerCase().indexOf(t) >= 0); }).map(function (f) {
          return [String(f.id), h("span", {}, f.question, f.active ? "" : h("span", { "class": "tag", text: "hidden" })), f.category, String(f.alt_questions.length), "v" + f.version + " · " + f.updated_at.slice(0, 10),
            h("span", { "class": "toolbar" }, h("button", { "class": "btn small ghost", text: "Edit", "aria-label": "Edit FAQ " + f.id, onclick: function () { edit(f); } }), h("button", { "class": "btn small danger", text: "Delete", "aria-label": "Delete FAQ " + f.id, onclick: function () { del(f); } }))];
        });
        holder.textContent = ""; holder.appendChild(table(["ID", "Question", "Category", "Alt. questions", "Version", ""], rows, "No FAQs match."));
      }
      q.addEventListener("input", draw); cat.addEventListener("change", draw); draw();
      var file = h("input", { type: "file", accept: ".json,.csv", "class": "sr", id: "imp", onchange: function () {
        var fd = new FormData(); fd.append("file", file.files[0]);
        api("import", { method: "POST", form: fd }).then(function (r) { toast("Imported " + r.added + ", skipped " + r.skipped_duplicates + " duplicates" + (r.errors.length ? ", " + r.errors.length + " rows had errors: " + r.errors[0] : "")); show("kb"); }).catch(fail);
      } });
      return [h("div", { "class": "toolbar" }, q, cat, h("button", { "class": "btn", text: "Add FAQ", onclick: function () { edit(null); } }), h("label", { "class": "btn ghost", "for": "imp", style: "cursor:pointer", text: "Import JSON/CSV" }), file, h("a", { "class": "btn ghost", href: "/admin/api/export?what=kb", text: "Export JSON" })), holder];
    });
  };
  function del(f) { if (confirm('Delete FAQ #' + f.id + ' "' + f.question + '"? This cannot be undone.')) api("faqs/" + f.id, { method: "DELETE" }).then(function () { toast("FAQ deleted"); show("kb"); }).catch(fail); }
  function edit(f, prefill) {
    f = f || { question: prefill || "", answer: "", category: "General", intent: "", keywords: "", source: "", alt_questions: [], related: [], active: 1 };
    var d = $("#dlg"), dupBox = h("p", { "class": "notice", hidden: "hidden", role: "status" });
    var F = {
      question: h("input", { value: f.question, required: "required", maxlength: 300 }), answer: h("textarea", { rows: 5, required: "required", maxlength: 4000, value: f.answer }),
      category: h("input", { value: f.category, maxlength: 60 }), intent: h("input", { value: f.intent, maxlength: 80, placeholder: "auto" }), keywords: h("input", { value: f.keywords, maxlength: 400 }),
      source: h("input", { value: f.source, maxlength: 200, placeholder: "Document name, page" }), alts: h("textarea", { rows: 5, value: f.alt_questions.join("\n") }),
      related: h("input", { value: (f.related || []).join(", "), placeholder: "FAQ ids, e.g. 3, 7" }), active: h("input", { type: "checkbox", checked: f.active, style: "width:auto" })
    };
    F.question.addEventListener("change", function () { api("check", { method: "POST", json: { question: F.question.value, exclude_id: f.id } }).then(function (r) { if (r.length) { dupBox.hidden = false; dupBox.textContent = "Similar existing FAQ: " + r.map(function (x) { return '#' + x.faq_id + ' "' + x.question + '"'; }).join("; ") + ". Consider editing that one instead."; } else dupBox.hidden = true; }).catch(function () {}); });
    var L = function (t, el, hint) { return h("label", {}, t, el, hint ? h("span", { "class": "fine", text: hint }) : null); };
    d.textContent = "";
    d.appendChild(h("form", { method: "dialog", onsubmit: function (e) {
      e.preventDefault();
      var body = { question: F.question.value, answer: F.answer.value, category: F.category.value, intent: F.intent.value, keywords: F.keywords.value, source: F.source.value, active: F.active.checked,
        alt_questions: F.alts.value.split("\n").map(function (x) { return x.trim(); }).filter(Boolean), related: F.related.value.split(",").map(function (x) { return parseInt(x, 10); }).filter(function (x) { return !isNaN(x); }) };
      api(f.id ? "faqs/" + f.id : "faqs", { method: f.id ? "PUT" : "POST", json: body }).then(function (r) { d.close(); toast(f.id ? "FAQ updated. Index rebuilt." : "FAQ added. Index rebuilt." + (r.possible_duplicates && r.possible_duplicates.length ? " Note: similar FAQ exists." : "")); show(current); }).catch(fail);
    } },
      h("h3", { text: f.id ? "Edit FAQ #" + f.id : "Add FAQ" }), L("Question", F.question), dupBox, L("Answer", F.answer, "Write exactly what the assistant should say. It never adds to this text."),
      h("div", { "class": "two" }, L("Category", F.category), L("Source", F.source, "Shown to users as evidence")),
      L("Alternative questions", F.alts, "One per line, including Hindi, Marathi or Hinglish phrasings. More variety means better matching."),
      h("div", { "class": "two" }, L("Keywords", F.keywords), L("Intent label", F.intent)), L("Related FAQ ids", F.related),
      h("label", { style: "flex-direction:row;align-items:center;gap:8px" }, F.active, "Visible to users"),
      h("div", { "class": "toolbar" }, h("button", { "class": "btn", type: "submit", text: "Save FAQ" }), h("button", { "class": "btn ghost", type: "button", text: "Cancel", onclick: function () { d.close(); } }))));
    d.showModal(); F.question.focus();
  }

  VIEWS.gaps = function () {
    return api("gaps").then(function (g) {
      return [h("div", { "class": "box" }, h("h3", { text: "Topics users ask about that the FAQ doesn't cover" }), h("p", { "class": "fine", text: "Similar unanswered or unclear questions are grouped so you can write one FAQ per topic." }),
        table(["Asked", "Example questions", ""], g.clusters.map(function (c) { return [String(c.size), c.examples.join(" | "), h("button", { "class": "btn small", text: "Create FAQ", onclick: function () { edit(null, c.examples[0]); } })]; }), "No unanswered questions logged yet.")),
        h("div", { "class": "box" }, h("h3", { text: "Most recent unanswered or unclear" }), table(["When", "Question", "Outcome", "Confidence"], g.recent.map(function (r) { return [r.ts.replace("T", " ").slice(0, 16), r.query, r.status, pct(r.confidence)]; }), "None."))];
    });
  };
  VIEWS.review = function () {
    return api("lowconf").then(function (rows) {
      return [h("div", { "class": "box" }, h("h3", { text: "Answers worth a human look" }), h("p", { "class": "fine", text: "Answered with confidence below 65%, or marked not helpful by the user." }),
        table(["When", "Question asked", "Answered with", "Confidence", "Feedback"], rows.map(function (r) { return [r.ts.replace("T", " ").slice(0, 16), r.query, r.matched || "-", pct(r.confidence), r.helpful === 0 ? "Not helpful" : r.helpful === 1 ? "Helpful" : "-"]; }), "Nothing to review."))];
    });
  };
  VIEWS.quality = function () {
    return api("quality").then(function (rows) {
      return [h("div", { "class": "box" }, h("h3", { text: "Knowledge-base quality" }), h("p", { "class": "fine", text: "Score starts at 100 and loses points for few alternative questions, staleness, low helpfulness and missing source or keywords. Lowest first." }),
        table(["Score", "FAQ", "Asked", "Issues"], rows.map(function (r) { return [String(r.score), "#" + r.id + " " + r.question, String(r.asked), r.issues.length ? r.issues.map(function (i) { return h("span", { "class": "tag", text: i }); }) : "None"]; })))];
    });
  };
  VIEWS.play = function () {
    var out = h("div"), inp = h("input", { placeholder: "Type a test question", "aria-label": "Test question" });
    function run() {
      api("test", { method: "POST", json: { query: inp.value } }).then(function (r) {
        out.textContent = "";
        out.appendChild(h("div", { "class": "grid" }, [["status", r.status], ["confidence", pct(r.confidence)], ["language", r.language], ["intent", r.intent || "n/a"], ["latency", r.latency_ms + " ms"]].map(function (x) { return h("div", { "class": "stat" }, h("b", { text: x[1], style: "font-size:1.2rem" }), h("span", { text: x[0] })); })));
        if (r.corrected_query) out.appendChild(h("p", { "class": "fine", text: "Spelling-corrected: " + r.corrected_query }));
        if (r.answer) out.appendChild(h("p", { text: r.answer }));
        if (r.message) out.appendChild(h("p", { text: r.message }));
        out.appendChild(h("div", { "class": "box" }, h("h3", { text: "Ranking evidence" }), table(["FAQ", "Score", "Words", "Chars", "BM25", "Coverage", "Matched text"], (r.evidence || []).map(function (e) { var p = e.parts; return [e.question, pct(e.score), pct(p.word), pct(p.char), pct(p.bm25), pct(p.cov), e.matched]; }), "No candidates.")));
      }).catch(fail);
    }
    inp.addEventListener("keydown", function (e) { if (e.key === "Enter") run(); });
    return Promise.resolve([h("div", { "class": "toolbar" }, inp, h("button", { "class": "btn", text: "Run", onclick: run })), h("p", { "class": "fine", text: "Test queries are not logged and do not affect analytics." }), out]);
  };
  VIEWS.settings = function () {
    return api("settings").then(function (r) {
      var s = r.settings, F = {};
      function field(key, label, hint, type) { F[key] = h("input", { value: s[key], type: type || "text" }); return h("label", {}, label, F[key], hint ? h("span", { "class": "fine", text: hint }) : null); }
      var red = h("input", { type: "checkbox", checked: s.redact_pii === "1", style: "width:auto" });
      var sug = r.suggestion.suggested_answer_threshold;
      var form = h("form", { "class": "box", style: "display:flex;flex-direction:column;gap:12px;max-width:640px", onsubmit: function (e) {
        e.preventDefault(); var body = {}; Object.keys(F).forEach(function (k) { body[k] = F[k].value; }); body.redact_pii = red.checked ? "1" : "0";
        api("settings", { method: "PUT", json: body }).then(function () { toast("Settings saved. Engine reloaded."); }).catch(fail);
      } },
        h("h3", { text: "Assistant" }), field("assistant_name", "Assistant name"), field("human_contact", "Human contact shown for unknown questions"),
        h("h3", { text: "Confidence thresholds" }), field("answer_threshold", "Answer directly at or above", "Higher = fewer wrong answers but more 'not sure' replies. Check the sweep in docs/evaluation_report.md.", "number"),
        field("clarify_threshold", "Ask 'did you mean…' at or above", "Below this the assistant says it doesn't know.", "number"),
        h("p", { "class": "fine", text: sug ? "Based on " + r.suggestion.based_on_votes + " feedback votes, " + sug + " is the lowest threshold where at least 90% of answers were rated helpful." : "Suggestion appears once at least 10 answers have feedback (" + r.suggestion.based_on_votes + " votes so far)." }),
        h("h3", { text: "Privacy and freshness" }), field("stale_days", "Warn users when an answer is older than (days)", "", "number"), field("log_retention_days", "Delete query logs after (days)", "", "number"),
        h("label", { style: "flex-direction:row;align-items:center;gap:8px" }, red, "Mask emails, phone numbers and ID numbers before logging"),
        h("div", {}, h("button", { "class": "btn", type: "submit", text: "Save settings" })));
      var cur = h("input", { type: "password", autocomplete: "current-password" }), nw = h("input", { type: "password", autocomplete: "new-password" });
      var pw = h("form", { "class": "box", style: "display:flex;flex-direction:column;gap:12px;max-width:640px", onsubmit: function (e) { e.preventDefault(); api("password", { method: "POST", json: { current: cur.value, "new": nw.value } }).then(function () { toast("Password changed"); cur.value = nw.value = ""; }).catch(fail); } },
        h("h3", { text: "Change password" }), h("label", {}, "Current password", cur), h("label", {}, "New password", nw, h("span", { "class": "fine", text: "At least 10 characters." })), h("div", {}, h("button", { "class": "btn", type: "submit", text: "Change password" })));
      var data = h("div", { "class": "box" }, h("h3", { text: "Backup and offline sync" }), h("p", { "class": "fine", text: "Everything is stored locally in SQLite. To move data between an offline install and a connected one, export here and import there." }),
        h("div", { "class": "toolbar" }, h("a", { "class": "btn ghost", href: "/admin/api/export?what=kb", text: "Export knowledge base" }), h("a", { "class": "btn ghost", href: "/admin/api/export?what=logs", text: "Export query log (CSV)" })));
      return [form, pw, data];
    });
  };
  VIEWS.activity = function () {
    return api("audit").then(function (rows) { return [h("div", { "class": "box" }, h("h3", { text: "Admin activity" }), table(["When (UTC)", "Who", "Action", "Detail"], rows.map(function (r) { return [r.ts.replace("T", " ").slice(0, 19), r.actor, r.action, r.detail || ""]; })))]; });
  };

  show((location.hash || "#overview").slice(1) in VIEWS ? location.hash.slice(1) : "overview");
})();
