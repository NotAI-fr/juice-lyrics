# 999 v2 continuity brief

This file is retained for old links and session prompts. It is no longer a
second full project-history document.

Use this handoff order:

1. `../AGENTS.md` — concise operating and safety instructions
2. `PROJECT_STATE.md` — canonical current checkpoint and roadmap
3. `../PROJECT_CONTEXT.md` — durable user/product context
4. Relevant design documents in `docs/`

## Current checkpoint

`999` is a Linux terminal music hub on branch `v2-redesign`. The primary
executable is `999`; `juice-lyrics` remains a compatibility alias, the Python
package remains `juice_lyrics`, and XDG data remains under `juice-lyrics`.

At commit `31ebaf2 Add one-button Library Sync`, MP3/FLAC/M4A local-library
support, adjacent LRC architecture, catalogue browsing/matching, downloads,
backups/restore, rmpc integration, the five-section TUI, Help/confirmation
polish, identity rebuild/state cleanup, performance safeguards, and one-button
incremental Library Sync are integrated. That checkpoint passed 410 tests plus
14 isolated recovery smoke tests, compileall, and `git diff --check`.

The normal Library action is `s` → **Sync Library**. It detects unchanged, new,
changed, and removed files; avoids redundant work for unchanged files; safely
backfills confident Unknown identities; retires removed entries; stays usable
offline; and does not modify audio, lyrics, backups, downloads, or rmpc config.

The next roadmap item is manual catalogue matching with an explicit identity
lock. The complete ordered roadmap, known limitations, safety invariants, and
resume commands are maintained only in `PROJECT_STATE.md`.
