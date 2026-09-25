# Project context

This file records durable human and product context. For the current technical
checkpoint and roadmap, read `docs/PROJECT_STATE.md`.

## User and environment

- Primary platform: Arch Linux.
- The user prefers lightweight keyboard-first Linux CLI/TUI tools and uses MPD
  with rmpc.
- The user can run documented commands but should not need Python knowledge or
  internal terms such as job UUIDs, SYLT frames, or state records.
- Defaults and error messages should be safe, direct, and understandable.

The usual local collection is under `~/Music/Juice WRLD`, but every path is
configurable. Automated work must never touch the user's real library or XDG
state. Tests use temporary HOME/XDG roots.

## Product identity

- Product and primary executable: `999`
- Legacy executable: `juice-lyrics`
- Python package: `juice_lyrics`
- Distribution: `juice-wrld-lyrics`
- Existing storage namespace: `juice-lyrics`

The internal and storage names intentionally remain stable. Do not create a
second `999` state tree or silently migrate user data.

## Product principles

The core download journey is:

```text
Browse → Add → Downloads → Download queue → Done
```

The normal local-library action is Library → `s` → **Sync Library**.

```text
common safe routine work → automatic/simple
ambiguous/destructive work → explicit user decision
```

Keep the TUI simpler than the CLI. The CLI remains useful for scripting,
diagnostics, and unusual recovery. Do not replace MPD/rmpc with a custom player.

## Durable safety decisions

- Preserve embedded lyrics and adjacent synchronized `.lrc` files.
- Never invent timestamps or treat untimed text as synchronized lyrics.
- Never convert MP3, FLAC, or M4A audio.
- The finalized audio path controls the sidecar path; deprecated `lyrics_dir`
  cannot redirect new writes.
- Back up before in-place media metadata mutation and verify afterward.
- Keep the newest 10 valid backups and preserve historical restore manifests.
- Matching is conservative: wrong confident identity is worse than Unknown.
- Normal startup and Library Sync never rewrite rmpc configuration.
- Acquisition is explicit; adding to the queue does not start downloading.

Detailed architecture, decisions, user behavior, and history live in
`docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/USER_GUIDE.md`, and
`docs/CHANGELOG.md`.
