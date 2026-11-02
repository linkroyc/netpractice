"""Проверка ответов.

Числовые, IP-адресные и короткие ответы проверяются детерминированно.
Развёрнутые ответы оцениваются по ключевым понятиям: пользователь видит,
какие пункты он упомянул, а какие пропустил. Если автоматическая оценка
спорна, интерфейс предлагает сверить ответ с образцом.
"""

from __future__ import annotations

import ipaddress
import math
import re

TYPE_LABELS = {
    "input": "Короткий ответ",
    "multi": "Расчёт по полям",
    "choice": "Выбор варианта",
    "scenario": "Технический сценарий",
    "troubleshoot": "Поиск неисправности",
}

DIFFICULTY_LABELS = {1: "Начальный", 2: "Средний", 3: "Продвинутый"}


def normalize_text(value: str) -> str:
    """Привести текст к сравнимому виду: регистр, ё, знаки, пробелы."""
    if value is None:
        return ""
    text = str(value).lower().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_prefix(value: str):
    """Разобрать маску или префикс в число бит (0..32)."""
    text = str(value).strip().lower().replace(" ", "")
    if not text:
        return None
    if text.startswith("/"):
        text = text[1:]
    if text.isdigit():
        number = int(text)
        return number if 0 <= number <= 32 else None
    try:
        network = ipaddress.IPv4Network("0.0.0.0/" + text, strict=False)
    except (ipaddress.NetmaskValueError, ipaddress.AddressValueError, ValueError):
        return None
    # ipaddress допускает только непрерывные маски, поэтому результат надёжен.
    return network.prefixlen


def _parse_ip(value: str):
    text = str(value).strip().lower()
    if "/" in text:
        text = text.split("/", 1)[0]
    try:
        return ipaddress.IPv4Address(text)
    except (ipaddress.AddressValueError, ValueError):
        return None


def _parse_int(value: str):
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else None


def _check_single(value: str, kind: str, accepted) -> bool:
    if kind == "host":
        given = _parse_ip(value)
        if given is None:
            return False
        try:
            network = ipaddress.IPv4Network(str(accepted[0]), strict=False)
        except (ipaddress.AddressValueError, ValueError):
            return False
        return (
            given in network
            and given not in (network.network_address, network.broadcast_address)
        )
    if kind in ("ip", "mask", "cidr"):
        parser = _parse_prefix if kind in ("mask", "cidr") else _parse_ip
        given = parser(value)
        if given is None:
            return False
        return any(parser(answer) == given for answer in accepted)
    if kind == "int":
        given = _parse_int(value)
        if given is None:
            return False
        return any(_parse_int(answer) == given for answer in accepted)
    normalized = normalize_text(value)
    if not normalized:
        return False
    return normalized in {normalize_text(answer) for answer in accepted}


def _plain_text(value, limit=600):
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def _field_result(key, label, given, expected, correct):
    return {
        "key": key,
        "label": label,
        "given": _plain_text(given),
        "expected": _plain_text(expected),
        "correct": bool(correct),
    }


def _grade_input(question, answer):
    given = answer.get("value", "")
    accepted = question["answers"]
    kind = question.get("answer_kind", "text")
    correct = _check_single(given, kind, accepted)
    field = _field_result(
        "value", question.get("answer_label", "Ответ"), given,
        question.get("answer_display", accepted[0]), correct,
    )
    return {
        "correct": correct,
        "score": 100 if correct else 0,
        "fields": [field],
        "matched": [],
        "missed": [],
        "empty": not normalize_text(given),
    }


def _expected_display(spec):
    if spec.get("display"):
        return spec["display"]
    if spec.get("kind") == "host":
        try:
            network = ipaddress.IPv4Network(str(spec["answers"][0]), strict=False)
            return str(network.network_address + 1)
        except (ipaddress.AddressValueError, ValueError):
            pass
    return spec["answers"][0]


