# VK Search 0.4.9 — macOS ARM64 build

Clean public build snapshot for the frozen VK Search 0.4.9 source candidate.

- Original private source commit: `45d96c6f2931bbeb346e82a1e136ea5c624002ff`
- Target: Apple Silicon Macs (M1/M2/M3/M4)
- Output: `VK_Search_0.4.9_macOS_arm64.dmg`
- Verification: backend tests, frontend tests/typecheck/build, PyInstaller app self-tests, ARM64 inspection, ad-hoc codesign verification, DMG verification and SHA-256.

The GitHub Release is created only after every verification step succeeds.
