import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from app import create_app
from backup import build_backup
from content import get_question
from database import Database
from grading import expected_answer


@pytest.fixture
def app(tmp_path):
    application = create_app(
        db_path=tmp_path / "netpractice_test.db", secret_key="test-secret"
    )
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def session_id_from(response):
    match = re.search(r"/lesson/(\d+)", response.headers["Location"])
    assert match, response.headers["Location"]
    return int(match.group(1))


def submit_current(client, app, session_id, override=None):
    db = app.config["DB"]
    session = db.get_session(session_id)
    question = get_question(session["question_ids"][session["position"]])
    answer = override or expected_answer(question)
    data = {"question_id": question["id"]}
    data.update(answer)
    response = client.post(f"/lesson/{session_id}/answer", data=data)
    assert response.status_code == 302
    return question, response


def complete_session(client, app, session_id):
    db = app.config["DB"]
    for _ in range(30):
        session = db.get_session(session_id)
        if session["completed"]:
            return
        if session["pending_attempt_id"] is not None:
            response = client.post(f"/lesson/{session_id}/next")
            assert response.status_code == 302
            continue
        submit_current(client, app, session_id)
    raise AssertionError("Занятие не завершилось за 30 шагов")


def test_home_opens(client):
    response = client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "NetPractice" in text
    assert "Начать занятие" in text
    assert 'name="viewport"' in text


def test_learn_lists_modules_and_locks_advanced(client):
    response = client.get("/learn")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    for title in ("Основы сетей", "IPv4 и подсети", "Комплексные лабораторные работы"):
        assert title in text
    assert "Закрыт" in text
    plain = re.sub(r"\s+", " ", text)
    # Для модуля 2 нужно 60% заданий модуля 1: ceil(12 * 0.6) = 8.
    assert "не менее 8 заданий модуля «Основы сетей». Сейчас пройдено 0" in plain

    locked = client.get("/learn/7")
    assert locked.status_code == 200
    locked_text = re.sub(r"\s+", " ", locked.get_data(as_text=True))
    assert "Модуль пока закрыт" in locked_text
    assert "не менее 8 заданий модуля «Основы Linux и серверов». Сейчас пройдено 0" in locked_text

    start = client.post("/practice/7/start")
    assert start.status_code == 302
    assert start.headers["Location"].endswith("/learn")


def test_daily_lesson_full_flow(client, app):
    start = client.post("/daily/start")
    assert start.status_code == 302
    session_id = session_id_from(start)

    db = app.config["DB"]
    session = db.get_session(session_id)
    assert session["kind"] == "daily"
    assert session["total"] == 8
    assert len(set(session["question_ids"])) == 8

    lesson = client.get(f"/lesson/{session_id}")
    assert lesson.status_code == 200
    assert "Задание 1 из 8" in lesson.get_data(as_text=True)

    complete_session(client, app, session_id)

    done = client.get(f"/lesson/{session_id}/done")
    assert done.status_code == 200
    assert "Занятие завершено" in done.get_data(as_text=True)

    stats = db.overview(date.today())
    assert stats["answered"] == 8
    assert stats["streak"] == 1
    assert stats["max_streak"] == 1
    assert stats["xp"] > 0
    assert db.count_completed_daily(date.today().isoformat()) == 1

    home = client.get("/")
    assert "Пройти ещё одно занятие" in home.get_data(as_text=True)


def test_parallel_daily_start_creates_one_session(app):
    def start(_):
        with app.test_client() as thread_client:
            response = thread_client.post("/daily/start")
            assert response.status_code == 302
            return session_id_from(response)

    with ThreadPoolExecutor(max_workers=8) as pool:
        session_ids = list(pool.map(start, range(16)))

    assert len(set(session_ids)) == 1
    db = app.config["DB"]
    with db.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE kind = 'daily'"
        ).fetchone()["n"]
    assert count == 1