def _grade_multi(question, answer):
    fields = []
    correct_count = 0
    for spec in question["fields"]:
        given = answer.get(spec["key"], "")
        correct = _check_single(
            given, spec.get("kind", "text"), spec["answers"]
        )
        correct_count += int(correct)
        fields.append(
            _field_result(
                spec["key"], spec["label"], given,
                _expected_display(spec), correct,
            )
        )
    total = len(fields)
    score = round(correct_count * 100 / total) if total else 0
    return {
        "correct": correct_count == total,
        "score": score,
        "fields": fields,
        "matched": [],
        "missed": [],
        "empty": all(not normalize_text(answer.get(f["key"], "")) for f in fields),
    }


def _grade_choice(question, answer):
    given = str(answer.get("value", "")).strip()
    options = question["options"]
    correct_index = int(question["correct"])
    given_index = int(given) if given.isdigit() else -1
    correct = given_index == correct_index
    field = _field_result(
        "value", "Выбранный вариант",
        options[given_index] if 0 <= given_index < len(options) else "—",
        options[correct_index], correct,
    )
    return {
        "correct": correct,
        "score": 100 if correct else 0,
        "fields": [field],
        "matched": [],
        "missed": [],
        "empty": not given,
    }


def _keyword_found(text: str, patterns) -> bool:
    normalized = normalize_text(text)
    for pattern in patterns:
        candidate = normalize_text(pattern)
        if candidate and candidate in normalized:
            return True
    return False


def _grade_written(question, answer):
    text = str(answer.get("text", "")).strip()
    keywords = question["keywords"]
    matched = []
    missed = []
    for keyword in keywords:
        if _keyword_found(text, keyword["patterns"]):
            matched.append(keyword["label"])
        else:
            missed.append(keyword["label"])

    total = len(keywords)
    min_points = int(question.get("min_points", max(2, math.ceil(total / 2))))
    score = round(len(matched) * 100 / total) if total else 0
    correct = len(matched) >= min_points and len(normalize_text(text)) >= 10

    return {
        "correct": correct,
        "score": score,
        "fields": [],
        "matched": matched,
        "missed": missed,
        "min_points": min_points,
        "needs_self_check": not correct,
        "empty": not normalize_text(text),
    }


def grade_answer(question: dict, answer: dict) -> dict:
    """Проверить ответ и вернуть подробный результат."""
    answer = answer or {}
    question_type = question["type"]
    if question_type == "input":
        result = _grade_input(question, answer)
    elif question_type == "multi":
        result = _grade_multi(question, answer)
    elif question_type == "choice":
        result = _grade_choice(question, answer)
    elif question_type in ("scenario", "troubleshoot"):
        result = _grade_written(question, answer)
    else:
        raise ValueError(f"Неизвестный тип задания: {question_type}")
    result["type"] = question_type
    return result


def collect_answer(question: dict, form) -> dict:
    """Собрать ответ из данных формы."""
    question_type = question["type"]
    if question_type == "input":
        return {"value": form.get("value", "").strip()}
    if question_type == "multi":
        return {
            field["key"]: form.get(field["key"], "").strip()
            for field in question["fields"]
        }
    if question_type == "choice":
        return {"value": form.get("value", "").strip()}
    if question_type in ("scenario", "troubleshoot"):
        return {"text": form.get("text", "").strip()}
    raise ValueError(f"Неизвестный тип задания: {question_type}")


def expected_answer(question: dict):
    """Эталон в машинном виде — используется в тестах и при самопроверке."""
    question_type = question["type"]
    if question_type == "input":
        return {"value": question["answers"][0]}
    if question_type == "multi":
        result = {}
        for field in question["fields"]:
            if field.get("kind") == "host":
                try:
                    network = ipaddress.IPv4Network(
                        str(field["answers"][0]), strict=False
                    )
                    result[field["key"]] = str(network.network_address + 1)
                except (ipaddress.AddressValueError, ValueError):
                    result[field["key"]] = field["answers"][0]
            else:
                result[field["key"]] = field["answers"][0]
        return result
    if question_type == "choice":
        return {"value": str(question["correct"])}
    if question_type in ("scenario", "troubleshoot"):
        parts = []
        for keyword in question["keywords"]:
            parts.append(keyword["patterns"][0])
        return {"text": "Проверить: " + ", ".join(parts)}
    raise ValueError(f"Неизвестный тип задания: {question_type}")
