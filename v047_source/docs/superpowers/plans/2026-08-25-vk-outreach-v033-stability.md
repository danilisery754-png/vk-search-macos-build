# VK Outreach Manager 0.3.3 Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a Windows 10/11 installer whose account authorization opens the packaged browser without HTTP 500, whose interface remains usable at supported window sizes, and whose two sending methods share an unlimited list of message variants.

**Architecture:** Keep the existing FastAPI/React/PyWebView architecture. Correct event-loop ownership at the API boundary, add backward-compatible JSON list settings and deterministic variant selection, replace settings anchors with local tabs, and extend the frozen executable with a packaged-browser self-test that the Windows workflow must pass before publishing.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy/SQLite, pytest, React 19, TypeScript, Vitest/Testing Library, Playwright Chromium, PyInstaller, Inno Setup, GitHub Actions Windows Server 2022.

**Spec:** `docs/superpowers/specs/2026-08-25-vk-outreach-v033-stability-design.md`

## Global Constraints

- Target Windows 10 and Windows 11 x64.
- Preserve all existing SQLite data, DPAPI-encrypted tokens, browser profiles, queues, results, and backups.
- Never expose passwords, 2FA codes, cookies, access tokens, or token-bearing URLs in errors or logs.
- Do not change VK sending limits, queue semantics, retry rules, account isolation, or result classification.
- A live VK login remains a user-operated acceptance check; CI must prove browser launch and the route/job machinery without user credentials.
- Release version is exactly `0.3.3`.

---

### Task 1: Establish a clean baseline

**Files:**
- Read: `backend/pyproject.toml`
- Read: `frontend/package.json`
- Read: `docs/superpowers/specs/2026-08-25-vk-outreach-v033-stability-design.md`

**Interfaces:**
- Consumes: existing source tree and dependency lock files.
- Produces: recorded baseline test output before code changes.

- [ ] **Step 1: Verify workspace isolation state**

Run:

```bash
git rev-parse --git-dir 2>/dev/null || true
git rev-parse --git-common-dir 2>/dev/null || true
git branch --show-current 2>/dev/null || true
```

Expected: the supplied project has no local Git metadata, so execution remains in this already isolated scratch workspace and no user branch can be modified.

- [ ] **Step 2: Run the backend baseline**

Run:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Expected: all existing backend tests pass.

- [ ] **Step 3: Run the frontend baseline**

Run:

```bash
npm test -- --run
npm run build
```

Working directory: `frontend`.

Expected baseline: Vitest reports `No test files found` because v0.3.2 contains no frontend tests; record this as the known starting state, then run the production build separately and require it to pass. Tasks 5 and 6 introduce the first frontend regression tests, after which `vitest run` must exit zero.

---

### Task 2: Fix authorization event-loop ownership

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/vk/auth.py`
- Modify: `backend/tests/test_api_smoke.py`
- Modify: `backend/tests/test_token_auth_service.py`

**Interfaces:**
- Consumes: `AccountService.start_authorization(account_id) -> AuthJob` and `AccountService.start_open_messages(account_id) -> BrowserJob`.
- Produces: async HTTP job-start endpoints and `BrowserLaunchError` with safe Russian text.

- [ ] **Step 1: Write failing API loop-context tests**

Add a controlled service whose start methods call `asyncio.get_running_loop()`:

```python
class LoopCheckingAccounts:
    def start_authorization(self, account_id=None):
        asyncio.get_running_loop()
        return AuthJob(id="auth-test")

    def start_open_messages(self, account_id):
        asyncio.get_running_loop()
        return BrowserJob(id="browser-test", account_id=account_id)
```

Inside `TestClient` lifespan, replace `app.state.services.accounts`, call both POST endpoints, and assert HTTP 202 plus the expected IDs.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_api_smoke.py -k "authorization_start or open_messages_start" -q
```

Expected: both calls fail with HTTP 500 because the current synchronous routes run in a worker thread without an event loop.

- [ ] **Step 3: Make both endpoints asynchronous**

Change only the route declarations:

