"""Работа с локальной базой SQLite.

Все данные хранятся в одном файле (по умолчанию instance/netpractice.db).
Новое соединение открывается на каждую операцию — так проще и надёжнее для
небольшого локального приложения.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

DAILY_BONUS = 15
DB_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uid          TEXT NOT NULL UNIQUE,
    session_id   INTEGER,
    question_id  TEXT NOT NULL,
    module_id    INTEGER NOT NULL,
    day          TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    mode         TEXT NOT NULL,
    answer       TEXT NOT NULL,
    correct      INTEGER NOT NULL,
    score        INTEGER NOT NULL,
    xp_awarded   INTEGER NOT NULL DEFAULT 0,
    detail       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_attempts_day ON attempts(day);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);

CREATE TABLE IF NOT EXISTS question_awards (
    question_id TEXT PRIMARY KEY,
    xp          INTEGER NOT NULL,
    day         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_questions (
    question_id    TEXT PRIMARY KEY,
    module_id      INTEGER NOT NULL,
    wrong_count    INTEGER NOT NULL DEFAULT 1,
    first_wrong_at TEXT NOT NULL,
    last_wrong_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    uid                TEXT NOT NULL UNIQUE,
    kind               TEXT NOT NULL,
    key                TEXT NOT NULL,
    question_ids       TEXT NOT NULL,
    position           INTEGER NOT NULL DEFAULT 0,
    correct            INTEGER NOT NULL DEFAULT 0,
    wrong              INTEGER NOT NULL DEFAULT 0,
    completed          INTEGER NOT NULL DEFAULT 0,
    pending_attempt_id INTEGER,
    bonus_xp           INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL,
    completed_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_kind ON sessions(kind, completed);

CREATE TABLE IF NOT EXISTS daily_bonus (
    day        TEXT PRIMARY KEY,
    xp         INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_modules (
    pack_id        TEXT PRIMARY KEY,
    module_id      INTEGER NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    author         TEXT NOT NULL,
    module_version TEXT NOT NULL,
    language       TEXT NOT NULL,
    difficulty     TEXT NOT NULL,
    category       TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    min_app_version TEXT NOT NULL,
    manifest_json  TEXT NOT NULL,
    package_size   INTEGER NOT NULL DEFAULT 0,
    installed_at   TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    removed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_custom_modules_removed
    ON custom_modules(removed_at);

CREATE TABLE IF NOT EXISTS custom_questions (
    question_id TEXT PRIMARY KEY,
    pack_id     TEXT NOT NULL,
    module_id   INTEGER NOT NULL,
    local_id    TEXT NOT NULL,
    position    INTEGER NOT NULL,
    data_json   TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL,
    UNIQUE(pack_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_custom_questions_pack
    ON custom_questions(pack_id, active, position);

CREATE TABLE IF NOT EXISTS custom_labs (
    pack_id     TEXT NOT NULL,
    local_id    TEXT NOT NULL,
    module_id   INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    data_json   TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY(pack_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_custom_labs_pack
    ON custom_labs(pack_id, active, position);

CREATE TABLE IF NOT EXISTS custom_assets (
    pack_id     TEXT NOT NULL,
    filename    TEXT NOT NULL,
    media_type  TEXT NOT NULL,
    size        INTEGER NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    data        BLOB NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY(pack_id, filename)
);

CREATE TABLE IF NOT EXISTS custom_question_archive (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_id        TEXT NOT NULL,
    question_id    TEXT NOT NULL,
    local_id       TEXT NOT NULL,
    source_version TEXT NOT NULL,
    data_json      TEXT NOT NULL,
    archived_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_custom_question_archive_pack
    ON custom_question_archive(pack_id, question_id);
"""


