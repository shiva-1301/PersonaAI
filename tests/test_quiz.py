import json

import pytest

from core import config, db, llm, quiz, rag
from core.vectorstore import Hit

TOPICS = {1: {"id": 1, "name": "Hive tables", "document_id": 1},
          2: {"id": 2, "name": "Pig macros", "document_id": 1}}
HITS = [Hit("Managed tables...", 1, "unit4.pdf", 12, 0.2), Hit("Macros...", 1, "unit3.pdf", 18, 0.2)]


def q(topic="T1", question="What does dropping a managed table do?", answer="B", **kw):
    item = {"topic": topic, "question": question,
            "options": ["Keeps data", "Deletes data and metadata", "Deletes metadata only", "Moves data"],
            "answer": answer, "explanation": "Hive owns managed tables.", "source": "S1"}
    item.update(kw)
    return item


def parse(items, needed={1: 5, 2: 5}):
    return quiz.parse_questions(json.dumps({"questions": items}), TOPICS, HITS, needed)


def test_valid_question_parsed_and_answer_tracks_shuffle():
    [question] = parse([q()])
    assert question.topic_id == 1 and question.topic == "Hive tables"
    assert question.correct_option == "Deletes data and metadata"
    assert question.source == "unit4.pdf, p. 12"


@pytest.mark.parametrize("answer", ["B", "b", "B)", "Deletes data and metadata"])
def test_answer_formats(answer):
    assert parse([q(answer=answer)])[0].correct_option == "Deletes data and metadata"


@pytest.mark.parametrize("bad", [
    {"options": ["a", "b", "c"]},                     # 3 options
    {"options": ["a", "a", "b", "c"]},                # duplicates
    {"options": ["a", "b", "c", "All of the above"]},
    {"answer": "E"},
    {"answer": 1},                                    # numeric: 0- or 1-based? rejected
    {"topic": "T9"},                                  # unknown topic
    {"question": ""},
])
def test_invalid_questions_dropped(bad):
    assert parse([q(**bad)]) == []


def test_option_letter_prefixes_stripped():
    [question] = parse([q(options=["A) Keeps data", "B) Deletes data and metadata", "C) Deletes metadata only", "D) Moves data"])])
    assert "Deletes data and metadata" in question.options


def test_malformed_json_returns_empty():
    assert quiz.parse_questions("not json {", TOPICS, HITS, {1: 1}) == []


def test_even_allocation():
    alloc = quiz.even_allocation([1, 2, 3], 10)
    assert sum(alloc.values()) == 10 and sorted(alloc.values()) == [3, 3, 4]
    alloc = quiz.even_allocation(list(range(20)), 5)
    assert sum(alloc.values()) == 5 and set(alloc.values()) == {1}


def test_grade():
    qs = parse([q(), q(topic="T2", question="Q2?")])
    result = quiz.grade(qs, [qs[0].answer, (qs[1].answer + 1) % 4])
    assert (result.score, result.total, result.correct, result.percent) == (1, 2, [True, False], 50)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    uid = db.get_or_create_user("u")["id"]
    doc = db.add_document(uid, "unit4.pdf", None, 20)
    db.set_topics(uid, doc, ["Hive tables", "Pig macros"])
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: HITS)
    return uid, {t["name"]: t["id"] for t in db.list_topics(uid)}


def test_generate_retries_only_for_missing_questions(env, monkeypatch):
    uid, ids = env
    replies = [
        # 1st call: one good T1 question, one broken, nothing for T2
        json.dumps({"questions": [q(), q(question="bad", options=["x"])]}),
        # 2nd call: the missing T2 question (prompt now only lists Pig macros as T1)
        json.dumps({"questions": [q(topic="T1", question="What is a Pig macro?")]}),
    ]
    prompts = []

    def fake(prompt, **kw):
        prompts.append(prompt)
        return replies[len(prompts) - 1], "gemini / test"

    monkeypatch.setattr(llm, "generate_with_model", fake)
    questions = quiz.generate(uid, {ids["Hive tables"]: 1, ids["Pig macros"]: 1})
    assert len(prompts) == 2
    assert 'T1: "Pig macros" - 1 question' in prompts[1]
    assert "What does dropping a managed table do?" in prompts[1]  # told to avoid repeats
    assert sorted(x.topic for x in questions) == ["Hive tables", "Pig macros"]


