import base64
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

import packs
from app import create_app
from content import get_question
from grading import expected_answer, grade_answer
from packs import (
    MAX_ARCHIVE_BYTES,
    MAX_UNCOMPRESSED_BYTES,
    PackError,
    parse_pack_bytes,
)

PNG_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture
def app(tmp_path):
    application = create_app(
        db_path=tmp_path / "packs_test.db", secret_key="test-secret"
    )
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def manifest(pack_id="test-pack", version="1.0.0", **overrides):
    value = {
        "format": "nptpack",
        "format_version": 1,
        "id": pack_id,
        "title": "Тестовый модуль",
        "description": "Короткое описание тестового модуля.",
        "author": "Тестовый автор",
        "module_version": version,
        "language": "ru",
        "difficulty": "beginner",
        "category": "networking",
        "created_at": "2026-10-31",
        "min_app_version": "1.0.0",
    }
    value.update(overrides)
    return value


def question(qid="q1", prompt="Введите IP-адрес 192.168.1.1.", **overrides):
    value = {
        "id": qid,
        "topic": "IPv4",
        "type": "input",
        "prompt": prompt,
        "difficulty": 1,
        "xp": 10,
        "explanation": "Это адрес узла в тестовой сети.",
        "sample": "192.168.1.1",
        "answer_kind": "ip",
        "answers": ["192.168.1.1"],
        "hints": ["Четыре октета."],
    }
    value.update(overrides)
    return value


def lab(lab_id="lab1", assets=None):
    return {
        "id": lab_id,
        "title": "Лабораторная работа",
        "description": "Описание лабораторной работы.",
        "goal": "Проверить адресацию.",
        "theory": "Краткая теория.",
        "steps": ["Проверить адрес."],
        "commands": ["ipconfig"],
        "expected": ["Адрес корректен."],
        "criteria": ["Указан адрес и маска."],
        "hints": ["Смотрите ipconfig."],
        "prerequisites": ["Компьютер с сетевой картой."],
        "explanation": "Итоговое объяснение.",
        "manual_check": True,
        "assets": assets or [],
    }


def pack_bytes(pack_id="test-pack", version="1.0.0", questions=None, labs=None,
               assets=None, manifest_overrides=None):
    return packs.build_zip(
        manifest(pack_id, version, **(manifest_overrides or {})),
        questions if questions is not None else [question()],
        labs if labs is not None else [lab()],
        assets or {},
    )


def raw_zip(files, compression=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def preview(client, raw, filename="test.nptpack", follow=True):
    return client.post(
        "/library/import/preview",
        data={"file": (io.BytesIO(raw), filename)},
        content_type="multipart/form-data",
        follow_redirects=follow,
    )


def token_from(response):
    match = re.search(rb'name="token" value="([^"]+)"', response.data)
    assert match, response.get_data(as_text=True)[:1000]
    return match.group(1).decode()


def module_count(app):
    with app.config["DB"].connect() as connection:
        return connection.execute("SELECT COUNT(*) AS n FROM custom_modules").fetchone()["n"]


def attempt_count(app):
    with app.config["DB"].connect() as connection:
        return connection.execute("SELECT COUNT(*) AS n FROM attempts").fetchone()["n"]


def test_valid_pack_preview_import_and_practice(client, app):
    raw = pack_bytes(
        questions=[question()],
        labs=[lab(assets=["assets/pixel.png"])],
        assets={"assets/pixel.png": {"data": PNG_PIXEL}},
    )
    response = preview(client, raw)
    assert response.status_code == 200
    assert "Тестовый модуль" in response.get_data(as_text=True)
    assert "База данных ещё не изменена" in response.get_data(as_text=True)
    assert module_count(app) == 0

    token = token_from(response)
    confirm = client.post("/library/import/confirm", data={"token": token})
    assert confirm.status_code == 302
    assert confirm.headers["Location"].endswith("/library/test-pack")
    assert module_count(app) == 1

    library = client.get("/library")
    assert "Тестовый модуль" in library.get_data(as_text=True)

    detail = client.get("/library/test-pack")
    text = detail.get_data(as_text=True)
    assert "Лабораторная работа" in text
    assert "assets/pixel.png" in text

    asset = client.get("/library/assets/test-pack/assets/pixel.png")
    assert asset.status_code == 200
    assert asset.mimetype == "image/png"

    start = client.post("/library/test-pack/start")
    assert start.status_code == 302
    lesson = client.get(start.headers["Location"])
    assert lesson.status_code == 200
    assert "Задание 1 из 1" in lesson.get_data(as_text=True)

    exported = client.get("/library/test-pack/export")
    assert exported.status_code == 200
    assert parse_pack_bytes(exported.data)["manifest"]["id"] == "test-pack"


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"this is not a zip archive", "ZIP"),
        (pack_bytes(manifest_overrides={"format_version": 2}), "формата"),
        (pack_bytes(manifest_overrides={"title": ""}), "title"),
        (pack_bytes(questions=[question(difficulty="beginner")]), "целым числом"),
        (pack_bytes(questions=[question(answers="192.168.1.1")]), "массивом"),
    ],
)
def test_invalid_pack_is_rejected_without_db_changes(client, app, raw, message):
    response = preview(client, raw)
    assert response.status_code == 200
    assert message in response.get_data(as_text=True)
    assert module_count(app) == 0


