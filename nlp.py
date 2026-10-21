"""Text normalisation and language handling (pure Python, no model downloads)."""
import re
import unicodedata
import difflib

TOKEN_RE = re.compile(r"[\w\u0900-\u097F]+", re.UNICODE)
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

STOPWORDS = set("""a an the is are was were be been am do does did can could should would will shall may might
i me my we our you your it its of to in on at for with by from and or but if then so as that this these those
there here please tell about what whats which who whom how when where why any some get got want need know
kya hai hain ka ki ke ko se me mein ye yeh vo wo aur par
steps step follow possible possibility wondering wonder hi hello hey just planning plan friend told might able allowed
look way ways let thing things something anything really very much many more most other another such only own same than
too already still yet ever never always usually kindly know knowing say said ask asking question regarding related whole
like going go come comes take takes give gives use used make made see every each per college institute institution
university campus""".split())
STRONG_FOLLOWUP = re.compile(r"^(and|also|what about|how about|what if|then|aur|और)\b", re.I)

# Canonical-term map: synonyms, Hinglish and common Devanagari words -> one English token.
SYNONYMS = {
    # money
    "fees": "fee", "charges": "fee", "charge": "fee", "cost": "fee", "price": "fee", "tuition": "fee",
    "shulk": "fee", "paisa": "fee",
    "फीस": "fee", "शुल्क": "fee", "fis": "fee",
    # housing
    "dorm": "hostel", "dormitory": "hostel", "accommodation": "hostel", "residence": "hostel",
    "छात्रावास": "hostel", "वसतिगृह": "hostel", "hostal": "hostel",
    # exams
    "exams": "exam", "examination": "exam", "test": "exam", "tests": "exam", "pariksha": "exam",
    "परीक्षा": "exam", "परीक्षेचे": "exam",
    "marks": "grade", "result": "grade", "results": "grade", "score": "grade", "scores": "grade",
    "nikal": "grade", "निकाल": "grade", "परिणाम": "grade",
    # admission
    "admissions": "admission", "enroll": "admission", "enrol": "admission", "enrollment": "admission",
    "enrolment": "admission", "register": "admission", "registration": "admission", "join": "admission",
    "praveshan": "admission", "प्रवेश": "admission", "daakhila": "admission",
    # library
    "books": "book", "borrow": "book", "पुस्तकालय": "library", "ग्रंथालय": "library",
    "granthalay": "library", "pustakalay": "library",
    # jobs
    "placements": "placement", "job": "placement", "jobs": "placement", "recruit": "placement",
    "recruitment": "placement", "recruiters": "placement", "company": "placement", "companies": "placement",
    "naukri": "placement", "नौकरी": "placement", 
    # scholarships
    "scholarships": "scholarship", "bursary": "scholarship", "stipend": "scholarship",
    "financial": "scholarship", "aid": "scholarship", "chatravritti": "scholarship", "छात्रवृत्ति": "scholarship",
    "शिष्यवृत्ती": "scholarship",
    # misc
    "timing": "time", "timings": "time", "hours": "time", "schedule": "time", "open": "time", "opening": "time",
    "close": "time", "closing": "time", "kab": "when", "kaise": "how", "kahan": "where", "kitna": "much",
    "kitni": "much", "kitne": "much", "kaun": "who", "kyun": "why",
    "wifi": "internet", "wi-fi": "internet", "network": "internet", "broadband": "internet",
    "id": "idcard", "identity": "idcard", "lost": "lose", "misplaced": "lose", "missing": "lose",
    "duplicate": "replacement", "replace": "replacement", "reissue": "replacement",
    "teacher": "faculty", "professor": "faculty", "staff": "faculty", "lecturer": "faculty",
    "lib": "library", "attendence": "attendance", "attend": "attendance", "absent": "attendance", "bunk": "attendance",
    "syllabus": "curriculum", "course": "curriculum", "subjects": "curriculum", "subject": "curriculum",
    "bus": "transport", "shuttle": "transport", "commute": "transport",
    "canteen": "food", "mess": "food", "cafeteria": "food", "meal": "food", "meals": "food", "lunch": "food",
    "refund": "refund", "cancel": "cancel", "cancellation": "cancel", "withdraw": "cancel", "withdrawal": "cancel",
    "certificate": "certificate", "certificates": "certificate", "marksheet": "certificate",
    "bonafide": "certificate", "transcript": "certificate",
    "reset": "reset", "forgot": "reset", "forget": "reset", "recover": "reset",
    "contact": "contact", "email": "contact", "phone": "contact", "call": "contact", "reach": "contact",
}

