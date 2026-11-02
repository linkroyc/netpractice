# NetPractice для Android

Автономная обёртка на Kotlin + Chaquopy вокруг существующего Flask-приложения.
Бизнес-логика, шаблоны, статика, SQLite, `.nptpack` и JSON-резервные копии не
дублируются: Android-код только запускает Flask на loopback и открывает его в
WebView.

## Требования к сборке

- JDK 17;
- Android SDK 35: `platforms;android-35`, `build-tools;35.0.0`, `platform-tools`;
- Python 3.15 в `PATH` (Chaquopy использует его как build-Python);
- Gradle 8.9+ или wrapper из этого каталога.

Путь к SDK задаётся в `local.properties`:

```properties
sdk.dir=C:/Users/<user>/AppData/Local/Android/Sdk
```

Путь к Python при необходимости меняется в `app/build.gradle`:

```groovy
chaquopy {
    defaultConfig {
        buildPython 'C:/Python315/python.exe'
    }
}
```

## Сборка

```bat
gradlew.bat assembleDebug
```

Готовый файл:

```text
app/build/outputs/apk/debug/app-debug.apk
NetPractice-debug.apk
```

## Архитектура

- `MainActivity` — экран загрузки, обработка ошибок, системные insets и
  жизненный цикл.
- `PythonServer` — запускает Python/Chaquopy и Flask в фоновом потоке.
- `WebViewManager` — WebView, разрешает только `http://127.0.0.1:<port>`,
  блокирует внешние переходы и подресурсы.
- `FileManager` — SAF-диалоги для импорта и экспорта файлов.
- `app/src/main/python/android_entry.py` — выставляет `NETPRACTICE_DATA_DIR` и
  `TZ`, импортирует существующий `app.py`, поднимает `werkzeug.serving.make_server`
  на `127.0.0.1:0`.

Данные приложения находятся в app-private каталоге `files/netpractice/`:
`netpractice.db`, `secret_key`, `pending_packs/`. Доступа ко всей файловой
системе нет; импорт и экспорт идут через Storage Access Framework.

## Ограничения

- Поддерживаются только 64-битные ABI: `arm64-v8a` и `x86_64`.
- Текущий APK — debug, подписан debug-ключом. Для публикации нужен release
  keystore и отдельная release-сборка.
- Запуск на физическом устройстве и эмуляторе ещё не проверялся. На машине
  сборки не было подключённого устройства, а аппаратная виртуализация для
  x86_64-эмулятора недоступна.
- Встроенный Flask слушает только loopback; доступ по Wi-Fi с компьютера
  намеренно не включён.
