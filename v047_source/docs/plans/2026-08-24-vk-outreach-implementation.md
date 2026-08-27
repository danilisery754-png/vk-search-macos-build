# План реализации VK Outreach Manager

## 1. Каркас и воспроизводимость

- Создать Python/TypeScript workspace, фиксированные зависимости, конфигурацию и русскую документацию.
- Добавить единый data directory, структурированные логи и проверку окружения.
- Проверка: backend import, frontend typecheck, clean config test.

## 2. База и миграции

- Описать модели accounts, secrets, settings, communities, runs, work_items, attempts, results, inbox и logs.
- Добавить Alembic initial migration, WAL/foreign keys/busy timeout, repository boundary.
- Сначала тесты схемы, ограничений и отката транзакций.

## 3. Нормализация и импорт

- Сначала тесты грязного ввода, двух ссылок в строке, club/public/id, vk.com/vk.ru и dedupe.
- Реализовать parser и resolver boundary; сохранять исходный фрагмент и канонический URL.

## 4. Распределение и очередь

- Сначала acceptance tests 4×50=200, 120→30/30/30/30, отключённый аккаунт и concurrent claim.
- Реализовать shuffle + balanced round-robin, per-account counters, leases и atomic claim.

## 5. Результаты, retries и recovery

- Сначала tests частичного/полного успеха, полного отказа и временной ошибки.
- Реализовать attempt journal, outcome service, exponential backoff с jitter и reconcile state.

## 6. VK-слой

- Сначала mock contract tests метода, params, masking и error classifier.
- Реализовать API client, accounts, community resolver, message sender, suggested-post sender и inbox.
- Добавить `docs/VK_LIVE_REGISTRY.md` с состояниями NOT_TESTED/LIVE_OK/LIVE_FAIL.

## 7. Получение токена

- Перенести устойчивые идеи BrowserTokenAuthService в adapter нового приложения.
- Сначала тесты state machine, identity mismatch, 2FA pending, token masking и single-flight.
- Реализовать Edge-first persistent profile, bundled Chromium fallback и DPAPI secret store.

## 8. Внутренний API и supervisor

- REST: dashboard, accounts, groups, control, results, settings, logs, inbox, exports.
- WebSocket/SSE для событий и прогресса.
- Supervisor запускает по одному worker на аккаунт; pause/continue/stop корректно завершают текущее действие.

## 9. React UI

- Создать дизайн-систему, shell, sidebar/topbar и responsive desktop layout.
- Реализовать все восемь экранов, две независимые таблицы результатов и master-detail inbox.
- Добавить skeleton, toast, empty/error states, tooltips и виртуальные таблицы.

## 10. Экспорт и копирование

- Сначала сервисные tests TSV, selected rows, links-only, TXT/CSV/XLSX.
- Реализовать API download и Clipboard actions с точным количеством строк.

## 11. Windows shell и сборка

- Single instance, окно WebView2, tray, корректное завершение backend.
- PyInstaller onedir spec, portable zip, Inno Setup installer, shortcut и выбор сохранения данных при uninstall.
- Версионная информация, иконка, диагностический bundle без секретов.

## 12. Проверка

- Backend: pytest с coverage и race/recovery integration.
- Frontend: Vitest/Testing Library, typecheck, production build.
- Contract: mock VK server.
- Smoke: запуск packaged backend + health + UI assets.
- LIVE: авторизация и методы на реальных тестовых аккаунтах пользователя.
- Windows: чистые VM Windows 10 17763+ и Windows 11 x64.

