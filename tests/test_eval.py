import csv
import json

import pytest

from core import llm, rag
from core.rag import Answer, Source
from evaluation import run_eval

Q = {"id": "1", "unit": "III", "question": "What is Pig?", "reference_answer": "A platform for Hadoop."}


@pytest.fixture
def stub(monkeypatch):
    """rag.answer + no-RAG answer + judge, all fake. The judge marks whichever answer
    mentions 'Hadoop' correct, so we can check verdicts follow answers through the
    random A/B order."""
    state = {"rag": Answer("Pig runs on Hadoop [S1].", True, [Source(1, "u3.pdf", 2, "...")], "gemini / m")}
    monkeypatch.setattr(rag, "answer", lambda uid, q: state["rag"])

    def fake(prompt, system=None, json_mode=False, **kw):
        if not json_mode:
            return "Pig is a farm animal.", "gemini / m"
        a1 = prompt.split("Answer 1:")[1].split("Answer 2:")[0]
        a2 = prompt.split("Answer 2:")[1].split("Grade each")[0]
        grade = lambda a: {"verdict": "correct" if "Hadoop" in a else "wrong", "reason": "r"}
        return json.dumps({"answer1": grade(a1), "answer2": grade(a2)}), "gemini / judge"

    monkeypatch.setattr(llm, "generate_with_model", fake)
    return state


def test_verdicts_follow_answers_through_random_order(stub):
    for _ in range(10):
        row = run_eval.evaluate_one(1, Q)
        assert (row["rag_verdict"], row["no_rag_verdict"]) == ("correct", "wrong")
    assert row["rag_sources"] == "u3.pdf, p. 2" and row["judge_model"] == "gemini / judge"


def test_not_found_counts_as_wrong_abstention(stub):
    stub["rag"] = Answer("I couldn't find this in your notes.", False)
    row = run_eval.evaluate_one(1, Q)
    assert row["rag_verdict"] == "wrong" and row["rag_reason"].startswith("Abstained")


def test_quota_error_stops_cleanly(monkeypatch):
    monkeypatch.setattr(rag, "answer", lambda *a: (_ for _ in ()).throw(llm.LLMError("429")))
    with pytest.raises(run_eval.QuotaStop):
        run_eval.evaluate_one(1, Q)


def rows(*pairs, manual=None):
    out = []
    for i, (a, b) in enumerate(pairs, 1):
        out.append({"id": str(i), "unit": "III", "question": f"q{i}", "rag_verdict": a, "no_rag_verdict": b,
                    "rag_reason": "", "no_rag_reason": "", "model": "m", "judge_model": "j",
                    "manual_rag": "", "manual_no_rag": ""})
    for (i, cond), v in (manual or {}).items():
        out[i][f"manual_{cond}"] = v
    return out


def test_summary_and_manual_override():
    data = rows(("correct", "wrong"), ("partial", "correct"), ("wrong", "wrong"), ("correct", "partial"),
                manual={(2, "rag"): "correct"})
    s = run_eval.summarize(data)
    assert (s["rag"]["correct"], s["rag"]["partial"], s["rag"]["wrong"]) == (3, 1, 0)
    assert s["rag"]["accuracy"] == 0.75 and s["rag"]["score"] == 0.875
    assert s["no_rag"]["accuracy"] == 0.25 and s["manual_overrides"] == 1


def test_resume_and_report(tmp_path):
    path = tmp_path / "results.csv"
    data = {r["id"]: r for r in rows(("correct", "wrong"), ("correct", "partial"))}
    run_eval.write_rows(path, data)
    loaded = run_eval.load_rows(path)
    assert set(loaded) == {"1", "2"} and loaded["1"]["rag_verdict"] == "correct"
    run_eval.write_report(tmp_path, list(loaded.values()), [tmp_path / "u3.pdf"])
    report = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "| With notes (RAG) | 2 | 0 | 0 | 100% | 100% |" in report
    assert (tmp_path / "chart.png").stat().st_size > 1000


def test_simulation_runs_and_adaptive_targets_weak_topics(tmp_path, monkeypatch):
    from core import config
    from evaluation import simulate_adaptive as sim
    monkeypatch.setattr(config, "DB_PATH", config.DB_PATH)  # restored after the test
    results = sim.run(students=4, sessions=6)
    later = lambda m: sum(results[m]["on_weak"][3:]) / 3
    assert later("adaptive") > later("even")
    sim.write_report(results, 4, 6, tmp_path)
    assert "| Measure | Adaptive | Even mix |" in (tmp_path / "adaptive_simulation.md").read_text(encoding="utf-8")
