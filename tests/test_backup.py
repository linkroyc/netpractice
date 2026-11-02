import copy
import json
from datetime import date

import pytest

from backup import (
    FORMAT_NAME,
    FORMAT_VERSION,
    BackupError,
    build_backup,
    parse_backup,
)
from content import get_question
from database import Database
from grading import grade_answer


def make_backup(tmp_path):
    db = Database(tmp_path / "test.db")
    question = get_question("m2-05")
    session_id = db.create_session("daily", "2026-10-20", [question["id"]])
    answer = {"value": "192.168.10.128"}
    db.record_attempt(
        session_id, question, answer, grade_answer(question, answer),
        "daily", "2026-10-20", question["xp"],
    )
    db.advance_session(session_id, "2026-10-20")
    return build_backup(db), db


def test_build_and_parse_backup(tmp_path):
    payload, db = make_backup(tmp_path)
    assert payload["format"] == FORMAT_NAME
    assert payload["format_version"] == FORMAT_VERSION
    assert payload["counts"]["attempts"] == 1
    assert payload["data"]["question_awards"]

    data, counts = parse_backup(json.loads(json.dumps(payload)))
    assert counts["attempts"] == 1
    assert counts["daily_bonus"] == 1
    assert data["attempts"][0]["question_id"] == "m2-05"
    assert data["question_awards"][0]["xp"] == get_question("m2-05")["xp"]


def test_rejects_non_object():
    with pytest.raises(BackupError):
        parse_backup([])


def test_rejects_wrong_format(tmp_path):
    payload, _ = make_backup(tmp_path)
    payload["format"] = "something-else"
    with pytest.raises(BackupError, match="формат"):
        parse_backup(payload)


def test_rejects_newer_version(tmp_path):
    payload, _ = make_backup(tmp_path)
    payload["format_version"] = 99
    with pytest.raises(BackupError, match="новой версией"):
        parse_backup(payload)


def test_rejects_missing_data(tmp_path):
    payload, _ = make_backup(tmp_path)
    del payload["data"]
    with pytest.raises(BackupError, match="данн"):
        parse_backup(payload)


def test_rejects_bad_date(tmp_path):
    payload, _ = make_backup(tmp_path)
    payload["data"]["attempts"][0]["day"] = "2026-13-99"
    with pytest.raises(BackupError, match="дату"):
        parse_backup(payload)


def test_rejects_broken_json_inside_answer(tmp_path):
    payload, _ = make_backup(tmp_path)
    payload["data"]["attempts"][0]["answer"] = "{broken"
    with pytest.raises(BackupError, match="JSON"):
        parse_backup(payload)


def test_removes_duplicate_attempts(tmp_path):
    payload, _ = make_backup(tmp_path)
    duplicate = copy.deepcopy(payload["data"]["attempts"][0])
    payload["data"]["attempts"].append(duplicate)
    _, counts = parse_backup(payload)
    assert counts["attempts"] == 1


def test_unknown_question_ids_are_preserved(tmp_path):
    payload, _ = make_backup(tmp_path)
    payload["data"]["attempts"][0]["question_id"] = "old-question-99"
    data, _ = parse_backup(payload)
    assert data["attempts"][0]["question_id"] == "old-question-99"


def test_empty_backup_is_valid(tmp_path):
    db = Database(tmp_path / "empty.db")
    payload = build_backup(db)
    data, counts = parse_backup(payload)
    assert counts == {
        "attempts": 0,
        "question_awards": 0,
        "review_questions": 0,
        "daily_bonus": 0,
    }
    assert data["attempts"] == []


def test_payload_is_json_serializable(tmp_path):
    payload, _ = make_backup(tmp_path)
    text = json.dumps(payload, ensure_ascii=False)
    restored = json.loads(text)
    assert restored["exported_at"]
    assert restored["data"]["attempts"][0]["day"] == date(2026, 10, 20).isoformat()
