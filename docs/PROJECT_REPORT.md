# TrustFAQ: A Confidence-Aware NLP FAQ Assistant — Project Report

> **Evidence note.** Sections 2-3 summarise well-known public systems and papers from background knowledge; no live web research was run while building this.
> Verify any specific system claim and add page-level citations before submitting. Section 11 numbers come from `evaluate.py` and are reproducible.

## 1. Introduction, problem statement, objectives
**Problem.** Institutions answer the same questions repeatedly; static FAQ pages are hard to search; keyword search misses paraphrases; chatbots that always answer
(especially generative ones) can state wrong facts confidently.
**Objective.** Build a system whose rule is: *answer when evidence is sufficient, ask when unclear, refuse when unknown, never invent.*
Priority order: correctness > confidence honesty > relevance > speed.

## 2. Evolution of FAQ / question-answering systems
| Generation | How it worked | Handles paraphrase | Typos | Context | Unknown detection | Maintenance | Typical use |
|---|---|---|---|---|---|---|---|
| Static FAQ page | Human scrolls/Ctrl-F | No | No | No | n/a | Easy but unsearchable at scale | Websites |
| Keyword search | Boolean/term match over text | Weak (needs same words) | No | No | "0 results" only | Easy | Intranets |
| Pattern matching (ELIZA 1966, AIML/ALICE) | Hand-written regex/templates | No | No | Minimal | Default reply | Brittle, grows unmanageably | Early chatbots |
| Decision trees / menu bots | Fixed button flows | n/a (no free text) | n/a | Within flow | n/a | Medium | IVR, banking menus |
| Early NLP QA (rules + parsing, IBM Watson-style pipelines) | Parsing, entity typing, large engineered pipelines | Partial | Partial | Limited | Weak | Expensive | Research, quiz shows |
| TF-IDF / BM25 retrieval | Weighted term overlap, cosine ranking | Weak-moderate | No (char n-grams fix it) | No | Needs threshold | Easy | Search engines, FAQ retrieval |
| ML intent classifiers | Train SVM/LR/NN on labelled utterances → intent → canned answer | Good for trained intents | Partial | Dialogue-manager dependent | Needs "out-of-scope" class | Needs labelled data per intent | Rasa/Dialogflow-style bots |
| Embedding retrieval (Word2Vec/GloVe → SBERT, DPR) | Dense vectors, cosine/ANN search | **Good** | Moderate | No | Needs calibration | Needs model; re-embed on change | Modern semantic FAQ |
| LLM assistants | Generate text from parameters | Very good | Good | Good | **Poor by default** (hallucination) | Prompt-level | General assistants |
| RAG | Retrieve passages, LLM writes grounded answer | Very good | Good | Good | Good *if* retrieval gated | Index + LLM ops | Enterprise knowledge bots |

Cross-cutting lessons: (a) vocabulary mismatch is the oldest failure; (b) every generation without a calibrated "I don't know" gives confident wrong answers;
(c) maintainability decides whether a deployment survives, which is why TrustFAQ treats the admin loop as a first-class feature.

## 3. Existing and current systems — what they show
*Examples (verify before citing):* IRCTC AskDISHA, SBI SIA and HDFC EVA (Indian banking/travel assistants), Bhashini (government multilingual NLP platform), university admission bots
such as Georgia State's "Pounce" and Georgia Tech's "Jill Watson" teaching assistant (international), plus vendor platforms (Dialogflow, Rasa, Azure QnA/Language, Amazon Lex).

Recurring gaps seen across them:
| Gap | Consequence | TrustFAQ response |
|---|---|---|
| Confident answers to out-of-scope questions | Wrong guidance, lost trust | Thresholds, coverage, out-of-vocabulary penalty, refusal path |
| Hallucination in generative layers | Invented fees/dates | Extractive answers only; verbatim KB text |
| No source/version shown | User can't verify | Source, version, last-updated on every answer |
| Stale answers | Outdated deadlines | Staleness notice + quality dashboard |
| Cloud-only, data leaves the premises | Privacy, outages | Fully local; PII masked in logs |
| Weak Indian-language/code-mixed support | Excludes users | Devanagari + Hinglish canonicalisation, multilingual alt-questions, optional multilingual embeddings |
| No feedback loop into the KB | Same gaps persist | Unanswered-query clustering → "Create FAQ" |

