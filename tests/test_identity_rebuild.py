from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.library import matching
from juice_lyrics.services.identity_rebuild import (
    IdentityChange,
    IdentityRebuildDependencies,
    IdentityRebuildPlan,
    IdentityRebuildResult,
    execute_catalogue_identity_rebuild,
    plan_catalogue_identity_rebuild,
)
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryTrack,
)


def _track(root: Path, relative: str, *, title: str | None = None, album: str = "Album") -> LibraryTrack:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"audio:{relative}".encode())
    path.with_suffix(".lrc").write_text("[00:01.00]keep\n", encoding="utf-8")
    return LibraryTrack(
        reference=relative,
        path=path,
        relative_path=Path(relative),
        filename=path.name,
        title=title or path.stem,
        duration_seconds=180.0,
        match_status=LibraryMatchStatus.MATCHED,
        matched_title=title or path.stem,
        lyric_status=(
            LibraryLyricStatus.SYNCED
            if path.suffix.casefold() == ".mp3"
            else LibraryLyricStatus.PLAIN
        ),
        lrc_status=LibraryLrcStatus.PRESENT,
        lrc_path=path.with_suffix(".lrc"),
        state_status=LibraryStateStatus.CURRENT,
        artist="Juice WRLD",
        album=album,
        media_format=path.suffix[1:].upper(),
    )


def _write_state(path: Path, files: dict) -> bytes:
    path.write_text(json.dumps({"files": files, "updated": "old", "keep": "top"}), encoding="utf-8")
    return path.read_bytes()


def _plan(settings: Settings, state_file: Path, tracks: tuple[LibraryTrack, ...], *, stale=()):
    raw = state_file.read_bytes() if state_file.exists() else b""
    state = json.loads(raw) if raw else {"files": {}, "updated": None}
    existing = sum(
        bool(entry.get("song_id") is not None and entry.get("api_name"))
        for entry in state.get("files", {}).values()
        if isinstance(entry, dict)
    )
    return IdentityRebuildPlan(
        settings,
        state_file,
        hashlib.sha256(raw).hexdigest(),
        state,
        tracks,
        tuple(stale),
        min(existing, len(tracks)),
    )


def test_rebuild_preview_is_read_only_and_reports_current_identity_and_stale_counts(tmp_path):
    music = tmp_path / "music"
    track = _track(music, "Album/Song.flac")
    state_file = tmp_path / "state.json"
    stale = "/tmp/pytest-of-someone/pytest-4/Song.mp3"
    original = _write_state(
        state_file,
        {
            "Album/Song.flac": {"song_id": 1, "api_name": "Song", "lyric_type": "FLAC_LYRICS"},
            stale: {"song_id": 2, "api_name": "Temporary"},
        },
    )
    snapshot = LibrarySnapshot(music, True, (track,))

    plan = plan_catalogue_identity_rebuild(
        Settings(music_dir=music),
        state_file=state_file,
        snapshot_provider=lambda *args, **kwargs: snapshot,
    )

    assert plan.current_tracks == 1
    assert plan.existing_identities == 1
    assert plan.currently_unknown == 0
    assert plan.stale_keys == (stale,)
    assert state_file.read_bytes() == original
    assert not tuple(tmp_path.glob("state.json.pre-identity-rebuild-*.bak"))


