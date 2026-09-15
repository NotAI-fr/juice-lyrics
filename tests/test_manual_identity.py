from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.library.media import AudioMetadata
from juice_lyrics.services.library_identity import (
    IdentityBackfillDependencies,
    backfill_catalogue_identities,
)
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibraryStateStatus,
    LibraryTrack,
    get_library_snapshot,
)
from juice_lyrics.services.manual_identity import (
    ManualIdentityDependencies,
    is_identity_locked,
    set_manual_identity,
    unlock_manual_identity,
)
from juice_lyrics.state import file_fingerprint, sha256_file


def _track(root: Path, name: str = "Album/Song.flac") -> LibraryTrack:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")
    return LibraryTrack(
        reference=name,
        path=path,
        relative_path=Path(name),
        filename=path.name,
        title=path.stem,
        duration_seconds=180.0,
        match_status=LibraryMatchStatus.UNMATCHED,
        matched_title=None,
        lyric_status=LibraryLyricStatus.PLAIN,
        lrc_status=LibraryLrcStatus.NONE,
        lrc_path=None,
        state_status=LibraryStateStatus.NEW,
        artist="Juice WRLD",
        album="Album",
        media_format=path.suffix[1:].upper(),
        content_fingerprint=file_fingerprint(path),
    )


def test_legacy_identity_is_automatic_and_unlocked() -> None:
    assert not is_identity_locked({"song_id": 1, "api_name": "Song"})
    assert not is_identity_locked(
        {
            "song_id": 1,
            "api_name": "Song",
            "identity_source": "manual",
            "identity_locked": False,
        }
    )


def test_library_snapshot_restores_manual_lock_after_restart(tmp_path):
    music = tmp_path / "music"
    track = _track(music)
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "files": {
                    track.reference: {
                        "sha256": sha256_file(track.path),
                        "song_id": 77,
                        "api_name": "Chosen",
                        "identity_source": "manual",
                        "identity_locked": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    snapshot = get_library_snapshot(
        Settings(music_dir=music),
        state_file=state_file,
        verifier=lambda path: (True, "FLAC plain lyrics"),
        metadata_reader=lambda path: AudioMetadata(
            "Song", "Juice WRLD", "Album", 180.0
        ),
    )
    restored = snapshot.tracks[0]
    assert restored.match_status is LibraryMatchStatus.MATCHED
    assert restored.matched_title == "Chosen"
    assert restored.identity_source == "manual"
    assert restored.identity_locked is True


def test_manual_match_is_atomic_file_bound_and_preserves_unrelated_state(tmp_path):
    music = tmp_path / "music"
    track = _track(music)
    sidecar = track.path.with_suffix(".lrc")
    sidecar.write_text("[00:01.00]keep\n", encoding="utf-8")
    rmpc = tmp_path / "rmpc.ron"
    rmpc.write_text("keep", encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "files": {
                    track.reference: {
                        "song_id": 123,
                        "api_name": "Wrong Automatic Match",
                        "lyric_type": "FLAC_LYRICS_PLAIN",
                        "custom": {"keep": True},
                    }
                },
                "top": 42,
            }
        ),
        encoding="utf-8",
    )
    audio_before = track.path.read_bytes()
    lrc_before = sidecar.read_bytes()

    result = set_manual_identity(
        Settings(music_dir=music),
        track,
        song_id=777,
        api_name="Chosen Recording",
        state_file=state_file,
    )

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    entry = saved["files"][track.reference]
    assert result.locked and result.song_id == 777
    assert entry["song_id"] == 777
    assert entry["api_name"] == "Chosen Recording"
    assert entry["identity_source"] == "manual"
    assert entry["identity_locked"] is True
    assert entry["sha256"] == sha256_file(track.path)
    assert entry["lyric_type"] == "FLAC_LYRICS_PLAIN"
    assert entry["custom"] == {"keep": True}
    assert saved["top"] == 42
    assert track.path.read_bytes() == audio_before
    assert sidecar.read_bytes() == lrc_before
    assert rmpc.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "backups").exists()