## 4. Where modern systems still fall short (the gap TrustFAQ targets)
Modern semantic/LLM systems paraphrase well but are costly to run offline, hard to audit, and tend to answer anyway. A small, auditable, offline system that is *calibrated about its own ignorance* is a defensible niche.

## 5. Purpose
Understand natural-language questions; normalise and correct input; retrieve and rank FAQs; score confidence; answer, clarify or refuse; keep conversational context for follow-ups;
let administrators manage the KB; surface what users ask that the KB cannot answer.

## 6. NLP pipeline — decisions and reasons
| Stage | Chosen | Why / what was rejected |
|---|---|---|
| Cleaning | NFKC, lowercase, strip apostrophes | Needed for Devanagari + Latin mix |
| Spell correction | Edit-distance match **against the KB's own vocabulary**, strict (same first letter, ratio ≥0.82; ≥0.88 for ≤5 letters) | A general dictionary "fixed" *paris* to *paisa*; domain vocabulary is safer |
| Normalisation | Synonym / Hinglish / Devanagari → canonical English token; applied before and after stemming | Cheap, explainable, admin-editable; cannot generalise beyond listed words |
| Stop-words | Small list incl. generic words | Generic out-of-vocabulary words ("steps", "follow") must not count as missing topic words |
| Stemming | Light suffix stemmer | Lemmatiser needs data downloads; stemming adequate for retrieval |
| Features | Word TF-IDF (1-2 grams) + char 3-5-gram TF-IDF + BM25 + weighted term coverage | Lexical stack runs offline instantly; char n-grams give typo tolerance; coverage penalises unseen topical words |
| Dense embeddings | Optional (`FAQ_USE_EMBEDDINGS=1`) | Best for paraphrase but needs a model download; kept optional |
| Intent | Logistic regression over TF-IDF of question variants | Used as an agreement signal, not as the answer source |
| Answer selection | Max over each FAQ's variants (question, alternatives, keywords, answer text, whole-FAQ document) | Evidence from several phrasings of the same FAQ |
| Confidence | `score × (0.85 + 0.15·min(1, margin/0.12))`, ±intent agreement | Margin to runner-up separates "clear winner" from "tie" |

## 7. Approach comparison and selection
| Approach | Accuracy | Semantics | Offline/CPU | Explainable | Data needed | Hallucination risk | Verdict |
|---|---|---|---|---|---|---|---|
| Rule-based | Low | None | Yes | Yes | None | None | Too brittle |
| Keyword | Low-med | None | Yes | Yes | None | None | Misses paraphrase |
| TF-IDF + cosine | Med | Weak | Yes | Yes | None | None | Baseline |
| ML intent classifier | Med-high on trained intents | Medium | Yes | Medium | Many examples/intent | None | Used only as a signal |
| Word-embedding (GloVe/FastText) | Med | Medium | Large files | Low | Pretrained | None | Skipped |
| Sentence-Transformer | High | Strong | CPU OK (~100-450 MB model) | Low | Pretrained | None | **Optional plug-in** |
| RAG | High | Strong | Needs LLM | Medium | LLM + index | Reduced, not zero | Out of scope: cost, privacy |
| LLM-only | Variable | Strong | GPU/cloud | Low | None | **High** | Rejected |
| **Hybrid lexical + calibrated abstention (chosen)** | Measured in §11 | Limited (see §12) | Yes | **High** | KB only | **None (extractive)** | **Selected** |

