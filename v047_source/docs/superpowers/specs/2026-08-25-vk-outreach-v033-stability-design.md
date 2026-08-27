# VK Outreach Manager 0.3.3 Stability Design

## Goal

Release a Windows 10/11 installer in which account authorization starts a usable browser window instead of returning HTTP 500, the dashboard and settings remain usable at the minimum supported window size, and one shared unlimited text list is used for both delivery directions.

## Confirmed causes

1. `POST /api/accounts/authorize` and `POST /api/accounts/{id}/open-messages` are synchronous FastAPI routes, but both call service methods that use `asyncio.create_task()`. FastAPI executes synchronous routes in a worker thread without a running event loop, which produces the immediate HTTP 500 seen by the user.
2. Settings navigation uses document anchors such as `href="#messages"`. The scrollable element is `.workspace main`, so anchor navigation scrolls the whole settings page and moves the header and earlier content out of view. The fourth link targets `#extra`, but no matching section exists.
3. Dashboard metric labels use `white-space: nowrap`, while the six-column layout remains active at widths where the workspace is already narrowed by the sidebar.
4. Message settings are stored as two scalar strings, so the UI and processor cannot represent multiple variants.

## Authorization design

- Convert both job-start routes to `async def`, ensuring `asyncio.create_task()` is called on FastAPI's active event loop.
- Preserve the existing manual VK login flow: the app opens a separate persistent Playwright browser profile; the user enters login, password, 2FA, or captcha directly in VK; the application never asks for those credentials in its own UI.
- Keep Edge-first launch with bundled Playwright Chromium fallback. Failure to find or start Edge must not prevent the bundled browser from opening.
- Normalize launch failures into a safe Russian diagnostic that identifies whether the browser executable, profile directory, navigation, timeout, or VK validation failed. Tokens, cookies, URLs containing tokens, and credentials must never appear in UI errors or logs.
- Add an installed-build browser self-test. It launches the packaged Chromium with a temporary profile, opens a local deterministic page, verifies the page, closes the context, and exits with a nonzero code plus a log file on failure.
- The Windows build workflow must run both the existing application self-test and the new browser self-test against the packaged executable before it uploads an installer.
- A unit/integration regression test must call the authorization endpoint and prove it returns HTTP 202 from FastAPI instead of raising “no running event loop”. It will use a controlled account-service double and will not open a real browser.

## Settings navigation design

- Replace the four anchor links with accessible buttons acting as tabs.
- Render one active settings panel at a time: `Рассылка`, `Сообщения`, `Данные и экспорт`, or `Дополнительно`.
- Clicking a tab changes local UI state and resets the settings content to its natural top without changing the URL hash or scrolling the application shell.
- Add the previously missing `Дополнительно` panel and place the already-supported `inbox_sync_seconds` and `interface_compact` settings there. No unrelated settings are introduced.
- At narrower workspace widths the tabs become a horizontal wrapping row above the panel so the content retains usable width.

## Message variants design

- Introduce canonical `message_texts: list[str]`, stored as JSON using the existing key/value settings table. No database schema migration is required. The old suggested-post keys remain compatibility mirrors of the shared list.
- Preserve backward compatibility: when the shared list does not yet exist, merge the existing `message_text`, `suggested_post_text`, and any legacy list values in their saved order while removing exact duplicates. Saving the new settings mirrors its first variant into both legacy scalar keys and the full list into both legacy list keys so older backups and code remain readable.
- Each list must contain at least one non-empty string. Empty entries are rejected with a precise validation message. A high accidental-payload guard may be applied, but there is no user-facing count limit.
- The UI shows one shared editor with numbered variant cards, textarea editing, `Добавить вариант`, `Удалить`, and move-up/move-down controls. The only remaining entry cannot be deleted.
- The processor selects one variant deterministically from the work-item ID. The same selected text is used for both the community DM and the suggested post for that group. Different groups are distributed across variants, while retries reuse the same variant.
- The processor attempts both directions for the same assigned account whenever each direction is not already final. A closed or failed DM must not suppress the suggested-post attempt, and a closed or failed suggested post must not undo a successful DM. Calls remain sequential to respect VK API rate limits.
- Existing processing behavior, retry rules, queue ownership, delays, account isolation, and result classification remain unchanged.

## Responsive dashboard design

- Use three metric columns at the user's demonstrated window width and two columns near the minimum supported width.
- Allow labels to wrap, give their text container `min-width: 0`, and keep numbers and icons readable.
- Preserve the six-column layout only when the workspace is genuinely wide enough.
- Add responsive rules for page headers, controls, settings grids, and backup rows so no horizontal clipping is introduced by the new message editor.

## Data and compatibility

- Existing SQLite databases, encrypted DPAPI tokens, browser profiles, queues, results, and backups are reused in place.
- The installer upgrades version 0.3.2 to 0.3.3 without requiring a PC restart.
- Browser profiles remain separate per VK account. Reauthorization for an existing account continues to verify that the same VK user signed in.

## Verification and release criteria

1. Backend unit and integration tests pass, including authorization route regression, settings migration/validation, deterministic variant selection, and retry stability.
2. Frontend component tests pass for tab navigation and unlimited add/remove/reorder behavior.
3. Frontend production build and Python compile checks pass.
4. A clean source extraction passes all tests.
5. The Windows packaged executable passes application self-test twice.
6. The Windows packaged executable passes bundled-browser self-test twice.
7. The installer is produced on Windows Server 2022, its SHA-256 is recorded, and the executable header is validated.
8. A live VK credential entry is not automated in CI. Final end-to-end confirmation after delivery is: the user opens the installed app, clicks `Подключить аккаунт`, signs in directly in the browser, completes any 2FA/captcha, and sees the account appear. This is the only check that requires the user's VK session.

## Explicit non-goals

- No password, 2FA code, cookie, or token is requested through chat or stored unencrypted.
- No change to VK sending limits, queue semantics, result tables, inbox ownership, or other project subsystems.
- No dependency on restarting Windows for authorization.
