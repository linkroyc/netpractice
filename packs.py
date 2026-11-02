"""Учебные пакеты .nptpack: проверка, установка, обновление и экспорт.

Пакет — ZIP-архив только с данными. Код из него никогда не выполняется,
файлы не распаковываются на диск: изображения сохраняются в SQLite как BLOB.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import zipfile
import zlib
from datetime import date
from pathlib import PurePosixPath

from content import ALLOWED_KINDS, ALLOWED_TYPES, normalize_question
from database import now_text

FORMAT_NAME = "nptpack"
FORMAT_VERSION = 1
APP_VERSION = "1.0.0"

MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_FILES = 60
MAX_JSON_BYTES = 1024 * 1024
MAX_QUESTIONS = 200
MAX_LABS = 50
MAX_ASSET_BYTES = 2 * 1024 * 1024
MAX_ASSET_SIDE = 4096
MAX_ASSET_PIXELS = 16 * 1024 * 1024

RESERVED_IDS = {"system", "netpractice", "core", "builtin"}

PACK_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
LOCAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CATEGORY_RE = re.compile(r"^[a-z][a-z0-9-]{1,49}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,4})?$")
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

DIFFICULTIES = {"beginner", "intermediate", "advanced"}
DIFFICULTY_LABELS = {
    "beginner": "Начальный",
    "intermediate": "Средний",
    "advanced": "Продвинутый",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SOF = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


class PackError(ValueError):
    """Понятная пользователю ошибка формата или установки пакета."""


# ----------------------------------------------------------------------
# Базовые проверки
# ----------------------------------------------------------------------

def _text(value, field: str, minimum=1, maximum=5000) -> str:
    if not isinstance(value, str):
        raise PackError(f"Поле «{field}» должно быть строкой.")
    value = value.strip()
    if len(value) < minimum:
        raise PackError(f"Поле «{field}» не заполнено.")
    if len(value) > maximum:
        raise PackError(f"Поле «{field}» слишком длинное (максимум {maximum}).")
    if CONTROL_RE.search(value):
        raise PackError(f"Поле «{field}» содержит недопустимые символы.")
    return value


def _int(value, field: str, minimum=0, maximum=10000) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PackError(f"Поле «{field}» должно быть целым числом.")
    if not minimum <= value <= maximum:
        raise PackError(f"Поле «{field}» должно быть в диапазоне {minimum}–{maximum}.")
    return value


def _bool(value, field: str) -> bool:
    if not isinstance(value, bool):
        raise PackError(f"Поле «{field}» должно быть true или false.")
    return value


def _list(value, field: str, minimum=0, maximum=100):
    if not isinstance(value, list):
        raise PackError(f"Поле «{field}» должно быть массивом.")
    if not minimum <= len(value) <= maximum:
        raise PackError(
            f"Поле «{field}» должно содержать от {minimum} до {maximum} элементов."
        )
    return value


def _strings(value, field: str, minimum=0, maximum=100, item_max=1000):
    items = _list(value, field, minimum, maximum)
    return [_text(item, f"{field}[{index}]", 1, item_max)
            for index, item in enumerate(items)]


def _slug(value, field: str, pattern=LOCAL_ID_RE) -> str:
    value = _text(value, field, 1, 64)
    if not pattern.match(value):
        raise PackError(
            f"Поле «{field}» должно содержать строчные латинские буквы, цифры и дефис."
        )
    return value


def parse_version(value: str, field: str = "version") -> tuple[int, int, int]:
    if not isinstance(value, str) or not VERSION_RE.match(value):
        raise PackError(f"Поле «{field}» должно иметь формат X.Y.Z.")
    return tuple(int(part) for part in value.split("."))


def compare_versions(first: str, second: str) -> int:
    left = parse_version(first)
    right = parse_version(second)
    return (left > right) - (left < right)


# ----------------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------------

def _validate_manifest(raw) -> dict:
    if not isinstance(raw, dict):
        raise PackError("manifest.json должен содержать объект.")
    if raw.get("format") != FORMAT_NAME:
        raise PackError("Неизвестный формат: ожидается nptpack.")
    version = raw.get("format_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise PackError("Поле «format_version» должно быть целым числом.")
    if version > FORMAT_VERSION:
        raise PackError(
            "Пакет создан более новой версией формата. Обновите NetPractice."
        )
    if version != FORMAT_VERSION:
        raise PackError(f"Неподдерживаемая версия формата: {version}.")

    pack_id = _slug(raw.get("id"), "manifest.id", PACK_ID_RE)
    if pack_id in RESERVED_IDS:
        raise PackError("Этот идентификатор зарезервирован для системного модуля.")

    title = _text(raw.get("title"), "manifest.title", 1, 120)
    description = _text(raw.get("description"), "manifest.description", 1, 1000)
    author = _text(raw.get("author"), "manifest.author", 1, 120)
    module_version = _text(raw.get("module_version"), "manifest.module_version", 1, 30)
    parse_version(module_version, "manifest.module_version")

    language = _text(raw.get("language"), "manifest.language", 2, 10)
    if not LANGUAGE_RE.match(language):
        raise PackError("Поле «manifest.language» имеет неверный формат.")

    difficulty = _text(raw.get("difficulty"), "manifest.difficulty", 1, 20)
    if difficulty not in DIFFICULTIES:
        raise PackError(
            "Поле «manifest.difficulty» должно быть beginner, intermediate или advanced."
        )

    category = _slug(raw.get("category"), "manifest.category", CATEGORY_RE)
    created_at = _text(raw.get("created_at"), "manifest.created_at", 10, 10)
    try:
        date.fromisoformat(created_at)
    except ValueError as error:
        raise PackError("Поле «manifest.created_at» содержит некорректную дату.") from error

    min_app_version = _text(
        raw.get("min_app_version"), "manifest.min_app_version", 1, 30
    )
    parse_version(min_app_version, "manifest.min_app_version")
    if compare_versions(APP_VERSION, min_app_version) < 0:
        raise PackError(
            f"Для пакета нужен NetPractice {min_app_version} или новее. "
            f"Текущая версия: {APP_VERSION}."
        )

    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "id": pack_id,
        "title": title,
        "description": description,
        "author": author,
        "module_version": module_version,
        "language": language,
        "difficulty": difficulty,
        "category": category,
        "created_at": created_at,
        "min_app_version": min_app_version,
    }


# ----------------------------------------------------------------------
# Вопросы и лабораторные
# ----------------------------------------------------------------------

def _clean_hints(item) -> list[str]:
    if item is None:
        return []
    return _strings(item, "hints", 0, 5, 300)


def _clean_question(item, pack_id: str, module_id: int, default_position: int,
                    assets: set[str]) -> dict:
    if not isinstance(item, dict):
        raise PackError("Каждый вопрос должен быть объектом.")

    local_id = _slug(item.get("id"), "questions.id")
    question_type = _text(item.get("type"), f"questions.{local_id}.type", 1, 30)
    if question_type not in ALLOWED_TYPES:
        raise PackError(f"Вопрос {local_id}: неизвестный тип «{question_type}».")

    topic = _text(item.get("topic"), f"questions.{local_id}.topic", 1, 120)
    prompt = _text(item.get("prompt"), f"questions.{local_id}.prompt", 1, 2000)
    explanation = _text(
        item.get("explanation"), f"questions.{local_id}.explanation", 1, 5000
    )
    sample = _text(item.get("sample"), f"questions.{local_id}.sample", 1, 3000)
    difficulty = _int(
        item.get("difficulty"), f"questions.{local_id}.difficulty", 1, 3
    )
    xp = _int(item.get("xp", 10), f"questions.{local_id}.xp", 0, 100)
    position = item.get("position", default_position)
    position = _int(position, f"questions.{local_id}.position", 0, 100000)
    hints = _clean_hints(item.get("hints"))

    image = item.get("image")
    if image is not None:
        image = _text(image, f"questions.{local_id}.image", 1, 200)
        if image not in assets:
            raise PackError(f"Вопрос {local_id}: изображение «{image}» отсутствует в assets.")

    question = {
        "id": f"npt:{pack_id}:{local_id}",
        "module": module_id,
        "topic": topic,
        "difficulty": difficulty,
        "type": question_type,
        "prompt": prompt,
        "explanation": explanation,
        "sample": sample,
        "xp": xp,
        "source": _text(
            item.get("source", "Учебный пакет NetPractice"),
            f"questions.{local_id}.source", 1, 300,
        ),
        "hints": hints,
        "local_id": local_id,
        "pack_id": pack_id,
        "position": position,
    }
    if image:
        question["image"] = image

    if question_type == "input":
        answer_kind = _text(
            item.get("answer_kind", "text"),
            f"questions.{local_id}.answer_kind", 1, 20,
        )
        if answer_kind not in ALLOWED_KINDS:
            raise PackError(f"Вопрос {local_id}: неизвестный answer_kind.")
        answers = _strings(
            item.get("answers"), f"questions.{local_id}.answers", 1, 20, 200
        )
        question["answer_kind"] = answer_kind
        question["answers"] = answers

    elif question_type == "choice":
        options = _strings(
            item.get("options"), f"questions.{local_id}.options", 2, 10, 300
        )
        correct = _int(
            item.get("correct"), f"questions.{local_id}.correct", 0, len(options) - 1
        )
        question["options"] = options
        question["correct"] = correct

    elif question_type == "multi":
        raw_fields = _list(
            item.get("fields"), f"questions.{local_id}.fields", 2, 10
        )
        fields = []
        keys = set()
        for index, raw_field in enumerate(raw_fields):
            if not isinstance(raw_field, dict):
                raise PackError(f"Вопрос {local_id}: поле {index + 1} должно быть объектом.")
            key = _slug(raw_field.get("key"), f"questions.{local_id}.fields.key")
            if key in keys:
                raise PackError(f"Вопрос {local_id}: повторяется ключ поля «{key}».")
            keys.add(key)
            kind = _text(
                raw_field.get("kind", "text"),
                f"questions.{local_id}.fields.{key}.kind", 1, 20,
            )
            if kind not in ALLOWED_KINDS:
                raise PackError(f"Вопрос {local_id}: неизвестный kind поля.")
            fields.append({
                "key": key,
                "label": _text(
                    raw_field.get("label"),
                    f"questions.{local_id}.fields.{key}.label", 1, 120,
                ),
                "kind": kind,
                "answers": _strings(
                    raw_field.get("answers"),
                    f"questions.{local_id}.fields.{key}.answers", 1, 20, 200,
                ),
            })
        question["fields"] = fields

    else:
        raw_keywords = item.get("keywords", item.get("criteria"))
        keyword_list = _list(
            raw_keywords, f"questions.{local_id}.keywords", 3, 20
        )
        keywords = []
        for index, raw_keyword in enumerate(keyword_list):
            if not isinstance(raw_keyword, dict):
                raise PackError(f"Вопрос {local_id}: критерий {index + 1} должен быть объектом.")
            keywords.append({
                "label": _text(
                    raw_keyword.get("label"),
                    f"questions.{local_id}.keywords.label", 1, 160,
                ),
                "patterns": _strings(
                    raw_keyword.get("patterns"),
                    f"questions.{local_id}.keywords.patterns", 1, 20, 200,
                ),
            })
        min_points = _int(
            item.get("min_points", max(2, (len(keywords) + 1) // 2)),
            f"questions.{local_id}.min_points", 1, len(keywords),
        )
        question["keywords"] = keywords
        question["min_points"] = min_points

    # Повторно используем валидатор основного контента: он гарантирует,
    # что вопрос совместим с grading.py и lesson.html.
    try:
        return normalize_question(question)
    except (ValueError, TypeError) as error:
        raise PackError(f"Вопрос {local_id}: {error}") from error


def _clean_lab(item, pack_id: str, module_id: int, default_position: int,
               assets: set[str]) -> dict:
    if not isinstance(item, dict):
        raise PackError("Каждая лабораторная работа должна быть объектом.")

    local_id = _slug(item.get("id"), "labs.id")
    title = _text(item.get("title"), f"labs.{local_id}.title", 1, 160)
    description = _text(item.get("description"), f"labs.{local_id}.description", 1, 2000)
    goal = _text(item.get("goal"), f"labs.{local_id}.goal", 1, 1000)
    theory = _text(item.get("theory"), f"labs.{local_id}.theory", 1, 8000)
    steps = _strings(item.get("steps"), f"labs.{local_id}.steps", 1, 50, 1000)
    commands = _strings(item.get("commands"), f"labs.{local_id}.commands", 0, 50, 500)
    expected = _strings(item.get("expected"), f"labs.{local_id}.expected", 1, 50, 1000)
    criteria = _strings(item.get("criteria"), f"labs.{local_id}.criteria", 1, 50, 1000)
    hints = _clean_hints(item.get("hints"))
    prerequisites = _strings(
        item.get("prerequisites"), f"labs.{local_id}.prerequisites", 0, 20, 500
    )
    explanation = _text(
        item.get("explanation"), f"labs.{local_id}.explanation", 1, 8000
    )
    position = _int(
        item.get("position", default_position),
        f"labs.{local_id}.position", 0, 100000,
    )
    manual_check = _bool(item.get("manual_check", True), f"labs.{local_id}.manual_check")
    if not manual_check:
        raise PackError(
            "Автоматическая проверка лабораторий пока не поддерживается; "
            "укажите manual_check: true."
        )

    image_names = _strings(
        item.get("assets", []), f"labs.{local_id}.assets", 0, 10, 200
    )
    for image in image_names:
        if image not in assets:
            raise PackError(f"Лабораторная {local_id}: изображение «{image}» отсутствует в assets.")

    return {
        "id": local_id,
        "local_id": local_id,
        "pack_id": pack_id,
        "module_id": module_id,
        "position": position,
        "title": title,
        "description": description,
        "goal": goal,
        "theory": theory,
        "steps": steps,
        "commands": commands,
        "expected": expected,
        "criteria": criteria,
        "hints": hints,
        "prerequisites": prerequisites,
        "explanation": explanation,
        "manual_check": True,
        "assets": image_names,
    }


# ----------------------------------------------------------------------
# Изображения
# ----------------------------------------------------------------------

def _image_info(data: bytes, filename: str) -> tuple[str, int, int]:
    if len(data) > MAX_ASSET_BYTES:
        raise PackError(f"Изображение «{filename}» больше 2 МБ.")
    extension = filename.rsplit(".", 1)[-1].lower()

    if extension == "png":
        if not data.startswith(PNG_SIGNATURE):
            raise PackError(f"Файл «{filename}» не похож на PNG.")
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise PackError(f"Повреждённый PNG «{filename}».")
        width, height = struct.unpack(">II", data[16:24])
        media_type = "image/png"
    elif extension in ("jpg", "jpeg"):
        if not data.startswith(b"\xff\xd8"):
            raise PackError(f"Файл «{filename}» не похож на JPEG.")
        width = height = None
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            while index < len(data) and data[index] == 0xFF:
                index += 1
            if index >= len(data):
                break
            marker = data[index]
            index += 1
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(data):
                break
            segment_size = struct.unpack(">H", data[index:index + 2])[0]
            if segment_size < 2 or index + segment_size > len(data):
                break
            if marker in JPEG_SOF and segment_size >= 7:
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                break
            index += segment_size
        if not width or not height:
            raise PackError(f"Не удалось определить размер JPEG «{filename}».")
        media_type = "image/jpeg"
    else:
        raise PackError(
            f"Формат изображения «{filename}» не поддерживается. "
            "Разрешены PNG и JPEG."
        )

    if width < 1 or height < 1:
        raise PackError(f"Некорректный размер изображения «{filename}».")
    if width > MAX_ASSET_SIDE or height > MAX_ASSET_SIDE:
        raise PackError(
            f"Изображение «{filename}» больше {MAX_ASSET_SIDE}px по стороне."
        )
    if width * height > MAX_ASSET_PIXELS:
        raise PackError(f"Изображение «{filename}» содержит слишком много пикселей.")
    return media_type, width, height


# ----------------------------------------------------------------------
# ZIP и JSON
# ----------------------------------------------------------------------

def _safe_member(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or ":" in name:
        raise PackError(f"Недопустимый путь в архиве: «{name}».")
    if CONTROL_RE.search(name):
        raise PackError("В архиве есть имя файла с недопустимыми символами.")
    if name == "assets/":
        return True
    path = PurePosixPath(name)
    parts = path.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise PackError(f"Недопустимый путь в архиве: «{name}».")
    if len(parts) == 1:
        if name not in ("manifest.json", "questions.json", "labs.json"):
            raise PackError(f"Лишний файл в корне архива: «{name}».")
    elif parts[0] == "assets" and len(parts) == 2:
        filename = parts[1]
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$", filename):
            raise PackError(f"Недопустимое имя изображения: «{name}».")
        if filename.rsplit(".", 1)[-1].lower() not in ("png", "jpg", "jpeg"):
            raise PackError(f"Недопустимый тип файла в assets: «{name}».")
    else:
        raise PackError(f"Неизвестный путь в архиве: «{name}».")
    return True


def _json_member(files: dict[str, bytes], name: str):
    raw = files.get(name)
    if raw is None:
        raise PackError(f"В архиве отсутствует {name}.")
    if len(raw) > MAX_JSON_BYTES:
        raise PackError(f"{name} слишком большой.")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as error:
        raise PackError(f"{name} содержит некорректный JSON.") from error


def parse_pack_bytes(raw: bytes) -> dict:
    """Проверить архив полностью и вернуть нормализованное содержимое."""
    if not isinstance(raw, (bytes, bytearray)):
        raise PackError("Файл пакета не прочитан.")
    raw = bytes(raw)
    if not raw:
        raise PackError("Файл пакета пуст.")
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise PackError("Архив больше 5 МБ.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as error:
        raise PackError("Файл не является корректным ZIP-архивом.") from error

    files: dict[str, bytes] = {}
    try:
        infos = archive.infolist()
        if len(infos) > MAX_FILES:
            raise PackError(f"В архиве слишком много файлов (максимум {MAX_FILES}).")
        total_size = 0
        seen = set()
        for info in infos:
            name = info.filename
            _safe_member(name)
            if info.flag_bits & 0x1:
                raise PackError("Зашифрованные записи в архиве не поддерживаются.")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackError("Символические ссылки в архиве запрещены.")
            if info.is_dir():
                continue
            if name in seen:
                raise PackError(f"Дубликат файла в архиве: «{name}».")
            seen.add(name)
            if info.file_size > MAX_UNCOMPRESSED_BYTES:
                raise PackError(f"Файл «{name}» слишком большой после распаковки.")
            total_size += info.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise PackError("Суммарный размер распакованных данных больше 20 МБ.")
            with archive.open(info) as stream:
                data = stream.read(MAX_ASSET_BYTES + 1) if name.startswith("assets/") else stream.read(MAX_JSON_BYTES + 1)
            if len(data) > (MAX_ASSET_BYTES if name.startswith("assets/") else MAX_JSON_BYTES):
                raise PackError(f"Файл «{name}» превышает допустимый размер.")
            files[name] = data
    except PackError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, zlib.error) as error:
        raise PackError("Не удалось безопасно прочитать ZIP-архив.") from error
    finally:
        archive.close()

    for required in ("manifest.json", "questions.json", "labs.json"):
        if required not in files:
            raise PackError(f"В архиве отсутствует обязательный файл {required}.")

    manifest = _validate_manifest(_json_member(files, "manifest.json"))
    pack_id = manifest["id"]
    module_id = 1000  # реальный ID назначается при установке

    assets = {}
    for name, data in files.items():
        if not name.startswith("assets/"):
            continue
        media_type, width, height = _image_info(data, name)
        assets[name] = {
            "filename": name,
            "data": data,
            "media_type": media_type,
            "size": len(data),
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    raw_questions = _json_member(files, "questions.json")
    if isinstance(raw_questions, dict):
        raw_questions = raw_questions.get("questions")
    if not isinstance(raw_questions, list):
        raise PackError("questions.json должен содержать массив вопросов.")
    if not 1 <= len(raw_questions) <= MAX_QUESTIONS:
        raise PackError(f"В пакете должно быть от 1 до {MAX_QUESTIONS} заданий.")

    questions = []
    seen_question_ids = set()
    for index, item in enumerate(raw_questions):
        question = _clean_question(item, pack_id, module_id, index + 1, set(assets))
        if question["local_id"] in seen_question_ids:
            raise PackError(f"Повторяется ID вопроса: {question['local_id']}.")
        seen_question_ids.add(question["local_id"])
        questions.append(question)
    questions.sort(key=lambda question: (question["position"], question["local_id"]))
    for index, question in enumerate(questions, start=1):
        question["position"] = index

    raw_labs = _json_member(files, "labs.json")
    if isinstance(raw_labs, dict):
        raw_labs = raw_labs.get("labs")
    if not isinstance(raw_labs, list):
        raise PackError("labs.json должен содержать массив лабораторных работ.")
    if len(raw_labs) > MAX_LABS:
        raise PackError(f"В пакете слишком много лабораторных работ (максимум {MAX_LABS}).")

    labs = []
    seen_lab_ids = set()
    for index, item in enumerate(raw_labs):
        lab = _clean_lab(item, pack_id, module_id, index + 1, set(assets))
        if lab["local_id"] in seen_lab_ids:
            raise PackError(f"Повторяется ID лабораторной работы: {lab['local_id']}.")
        seen_lab_ids.add(lab["local_id"])
        labs.append(lab)
    labs.sort(key=lambda lab: (lab["position"], lab["local_id"]))
    for index, lab in enumerate(labs, start=1):
        lab["position"] = index

    return {
        "manifest": manifest,
        "questions": questions,
        "labs": labs,
        "assets": assets,
        "package_size": len(raw),
    }


# ----------------------------------------------------------------------
# Хранение в SQLite
# ----------------------------------------------------------------------

def _module_row(row) -> dict:
    return dict(row) if row is not None else None


def get_custom_module(db, pack_id: str, include_removed=False):
    query = "SELECT * FROM custom_modules WHERE pack_id = ?"
    params = [pack_id]
    if not include_removed:
        query += " AND removed_at IS NULL"
    with db.connect() as connection:
        row = connection.execute(query, params).fetchone()
    return _module_row(row)


def list_custom_modules(db, include_removed=False) -> list[dict]:
    query = "SELECT * FROM custom_modules"
    if not include_removed:
        query += " WHERE removed_at IS NULL"
    query += " ORDER BY title COLLATE NOCASE, pack_id"
    with db.connect() as connection:
        rows = [dict(row) for row in connection.execute(query).fetchall()]
        for row in rows:
            row["question_count"] = int(connection.execute(
                "SELECT COUNT(*) AS n FROM custom_questions WHERE pack_id = ? AND active = 1",
                (row["pack_id"],),
            ).fetchone()["n"])
            row["lab_count"] = int(connection.execute(
                "SELECT COUNT(*) AS n FROM custom_labs WHERE pack_id = ? AND active = 1",
                (row["pack_id"],),
            ).fetchone()["n"])
    return rows


def get_custom_questions(db, pack_id: str, active_only=True) -> list[dict]:
    query = "SELECT data_json FROM custom_questions WHERE pack_id = ?"
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY position, local_id"
    with db.connect() as connection:
        rows = connection.execute(query, (pack_id,)).fetchall()
    result = []
    for row in rows:
        try:
            result.append(json.loads(row["data_json"]))
        except (TypeError, ValueError):
            continue
    return result


def get_custom_question(db, question_id: str, active_only=False):
    query = "SELECT data_json, active FROM custom_questions WHERE question_id = ?"
    with db.connect() as connection:
        row = connection.execute(query, (question_id,)).fetchone()
    if row is None:
        return None
    if active_only and not row["active"]:
        return None
    try:
        return json.loads(row["data_json"])
    except (TypeError, ValueError):
        return None


def get_custom_labs(db, pack_id: str, active_only=True) -> list[dict]:
    query = "SELECT data_json FROM custom_labs WHERE pack_id = ?"
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY position, local_id"
    with db.connect() as connection:
        rows = connection.execute(query, (pack_id,)).fetchall()
    result = []
    for row in rows:
        try:
            result.append(json.loads(row["data_json"]))
        except (TypeError, ValueError):
            continue
    return result


def get_custom_asset(db, pack_id: str, filename: str):
    with db.connect() as connection:
        row = connection.execute(
            """SELECT filename, media_type, data FROM custom_assets
               WHERE pack_id = ? AND filename = ? AND active = 1""",
            (pack_id, filename),
        ).fetchone()
    return dict(row) if row else None


def module_progress(db, module: dict) -> dict:
    questions = get_custom_questions(db, module["pack_id"])
    status = db.question_status()
    attempted = sum(1 for q in questions if status.get(q["id"], {}).get("attempts", 0))
    correct = sum(1 for q in questions if status.get(q["id"], {}).get("ever_correct"))
    total = len(questions)
    return {
        "total": total,
        "attempted": attempted,
        "correct": correct,
        "percent": round(correct * 100 / total) if total else 0,
    }


def install_pack(db, pack: dict, package_size: int, allow_downgrade=False) -> dict:
    """Установить или обновить пакет одной транзакцией."""
    manifest = pack["manifest"]
    pack_id = manifest["id"]
    if pack_id in RESERVED_IDS:
        raise PackError("Нельзя перезаписать системный модуль.")

    now = now_text()
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing_row = connection.execute(
            "SELECT * FROM custom_modules WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        existing = dict(existing_row) if existing_row else None

        status = "installed"
        if existing:
            comparison = compare_versions(
                manifest["module_version"], existing["module_version"]
            )
            if comparison == 0 and existing["removed_at"] is None:
                return {"status": "same", "module_id": existing["module_id"]}
            if comparison < 0 and not allow_downgrade:
                raise PackError(
                    f"Установлена более новая версия {existing['module_version']}. "
                    "Установка старой версии требует отдельного подтверждения."
                )
            module_id = int(existing["module_id"])
            status = "updated" if comparison > 0 else (
                "reinstalled" if existing["removed_at"] else "downgraded"
            )
        else:
            row = connection.execute(
                "SELECT COALESCE(MAX(module_id), 999) + 1 AS next_id FROM custom_modules"
            ).fetchone()
            module_id = max(1000, int(row["next_id"]))

        manifest_json = json.dumps(manifest, ensure_ascii=False)
        connection.execute(
            """INSERT INTO custom_modules
               (pack_id, module_id, title, description, author, module_version,
                language, difficulty, category, created_at, min_app_version,
                manifest_json, package_size, installed_at, updated_at, removed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
               ON CONFLICT(pack_id) DO UPDATE SET
                   title = excluded.title,
                   description = excluded.description,
                   author = excluded.author,
                   module_version = excluded.module_version,
                   language = excluded.language,
                   difficulty = excluded.difficulty,
                   category = excluded.category,
                   created_at = excluded.created_at,
                   min_app_version = excluded.min_app_version,
                   manifest_json = excluded.manifest_json,
                   package_size = excluded.package_size,
                   updated_at = excluded.updated_at,
                   removed_at = NULL""",
            (
                pack_id, module_id, manifest["title"], manifest["description"],
                manifest["author"], manifest["module_version"], manifest["language"],
                manifest["difficulty"], manifest["category"], manifest["created_at"],
                manifest["min_app_version"], manifest_json, package_size, now, now,
            ),
        )

        existing_questions = {
            row["local_id"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM custom_questions WHERE pack_id = ?", (pack_id,)
            ).fetchall()
        }
        new_question_locals = set()
        for question in pack["questions"]:
            local_id = question["local_id"]
            new_question_locals.add(local_id)
            question["module"] = module_id
            question["id"] = f"npt:{pack_id}:{local_id}"
            data_json = json.dumps(question, ensure_ascii=False)
            old = existing_questions.get(local_id)
            if old and old["data_json"] != data_json:
                connection.execute(
                    """INSERT INTO custom_question_archive
                       (pack_id, question_id, local_id, source_version,
                        data_json, archived_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (pack_id, question["id"], local_id,
                     existing["module_version"] if existing else "new",
                     old["data_json"], now),
                )
            connection.execute(
                """INSERT INTO custom_questions
                   (question_id, pack_id, module_id, local_id, position,
                    data_json, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(question_id) DO UPDATE SET
                       module_id = excluded.module_id,
                       position = excluded.position,
                       data_json = excluded.data_json,
                       active = 1,
                       updated_at = excluded.updated_at""",
                (question["id"], pack_id, module_id, local_id,
                 question["position"], data_json, now),
            )
        for local_id, old in existing_questions.items():
            if local_id not in new_question_locals:
                connection.execute(
                    """INSERT INTO custom_question_archive
                       (pack_id, question_id, local_id, source_version,
                        data_json, archived_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (pack_id, old["question_id"], local_id,
                     existing["module_version"] if existing else "new",
                     old["data_json"], now),
                )
                connection.execute(
                    "UPDATE custom_questions SET active = 0, updated_at = ? WHERE question_id = ?",
                    (now, old["question_id"]),
                )

        existing_labs = {
            row["local_id"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM custom_labs WHERE pack_id = ?", (pack_id,)
            ).fetchall()
        }
        new_lab_locals = set()
        for lab in pack["labs"]:
            local_id = lab["local_id"]
            new_lab_locals.add(local_id)
            lab["module_id"] = module_id
            connection.execute(
                """INSERT INTO custom_labs
                   (pack_id, local_id, module_id, position, data_json, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(pack_id, local_id) DO UPDATE SET
                       module_id = excluded.module_id,
                       position = excluded.position,
                       data_json = excluded.data_json,
                       active = 1,
                       updated_at = excluded.updated_at""",
                (pack_id, local_id, module_id, lab["position"],
                 json.dumps(lab, ensure_ascii=False), now),
            )
        for local_id, old in existing_labs.items():
            if local_id not in new_lab_locals:
                connection.execute(
                    """UPDATE custom_labs SET active = 0, updated_at = ?
                       WHERE pack_id = ? AND local_id = ?""",
                    (now, pack_id, local_id),
                )

        existing_assets = {
            row["filename"]: dict(row)
            for row in connection.execute(
                "SELECT filename FROM custom_assets WHERE pack_id = ?", (pack_id,)
            ).fetchall()
        }
        for filename, asset in pack["assets"].items():
            connection.execute(
                """INSERT INTO custom_assets
                   (pack_id, filename, media_type, size, width, height,
                    sha256, data, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(pack_id, filename) DO UPDATE SET
                       media_type = excluded.media_type,
                       size = excluded.size,
                       width = excluded.width,
                       height = excluded.height,
                       sha256 = excluded.sha256,
                       data = excluded.data,
                       active = 1,
                       updated_at = excluded.updated_at""",
                (pack_id, filename, asset["media_type"], asset["size"],
                 asset["width"], asset["height"], asset["sha256"],
                 asset["data"], now),
            )
        for filename in existing_assets:
            if filename not in pack["assets"]:
                connection.execute(
                    """UPDATE custom_assets SET active = 0, updated_at = ?
                       WHERE pack_id = ? AND filename = ?""",
                    (now, pack_id, filename),
                )

        return {
            "status": status,
            "module_id": module_id,
            "questions": len(pack["questions"]),
            "labs": len(pack["labs"]),
            "assets": len(pack["assets"]),
        }


def remove_custom_pack(db, pack_id: str) -> dict:
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM custom_modules WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        if row is None:
            raise PackError("Пользовательский модуль не найден.")
        now = now_text()
        connection.execute(
            "UPDATE custom_modules SET removed_at = ?, updated_at = ? WHERE pack_id = ?",
            (now, now, pack_id),
        )
        connection.execute(
            "UPDATE custom_questions SET active = 0, updated_at = ? WHERE pack_id = ?",
            (now, pack_id),
        )
        connection.execute(
            "UPDATE custom_labs SET active = 0, updated_at = ? WHERE pack_id = ?",
            (now, pack_id),
        )
        connection.execute(
            "UPDATE custom_assets SET active = 0, updated_at = ? WHERE pack_id = ?",
            (now, pack_id),
        )
        return {"module_id": int(row["module_id"]), "title": row["title"]}


# ----------------------------------------------------------------------
# Экспорт
# ----------------------------------------------------------------------

def _export_manifest(module: dict) -> dict:
    try:
        manifest = json.loads(module["manifest_json"])
    except (TypeError, ValueError):
        manifest = {}
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "id": module["pack_id"],
        "title": module["title"],
        "description": module["description"],
        "author": module["author"],
        "module_version": module["module_version"],
        "language": module["language"],
        "difficulty": module["difficulty"],
        "category": module["category"],
        "created_at": module["created_at"],
        "min_app_version": module["min_app_version"],
    }


def _export_question(question: dict) -> dict:
    result = {
        "id": question["local_id"],
        "topic": question["topic"],
        "type": question["type"],
        "prompt": question["prompt"],
        "difficulty": question["difficulty"],
        "xp": question.get("xp", 10),
        "explanation": question["explanation"],
        "sample": question["sample"],
        "hints": question.get("hints", []),
        "position": question.get("position", 1),
    }
    for key in ("answer_kind", "answers", "options", "correct", "fields",
                "keywords", "min_points", "source", "image"):
        if key in question:
            result[key] = question[key]
    return result


def _export_lab(lab: dict) -> dict:
    result = {
        "id": lab["local_id"],
        "title": lab["title"],
        "description": lab["description"],
        "goal": lab["goal"],
        "theory": lab["theory"],
        "steps": lab["steps"],
        "commands": lab["commands"],
        "expected": lab["expected"],
        "criteria": lab["criteria"],
        "hints": lab["hints"],
        "prerequisites": lab["prerequisites"],
        "explanation": lab["explanation"],
        "manual_check": True,
        "assets": lab["assets"],
        "position": lab.get("position", 1),
    }
    return result


def build_zip(manifest: dict, questions: list[dict], labs: list[dict],
              assets: dict[str, dict]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        archive.writestr(
            "questions.json",
            json.dumps(questions, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        archive.writestr(
            "labs.json",
            json.dumps(labs, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        for filename, asset in assets.items():
            data = asset["data"] if isinstance(asset, dict) else asset
            archive.writestr(filename, data)
    return buffer.getvalue()


def export_pack(db, pack_id: str) -> bytes:
    module = get_custom_module(db, pack_id)
    if module is None:
        raise PackError("Модуль не найден или удалён.")
    questions = [_export_question(q) for q in get_custom_questions(db, pack_id)]
    labs = [_export_lab(lab) for lab in get_custom_labs(db, pack_id)]
    with db.connect() as connection:
        asset_rows = connection.execute(
            """SELECT filename, data FROM custom_assets
               WHERE pack_id = ? AND active = 1 ORDER BY filename""",
            (pack_id,),
        ).fetchall()
    assets = {row["filename"]: bytes(row["data"]) for row in asset_rows}
    raw = build_zip(_export_manifest(module), questions, labs, assets)
    parse_pack_bytes(raw)  # экспорт обязан проходить ту же проверку
    return raw