def now_text() -> str:
    """Локальное время сервера в удобном для чтения формате."""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def compute_streak(day_strings, today: date) -> tuple[int, int]:
    """Вернуть (текущая серия, максимальная серия).

    Серия считается по уникальным календарным датам занятий.
    Если последнее занятие было сегодня или вчера, серия продолжается.
    Пропуск полного календарного дня обнуляет текущую серию.
    Максимальная серия вычисляется по всей истории.
    """
    days = sorted({date.fromisoformat(d) for d in day_strings})

    max_run = 0
    run = 0
    previous = None
    for day in days:
        if previous is not None and (day - previous).days == 1:
            run += 1
        else:
            run = 1
        max_run = max(max_run, run)
        previous = day

    current = 0
    if days and days[-1] in (today, today - timedelta(days=1)):
        current = 1
        index = len(days) - 1
        while index > 0 and (days[index] - days[index - 1]).days == 1:
            current += 1
            index -= 1

    return current, max_run


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Служебные методы
    # ------------------------------------------------------------------
    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self):
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('db_version', ?)",
                (str(DB_VERSION),),
            )

    # ------------------------------------------------------------------
    # Сессии (уроки, практика, повторение)
    # ------------------------------------------------------------------
    def create_session(self, kind: str, key: str, question_ids) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO sessions
                   (uid, kind, key, question_ids, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex,
                    kind,
                    key,
                    json.dumps(list(question_ids), ensure_ascii=False),
                    now_text(),
                ),
            )
            return int(cursor.lastrowid)

    def get_or_create_daily_session(self, key: str, question_ids) -> int:
        """Вернуть незавершённую ежедневную сессию или создать её атомарно.

        BEGIN IMMEDIATE берёт write-lock до проверки. Без него два запроса
        могут одновременно не найти сессию и создать две разные.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id FROM sessions
                   WHERE kind = 'daily' AND completed = 0
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cursor = connection.execute(
                """INSERT INTO sessions
                   (uid, kind, key, question_ids, created_at)
                   VALUES (?, 'daily', ?, ?, ?)""",
                (
                    uuid.uuid4().hex,
                    key,
                    json.dumps(list(question_ids), ensure_ascii=False),
                    now_text(),
                ),
            )
            return int(cursor.lastrowid)


    def get_session(self, session_id: int):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._session_row(row)

    @staticmethod
    def _session_row(row):
        if row is None:
            return None
        data = dict(row)
        data["question_ids"] = json.loads(data["question_ids"])
        data["total"] = len(data["question_ids"])
        return data

    def find_incomplete_session(self, kind: str):
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM sessions
                   WHERE kind = ? AND completed = 0
                   ORDER BY id DESC LIMIT 1""",
                (kind,),
            ).fetchone()
        return self._session_row(row)

    def find_incomplete_session_for_key(self, kind: str, key: str):
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM sessions
                   WHERE kind = ? AND key = ? AND completed = 0
                   ORDER BY id DESC LIMIT 1""",
                (kind, key),
            ).fetchone()
        return self._session_row(row)

    def count_completed_daily(self, day: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS n FROM sessions
                   WHERE kind = 'daily' AND key = ? AND completed = 1""",
                (day,),
            ).fetchone()
        return int(row["n"])

    def count_completed_lessons(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM sessions WHERE kind = 'daily' AND completed = 1"
            ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # Попытки и XP
    # ------------------------------------------------------------------
    def record_attempt(
        self,
        session_id: int,
        question: dict,
        answer: dict,
        result: dict,
        mode: str,
        day: str,
        xp_value: int,
    ) -> tuple[int, int]:
        """Сохранить попытку. Вернуть (id попытки, начисленный XP)."""
        with self.connect() as connection:
            session = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session is None:
                raise ValueError("Урок не найден.")
            if session["completed"]:
                raise ValueError("Урок уже завершён.")
            if session["pending_attempt_id"] is not None:
                raise ValueError("Сначала перейдите к следующему заданию.")
            if not result.get("correct") and not result.get("fields"):
                # Даже пустой ответ сохраняем как ошибку.
                pass

            attempt_uid = uuid.uuid4().hex
            cursor = connection.execute(
                """INSERT INTO attempts
                   (uid, session_id, question_id, module_id, day, created_at, mode,
                    answer, correct, score, xp_awarded, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (
                    attempt_uid,
                    session_id,
                    question["id"],
                    question["module"],
                    day,
                    now_text(),
                    mode,
                    json.dumps(answer, ensure_ascii=False),
                    int(bool(result.get("correct"))),
                    int(result.get("score", 0)),
                    json.dumps(result, ensure_ascii=False),
                ),
            )
            attempt_id = int(cursor.lastrowid)

            xp_awarded = 0
            if result.get("correct") and xp_value > 0:
                xp_awarded = self._award_xp(connection, question, xp_value, day)
                if xp_awarded:
                    connection.execute(
                        "UPDATE attempts SET xp_awarded = ? WHERE id = ?",
                        (xp_awarded, attempt_id),
                    )

            if result.get("correct"):
                connection.execute(
                    "DELETE FROM review_questions WHERE question_id = ?",
                    (question["id"],),
                )
            else:
                connection.execute(
                    """INSERT INTO review_questions
                       (question_id, module_id, wrong_count, first_wrong_at, last_wrong_at)
                       VALUES (?, ?, 1, ?, ?)
                       ON CONFLICT(question_id) DO UPDATE SET
                           wrong_count = wrong_count + 1,
                           last_wrong_at = excluded.last_wrong_at""",
                    (question["id"], question["module"], now_text(), now_text()),
                )

            connection.execute(
                """UPDATE sessions SET
                       correct = correct + ?,
                       wrong = wrong + ?,
                       pending_attempt_id = ?
                   WHERE id = ?""",
                (
                    1 if result.get("correct") else 0,
                    0 if result.get("correct") else 1,
                    attempt_id,
                    session_id,
                ),
            )
            return attempt_id, xp_awarded

    @staticmethod
    def _award_xp(connection, question: dict, xp_value: int, day: str) -> int:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO question_awards
               (question_id, xp, day, created_at)
               VALUES (?, ?, ?, ?)""",
            (question["id"], xp_value, day, now_text()),
        )
        return xp_value if cursor.rowcount else 0

    def get_attempt(self, attempt_id: int):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        try:
            data["answer"] = json.loads(data["answer"])
        except (TypeError, ValueError):
            data["answer"] = {}
        try:
            data["detail"] = json.loads(data["detail"])
        except (TypeError, ValueError):
            data["detail"] = {}
        return data

    def advance_session(self, session_id: int, day: str):
        """Перейти к следующему заданию или завершить урок."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Урок не найден.")
            if row["pending_attempt_id"] is None:
                raise ValueError("Нет ответа, который можно пропустить.")

            question_ids = json.loads(row["question_ids"])
            new_position = int(row["position"]) + 1
            if new_position >= len(question_ids):
                bonus = 0
                if row["kind"] == "daily":
                    cursor = connection.execute(
                        """INSERT OR IGNORE INTO daily_bonus (day, xp, created_at)
                           VALUES (?, ?, ?)""",
                        (row["key"], DAILY_BONUS, now_text()),
                    )
                    if cursor.rowcount:
                        bonus = DAILY_BONUS
                connection.execute(
                    """UPDATE sessions SET
                           position = ?, completed = 1, pending_attempt_id = NULL,
                           bonus_xp = ?, completed_at = ?
                       WHERE id = ?""",
                    (len(question_ids), bonus, now_text(), session_id),
                )
            else:
                connection.execute(
                    """UPDATE sessions SET position = ?, pending_attempt_id = NULL
                       WHERE id = ?""",
                    (new_position, session_id),
                )
        return self.get_session(session_id)

    def mark_self_correct(self, attempt_id: int, session_id: int, question: dict,
                          xp_value: int, day: str) -> int:
        """Пользователь подтвердил, что развёрнутый ответ верен по смыслу."""
        with self.connect() as connection:
            session = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            attempt = connection.execute(
                "SELECT * FROM attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if session is None or attempt is None:
                raise ValueError("Попытка не найдена.")
            if session["pending_attempt_id"] != attempt_id or session["completed"]:
                raise ValueError("Эту попытку уже нельзя изменить.")
            if attempt["correct"]:
                return 0

            detail = self._load_json(attempt["detail"])
            detail["self_assessed"] = True
            xp_awarded = 0
            if xp_value > 0:
                xp_awarded = self._award_xp(connection, question, xp_value, day)

            connection.execute(
                """UPDATE attempts SET correct = 1, score = 100, xp_awarded = ?,
                       detail = ? WHERE id = ?""",
                (xp_awarded, json.dumps(detail, ensure_ascii=False), attempt_id),
            )
            connection.execute(
                """UPDATE sessions SET
                       correct = correct + 1,
                       wrong = MAX(wrong - 1, 0)
                   WHERE id = ?""",
                (session_id,),
            )
            connection.execute(
                "DELETE FROM review_questions WHERE question_id = ?",
                (question["id"],),
            )
            return xp_awarded

    def mark_understood(self, attempt_id: int):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT detail FROM attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                return
            detail = self._load_json(row["detail"])
            detail["understood"] = True
            connection.execute(
                "UPDATE attempts SET detail = ? WHERE id = ?",
                (json.dumps(detail, ensure_ascii=False), attempt_id),
            )

    @staticmethod
    def _load_json(text):
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    # ------------------------------------------------------------------
    # Статистика и прогресс
    # ------------------------------------------------------------------
    def question_status(self) -> dict:
        """question_id -> {attempts, correct, ever_correct}."""
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT question_id, COUNT(*) AS attempts,
                          SUM(correct) AS correct, MAX(correct) AS ever_correct
                   FROM attempts GROUP BY question_id"""
            ).fetchall()
        return {
            row["question_id"]: {
                "attempts": int(row["attempts"]),
                "correct": int(row["correct"] or 0),
                "ever_correct": bool(row["ever_correct"]),
            }
            for row in rows
        }

    def review_questions(self):
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM review_questions
                   ORDER BY wrong_count DESC, last_wrong_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def review_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS n FROM review_questions AS r
                   WHERE NOT EXISTS (
                       SELECT 1 FROM custom_questions AS q
                       WHERE q.question_id = r.question_id AND q.active = 0
                   )"""
            ).fetchone()
        return int(row["n"])

    def total_xp(self) -> int:
        with self.connect() as connection:
            awards = connection.execute(
                "SELECT COALESCE(SUM(xp), 0) AS n FROM question_awards"
            ).fetchone()["n"]
            bonus = connection.execute(
                "SELECT COALESCE(SUM(xp), 0) AS n FROM daily_bonus"
            ).fetchone()["n"]
        return int(awards) + int(bonus)

    def day_stats(self, day: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS answered, COALESCE(SUM(correct), 0) AS correct,
                          COALESCE(SUM(xp_awarded), 0) AS xp
                   FROM attempts WHERE day = ?""",
                (day,),
            ).fetchone()
            bonus = connection.execute(
                "SELECT COALESCE(SUM(xp), 0) AS n FROM daily_bonus WHERE day = ?",
                (day,),
            ).fetchone()["n"]
        answered = int(row["answered"])
        return {
            "answered": answered,
            "correct": int(row["correct"]),
            "xp": int(row["xp"]) + int(bonus),
        }

    def activity_map(self) -> dict:
        """Дата -> сведения об активности (для календаря)."""
        result = {}
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT day, COUNT(*) AS answered,
                          COALESCE(SUM(correct), 0) AS correct,
                          COALESCE(SUM(xp_awarded), 0) AS xp
                   FROM attempts GROUP BY day"""
            ).fetchall()
            for row in rows:
                result[row["day"]] = {
                    "answered": int(row["answered"]),
                    "correct": int(row["correct"]),
                    "xp": int(row["xp"]),
                }
            bonuses = connection.execute("SELECT day, xp FROM daily_bonus").fetchall()
            for row in bonuses:
                entry = result.setdefault(
                    row["day"], {"answered": 0, "correct": 0, "xp": 0}
                )
                entry["xp"] += int(row["xp"])
        return result

    def overview(self, today: date) -> dict:
        with self.connect() as connection:
            totals = connection.execute(
                "SELECT COUNT(*) AS answered, COALESCE(SUM(correct), 0) AS correct "
                "FROM attempts"
            ).fetchone()
            days = [
                row["day"]
                for row in connection.execute(
                    "SELECT DISTINCT day FROM attempts"
                ).fetchall()
            ]
        answered = int(totals["answered"])
        correct = int(totals["correct"])
        streak, max_streak = compute_streak(days, today)
        today_stats = self.day_stats(today.isoformat())
        return {
            "answered": answered,
            "correct": correct,
            "accuracy": round(correct * 100 / answered) if answered else 0,
            "xp": self.total_xp(),
            "streak": streak,
            "max_streak": max_streak,
            "days_active": len(days),
            "today_answered": today_stats["answered"],
            "today_correct": today_stats["correct"],
            "today_xp": today_stats["xp"],
            "review_count": self.review_count(),
            "lessons_completed": self.count_completed_lessons(),
        }

    def session_attempts(self, session_id: int):
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM attempts WHERE session_id = ?
                   ORDER BY id""",
                (session_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = self._load_json(item["detail"])
            result.append(item)
        return result

    def session_xp(self, session_id: int) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COALESCE(SUM(xp_awarded), 0) AS xp
                   FROM attempts WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
            bonus = connection.execute(
                "SELECT bonus_xp FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return int(row["xp"]) + (int(bonus["bonus_xp"]) if bonus else 0)

    # ------------------------------------------------------------------
    # Экспорт и импорт
    # ------------------------------------------------------------------
    def export_data(self) -> dict:
        with self.connect() as connection:
            attempts = [
                dict(row)
                for row in connection.execute(
                    """SELECT uid, question_id, module_id, day, created_at, mode,
                              answer, correct, score, xp_awarded, detail
                       FROM attempts ORDER BY id"""
                ).fetchall()
            ]
            awards = [
                dict(row)
                for row in connection.execute(
                    "SELECT question_id, xp, day, created_at FROM question_awards"
                ).fetchall()
            ]
            review = [
                dict(row)
                for row in connection.execute(
                    """SELECT question_id, module_id, wrong_count,
                              first_wrong_at, last_wrong_at
                       FROM review_questions"""
                ).fetchall()
            ]
            bonus = [
                dict(row)
                for row in connection.execute(
                    "SELECT day, xp, created_at FROM daily_bonus"
                ).fetchall()
            ]
        return {
            "attempts": attempts,
            "question_awards": awards,
            "review_questions": review,
            "daily_bonus": bonus,
        }

    def replace_from_backup(self, data: dict) -> dict:
        with self.connect() as connection:
            for table in ("attempts", "question_awards", "review_questions",
                          "sessions", "daily_bonus"):
                connection.execute(f"DELETE FROM {table}")
            counts = self._insert_backup(connection, data)
        return counts

    def merge_from_backup(self, data: dict) -> dict:
        counts = {
            "attempts": 0,
            "question_awards": 0,
            "review_questions": 0,
            "daily_bonus": 0,
        }
        with self.connect() as connection:
            for item in data["attempts"]:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO attempts
                       (uid, session_id, question_id, module_id, day, created_at,
                        mode, answer, correct, score, xp_awarded, detail)
                       VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item["uid"], item["question_id"], item["module_id"],
                        item["day"], item["created_at"], item["mode"],
                        item["answer"], item["correct"], item["score"],
                        item["xp_awarded"], item["detail"],
                    ),
                )
                counts["attempts"] += cursor.rowcount
            for item in data["question_awards"]:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO question_awards
                       (question_id, xp, day, created_at) VALUES (?, ?, ?, ?)""",
                    (item["question_id"], item["xp"], item["day"],
                     item["created_at"]),
                )
                counts["question_awards"] += cursor.rowcount
            for item in data["review_questions"]:
                connection.execute(
                    """INSERT INTO review_questions
                       (question_id, module_id, wrong_count, first_wrong_at,
                        last_wrong_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(question_id) DO UPDATE SET
                           wrong_count = MAX(wrong_count, excluded.wrong_count),
                           first_wrong_at = MIN(first_wrong_at, excluded.first_wrong_at),
                           last_wrong_at = MAX(last_wrong_at, excluded.last_wrong_at)""",
                    (item["question_id"], item["module_id"],
                     item["wrong_count"], item["first_wrong_at"],
                     item["last_wrong_at"]),
                )
                counts["review_questions"] += 1
            for item in data["daily_bonus"]:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO daily_bonus (day, xp, created_at)
                       VALUES (?, ?, ?)""",
                    (item["day"], item["xp"], item["created_at"]),
                )
                counts["daily_bonus"] += cursor.rowcount
        return counts

    @staticmethod
    def _insert_backup(connection, data: dict) -> dict:
        counts = {
            "attempts": 0,
            "question_awards": 0,
            "review_questions": 0,
            "daily_bonus": 0,
        }
        for item in data["attempts"]:
            connection.execute(
                """INSERT INTO attempts
                   (uid, session_id, question_id, module_id, day, created_at,
                    mode, answer, correct, score, xp_awarded, detail)
                   VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["uid"], item["question_id"], item["module_id"],
                    item["day"], item["created_at"], item["mode"], item["answer"],
                    item["correct"], item["score"], item["xp_awarded"],
                    item["detail"],
                ),
            )
            counts["attempts"] += 1
        for item in data["question_awards"]:
            connection.execute(
                """INSERT INTO question_awards (question_id, xp, day, created_at)
                   VALUES (?, ?, ?, ?)""",
                (item["question_id"], item["xp"], item["day"], item["created_at"]),
            )
            counts["question_awards"] += 1
        for item in data["review_questions"]:
            connection.execute(
                """INSERT INTO review_questions
                   (question_id, module_id, wrong_count, first_wrong_at, last_wrong_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    item["question_id"], item["module_id"], item["wrong_count"],
                    item["first_wrong_at"], item["last_wrong_at"],
                ),
            )
            counts["review_questions"] += 1
        for item in data["daily_bonus"]:
            connection.execute(
                "INSERT INTO daily_bonus (day, xp, created_at) VALUES (?, ?, ?)",
                (item["day"], item["xp"], item["created_at"]),
            )
            counts["daily_bonus"] += 1
        return counts
