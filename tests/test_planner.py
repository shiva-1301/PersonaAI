from datetime import date, timedelta

import pytest

from core import config, db, memory, planner
from core.memory import TopicStat
from core.planner import PlanError, build_plan

TODAY = date(2026, 10, 7)


def stat(tid, acc, answers=5):
    return TopicStat(tid, f"Topic {tid}", 1, "f.pdf", answers if acc is not None else 0, 0, acc, None)


STATS = [stat(1, 0.2), stat(2, 0.5), stat(3, None), stat(4, 0.9), stat(5, None),
         stat(6, 0.7), stat(7, 0.3), stat(8, None), stat(9, 0.95), stat(10, 0.65)]


def plan_14(stats=STATS, hours=3):
    return build_plan(stats, TODAY + timedelta(days=14), hours, today=TODAY)


def test_every_topic_is_studied_and_hours_add_up():
    plan = plan_14()
    studied = {t.topic_id for d in plan.days for t in d.tasks if t.kind == "study"}
    assert studied == {s.topic_id for s in STATS}
    study_days = [d for d in plan.days if any(t.kind in ("study", "review") for t in d.tasks)]
    assert sum(plan.topic_hours.values()) == len(study_days) * 3
    assert sum(t.hours for d in study_days for t in d.tasks) == sum(plan.topic_hours.values())
    assert all(d.hours <= 3 for d in plan.days)


def test_weak_topics_get_more_time_than_untested_than_strong():
    h = plan_14().topic_hours
    weak, new, strong = [1, 2, 7], [3, 5, 8], [4, 9]
    assert min(h[t] for t in weak) > max(h[t] for t in new) > max(h[t] for t in strong)


def test_reviews_come_after_the_topic_is_studied():
    plan = plan_14()
    first_study, first_review = {}, {}
    for i, d in enumerate(plan.days):
        for t in d.tasks:
            target = first_study if t.kind == "study" else first_review if t.kind == "review" else None
            if target is not None:
                target.setdefault(t.topic_id, i)
    assert set(first_review) >= {1, 2, 7}  # every weak topic gets reviewed
    assert all(first_review[t] > first_study[t] for t in first_review)


def test_plan_covers_days_until_exam_and_ends_with_mock_and_revision():
    plan = plan_14()
    assert len(plan.days) == 14
    assert plan.days[0].date == TODAY.isoformat()
    assert plan.days[-1].date == (TODAY + timedelta(days=13)).isoformat()  # exam day itself is free
    assert [t.kind for t in plan.days[-2].tasks][0] == "mock"
    assert plan.days[-1].tasks[0].kind == "revision"
    assert "Topic 1" in plan.days[-1].tasks[0].title  # weakest topic named in final revision


@pytest.mark.parametrize("days,finals", [(1, []), (2, []), (5, ["revision"]), (7, ["mock", "revision"])])
def test_short_plans(days, finals):
    plan = build_plan(STATS[:3], TODAY + timedelta(days=days), 4, today=TODAY)
    kinds = [d.tasks[0].kind for d in plan.days]
    assert kinds[len(kinds) - len(finals):] == finals if finals else "mock" not in kinds
    studied = {t.topic_id for d in plan.days for t in d.tasks if t.kind == "study"}
    assert studied == {1, 2, 3}


def test_errors():
    with pytest.raises(PlanError, match="after today"):
        build_plan(STATS, TODAY, 3, today=TODAY)
    with pytest.raises(PlanError, match="Not enough time"):
        build_plan(STATS, TODAY + timedelta(days=2), 1, today=TODAY)  # 10 topics, 4 slots
    with pytest.raises(PlanError, match="No topics"):
        build_plan([], TODAY + timedelta(days=5), 3, today=TODAY)


def test_round_trip():
    plan = plan_14()
    assert planner.Plan.from_dict(plan.to_dict()) == plan


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    uid = db.get_or_create_user("u")["id"]
    d1 = db.add_document(uid, "unit3.pdf", None, 20)
    d2 = db.add_document(uid, "unit4.pdf", None, 20)
    db.set_topics(uid, d1, ["Pig macros", "Flume sinks"])
    db.set_topics(uid, d2, ["Hive tables", "Sqoop export"])
    return uid, {t["name"]: t["id"] for t in db.list_topics(uid)}, (d1, d2)


def quiz_on(uid, tid, results):
    db.save_quiz_attempt(uid, sum(results), len(results), [(tid, "q", "a", "b", ok) for ok in results])


def test_plan_shifts_time_away_from_a_topic_after_improvement(env):
    uid, ids, _ = env
    hive = ids["Hive tables"]
    quiz_on(uid, hive, [False] * 4)  # weak
    exam = TODAY + timedelta(days=14)
    first = planner.create(uid, exam, 2, today=TODAY)
    quiz_on(uid, hive, [True] * 10)  # now strong on the last 10 answers
    assert memory.topic_stats(uid, [hive])[0].status == "strong"
    second = planner.regenerate(uid, first, today=TODAY)
    assert second.topic_hours[hive] < first.topic_hours[hive]
    names = {v: k for k, v in ids.items()}
    assert any(line.startswith("Hive tables:") for line in planner.changes(first, second, names))
    assert planner.latest(uid)[1] == second


def test_document_scope_is_kept_on_regenerate(env):
    uid, ids, (d1, _) = env
    first = planner.create(uid, TODAY + timedelta(days=10), 2, [d1], today=TODAY)
    assert set(first.topic_hours) == {ids["Pig macros"], ids["Flume sinks"]}
    assert set(planner.regenerate(uid, first, today=TODAY).topic_hours) == set(first.topic_hours)


def test_marking_days_done_is_saved(env):
    uid, _, _ = env
    planner.create(uid, TODAY + timedelta(days=7), 2, today=TODAY)
    plan_id, plan = planner.latest(uid)
    plan.days[0].done = True
    planner.save(plan_id, plan)
    assert planner.latest(uid)[1].days[0].done
