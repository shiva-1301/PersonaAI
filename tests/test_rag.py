from core import rag
from core.ingest import parse_topics
from core.vectorstore import Hit


def hits(n=3):
    return [Hit(f"text {i}", 1, "unit3.pdf", i, 0.3) for i in range(1, n + 1)]


def test_not_found_reply():
    for reply in ["NOT_FOUND", "  NOT_FOUND.", "not_found", ""]:
        a = rag.parse_answer(reply, hits())
        assert not a.found and a.sources == []


def test_only_cited_sources_listed_in_order():
    a = rag.parse_answer("Pig is a platform [S3]. It runs on Hadoop [S1][s3].", hits())
    assert a.found
    assert [s.number for s in a.sources] == [1, 3]
    assert a.sources[0].label == "unit3.pdf, p. 1"


def test_out_of_range_citations_ignored_and_uncited_falls_back_to_all():
    assert [s.number for s in rag.parse_answer("Q22 says x [22] [S9]", hits()).sources] == [1, 2, 3]


def test_prompt_numbers_excerpts_with_file_and_page():
    p = rag.build_prompt("What is Pig?", hits(2))
    assert "[S1] (unit3.pdf, p. 1)" in p and "[S2] (unit3.pdf, p. 2)" in p
    assert p.endswith("Question: What is Pig?")


def test_parse_topics_formats():
    assert parse_topics('{"topics": ["Hive tables", " Sqoop  import "]}') == ["Hive tables", "Sqoop import"]
    assert parse_topics('```json\n["A", "B"]\n```') == ["A", "B"]
    assert parse_topics('{"topics": [{"name": "Flume sinks"}]}') == ["Flume sinks"]


def test_slides_are_labelled_as_slides_in_prompt_and_sources():
    slide = [Hit("Padding adds a border of zeros.", 1, "Deep Learning - Unit 2.pptx", 21, 0.3)]
    assert "[S1] (Deep Learning - Unit 2.pptx, slide 21)" in rag.build_prompt("What is padding?", slide)
    assert rag.parse_answer("Padding adds zeros [S1].", slide).sources[0].label == "Deep Learning - Unit 2.pptx, slide 21"


def test_single_questions_skip_the_splitter(monkeypatch):
    monkeypatch.setattr(rag.llm, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert rag.sub_questions("What is a context-free grammar?") == ["What is a context-free grammar?"]


def test_multi_part_question_is_split_and_each_part_gets_excerpts(monkeypatch):
    import json
    monkeypatch.setattr(rag.llm, "generate", lambda *a, **k: json.dumps(
        {"questions": ["What does the YARN Resource Manager do?", "What does a pooling layer do in a CNN?"]}))
    yarn = [Hit(f"yarn {i}", 1, "Big Data - Unit 2.pptx", i, 0.3) for i in range(1, 6)]
    pool = [Hit(f"pool {i}", 2, "Deep Learning - Unit 2.pptx", i, 0.3) for i in range(1, 6)]
    monkeypatch.setattr(rag, "retrieve", lambda uid, q, docs=None, k=rag.TOP_K: yarn if "YARN" in q else pool)
    merged = rag.retrieve_for_answer(1, "What does YARN's Resource Manager do, and what does a pooling layer do?")
    assert [h.text for h in merged[:4]] == ["yarn 1", "pool 1", "yarn 2", "pool 2"]
    assert len(merged) == rag.MAX_EXCERPTS_MULTI


def test_splitter_failure_falls_back_to_the_whole_question(monkeypatch):
    def down(*a, **k):
        raise rag.llm.LLMError("offline")
    monkeypatch.setattr(rag.llm, "generate", down)
    assert rag.sub_questions("What is YARN and what is HDFS?") == ["What is YARN and what is HDFS?"]