def test_missing_manifest_is_rejected(client, app):
    raw = raw_zip({
        "questions.json": json.dumps([question()]),
        "labs.json": "[]",
    })
    response = preview(client, raw)
    assert response.status_code == 200
    assert "manifest.json" in response.get_data(as_text=True)
    assert module_count(app) == 0


def test_zip_slip_and_executables_are_rejected(client, app):
    valid = pack_bytes()
    with zipfile.ZipFile(io.BytesIO(valid)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    files["../evil.txt"] = b"evil"
    slip = raw_zip(files)
    response = preview(client, slip)
    assert response.status_code == 200
    assert "Недопустимый путь" in response.get_data(as_text=True)
    assert module_count(app) == 0

    files.pop("../evil.txt")
    files["payload.py"] = b"print('no')"
    executable = raw_zip(files)
    response = preview(client, executable)
    assert response.status_code == 200
    assert "Лишний файл" in response.get_data(as_text=True)
    assert module_count(app) == 0


def test_oversized_archive_is_rejected(client, app):
    response = preview(client, b"x" * (MAX_ARCHIVE_BYTES + 1))
    assert response.status_code == 200
    assert "больше 5 МБ" in response.get_data(as_text=True)
    assert module_count(app) == 0


def test_zip_bomb_expansion_is_rejected(client, app):
    files = {
        "manifest.json": json.dumps(manifest()),
        "questions.json": json.dumps([question()]),
        "labs.json": "[]",
        "assets/bomb.png": b"\0" * (MAX_UNCOMPRESSED_BYTES + 1),
    }
    raw = raw_zip(files, compression=zipfile.ZIP_DEFLATED)
    assert len(raw) < MAX_ARCHIVE_BYTES
    response = preview(client, raw)
    assert response.status_code == 200
    assert "слишком большой" in response.get_data(as_text=True)
    assert module_count(app) == 0


def test_invalid_image_is_rejected(client, app):
    raw = pack_bytes(assets={"assets/bad.png": {"data": b"not a png"}})
    response = preview(client, raw)
    assert response.status_code == 200
    assert "PNG" in response.get_data(as_text=True)
    assert module_count(app) == 0


def test_reserved_system_id_is_rejected(client, app):
    raw = pack_bytes("system")
    response = preview(client, raw)
    assert response.status_code == 200
    assert "зарезервирован" in response.get_data(as_text=True)
    assert module_count(app) == 0


def test_same_version_is_not_installed_twice(client, app):
    raw = pack_bytes()
    first = preview(client, raw)
    client.post("/library/import/confirm", data={"token": token_from(first)})
    assert module_count(app) == 1

    again = preview(client, raw)
    text = again.get_data(as_text=True)
    assert "уже установлена" in text
    assert "Устанавливать нечего" in text
    assert module_count(app) == 1


def test_update_preserves_progress_and_archives_changed_question(client, app):
    old = pack_bytes(
        version="1.0.0",
        questions=[question("q1"), question("q2", prompt="Старый вопрос")],
    )
    first = preview(client, old)
    client.post("/library/import/confirm", data={"token": token_from(first)})

    db = app.config["DB"]
    qid = "npt:test-pack:q1"
    custom = packs.get_custom_question(db, qid)
    answer = expected_answer(custom)
    result = grade_answer(custom, answer)
    session_id = db.create_session("practice", "pack:test-pack", [qid])
    db.record_attempt(
        session_id, custom, answer, result, "practice", "2026-10-31", custom["xp"]
    )
    attempts_before = attempt_count(app)
    xp_before = db.total_xp()
    assert attempts_before == 1
    assert xp_before > 0

    newer = pack_bytes(
        version="1.1.0",
        questions=[question("q1", prompt="Новый вопрос"), question("q3")],
    )
    response = preview(client, newer)
    assert response.status_code == 200
    assert "Доступно обновление" in response.get_data(as_text=True)
    token = token_from(response)
    confirm = client.post("/library/import/confirm", data={"token": token})
    assert confirm.status_code == 302

    assert attempt_count(app) == attempts_before
    assert db.total_xp() == xp_before
    assert packs.get_custom_module(db, "test-pack")["module_version"] == "1.1.0"
    assert packs.get_custom_question(db, qid)["prompt"] == "Новый вопрос"
    assert packs.get_custom_question(db, "npt:test-pack:q2") is not None
    with db.connect() as connection:
        old = connection.execute(
            "SELECT active FROM custom_questions WHERE question_id = ?",
            ("npt:test-pack:q2",),
        ).fetchone()
        archived = connection.execute(
            "SELECT COUNT(*) AS n FROM custom_question_archive WHERE question_id = ?",
            (qid,),
        ).fetchone()["n"]
    assert old["active"] == 0
    assert archived >= 1


def test_older_version_requires_explicit_confirmation(client, app):
    newer = pack_bytes(version="2.0.0")
    first = preview(client, newer)
    client.post("/library/import/confirm", data={"token": token_from(first)})

    old_raw = pack_bytes(version="1.0.0")
    old = preview(client, old_raw)
    assert "Пакет старше установленного" in old.get_data(as_text=True)
    token = token_from(old)
    response = client.post("/library/import/confirm", data={"token": token})
    assert response.status_code == 302
    assert packs.get_custom_module(app.config["DB"], "test-pack")["module_version"] == "2.0.0"

    old = preview(client, old_raw)
    token = token_from(old)
    response = client.post(
        "/library/import/confirm",
        data={"token": token, "allow_downgrade": "yes"},
    )
    assert response.status_code == 302
    assert packs.get_custom_module(app.config["DB"], "test-pack")["module_version"] == "1.0.0"


def test_delete_archives_module_and_preserves_history(client, app):
    raw = pack_bytes()
    first = preview(client, raw)
    client.post("/library/import/confirm", data={"token": token_from(first)})

    db = app.config["DB"]
    qid = "npt:test-pack:q1"
    custom = packs.get_custom_question(db, qid)
    answer = expected_answer(custom)
    result = grade_answer(custom, answer)
    session_id = db.create_session("practice", "pack:test-pack", [qid])
    db.record_attempt(
        session_id, custom, answer, result, "practice", "2026-10-31", custom["xp"]
    )
    attempts_before = attempt_count(app)

    assert client.get("/library/test-pack/delete").status_code == 200
    assert client.post("/library/test-pack/delete").status_code == 302
    assert "test-pack" in [m["pack_id"] for m in packs.list_custom_modules(db)]

    response = client.post("/library/test-pack/delete", data={"confirm": "yes"})
    assert response.status_code == 302
    assert packs.list_custom_modules(db) == []
    assert attempt_count(app) == attempts_before
    assert packs.get_custom_question(db, qid) is not None
    with db.connect() as connection:
        active = connection.execute(
            "SELECT active FROM custom_questions WHERE question_id = ?", (qid,)
        ).fetchone()["active"]
    assert active == 0
    library_text = client.get("/library").get_data(as_text=True)
    assert "/library/test-pack" not in library_text
    assert "Пользовательских модулей пока нет" in library_text


def test_delete_hides_archived_review_rows_but_keeps_attempts(client, app):
    raw = pack_bytes()
    first = preview(client, raw)
    client.post("/library/import/confirm", data={"token": token_from(first)})
    db = app.config["DB"]
    qid = "npt:test-pack:q1"
    custom = packs.get_custom_question(db, qid)
    answer = {"value": "10.0.0.1"}
    result = grade_answer(custom, answer)
    session_id = db.create_session("practice", "pack:test-pack", [qid])
    db.record_attempt(
        session_id, custom, answer, result, "practice", "2026-10-31", custom["xp"]
    )
    assert db.review_count() == 1
    attempts_before = attempt_count(app)

    client.post("/library/test-pack/delete", data={"confirm": "yes"})
    assert db.review_count() == 0
    assert attempt_count(app) == attempts_before
    review_page = client.get("/review")
    assert custom["topic"] not in review_page.get_data(as_text=True)


def test_system_modules_cannot_be_deleted_or_overwritten(client, app):
    assert client.get("/library/1/delete").status_code == 404
    library = client.get("/library").get_data(as_text=True)
    assert "Основы сетей" in library
    assert "встроенный" in library
    raw = pack_bytes("system")
    response = preview(client, raw)
    assert "зарезервирован" in response.get_data(as_text=True)
    assert module_count(app) == 0


def test_custom_lesson_and_review_use_existing_engine(client, app):
    raw = pack_bytes()
    first = preview(client, raw)
    client.post("/library/import/confirm", data={"token": token_from(first)})

    start = client.post("/library/test-pack/start")
    session_id = int(re.search(r"/lesson/(\d+)", start.headers["Location"]).group(1))
    db = app.config["DB"]
    session = db.get_session(session_id)
    qid = session["question_ids"][0]
    custom = packs.get_custom_question(db, qid)

    answer = client.post(
        f"/lesson/{session_id}/answer",
        data={"question_id": qid, "value": "10.0.0.1"},
    )
    assert answer.status_code == 302
    feedback = client.get(answer.headers["Location"])
    assert feedback.status_code == 200
    assert "Пока неверно" in feedback.get_data(as_text=True)
    assert custom["topic"] in feedback.get_data(as_text=True)

    review = client.get("/review")
    assert review.status_code == 200
    assert custom["topic"] in review.get_data(as_text=True)

    review_start = client.post("/review/start")
    assert review_start.status_code == 302
    review_session_id = int(
        re.search(r"/lesson/(\d+)", review_start.headers["Location"]).group(1)
    )
    assert db.get_session(review_session_id)["question_ids"] == [qid]


def test_reinstall_after_delete_restores_module_and_history(client, app):
    raw = pack_bytes()
    first = preview(client, raw)
    client.post("/library/import/confirm", data={"token": token_from(first)})
    db = app.config["DB"]
    qid = "npt:test-pack:q1"
    custom = packs.get_custom_question(db, qid)
    answer = expected_answer(custom)
    result = grade_answer(custom, answer)
    session_id = db.create_session("practice", "pack:test-pack", [qid])
    db.record_attempt(
        session_id, custom, answer, result, "practice", "2026-10-31", custom["xp"]
    )
    attempts_before = attempt_count(app)
    client.post("/library/test-pack/delete", data={"confirm": "yes"})

    response = preview(client, raw)
    assert "Модуль был удалён" in response.get_data(as_text=True)
    client.post("/library/import/confirm", data={"token": token_from(response)})
    assert packs.get_custom_module(db, "test-pack") is not None
    assert attempt_count(app) == attempts_before
    with db.connect() as connection:
        active = connection.execute(
            "SELECT active FROM custom_questions WHERE question_id = ?", (qid,)
        ).fetchone()["active"]
    assert active == 1


def test_export_round_trip(client, app, tmp_path):
    raw = pack_bytes(
        questions=[question(), question("q2")],
        labs=[lab(lab_id="lab1")],
    )
    first = preview(client, raw)
    client.post("/library/import/confirm", data={"token": token_from(first)})
    db = app.config["DB"]

    exported = packs.export_pack(db, "test-pack")
    parsed = parse_pack_bytes(exported)
    assert parsed["manifest"]["id"] == "test-pack"
    assert len(parsed["questions"]) == 2
    assert len(parsed["labs"]) == 1

    second_app = create_app(
        db_path=tmp_path / "roundtrip.db", secret_key="test-secret-2"
    )
    second_db = second_app.config["DB"]
    result = packs.install_pack(second_db, parsed, len(exported))
    assert result["status"] == "installed"
    assert packs.get_custom_module(second_db, "test-pack") is not None


def test_update_rolls_back_on_mid_transaction_error(client, app, monkeypatch):
    raw = pack_bytes(version="1.0.0")
    first = preview(client, raw)
    client.post("/library/import/confirm", data={"token": token_from(first)})
    db = app.config["DB"]
    qid = "npt:test-pack:q1"
    before = packs.get_custom_question(db, qid)

    newer = parse_pack_bytes(
        pack_bytes(version="1.1.0", questions=[question(prompt="Новая формулировка")])
    )
    real_dumps = packs.json.dumps
    calls = {"count": 0}

    def fail_on_question(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("simulated database write failure")
        return real_dumps(*args, **kwargs)

    monkeypatch.setattr(packs.json, "dumps", fail_on_question)
    with pytest.raises(RuntimeError):
        packs.install_pack(db, newer, 100)

    assert packs.get_custom_module(db, "test-pack")["module_version"] == "1.0.0"
    assert packs.get_custom_question(db, qid)["prompt"] == before["prompt"]


def test_demo_pack_is_valid_and_complete():
    raw = Path("demo_packs/ipv4-basics.nptpack").read_bytes()
    pack = parse_pack_bytes(raw)
    assert pack["manifest"]["id"] == "ipv4-basics"
    assert len(pack["questions"]) >= 15
    assert len(pack["labs"]) >= 2
    assert len(pack["assets"]) >= 1
    assert all(q["type"] in packs.ALLOWED_TYPES for q in pack["questions"])


def test_demo_pack_imports_and_opens(client, app):
    raw = Path("demo_packs/ipv4-basics.nptpack").read_bytes()
    response = preview(client, raw, filename="ipv4-basics.nptpack")
    assert response.status_code == 200
    client.post("/library/import/confirm", data={"token": token_from(response)})
    module = packs.get_custom_module(app.config["DB"], "ipv4-basics")
    assert module is not None
    assert len(packs.get_custom_questions(app.config["DB"], "ipv4-basics")) == 15
    assert len(packs.get_custom_labs(app.config["DB"], "ipv4-basics")) == 2
    page = client.get("/library/ipv4-basics")
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert "Основы IPv4 и подсетей" in text
    assert "Ручная проверка" in text


def test_non_nptpack_extension_is_rejected(client, app):
    response = preview(client, pack_bytes(), filename="pack.txt")
    assert response.status_code == 200
    assert "расширением .nptpack" in response.get_data(as_text=True)
    assert module_count(app) == 0