def test_rebuild_corrects_live_bandit_and_ten_feet_and_preserves_everything_else(tmp_path, monkeypatch):
    music = tmp_path / "music"
    bandit = _track(
        music,
        "Albums/Bandit.flac",
        title="Bandit (with YoungBoy Never Broke Again)",
        album="Death Race For Love (Bonus Track Version)",
    )
    ten_feet = _track(
        music,
        "Albums/10 Feet.m4a",
        title="10 Feet",
        album="Death Race For Love (Bonus Track Version)",
    )
    audio_before = {track.path: track.path.read_bytes() for track in (bandit, ten_feet)}
    lrc_before = {track.lrc_path: track.lrc_path.read_bytes() for track in (bandit, ten_feet)}
    state_file = tmp_path / "state.json"
    stale = "/tmp/pytest-of-someone/pytest-8/Old.mp3"
    original = _write_state(
        state_file,
        {
            str(bandit.relative_path): {"sha256": "bandit", "lyric_type": "FLAC_LYRICS", "lrc": str(bandit.lrc_path), "history": ["keep"]},
            str(ten_feet.relative_path): {"sha256": "ten", "song_id": 96383, "api_name": "10 Feet", "lyric_type": "M4A_LYRICS", "lrc": str(ten_feet.lrc_path)},
            "Historical/Keep.mp3": {"song_id": 55, "api_name": "Historical", "lyric_type": "USLT"},
            stale: {"song_id": 66, "api_name": "Stale"},
        },
    )
    bandit_results = [
        {"id": 96405, "name": bandit.title, "category": "recording_session", "length": ""},
        {"id": 95296, "name": f"{bandit.title} [v1]", "category": "unreleased", "length": "3:12"},
        {"id": 95298, "name": f"{bandit.title} [v4]", "category": "unreleased", "length": "3:12"},
        {"id": 94107, "name": "Bandit (feat. YoungBoy Never Broke Again)", "category": "released", "length": "3:09", "path": "Compilation/Released Discography/15. Death Race For Love (Bonus Track Version)/Bandit.mp3"},
    ]
    ten_results = [
        {"id": 94102, "name": "10 Feet", "category": "released", "length": "3:36", "path": "Compilation/Released Discography/11. Death Race For Love/10 Feet.mp3"},
        {"id": 96383, "name": "10 Feet", "category": "recording_session", "length": ""},
        {"id": 95062, "name": "10 Feet (v3)", "category": "unreleased", "length": "3:36"},
        {"id": 94269, "name": "10 Feet (TV Mix) [v1]", "category": "released", "length": "3:36"},
    ]
    monkeypatch.setattr(matching, "is_tagged_container", lambda path: True)
    monkeypatch.setattr(matching, "tagged_matching_title", lambda path: bandit.title if "Bandit" in path.name else "10 Feet")
    monkeypatch.setattr(
        matching,
        "local_duration",
        lambda path: 189.322562 if "Bandit" in path.name else 212.311927,
    )
    monkeypatch.setattr(matching, "local_album", lambda path: bandit.album if "Bandit" in path.name else ten_feet.album)
    dependencies = IdentityRebuildDependencies(
        searcher=lambda settings, query, refresh=False: bandit_results if query == "Bandit" else ten_results,
        matcher=matching.choose_candidate,
        search_title=lambda path: "Bandit" if "Bandit" in path.name else "10 Feet",
    )

    result = execute_catalogue_identity_rebuild(
        _plan(Settings(music_dir=music), state_file, (bandit, ten_feet), stale=(stale,)),
        dependencies=dependencies,
    )
    saved = json.loads(state_file.read_text(encoding="utf-8"))

    assert saved["files"][str(bandit.relative_path)]["song_id"] == 94107
    assert saved["files"][str(ten_feet.relative_path)]["song_id"] == 94102
    assert saved["files"][str(ten_feet.relative_path)]["lyric_type"] == "M4A_LYRICS"
    assert saved["files"][str(bandit.relative_path)]["history"] == ["keep"]
    assert saved["files"]["Historical/Keep.mp3"]["song_id"] == 55
    assert saved["files"][stale]["song_id"] == 66
    assert saved["keep"] == "top"
    assert result.matched == 2
    assert result.unknown == 0
    assert result.changed_identities == 2
    assert result.stale_ignored == 1
    assert {(change.old_song_id, change.new_song_id) for change in result.changes} == {(None, 94107), (96383, 94102)}
    assert result.backup_path is not None and result.backup_path.read_bytes() == original
    assert all(path.read_bytes() == value for path, value in audio_before.items())
    assert all(path.read_bytes() == value for path, value in lrc_before.items())
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("relative", ["Song.mp3", "Nested/Song.FLAC", "Nested/Song.M4A"])
def test_rebuild_forces_current_matcher_for_every_supported_format(tmp_path, relative):
    music = tmp_path / "music"
    track = _track(music, relative, title="Song")
    state_file = tmp_path / "state.json"
    _write_state(state_file, {relative: {"song_id": 1, "api_name": "Wrong", "lyric_type": "keep"}})
    calls = []
    dependencies = IdentityRebuildDependencies(
        searcher=lambda settings, query, refresh=False: calls.append(query) or [{"id": 2, "name": "Song"}],
        search_title=lambda path: "Song",
        matcher=lambda settings, path, results, query: (results[0], 100.0, [], []),
    )

    result = execute_catalogue_identity_rebuild(
        _plan(Settings(music_dir=music), state_file, (track,)), dependencies=dependencies
    )
    saved = json.loads(state_file.read_text(encoding="utf-8"))["files"][relative]

    assert calls == ["Song"]
    assert saved["song_id"] == 2
    assert saved["api_name"] == "Song"
    assert saved["lyric_type"] == "keep"
    assert result.changed_identities == 1


