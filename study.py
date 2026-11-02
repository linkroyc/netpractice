"""Логика обучения: прогресс модулей, подбор заданий и календарь."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from content import ALL_QUESTIONS, MODULES, QUESTIONS_BY_ID, QUESTIONS_BY_MODULE

DAILY_SIZE = 8
PRACTICE_SIZE = 6
REVIEW_SIZE = 8

MONTHS_SHORT = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


def module_progress(db) -> list[dict]:
    """Прогресс по каждому модулю и правила открытия следующего."""
    status = db.question_status()
    progress = []
    for module in MODULES:
        questions = QUESTIONS_BY_MODULE[module["id"]]
        total = len(questions)
        attempted = sum(
            1 for question in questions
            if status.get(question["id"], {}).get("attempts", 0) > 0
        )
        correct = sum(
            1 for question in questions
            if status.get(question["id"], {}).get("ever_correct")
        )
        progress.append({
            **module,
            "total": total,
            "attempted": attempted,
            "correct": correct,
            "percent_correct": round(correct * 100 / total) if total else 0,
            "percent_attempted": round(attempted * 100 / total) if total else 0,
            "unlocked": False,
        })

    for index, item in enumerate(progress):
        if index == 0:
            item["unlocked"] = True
            continue
        previous = progress[index - 1]
        threshold = max(3, math.ceil(previous["total"] * 0.6))
        item["unlocked"] = previous["unlocked"] and previous["attempted"] >= threshold
        item["unlock_needed"] = max(0, threshold - previous["attempted"])
        item["unlock_required"] = threshold
        item["unlock_done"] = previous["attempted"]
        item["unlock_from"] = previous["title"]
    return progress


def get_module_progress(db, module_id: int):
    for item in module_progress(db):
        if item["id"] == module_id:
            return item
    return None


def unlocked_questions(db):
    unlocked_ids = {item["id"] for item in module_progress(db) if item["unlocked"]}
    return [
        question for question in ALL_QUESTIONS
        if question["module"] in unlocked_ids
    ]


def _sample(rng: random.Random, items, limit):
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return list(items)
    return rng.sample(items, limit)


def _order_for_lesson(rng: random.Random, questions):
    rng.shuffle(questions)
    return sorted(questions, key=lambda question: question["difficulty"])


def build_daily(db, day: date, size: int = DAILY_SIZE) -> list[str]:
    """Собрать ежедневный урок: новый материал + повторение + закрепление."""
    progress = module_progress(db)
    unlocked = [item for item in progress if item["unlocked"]]
    if not unlocked:
        return []

    frontier_id = max(item["id"] for item in unlocked)
    unlocked_ids = {item["id"] for item in unlocked}
    status = db.question_status()
    wrong_ids = {row["question_id"] for row in db.review_questions()}

    frontier = [
        question for question in QUESTIONS_BY_MODULE[frontier_id]
    ]
    unseen_frontier = [
        question for question in frontier if question["id"] not in status
    ]

    rng = random.Random(
        day.toordinal() * 31 + frontier_id * 7
        + db.count_completed_daily(day.isoformat())
    )

    chosen = _sample(rng, unseen_frontier, min(5, size))
    chosen_ids = {question["id"] for question in chosen}

    review_pool = [
        question for question in ALL_QUESTIONS
        if question["module"] in unlocked_ids
        and question["id"] in wrong_ids
        and question["id"] not in chosen_ids
    ]
    picked = _sample(rng, review_pool, min(2, size - len(chosen)))
    chosen.extend(picked)
    chosen_ids.update(question["id"] for question in picked)

    older_pool = [
        question for question in ALL_QUESTIONS
        if question["module"] in unlocked_ids
        and question["module"] < frontier_id
        and question["id"] not in chosen_ids
        and question["id"] not in wrong_ids
    ]
    picked = _sample(rng, older_pool, min(1, size - len(chosen)))
    chosen.extend(picked)
    chosen_ids.update(question["id"] for question in picked)

    if len(chosen) < size:
        unseen_any = [
            question for question in ALL_QUESTIONS
            if question["module"] in unlocked_ids
            and question["id"] not in chosen_ids
            and question["id"] not in status
        ]
        seen_any = [
            question for question in ALL_QUESTIONS
            if question["module"] in unlocked_ids
            and question["id"] not in chosen_ids
            and question["id"] in status
        ]
        remaining = size - len(chosen)
        chosen.extend(_sample(rng, unseen_any, remaining))
        chosen_ids.update(question["id"] for question in chosen)
        if len(chosen) < size:
            chosen.extend(
                _sample(rng, seen_any, size - len(chosen))
            )

    return [question["id"] for question in _order_for_lesson(rng, chosen)]


def build_practice_from_questions(db, questions, day: date, seed: int,
                                  size: int = PRACTICE_SIZE) -> list[str]:
    """Подобрать практику из произвольного списка вопросов (в т.ч. пакета)."""
    status = db.question_status()
    wrong_ids = {row["question_id"] for row in db.review_questions()}
    rng = random.Random(day.toordinal() * 13 + seed)

    unseen = [question for question in questions if question["id"] not in status]
    unseen_ids = {question["id"] for question in unseen}
    wrong = [
        question for question in questions
        if question["id"] in wrong_ids and question["id"] not in unseen_ids
    ]
    wrong_ids_in_questions = {question["id"] for question in wrong}
    seen = [
        question for question in questions
        if question["id"] not in unseen_ids
        and question["id"] not in wrong_ids_in_questions
    ]

    chosen = _sample(rng, unseen, size)
    chosen.extend(_sample(rng, wrong, size - len(chosen)))
    chosen.extend(_sample(rng, seen, size - len(chosen)))
    return [question["id"] for question in _order_for_lesson(rng, chosen)]


def build_practice(db, module_id: int, day: date, size: int = PRACTICE_SIZE) -> list[str]:
    """Подобрать задания для практики по одному встроенному модулю."""
    return build_practice_from_questions(
        db, QUESTIONS_BY_MODULE.get(module_id, []), day, module_id, size
    )


def build_review(db, size: int = REVIEW_SIZE, lookup=None) -> list[str]:
    """Задания, на которых пользователь ошибался.

    lookup позволяет подключить вопросы пользовательских пакетов.
    """
    result = []
    for row in db.review_questions():
        question = QUESTIONS_BY_ID.get(row["question_id"])
        if question is None and lookup is not None:
            question = lookup(row["question_id"])
        if question is not None:
            result.append(question["id"])
        if len(result) >= size:
            break
    return result


def activity_level(count: int) -> int:
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 4:
        return 2
    if count <= 7:
        return 3
    return 4


def calendar_weeks(activity: dict, today: date, weeks: int = 12):
    """Календарь активности: список недель, каждая — 7 дней (Пн–Вс)."""
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=weeks - 1)
    result = []
    for week_index in range(weeks):
        week_start = start + timedelta(weeks=week_index)
        days = []
        for day_index in range(7):
            day = week_start + timedelta(days=day_index)
            entry = activity.get(day.isoformat(), {})
            count = int(entry.get("answered", 0))
            days.append({
                "date": day,
                "iso": day.isoformat(),
                "count": count,
                "xp": int(entry.get("xp", 0)),
                "level": activity_level(count),
                "future": day > today,
                "today": day == today,
            })
        month_label = ""
        for day in days:
            if day["date"].day == 1:
                month_label = MONTHS_SHORT[day["date"].month]
                break
        if week_index == 0:
            month_label = MONTHS_SHORT[days[0]["date"].month]
        result.append({"days": days, "month": month_label})
    return result


def recommended_module(progress):
    for item in progress:
        if item["unlocked"] and item["correct"] < item["total"]:
            return item
    return progress[-1] if progress else None


def lesson_title(kind: str, key: str) -> str:
    if kind == "daily":
        return "Ежедневное занятие"
    if kind == "practice":
        try:
            module_id = int(key)
        except (TypeError, ValueError):
            return "Практика"
        for module in MODULES:
            if module["id"] == module_id:
                return f"Практика: {module['title']}"
        return "Практика"
    if kind == "review":
        return "Повторение ошибок"
    return "Занятие"