def test_lesson_resumes_after_restart(client, app, tmp_path):
    start = client.post("/daily/start")
    session_id = session_id_from(start)
    submit_current(client, app, session_id)

    reopened = Database(tmp_path / "netpractice_test.db")
    session = reopened.get_session(session_id)
    assert session["pending_attempt_id"] is not None

    feedback = client.get(f"/lesson/{session_id}")
    assert feedback.status_code == 302
    assert feedback.headers["Location"].endswith(f"/lesson/{session_id}/feedback")

    next_page = client.get(f"/lesson/{session_id}/feedback")
    assert next_page.status_code == 200
    assert "Разбор" in next_page.get_data(as_text=True)


def test_xp_not_awarded_again_for_same_question(client, app):
    start = client.post("/daily/start")
    session_id = session_id_from(start)
    complete_session(client, app, session_id)
    db = app.config["DB"]
    xp_before = db.total_xp()
    attempts = db.session_attempts(session_id)
    question_id = attempts[0]["question_id"]
    question = get_question(question_id)

    repeat_session = db.create_session("practice", "1", [question_id])
    data = {"question_id": question_id}
    data.update(expected_answer(question))
    response = client.post(f"/lesson/{repeat_session}/answer", data=data)
    assert response.status_code == 302
    client.post(f"/lesson/{repeat_session}/next")

    assert db.total_xp() == xp_before
    latest = db.session_attempts(repeat_session)[0]
    assert latest["correct"] == 1
    assert latest["xp_awarded"] == 0


def test_review_flow_removes_fixed_question(client, app):
    db = app.config["DB"]
    question = get_question("m1-03")
    session_id = db.create_session("practice", "1", [question["id"]])

    _, response = submit_current(
        client, app, session_id, override={"value": "7"}
    )
    feedback = client.get(response.headers["Location"])
    assert "Пока неверно" in feedback.get_data(as_text=True)
    client.post(f"/lesson/{session_id}/next")
    assert db.review_count() == 1

    review_page = client.get("/review")
    text = review_page.get_data(as_text=True)
    assert "MAC-адрес" in text
    assert "Начать повторение" in text

    start = client.post("/review/start")
    assert start.status_code == 302
    review_session = session_id_from(start)
    complete_session(client, app, review_session)

    assert db.review_count() == 0
    done = client.get(f"/lesson/{review_session}/done")
    assert "Занятие завершено" in done.get_data(as_text=True)


def test_self_check_for_written_answer(client, app):
    db = app.config["DB"]
    question = get_question("m1-11")
    session_id = db.create_session("practice", "1", [question["id"]])

    _, response = submit_current(
        client, app, session_id, override={"text": "Не знаю, подскажите."}
    )
    feedback = client.get(response.headers["Location"])
    text = feedback.get_data(as_text=True)
    assert "Ключевые пункты" in text
    assert "Мой ответ верен по смыслу" in text
    assert "Пример решения" in text

    self_mark = client.post(
        f"/lesson/{session_id}/self-mark",
        data={"value": "correct"},
        follow_redirects=True,
    )
    assert "Ответ зачтён" in self_mark.get_data(as_text=True)
    attempt = db.get_attempt(db.get_session(session_id)["pending_attempt_id"])
    assert attempt["correct"] == 1
    assert db.total_xp() == question["xp"]

    client.post(f"/lesson/{session_id}/next")
    assert db.get_session(session_id)["completed"] == 1
    assert db.review_count() == 0


