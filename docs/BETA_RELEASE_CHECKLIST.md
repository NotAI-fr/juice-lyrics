# 999 beta release checklist

Target: `2.0.0b1` (PEP 440) / Git tag `v2.0.0b1`.

This checklist prepares a release; it does not authorize publishing, tagging,
or merging. `main` remains the stable v1.4 baseline until the beta is accepted.

## 1. Repository and metadata

- [ ] `v2-redesign` is clean, pushed, and reviewed against `main`.
- [ ] `juice_lyrics.__version__`, `999 --version`, wheel metadata, and the
      changelog all say `2.0.0b1`.
- [ ] The changelog heading has the actual release date instead of
      `Unreleased`.
- [ ] README installation commands point to the intended immutable tag or
      attached wheel, not the moving development branch. Before any package-
      index publication, give its long description an immutable public image
      URL or omit the screenshot there.
- [ ] The synthetic screenshot contains no username, home path, token, state,
      song list, or real-library data.
- [ ] Distribution contents contain the license, README, metadata, and every
      runtime module, with no tests, caches, secrets, or checkout paths.

## 2. Automated release candidate checks

Run from a clean checkout with isolated build and application paths:

```bash
pytest -q
python -m compileall -q src
git diff --check
python -m build
```

- [ ] Full test suite passes with only understood environment skips.
- [ ] Wheel and sdist install independently in new environments outside the
      checkout, with no source tree on `PYTHONPATH`.
- [ ] `999 --help`, `999 --version`, `juice-lyrics --version`, and
      `999 doctor` work from both artifacts.
- [ ] TUI launches and exits from both artifacts.
- [ ] Bash/Zsh/Fish completion generation succeeds; syntax is checked where
      the shell is installed.
- [ ] Force-reinstall, uninstall, and reinstall leave the commands and imports
      in the expected state without touching application XDG data.
- [ ] The GitHub `Verify` workflow passes on supported oldest/current Python
      versions for the release pull request.

## 3. GitHub presentation settings

- [x] Keep `main` as the default/stable branch until the beta pull request is
      approved; do not point normal users at an unreviewed branch.
- [x] Set the repository description to “999 — a cautious Juice WRLD library
      and lyrics TUI for Linux”.
- [x] Add concise topics such as `linux`, `python`, `tui`, `music-library`,
      `lyrics`, `mpd`, and `rmpc`.
- [x] Confirm Issues are enabled and the repository license is detected as MIT.
- [ ] Decide explicitly when the currently private repository should become
      public; do not change visibility as a side effect of release prep.
- [ ] Preview README links and the synthetic screenshot on GitHub before merge.

## 4. Manual beta acceptance

Use an explicit backup and a small temporary copy of representative media
before testing any mutating workflow.

- [ ] Launch, Help, navigation, Browse search/pagination/details, queue Add,
      Downloads, Retry, and confirmed Download queue work.
- [ ] Sync Library handles unchanged/new/changed/removed files and remains
      usable offline.
- [ ] Bandit identifies as `94107`; 10 Feet identifies as `94102`.
- [ ] Manual match/lock, unlock, Issues, Duplicates, and Missing Library behave
      as documented.
- [ ] One copied MP3, FLAC, and M4A completes metadata preview/apply with its
      audio payload, artwork, lyrics, unrelated tags, sidecar, backup, and lock
      verified.
- [ ] Restore succeeds from a generated backup and does not delete the backup.
- [ ] rmpc verify works when installed; explicit setup is reviewed separately.
- [ ] `999 doctor --support-report` is manually reviewed for privacy before it
      is attached to an issue.
- [ ] A beta tester confirms clean pipx install and upgrade on the supported
      Linux environment.

## 5. Release procedure — only after explicit approval

1. Open and review a pull request from `v2-redesign` into `main`.
2. Resolve acceptance findings on `v2-redesign`; rerun the checks above.
3. Update the changelog date and replace moving-branch install examples with
   `v2.0.0b1` release/tag instructions.
4. Merge without rewriting published history.
5. Create the annotated tag `v2.0.0b1` on the accepted merge commit.
6. Build artifacts from a clean checkout of that tag and record SHA-256 sums.
7. Create a GitHub **pre-release**, paste the changelog section, and attach the
   wheel, sdist, and checksum file.
8. Install once from the attached wheel and run `999 doctor` before announcing
   the beta.

Package-index publication is a separate explicit decision. Do not upload to
PyPI merely because GitHub artifacts exist.

## 6. Stop/rollback conditions

Do not release if tests fail, artifact versions disagree, generated packages
depend on the checkout, privacy review fails, or a mutating acceptance test
cannot prove backup and preservation behavior. Fix on `v2-redesign`; do not
move an existing tag. If a published beta is defective, document it and issue
a new prerelease version rather than replacing its artifacts silently.
