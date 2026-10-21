"""
TrustFAQ retrieval engine.

Pipeline:  clean -> spell-correct (vs KB vocabulary) -> synonym/Hinglish canonicalisation -> stopword removal -> stem
           -> hybrid scoring (word TF-IDF + char n-gram TF-IDF + BM25 + weighted term coverage [+ optional dense embeddings])
           -> per-FAQ max over variants -> confidence (score, margin, intent agreement) -> answer / clarify / ambiguous / unknown

Design rule: correctness > confidence > relevance > speed. When evidence is weak the engine says so instead of answering.
"""
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from nlp import Preprocessor, detect_language

KIND_MULT = {"question": 1.0, "alt": 1.0, "keywords": 0.85, "answer": 0.6, "doc": 0.9}
W = {"word": 0.32, "char": 0.20, "bm25": 0.18, "cov": 0.30}          # lexical weights (sum to 1)
W_DENSE = 0.35                                                       # share given to dense similarity when enabled
BM25_K1, BM25_B = 1.5, 0.75


class DenseScorer:
    """Optional sentence-embedding scorer. Enabled with FAQ_USE_EMBEDDINGS=1 and `pip install sentence-transformers`.
    Runs fully offline once the model is cached locally (set FAQ_EMBED_MODEL to a model name or local folder)."""

    def __init__(self, texts):
        from sentence_transformers import SentenceTransformer  # imported lazily on purpose
        name = os.environ.get("FAQ_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
        self.model = SentenceTransformer(name)
        self.emb = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    def scores(self, query):
        q = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        return np.clip(self.emb @ q, 0, 1)


class Engine:
    def __init__(self, faqs, settings=None, use_dense=None):
        self.faqs = [f for f in faqs if f.get("active", 1)]
        self.pre = Preprocessor()
        self.set_thresholds(settings or {})
        self.dense = None
        self.dense_error = None
        self._build(use_dense)

    # ------------------------------------------------------------------ build
    def set_thresholds(self, s):
        self.answer_th = float(s.get("answer_threshold", 0.55))
        self.clarify_th = float(s.get("clarify_threshold", 0.30))
        self.stale_days = int(float(s.get("stale_days", 180)))
        self.human_contact = s.get("human_contact", "")

    def _build(self, use_dense):
        V = []  # variants
        for i, f in enumerate(self.faqs):
            V.append((i, "question", f["question"]))
            for a in f.get("alt_questions", []):
                V.append((i, "alt", a))
            kw = " ".join(x for x in (f.get("keywords", ""), f.get("entities", ""), f.get("category", "")) if x)
            if kw.strip():
                V.append((i, "keywords", kw))
            V.append((i, "answer", f["answer"]))
            # whole-FAQ document: lets evidence from question + alternatives + keywords + answer combine
            V.append((i, "doc", " ".join([f["question"], *f.get("alt_questions", []), kw, f["answer"]])))
        self.variants = V
        self.pre.fit_vocab([t for _, k, t in V if k != "doc"])
        self.stems = [self.pre.process(t, spell=False)[0] for _, _, t in V]
        self.v_faq = np.array([v[0] for v in V])
        self.v_mult = np.array([KIND_MULT[v[1]] for v in V])

        docs = [" ".join(s) for s in self.stems]
        self.wvec = TfidfVectorizer(token_pattern=r"\S+", ngram_range=(1, 2), sublinear_tf=True)
        self.Xw = self.wvec.fit_transform(docs) if any(docs) else None
        self.cvec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.Xc = self.cvec.fit_transform(docs) if any(docs) else None

        # BM25 + coverage statistics
        N = max(len(self.stems), 1)
        df = Counter(t for s in self.stems for t in set(s))
        self.idf = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
        self.idf_max = max(self.idf.values()) if self.idf else 1.0
        lens = [len(s) for s in self.stems]
        self.avgdl = (sum(lens) / N) or 1.0
        self.tf = [Counter(s) for s in self.stems]
        self.dl = lens
        self.sets = [set(s) for s in self.stems]

        # intent classifier (question-like variants only)
        self.clf = None
        idx = [j for j, v in enumerate(V) if v[1] in ("question", "alt")]
        labels = [self.faqs[V[j][0]].get("intent") or f"faq_{self.faqs[V[j][0]]['id']}" for j in idx]
        if self.Xw is not None and len(set(labels)) >= 2:
            X = hstack([self.Xw[idx], self.Xc[idx]]).tocsr()
            self.clf = LogisticRegression(C=20, max_iter=2000).fit(X, labels)
            self.intent_to_faq = {}
            for j, lab in zip(idx, labels):
                self.intent_to_faq.setdefault(lab, V[j][0])

        if use_dense is None:
            use_dense = os.environ.get("FAQ_USE_EMBEDDINGS") == "1"
        if use_dense:
            try:
                self.dense = DenseScorer([t for _, _, t in V])
            except Exception as e:  # missing package / model not cached -> fall back to lexical hybrid
                self.dense_error = str(e)

    # --------------------------------------------------------------- scoring
    def _bm25(self, q_terms):
        n = len(self.stems)
        out = np.zeros(n)
        bound = 0.0
        for t in set(q_terms):
            idf = self.idf.get(t, self.idf_max)
            bound += idf * (BM25_K1 + 1)
            if t not in self.idf:
                continue
            for j in range(n):
                f = self.tf[j].get(t, 0)
                if f:
                    out[j] += idf * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * self.dl[j] / self.avgdl))
        return out / bound if bound else out

    def _coverage(self, q_terms):
        uniq = set(q_terms)
        w = {t: self.idf.get(t, self.idf_max) for t in uniq}
        total = sum(w.values()) or 1.0
        return np.array([sum(w[t] for t in uniq if t in s) / total for s in self.sets])

    def _score_variants(self, query):
        stems, corrected = self.pre.process(query)
        if not stems or self.Xw is None:
            return stems, corrected, None
        qs = " ".join(stems)
        word = (self.Xw @ self.wvec.transform([qs]).T).toarray().ravel()
        char = (self.Xc @ self.cvec.transform([qs]).T).toarray().ravel()
        bm = self._bm25(stems)
        cov = self._coverage(stems)
        uniq = set(stems)
        wts = {t: self.idf.get(t, self.idf_max) for t in uniq}
        known = sum(v for t, v in wts.items() if t in self.idf) / (sum(wts.values()) or 1.0)
        oov_scale = 0.35 + 0.65 * known     # topical words the KB has never seen (e.g. "bitcoin") must lower confidence
        lex = oov_scale * (W["word"] * word + W["char"] * char + W["bm25"] * bm + W["cov"] * cov)
        if self.dense is not None:
            dn = self.dense.scores(query)
            fused = (1 - W_DENSE) * lex + W_DENSE * dn
        else:
            dn = None
            fused = lex
        fused = np.clip(fused, 0, 1) * self.v_mult
        parts = {"word": word, "char": char, "bm25": bm, "cov": cov, "dense": dn}
        return stems, corrected, (fused, parts)

    def _rank(self, query, exclude=None, penalty=None, boost_ids=()):
        stems, corrected, sc = self._score_variants(query)
        if sc is None:
            return stems, corrected, []
        fused, parts = sc
        best = {}
        for j, s in enumerate(fused):
            i = int(self.v_faq[j])
            if i not in best or s > best[i][0]:
                best[i] = (float(s), j)
        cands = []
        for i, (s, j) in best.items():
            if exclude is not None and self.faqs[i]["id"] == exclude:
                s *= (penalty if penalty is not None else 0.0)
            if self.faqs[i]["id"] in boost_ids:
                s = min(1.0, s * 1.15)
            cands.append({
                "idx": i, "score": s, "variant": self.variants[j][2], "kind": self.variants[j][1],
                "parts": {k: (round(float(v[j]), 3) if v is not None else None) for k, v in parts.items()},
            })
        cands.sort(key=lambda c: -c["score"])
        return stems, corrected, cands

    # -------------------------------------------------------------- decisions
    def _intent(self, query, stems):
        if not self.clf or not stems:
            return None, 0.0
        qs = " ".join(stems)
        X = hstack([self.wvec.transform([qs]), self.cvec.transform([qs])]).tocsr()
        p = self.clf.predict_proba(X)[0]
        k = int(np.argmax(p))
        return self.clf.classes_[k], float(p[k])

    def _confidence(self, cands, intent, intent_p):
        s1 = cands[0]["score"]
        s2 = cands[1]["score"] if len(cands) > 1 else 0.0
        conf = s1 * (0.85 + 0.15 * min(1.0, (s1 - s2) / 0.12))
        top_intent = self.faqs[cands[0]["idx"]].get("intent")
        if intent:
            if intent == top_intent and intent_p >= 0.25:
                conf = min(1.0, conf + 0.03)
            elif intent != top_intent and intent_p >= 0.6:
                conf *= 0.92
        return float(conf), s1, s2

    def _view(self, c):
        f = self.faqs[c["idx"]]
        return {"faq_id": f["id"], "question": f["question"], "category": f["category"], "score": round(c["score"], 3)}

    def _stale(self, f):
        try:
            t = datetime.strptime(f["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - t).days > self.stale_days
        except Exception:
            return False

    def answer(self, query, ctx=None):
        t0 = time.perf_counter()
        query = (query or "").strip()
        lang = detect_language(query)
        res = {"query": query, "language": lang, "status": "unknown", "answer": None, "faq_id": None, "confidence": 0.0,
               "intent": None, "suggestions": [], "evidence": [], "sources": [], "used_context": False,
               "corrected_query": None, "stale": False}

        st_intent, st_reply = self.pre.smalltalk(query)
        if st_intent:
            res.update(status="smalltalk", answer=st_reply, intent=st_intent, confidence=1.0)
            return self._done(res, t0)

        stems, corrected, cands = self._rank(query)
        if not stems:
            res.update(status="empty", message="I couldn't find any searchable words in that. Try a short question such as 'What is the fee structure?'")
            return self._done(res, t0)
        res["corrected_query"] = corrected if corrected != " ".join(query.lower().split()) else None
        intent, ip = self._intent(query, stems)
        conf, s1, s2 = self._confidence(cands, intent, ip)

        # follow-up handling: only when standalone retrieval is not already convincing
        strong = Preprocessor.is_strong_followup(query)
        if ctx and ctx.get("last_faq_id") and (strong or (conf < self.answer_th and Preprocessor.is_followup(query, len(stems)))):
            last = next((f for f in self.faqs if f["id"] == ctx["last_faq_id"]), None)
            if last:
                cq = f'{query} {last["category"]}'   # topic of the conversation, not the whole previous question
                c_stems, _, c_cands = self._rank(cq, exclude=last["id"], penalty=0.6, boost_ids=set(last.get("related", [])))
                if c_cands:
                    # additive evidence: what the follow-up says on its own + what the conversation topic implies
                    alone = {c["idx"]: c["score"] for c in cands}
                    for c in c_cands:
                        c["score"] = 0.6 * alone.get(c["idx"], 0.0) + 0.4 * c["score"]
                        if self.faqs[c["idx"]]["id"] == last["id"]:
                            c["score"] *= 0.6
                    c_cands.sort(key=lambda c: -c["score"])
                    c_intent, c_ip = self._intent(cq, c_stems)
                    c_conf, c_s1, c_s2 = self._confidence(c_cands, c_intent, c_ip)
                    if c_conf > conf + (-0.1 if strong else 0.05):
                        cands, conf, s1, s2, intent, ip = c_cands, c_conf, c_s1, c_s2, c_intent, c_ip
                        res["used_context"] = True
                        res["interpreted_as"] = f'{last["question"]} → {query}'

        top = cands[0]
        f = self.faqs[top["idx"]]
        res["intent"] = intent
        res["intent_confidence"] = round(ip, 3)
        res["confidence"] = round(conf, 3)
        res["evidence"] = [dict(self._view(c), parts=c["parts"], matched=c["variant"], kind=c["kind"]) for c in cands[:3]]
        near = [self._view(c) for c in cands[:4] if c["score"] >= 0.12]

        ambiguous = (len(cands) > 1 and s2 >= 0.9 * s1 and s2 >= self.clarify_th
                     and self.faqs[cands[1]["idx"]].get("intent") != f.get("intent"))
        if conf >= self.answer_th and not ambiguous:
            res.update(status="answered", answer=f["answer"], faq_id=f["id"], matched_question=f["question"],
                       category=f["category"], stale=self._stale(f),
                       sources=[{"faq_id": f["id"], "source": f["source"], "version": f["version"], "updated": f["updated_at"][:10]}])
            res["confidence_label"] = "high" if conf >= 0.75 else "medium"
            res["related"] = [self._rel(i) for i in f.get("related", []) if self._rel(i)]
            res["suggestions"] = [n for n in near if n["faq_id"] != f["id"]][:3]
        elif conf >= self.clarify_th:
            res.update(status="ambiguous" if ambiguous else "clarify", suggestions=near[:3], confidence_label="low")
            res["message"] = ("Your question matches more than one topic. Which of these do you mean?" if ambiguous else
                              "I'm not certain I understood. Did you mean one of these?")
        else:
            res.update(status="unknown", suggestions=near[:3], confidence_label="none")
            res["message"] = ("I don't have verified information on that, so I won't guess. "
                              + (f"You can reach the office at {self.human_contact}. " if self.human_contact else "")
                              + "I've noted your question so the FAQ can be improved.")
        return self._done(res, t0)

    def _rel(self, fid):
        f = next((x for x in self.faqs if x["id"] == fid), None)
        return {"faq_id": f["id"], "question": f["question"]} if f else None

    @staticmethod
    def _done(res, t0):
        res["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return res

    # ---------------------------------------------------------- admin helpers
    def rank_ids(self, query, k=3):
        _, _, cands = self._rank(query)
        return [self.faqs[c["idx"]]["id"] for c in cands[:k]]

    def similar(self, text, exclude_id=None, k=3, min_score=0.5):
        _, _, cands = self._rank(text)
        return [dict(self._view(c)) for c in cands
                if self.faqs[c["idx"]]["id"] != exclude_id and c["score"] >= min_score][:k]

    def cluster(self, texts, threshold=0.45):
        """Greedy cosine clustering of unanswered queries to expose missing FAQ topics."""
        rows = [(t, " ".join(self.pre.process(t)[0])) for t in texts]
        rows = [(t, s) for t, s in rows if s]
        if not rows:
            return []
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), sublinear_tf=True)
        X = vec.fit_transform([s for _, s in rows])
        sim = (X @ X.T).toarray()
        used, clusters = set(), []
        for i in range(len(rows)):
            if i in used:
                continue
            members = [j for j in range(len(rows)) if j not in used and sim[i, j] >= threshold]
            used.update(members)
            clusters.append([rows[j][0] for j in members])
        clusters.sort(key=len, reverse=True)
        return [{"size": len(c), "examples": list(dict.fromkeys(c))[:4]} for c in clusters]
