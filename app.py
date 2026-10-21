"""TrustFAQ web app. Run:  python app.py   (http://127.0.0.1:5000, admin at /admin)"""
import csv
import io
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db
from engine import Engine
from nlp import redact_pii

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=2 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("FAQ_HTTPS") == "1", PERMANENT_SESSION_LIFETIME=2 * 3600)


def _secret():
    p = os.path.join(HERE, "data", "secret.key")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(p, 0o600)
    return open(p).read().strip()


app.secret_key = os.environ.get("FAQ_SECRET") or _secret()

_state = {"engine": None}
_lock = threading.Lock()
_hits = defaultdict(deque)


def reload_engine():
    eng = Engine(db.list_faqs(True), db.get_settings())
    with _lock:
        _state["engine"] = eng


def limited(key, limit, window):
    now = time.time()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


# ------------------------------------------------------------------ security
@app.after_request
def headers(resp):
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                               "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith(("/api", "/admin")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"):
            if request.path.startswith("/admin/api"):
                return jsonify(error="login required"), 401
            return redirect(url_for("login"))
        if request.method not in ("GET", "HEAD") and not secrets.compare_digest(
                request.headers.get("X-CSRF-Token", ""), session.get("csrf", "")):
            return jsonify(error="bad CSRF token"), 403
        return f(*a, **k)
    return w


def ip():
    return request.remote_addr or "?"


# ------------------------------------------------------------------- public
@app.get("/")
def index():
    return render_template("index.html", name=db.get_settings()["assistant_name"])


@app.get("/api/bootstrap")
def bootstrap():
    s = db.get_settings()
    faqs = db.list_faqs(True)
    pop = db.conn().execute("SELECT faq_id, COUNT(*) n FROM query_log WHERE status='answered' AND faq_id IS NOT NULL "
                            "GROUP BY faq_id ORDER BY n DESC LIMIT 6").fetchall()
    byid = {f["id"]: f for f in faqs}
    popular = [byid[r["faq_id"]]["question"] for r in pop if r["faq_id"] in byid]
    for f in faqs:
        if len(popular) >= 6:
            break
        if f["question"] not in popular:
            popular.append(f["question"])
    return jsonify(name=s["assistant_name"], contact=s["human_contact"], popular=popular,
                   categories=sorted({f["category"] for f in faqs}), faq_count=len(faqs))


@app.post("/api/ask")
def ask():
    if limited(("ask", ip()), 40, 60):
        return jsonify(error="Too many questions. Please wait a minute."), 429
    d = request.get_json(silent=True) or {}
    q = str(d.get("query", "")).strip()
    if not q:
        return jsonify(error="Type a question first."), 400
    if len(q) > 500:
        return jsonify(error="Please keep questions under 500 characters."), 400
    ctx = d.get("context") if isinstance(d.get("context"), dict) else None
    if ctx and not isinstance(ctx.get("last_faq_id"), int):
        ctx = None
    with _lock:
        eng = _state["engine"]
    r = eng.answer(q, ctx)
    s = db.get_settings()
    stored = redact_pii(q) if s.get("redact_pii") == "1" else q
    r["log_id"] = db.log_query(stored, r["language"], r["status"], r.get("faq_id"), r["confidence"], r.get("intent"), r["latency_ms"])
    r["query"] = q
    return jsonify(r)


@app.post("/api/feedback")
def feedback():
    if limited(("fb", ip()), 60, 60):
        return jsonify(error="rate limited"), 429
    d = request.get_json(silent=True) or {}
    if not isinstance(d.get("log_id"), int) or not isinstance(d.get("helpful"), bool):
        return jsonify(error="invalid"), 400
    return jsonify(ok=db.add_feedback(d["log_id"], d["helpful"]))


@app.get("/api/health")
def health():
    e = _state["engine"]
    return jsonify(ok=True, faqs=len(e.faqs), dense=bool(e.dense), dense_error=e.dense_error)


# --------------------------------------------------------------------- admin
@app.route("/admin/login", methods=["GET", "POST"])
def login():
    err = None
    if request.method == "POST":
        if limited(("login", ip()), 5, 300):
            err = "Too many attempts. Try again in 5 minutes."
        elif not secrets.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            err = "Session expired. Reload and try again."
        else:
            row = db.conn().execute("SELECT * FROM admins WHERE username=?", (request.form.get("username", ""),)).fetchone()
            if row and check_password_hash(row["pw_hash"], request.form.get("password", "")):
                session.clear()
                session.permanent = True
                session["admin"] = row["username"]
                csrf_token()
                db.audit(row["username"], "login", ip())
                return redirect(url_for("admin_page"))
            err = "Wrong username or password."
            db.audit("-", "login_failed", f"{request.form.get('username', '')[:40]} from {ip()}")
    return render_template("login.html", error=err, name=db.get_settings()["assistant_name"])


