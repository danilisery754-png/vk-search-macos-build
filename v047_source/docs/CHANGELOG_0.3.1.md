# Изменения v0.3.1

## Исправлено

- В PyInstaller bundle добавлены `backend/alembic.ini` и полный каталог `backend/alembic`, необходимые для создания чистой базы при первом запуске.
- Frozen `--self-test` больше не скрывает исключение: полный traceback сохраняется в `build/self-test-error.log` и показывается сборщиком.
- Двойной клик по `СОБРАТЬ_WINDOWS.cmd` больше не ломает сообщения после ошибки из-за несовместимости кодировок Windows CMD: управляющий CMD-файл теперь ASCII-only.
- Имена portable ZIP и installer обновлены до версии 0.3.1.

## Подтверждено

- Присланный журнал Windows Server 2019 подтверждает скачивание NuGet CPython 3.13.15, установку зависимостей, загрузку Chromium и полное создание PyInstaller onedir/EXE.
- Причина последнего отказа локализована непосредственно по пути frozen runtime и конфигурации Alembic, а исправление закреплено регрессионными тестами.
- Исходная сборка повторно проходит backend tests, frontend production build и desktop source self-test.

Финальный Windows EXE считается полностью подтверждённым только после повторного успешного запуска сборщика на Windows и последующей clean-VM проверки Windows 10/11.
