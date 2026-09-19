"""Transactional metadata repair foundation; intentionally not exposed in the TUI."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TIT2, TPE1, TRCK
from mutagen.mp4 import MP4

from ..backup.manager import (
    backup_file,
    make_backup_root,
    now_iso,
    restore_file,
    write_manifest,
)
from ..config.settings import STATE_FILE, Settings
from ..library.media import AudioMetadata, is_flac, is_m4a, read_audio_metadata
from ..lyrics.sidecar import sidecar_lrc_path
from ..state import (
    file_fingerprint,
    read_state_file,
    resolve_state_entry,
    sha256_file,
    write_state_file,
)
from .manual_identity import is_identity_locked
from .metadata_audit import MetadataAudit, MetadataProposal


@dataclass(frozen=True, slots=True)
class MediaPreservation:
    audio_payload_sha256: str
    unrelated_tags: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class MetadataRepairPlan:
    track_path: Path
    music_dir: Path
    reference: str
    state_file: Path
    state_key: str
    state_digest: str
    state_bytes: bytes
    state: dict[str, Any]
    selected: tuple[MetadataProposal, ...]
    original_sha256: str
    original_fingerprint: tuple[int, int, int, int, int]
    preservation: MediaPreservation
    sidecar_signature: tuple[bool, str | None]
    catalogue_id: Any
    identity_locked: bool


@dataclass(frozen=True, slots=True)
class MetadataRepairResult:
    path: Path
    fields: tuple[str, ...]
    backup_path: Path
    backup_root: Path
    sha256_before: str
    sha256_after: str
    identity_lock_preserved: bool


@dataclass(slots=True)
class MetadataRepairDependencies:
    state_reader: Callable[[Path], dict[str, Any]] = read_state_file
    state_writer: Callable[[Path, Mapping[str, Any]], None] = write_state_file
    hasher: Callable[[Path], str] = sha256_file
    fingerprint_reader: Callable[[Path], tuple[int, int, int, int, int]] = file_fingerprint
    backup_root_factory: Callable[[], Path] = make_backup_root
    backup_writer: Callable[[Path, Path, Path], Path] = backup_file
    manifest_writer: Callable[[Path, list[dict[str, Any]]], None] = write_manifest
    restorer: Callable[[Path, Path], None] = restore_file
    copier: Callable[[Path, Path], Any] = shutil.copy2
    replacer: Callable[[Path, Path], None] = os.replace
    tag_writer: Callable[[Path, Mapping[str, str]], None] | None = None
    metadata_reader: Callable[[Path], AudioMetadata] = read_audio_metadata


def _source_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_scope(settings: Settings, path: Path, reference: str) -> Path:
    try:
        root = Path(settings.music_dir).resolve(strict=True)
        resolved = Path(path).resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError("The selected track is outside the configured music library.") from exc
    if Path(reference).is_absolute() or ".." in Path(reference).parts or str(relative) != reference:
        raise RuntimeError("The selected track path is no longer valid; Sync Library first.")
    return root


def _freeze(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return ("bytes", len(value), hashlib.sha256(value).hexdigest())
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return (type(value).__name__, _freeze(attributes))
    return (type(value).__name__, repr(value))


def _mp3_audio_payload(data: bytes) -> bytes:
    start = 0
    if len(data) >= 10 and data[:3] == b"ID3":
        size_bytes = data[6:10]
        if any(value & 0x80 for value in size_bytes):
            raise RuntimeError("MP3 has an invalid ID3 size header.")
        tag_size = sum(value << shift for value, shift in zip(size_bytes, (21, 14, 7, 0)))
        start = 10 + tag_size
        if data[5] & 0x10:
            start += 10
    end = len(data) - 128 if len(data) >= 128 and data[-128:-125] == b"TAG" else len(data)
    if start > end:
        raise RuntimeError("MP3 tag boundaries are invalid.")
    return data[start:end]


def _flac_audio_payload(data: bytes) -> bytes:
    if not data.startswith(b"fLaC"):
        raise RuntimeError("FLAC stream marker is missing.")
    position = 4
    while True:
        if position + 4 > len(data):
            raise RuntimeError("FLAC metadata blocks are truncated.")
        header = data[position]
        length = int.from_bytes(data[position + 1 : position + 4], "big")
        position += 4 + length
        if position > len(data):
            raise RuntimeError("FLAC metadata blocks are truncated.")
        if header & 0x80:
            return data[position:]


def _m4a_audio_payload(data: bytes) -> bytes:
    position = 0
    payloads: list[bytes] = []
    while position + 8 <= len(data):
        size = int.from_bytes(data[position : position + 4], "big")
        atom = data[position + 4 : position + 8]
        header_size = 8
        if size == 1:
            if position + 16 > len(data):
                raise RuntimeError("M4A atom header is truncated.")
            size = int.from_bytes(data[position + 8 : position + 16], "big")
            header_size = 16
        elif size == 0:
            size = len(data) - position
        if size < header_size or position + size > len(data):
            raise RuntimeError("M4A atom boundaries are invalid.")
        if atom == b"mdat":
            payloads.append(data[position + header_size : position + size])
        position += size
    if not payloads:
        raise RuntimeError("M4A media payload is missing.")
    return b"".join(payloads)


def _audio_payload_sha256(path: Path) -> str:
    data = path.read_bytes()
    if is_flac(path):
        payload = _flac_audio_payload(data)
    elif is_m4a(path):
        payload = _m4a_audio_payload(data)
    else:
        payload = _mp3_audio_payload(data)
    return hashlib.sha256(payload).hexdigest()


def _unrelated_tags(path: Path, selected_fields: frozenset[str]) -> tuple[Any, ...]:
    if is_flac(path):
        audio = FLAC(path)
        keys = {
            "title": "title",
            "artist": "artist",
            "album": "album",
            "track_number": "tracknumber",
        }
        excluded = {keys[field] for field in selected_fields}
        tags = tuple(
            sorted(
                (key.casefold(), _freeze(values))
                for key, values in (audio.tags or {}).items()
                if key.casefold() not in excluded
            )
        )
        pictures = tuple(_freeze(picture.write()) for picture in audio.pictures)
        return ("FLAC", tags, pictures)
    if is_m4a(path):
        audio = MP4(path)
        atoms = {
            "title": "\xa9nam",
            "artist": "\xa9ART",
            "album": "\xa9alb",
            "track_number": "trkn",
        }
        excluded = {atoms[field] for field in selected_fields}
        tags = tuple(
            sorted(
                (key, _freeze(values))
                for key, values in (audio.tags or {}).items()
                if key not in excluded
            )
        )
        return ("M4A", tags)
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    frames = {
        "title": "TIT2",
        "artist": "TPE1",
        "album": "TALB",
        "track_number": "TRCK",
    }
    excluded = {frames[field] for field in selected_fields}
    preserved = tuple(
        sorted(
            (key, _freeze(frame))
            for key, frame in tags.items()
            if key.split(":", 1)[0] not in excluded
        )
    )
    data = path.read_bytes()
    id3v1 = data[-128:] if len(data) >= 128 and data[-128:-125] == b"TAG" else b""
    return ("MP3", preserved, _freeze(id3v1))


def inspect_media_preservation(
    path: Path,
    selected_fields: frozenset[str],
) -> MediaPreservation:
    return MediaPreservation(
        _audio_payload_sha256(path),
        _unrelated_tags(path, selected_fields),
    )


def _parse_track_number(value: str) -> tuple[int, int]:
    parts = value.strip().split("/", 1)
    try:
        number = int(parts[0])
        total = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 0
    except ValueError as exc:
        raise RuntimeError("The proposed track number is not valid.") from exc
    if number <= 0 or total < 0:
        raise RuntimeError("The proposed track number is not valid.")
    return number, total


def write_metadata_fields(path: Path, values: Mapping[str, str]) -> None:
    """Write only supported common fields to a disposable working copy."""

    if is_flac(path):
        audio = FLAC(path)
        keys = {
            "title": "TITLE",
            "artist": "ARTIST",
            "album": "ALBUM",
            "track_number": "TRACKNUMBER",
        }
        for field, value in values.items():
            audio[keys[field]] = [value]
        audio.save()
        return
    if is_m4a(path):
        audio = MP4(path)
        if audio.tags is None:
            audio.add_tags()
        atoms = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb"}
        for field, value in values.items():
            if field == "track_number":
                audio["trkn"] = [_parse_track_number(value)]
            else:
                audio[atoms[field]] = [value]
        audio.save()
        return
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    frames = {"title": TIT2, "artist": TPE1, "album": TALB, "track_number": TRCK}
    for field, value in values.items():
        tags.delall(frames[field].__name__)
        tags.add(frames[field](encoding=3, text=[value]))
    version = 3 if getattr(tags, "version", None) and tags.version[0] == 3 else 4
    tags.save(path, v2_version=version)


def _sidecar_signature(path: Path) -> tuple[bool, str | None]:
    sidecar = sidecar_lrc_path(path)
    if not sidecar.exists():
        return False, None
    return True, sha256_file(sidecar)


def _metadata_value(metadata: AudioMetadata, field: str) -> str | None:
    value = getattr(metadata, field)
    return str(value).strip() if value is not None else None


def _field_matches(field: str, actual: str | None, expected: str) -> bool:
    if actual is None:
        return False
    if field == "track_number":
        try:
            return _parse_track_number(actual) == _parse_track_number(expected)
        except RuntimeError:
            return False
    return actual == expected


def plan_metadata_repair(
    settings: Settings,
    audit: MetadataAudit,
    selected_fields: tuple[str, ...],
    *,
    state_file: Path = STATE_FILE,
    dependencies: MetadataRepairDependencies | None = None,
) -> MetadataRepairPlan:
    """Pin an explicit subset of previewed fields without modifying anything."""

    deps = dependencies or MetadataRepairDependencies()
    track = audit.track
    root = _validate_scope(settings, track.path, track.reference)
    if audit.catalogue is None or track.catalogue_id is None:
        raise RuntimeError("A confirmed catalogue identity is required for metadata repair.")
    if str(audit.catalogue.song_id) != str(track.catalogue_id):
        raise RuntimeError("Catalogue evidence no longer matches the selected identity.")
    proposal_by_field = {proposal.field: proposal for proposal in audit.proposals}
    if not selected_fields or len(set(selected_fields)) != len(selected_fields):
        raise RuntimeError("Select at least one metadata field exactly once.")
    try:
        selected = tuple(proposal_by_field[field] for field in selected_fields)
    except KeyError as exc:
        raise RuntimeError("A selected field is not present in the reviewed preview.") from exc

    fingerprint = deps.fingerprint_reader(track.path)
    if track.content_fingerprint is not None and fingerprint != track.content_fingerprint:
        raise RuntimeError("The selected audio changed; Sync Library and preview again.")
    digest = deps.hasher(track.path)
    if track.content_sha256 is not None and digest != track.content_sha256:
        raise RuntimeError("The selected audio changed; Sync Library and preview again.")
    if deps.fingerprint_reader(track.path) != fingerprint:
        raise RuntimeError("The selected audio changed while the plan was prepared.")

    state_path = Path(state_file)
    state_bytes = _source_bytes(state_path)
    state = deps.state_reader(state_path)
    files = state.get("files", {})
    if not isinstance(files, Mapping):
        raise RuntimeError("Library state records are malformed.")
    state_key, resolved = resolve_state_entry(files, track.relative_path, (track.relative_path,))
    if state_key is None or not isinstance(resolved, Mapping):
        raise RuntimeError("Current state for the selected track is unavailable.")
    if resolved.get("sha256") != digest or str(resolved.get("song_id")) != str(track.catalogue_id):
        raise RuntimeError("Library state no longer matches the reviewed audio and identity.")
    locked = is_identity_locked(resolved)
    if track.identity_locked != locked:
        raise RuntimeError("Catalogue lock state changed; refresh and preview again.")
    selected_names = frozenset(proposal.field for proposal in selected)
    return MetadataRepairPlan(
        track.path,
        root,
        track.reference,
        state_path,
        state_key,
        _digest_bytes(state_bytes),
        state_bytes,
        state,
        selected,
        digest,
        fingerprint,
        inspect_media_preservation(track.path, selected_names),
        _sidecar_signature(track.path),
        track.catalogue_id,
        locked,
    )


def _revalidate(plan: MetadataRepairPlan, deps: MetadataRepairDependencies) -> None:
    if _digest_bytes(_source_bytes(plan.state_file)) != plan.state_digest:
        raise RuntimeError("Library state changed after preview; no metadata was applied.")
    if deps.fingerprint_reader(plan.track_path) != plan.original_fingerprint:
        raise RuntimeError("The selected audio changed after preview; no metadata was applied.")
    if deps.hasher(plan.track_path) != plan.original_sha256:
        raise RuntimeError("The selected audio changed after preview; no metadata was applied.")
    selected = frozenset(proposal.field for proposal in plan.selected)
    if inspect_media_preservation(plan.track_path, selected) != plan.preservation:
        raise RuntimeError("The selected audio metadata changed after preview.")
    if _sidecar_signature(plan.track_path) != plan.sidecar_signature:
        raise RuntimeError("The adjacent lyrics changed after preview; no metadata was applied.")


def execute_metadata_repair(
    plan: MetadataRepairPlan,
    *,
    confirmed: bool = False,
    dependencies: MetadataRepairDependencies | None = None,
) -> MetadataRepairResult:
    """Apply a pinned plan through backup, temporary verification, and rollback."""

    if not confirmed:
        raise RuntimeError("Metadata repair requires explicit confirmation.")
    deps = dependencies or MetadataRepairDependencies()
    _revalidate(plan, deps)
    backup_root = deps.backup_root_factory()
    backup = deps.backup_writer(plan.track_path, backup_root, plan.music_dir)
    deps.manifest_writer(
        backup_root,
        [
            {
                "file": str(plan.track_path),
                "sha256_before": plan.original_sha256,
                "operation": "metadata_repair",
                "fields": [proposal.field for proposal in plan.selected],
            }
        ],
    )

    descriptor, temporary_name = tempfile.mkstemp(
        dir=plan.track_path.parent,
        prefix=f".{plan.track_path.name}.",
        suffix=plan.track_path.suffix,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    replaced = False
    state_candidate: dict[str, Any] | None = None
    new_sha256: str | None = None
    try:
        deps.copier(plan.track_path, temporary)
        values = {proposal.field: proposal.after for proposal in plan.selected}
        (deps.tag_writer or write_metadata_fields)(temporary, values)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        selected = frozenset(values)
        metadata = deps.metadata_reader(temporary)
        for field, expected in values.items():
            if not _field_matches(field, _metadata_value(metadata, field), expected):
                raise RuntimeError(f"Temporary metadata verification failed for {field}.")
        if inspect_media_preservation(temporary, selected) != plan.preservation:
            raise RuntimeError("Metadata write changed audio or unrelated tags.")
        _revalidate(plan, deps)
        deps.replacer(temporary, plan.track_path)
        replaced = True

        metadata = deps.metadata_reader(plan.track_path)
        for field, expected in values.items():
            if not _field_matches(field, _metadata_value(metadata, field), expected):
                raise RuntimeError(f"Final metadata verification failed for {field}.")
        if inspect_media_preservation(plan.track_path, selected) != plan.preservation:
            raise RuntimeError("Final verification found changed audio or unrelated tags.")
        if _sidecar_signature(plan.track_path) != plan.sidecar_signature:
            raise RuntimeError("The adjacent lyrics changed during metadata repair.")
        new_sha256 = deps.hasher(plan.track_path)

        if _digest_bytes(_source_bytes(plan.state_file)) != plan.state_digest:
            raise RuntimeError("Library state changed during metadata repair.")
        updated = dict(plan.state)
        files = dict(updated.get("files", {}))
        entry = dict(files.get(plan.state_key, {}))
        if str(entry.get("song_id")) != str(plan.catalogue_id):
            raise RuntimeError("Catalogue identity changed during metadata repair.")
        if plan.identity_locked and not is_identity_locked(entry):
            raise RuntimeError("Manual catalogue lock changed during metadata repair.")
        entry["sha256"] = new_sha256
        entry["updated"] = now_iso()
        files[plan.state_key] = entry
        updated["files"] = files
        state_candidate = updated
        deps.state_writer(plan.state_file, updated)
        return MetadataRepairResult(
            plan.track_path,
            tuple(values),
            backup,
            backup_root,
            plan.original_sha256,
            new_sha256,
            plan.identity_locked,
        )
    except BaseException as exc:
        if not replaced and not temporary.exists():
            # os.replace may have completed just before an asynchronous
            # interruption was delivered to Python.
            replaced = True
        if replaced:
            try:
                deps.restorer(backup, plan.track_path)
                if deps.hasher(plan.track_path) != plan.original_sha256:
                    raise RuntimeError("restored file hash does not match the original")
            except Exception as restore_error:
                raise RuntimeError(
                    f"Metadata repair failed and automatic rollback failed: {restore_error}"
                ) from exc
        if state_candidate is not None and new_sha256 is not None:
            current = deps.state_reader(plan.state_file)
            expected = dict(state_candidate)
            current_without_timestamp = dict(current)
            expected.pop("updated", None)
            current_without_timestamp.pop("updated", None)
            if current_without_timestamp == expected:
                _atomic_restore_bytes(plan.state_file, plan.state_bytes)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_restore_bytes(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".rollback",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
