# VK Outreach Manager v0.4.0 — status

## Scope

v0.4.0 is a UI-stability, messaging-UX and per-run-history release built on the working v0.3.5 authorization baseline. The VK authorization/token capture and saved-session refresh flow is intentionally treated as a protected boundary.

## Implemented

- bounded desktop shell and styled internal scrollbars;
- compact unlimited message variants;
- simplified scalable account cards and functional `⋮` menu;
- automatic dialog sync, 300-message initial page, upward pagination and scroll-position preservation;
- fixed conversation header/composer, reply-account avatar/name/note, blocked-reply state and new-message affordance;
- persistent run summaries, original run group count and protected deletion of historical runs;
- strict result list/export filtering by `run_id`;
- shared result-run selector across success/failed screens;
- additive database migrations from the v0.3.5 schema.

## Verification so far

- Local backend full suite: **109 tests collected, 109 passed** on the Linux development environment after the v0.4.0 backend changes and migration regression.
- Protected v0.3.5 auth/token-refresh subset: **15 passed**.
- `test_migration_v035_to_v040.py`: passed against a manually constructed v0.3.5-shaped SQLite schema and Alembic revision marker `20260825_0001`.
- `backend/app/vk/auth.py`: unchanged from v0.3.5 baseline.
- Local frontend tests/build are not treated as verified yet because this container cannot reach `registry.npmjs.org` (`EAI_AGAIN`) and its partial `node_modules` tree cannot provide Vitest/Vite/type definitions. Frontend verification must therefore come from the Windows/GitHub CI run before release acceptance.

## Release gate still required

Before calling v0.4.0 complete, the Windows CI run must verify frontend tests/typecheck/build, backend tests, frozen EXE self-tests/browser self-tests, Inno Setup compilation and the final installer hash. Any Windows-only failures must be reported with exact counts rather than hidden behind an overall green workflow.
