"""SQLite persistence: FAQs, alternative questions, query log, feedback, admins, settings, audit log."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("FAQ_DB", os.path.join(os.path.dirname(__file__), "data", "faq.db"))
_local = threading.local()

DEFAULT_SETTINGS = {
    "answer_threshold": "0.45",     # >= : answer directly (chosen from the evaluate.py sweep)
    "clarify_threshold": "0.30",    # between : "did you mean" with suggestions
    "stale_days": "180",            # answers older than this carry a "may be outdated" notice
    "log_retention_days": "90",
    "redact_pii": "1",
    "assistant_name": "Campus Help Desk",
    "human_contact": "helpdesk@example.edu | +91-00000-00000",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS faqs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, answer TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'General', intent TEXT NOT NULL DEFAULT '', keywords TEXT NOT NULL DEFAULT '',
  entities TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
  related TEXT NOT NULL DEFAULT '[]', active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alt_questions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, faq_id INTEGER NOT NULL REFERENCES faqs(id) ON DELETE CASCADE, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS query_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, query TEXT NOT NULL, language TEXT, status TEXT NOT NULL,
  faq_id INTEGER, confidence REAL, intent TEXT, latency_ms REAL);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, log_id INTEGER NOT NULL, helpful INTEGER NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admins(username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS idx_log_ts ON query_log(ts);
CREATE INDEX IF NOT EXISTS idx_log_status ON query_log(status);
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conn():
    c = getattr(_local, "c", None)
    if c is None or getattr(_local, "path", None) != DB_PATH:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        _local.c, _local.path = c, DB_PATH
    return c


def init_db():
    c = conn()
    c.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    c.commit()


def get_settings():
    return {r["key"]: r["value"] for r in conn().execute("SELECT key,value FROM settings")}


def set_setting(key, value):
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"unknown setting {key}")
    conn().execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, str(value)))
    conn().commit()


# ---------- FAQs ----------
def _faq_row(r, alts):
    d = dict(r)
    d["related"] = json.loads(d["related"] or "[]")
    d["alt_questions"] = alts.get(d["id"], [])
    return d


def list_faqs(active_only=False):
    c = conn()
    alts = {}
    for a in c.execute("SELECT faq_id,text FROM alt_questions ORDER BY id"):
        alts.setdefault(a["faq_id"], []).append(a["text"])
    q = "SELECT * FROM faqs" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
    return [_faq_row(r, alts) for r in c.execute(q)]


def get_faq(fid):
    r = conn().execute("SELECT * FROM faqs WHERE id=?", (fid,)).fetchone()
    if not r:
        return None
    alts = {fid: [a["text"] for a in conn().execute("SELECT text FROM alt_questions WHERE faq_id=? ORDER BY id", (fid,))]}
    return _faq_row(r, alts)


def _clean_alts(alts):
    seen, out = set(), []
    for a in alts or []:
        a = (a or "").strip()
        if a and a.lower() not in seen:
            seen.add(a.lower())
            out.append(a[:300])
    return out


def create_faq(d):
    c, t = conn(), now()
    cur = c.execute(
        "INSERT INTO faqs(question,answer,category,intent,keywords,entities,source,related,active,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (d["question"].strip(), d["answer"].strip(), (d.get("category") or "General").strip(),
         (d.get("intent") or "").strip(), (d.get("keywords") or "").strip(), (d.get("entities") or "").strip(),
         (d.get("source") or "").strip(), json.dumps(d.get("related") or []), 1 if d.get("active", True) else 0, t, t))
    fid = cur.lastrowid
    if not d.get("intent"):
        c.execute("UPDATE faqs SET intent=? WHERE id=?", (f"faq_{fid}", fid))
    for a in _clean_alts(d.get("alt_questions")):
        c.execute("INSERT INTO alt_questions(faq_id,text) VALUES(?,?)", (fid, a))
    c.commit()
    return fid


def update_faq(fid, d):
    c = conn()
    old = get_faq(fid)
    if not old:
        return False
    content_changed = any(str(d.get(k, old[k])).strip() != str(old[k]).strip() for k in ("question", "answer"))
    c.execute(
        "UPDATE faqs SET question=?,answer=?,category=?,intent=?,keywords=?,entities=?,source=?,related=?,active=?,"
        "version=version+?,updated_at=? WHERE id=?",
        (d.get("question", old["question"]).strip(), d.get("answer", old["answer"]).strip(),
         (d.get("category", old["category"]) or "General").strip(), (d.get("intent", old["intent"]) or f"faq_{fid}").strip(),
         d.get("keywords", old["keywords"]).strip(), d.get("entities", old["entities"]).strip(),
         d.get("source", old["source"]).strip(), json.dumps(d.get("related", old["related"])),
         1 if d.get("active", bool(old["active"])) else 0, 1 if content_changed else 0, now(), fid))
    if "alt_questions" in d:
        c.execute("DELETE FROM alt_questions WHERE faq_id=?", (fid,))
        for a in _clean_alts(d["alt_questions"]):
            c.execute("INSERT INTO alt_questions(faq_id,text) VALUES(?,?)", (fid, a))
    c.commit()
    return True


def delete_faq(fid):
    cur = conn().execute("DELETE FROM faqs WHERE id=?", (fid,))
    conn().commit()
    return cur.rowcount > 0


# ---------- logs / feedback ----------
def log_query(query, language, status, faq_id, confidence, intent, latency_ms):
    cur = conn().execute(
        "INSERT INTO query_log(ts,query,language,status,faq_id,confidence,intent,latency_ms) VALUES(?,?,?,?,?,?,?,?)",
        (now(), query, language, status, faq_id, confidence, intent, latency_ms))
    conn().commit()
    return cur.lastrowid


def add_feedback(log_id, helpful):
    if not conn().execute("SELECT 1 FROM query_log WHERE id=?", (log_id,)).fetchone():
        return False
    conn().execute("INSERT INTO feedback(log_id,helpful,ts) VALUES(?,?,?)", (log_id, 1 if helpful else 0, now()))
    conn().commit()
    return True


def audit(actor, action, detail=""):
    conn().execute("INSERT INTO audit_log(ts,actor,action,detail) VALUES(?,?,?,?)", (now(), actor, action, detail[:500]))
    conn().commit()


def purge_old_logs(days):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).strftime("%Y-%m-%dT%H:%M:%SZ")
    c = conn()
    c.execute("DELETE FROM feedback WHERE log_id IN (SELECT id FROM query_log WHERE ts<?)", (cutoff,))
    c.execute("DELETE FROM query_log WHERE ts<?", (cutoff,))
    c.commit()


def seed_if_empty(path):
    if conn().execute("SELECT COUNT(*) n FROM faqs").fetchone()["n"]:
        return 0
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    id_map = {}
    for it in items:
        id_map[it["key"]] = create_faq(it)
    for it in items:  # resolve related keys -> ids
        rel = [id_map[k] for k in it.get("related_keys", []) if k in id_map]
        if rel:
            update_faq(id_map[it["key"]], {"related": rel})
    return len(items)
