# Покрытие мастер-промпта

Статусы:

- `TESTED` — реализовано и проверено автоматическими тестами или production build;
- `IMPLEMENTED` — реализовано, но требует проверки на целевой Windows;
- `LIVE_NOT_TESTED` — код и контракт есть, однако нужен реальный VK-аккаунт;
- `LIMITATION` — внешнее ограничение явно зафиксировано, догадка не выдаётся за готовность.

| Требование | Статус | Реализация и проверка |
|---|---|---|
| Отдельное Windows-приложение без PyCharm | IMPLEMENTED | pywebview, single instance, tray, PyInstaller onedir, Inno Setup, portable ZIP |
| Windows 10/11 x64 | IMPLEMENTED | build 17763+, обязательная clean-VM матрица в `TEST_MATRIX.md` |
| Сборка без системного Python/Node.js | TESTED | официальный NuGet CPython 3.13.15, очищаются `PYTHONHOME/PYTHONPATH`, готовый `frontend/dist` |
| Автоматическое получение токена | LIVE_NOT_TESTED | отдельный persistent Edge/Chromium profile, перехват OAuth redirect, `users.get` validation |
| Защита токенов и профилей | TESTED | Windows DPAPI, отдельный профиль на аккаунт, маскирование секретов, удаление токена и профиля |
| Несколько независимых аккаунтов | TESTED | токены, cookies, сообщения, результаты и задачи привязаны к `account_id` |
| Панель аккаунтов и диагностика | TESTED | имя/заметка, аватар, auth/API/session/work, назначено/обработано/unread, последнее действие и ошибка |
| Один общий грязный список групп | TESTED | URL/ID/текст, нормализация, canonical URL, dedupe внутри прохода |
| Повторная загрузка группы в новом проходе | TESTED | уникальность `(run_id, community_id)`, история предыдущего прохода сохраняется |
| Лимит на каждый аккаунт | TESTED | 4×50=200, 120→30/30/30/30 |
| Случайное сбалансированное распределение | TESTED | детерминированный seed прохода, capacity каждого аккаунта |
| Одна группа — один аккаунт | TESTED | атомарный SQLite `BEGIN IMMEDIATE`, конкурентный race test |
| Пауза / продолжение / остановка | TESTED | новые задачи не стартуют на паузе; остановленный проход можно безопасно запустить снова |
| Перераспределение отключённого аккаунта | TESTED | не начатые задачи возвращаются в общий пул |
| Crash recovery и отсутствие слепого дубля | TESTED | leases, attempt journal, deterministic `random_id`, ambiguous result → reconcile |
| Контролируемые retry/backoff | TESTED | bounded exponential retry, auth pause, final/temporary/unknown классификация |
| ЛС сообществу | LIVE_NOT_TESTED | `messages.send`, `peer_id=-group_id`, отдельный результат и причина |
| Предложенная запись | LIVE_NOT_TESTED | `wall.post`, `owner_id=-group_id`, отдельный результат и причина |
| Один общий текст для обоих способов | TESTED | один стабильный вариант выбирается на группу и без изменений используется для ЛС и предложки; список вариантов не ограничен фиксированным числом |
| Итог при частичном успехе | TESTED | оба направления пробуются независимо и последовательно; успех, если сработало ЛС или предложка; оба результата сохраняются |
| Завершённые группы уходят из активного списка | TESTED | active query исключает `success/failed`, история и результаты остаются |
| Два независимых экрана результатов | TESTED | отдельные API и React routes success/failed |
| Поиск, сортировка, фильтры, select all | TESTED | группы, результаты, логи и inbox; результатная таблица виртуализирована |
| Изменение ширины колонок | TESTED | drag resize в результатах, native resize в рабочем списке |
| Копирование таблицы/выбранного/ссылок | TESTED | TSV clipboard и чистые ссылки без заголовка |
| TXT/CSV/XLSX экспорт | TESTED | все/выбранные, отдельные колонки ЛС/предложка/назначение/аккаунт/причина |
| Полная история группы | TESTED | карточка результата открывает итог, попытки, VK object IDs и технические события |
| Единый inbox | TESTED | фильтр аккаунта, all/read/unread, поиск, сворачиваемые группы аккаунтов |
| Ответ правильным аккаунтом | TESTED | dialog owner определяет токен, отдельный isolation test |
| Непрочитанные и прочтение | TESTED | `in_read/out_read`, `messages.markAsRead`, per-account counters |
| Фоновая синхронизация inbox | TESTED | отдельный worker независимо от состояния рассылки, изоляция ошибок аккаунтов |
| Browser fallback сообщений | LIVE_NOT_TESTED | открытие `/im` в сохранённом профиле конкретного аккаунта |
| Настройки без повторного ввода | TESTED | лимит, задержки fixed/random, retries, общий список текстов, inbox interval; вкладки не меняют scroll/hash |
| SQLite, WAL, migrations, backup | TESTED | Alembic, FK, индексы, startup/manual backup, retention |
| Пользовательские и технические логи | TESTED | отдельное сообщение + раскрываемый redacted JSON |
| Неблокирующий UI | TESTED | фоновые worker-задачи, короткие транзакции, polling, React Query |
| Реальная работоспособность методов VK | LIVE_NOT_TESTED | обязательный реестр `VK_LIVE_REGISTRY.md`; нужен вход пользователя |
| Готовый EXE на Windows 10/11 | IMPLEMENTED | Windows-сборка обязана дважды пройти `--self-test` и дважды `--browser-self-test` до создания установщика; clean-VM приёмка на обеих ОС остаётся отдельным ручным этапом |

## Релизное правило

Нельзя менять `LIVE_NOT_TESTED` или `LIMITATION` на готовность без фактического запуска. Финальная Windows-сборка считается принятой только после:

1. успешного `--self-test` собранного EXE;
2. запуска portable и installer на Windows 10 и Windows 11 x64;
3. заполнения строк `VK_LIVE_REGISTRY.md` на тестовых VK-аккаунтах;
4. контрольного прохода: импорт → распределение → ЛС/предложка → результаты → inbox → перезапуск без дубля.
