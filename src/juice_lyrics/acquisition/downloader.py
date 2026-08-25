from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import AcquisitionItem, AcquisitionResult, AcquisitionState

ProgressCallback = Callable[[int, int | None], None]
NON_RETRYABLE_HTTP_CODES = {400, 401, 403, 404, 410}


class FatalDownloadError(RuntimeError):
    """An error that cannot be resolved by retrying the transfer."""


@dataclass(slots=True)
class DownloadPolicy:
    """Safety and transport policy for an explicitly authorized URL."""

    timeout: int = 30
    retries: int = 3
    retry_delay: float = 1.0
    chunk_size: int = 1024 * 128
    max_bytes: int | None = 1024 * 1024 * 1024
    resume: bool = True
    overwrite: bool = False
    require_https: bool = True


def _validate_url(url: str, *, require_https: bool) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise RuntimeError("Resource URL must be an absolute HTTP(S) URL")
    if require_https and parsed.scheme != "https":
        raise RuntimeError("HTTPS is required by the current download policy")


def _sha256(path: Path, chunk_size: int = 1024 * 128) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_probable_error_payload(path: Path) -> bool:
    """Reject tiny text/HTML payloads commonly returned by failed downloads."""

    try:
        size = path.stat().st_size
        if size == 0:
            return True
        if size > 1024 * 1024:
            return False
        head = path.read_bytes()[:4096].lstrip().lower()
        if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            return True
        if head.startswith(b'{"error"') or head.startswith(b'{"detail"'):
            return True
    except OSError:
        return True
    return False


def _existing_ok(item: AcquisitionItem, policy: DownloadPolicy) -> bool:
    if not item.destination.exists():
        return False
    if not item.destination.is_file():
        raise RuntimeError(f"Destination exists but is not a file: {item.destination}")
    if policy.overwrite:
        return False
    if item.expected_size is not None and item.destination.stat().st_size != item.expected_size:
        raise RuntimeError(f"Destination already exists with a different size: {item.destination}")
    if item.expected_sha256:
        if _sha256(item.destination) != item.expected_sha256.lower():
            raise RuntimeError(f"Destination already exists with a different checksum: {item.destination}")
    return True


def download_to(
    item: AcquisitionItem,
    policy: DownloadPolicy | None = None,
    *,
    progress: ProgressCallback | None = None,
) -> AcquisitionResult:
    """Download one explicitly authorized resource safely and atomically."""

    policy = policy or DownloadPolicy()
    result = AcquisitionResult(item=item, state=AcquisitionState.CHECKING_EXISTING)
    _validate_url(item.url, require_https=policy.require_https)

    if _existing_ok(item, policy):
        result.state = AcquisitionState.SKIPPED
        result.destination = item.destination
        result.bytes_written = item.destination.stat().st_size
        return result

    item.destination.parent.mkdir(parents=True, exist_ok=True)
    partial = item.destination.with_name(item.destination.name + ".part")

    last_error: Exception | None = None
    for attempt in range(policy.retries + 1):
        resume_from = partial.stat().st_size if policy.resume and partial.exists() else 0
        try:
            headers = {
                "User-Agent": "juice-lyrics-acquisition/1.0",
                "Accept": "audio/mpeg,application/octet-stream;q=0.9,*/*;q=0.1",
            }
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"

            request = Request(item.url, headers=headers)
            result.state = AcquisitionState.DOWNLOADING
            with urlopen(request, timeout=policy.timeout) as response:
                status = getattr(response, "status", None)
                content_length = response.headers.get("Content-Length")
                remote_size = int(content_length) if content_length and content_length.isdigit() else None
                accepts_resume = status == 206 and resume_from > 0
                if resume_from > 0 and not accepts_resume:
                    resume_from = 0
                    partial.unlink(missing_ok=True)
                mode = "ab" if (resume_from > 0 and accepts_resume) else "wb"
                total = (resume_from + remote_size) if remote_size is not None and accepts_resume else remote_size
                written = resume_from if accepts_resume else 0
                result.resumed = accepts_resume
                with partial.open(mode) as handle:
                    while True:
                        chunk = response.read(policy.chunk_size)
                        if not chunk:
                            break
                        handle.write(chunk)
                        written += len(chunk)
                        if policy.max_bytes is not None and written > policy.max_bytes:
                            partial.unlink(missing_ok=True)
                            raise FatalDownloadError("Download exceeds the configured maximum size")
                        if progress:
                            progress(written, total)

            result.state = AcquisitionState.VALIDATING
            if _is_probable_error_payload(partial):
                partial.unlink(missing_ok=True)
                raise RuntimeError("Downloaded payload looks empty or like an error response")
            final_size = partial.stat().st_size
            if item.expected_size is not None and final_size != item.expected_size:
                partial.unlink(missing_ok=True)
                raise FatalDownloadError(f"Downloaded size mismatch: expected {item.expected_size}, got {final_size}")
            if item.expected_sha256 and _sha256(partial) != item.expected_sha256.lower():
                partial.unlink(missing_ok=True)
                raise FatalDownloadError("Downloaded SHA-256 checksum does not match the expected value")

            os.replace(partial, item.destination)
            result.state = AcquisitionState.COMPLETE
            result.destination = item.destination
            result.bytes_written = final_size
            return result

        except FatalDownloadError as exc:
            last_error = exc
            break

        except HTTPError as exc:
            last_error = exc
            if exc.code in NON_RETRYABLE_HTTP_CODES:
                break
            if exc.code == 416 and resume_from > 0:
                partial.unlink(missing_ok=True)
                if attempt < policy.retries:
                    time.sleep(policy.retry_delay * (2 ** attempt))
                continue
            if attempt >= policy.retries:
                break
            time.sleep(policy.retry_delay * (2 ** attempt))

        except (URLError, OSError, RuntimeError) as exc:
            last_error = exc
            if attempt >= policy.retries:
                break
            time.sleep(policy.retry_delay * (2 ** attempt))

    result.state = AcquisitionState.FAILED
    result.error = str(last_error or "Download failed")
    return result

