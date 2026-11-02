"""NetPractice — локальный тренажёр сетевого администратора.

Запуск: python app.py
Адрес по умолчанию: http://127.0.0.1:5000
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)

import packs
import study
from backup import (
    MAX_FILE_SIZE,
    BackupError,
    build_backup,
    parse_backup,
)
from content import get_module, get_question
from database import Database
from grading import (
    DIFFICULTY_LABELS,
    TYPE_LABELS,
    collect_answer,
    grade_answer,
)
from packs import MAX_ARCHIVE_BYTES, PackError

ALLOWED_MODES = {"daily", "practice", "review"}


def load_secret_key(instance_path: str) -> str:
    path = Path(instance_path) / "secret_key"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    path.write_text(value, encoding="utf-8")
    return value


def create_app(db_path=None, secret_key=None) -> Flask:
    data_dir_env = os.environ.get("NETPRACTICE_DATA_DIR")
    if db_path is None and data_dir_env:
        data_dir = Path(data_dir_env).expanduser().resolve()
        app = Flask(
            __name__,
            instance_path=str(data_dir),
            instance_relative_config=True,
        )
    else:
        app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    if db_path is None:
        if data_dir_env:
            data_dir = Path(data_dir_env).expanduser().resolve()
        else:
            data_dir = Path(app.instance_path)
        db_path = os.environ.get(
            "NETPRACTICE_DB", str(data_dir / "netpractice.db")
        )
    else:
        data_dir = Path(db_path).expanduser().resolve().parent

    data_dir.mkdir(parents=True, exist_ok=True)
    app.config["DATA_DIR"] = str(data_dir)
    app.config["SECRET_KEY"] = secret_key or load_secret_key(data_dir)
    app.config["DB"] = Database(db_path)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    app.config["PACK_PENDING_DIR"] = data_dir / "pending_packs"
    app.config["PACK_PENDING_DIR"].mkdir(parents=True, exist_ok=True)
    # В тестах можно зафиксировать дату, чтобы проверять серию дней.
    app.config["TODAY_OVERRIDE"] = None

    def db() -> Database:
        return current_app.config["DB"]

    def today() -> date:
        return current_app.config.get("TODAY_OVERRIDE") or date.today()

    def load_question(question_id: str, active_only=False):
        question = get_question(question_id)
        if question is not None:
            return question
        return packs.get_custom_question(db(), question_id, active_only=active_only)

    def session_title(session) -> str:
        title = study.lesson_title(session["kind"], session["key"])
        if session["kind"] == "practice" and session["key"].startswith("pack:"):
            module = packs.get_custom_module(
                db(), session["key"][5:], include_removed=True
            )
            if module:
                return f"Практика: {module['title']}"
        return title

    @app.context_processor
    def inject_globals():
        return {
            "TYPE_LABELS": TYPE_LABELS,
            "DIFFICULTY_LABELS": DIFFICULTY_LABELS,
            "PACK_DIFFICULTY_LABELS": packs.DIFFICULTY_LABELS,
            "global_stats": db().overview(today()),
            "today": today(),
            "app_year": date.today().year,
        }

    @app.template_filter("ru_date")
    def ru_date(value):
        if isinstance(value, str):
            try:
                value = date.fromisoformat(value[:10])
            except ValueError:
                return value
        if isinstance(value, date):
            return value.strftime("%d.%m.%Y")
        return value

    @app.template_filter("ru_datetime")
    def ru_datetime(value):
        if not value:
            return "—"
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return value
        return moment.strftime("%d.%m.%Y %H:%M")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'",
        )
        return response

    # ------------------------------------------------------------------
    # Главная
    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        day = today()
        stats = db().overview(day)
        daily = db().find_incomplete_session("daily")
        completed_today = db().count_completed_daily(day.isoformat())
        weeks = study.calendar_weeks(db().activity_map(), day)
        return render_template(
            "index.html",
            stats=stats,
            daily=daily,
            completed_today=completed_today,
            weeks=weeks,
            daily_size=study.DAILY_SIZE,
            daily_percent=min(100, round(stats["today_answered"] * 100 / study.DAILY_SIZE)),
        )

    @app.post("/daily/start")
    def daily_start():
        existing = db().find_incomplete_session("daily")
        if existing:
            return redirect(url_for("lesson", session_id=existing["id"]))
        day = today()
        question_ids = study.build_daily(db(), day)
        if not question_ids:
            flash("Не удалось подобрать задания. Проверьте учебный контент.", "error")
            return redirect(url_for("index"))
        # Ранний поиск выше уже обработан; здесь закрываем гонку между
        # параллельными POST: проверка и вставка идут под BEGIN IMMEDIATE.
        session_id = db().get_or_create_daily_session(day.isoformat(), question_ids)
        return redirect(url_for("lesson", session_id=session_id))

    # ------------------------------------------------------------------
    # Обучение и практика
    # ------------------------------------------------------------------
    @app.get("/learn")
    def learn():
        progress = study.module_progress(db())
        incomplete = db().find_incomplete_session("practice")
        return render_template(
            "learn.html", progress=progress, incomplete=incomplete
        )

    @app.get("/learn/<int:module_id>")
    def module_detail(module_id):
        module = get_module(module_id)
        if module is None:
            abort(404)
        progress = study.get_module_progress(db(), module_id)
        status = db().question_status()
        questions = []
        if progress["unlocked"]:
            for question in study.QUESTIONS_BY_MODULE[module_id]:
                info = status.get(question["id"], {})
                questions.append({
                    **question,
                    "attempted": info.get("attempts", 0) > 0,
                    "ever_correct": bool(info.get("ever_correct")),
                })
        return render_template(
            "module.html",
            module=module,
            progress=progress,
            questions=questions,
        )

    @app.get("/practice")
    def practice():
        return redirect(url_for("learn"))

    @app.post("/practice/<int:module_id>/start")
    def practice_start(module_id):
        module = get_module(module_id)
        if module is None:
            abort(404)
        progress = study.get_module_progress(db(), module_id)
        if not progress or not progress["unlocked"]:
            flash(
                "Этот модуль пока закрыт. Сначала пройдите предыдущий модуль.",
                "error",
            )
            return redirect(url_for("learn"))
        existing = db().find_incomplete_session_for_key("practice", str(module_id))
        if existing:
            return redirect(url_for("lesson", session_id=existing["id"]))
        question_ids = study.build_practice(
            db(), module_id, today(), study.PRACTICE_SIZE
        )
        if not question_ids:
            flash("В этом модуле пока нет заданий.", "error")
            return redirect(url_for("learn"))
        session_id = db().create_session("practice", str(module_id), question_ids)
        return redirect(url_for("lesson", session_id=session_id))

    # ------------------------------------------------------------------
    # Повторение
    # ------------------------------------------------------------------
    @app.get("/review")
    def review():
        rows = db().review_questions()
        items = []
        for row in rows:
            question = load_question(row["question_id"], active_only=True)
            if question:
                items.append({**row, "question": question})
        incomplete = db().find_incomplete_session("review")
        return render_template(
            "review.html", items=items, incomplete=incomplete
        )

    @app.post("/review/start")
    def review_start():
        existing = db().find_incomplete_session("review")
        if existing:
            return redirect(url_for("lesson", session_id=existing["id"]))
        question_ids = study.build_review(
            db(),
            lookup=lambda question_id: packs.get_custom_question(
                db(), question_id, active_only=True
            ),
        )
        if not question_ids:
            flash("В списке повторения пока нет заданий — вы ещё не ошибались.", "info")
            return redirect(url_for("review"))
        session_id = db().create_session("review", "review", question_ids)
        return redirect(url_for("lesson", session_id=session_id))

    # ------------------------------------------------------------------
    # Прохождение занятия
    # ------------------------------------------------------------------
    def load_session(session_id: int):
        session = db().get_session(session_id)
        if session is None:
            abort(404)
        return session

    @app.get("/lesson/<int:session_id>")
    def lesson(session_id):
        session = load_session(session_id)
        if session["completed"]:
            return redirect(url_for("lesson_done", session_id=session_id))
        if session["pending_attempt_id"] is not None:
            return redirect(url_for("lesson_feedback", session_id=session_id))
        if session["position"] >= session["total"]:
            return redirect(url_for("lesson_feedback", session_id=session_id))
        question = load_question(session["question_ids"][session["position"]])
        if question is None:
            abort(404)
        return render_template(
            "lesson.html",
            session=session,
            question=question,
            title=session_title(session),
            question_number=session["position"] + 1,
            progress_percent=round(session["position"] * 100 / session["total"]),
        )

    @app.post("/lesson/<int:session_id>/answer")
    def lesson_answer(session_id):
        session = load_session(session_id)
        if session["completed"]:
            return redirect(url_for("lesson_done", session_id=session_id))
        if session["pending_attempt_id"] is not None:
            return redirect(url_for("lesson_feedback", session_id=session_id))
        if session["position"] >= session["total"]:
            return redirect(url_for("lesson_feedback", session_id=session_id))

        question = load_question(session["question_ids"][session["position"]])
        if question is None:
            abort(404)
        if request.form.get("question_id") != question["id"]:
            flash("Форма устарела. Откройте задание заново.", "error")
            return redirect(url_for("lesson", session_id=session_id))

        answer = collect_answer(question, request.form)
        result = grade_answer(question, answer)
        try:
            db().record_attempt(
                session_id=session_id,
                question=question,
                answer=answer,
                result=result,
                mode=session["kind"],
                day=today().isoformat(),
                xp_value=question["xp"],
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("lesson", session_id=session_id))
        return redirect(url_for("lesson_feedback", session_id=session_id))

    @app.get("/lesson/<int:session_id>/feedback")
    def lesson_feedback(session_id):
        session = load_session(session_id)
        if session["pending_attempt_id"] is None:
            if session["completed"]:
                return redirect(url_for("lesson_done", session_id=session_id))
            return redirect(url_for("lesson", session_id=session_id))
        attempt = db().get_attempt(session["pending_attempt_id"])
        if attempt is None:
            return redirect(url_for("lesson", session_id=session_id))
        question = load_question(attempt["question_id"])
        if question is None:
            abort(404)
        result = attempt["detail"]
        self_check_available = (
            not attempt["correct"]
            and question["type"] in ("scenario", "troubleshoot")
            and not result.get("self_assessed")
        )
        return render_template(
            "feedback.html",
            session=session,
            attempt=attempt,
            question=question,
            result=result,
            title=session_title(session),
            question_number=session["position"] + 1,
            progress_percent=round(
                (session["position"] + 1) * 100 / session["total"]
            ),
            is_last=session["position"] + 1 >= session["total"],
            self_check_available=self_check_available,
        )

    @app.post("/lesson/<int:session_id>/next")
    def lesson_next(session_id):
        session = load_session(session_id)
        if session["pending_attempt_id"] is None:
            if session["completed"]:
                return redirect(url_for("lesson_done", session_id=session_id))
            return redirect(url_for("lesson", session_id=session_id))
        try:
            updated = db().advance_session(session_id, today().isoformat())
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("lesson", session_id=session_id))
        if updated["completed"]:
            return redirect(url_for("lesson_done", session_id=session_id))
        return redirect(url_for("lesson", session_id=session_id))

    @app.post("/lesson/<int:session_id>/self-mark")
    def lesson_self_mark(session_id):
        session = load_session(session_id)
        attempt_id = session["pending_attempt_id"]
        if attempt_id is None:
            return redirect(url_for("lesson", session_id=session_id))
        attempt = db().get_attempt(attempt_id)
        if attempt is None:
            abort(404)
        question = load_question(attempt["question_id"])
        if question is None or question["type"] not in ("scenario", "troubleshoot"):
            abort(400)

        value = request.form.get("value")
        if value == "correct":
            try:
                xp = db().mark_self_correct(
                    attempt_id, session_id, question, question["xp"],
                    today().isoformat(),
                )
            except ValueError as error:
                flash(str(error), "error")
                return redirect(url_for("lesson_feedback", session_id=session_id))
            if xp:
                flash(f"Ответ зачтён. Начислено {xp} XP (один раз за задание).", "success")
            else:
                flash("Ответ зачтён. XP за это задание уже начислялся ранее.", "info")
        elif value == "understood":
            db().mark_understood(attempt_id)
            flash("Хорошо. Прочитайте разбор и переходите к следующему заданию.", "info")
        else:
            flash("Неизвестное действие.", "error")
        return redirect(url_for("lesson_feedback", session_id=session_id))

    @app.get("/lesson/<int:session_id>/done")
    def lesson_done(session_id):
        session = load_session(session_id)
        if not session["completed"]:
            return redirect(url_for("lesson", session_id=session_id))
        attempts = db().session_attempts(session_id)
        answered = len(attempts)
        correct = sum(1 for attempt in attempts if attempt["correct"])
        xp = db().session_xp(session_id)
        accuracy = round(correct * 100 / answered) if answered else 0
        items = []
        for attempt in attempts:
            question = load_question(attempt["question_id"])
            if question:
                items.append({
                    "question": question,
                    "correct": bool(attempt["correct"]),
                    "xp": attempt["xp_awarded"],
                })
        return render_template(
            "done.html",
            session=session,
            title=session_title(session),
            answered=answered,
            correct=correct,
            accuracy=accuracy,
            xp=xp,
            items=items,
            review_left=db().review_count(),
        )

    # ------------------------------------------------------------------
    # Статистика
    # ------------------------------------------------------------------
    @app.get("/stats")
    def stats_page():
        day = today()
        stats = db().overview(day)
        progress = study.module_progress(db())
        activity = db().activity_map()
        weeks = study.calendar_weeks(activity, day)
        total_questions = sum(item["total"] for item in progress)
        total_correct = sum(item["correct"] for item in progress)
        return render_template(
            "stats.html",
            stats=stats,
            progress=progress,
            weeks=weeks,
            total_questions=total_questions,
            total_correct=total_correct,
            overall_percent=(
                round(total_correct * 100 / total_questions)
                if total_questions else 0
            ),
        )

    # ------------------------------------------------------------------
    # Данные: экспорт и импорт
    # ------------------------------------------------------------------
    @app.get("/data")
    def data_page():
        return redirect(url_for("stats_page"))

    @app.get("/data/export")
    def data_export():
        payload = build_backup(db())
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        response = Response(text, mimetype="application/json")
        response.headers["Content-Disposition"] = (
            "attachment; filename=netpractice_backup.json"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/data/import")
    def data_import():
        upload = request.files.get("file")
        mode = request.form.get("mode", "merge")

        if upload is None or not upload.filename:
            flash("Выберите JSON-файл резервной копии.", "error")
            return redirect(url_for("stats_page"))
        if mode not in ("merge", "replace"):
            flash("Выберите режим импорта: объединить или заменить.", "error")
            return redirect(url_for("stats_page"))

        raw = upload.stream.read(MAX_FILE_SIZE + 1)
        if len(raw) > MAX_FILE_SIZE:
            flash("Файл слишком большой (максимум 2 МБ).", "error")
            return redirect(url_for("stats_page"))

        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Не удалось прочитать файл: он должен быть в кодировке UTF-8.", "error")
            return redirect(url_for("stats_page"))

        try:
            payload = json.loads(text)
        except ValueError:
            flash(
                "Файл повреждён: это не корректный JSON. Прогресс не изменён.",
                "error",
            )
            return redirect(url_for("stats_page"))

        try:
            data, counts = parse_backup(payload)
        except BackupError as error:
            flash(f"Импорт отменён. {error}", "error")
            return redirect(url_for("stats_page"))

        if mode == "replace":
            result = db().replace_from_backup(data)
            flash(
                "Прогресс заменён. Загружено: "
                f"{result['attempts']} ответов, "
                f"{result['question_awards']} начислений XP, "
                f"{result['review_questions']} заданий в повторении.",
                "success",
            )
        else:
            result = db().merge_from_backup(data)
            flash(
                "История объединена. Добавлено: "
                f"{result['attempts']} новых ответов, "
                f"{result['question_awards']} новых начислений XP, "
                f"{result['review_questions']} записей повторения. "
                "Дубликаты не начислены повторно.",
                "success",
            )
        return redirect(url_for("stats_page"))

    # ------------------------------------------------------------------
    # Библиотека учебных пакетов
    # ------------------------------------------------------------------
    def pack_import_status(existing, manifest) -> str:
        if existing is None:
            return "new"
        if existing["removed_at"]:
            return "reinstall"
        comparison = packs.compare_versions(
            manifest["module_version"], existing["module_version"]
        )
        if comparison > 0:
            return "update"
        if comparison == 0:
            return "same"
        return "downgrade"

    def pending_path(token: str) -> Path:
        return Path(current_app.config["PACK_PENDING_DIR"]) / f"{token}.nptpack"

    @app.get("/library")
    def library():
        modules = packs.list_custom_modules(db())
        for module in modules:
            module["progress"] = packs.module_progress(db(), module)
        return render_template(
            "library.html",
            custom_modules=modules,
            system_modules=study.module_progress(db()),
        )

    @app.post("/library/import/preview")
    def library_import_preview():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            flash("Выберите файл учебного пакета .nptpack.", "error")
            return redirect(url_for("library"))
        if Path(upload.filename).suffix.lower() != ".nptpack":
            flash("Нужен файл с расширением .nptpack.", "error")
            return redirect(url_for("library"))
        allowed_mimes = {
            "application/zip", "application/x-zip-compressed",
            "application/octet-stream", "application/x-nptpack", "",
        }
        if upload.mimetype not in allowed_mimes:
            flash("Неверный MIME-тип файла. Нужен ZIP-архив .nptpack.", "error")
            return redirect(url_for("library"))

        raw = upload.stream.read(MAX_ARCHIVE_BYTES + 1)
        if len(raw) > MAX_ARCHIVE_BYTES:
            flash("Пакет больше 5 МБ.", "error")
            return redirect(url_for("library"))
        try:
            pack = packs.parse_pack_bytes(raw)
        except PackError as error:
            flash(f"Пакет не принят: {error}", "error")
            return redirect(url_for("library"))
        except Exception:
            current_app.logger.exception("Unexpected pack parse failure")
            flash("Не удалось проверить пакет. Изменения не внесены.", "error")
            return redirect(url_for("library"))

        token = secrets.token_urlsafe(24)
        path = pending_path(token)
        path.write_bytes(raw)
        session["pending_pack"] = token
        existing = packs.get_custom_module(
            db(), pack["manifest"]["id"], include_removed=True
        )
        status = pack_import_status(existing, pack["manifest"])
        if status == "same":
            path.unlink(missing_ok=True)
            session.pop("pending_pack", None)
        return render_template(
            "library_import.html",
            pack=pack,
            existing=existing,
            status=status,
            token=token,
        )

    @app.post("/library/import/confirm")
    def library_import_confirm():
        token = request.form.get("token", "")
        expected = session.get("pending_pack")
        safe_token = bool(token) and all(
            character.isalnum() or character in "-_" for character in token
        )
        if not safe_token or token != expected:
            flash("Сессия импорта устарела. Загрузите пакет заново.", "error")
            return redirect(url_for("library"))

        path = pending_path(token)
        if not path.is_file():
            session.pop("pending_pack", None)
            flash("Временный файл пакета не найден. Загрузите его заново.", "error")
            return redirect(url_for("library"))

        raw = path.read_bytes()
        try:
            pack = packs.parse_pack_bytes(raw)
            result = packs.install_pack(
                db(), pack, len(raw),
                allow_downgrade=request.form.get("allow_downgrade") == "yes",
            )
        except PackError as error:
            flash(f"Импорт отменён: {error}", "error")
            return redirect(url_for("library"))
        except Exception:
            current_app.logger.exception("Unexpected pack install failure")
            flash("Не удалось установить пакет. Предыдущая версия не изменена.", "error")
            return redirect(url_for("library"))
        finally:
            path.unlink(missing_ok=True)
            session.pop("pending_pack", None)

        pack_id = pack["manifest"]["id"]
        if result["status"] == "same":
            flash("Эта версия модуля уже установлена. Изменения не внесены.", "info")
        else:
            action = "обновлён" if result["status"] in ("updated", "downgraded") else "установлен"
            flash(
                f"Модуль «{pack['manifest']['title']}» {action}. "
                f"Заданий: {result['questions']}, лабораторных: {result['labs']}.",
                "success",
            )
        return redirect(url_for("library_pack", pack_id=pack_id))

    @app.post("/library/import/cancel")
    def library_import_cancel():
        token = request.form.get("token", "")
        if token and token == session.get("pending_pack"):
            path = pending_path(token)
            path.unlink(missing_ok=True)
            session.pop("pending_pack", None)
        flash("Импорт отменён. База данных не изменена.", "info")
        return redirect(url_for("library"))

    @app.get("/library/<pack_id>")
    def library_pack(pack_id):
        module = packs.get_custom_module(db(), pack_id)
        if module is None:
            abort(404)
        questions = packs.get_custom_questions(db(), pack_id)
        status = db().question_status()
        for question in questions:
            info = status.get(question["id"], {})
            question["attempted"] = info.get("attempts", 0) > 0
            question["ever_correct"] = bool(info.get("ever_correct"))
        labs = packs.get_custom_labs(db(), pack_id)
        progress = packs.module_progress(db(), module)
        incomplete = db().find_incomplete_session_for_key(
            "practice", f"pack:{pack_id}"
        )
        return render_template(
            "library_pack.html",
            module=module,
            questions=questions,
            labs=labs,
            progress=progress,
            incomplete=incomplete,
        )

    @app.post("/library/<pack_id>/start")
    def library_start(pack_id):
        module = packs.get_custom_module(db(), pack_id)
        if module is None:
            abort(404)
        questions = packs.get_custom_questions(db(), pack_id)
        if not questions:
            flash("В этом модуле нет заданий.", "error")
            return redirect(url_for("library_pack", pack_id=pack_id))
        key = f"pack:{pack_id}"
        existing = db().find_incomplete_session_for_key("practice", key)
        if existing:
            return redirect(url_for("lesson", session_id=existing["id"]))
        question_ids = study.build_practice_from_questions(
            db(), questions, today(), module["module_id"], study.PRACTICE_SIZE
        )
        session_id = db().create_session("practice", key, question_ids)
        return redirect(url_for("lesson", session_id=session_id))

    @app.get("/library/assets/<pack_id>/<path:filename>")
    def library_asset(pack_id, filename):
        module = packs.get_custom_module(db(), pack_id)
        if module is None:
            abort(404)
        asset = packs.get_custom_asset(db(), pack_id, filename)
        if asset is None:
            abort(404)
        return send_file(
            BytesIO(asset["data"]),
            mimetype=asset["media_type"],
            download_name=Path(asset["filename"]).name,
            max_age=3600,
        )

    @app.get("/library/<pack_id>/export")
    def library_export(pack_id):
        module = packs.get_custom_module(db(), pack_id)
        if module is None:
            abort(404)
        try:
            raw = packs.export_pack(db(), pack_id)
        except PackError as error:
            flash(f"Не удалось экспортировать модуль: {error}", "error")
            return redirect(url_for("library_pack", pack_id=pack_id))
        return send_file(
            BytesIO(raw),
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{pack_id}-{module['module_version']}.nptpack",
        )

    @app.get("/library/<pack_id>/delete")
    def library_delete_page(pack_id):
        module = packs.get_custom_module(db(), pack_id)
        if module is None:
            abort(404)
        return render_template("library_delete.html", module=module)

    @app.post("/library/<pack_id>/delete")
    def library_delete(pack_id):
        module = packs.get_custom_module(db(), pack_id)
        if module is None:
            abort(404)
        if request.form.get("confirm") != "yes":
            flash("Удаление не подтверждено. Модуль оставлен в библиотеке.", "error")
            return redirect(url_for("library_pack", pack_id=pack_id))
        try:
            packs.remove_custom_pack(db(), pack_id)
        except PackError as error:
            flash(str(error), "error")
            return redirect(url_for("library_pack", pack_id=pack_id))
        flash(f"Модуль «{module['title']}» удалён из библиотеки. История сохранена.", "success")
        return redirect(url_for("library"))

    # ------------------------------------------------------------------
    # PWA и служебные страницы
    # ------------------------------------------------------------------
    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(
            app.static_folder,
            "manifest.webmanifest",
            mimetype="application/manifest+json",
        )

    @app.get("/sw.js")
    def service_worker():
        response = send_from_directory(
            app.static_folder, "js/sw.js", mimetype="application/javascript"
        )
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/offline")
    def offline():
        return render_template("offline.html")

    @app.errorhandler(404)
    def not_found(error):
        return render_template(
            "error.html",
            title="Страница не найдена",
            message="Такой страницы нет. Вернитесь на главную и продолжите занятие.",
        ), 404

    @app.errorhandler(413)
    def too_large(error):
        return render_template(
            "error.html",
            title="Файл слишком большой",
            message="Максимальный размер загружаемого файла — 10 МБ.",
        ), 413

    return app


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("NETPRACTICE_HOST", "127.0.0.1")
    port = int(os.environ.get("NETPRACTICE_PORT", "5000"))
    print("=" * 58)
    print("NetPractice запущен")
    print(f"Откройте в браузере: http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        print("Доступ по локальной сети включён (host 0.0.0.0).")
        print("Открывайте адрес компьютера вида http://192.168.x.x:%d" % port)
    print("Остановить сервер: Ctrl+C")
    print("=" * 58, flush=True)
    # debug=False обязателен: отладочный режим нельзя открывать в сеть.
    app.run(host=host, port=port, debug=False)

