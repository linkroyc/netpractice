import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from content import get_question
from database import Database, compute_streak
from grading import grade_answer


def make_session(db, qids, kind="practice", key="test", day="2026-10-20"):
    return db.create_session(kind, key, qids)


def answer(db, session_id, question, answer_value, day="2026-10-20", mode="practice"):
    result = grade_answer(question, answer_value)
    return db.record_attempt(
        session_id, question, answer_value, result, mode, day, question["xp"]
    )


def insert_day(db, day, correct=1):
    with db.connect() as connection:
        connection.execute(
            """INSERT INTO attempts
               (uid, session_id, question_id, module_id, day, created_at, mode,
                answer, correct, score, xp_awarded, detail)
               VALUES (?, NULL, 'm1-01', 1, ?, ?, 'practice', '{}', ?, 100, 0, '{}')""",
            (uuid.uuid4().hex, day, f"{day} 10:00:00", correct),
        )


def test_database_file_is_created(tmp_path):
    path = tmp_path / "nested" / "test.db"
    db = Database(path)
    assert path.exists()
    assert db.overview(date(2026, 10, 20))["answered"] == 0


def test_xp_is_awarded_only_once_per_question(tmp_path):
    db = Database(tmp_path / "test.db")
    question = get_question("m2-01")

    first_session = make_session(db, [question["id"]])
    _, xp = answer(db, first_session, question, {"value": "255.255.255.192"})
    assert xp == question["xp"]
    assert db.total_xp() == question["xp"]

    second_session = make_session(db, [question["id"]])
    _, xp_again = answer(db, second_session, question, {"value": "/26"})
    assert xp_again == 0
    assert db.total_xp() == question["xp"]


def test_wrong_answer_enters_review_and_correct_removes(tmp_path):
    db = Database(tmp_path / "test.db")
    question = get_question("m2-01")
    session_id = make_session(db, [question["id"]])

    attempt_id, xp = answer(db, session_id, question, {"value": "255.255.255.0"})
    assert xp == 0
    assert db.review_count() == 1
    assert db.get_attempt(attempt_id)["correct"] == 0
    db.advance_session(session_id, "2026-10-20")

    session_id = make_session(db, [question["id"]])
    answer(db, session_id, question, {"value": "255.255.255.192"})
    assert db.review_count() == 0


def test_session_persists_and_resumes(tmp_path):
    path = tmp_path / "test.db"
    db = Database(path)
    question = get_question("m1-03")
    session_id = make_session(db, [question["id"]], kind="daily", key="2026-10-20")
    answer(db, session_id, question, {"value": "48"}, mode="daily")

    reopened = Database(path)
    session = reopened.get_session(session_id)
    assert session["pending_attempt_id"] is not None
    assert session["correct"] == 1
    assert session["position"] == 0

    reopened.advance_session(session_id, "2026-10-20")
    assert reopened.get_session(session_id)["completed"] == 1


def test_daily_bonus_once_per_day(tmp_path):
    db = Database(tmp_path / "test.db")
    question = get_question("m1-03")

    first = make_session(db, [question["id"]], kind="daily", key="2026-10-20")
    answer(db, first, question, {"value": "48"}, mode="daily")
    completed = db.advance_session(first, "2026-10-20")
    assert completed["bonus_xp"] == 15
    assert db.session_xp(first) == question["xp"] + 15

    second = make_session(db, [question["id"]], kind="daily", key="2026-10-20")
    answer(db, second, question, {"value": "48"}, mode="daily")
    completed = db.advance_session(second, "2026-10-20")
    assert completed["bonus_xp"] == 0
    assert db.total_xp() == question["xp"] + 15


def test_get_or_create_daily_session_reuses_unfinished(tmp_path):
    db = Database(tmp_path / "test.db")
    first = db.get_or_create_daily_session("2026-10-20", ["m1-01"])
    second = db.get_or_create_daily_session("2026-10-21", ["m1-02"])

    assert first == second
    assert db.get_session(first)["question_ids"] == ["m1-01"]
    with db.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE kind = 'daily' AND completed = 0"
        ).fetchone()["n"]
    assert count == 1


def test_parallel_daily_session_creation_is_atomic(tmp_path):
    db = Database(tmp_path / "test.db")

    def create(_):
        return db.get_or_create_daily_session("2026-10-20", ["m1-01"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(create, range(16)))

    assert len(set(ids)) == 1
    with db.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE kind = 'daily'"
        ).fetchone()["n"]
    assert count == 1


def test_streak_first_day(tmp_path):
    db = Database(tmp_path / "test.db")
    today = date(2026, 10, 20)
    insert_day(db, today.isoformat())
    stats = db.overview(today)
    assert stats["streak"] == 1
    assert stats["max_streak"] == 1
    assert stats["days_active"] == 1


def test_streak_repeat_same_day_does_not_grow(tmp_path):
    db = Database(tmp_path / "test.db")
    today = date(2026, 10, 20)
    insert_day(db, today.isoformat())
    insert_day(db, today.isoformat())
    stats = db.overview(today)
    assert stats["streak"] == 1
    assert stats["max_streak"] == 1


