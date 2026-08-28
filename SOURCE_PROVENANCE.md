# VK Search 0.4.10 source provenance

This public build repository started from the exact VK Search 0.4.9 source snapshot:

- private source repository: `danilisery754-png/desktop-tutorial`
- v0.4.9 base commit: `45d96c6f2931bbeb346e82a1e136ea5c624002ff`
- base branch: `codex/vk-search-v049`

The v0.4.10 production source is transferred as the exact production-file diff from the repaired source:

- repaired source commit: `3371cf5aac87cf9471dd79bb243e2d3b2a91bf66`
- repaired branch: `codex/vk-search-v0410-repair`

Only product/production source changes are transferred into this public build repository. Private-repository CI, planning documents, and private CI-only tests are intentionally not copied. Protected sender/backend core files remain byte-for-byte equal to the v0.4.9 base; the only backend production changes are release-version metadata.

Public build branch: `vk-search-v0410-full`

Release: `v0.4.10`

Expected installer: `VK_Search_0.4.10_macOS_arm64.dmg`