## 8. Architecture
```
USER                                         ADMIN
 |                                             |
 v                                             v
Chat UI (HTML/CSS/JS) ---> /api/ask       Login (hash, lockout, CSRF) -> Dashboard
                              |                         |
                      Language detect                FAQ CRUD / import
                      Normalise + spell-correct      Duplicate check
                      Synonym canonicalise + stem         |
                              |                           v
        +---------------------+------------+     SQLite  (faqs, alt_questions, settings,
        | word TF-IDF | char TF-IDF | BM25 | coverage |    query_log, feedback, audit_log, admins)
        +---------------------+------------+            |
                              |  (+ optional embeddings)  v
                      Per-FAQ max, intent check    Rebuild index in memory (atomic swap)
                      Confidence = score + margin
                              |
        answered / ambiguous / clarify / unknown ---> response + source + related + evidence
                              |
                    log (PII masked) -> feedback -> gap clustering -> admin review -> new FAQ
```
Modules are independent: swap `engine.py` scoring, add a dense scorer, or move SQLite → PostgreSQL by changing `db.py` only.

## 9. Knowledge base and storage
Fields: id, question, alternative questions, answer, category, intent, keywords, entities, source, version (auto-increments when question/answer change), related ids, active flag, created/updated.
**SQLite chosen**: zero-config, transactional, single file, offline, adequate for thousands of FAQs. JSON/CSV remain the import/export interchange. PostgreSQL is the upgrade path for multi-server deployment;
a vector DB (FAISS/Chroma) only pays off beyond ~10⁵ FAQs — in-memory matrices are used here.

## 10. Workflows
**User scenarios**
| Scenario | Behaviour |
|---|---|
| Exact / paraphrase | Answer + source + related FAQs; "Why this answer?" shows ranking |
| Spelling mistake | Corrected against KB vocabulary and char n-grams; corrected text shown |
| Ambiguous ("hostel") | Two close topics → "Which did you mean?" with options |
| Unknown / unrelated | No answer; closest topics; contact; query logged |
| Follow-up ("and the timings?") | Uses last FAQ's category as topic, adds evidence from the follow-up's own words |
| Low confidence | "Did you mean…" suggestions |
| Greeting / thanks / empty | Handled before retrieval |
| Stale answer | Answered with an "may be out of date" notice |

**Admin:** login → overview → add/import FAQs (duplicate check) → index rebuilds → monitor → *Unanswered* clusters → create FAQ → *Review* low-confidence / not-helpful → *Quality* scores → tune thresholds (feedback-based suggestion) → audit log.

## 11. Evaluation (reproducible: `python evaluate.py`)
Method: 86 hand-written queries across 10 categories (exact, paraphrase, typos, short, long, ambiguous, unknown, unrelated, follow-up, multilingual); none is copied from the KB's alternative questions.
Metrics: top-1/top-3 retrieval, MRR, outcome rates, abstention precision/recall/F1, calibration bins, threshold sweep, latency. Full tables: `docs/evaluation_report.md`.

| Metric (default threshold 0.45) | Result |
|---|---|
| Top-1 / Top-3 retrieval (answerable queries) | 0.88 / 0.97 |
| MRR | 0.92 |
| Answered correctly | 0.64 |
| Answered wrongly | 0.03 |
| Clarified with the correct FAQ among the options | 0.14 |
| **Safe success** (correct answer or correct option offered) | 0.78 |
| Abstained although answerable | 0.33 |
| False answers on unknown/unrelated queries | **0 / 16** |
| Latency p50 / p95 | ≈5 / 7 ms on CPU |

Per category (answered correctly): exact 1.00 · short 0.88 · typos 0.80 · follow-up 0.67 · multilingual 0.60 · paraphrase 0.50 · long 0.00 (retrieval top-1 0.75: right FAQ ranked first but confidence too low to answer).
**Calibration:** the 0.75-1.00 confidence bin was right 97% of the time; the 0.55-0.75 bin 80% (small bins: 30 and 10 queries).

