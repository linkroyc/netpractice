"""Frontend regression tests for the start-button loading guard.

The behavioral test runs app.js in an installed Chrome via ``--dump-dom`` and
is skipped when Chrome is not available. No Node.js or external browser
automation package is required.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app import create_app

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "js" / "app.js"


def find_chrome():
    candidates = [
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


@pytest.fixture
def client(tmp_path):
    app = create_app(
        db_path=tmp_path / "frontend.db", secret_key="test-secret"
    )
    app.config.update(TESTING=True)
    return app.test_client()


def test_start_forms_are_marked(client):
    assert client.get("/").get_data(as_text=True).count("data-start-form") >= 1
    assert "data-start-form" in client.get("/learn").get_data(as_text=True)
    assert "data-start-form" in client.get("/learn").get_data(as_text=True)


def test_app_js_has_loading_and_bfcache_contract():
    source = APP_JS.read_text(encoding="utf-8")
    assert 'addEventListener("pageshow"' in source
    assert "aria-busy" in source
    assert "is-loading" in source
    assert "LOADING_TIMEOUT_MS" in source
    assert "Запускаю…" in source
    assert "Сервер не ответил" in source
    assert "fetch(" not in source
    assert ".submit()" not in source
    assert "window.confirm" not in source
    assert "backup-import-toggle" in source
    assert "aria-expanded" in source


@pytest.fixture(scope="module")
def browser_result(tmp_path_factory):
    chrome = find_chrome()
    if not chrome:
        pytest.skip("Chrome не найден: поведенческий тест интерфейса пропущен")

    tmp = Path(tempfile.mkdtemp(
        prefix="np-frontend-", dir=str(tmp_path_factory.getbasetemp())
    ))
    shutil.copy(APP_JS, tmp / "app.js")

    harness = """<!doctype html>
<meta charset="utf-8">
<form id="f" method="post" action="/daily/start" data-start-form>
  <button id="b" type="submit">Начать занятие</button>
</form>
<pre id="out">pending</pre>
<script src="app.js"></script>
<script>
window.__submits = 0;
window.__programmatic = 0;
HTMLFormElement.prototype.submit = function () { window.__programmatic += 1; };
document.addEventListener("submit", function (event) {
  window.__submits += 1;
  event.preventDefault();
});
var results = {};
function snapshot() {
  var form = document.getElementById("f");
  var button = document.getElementById("b");
  var error = document.querySelector("[data-submit-error]");
  return {
    guard: form.dataset.submitting || null,
    text: button.textContent,
    busy: button.getAttribute("aria-busy"),
    disabled: button.getAttribute("aria-disabled"),
    loading: button.classList.contains("is-loading"),
    error: error ? error.textContent : null,
    submits: window.__submits,
    programmatic: window.__programmatic
  };
}
window.addEventListener("load", function () {
  setTimeout(function () {
    document.getElementById("b").click();
    results.first = snapshot();
    document.getElementById("b").click();
    document.getElementById("b").click();
    document.getElementById("b").click();
    results.retries = snapshot();
  }, 100);
  setTimeout(function () {
    results.timeout = snapshot();
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    results.pageshow = snapshot();
    document.getElementById("out").textContent = JSON.stringify(results);
  }, 16000);
});
</script>"""

    (tmp / "harness.html").write_text(harness, encoding="utf-8")
    command = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        f"--user-data-dir={tmp / 'profile'}",
        "--allow-file-access-from-files",
        "--virtual-time-budget=17500",
        "--dump-dom",
        (tmp / "harness.html").as_uri(),
    ]
    if sys.platform.startswith("linux"):
        command.insert(1, "--no-sandbox")
        command.insert(2, "--disable-dev-shm-usage")

    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    match = re.search(r'<pre id="out">(.*?)</pre>', completed.stdout, re.S)
    assert match, completed.stdout[-2000:]
    return json.loads(html.unescape(match.group(1)))


def test_loading_state_and_aria(browser_result):
    first = browser_result["first"]
    assert first["guard"] == "1"
    assert first["text"] == "Запускаю…"
    assert first["busy"] == "true"
    assert first["disabled"] == "true"
    assert first["loading"] is True
    assert first["error"] is None


def test_repeated_clicks_are_blocked(browser_result):
    retries = browser_result["retries"]
    assert retries["submits"] == 4  # первый клик и три повторных submit
    assert retries["guard"] == "1"
    assert retries["programmatic"] == 0


def test_timeout_shows_error_without_auto_resubmit(browser_result):
    timeout = browser_result["timeout"]
    assert timeout["guard"] is None
    assert "Сервер не ответил" in timeout["error"]
    assert timeout["text"] == "Начать занятие"
    assert timeout["loading"] is False
    assert timeout["programmatic"] == 0
    assert timeout["submits"] == 4


def test_pageshow_resets_bfcache_state(browser_result):
    pageshow = browser_result["pageshow"]
    assert pageshow["guard"] is None
    assert pageshow["error"] is None
    assert pageshow["text"] == "Начать занятие"
    assert pageshow["loading"] is False
    assert pageshow["busy"] is None
    assert pageshow["disabled"] is None