FOLLOWUP_MARKERS = re.compile(
    r"^(and|also|what about|how about|then|what if|ok and|okay and|aur|और|peki)\b|\b(it|that|this|those|them|there|its|their)\b",
    re.I)

SMALLTALK = [
    ("greeting", re.compile(r"^(hi|hello|hey|hii+|namaste|namaskar|good (morning|afternoon|evening)|नमस्ते|नमस्कार)\b[\s!.]*$", re.I),
     "Hello! I answer questions from the institute's verified FAQ. Ask me about admissions, fees, exams, hostel, library, placements and more."),
    ("thanks", re.compile(r"^(thanks|thank you|thx|ty|dhanyavad|shukriya|आभार|धन्यवाद)[\s!.]*$", re.I),
     "You're welcome. Ask another question any time."),
    ("goodbye", re.compile(r"^(bye|goodbye|see you|exit|quit|alvida)[\s!.]*$", re.I),
     "Goodbye. The FAQ will be here when you need it."),
]

PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[phone]"),
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "[id-number]"),
    (re.compile(r"(?<!\d)\d{4}[\s-]\d{4}[\s-]\d{4}(?!\d)"), "[id-number]"),
]


def redact_pii(text: str) -> str:
    for pat, repl in PII_PATTERNS:
        text = pat.sub(repl, text)
    return text


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.replace("’", "'").replace("'", "")
    return re.sub(r"\s+", " ", text).strip()


def detect_language(text: str) -> str:
    """Script + marker-word detection. Returns en | hi | mr | hinglish."""
    if DEVANAGARI_RE.search(text):
        mr_markers = ("आहे", "काय", "कसे", "कुठे", "किती", "मला", "तुमचे", "आहेत", "का ", "होईल")
        return "mr" if any(m in text for m in mr_markers) else "hi"
    toks = set(TOKEN_RE.findall(text.lower()))
    hinglish = {"kya", "hai", "kaise", "kab", "kahan", "kitna", "kitni", "kitne", "mujhe", "nahi", "karna",
                "karo", "ke", "ka", "ki", "hota", "milega", "chahiye", "batao", "bataiye", "lagega", "kaun"}
    return "hinglish" if len(toks & hinglish) >= 1 and len(toks & hinglish) >= len(toks) * 0.2 else "en"


def stem(w: str) -> str:
    if len(w) <= 3 or DEVANAGARI_RE.search(w):
        return w
    for suf, rep in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("ed", ""), ("ly", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3 and not (suf == "s" and w.endswith("ss")):
            return w[: -len(suf)] + rep
    return w


def raw_tokens(text: str):
    return TOKEN_RE.findall(clean(text))


class Preprocessor:
    """clean -> tokenize -> spell-correct (vs KB vocab) -> canonicalise synonyms -> stopword removal -> stem."""

    def __init__(self):
        self.vocab = set()

    def fit_vocab(self, texts):
        v = set()
        for t in texts:
            for tok in raw_tokens(t):
                if tok not in STOPWORDS and len(tok) >= 3:
                    v.add(tok)
        v.update(k for k in SYNONYMS if k.isascii())
        self.vocab = v
        self._vocab_list = sorted(v)

    def correct(self, tok: str):
        if tok in self.vocab or tok in STOPWORDS or len(tok) < 4 or not tok.isascii() or tok.isdigit():
            return tok
        # strict: same first letter, and short words need a very close match (avoids "paris" -> "paisa")
        cands = [v for v in self._vocab_list if v[0] == tok[0] and abs(len(v) - len(tok)) <= 2]
        m = difflib.get_close_matches(tok, cands, n=1, cutoff=0.88 if len(tok) <= 5 else 0.82)
        return m[0] if m else tok

    def process(self, text: str, spell=True):
        """Return (stems, corrected_text)."""
        toks = raw_tokens(text)
        if spell:
            toks = [self.correct(t) for t in toks]
        corrected = " ".join(toks)
        out = []
        for t in toks:
            t = SYNONYMS.get(t, t)
            if t in STOPWORDS:
                continue
            s = stem(t)
            out.append(SYNONYMS.get(s, s))   # canonicalise again after stemming ("enrolled" -> "enroll" -> "admission")
        return out, corrected

    def smalltalk(self, text: str):
        c = clean(text)
        for intent, pat, reply in SMALLTALK:
            if pat.match(c):
                return intent, reply
        return None, None

    @staticmethod
    def is_strong_followup(text: str) -> bool:
        return bool(STRONG_FOLLOWUP.search(clean(text)))

    @staticmethod
    def is_followup(text: str, n_content: int) -> bool:
        return n_content <= 2 or bool(FOLLOWUP_MARKERS.search(clean(text)))
