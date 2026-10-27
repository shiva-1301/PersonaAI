from streamlit.testing.v1 import AppTest

from core import config


def text(at) -> str:
    """All markdown/HTML on the page as one string (page titles, stat tiles and badges
    are rendered as HTML, not st.title / st.metric)."""
    return " ".join(m.value for m in at.markdown)


def signed_in(page: str, user_id: int, name: str = "Vivek") -> AppTest:
    at = AppTest.from_file(f"../views/{page}.py", default_timeout=10)
    at.session_state.user_id = user_id
    at.session_state.username = name
    return at


def _app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db, rag
    monkeypatch.setattr(rag, "warm_up", lambda: None)
    db.init_db()
    db.import_students([{"hall_ticket": "22B81A0501", "name": "Ananya Rao", "department": "CSE", "year": "3"}])
    return AppTest.from_file("../app.py", default_timeout=10).run()


def sign_in(at, ticket, password):
    at.text_input[0].input(ticket)
    at.text_input[1].input(password)
    at.button[0].click().run()
    assert not at.exception


def test_first_sign_in_then_password_login(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    assert "pa-login-title" in text(at) and not at.sidebar.button  # no sidebar before login

    sign_in(at, "22b81a0501", "")  # registered, no password yet
    assert "First sign-in for <b>22B81A0501</b>" in text(at)
    at.text_input[0].input("secret123")
    at.text_input[1].input("secret123")
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state.username == "22B81A0501" and at.session_state.role == "student"
    assert "Welcome back, Ananya" in text(at)  # home page hero
    assert "CSE · Year 3" in " ".join(m.value for m in at.sidebar.markdown)
    assert [b.label for b in at.sidebar.button] == ["Log out"]

    at.sidebar.button[0].click().run()  # log out, then sign in with the password
    sign_in(at, "22B81A0501", "wrong-pass")
    assert at.error[0].value == "Wrong hall ticket number or password."
    sign_in(at, "22B81A0501", "secret123")
    assert at.session_state.role == "student"


def test_unknown_or_empty_hall_ticket_is_refused(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    at.button[0].click().run()
    assert at.error[0].value == "Please enter your hall ticket number."
    sign_in(at, "99X99", "whatever")
    assert "isn't registered" in at.error[0].value
    assert "user_id" not in at.session_state


def test_admin_sign_in_shows_only_admin_page(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "admin-pass")
    at = _app(tmp_path, monkeypatch)
    sign_in(at, "admin", "admin-pass")
    assert at.session_state.role == "admin"
    assert "Import a class list" in text(at)
    assert "Administrator" in " ".join(m.value for m in at.sidebar.markdown)


def test_admin_page_shares_notes_with_a_cohort(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db, ingest
    db.init_db()
    db.import_students([{"hall_ticket": "22B81A0501", "name": "Ananya Rao", "department": "CSE", "year": "3"}])
    admin = db.get_or_create_user("admin")["id"]
    at = AppTest.from_file("../views/admin.py", default_timeout=10)
    at.session_state.user_id, at.session_state.username, at.session_state.role = admin, "admin", "admin"
    at.run()
    assert not at.exception
    assert "CSE · Year 3" in text(at) and "1 students" in text(at)

    [subject_box] = [t for t in at.text_input if t.label == "New subject"]
    subject_box.input("Big Data")
    next(b for b in at.button if b.label == "Add subject").click().run()
    assert not at.exception
    cohort = db.get_or_create_cohort("CSE", "3")
    assert [s["name"] for s in db.list_subjects(cohort)] == ["Big Data"]


def test_admin_page_is_closed_to_students(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db
    db.init_db()
    at = signed_in("admin", db.get_or_create_user("22B81A0501")["id"]).run()
    assert "for the admin only" in at.warning[0].value


def test_page_requires_login(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    at = AppTest.from_file("../views/notes_qa.py").run()
    assert not at.exception
    assert "sign in" in at.warning[0].value


def test_notes_page_empty_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db, rag
    monkeypatch.setattr(rag, "warm_up", lambda: None)  # skip loading ML models
    db.init_db()
    at = signed_in("notes_qa", db.get_or_create_user("Vivek")["id"]).run()
    assert not at.exception
    assert "Notes Q&amp;A" in text(at) or "Notes Q&A" in text(at)
    assert "Upload your notes on the right first" in text(at)


def _quiz_user(tmp_path, monkeypatch, n=5):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db, quiz, rag
    monkeypatch.setattr(rag, "warm_up", lambda: None)
    db.init_db()
    uid = db.get_or_create_user("Vivek")["id"]
    doc = db.add_document(uid, "unit4.pdf", None, 20)
    db.set_topics(uid, doc, ["Hive tables"])
    tid = db.list_topics(uid)[0]["id"]
    fake = [quiz.Question(tid, "Hive tables", f"Question {i}?", ["a", "b", "c", "d"], 1, "because", "unit4.pdf, p. 3")
            for i in range(n)]
    monkeypatch.setattr(quiz, "generate", lambda user_id, alloc: fake)
    return uid


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception


def test_quiz_page_one_question_at_a_time(tmp_path, monkeypatch):
    from core import db
    uid = _quiz_user(tmp_path, monkeypatch)
    at = signed_in("quiz", uid).run()
    assert not at.exception
    at.button_group[0].set_value(5).run()  # number of questions
    click(at, "Generate quiz")
    assert "Question 1 of 5" in text(at)

    # Answer Q1, go forward, come back: the answer is kept.
    at.radio(key="q_0").set_value(1).run()
    click(at, "Next")
    assert "Question 2 of 5" in text(at)
    click(at, "Previous")
    assert at.radio(key="q_0").value == 1

    # Skip to the end; submitting with blanks is refused.
    for _ in range(4):
        click(at, "Next")
    click(at, "Submit answers")
    assert "Answer every question first. Missing: 2, 3, 4, 5" in at.warning[0].value
    assert "Question 2 of 5" in text(at)  # taken to the first unanswered question

    # Answer the rest (one wrong) via the question navigator.
    for i in range(1, 5):
        at.pills[0].set_value(i).run()
        at.radio(key=f"q_{i}").set_value(1 if i < 4 else 2).run()
    click(at, "Submit answers")
    assert "4 / 5" in text(at) and "80%" in text(at)
    [attempt] = db.list_quiz_attempts(uid)
    assert (attempt["score"], attempt["total"]) == (4, 5)


def _user_with_history(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db, rag
    monkeypatch.setattr(rag, "warm_up", lambda: None)
    db.init_db()
    uid = db.get_or_create_user("Vivek")["id"]
    doc = db.add_document(uid, "unit4.pdf", None, 20)
    db.set_topics(uid, doc, ["Hive tables", "Sqoop export", "Pig macros"])
    ids = {t["name"]: t["id"] for t in db.list_topics(uid)}
    db.save_quiz_attempt(uid, 1, 4, [(ids["Hive tables"], f"q{i}", "x", "y", i == 0) for i in range(4)])
    db.save_quiz_attempt(uid, 3, 3, [(ids["Sqoop export"], f"s{i}", "y", "y", True) for i in range(3)])
    return uid, ids


def test_home_dashboard(tmp_path, monkeypatch):
    uid, _ = _user_with_history(tmp_path, monkeypatch)
    at = signed_in("home", uid).run()
    assert not at.exception
    page = text(at)
    assert "Welcome back, Vivek" in page
    assert "Quizzes taken" in page and "57%" in page  # 4 of 7 answers correct
    assert "Hive tables · 25%" in page  # weak-topic chip
    assert any(b.label == "Take an adaptive quiz" for b in at.button)


def test_progress_page_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db
    db.init_db()
    at = signed_in("progress", db.get_or_create_user("Vivek")["id"]).run()
    assert not at.exception
    assert "No quizzes yet" in text(at)


def test_progress_page_with_history(tmp_path, monkeypatch):
    uid, _ = _user_with_history(tmp_path, monkeypatch)
    at = signed_in("progress", uid).run()
    assert not at.exception
    page = text(at)
    for expected in ("Quizzes taken", "57%", "Hive tables · 25%", "Sqoop export · 100%", "2 / 3"):
        assert expected in page, expected


def test_quiz_page_adaptive_targets_weak_topics(tmp_path, monkeypatch):
    uid, ids = _user_with_history(tmp_path, monkeypatch)
    from core import quiz
    seen = {}

    def fake_generate(user_id, allocation):
        seen.update(allocation)
        return [quiz.Question(ids["Hive tables"], "Hive tables", "Q?", ["a", "b", "c", "d"], 0, "", None)]

    monkeypatch.setattr(quiz, "generate", fake_generate)
    at = signed_in("quiz", uid).run()
    assert "Hive tables · 25%" in text(at)  # adaptive focus chip
    click(at, "Generate quiz")
    # 10 questions: 6 on the weak topic, the rest untested first
    assert seen[ids["Hive tables"]] == 6 and seen[ids["Pig macros"]] >= 2


def test_study_plan_create_mark_done_and_regenerate(tmp_path, monkeypatch):
    uid, ids = _user_with_history(tmp_path, monkeypatch)
    from core import planner
    at = signed_in("study_plan", uid).run()
    assert not at.exception
    at.number_input[0].set_value(2.0)
    click(at, "Create plan")
    plan_id, plan = planner.latest(uid)
    # Default timetable: one exam ("General": notes without a subject) two weeks out.
    assert [e["subject"] for e in plan.exams] == ["General"]
    assert len(plan.days) == 15 and set(plan.topic_hours) == set(ids.values())
    assert plan.days[-1].tasks[0].kind == "exam" and "Next exam: General" in text(at)
    # Weak "Hive tables" (25%) gets the most time and is flagged as a priority chip
    assert max(plan.topic_hours, key=plan.topic_hours.get) == ids["Hive tables"]
    assert "⚑" in text(at) and "Today" in text(at)

    at.checkbox(key=f"done_{plan_id}_0").check().run()
    assert not at.exception
    assert planner.latest(uid)[1].days[0].done

    click(at, "Regenerate with latest scores")
    assert "Plan regenerated" in at.success[0].value  # no new quizzes -> unchanged


def test_study_plan_timetable_for_cohort_subjects(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    from core import db, planner
    db.init_db()
    db.import_students([{"hall_ticket": "22B81A0501", "name": "Ananya Rao", "department": "CSE", "year": "3"}])
    admin = db.get_or_create_user("admin")["id"]
    cse = db.get_or_create_cohort("CSE", "3")
    for subject in ("DBMS", "Operating Systems"):
        doc = db.add_document(admin, f"{subject}.pdf", None, 5, cohort_id=cse,
                              subject_id=db.add_subject(cse, subject), unit="Unit 1")
        db.set_topics(admin, doc, [f"{subject} basics", f"{subject} advanced"])
    uid = db.find_user("22B81A0501")["id"]

    at = signed_in("study_plan", uid).run()
    assert not at.exception
    click(at, "Create plan")  # default timetable: one row per subject, two days apart
    _, plan = planner.latest(uid)
    assert [e["subject"] for e in plan.exams] == ["DBMS", "Operating Systems"]
    assert [e["exam_date"] for e in db.list_exams(uid)] == [e["date"] for e in plan.exams]
    assert "DBMS · Study:" in text(at) and "Next exam: DBMS" in text(at)
