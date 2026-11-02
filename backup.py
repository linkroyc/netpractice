"""Экспорт и импорт прогресса в JSON.

Импортированный файл — это только данные. Никакой код из него не выполняется.
Перед импортом проверяются формат, версия, типы и допустимые размеры.
"""

from __future__ import annotations

import json
from datetime import date, datetime

FORMAT_NAME = "netpractice-backup"
FORMAT_VERSION = 1
MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_ATTEMPTS = 50000
MAX_AWARDS = 10000
MAX_REVIEW = 10000
MAX_BONUS = 10000
MODES = {"daily", "practice", "review"}


class BackupError(Exception):
    """Понятная пользователю ошибка формата резервной копии."""


def build_backup(db) -> dict:
    data = db.export_data()
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app": "NetPractice",
        "exported_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "description": (
            "Резервная копия прогресса NetPractice. Содержит историю ответов, "
            "начисленный XP, список ошибок для повторения и бонусы за занятия. "
            "Незавершённое занятие в файл не входит."
        ),
        "counts": {
            "attempts": len(data["attempts"]),
            "question_awards": len(data["question_awards"]),
            "review_questions": len(data["review_questions"]),
            "daily_bonus": len(data["daily_bonus"]),
        },
        "data": data,
    }


def _require_string(value, field, max_length=120, allow_empty=False):
    if not isinstance(value, str):
        raise BackupError(f"Поле «{field}» должно быть строкой.")
    value = value.strip()
    if not allow_empty and not value:
        raise BackupError(f"Поле «{field}» не может быть пустым.")
    if len(value) > max_length:
        raise BackupError(f"Поле «{field}» слишком длинное.")
    return value


def _require_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackupError(f"Поле «{field}» должно быть целым числом.")
    if not minimum <= value <= maximum:
        raise BackupError(
            f"Поле «{field}» должно быть в диапазоне {minimum}–{maximum}."
        )
    return value


def _require_day(value, field):
    text = _require_string(value, field, 10)
    try:
        date.fromisoformat(text)
    except ValueError as error:
        raise BackupError(f"Поле «{field}» содержит некорректную дату.") from error
    return text


def _require_timestamp(value, field):
    text = _require_string(value, field, 40)
    return text


def _require_json_text(value, field, max_length):
    if not isinstance(value, str):
        raise BackupError(f"Поле «{field}» должно содержать JSON-строку.")
    if len(value) > max_length:
        raise BackupError(f"Поле «{field}» слишком длинное.")
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as error:
        raise BackupError(f"Поле «{field}» содержит повреждённый JSON.") from error
    return json.dumps(parsed, ensure_ascii=False)


def _require_list(data, key, limit):
    value = data.get(key)
    if not isinstance(value, list):
        raise BackupError(f"Раздел «{key}» отсутствует или имеет неверный формат.")
    if len(value) > limit:
        raise BackupError(
            f"Раздел «{key}» слишком большой (максимум {limit} записей)."
        )
    return value


def _clean_attempt(item):
    if not isinstance(item, dict):
        raise BackupError("Запись истории ответов имеет неверный формат.")
    return {
        "uid": _require_string(item.get("uid"), "attempts.uid", 80),
        "question_id": _require_string(
            item.get("question_id"), "attempts.question_id", 80
        ),
        "module_id": _require_int(item.get("module_id"), "attempts.module_id", 1, 99),
        "day": _require_day(item.get("day"), "attempts.day"),
        "created_at": _require_timestamp(
            item.get("created_at"), "attempts.created_at"
        ),
        "mode": (
            item.get("mode")
            if item.get("mode") in MODES
            else "practice"
        ),
        "answer": _require_json_text(
            item.get("answer"), "attempts.answer", 5000
        ),
        "correct": _require_int(item.get("correct"), "attempts.correct", 0, 1),
        "score": _require_int(item.get("score"), "attempts.score", 0, 100),
        "xp_awarded": _require_int(
            item.get("xp_awarded"), "attempts.xp_awarded", 0, 1000
        ),
        "detail": _require_json_text(
            item.get("detail", "{}"), "attempts.detail", 20000
        ),
    }