@app.post("/admin/logout")
@admin_required
def logout():
    db.audit(session["admin"], "logout")
    session.clear()
    return jsonify(ok=True)


@app.get("/admin")
@admin_required
def admin_page():
    return render_template("admin.html", name=db.get_settings()["assistant_name"], user=session["admin"])


def _payload(d, partial=False):
    """Validate FAQ input; returns (clean, error)."""
    out = {}
    rules = {"question": (3, 300), "answer": (1, 4000), "category": (0, 60), "intent": (0, 80), "keywords": (0, 400),
             "entities": (0, 400), "source": (0, 200)}
    for k, (lo, hi) in rules.items():
        if k in d:
            if not isinstance(d[k], str) or not (lo <= len(d[k].strip()) <= hi):
                return None, f"{k} must be text of {lo}-{hi} characters"
            out[k] = d[k].strip()
        elif not partial and k in ("question", "answer"):
            return None, f"{k} is required"
    if "alt_questions" in d:
        if not isinstance(d["alt_questions"], list) or len(d["alt_questions"]) > 40:
            return None, "alt_questions must be a list of up to 40 items"
        out["alt_questions"] = [str(x) for x in d["alt_questions"]]
    if "related" in d:
        if not isinstance(d["related"], list) or not all(isinstance(x, int) for x in d["related"]):
            return None, "related must be a list of FAQ ids"
        out["related"] = d["related"][:10]
    if "active" in d:
        out["active"] = bool(d["active"])
    return out, None


@app.get("/admin/api/faqs")
@admin_required
def a_faqs():
    return jsonify(db.list_faqs())


@app.post("/admin/api/faqs")
@admin_required
def a_faq_create():
    d, err = _payload(request.get_json(silent=True) or {})
    if err:
        return jsonify(error=err), 400
    with _lock:
        dup = _state["engine"].similar(d["question"], min_score=0.8)
    fid = db.create_faq(d)
    db.audit(session["admin"], "faq_create", f"#{fid} {d['question'][:80]}")
    reload_engine()
    return jsonify(id=fid, possible_duplicates=dup), 201


@app.put("/admin/api/faqs/<int:fid>")
@admin_required
def a_faq_update(fid):
    d, err = _payload(request.get_json(silent=True) or {}, partial=True)
    if err:
        return jsonify(error=err), 400
    if not db.update_faq(fid, d):
        return jsonify(error="not found"), 404
    db.audit(session["admin"], "faq_update", f"#{fid}")
    reload_engine()
    return jsonify(ok=True)


@app.delete("/admin/api/faqs/<int:fid>")
@admin_required
def a_faq_delete(fid):
    if not db.delete_faq(fid):
        return jsonify(error="not found"), 404
    db.audit(session["admin"], "faq_delete", f"#{fid}")
    reload_engine()
    return jsonify(ok=True)


@app.post("/admin/api/check")
@admin_required
def a_check():
    d = request.get_json(silent=True) or {}
    with _lock:
        return jsonify(_state["engine"].similar(str(d.get("question", ""))[:300], exclude_id=d.get("exclude_id"), min_score=0.5))


@app.post("/admin/api/test")
@admin_required
def a_test():
    """Playground: run the engine without logging; returns full evidence."""
    d = request.get_json(silent=True) or {}
    with _lock:
        return jsonify(_state["engine"].answer(str(d.get("query", ""))[:500]))


