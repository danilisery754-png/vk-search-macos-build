# Статус проекта v0.3.3

## Подтверждено автоматическими проверками

- 83 backend unit/integration/contract tests;
- 7 frontend component/regression tests;
- чистая миграция SQLite через Alembic;
- atomic claim и concurrent race test;
- crash recovery без слепой повторной отправки;
- распределение и лимит на каждый аккаунт;
- partial/full outcome;
- маскирование токенов и identity mismatch;
- изоляция диалогов аккаунтов;
- `in_read`/`out_read`, `messages.markAsRead` и владелец токена диалога;
- независимая фоновая синхронизация входящих с изоляцией ошибок аккаунтов;
- single-flight открытия VK Messages в сохранённом профиле;
- TXT/TSV/CSV/XLSX export;
- FastAPI smoke;
- TypeScript typecheck;
- production Vite build;
- Python compileall.
- исправление HTTP 500 при запуске браузерной авторизации из FastAPI;
- один общий неограниченный список текстов для ЛС и предложки;
- один стабильный вариант текста на группу для обоих способов отправки;
- адаптивные карточки главного экрана и вкладки настроек без проваливания страницы вниз;

## Подготовлено, но требует Windows runner

- PyInstaller onedir;
- portable zip;
- Inno Setup installer;
- WebView2 bootstrapper;
- два автономных запуска `--self-test` и два `--browser-self-test` собранного EXE до упаковки;
- Alembic-конфигурация и все миграции включены в PyInstaller bundle;
- подробный traceback frozen self-test сохраняется и выводится сборщиком;
- GUI EXE не зависит от `stdout`/`stderr`: Uvicorn запускается без консольного formatter;
- UTF-8 BOM regression для Windows PowerShell 5.1 и Inno Setup на Windows 10;
- официальный переносимый Python 3.13.15 из NuGet с проверкой stdlib; системный Python и его переменные окружения игнорируются;
- one-click Windows build без Node.js и с остановкой на любом native error;
- Edge-first auth и bundled Chromium fallback;
- Windows 10 build 17763+ / Windows 11 x64 clean-VM checklist.

Сборка автоматизирована в `build/СОБРАТЬ_WINDOWS.cmd` и `.github/workflows/build-windows.yml`. Выдавать установщик разрешено только после четырёх frozen-проверок: два запуска приложения и два запуска встроенного браузера. Отдельная приёмка реального входа VK и методов API всё равно требует аккаунта пользователя.

## Требует реального VK-входа пользователя

Все строки `docs/VK_LIVE_REGISTRY.md`. До заполнения registry нельзя заявлять, что текущий токен VK фактически допускает ЛС, предложку и unified inbox именно на аккаунтах пользователя. Unit/mocks это не доказывают.