def _clean_award(item):
    if not isinstance(item, dict):
        raise BackupError("Запись о начислении XP имеет неверный формат.")
    return {
        "question_id": _require_string(
            item.get("question_id"), "question_awards.question_id", 80
        ),
        "xp": _require_int(item.get("xp"), "question_awards.xp", 0, 1000),
        "day": _require_day(item.get("day"), "question_awards.day"),
        "created_at": _require_timestamp(
            item.get("created_at"), "question_awards.created_at"
        ),
    }


def _clean_review(item):
    if not isinstance(item, dict):
        raise BackupError("Запись списка повторения имеет неверный формат.")
    return {
        "question_id": _require_string(
            item.get("question_id"), "review_questions.question_id", 80
        ),
        "module_id": _require_int(
            item.get("module_id"), "review_questions.module_id", 1, 99
        ),
        "wrong_count": _require_int(
            item.get("wrong_count"), "review_questions.wrong_count", 1, 100000
        ),
        "first_wrong_at": _require_timestamp(
            item.get("first_wrong_at"), "review_questions.first_wrong_at"
        ),
        "last_wrong_at": _require_timestamp(
            item.get("last_wrong_at"), "review_questions.last_wrong_at"
        ),
    }


def _clean_bonus(item):
    if not isinstance(item, dict):
        raise BackupError("Запись о бонусе за занятие имеет неверный формат.")
    return {
        "day": _require_day(item.get("day"), "daily_bonus.day"),
        "xp": _require_int(item.get("xp"), "daily_bonus.xp", 0, 1000),
        "created_at": _require_timestamp(
            item.get("created_at"), "daily_bonus.created_at"
        ),
    }


def parse_backup(payload):
    """Проверить и очистить резервную копию. Вернуть (data, counts)."""
    if not isinstance(payload, dict):
        raise BackupError("Файл не похож на резервную копию NetPractice.")
    if payload.get("format") != FORMAT_NAME:
        raise BackupError(
            "Неизвестный формат файла. Выберите JSON-файл, созданный кнопкой "
            "«Экспорт прогресса»."
        )

    version = payload.get("format_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise BackupError("В файле не указана версия формата.")
    if version > FORMAT_VERSION:
        raise BackupError(
            "Файл создан более новой версией приложения. Обновите NetPractice, "
            "чтобы импортировать его."
        )
    if version != FORMAT_VERSION:
        raise BackupError(f"Неподдерживаемая версия формата: {version}.")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise BackupError("В файле нет раздела с данными.")

    raw_attempts = _require_list(data, "attempts", MAX_ATTEMPTS)
    raw_awards = _require_list(data, "question_awards", MAX_AWARDS)
    raw_review = _require_list(data, "review_questions", MAX_REVIEW)
    raw_bonus = _require_list(data, "daily_bonus", MAX_BONUS)

    attempts = []
    seen_uids = set()
    for item in raw_attempts:
        clean = _clean_attempt(item)
        if clean["uid"] in seen_uids:
            continue
        seen_uids.add(clean["uid"])
        attempts.append(clean)

    awards = []
    seen_awards = set()
    for item in raw_awards:
        clean = _clean_award(item)
        if clean["question_id"] in seen_awards:
            continue
        seen_awards.add(clean["question_id"])
        awards.append(clean)

    review = []
    seen_review = set()
    for item in raw_review:
        clean = _clean_review(item)
        if clean["question_id"] in seen_review:
            continue
        seen_review.add(clean["question_id"])
        review.append(clean)

    bonus = []
    seen_bonus = set()
    for item in raw_bonus:
        clean = _clean_bonus(item)
        if clean["day"] in seen_bonus:
            continue
        seen_bonus.add(clean["day"])
        bonus.append(clean)

    cleaned = {
        "attempts": attempts,
        "question_awards": awards,
        "review_questions": review,
        "daily_bonus": bonus,
    }
    counts = {key: len(value) for key, value in cleaned.items()}
    return cleaned, counts
