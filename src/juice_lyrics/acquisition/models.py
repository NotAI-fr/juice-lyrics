from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class AcquisitionState(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CHECKING_EXISTING = "checking_existing"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    VALIDATING = "validating"
    IMPORTED = "imported"
    FAILED = "failed"
    SKIPPED = "skipped"
    COMPLETE = "complete"


@dataclass(slots=True)
class AcquisitionItem:
    """One explicitly selected/authorized acquisition target."""

    identifier: str
    title: str
    url: str
    destination: Path
    expected_size: int | None = None
    expected_sha256: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AcquisitionResult:
    item: AcquisitionItem
    state: AcquisitionState
    destination: Path | None = None
    bytes_written: int = 0
    resumed: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.state is AcquisitionState.COMPLETE