```python
@router.post("/accounts/authorize", status_code=202)
async def authorize_account(...):
    ...

@router.post("/accounts/{account_id}/open-messages", status_code=202)
async def open_account_messages(...):
    ...
```

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2.

Expected: both tests pass with HTTP 202.

- [ ] **Step 5: Write a failing safe launch-error test**

Use a fake Playwright chromium object whose Edge and bundled launches both raise errors containing a fake token. Assert `_launch()` raises `BrowserLaunchError` whose text is Russian and does not contain the token or original URLs.

- [ ] **Step 6: Run the launch-error test and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_token_auth_service.py -k launch_error -q
```

Expected: failure because `BrowserLaunchError` and safe normalization do not yet exist.

- [ ] **Step 7: Implement safe browser fallback diagnostics**

Add:

```python
class BrowserLaunchError(AuthError):
    pass
```

Capture the Edge failure, attempt bundled Chromium, and if both fail raise a fixed Russian message naming the two launch paths and exception classes only. Chain the original exception without rendering its text.

- [ ] **Step 8: Run focused and full backend tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_api_smoke.py backend/tests/test_token_auth_service.py -q
.venv/bin/python -m pytest backend/tests -q
```

Expected: all pass without unawaited-coroutine warnings.

---

### Task 3: Add backward-compatible message variant settings

**Files:**
- Create: `backend/app/services/message_variants.py`
- Modify: `backend/app/services/settings.py`
- Create: `backend/tests/test_message_variants.py`

**Interfaces:**
- Produces: `normalize_variants(value: object, label: str) -> list[str]`.
- Produces: `select_variant(variants: object, *, work_item_id: int, direction: str = "outreach") -> str`.
- Produces canonical setting `message_texts: list[str]` while retaining both suggested-post and scalar keys as compatibility mirrors.

- [ ] **Step 1: Write failing normalization and migration tests**

Cover these behaviors:

```python
assert normalize_variants([" Первый ", "Второй"], "ЛС") == ["Первый", "Второй"]
```

- empty list and whitespace-only entries raise `ValueError`;
- a database containing different legacy DM and suggested-post texts merges both into `message_texts` without loss or duplicates;
- saving `message_texts` persists the shared list and mirrors it to both legacy directions;
- an arbitrary list of 250 non-empty entries is accepted, proving no count limit.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_message_variants.py -q
```

Expected: import or assertion failures because the module and list settings do not exist.

- [ ] **Step 3: Implement normalization and settings migration**

Add list defaults, normalize list updates before persistence, update legacy scalar counterparts, and use the set of stored database keys to decide whether legacy-to-list migration is needed in `all()`.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2.

Expected: all message-setting tests pass.

- [ ] **Step 5: Run settings API regression tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_api_smoke.py backend/tests/test_run_lifecycle.py -q
```

Expected: existing scalar settings remain compatible and all tests pass.

---

### Task 4: Select stable variants in the processor

**Files:**
- Modify: `backend/app/services/message_variants.py`
- Modify: `backend/app/services/processor.py`
- Modify: `backend/tests/test_message_variants.py`
- Modify: `backend/tests/test_processor.py`

**Interfaces:**
- Consumes: `select_variant(..., work_item_id=claimed.id, direction="message" | "suggested")`.
- Produces: stable text selection per work item and direction.

- [ ] **Step 1: Write failing deterministic selection tests**

Assert that the same work-item ID always returns the same string, different IDs cover more than one variant across a sample, and both processor directions receive exactly that same string.

- [ ] **Step 2: Write a failing processor retry-stability test**

Capture texts passed to `send_community_message` and `send_suggested_post`, process the same claimed item through a temporary retry and a second attempt, and assert both attempts use the same selected text for that direction.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_message_variants.py backend/tests/test_processor.py -q
```

Expected: failures because the processor still reads scalar settings.

- [ ] **Step 4: Implement deterministic SHA-256 selection**

Compute one shared index from:

```python
digest = hashlib.sha256(f"{work_item_id}:outreach".encode("utf-8")).digest()
index = int.from_bytes(digest[:8], "big") % len(normalized)
```

Select once per claimed item and use the same text in both processor directions without changing the surrounding retry or outcome logic. Keep the two VK calls sequential and independent.

- [ ] **Step 5: Run focused and full processor tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_message_variants.py backend/tests/test_processor.py -q
.venv/bin/python -m pytest backend/tests -q
```

