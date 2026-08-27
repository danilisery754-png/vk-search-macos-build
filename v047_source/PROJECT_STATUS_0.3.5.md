# VK Outreach Manager v0.3.5 — status

## Scope of this release

v0.3.5 fixes the live VK authorization regression found in v0.3.4. The implementation is based on the known-good VKVIEWS authorization flow supplied by the user, not on the simplified OAuth-only flow from v0.3.4.

## Root causes fixed

1. v0.3.4 searched for an exact button named `Продолжить`; VK renders `Продолжить как <имя>`, so automation did not click it.
2. v0.3.4 mostly polled Playwright `page.url`. A token can already be visible in the browser address bar while that property lags, so the application could hang with a visible `access_token`.
3. v0.3.4 bypassed the known-good VKHost flow and went directly to a hard-coded OAuth URL.
4. Normal VK operations had no transparent saved-session refresh when a previously stored token expired.

## Current flow

Manual connect/update:

`https://vk.com/` → user signs in → `Я вошёл в VK` → `https://vkhost.github.io/` → exact `vk.com` → optional `Этот номер ещё ваш? / Да` → `Продолжить как…` / approval → token captured → `users.get` validation → encrypted storage.

Token capture sources are checked in parallel/fallback order: observed navigation/request URL, Playwright page URL, frame URLs, real `window.location.href`, Chrome DevTools target list.

If a newly captured token is already rejected by VK, the capture/validation cycle is repeated once automatically. If a stored token expires during later work, the account service attempts one automatic refresh from the saved browser profile and retries the VK operation once. If the saved session requires user interaction, the account is marked `requires_login` rather than looping forever.

## Regression coverage

Backend tests cover the real `Продолжить как <имя>` prefix, direct address token parsing, lagging `page.url`, navigation-event capture, CDP fallback, phone-number confirmation modal, explicit manual gate, rejected-token recapture, saved-session refresh, and routing of processor/inbox/worklist calls through the refresh wrapper.
