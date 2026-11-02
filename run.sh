#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Первый запуск: создаю виртуальное окружение..."
    python3 -m venv .venv
fi

echo "Проверяю зависимости..."
. .venv/bin/activate
python -m pip install --disable-pip-version-check -q -r requirements.txt

echo
echo "Запускаю NetPractice. Откройте http://127.0.0.1:5000"
echo "Остановить сервер: Ctrl+C"
echo
exec python app.py