@app.get("/admin/api/summary")
@admin_required
def a_summary():
    c = db.conn()
    one = lambda q, *a: c.execute(q, a).fetchone()
    total = one("SELECT COUNT(*) n FROM query_log")["n"]
    by_status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM query_log GROUP BY status")}
    daily = [dict(r) for r in c.execute("SELECT substr(ts,1,10) d, COUNT(*) n, SUM(status='answered') ans, SUM(status IN ('unknown','clarify','ambiguous')) miss "
                                        "FROM query_log GROUP BY d ORDER BY d DESC LIMIT 14")][::-1]
    fb = one("SELECT COUNT(*) n, SUM(helpful) h FROM feedback")
    lat = sorted(r["latency_ms"] for r in c.execute("SELECT latency_ms FROM query_log WHERE latency_ms IS NOT NULL ORDER BY id DESC LIMIT 500"))
    top = [dict(r) for r in c.execute("SELECT f.id, f.question, COUNT(*) n FROM query_log l JOIN faqs f ON f.id=l.faq_id "
                                      "WHERE l.status='answered' GROUP BY f.id ORDER BY n DESC LIMIT 8")]
    langs = {r["language"]: r["n"] for r in c.execute("SELECT language, COUNT(*) n FROM query_log GROUP BY language")}
    return jsonify(total=total, by_status=by_status, daily=daily, languages=langs, top_faqs=top,
                   feedback={"n": fb["n"], "helpful": fb["h"] or 0},
                   latency_p50=lat[len(lat) // 2] if lat else None, latency_p95=lat[int(.95 * (len(lat) - 1))] if lat else None,
                   faqs=len(_state["engine"].faqs), dense=bool(_state["engine"].dense),
                   avg_conf=(one("SELECT AVG(confidence) a FROM query_log WHERE status='answered'")["a"]))


@app.get("/admin/api/gaps")
@admin_required
def a_gaps():
    rows = db.conn().execute("SELECT id, ts, query, status, confidence FROM query_log WHERE status IN ('unknown','clarify','ambiguous') "
                             "ORDER BY id DESC LIMIT 500").fetchall()
    with _lock:
        eng = _state["engine"]
    clusters = eng.cluster([r["query"] for r in rows])
    return jsonify(clusters=clusters, recent=[dict(r) for r in rows[:50]])


@app.get("/admin/api/lowconf")
@admin_required
def a_lowconf():
    rows = db.conn().execute(
        "SELECT l.id, l.ts, l.query, l.confidence, f.question matched, "
        "(SELECT helpful FROM feedback WHERE log_id=l.id ORDER BY id DESC LIMIT 1) helpful "
        "FROM query_log l LEFT JOIN faqs f ON f.id=l.faq_id WHERE l.status='answered' AND "
        "(l.confidence<0.65 OR helpful=0) ORDER BY l.id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/admin/api/quality")
@admin_required
def a_quality():
    c = db.conn()
    stale_days = int(float(db.get_settings()["stale_days"]))
    asked = {r["faq_id"]: r["n"] for r in c.execute("SELECT faq_id, COUNT(*) n FROM query_log WHERE faq_id IS NOT NULL GROUP BY faq_id")}
    votes = {r["faq_id"]: (r["n"], r["h"]) for r in c.execute(
        "SELECT l.faq_id, COUNT(*) n, SUM(fb.helpful) h FROM feedback fb JOIN query_log l ON l.id=fb.log_id WHERE l.faq_id IS NOT NULL GROUP BY l.faq_id")}
    out = []
    for f in db.list_faqs():
        issues, score = [], 100
        age = (datetime.now(timezone.utc) - datetime.strptime(f["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).days
        if len(f["alt_questions"]) < 3:
            issues.append("fewer than 3 alternative questions"); score -= 25
        if age > stale_days:
            issues.append(f"not reviewed for {age} days"); score -= 20
        n, h = votes.get(f["id"], (0, 0))
        if n >= 3 and (h or 0) / n < 0.6:
            issues.append(f"only {round(100 * (h or 0) / n)}% of voters found it helpful"); score -= 30
        if not f["source"]:
            issues.append("no source reference"); score -= 10
        if not f["keywords"]:
            issues.append("no keywords"); score -= 10
        out.append({"id": f["id"], "question": f["question"], "score": max(score, 0), "issues": issues, "asked": asked.get(f["id"], 0), "votes": n})
    return jsonify(sorted(out, key=lambda x: x["score"]))


def _threshold_suggestion():
    rows = db.conn().execute("SELECT l.confidence c, fb.helpful h FROM feedback fb JOIN query_log l ON l.id=fb.log_id "
                             "WHERE l.status='answered'").fetchall()
    for t in [x / 100 for x in range(30, 90, 5)]:
        sel = [r for r in rows if r["c"] >= t]
        if len(sel) >= 10 and sum(r["h"] for r in sel) / len(sel) >= 0.9:
            return {"suggested_answer_threshold": t, "based_on_votes": len(rows)}
    return {"suggested_answer_threshold": None, "based_on_votes": len(rows)}


@app.get("/admin/api/settings")
@admin_required
def a_settings():
    return jsonify(settings=db.get_settings(), suggestion=_threshold_suggestion())


@app.put("/admin/api/settings")
@admin_required
def a_settings_put():
    d = request.get_json(silent=True) or {}
    try:
        for k, v in d.items():
            if k in ("answer_threshold", "clarify_threshold"):
                if not 0.05 <= float(v) <= 0.95:
                    raise ValueError(f"{k} must be between 0.05 and 0.95")
            elif k in ("stale_days", "log_retention_days"):
                if not 1 <= int(float(v)) <= 3650:
                    raise ValueError(f"{k} must be 1-3650")
            elif k == "redact_pii":
                v = "1" if str(v) in ("1", "true", "True") else "0"
            elif len(str(v)) > 200:
                raise ValueError(f"{k} too long")
            db.set_setting(k, v)
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    s = db.get_settings()
    if float(s["clarify_threshold"]) >= float(s["answer_threshold"]):
        return jsonify(error="clarify_threshold must be lower than answer_threshold"), 400
    db.audit(session["admin"], "settings_update", json.dumps(d)[:300])
    reload_engine()
    return jsonify(ok=True)


@app.post("/admin/api/import")
@admin_required
def a_import():
    f = request.files.get("file")
    if not f:
        return jsonify(error="choose a .json or .csv file"), 400
    raw = f.read().decode("utf-8-sig", errors="replace")
    try:
        if f.filename.lower().endswith(".csv"):
            items = list(csv.DictReader(io.StringIO(raw)))
            for it in items:
                it["alt_questions"] = [x for x in (it.get("alt_questions") or "").split("|") if x.strip()]
        else:
            items = json.loads(raw)
    except Exception as e:
        return jsonify(error=f"could not parse file: {e}"), 400
    if not isinstance(items, list) or len(items) > 2000:
        return jsonify(error="expected a list of up to 2000 FAQs"), 400
    existing = {x["question"].strip().lower() for x in db.list_faqs()}
    added, skipped, errors = 0, 0, []
    for i, it in enumerate(items, 1):
        d, err = _payload({k: v for k, v in it.items() if k in ("question", "answer", "category", "intent", "keywords", "entities", "source", "alt_questions")})
        if err:
            errors.append(f"row {i}: {err}")
        elif d["question"].lower() in existing:
            skipped += 1
        else:
            db.create_faq(d); existing.add(d["question"].lower()); added += 1
    db.audit(session["admin"], "import", f"added {added}, skipped {skipped}, errors {len(errors)}")
    reload_engine()
    return jsonify(added=added, skipped_duplicates=skipped, errors=errors[:20])


@app.get("/admin/api/export")
@admin_required
def a_export():
    what = request.args.get("what", "kb")
    if what == "logs":
        rows = db.conn().execute("SELECT ts,query,language,status,faq_id,confidence,intent,latency_ms FROM query_log ORDER BY id").fetchall()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "query", "language", "status", "faq_id", "confidence", "intent", "latency_ms"])
        for r in rows:
            w.writerow([("'" + str(v)) if isinstance(v, str) and v[:1] in "=+-@" else v for v in tuple(r)])  # CSV-injection safe
        return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=query_log.csv"})
    data = [{k: f[k] for k in ("question", "answer", "category", "intent", "keywords", "entities", "source", "alt_questions", "version", "updated_at")}
            for f in db.list_faqs()]
    return Response(json.dumps(data, ensure_ascii=False, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=knowledge_base.json"})


@app.get("/admin/api/audit")
@admin_required
def a_audit():
    return jsonify([dict(r) for r in db.conn().execute("SELECT ts,actor,action,detail FROM audit_log ORDER BY id DESC LIMIT 100")])


@app.post("/admin/api/password")
@admin_required
def a_password():
    d = request.get_json(silent=True) or {}
    row = db.conn().execute("SELECT * FROM admins WHERE username=?", (session["admin"],)).fetchone()
    new = str(d.get("new", ""))
    if not check_password_hash(row["pw_hash"], str(d.get("current", ""))):
        return jsonify(error="current password is wrong"), 400
    if len(new) < 10:
        return jsonify(error="new password must be at least 10 characters"), 400
    db.conn().execute("UPDATE admins SET pw_hash=? WHERE username=?", (generate_password_hash(new), row["username"]))
    db.conn().commit()
    db.audit(row["username"], "password_change")
    return jsonify(ok=True)


# ------------------------------------------------------------------- startup
def bootstrap_app():
    db.init_db()
    n = db.seed_if_empty(os.path.join(HERE, "data", "seed_faqs.json"))
    if n:
        print(f"[setup] seeded {n} sample FAQs")
    user = os.environ.get("FAQ_ADMIN_USER", "admin")
    if not db.conn().execute("SELECT 1 FROM admins").fetchone():
        pw = os.environ.get("FAQ_ADMIN_PASSWORD")
        generated = pw is None
        pw = pw or secrets.token_urlsafe(12)
        db.conn().execute("INSERT INTO admins(username,pw_hash) VALUES(?,?)", (user, generate_password_hash(pw)))
        db.conn().commit()
        if generated:
            print(f"[setup] admin account created -> username: {user}  password: {pw}   (shown once; change it in Settings)")
    db.purge_old_logs(db.get_settings()["log_retention_days"])
    reload_engine()


bootstrap_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("FAQ_HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