def test_locked_identity_is_reused_without_catalogue_search(tmp_path):
    music = tmp_path / "music"
    track = _track(music, "Song.mp3")
    digest = sha256_file(track.path)
    track = replace(
        track,
        content_sha256=digest,
        state_status=LibraryStateStatus.CURRENT,
    )
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "files": {
                    track.reference: {
                        "sha256": digest,
                        "song_id": 7,
                        "api_name": "Manual",
                        "identity_source": "manual",
                        "identity_locked": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    result = backfill_catalogue_identities(
        Settings(music_dir=music),
        (track,),
        state_file=state_file,
        dependencies=IdentityBackfillDependencies(
            searcher=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("locked identity searched")
            )
        ),
    )
    assert result.reused == 1
    assert json.loads(state_file.read_text(encoding="utf-8"))["files"][
        track.reference
    ]["song_id"] == 7


def test_changed_audio_recalculation_does_not_transfer_manual_lock(tmp_path):
    music = tmp_path / "music"
    track = _track(music)
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "files": {
                    track.reference: {
                        "sha256": "old",
                        "song_id": 1,
                        "api_name": "Old",
                        "identity_source": "manual",
                        "identity_locked": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    candidate = {"id": 2, "name": "New"}
    result = backfill_catalogue_identities(
        Settings(music_dir=music),
        (track,),
        state_file=state_file,
        dependencies=IdentityBackfillDependencies(
            searcher=lambda *args, **kwargs: [candidate],
            matcher=lambda *args: (candidate, 100.0, [], []),
            search_title=lambda path: "Song",
        ),
    )
    entry = json.loads(state_file.read_text(encoding="utf-8"))["files"][
        track.reference
    ]
    assert result.identified == 1 and entry["song_id"] == 2
    assert "identity_source" not in entry
    assert "identity_locked" not in entry


def test_unlock_clears_identity_but_preserves_lyrics_and_custom_fields(tmp_path):
    music = tmp_path / "music"
    track = _track(music)
    digest = sha256_file(track.path)
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "files": {
                    track.reference: {
                        "sha256": digest,
                        "song_id": 5,
                        "api_name": "Manual",
                        "identity_source": "manual",
                        "identity_locked": True,
                        "lyric_type": "FLAC_LYRICS_PLAIN",
                        "custom": 9,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = unlock_manual_identity(
        Settings(music_dir=music), track, state_file=state_file
    )

    entry = json.loads(state_file.read_text(encoding="utf-8"))["files"][
        track.reference
    ]
    assert result.changed and not result.locked
    assert all(
        field not in entry
        for field in ("song_id", "api_name", "identity_source", "identity_locked")
    )
    assert entry["lyric_type"] == "FLAC_LYRICS_PLAIN"
    assert entry["custom"] == 9

    candidate = {"id": 8, "name": "Automatic Later"}
    backfill_catalogue_identities(
        Settings(music_dir=music),
        (track,),
        state_file=state_file,
        dependencies=IdentityBackfillDependencies(
            searcher=lambda *args, **kwargs: [candidate],
            matcher=lambda *args: (candidate, 100.0, [], []),
            search_title=lambda path: "Song",
        ),
    )
    reconsidered = json.loads(state_file.read_text(encoding="utf-8"))["files"][
        track.reference
    ]
    assert reconsidered["song_id"] == 8
    assert "identity_locked" not in reconsidered


def test_manual_match_rejects_state_conflict_and_changed_or_missing_audio(tmp_path):
    music = tmp_path / "music"
    track = _track(music)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {}}), encoding="utf-8")

    def conflict_hash(path: Path) -> str:
        state_file.write_text(json.dumps({"files": {}, "newer": True}), encoding="utf-8")
        return sha256_file(path)

    with pytest.raises(RuntimeError, match="state changed"):
        set_manual_identity(
            Settings(music_dir=music),
            track,
            song_id=1,
            api_name="Song",
            state_file=state_file,
            dependencies=ManualIdentityDependencies(hasher=conflict_hash),
        )
    assert json.loads(state_file.read_text(encoding="utf-8"))["newer"] is True

    track.path.write_bytes(b"replacement")
    with pytest.raises(RuntimeError, match="audio file changed"):
        set_manual_identity(
            Settings(music_dir=music),
            track,
            song_id=1,
            api_name="Song",
            state_file=state_file,
        )
    track.path.unlink()
    with pytest.raises(RuntimeError, match="outside the configured music library"):
        set_manual_identity(
            Settings(music_dir=music),
            track,
            song_id=1,
            api_name="Song",
            state_file=state_file,
        )