def test_generate_gives_up_after_max_attempts(env, monkeypatch):
    uid, ids = env
    monkeypatch.setattr(llm, "generate_with_model", lambda *a, **k: ("garbage", "gemini / test"))
    with pytest.raises(quiz.QuizError):
        quiz.generate(uid, {ids["Hive tables"]: 2})


def test_surplus_questions_trimmed(env, monkeypatch):
    uid, ids = env
    many = [q(question=f"Q{i}?") for i in range(5)]
    monkeypatch.setattr(
        llm, "generate_with_model", lambda *a, **k: (json.dumps({"questions": many}), "gemini / test")
    )
    assert len(quiz.generate(uid, {ids["Hive tables"]: 2})) == 2


def test_submit_saves_attempt_and_answers(env, monkeypatch):
    uid, ids = env
    qs = parse([q(), q(topic="T2", question="Q2?")], needed={ids["Hive tables"]: 1, ids["Pig macros"]: 1})
    # parse() maps T1/T2 through TOPICS ids 1/2, which match the db ids here
    result = quiz.submit(uid, qs, [qs[0].answer, (qs[1].answer + 1) % 4])
    [attempt] = db.list_quiz_attempts(uid)
    assert (attempt["score"], attempt["total"]) == (1, 2)
    answers = db.list_quiz_answers(result.attempt_id)
    assert [a["is_correct"] for a in answers] == [1, 0]
    assert answers[0]["topic"] == "Hive tables"
    assert answers[1]["chosen"] != answers[1]["correct"]


def test_ollama_quiz_drops_questions_the_model_answers_differently(env, monkeypatch):
    uid, ids = env
    good, bad = q(question="Good?"), q(question="Wrong key?")
    monkeypatch.setattr(
        llm, "generate_with_model",
        lambda *a, **k: (json.dumps({"questions": [good, bad]}), "ollama / llama3.1:8b"),
    )
    monkeypatch.setattr(quiz.random, "shuffle", lambda x: None)  # key stays "B"
    verify_prompts = []

    def solver(prompt, **kw):
        verify_prompts.append(prompt)
        # Agrees with the key on question 1, disagrees on question 2.
        return json.dumps({"answers": [{"n": 1, "answer": "B"}, {"n": 2, "answer": "C"}]})

    monkeypatch.setattr(llm, "generate", solver)
    questions = quiz.generate(uid, {ids["Hive tables"]: 1})
    assert [x.question for x in questions] == ["Good?"]
    assert len(verify_prompts) == 1


def test_gemini_quiz_is_not_verified(env, monkeypatch):
    uid, ids = env
    monkeypatch.setattr(
        llm, "generate_with_model",
        lambda *a, **k: (json.dumps({"questions": [q()]}), "gemini / gemini-3.5-flash-lite"),
    )

    def boom(*a, **k):
        raise AssertionError("verification should not run for Gemini")

    monkeypatch.setattr(llm, "generate", boom)
    assert len(quiz.generate(uid, {ids["Hive tables"]: 1})) == 1


def test_unreadable_verification_keeps_nothing(monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "nonsense")
    assert quiz.verify(parse([q()]), HITS) == []


def test_topic_name_instead_of_tag_is_accepted():
    # Claude sometimes answered with the topic's name, which used to reject every question.
    [question] = parse([q(topic="pig MACROS")])
    assert question.topic_id == 2
    assert parse([q(topic="Unknown topic")]) == []


def test_quiz_schema_limits_topic_and_source_tags():
    schema = quiz.quiz_schema(["T1", "T2"], 3)
    item = schema["properties"]["questions"]["items"]["properties"]
    assert item["topic"]["enum"] == ["T1", "T2"]
    assert item["source"]["enum"] == ["S1", "S2", "S3"]
    assert item["answer"]["enum"] == ["A", "B", "C", "D"]