def test_correct_identity_stays_unchanged_and_ambiguous_identity_becomes_unknown(tmp_path):
    music = tmp_path / "music"
    correct = _track(music, "Correct.mp3")
    ambiguous = _track(music, "Ambiguous.flac")
    state_file = tmp_path / "state.json"
    _write_state(
        state_file,
        {
            "Correct.mp3": {"song_id": 1, "api_name": "Correct", "lyric_type": "SYLT"},
            "Ambiguous.flac": {"song_id": 9, "api_name": "Wrong", "lyric_type": "FLAC_LYRICS"},
        },
    )
    dependencies = IdentityRebuildDependencies(
        searcher=lambda settings, query, refresh=False: [{"id": 1, "name": "Correct"}] if query == "Correct" else [],
        search_title=lambda path: path.stem,
        matcher=lambda settings, path, results, query: ((results[0], 100.0, [], []) if results else (None, 0.0, [], [])),
    )

    result = execute_catalogue_identity_rebuild(
        _plan(Settings(music_dir=music), state_file, (correct, ambiguous)),
        dependencies=dependencies,
    )
    files = json.loads(state_file.read_text(encoding="utf-8"))["files"]

    assert files["Correct.mp3"]["song_id"] == 1
    assert "song_id" not in files["Ambiguous.flac"]
    assert "api_name" not in files["Ambiguous.flac"]
    assert files["Ambiguous.flac"]["lyric_type"] == "FLAC_LYRICS"
    assert result.matched == 1
    assert result.unknown == 1
    assert result.changed_identities == 1
    assert result.unchanged_identities == 1


def test_broad_catalogue_outage_aborts_without_backup_or_state_change(tmp_path):
    music = tmp_path / "music"
    tracks = (_track(music, "One.mp3"), _track(music, "Two.flac"))
    state_file = tmp_path / "state.json"
    original = _write_state(
        state_file,
        {track.reference: {"song_id": index, "api_name": track.title} for index, track in enumerate(tracks, 1)},
    )
    dependencies = IdentityRebuildDependencies(
        searcher=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
        search_title=lambda path: path.stem,
    )

    result = execute_catalogue_identity_rebuild(
        _plan(Settings(music_dir=music), state_file, tracks), dependencies=dependencies
    )

    assert result.aborted is True
    assert result.failed_preserved == 2
    assert result.backup_path is None
    assert state_file.read_bytes() == original


