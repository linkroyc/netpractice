"""Сборка и проверка учебного контента.

Чтобы добавить задание, достаточно дописать словарь в файл нужного модуля.
При запуске приложение проверит обязательные поля и уникальность ID.
"""

from __future__ import annotations

from .theory import MODULES
from .hints import HINTS
from . import module1, module2, module3, module4, module5, module6, module7

_MODULE_QUESTIONS = {
    1: module1.QUESTIONS,
    2: module2.QUESTIONS,
    3: module3.QUESTIONS,
    4: module4.QUESTIONS,
    5: module5.QUESTIONS,
    6: module6.QUESTIONS,
    7: module7.QUESTIONS,
}

DEFAULT_XP = {
    "choice": 10,
    "input": 12,
    "multi": 15,
    "scenario": 20,
    "troubleshoot": 25,
}

ALLOWED_TYPES = {"input", "multi", "choice", "scenario", "troubleshoot"}
ALLOWED_KINDS = {"text", "ip", "mask", "cidr", "int", "host"}

REQUIRED_FIELDS = (
    "id",
    "module",
    "topic",
    "difficulty",
    "type",
    "prompt",
    "explanation",
    "sample",
)


def _normalize_question(raw: dict) -> dict:
    question = dict(raw)
    missing = [field for field in REQUIRED_FIELDS if not question.get(field)]
    if missing:
        raise ValueError(f"Задание {question.get('id', '?')}: нет полей {missing}")

    if question["type"] not in ALLOWED_TYPES:
        raise ValueError(f"Задание {question['id']}: неизвестный тип {question['type']}")
    if question["difficulty"] not in (1, 2, 3):
        raise ValueError(f"Задание {question['id']}: сложность должна быть 1–3")
    if not isinstance(question["module"], int):
        raise ValueError(f"Задание {question['id']}: module должен быть числом")

    question.setdefault("xp", DEFAULT_XP[question["type"]])
    question.setdefault("source", "Материал подготовлен для тренажёра NetPractice")
    question.setdefault("hints", list(HINTS.get(question["id"], [])))

    question_type = question["type"]
    if question_type == "input":
        if not question.get("answers"):
            raise ValueError(f"Задание {question['id']}: нет answers")
        question.setdefault("answer_kind", "text")
        if question["answer_kind"] not in ALLOWED_KINDS:
            raise ValueError(f"Задание {question['id']}: неизвестный answer_kind")
    elif question_type == "multi":
        fields = question.get("fields") or []
        if len(fields) < 2:
            raise ValueError(f"Задание {question['id']}: нужно минимум два поля")
        keys = set()
        for field in fields:
            if not field.get("key") or not field.get("label") or not field.get("answers"):
                raise ValueError(f"Задание {question['id']}: неполное поле расчёта")
            if field["key"] in keys:
                raise ValueError(f"Задание {question['id']}: повторяется ключ поля")
            keys.add(field["key"])
            field.setdefault("kind", "text")
            if field["kind"] not in ALLOWED_KINDS:
                raise ValueError(f"Задание {question['id']}: неизвестный kind поля")
    elif question_type == "choice":
        options = question.get("options") or []
        if len(options) < 2:
            raise ValueError(f"Задание {question['id']}: нужно минимум два варианта")
        if not isinstance(question.get("correct"), int) or not (
            0 <= question["correct"] < len(options)
        ):
            raise ValueError(f"Задание {question['id']}: неверный correct")
    else:
        keywords = question.get("keywords") or []
        if len(keywords) < 3:
            raise ValueError(f"Задание {question['id']}: нужно минимум три ключевых пункта")
        for keyword in keywords:
            if not keyword.get("label") or not keyword.get("patterns"):
                raise ValueError(f"Задание {question['id']}: неполный ключевой пункт")
        minimum = question.setdefault("min_points", max(2, (len(keywords) + 1) // 2))
        if not 1 <= minimum <= len(keywords):
            raise ValueError(f"Задание {question['id']}: неверный min_points")

    return question


_ALL = []
for module_id, questions in _MODULE_QUESTIONS.items():
    for raw in questions:
        if raw.get("module") != module_id:
            raise ValueError(f"Задание {raw.get('id')}: модуль не совпадает с файлом")
        _ALL.append(_normalize_question(raw))

_ids = [question["id"] for question in _ALL]
if len(_ids) != len(set(_ids)):
    raise ValueError("ID заданий должны быть уникальными")

# Внутри модуля задания идут от простого к сложному. Сортировка стабильна,
# поэтому порядок заданий одной сложности сохраняется.
_ALL.sort(key=lambda question: (question["module"], question["difficulty"]))

ALL_QUESTIONS = _ALL
QUESTIONS_BY_ID = {question["id"]: question for question in ALL_QUESTIONS}
QUESTIONS_BY_MODULE = {
    module["id"]: [
        question for question in ALL_QUESTIONS if question["module"] == module["id"]
    ]
    for module in MODULES
}

for module in MODULES:
    module["question_count"] = len(QUESTIONS_BY_MODULE[module["id"]])


def normalize_question(raw: dict) -> dict:
    """Проверить и нормализовать вопрос (используется и для пакетов)."""
    return _normalize_question(raw)


def get_question(question_id: str):
    return QUESTIONS_BY_ID.get(question_id)


def get_module(module_id: int):
    for module in MODULES:
        if module["id"] == module_id:
            return module
    return None
