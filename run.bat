@echo off
setlocal
cd /d "%~dp0"
title NetPractice

set "PYTHON=python"
where py >nul 2>nul && set "PYTHON=py -3"

if not exist ".venv\Scripts\python.exe" (
    echo Первый запуск: создаю виртуальное окружение...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto error
)

echo Проверяю зависимости...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto error

echo.
echo Запускаю NetPractice. Откройте http://127.0.0.1:5000
echo Остановить сервер: Ctrl+C
echo.
".venv\Scripts\python.exe" app.py
goto end

:error
echo.
echo Не удалось запустить приложение.
echo Установите Python 3.11 или новее с python.org и повторите запуск.
pause

:end
endlocal
