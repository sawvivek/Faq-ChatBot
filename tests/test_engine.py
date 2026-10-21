import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["FAQ_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import pytest
import db
from engine import Engine
from nlp import Preprocessor, detect_language, redact_pii

HERE = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture(scope="module")
def eng():
    db.init_db(); db.seed_if_empty(os.path.join(HERE, "data", "seed_faqs.json"))
    return Engine(db.list_faqs(True), db.get_settings())


def test_exact_question_answers(eng):
    r = eng.answer("What is the fee structure?")
    assert r["status"] == "answered" and r["matched_question"] == "What is the fee structure?"
    assert r["sources"] and r["confidence"] > 0.8


def test_spelling_mistakes_tolerated(eng):
    assert eng.answer("admision proces")["matched_question"] == "How do I apply for admission?"


def test_unrelated_is_not_answered(eng):
    for q in ("What is the capital of France?", "bitcoin price", "weather in Mumbai today", "tell me a joke"):
        r = eng.answer(q)
        assert r["status"] != "answered" and r["answer"] is None, q


def test_unknown_never_fabricates(eng):
    r = eng.answer("Is there a swimming pool on campus?")
    assert r["status"] in ("unknown", "clarify") and r["answer"] is None


def test_answer_text_is_verbatim_from_kb(eng):
    r = eng.answer("library timings")
    assert r["answer"] == next(f["answer"] for f in eng.faqs if f["id"] == r["faq_id"])


def test_followup_uses_context(eng):
    hostel = next(f for f in eng.faqs if f["question"].startswith("How do I get a hostel room"))
    r = eng.answer("and the timings?", {"last_faq_id": hostel["id"]})
    assert r["used_context"] and "timings" in r["matched_question"].lower()


def test_smalltalk_and_empty(eng):
    assert eng.answer("hello")["status"] == "smalltalk"
    assert eng.answer("???")["status"] == "empty"


def test_hindi_query(eng):
    assert eng.answer("फीस कितनी है")["matched_question"] == "What is the fee structure?"


def test_language_detection():
    assert detect_language("fees kitni hai") == "hinglish"
    assert detect_language("फीस कितनी है") == "hi"
    assert detect_language("शुल्क किती आहे, काय करावे") == "mr"
    assert detect_language("what is the fee") == "en"


def test_spell_correction_is_conservative():
    p = Preprocessor(); p.fit_vocab(["admission process", "hostel room", "paisa"])
    assert p.correct("admision") == "admission"
    assert p.correct("paris") == "paris"


def test_pii_redaction():
    t = redact_pii("mail me at a.b@c.com or call 9876543210, id 1234 5678 9012")
    assert "@" not in t and "9876543210" not in t and "5678" not in t


def test_ambiguous_single_word_offers_options(eng):
    r = eng.answer("hostel")
    assert r["status"] in ("ambiguous", "answered") and (r["status"] != "ambiguous" or len(r["suggestions"]) >= 2)


def test_new_faq_is_searchable_after_rebuild():
    fid = db.create_faq({"question": "Is there a gym on campus?", "answer": "Yes, 6 am to 9 pm.", "category": "Facilities",
                         "alt_questions": ["where can I work out", "fitness centre"]})
    e2 = Engine(db.list_faqs(True), db.get_settings())
    assert e2.answer("is there a gym")["faq_id"] == fid
    db.delete_faq(fid)
