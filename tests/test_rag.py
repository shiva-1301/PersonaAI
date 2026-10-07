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
    assert "[S1] (unit3.pdf, page 1)" in p and "[S2] (unit3.pdf, page 2)" in p
    assert p.endswith("Question: What is Pig?")


def test_parse_topics_formats():
    assert parse_topics('{"topics": ["Hive tables", " Sqoop  import "]}') == ["Hive tables", "Sqoop import"]
    assert parse_topics('```json\n["A", "B"]\n```') == ["A", "B"]
    assert parse_topics('{"topics": [{"name": "Flume sinks"}]}') == ["Flume sinks"]
