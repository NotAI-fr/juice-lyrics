from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..backup.manager import ensure_data_dirs
from ..config.settings import DATA_DIR
from .models import AcquisitionItem, AcquisitionResult, AcquisitionState

DEFAULT_JOBS_FILE = DATA_DIR / "acquisition_jobs.json"


class JobStoreError(RuntimeError):
    """Raised when the persistent acquisition job store is invalid or unusable."""


@dataclass(slots=True)
class JobItem:
    """Persistent state for one acquisition item inside a job."""

    item: AcquisitionItem
    state: AcquisitionState = AcquisitionState.PENDING
    bytes_written: int = 0
    resumed: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": {
                "identifier": self.item.identifier,
                "title": self.item.title,
                "url": self.item.url,
                "destination": str(self.item.destination),
                "expected_size": self.item.expected_size,
                "expected_sha256": self.item.expected_sha256,
                "metadata": dict(self.item.metadata),
            },
            "state": self.state.value,
            "bytes_written": self.bytes_written,
            "resumed": self.resumed,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "JobItem":
        try:
            item_raw = raw["item"]
            item = AcquisitionItem(
                identifier=str(item_raw["identifier"]),
                title=str(item_raw["title"]),
                url=str(item_raw["url"]),
                destination=Path(str(item_raw["destination"])),
                expected_size=item_raw.get("expected_size"),
                expected_sha256=item_raw.get("expected_sha256"),
                metadata={str(k): str(v) for k, v in dict(item_raw.get("metadata", {})).items()},
            )
            state = AcquisitionState(str(raw.get("state", AcquisitionState.PENDING.value)))
        except (KeyError, TypeError, ValueError) as exc:
            raise JobStoreError(f"Invalid acquisition job item: {exc}") from exc

        return cls(
            item=item,
            state=state,
            bytes_written=int(raw.get("bytes_written", 0)),
            resumed=bool(raw.get("resumed", False)),
            error=raw.get("error"),
        )


@dataclass(slots=True)
class AcquisitionJob:
    """A persistent batch of explicitly selected acquisition items."""

    job_id: str
    created_at: str
    updated_at: str
    items: list[JobItem] = field(default_factory=list)

    @property
    def state(self) -> AcquisitionState:
        states = [entry.state for entry in self.items]
        if not states:
            return AcquisitionState.COMPLETE
        if any(state is AcquisitionState.FAILED for state in states):
            return AcquisitionState.FAILED
        if all(state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED} for state in states):
            return AcquisitionState.COMPLETE
        if any(state in {AcquisitionState.DOWNLOADING, AcquisitionState.VALIDATING} for state in states):
            return AcquisitionState.DOWNLOADING
        return AcquisitionState.PENDING

    @classmethod
    def new(cls, items: Iterable[AcquisitionItem], *, job_id: str | None = None) -> "AcquisitionJob":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            job_id=job_id or uuid.uuid4().hex,
            created_at=now,
            updated_at=now,
            items=[JobItem(item=item) for item in items],
        )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def get(self, index: int) -> JobItem:
        try:
            return self.items[index]
        except IndexError as exc:
            raise JobStoreError(f"Acquisition job item index out of range: {index}") from exc

    def record_result(self, index: int, result: AcquisitionResult) -> None:
        entry = self.get(index)
        entry.state = result.state
        entry.bytes_written = result.bytes_written
        entry.resumed = result.resumed
        entry.error = result.error
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "state": self.state.value,
            "items": [entry.to_dict() for entry in self.items],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AcquisitionJob":
        try:
            return cls(
                job_id=str(raw["job_id"]),
                created_at=str(raw["created_at"]),
                updated_at=str(raw["updated_at"]),
                items=[JobItem.from_dict(item) for item in raw.get("items", [])],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise JobStoreError(f"Invalid acquisition job: {exc}") from exc


class JobStore:
    """Small JSON-backed store for resumable acquisition jobs.

    The store writes atomically and keeps individual jobs keyed by ID, so a
    process restart cannot leave the entire state file half-written.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_JOBS_FILE

    def _ensure_parent(self) -> None:
        if self.path == DEFAULT_JOBS_FILE:
            ensure_data_dirs()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"jobs": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JobStoreError(f"Could not read acquisition job store: {self.path}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("jobs", {}), dict):
            raise JobStoreError(f"Invalid acquisition job store format: {self.path}")
        return raw

    def _save_raw(self, raw: dict[str, Any]) -> None:
        self._ensure_parent()
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise JobStoreError(f"Could not write acquisition job store: {self.path}") from exc

    def save(self, job: AcquisitionJob) -> None:
        raw = self._load_raw()
        job.touch()
        raw["jobs"][job.job_id] = job.to_dict()
        self._save_raw(raw)

    def create(self, items: Iterable[AcquisitionItem], *, job_id: str | None = None) -> AcquisitionJob:
        job = AcquisitionJob.new(items, job_id=job_id)
        self.save(job)
        return job

    def get(self, job_id: str) -> AcquisitionJob | None:
        raw = self._load_raw()
        payload = raw["jobs"].get(job_id)
        return AcquisitionJob.from_dict(payload) if payload is not None else None

    def list(self) -> list[AcquisitionJob]:
        raw = self._load_raw()
        jobs = [AcquisitionJob.from_dict(payload) for payload in raw["jobs"].values()]
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def delete(self, job_id: str) -> bool:
        raw = self._load_raw()
        if job_id not in raw["jobs"]:
            return False
        del raw["jobs"][job_id]
        self._save_raw(raw)
        return True

    def recover_interrupted(self) -> list[AcquisitionJob]:
        """Reset transient in-progress items so a new process can resume safely."""
        jobs = self.list()
        changed: list[AcquisitionJob] = []
        transient = {
            AcquisitionState.CHECKING_EXISTING,
            AcquisitionState.DOWNLOADING,
            AcquisitionState.VALIDATING,
        }
        for job in jobs:
            job_changed = False
            for entry in job.items:
                if entry.state in transient:
                    entry.state = AcquisitionState.PENDING
                    entry.error = "Recovered after an interrupted acquisition run"
                    entry.resumed = False
                    job_changed = True
            if job_changed:
                self.save(job)
                changed.append(job)
        return changed