Expected: all pass.

---

### Task 5: Replace settings anchors and build the variant editor

**Files:**
- Create: `frontend/src/components/SettingsTabs.tsx`
- Create: `frontend/src/components/MessageVariantsEditor.tsx`
- Create: `frontend/src/components/SettingsTabs.test.tsx`
- Create: `frontend/src/components/MessageVariantsEditor.test.tsx`
- Create: `frontend/src/test/setup.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- `SettingsTabs({ active, onSelect })` uses section type `'sending' | 'messages' | 'data' | 'extra'`.
- `MessageVariantsEditor({ label, values, onChange })` emits the one shared complete `string[]` after add, edit, delete, move up, or move down.

- [ ] **Step 1: Write failing tab component tests**

Render `SettingsTabs`, assert four buttons exist, no anchor exists, the active button has `aria-selected="true"`, and clicking `Сообщения` calls `onSelect('messages')`.

- [ ] **Step 2: Write failing variant editor tests**

Render with two variants and assert:

- `Добавить вариант` appends an empty textarea;
- editing emits the new complete list;
- move down swaps entries;
- delete removes an entry;
- delete is disabled when only one entry remains.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
npm test -- --run src/components/SettingsTabs.test.tsx src/components/MessageVariantsEditor.test.tsx
```

Working directory: `frontend`.

Expected: import failures because the components do not exist.

- [ ] **Step 4: Implement focused components**

Create accessible button-based tabs and a numbered variant editor with add/delete/up/down controls. Keep state ownership in `SettingsPage`.

- [ ] **Step 5: Integrate one-panel settings rendering**

Change the Settings type to include `string[]`, add `activeSection` state, replace all anchors, render only the chosen panel, show one shared editor for both delivery methods, and add the missing extra panel containing inbox sync interval and compact-interface checkbox.

- [ ] **Step 6: Add responsive styles**

Style `.settings-nav button`, `.message-variants`, `.message-variant`, and responsive tab/layout rules. Remove anchor-specific styles and avoid URL hashes entirely.

- [ ] **Step 7: Run tests and verify GREEN**

Run:

```bash
npm test -- --run
npm run typecheck
npm run build
```

Working directory: `frontend`.

Expected: all component tests, TypeScript checks, and production build pass.

---

### Task 6: Fix dashboard card responsiveness

**Files:**
- Create: `frontend/src/pages/DashboardPage.test.tsx`
- Modify: `frontend/src/pages/DashboardPage.tsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: existing six dashboard metrics.
- Produces: metric labels with a dedicated wrapping text container and responsive grid breakpoints.

- [ ] **Step 1: Write a failing dashboard markup test**

Render the page with controlled dashboard data and assert every metric card exposes a `.metric-copy` container and complete label text.

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
npm test -- --run src/pages/DashboardPage.test.tsx
```

Expected: failure because `.metric-copy` is absent.

- [ ] **Step 3: Implement markup and CSS correction**

Add the class, remove `white-space: nowrap`, allow wrapping, set `min-width: 0`, switch to three columns below 1550px and two columns below 1200px, and make page header controls wrap at the minimum supported width.

- [ ] **Step 4: Run the frontend suite**

Run:

```bash
npm test -- --run
npm run typecheck
npm run build
```

Expected: all pass.

---

### Task 7: Add packaged Chromium self-test

**Files:**
- Modify: `desktop/main.py`
- Modify: `backend/tests/test_desktop_entrypoint.py`
- Modify: `build/BUILD_WINDOWS.ps1`

**Interfaces:**
- Produces CLI flag: `--browser-self-test`.
- Consumes environment variable `VK_OUTREACH_SELF_TEST_LOG` for failure trace output.