def test_import_rejects_broken_json(client, app):
    db = app.config["DB"]
    before = db.overview(date.today())["answered"]
    response = client.post(
        "/data/import",
        data={
            "file": (io.BytesIO(b"{not a json"), "broken.json"),
            "mode": "merge",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)
    assert "повреждён" in text
    assert db.overview(date.today())["answered"] == before


def test_import_replace_without_confirmation(client, app):
    db = app.config["DB"]
    question = get_question("m1-03")
    session_id = db.create_session("practice", "1", [question["id"]])
    submit_current(client, app, session_id)
    before = db.overview(date.today())["answered"]
    assert before == 1

    empty_db = Database(app.config["DB"].path.parent / "empty_replace.db")
    empty_backup = json.dumps(build_backup(empty_db), ensure_ascii=False).encode()
    response = client.post(
        "/data/import",
        data={
            "file": (io.BytesIO(empty_backup), "empty.json"),
            "mode": "replace",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)
    assert "Прогресс заменён" in text
    assert "Статистика" in text
    assert db.overview(date.today())["answered"] == 0


def test_export_merge_and_replace(client, app, tmp_path):
    db = app.config["DB"]
    question = get_question("m2-02")
    session_id = db.create_session("practice", "1", [question["id"]])
    submit_current(client, app, session_id)
    client.post(f"/lesson/{session_id}/next")
    xp_before = db.total_xp()
    assert xp_before == question["xp"]

    exported = client.get("/data/export")
    payload = json.loads(exported.get_data(as_text=True))
    assert payload["format"] == "netpractice-backup"
    assert payload["format_version"] == 1
    assert payload["counts"]["attempts"] == 1
    assert "attachment" in exported.headers["Content-Disposition"]

    merge = client.post(
        "/data/import",
        data={
            "file": (io.BytesIO(exported.data), "backup.json"),
            "mode": "merge",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "История объединена" in merge.get_data(as_text=True)
    assert db.total_xp() == xp_before

    empty_db = Database(tmp_path / "empty.db")
    empty_backup = json.dumps(build_backup(empty_db), ensure_ascii=False).encode()
    replace = client.post(
        "/data/import",
        data={
            "file": (io.BytesIO(empty_backup), "empty.json"),
            "mode": "replace",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "Прогресс заменён" in replace.get_data(as_text=True)
    assert db.overview(date.today())["answered"] == 0
    assert db.total_xp() == 0


def test_practice_session_created_for_first_module(client, app):
    response = client.post("/practice/1/start")
    assert response.status_code == 302
    session = app.config["DB"].get_session(session_id_from(response))
    assert session["kind"] == "practice"
    assert session["total"] == 6


def test_data_dir_env_controls_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "netpractice-data"
    monkeypatch.setenv("NETPRACTICE_DATA_DIR", str(data_dir))
    monkeypatch.delenv("NETPRACTICE_DB", raising=False)
    application = create_app(secret_key=None)
    expected = data_dir.resolve()
    assert Path(application.config["DATA_DIR"]) == expected
    assert Path(application.config["DB"].path) == expected / "netpractice.db"
    assert Path(application.instance_path) == expected
    assert (expected / "secret_key").is_file()
    assert (expected / "pending_packs").is_dir()
    assert Path(application.config["PACK_PENDING_DIR"]) == expected / "pending_packs"


def test_data_dir_env_keeps_explicit_db_override(tmp_path, monkeypatch):
    data_dir = tmp_path / "netpractice-data"
    db_path = tmp_path / "custom" / "other.db"
    monkeypatch.setenv("NETPRACTICE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("NETPRACTICE_DB", str(db_path))
    application = create_app(secret_key="test-secret")
    assert Path(application.config["DATA_DIR"]) == data_dir.resolve()
    assert Path(application.config["DB"].path) == db_path
    assert Path(application.config["PACK_PENDING_DIR"]) == data_dir.resolve() / "pending_packs"


def test_explicit_db_path_uses_its_parent_for_runtime_files(tmp_path):
    db_path = tmp_path / "explicit" / "netpractice.db"
    application = create_app(db_path=db_path, secret_key="test-secret")
    assert Path(application.config["DATA_DIR"]) == db_path.parent
    assert Path(application.config["PACK_PENDING_DIR"]) == db_path.parent / "pending_packs"


def test_navigation_has_exactly_four_items(client):
    text = client.get("/").get_data(as_text=True)
    for css_class in ("main-nav", "bottom-nav"):
        match = re.search(
            rf'<nav class="{css_class}".*?</nav>', text, re.S
        )
        assert match, css_class
        links = re.findall(r"<a\b", match.group(0))
        assert len(links) == 4, (css_class, links)
    assert 'href="/learn"' in text
    assert 'href="/review"' in text
    assert 'href="/stats"' in text


def test_practice_page_redirects_to_learn(client):
    response = client.get("/practice")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/learn")
    assert client.get("/practice", follow_redirects=True).status_code == 200


def test_learn_shows_unfinished_practice(client, app):
    db = app.config["DB"]
    session_id = db.create_session("practice", "1", ["m1-01"])
    response = client.get("/learn")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Незавершённая тренировка" in text
    assert f"/lesson/{session_id}" in text


def test_library_has_learning_switcher_and_no_filters(client):
    response = client.get("/library")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "learning-switcher" in text
    assert "Мои модули" in text
    assert 'class="filter-bar"' not in text
    assert 'name="category"' not in text
    assert 'name="difficulty"' not in text


def test_home_has_only_streak_and_calendar(client):
    response = client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'class="daily-card"' not in text
    assert "Продолжить обучение" not in text
    assert "Всего XP" not in text
    assert "Точность" not in text
    assert text.count('class="metric"') == 1
    assert "Календарь активности" in text
    assert "home-calendar" in text


def test_home_shows_daily_progress_in_hero(client, app):
    db = app.config["DB"]
    session_id = db.create_session("daily", date.today().isoformat(), ["m1-01"])
    response = client.get("/")
    text = response.get_data(as_text=True)
    assert "Продолжить занятие" in text
    assert "Задание 1 из 1" in text
    assert f"/lesson/{session_id}" in text


def test_dark_color_scheme_declared(client):
    page = client.get("/").get_data(as_text=True)
    assert '<meta name="color-scheme" content="dark">' in page
    css = Path("static/css/style.css").read_text(encoding="utf-8")
    assert "color-scheme: dark;" in css
    assert "--field-bg:" in css
    assert ".import-form" in css
    stats = client.get("/stats").get_data(as_text=True)
    assert 'class="import-form"' in stats


def test_stats_page_is_only_page_and_has_backup(client):
    redirect = client.get("/data")
    assert redirect.status_code == 302
    assert redirect.headers["Location"].endswith("/stats")

    stats = client.get("/stats")
    assert stats.status_code == 200
    text = stats.get_data(as_text=True)
    assert "Последние ответы" not in text
    assert "Резервная копия" in text
    assert "История ответов" not in text
    assert "Экспорт" in text
    assert "Импорт" in text
    assert 'download' in text
    assert 'id="backup-import-toggle"' in text
    assert 'aria-expanded="false"' in text
    assert 'id="backup-import-panel"' in text
    assert " hidden" in text
    assert 'name="mode" value="merge"' in text
    assert 'name="mode" value="replace"' in text
    assert text.count('data-backup-submit disabled') == 2
    assert 'name="confirm"' not in text


def test_stats_and_review_pages_open(client):
    for path in ("/stats", "/review"):
        response = client.get(path)
        assert response.status_code == 200, path
    stats = client.get("/stats").get_data(as_text=True)
    assert "Календарь активности" in stats
    assert "Знания по программе" in stats
    assert "Резервная копия" in stats


def test_pwa_endpoints(client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.mimetype == "application/manifest+json"
    payload = json.loads(manifest.get_data(as_text=True))
    assert payload["start_url"] == "/"
    assert payload["display"] == "standalone"

    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["Service-Worker-Allowed"] == "/"

    offline = client.get("/offline")
    assert offline.status_code == 200
    assert "Локальный сервер недоступен" in offline.get_data(as_text=True)

    icon = client.get("/static/icons/icon-192.png")
    assert icon.status_code == 200
    assert icon.mimetype == "image/png"


def test_404_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "Страница не найдена" in response.get_data(as_text=True)
