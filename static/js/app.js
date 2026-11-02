/* Минимальный JavaScript: индикатор отправки, защита от повторов и bfcache. */
(function () {
  "use strict";

  var LOADING_TIMEOUT_MS = 15000;
  var LOADING_TEXT = "Запускаю…";
  var TIMEOUT_TEXT = "Сервер не ответил за 15 секунд. Проверьте, что приложение запущено, и попробуйте снова.";

  function isStartForm(form) {
    return form.hasAttribute("data-start-form");
  }

  function clearError(form) {
    if (form._errorNode) {
      if (form._errorNode.parentNode) {
        form._errorNode.parentNode.removeChild(form._errorNode);
      }
      form._errorNode = null;
    }
    var next = form.nextElementSibling;
    if (next && next.hasAttribute && next.hasAttribute("data-submit-error")) {
      next.parentNode.removeChild(next);
    }
  }

  function showError(form, message) {
    clearError(form);
    var error = document.createElement("p");
    error.className = "form-error";
    error.setAttribute("data-submit-error", "");
    error.setAttribute("role", "alert");
    error.textContent = message;
    form.insertAdjacentElement("afterend", error);
    form._errorNode = error;
  }

  function resetForm(form) {
    if (form._loadingTimer) {
      window.clearTimeout(form._loadingTimer);
      form._loadingTimer = null;
    }
    delete form.dataset.submitting;
    form.removeAttribute("aria-busy");
    clearError(form);

    var buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    for (var index = 0; index < buttons.length; index += 1) {
      var button = buttons[index];
      button.classList.remove("is-loading");
      button.removeAttribute("aria-busy");
      button.removeAttribute("aria-disabled");
      if (button.dataset.originalLabel !== undefined) {
        if (button.tagName === "INPUT") {
          button.value = button.dataset.originalLabel;
        } else {
          button.textContent = button.dataset.originalLabel;
        }
        delete button.dataset.originalLabel;
      }
    }
  }

  function startLoading(form, submitter) {
    form.setAttribute("aria-busy", "true");
    clearError(form);

    var button = submitter;
    if (!(button instanceof HTMLButtonElement) && !(button instanceof HTMLInputElement)) {
      button = form.querySelector('button[type="submit"], input[type="submit"]');
    }
    if (!button) {
      return;
    }

    button.setAttribute("aria-busy", "true");
    button.setAttribute("aria-disabled", "true");
    if (button.dataset.originalLabel === undefined) {
      button.dataset.originalLabel =
        button.tagName === "INPUT" ? button.value : button.textContent;
    }
    if (button.tagName === "INPUT") {
      button.value = LOADING_TEXT;
    } else {
      button.textContent = LOADING_TEXT;
    }
    button.classList.add("is-loading");
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }

    if (form.dataset.submitting === "1") {
      event.preventDefault();
      return;
    }

    form.dataset.submitting = "1";

    // Если навигация не началась, через 15 секунд возвращаем форму
    // в рабочее состояние и показываем ошибку. Автоповтора POST нет.
    form._loadingTimer = window.setTimeout(function () {
      form._loadingTimer = null;
      if (!form.isConnected || form.dataset.submitting !== "1") {
        return;
      }
      resetForm(form);
      showError(form, TIMEOUT_TEXT);
    }, LOADING_TIMEOUT_MS);

    if (isStartForm(form)) {
      startLoading(form, event.submitter);
    }
  });

  // bfcache восстанавливает DOM вместе с data-submitting. Сбрасываем
  // состояние при любом pageshow, чтобы кнопка не оставалась заблокированной.
  window.addEventListener("pageshow", function () {
    var forms = document.querySelectorAll("form");
    for (var index = 0; index < forms.length; index += 1) {
      resetForm(forms[index]);
    }
    updateBackupButtons();
  });

  var backupToggle = document.getElementById("backup-import-toggle");
  var backupPanel = document.getElementById("backup-import-panel");
  var backupFile = document.getElementById("backup-file");
  var backupButtons = document.querySelectorAll("[data-backup-submit]");

  function updateBackupButtons() {
    var selected = !!(backupFile && backupFile.files && backupFile.files.length);
    for (var index = 0; index < backupButtons.length; index += 1) {
      backupButtons[index].disabled = !selected;
    }
  }

  if (backupToggle && backupPanel) {
    backupToggle.addEventListener("click", function () {
      var opening = backupPanel.hidden;
      backupPanel.hidden = !opening;
      backupToggle.setAttribute("aria-expanded", opening ? "true" : "false");
      if (opening && backupFile) {
        backupFile.focus();
      }
    });
  }

  if (backupFile) {
    backupFile.addEventListener("change", updateBackupButtons);
    updateBackupButtons();
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {
        /* Установка на главный экран работает и без service worker. */
      });
    });
  }
})();
