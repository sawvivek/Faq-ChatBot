# TrustFAQ — NLP-based FAQ assistant (Python)

A confidence-aware FAQ assistant that **answers only from a verified knowledge base** and says "I don't know" instead of guessing.
Runs fully offline on CPU (Flask + scikit-learn + SQLite). No model download, no API keys, no internet.

## Run it
```bash
pip install -r requirements.txt
python app.py                 # prints the admin password once on first run
# user app:   http://127.0.0.1:5000        admin: http://127.0.0.1:5000/admin
python evaluate.py --report docs/evaluation_report.md   # reproduce the numbers
python -m pytest -q tests                                # 13 tests
```
Set your own admin login: `FAQ_ADMIN_USER=admin FAQ_ADMIN_PASSWORD='...' python app.py` (before first run).
Serve over HTTPS in production and set `FAQ_HTTPS=1` (secure cookies). Use gunicorn/waitress instead of the dev server.

## What is in the box
| Path | Role |
|---|---|
| `nlp.py` | normalise, spell-correct (against KB vocabulary), synonym/Hinglish/Devanagari canonicalisation, stemming, language detection, PII redaction |
| `engine.py` | hybrid retrieval (word TF-IDF + char n-gram TF-IDF + BM25 + weighted term coverage), intent classifier, confidence, follow-ups, FAQ-gap clustering, optional sentence embeddings |
| `db.py` | SQLite: FAQs, alternative questions, query log, feedback, admins, settings, audit log |
| `app.py` | Flask API, admin API, CSRF, rate limiting, CSP headers, password hashing |
| `templates/`, `static/` | chat UI (light/dark, responsive, keyboard + screen-reader friendly) and admin dashboard |
| `data/seed_faqs.json` | 27 sample FAQs for a fictional institute (replace via Admin → Import) |
| `data/eval_set.json`, `evaluate.py` | 86-query test set across 10 categories, metrics, calibration, threshold sweep |
| `docs/PROJECT_REPORT.md` | research, architecture, comparisons, security, evaluation, USP, limitations, references |

## Decision flow (the core idea)
```
question -> normalise -> hybrid retrieval -> confidence = f(score, margin vs runner-up, intent agreement)
   conf >= answer threshold  -> answer (verbatim from KB) + source + related FAQs   [or "which did you mean?" if two topics tie]
   conf >= clarify threshold -> "Did you mean..." with the closest FAQs
   otherwise                 -> "I don't have verified information", contact info, logged for admins
```
The assistant never generates free text: every answer is a stored, versioned, sourced FAQ answer, so it cannot hallucinate.

## Admin features
Login (hashed password, lockout, CSRF) · add/edit/delete/hide FAQs with live duplicate warning · alternative questions · import/export JSON/CSV ·
unanswered-question clusters with one-click "Create FAQ" · low-confidence/not-helpful review · KB quality scores · engine playground with ranking evidence ·
thresholds with feedback-based suggestion · PII masking and log retention · audit log.

## Demo script (≈6 minutes)
1. Admin login → Overview. 2. Knowledge base → Add FAQ "Is there a gym on campus?" (note duplicate check) → Save (index rebuilds instantly).
3. Assistant: ask exactly that, then "where can I work out", then "is there a gimm in college" (typo). 4. Ask "weather in Mumbai" → refusal + logged.
5. Ask "hostel" → "which did you mean?". 6. Ask "How do I get a hostel room?" then "and the timings?" (follow-up). 7. Ask "फीस कितनी है" and "hostel ki fees kitni hai".
8. Open "Why this answer?" (ranking evidence, spelling correction). Click Not helpful. 9. Admin → Unanswered (cluster) → Review → Quality → Test the engine.
10. Stop the server, restart: data persists (SQLite). Disconnect Wi-Fi: everything still works.

## Optional: semantic embeddings (paraphrase handling)
```bash
pip install sentence-transformers
FAQ_USE_EMBEDDINGS=1 FAQ_EMBED_MODEL=paraphrase-multilingual-MiniLM-L12-v2 python app.py
```
The model downloads once, then runs offline on CPU. If unavailable the engine silently falls back to the lexical hybrid (`/api/health` shows `dense_error`).
**This path was not exercised in the build environment** (no access to the model host): re-run `evaluate.py` with it on and compare before relying on it.
# Faq-ChatBot