def test_streak_next_day_grows(tmp_path):
    db = Database(tmp_path / "test.db")
    today = date(2026, 10, 20)
    insert_day(db, (today - timedelta(days=1)).isoformat())
    insert_day(db, today.isoformat())
    stats = db.overview(today)
    assert stats["streak"] == 2
    assert stats["max_streak"] == 2


def test_streak_missed_day_breaks(tmp_path):
    db = Database(tmp_path / "test.db")
    today = date(2026, 10, 20)
    insert_day(db, (today - timedelta(days=2)).isoformat())
    insert_day(db, (today - timedelta(days=5)).isoformat())
    insert_day(db, today.isoformat())
    stats = db.overview(today)
    assert stats["streak"] == 1
    assert stats["max_streak"] == 1


def test_streak_current_and_max():
    today = date(2026, 10, 20)
    days = [(today - timedelta(days=n)).isoformat() for n in (5, 4, 3, 1, 0)]
    current, maximum = compute_streak(days, today)
    assert current == 2
    assert maximum == 3

    old_days = [(today - timedelta(days=n)).isoformat() for n in (8, 7, 6)]
    current, maximum = compute_streak(old_days, today)
    assert current == 0
    assert maximum == 3


def test_streak_continues_yesterday_without_today(tmp_path):
    db = Database(tmp_path / "test.db")
    today = date(2026, 10, 20)
    insert_day(db, (today - timedelta(days=1)).isoformat())
    insert_day(db, (today - timedelta(days=2)).isoformat())
    stats = db.overview(today)
    assert stats["streak"] == 2


def test_merge_backup_deduplicates(tmp_path):
    db = Database(tmp_path / "first.db")
    question = get_question("m2-02")
    session_id = make_session(db, [question["id"]])
    answer(db, session_id, question, {"value": "255.255.255.224"})
    db.advance_session(session_id, "2026-10-20")
    backup = db.export_data()

    other = Database(tmp_path / "second.db")
    other_question = get_question("m1-03")
    other_session = make_session(other, [other_question["id"]])
    answer(other, other_session, other_question, {"value": "48"})
    other.advance_session(other_session, "2026-10-20")
    xp_before = other.total_xp()

    counts = other.merge_from_backup(backup)
    assert counts["attempts"] == 1
    assert other.total_xp() == xp_before + question["xp"]

    counts_again = other.merge_from_backup(backup)
    assert counts_again["attempts"] == 0
    assert counts_again["question_awards"] == 0
    assert other.total_xp() == xp_before + question["xp"]


def test_replace_backup_clears_old_data(tmp_path):
    db = Database(tmp_path / "first.db")
    question = get_question("m2-02")
    session_id = make_session(db, [question["id"]])
    answer(db, session_id, question, {"value": "255.255.255.224"})
    db.advance_session(session_id, "2026-10-20")
    backup = db.export_data()

    other = Database(tmp_path / "second.db")
    old_question = get_question("m1-12")
    old_session = make_session(other, [old_question["id"]])
    answer(other, old_session, old_question, {"value": "7"})
    other.advance_session(old_session, "2026-10-19")
    assert other.overview(date(2026, 10, 20))["answered"] == 1

    counts = other.replace_from_backup(backup)
    assert counts["attempts"] == 1
    stats = other.overview(date(2026, 10, 20))
    assert stats["answered"] == 1
    assert stats["xp"] == question["xp"]
    assert stats["streak"] == 1
    assert other.review_count() == 0


def test_self_assessment_awards_xp_and_clears_review(tmp_path):
    db = Database(tmp_path / "test.db")
    question = get_question("m1-11")
    session_id = make_session(db, [question["id"]])
    attempt_id, xp = answer(db, session_id, question, {"text": "Не знаю."})
    assert xp == 0
    assert db.review_count() == 1

    awarded = db.mark_self_correct(
        attempt_id, session_id, question, question["xp"], "2026-10-20"
    )
    assert awarded == question["xp"]
    assert db.review_count() == 0
    attempt = db.get_attempt(attempt_id)
    assert attempt["correct"] == 1
    assert attempt["detail"]["self_assessed"] is True
    session = db.get_session(session_id)
    assert session["correct"] == 1
    assert session["wrong"] == 0
    assert db.total_xp() == question["xp"]


def test_self_assessment_cannot_award_twice(tmp_path):
    db = Database(tmp_path / "test.db")
    question = get_question("m1-11")
    session_id = make_session(db, [question["id"]])
    attempt_id, _ = answer(db, session_id, question, {"text": "Не знаю."})
    db.mark_self_correct(attempt_id, session_id, question, question["xp"], "2026-10-20")
    again = db.mark_self_correct(
        attempt_id, session_id, question, question["xp"], "2026-10-20"
    )
    assert again == 0
    assert db.total_xp() == question["xp"]