- [ ] **Step 1: Write failing entrypoint tests**

Add tests for `is_browser_self_test(argv)` and for main dispatch to a patched `run_browser_self_test()` returning a known exit code.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_desktop_entrypoint.py -k browser -q
```

Expected: failures because the flag and dispatcher do not exist.

- [ ] **Step 3: Implement browser self-test**

After `configure_runtime()`, use `asyncio.run()` to launch bundled Playwright Chromium headlessly with a temporary persistent profile, navigate to a deterministic `data:` page, assert title/body content, close cleanly, and write traceback through the existing self-test log path on failure.

- [ ] **Step 4: Extend the Windows build script**

After PyInstaller completes, invoke the packaged GUI executable twice with `--self-test` and twice with `--browser-self-test`. Give each invocation its own log path, require exit code zero, and display the log before throwing on failure.

- [ ] **Step 5: Run source-level entrypoint regression**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_desktop_entrypoint.py -q
.venv/bin/python desktop/main.py --browser-self-test
```

Expected: tests pass and the local bundled-browser check exits zero.

---

### Task 8: Version, documentation, and clean verification

**Files:**
- Modify: `backend/app/__init__.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/pyproject.toml`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `build/BUILD_WINDOWS.ps1`
- Modify: `build/installer.iss`
- Modify: `README.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `BUILD_REPORT.md`
- Create: `docs/CHANGELOG_0.3.3.md`
- Modify: `docs/REQUIREMENTS_COVERAGE.md`
- Modify: `docs/TEST_MATRIX.md`

**Interfaces:**
- Produces application and installer version `0.3.3` everywhere.

- [ ] **Step 1: Update version-bearing files**

Replace application-owned `0.3.2` references with `0.3.3`; do not alter third-party dependency versions containing the same digits.

- [ ] **Step 2: Document exact fixes and honest verification boundary**

Record the event-loop root cause, tab behavior, list migration, deterministic variants, responsive cards, packaged browser tests, and the remaining user-operated live VK login check.

- [ ] **Step 3: Run the complete local verification**

Run:

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m compileall -q backend/app desktop
.venv/bin/python -m pip check
npm test -- --run
npm run typecheck
npm run build
```

Run frontend commands from `frontend`.

Expected: every command exits zero.

- [ ] **Step 4: Create and verify a clean source archive**

Archive the source without `.venv`, `node_modules`, build outputs, caches, databases, profiles, or tokens. Extract it into a temporary directory, install only from lock/metadata, and repeat backend tests plus frontend build there.

Expected: clean extraction passes without relying on the working tree.

---

### Task 9: Build and validate the Windows installer

**Files:**
- Create artifact: `VK_Outreach_Manager_Setup_0.3.3.exe`
- Create artifact: `VK_Outreach_Manager_Setup_0.3.3.sha256.txt`

**Interfaces:**
- Consumes: clean v0.3.3 source archive and isolated Windows Server 2022 build branch.
- Produces: verified installer and checksum.

- [ ] **Step 1: Upload only the isolated v0.3.3 build branch**

Create a new branch for v0.3.3 in the connected private build repository. Do not modify its main branch or the prior v0.3.2 branch.

- [ ] **Step 2: Run Windows Server 2022 build**

The workflow reconstructs the clean source, invokes `build/BUILD_WINDOWS.ps1`, and uploads only the installer artifact with no compression.

Expected: workflow succeeds only after both application self-tests and both browser self-tests pass.

- [ ] **Step 3: Download and validate artifact integrity**

Verify workflow artifact digest, ZIP integrity, `MZ` executable header, Windows PE file type, exact filename, and SHA-256.

- [ ] **Step 4: Save final deliverables**

Save the installer and checksum as user-facing Library artifacts, preserving the local verified copies.

- [ ] **Step 5: Report verified and unverified boundaries**

State the test counts, Windows build evidence, self-test counts, SHA-256, and that only the user's real VK login/2FA remains as live acceptance because credentials are never collected.