def test_individual_failure_preserves_old_identity_while_other_track_rebuilds(tmp_path):
    music = tmp_path / "music"
    failed = _track(music, "Failed.mp3")
    repaired = _track(music, "Repaired.flac")
    state_file = tmp_path / "state.json"
    _write_state(
        state_file,
        {
            "Failed.mp3": {"song_id": 1, "api_name": "Keep"},
            "Repaired.flac": {"song_id": 2, "api_name": "Wrong"},
        },
    )

    def search(settings, query, refresh=False):
        if query == "Failed":
            raise TimeoutError("one request timed out")
        return [{"id": 3, "name": "Repaired"}]

    result = execute_catalogue_identity_rebuild(
        _plan(Settings(music_dir=music), state_file, (failed, repaired)),
        dependencies=IdentityRebuildDependencies(
            searcher=search,
            search_title=lambda path: path.stem,
            matcher=lambda settings, path, results, query: (results[0], 100.0, [], []),
        ),
    )
    files = json.loads(state_file.read_text(encoding="utf-8"))["files"]

    assert files["Failed.mp3"]["song_id"] == 1
    assert files["Repaired.flac"]["song_id"] == 3
    assert result.failed_preserved == 1
    assert result.changed_identities == 1


def test_atomic_write_failure_preserves_original_and_complete_safety_backup(tmp_path):
    music = tmp_path / "music"
    track = _track(music, "Song.m4a")
    state_file = tmp_path / "state.json"
    original = _write_state(state_file, {"Song.m4a": {"song_id": 1, "api_name": "Old"}})
    plan = _plan(Settings(music_dir=music), state_file, (track,))

    with pytest.raises(OSError, match="disk full"):
        execute_catalogue_identity_rebuild(
            plan,
            dependencies=IdentityRebuildDependencies(
                searcher=lambda *args, **kwargs: [{"id": 2, "name": "Song"}],
                search_title=lambda path: "Song",
                matcher=lambda settings, path, results, query: (results[0], 100.0, [], []),
                state_writer=lambda path, state: (_ for _ in ()).throw(OSError("disk full")),
            ),
        )

    assert state_file.read_bytes() == original
    backups = tuple(tmp_path.glob("state.json.pre-identity-rebuild-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_rebuild_refuses_stale_preview_before_contacting_catalogue(tmp_path):
    music = tmp_path / "music"
    track = _track(music, "Song.mp3")
    state_file = tmp_path / "state.json"
    _write_state(state_file, {"Song.mp3": {"song_id": 1, "api_name": "Old"}})
    plan = _plan(Settings(music_dir=music), state_file, (track,))
    state_file.write_text('{"files": {}, "changed": true}', encoding="utf-8")
    calls = []

    with pytest.raises(RuntimeError, match="changed after the rebuild preview"):
        execute_catalogue_identity_rebuild(
            plan,
            dependencies=IdentityRebuildDependencies(
                searcher=lambda *args, **kwargs: calls.append(True) or [],
            ),
        )

    assert calls == []


def test_cli_rebuild_preview_requires_yes_and_apply_reports_audit(tmp_path, monkeypatch, capsys):
    from juice_lyrics import cli

    music = tmp_path / "music"
    track = _track(music, "10 Feet.flac")
    state_file = tmp_path / "state.json"
    _write_state(state_file, {track.reference: {"song_id": 96383, "api_name": "10 Feet"}})
    plan = _plan(Settings(music_dir=music), state_file, (track,))
    result = IdentityRebuildResult(
        1,
        1,
        0,
        1,
        0,
        0,
        0,
        (IdentityChange(track.relative_path, 96383, "10 Feet", 94102, "10 Feet"),),
        (),
        tmp_path / "state.backup",
    )
    executions = []
    monkeypatch.setattr(cli, "plan_catalogue_identity_rebuild", lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        cli,
        "execute_catalogue_identity_rebuild",
        lambda value, **kwargs: executions.append((value, kwargs)) or result,
    )

    preview_args = cli.build_parser().parse_args(["state", "rebuild-identities"])
    assert cli.command_state(preview_args, plan.settings, False) == 0
    assert not executions
    assert "No changes made" in capsys.readouterr().out

    apply_args = cli.build_parser().parse_args(
        ["state", "rebuild-identities", "--yes", "--details", "--refresh"]
    )
    assert cli.command_state(apply_args, plan.settings, False) == 0
    output = capsys.readouterr().out
    assert executions == [(plan, {"refresh": True})]
    assert "96383 (10 Feet) -> 94102 (10 Feet)" in output
    assert "Audio, embedded lyrics, sidecars, and rmpc configuration were not changed" in output