**How to read this honestly**
- Strength: it rarely answers wrongly and never answered an out-of-scope question in this set.
- Weakness: it is *conservative* — about a third of answerable questions get "did you mean" instead of an answer, mostly paraphrases and long questions where wording differs from the KB. That is the lexical ceiling; embeddings are the intended fix.
- Caveats: one author, 86 queries, one sample KB. Some synonyms and generic stop-words were added after inspecting failures, so these are **development-set** numbers, not an untouched hold-out. The threshold (0.45) was picked from the sweep on the same set. Create a fresh test set from your own KB before quoting figures.
- Not yet measured: load testing, usability study, penetration testing, embeddings-on comparison.

## 12. Limitations
Synonym coverage is a hand-maintained list (e.g. the Devanagari spelling "हॉस्टल" is not mapped); Hindi/Marathi support depends on alternative questions and listed words, not real translation;
no cross-lingual semantics without the optional embedding model; follow-up handling is a heuristic (topic = last FAQ's category); single-FAQ answers only (no multi-document synthesis);
in-memory rate limiting (use a reverse proxy for production); no email/2FA for admin.

## 13. Offline analysis
| Component | Offline? |
|---|---|
| NLP pipeline, retrieval, intent classifier | Yes, pure CPU, ~tens of MB RAM |
| SQLite KB, logs, admin dashboard, UI | Yes (system fonts, no CDN) |
| Optional embedding model | Download once, then offline (≈100-450 MB; CPU works, GPU optional) |
| Browser voice input | Usually **needs internet** (browser sends audio to a speech service); hidden when offline |
| Multi-site "sync" | Manual: export KB / query log from one install, import into another. No automatic sync is implemented |

## 14. Reliability and hallucination control
Extractive-only answers (verbatim KB text) · thresholds + margin + out-of-vocabulary penalty · refusal and clarification paths · source/version/date on each answer · staleness notice ·
human contact escalation · feedback and admin review · automated tests (`tests/`) and the evaluation harness. No claim of 100% accuracy is made or supportable.

## 15. Security and privacy
| Control | Status |
|---|---|
| Password hashing (Werkzeug scrypt/PBKDF2), random first-run password | Implemented |
| Session cookie HttpOnly + SameSite=Lax (+Secure with `FAQ_HTTPS=1`), 2-hour lifetime | Implemented |
| CSRF token on all admin writes and login | Implemented |
| Login rate limit (5 / 5 min / IP), API rate limit | Implemented (in-memory) |
| SQL injection | Parameterised queries throughout |
| XSS | Jinja autoescape; UI renders with `textContent`; CSP `script-src 'self'; style-src 'self'` (no inline) |
| CSV-injection-safe log export | Implemented |
| Input validation and size limits | Implemented |
| Audit log of admin actions | Implemented |
| PII masking (email, phone, 12-digit IDs) before logging; log retention purge | Implemented, configurable |
| Encryption at rest, 2FA, per-role access, HTTPS termination | **Not implemented** (deploy behind HTTPS; use disk encryption) |
No user data leaves the machine unless you enable an external service yourself.

## 16. Multilingual and accessibility
Language detection by script and marker words (English, Hindi, Marathi, Hinglish). Devanagari and Hinglish words map to canonical tokens; alternative questions in any language join the same index.
For genuine cross-lingual semantics use the optional multilingual embedding model. Accessibility: skip link, labelled controls, `role="log"` live region, visible focus, keyboard shortcuts (`/` focus, Enter send, Esc clear),
reduced-motion and forced-colours support, responsive from phone to desktop, light/dark themes. Screen-reader testing with real assistive tech has **not** been done.

## 17. Technology stack
| Tech | Why | Alternatives | Why not |
|---|---|---|---|
| Python | NLP ecosystem | Node/Java | Weaker NLP libraries |
| scikit-learn | TF-IDF, logistic regression, CPU-fast | spaCy/NLTK | Need model/data downloads; not needed for retrieval |
| Own BM25 + coverage | ~25 lines; no dependency | rank_bm25, Elasticsearch | Overkill for this size |
| Flask | Small, transparent | FastAPI/Django | FastAPI fine for async/OpenAPI; Django heavier |
| SQLite | Offline, zero-config | PostgreSQL/MySQL | Needed only for multi-server |
| Vanilla JS/CSS | No build, works offline, CSP-clean | React | Build tooling adds weight |
| sentence-transformers (optional) | Paraphrase/cross-lingual | Hugging Face directly, FAISS | Adds weight; optional |

## 18. Comparison with other approaches (evidence-based, own results where available)
| Feature | Static FAQ | Keyword | ML intent bot | Semantic FAQ | TrustFAQ (this build) |
|---|---|---|---|---|---|
| Keyword matching | Manual | Yes | Yes | Yes | Yes |
| Paraphrase handling | No | No | Trained intents | Strong | **Moderate** (top-3 0.97, direct answer 0.50) |
| Intent detection | No | No | Yes | Sometimes | Yes (signal only) |
| Context awareness | No | No | Via dialogue manager | Rare | Basic follow-ups |
| Spelling tolerance | No | No | Partial | Moderate | Yes (typos 0.80 answered) |
| Unknown detection | n/a | No | Needs OOS class | Needs threshold | **Yes** (0/16 false answers in test) |
| Confidence scoring | No | No | Yes | Yes | Yes, with refusal/clarify paths |
| Source grounding | Page itself | Page | Rare | Sometimes | Always |
| Admin tooling + analytics | No | No | Vendor-dependent | Vendor-dependent | Yes |
| Multilingual | Manual | No | Per-language training | Strong with multilingual models | Partial (listed words + alt-questions; embeddings optional) |
| Offline | Yes | Yes | Often | Possible | **Yes by default** |
| Scalability | n/a | High | Medium | High | Thousands of FAQs per node; not tested beyond sample KB |
| Hallucination control | n/a | n/a | n/a | n/a | **By construction (extractive)** |
The semantic FAQ column is stronger on paraphrase; TrustFAQ is stronger on auditability, offline operation and refusal behaviour.

## 19. USP and innovations
**USP: a trustworthy, offline-first FAQ assistant that knows when it doesn't know, shows its evidence, and turns every miss into a task for the administrator.**
Innovations (all implemented and explainable): hybrid lexical retrieval with coverage and out-of-vocabulary penalty · margin-based confidence with ambiguity detection ·
three-way outcome (answer / clarify / refuse) · explainable ranking ("Why this answer?") · FAQ-gap clustering of unanswered queries · duplicate-FAQ detection on entry ·
KB quality scoring · feedback-based threshold suggestion · PII-masked analytics · optional embedding upgrade without code changes.

## 20. Future scope
Embedding retrieval evaluated against this baseline · admin-editable synonym thesaurus · real translation/transliteration (e.g. Bhashini) · cross-encoder reranking · RAG with strictly quoted spans over PDFs ·
role-based admin, 2FA, encryption at rest · load and usability testing · automatic KB sync across sites.

## 21. Conclusion
The build demonstrates an end-to-end, auditable NLP retrieval system whose defining behaviour — refusing or clarifying rather than guessing — is measured, not asserted.
Its main weakness, paraphrase recall, is stated openly with a concrete upgrade path.

## 22. References (to verify and cite properly)
Weizenbaum (1966) ELIZA · Salton & Buckley (1988) term weighting · Robertson & Zaragoza (2009) BM25 · Mikolov et al. (2013) Word2Vec · Pennington et al. (2014) GloVe · Bojanowski et al. (2017) FastText ·
Devlin et al. (2018) BERT · Reimers & Gurevych (2019) Sentence-BERT · Karpukhin et al. (2020) DPR · Lewis et al. (2020) RAG · Rajpurkar et al. (2016) SQuAD · Ferrucci et al. (2010) IBM Watson ·
Bird, Klein & Loper (2009) NLTK · Pedregosa et al. (2011) scikit-learn.
