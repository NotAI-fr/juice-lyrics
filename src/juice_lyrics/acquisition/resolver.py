from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..config.settings import DEFAULT_API_BASE
from .models import AcquisitionItem


_URL_FIELDS = (
    "resource_url",
    "download_url",
    "audio_url",
    "file_url",
    "url",
)
_SIZE_FIELDS = ("expected_size", "size", "file_size", "filesize")
_SHA_FIELDS = ("expected_sha256", "sha256", "checksum", "hash")
_ID_FIELDS = ("id", "identifier", "slug")
_TITLE_FIELDS = ("title", "name")
_FILENAME_FIELDS = ("filename", "file_name", "audio_filename", "path", "file_path")


class ResourceResolutionError(RuntimeError):
    """The selected API result cannot be turned into a safe acquisition item."""


def _first_value(data: dict[str, Any], fields: tuple[str, ...]) -> Any:
    for field in fields:
        value = data.get(field)
        if value not in (None, ""):
            return value
    return None


def _clean_filename(value: str) -> str:
    value = unquote(value).strip()
    value = value.replace("\\", "/")
    value = Path(value).name
    value = re.sub(r"[\x00-\x1f\x7f]", "", value)
    value = value.strip(" .")
    if not value or value in {".", ".."}:
        raise ResourceResolutionError("The resource filename is empty or invalid")
    return value


def _filename_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "path" in qs and qs["path"]:
        candidate = Path(unquote(qs["path"][0])).name
        if candidate and candidate not in {".", ".."}:
            try:
                return _clean_filename(candidate)
            except ResourceResolutionError:
                pass
    candidate = Path(unquote(parsed.path)).name
    if not candidate or candidate in {".", ".."}:
        return None
    try:
        return _clean_filename(candidate)
    except ResourceResolutionError:
        return None


def _coerce_size(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ResourceResolutionError(f"Invalid expected size: {value!r}") from exc
    if parsed < 0:
        raise ResourceResolutionError("Expected size cannot be negative")
    return parsed


def _coerce_sha256(value: Any) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ResourceResolutionError("Expected SHA-256 must be a 64-character hexadecimal string")
    return value


def _absolute_url(value: Any) -> str:
    url = str(value).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ResourceResolutionError("Selected resource does not contain an absolute HTTP(S) URL")
    return url


def resolve_resource(
    resource: dict[str, Any],
    *,
    destination_dir: Path,
    api_base: str = DEFAULT_API_BASE,
    allow_http: bool = False,
) -> AcquisitionItem:
    """Resolve one explicitly selected API resource into an AcquisitionItem.

    Accepts standard resource fields (download_url, size, sha256) or a live API
    resource with a relative 'path', synthesizing the authorized download endpoint
    using the configured api_base while preserving filename, size, and checksum.
    """

    if not isinstance(resource, dict):
        raise ResourceResolutionError("Selected resource must be an object")

    raw_url = _first_value(resource, _URL_FIELDS)
    if raw_url is None:
        path_val = _first_value(resource, ("path", "file_path"))
        if path_val not in (None, ""):
            path_str = str(path_val).strip()
            parsed_path = urlparse(path_str)
            if parsed_path.scheme in {"http", "https"} and parsed_path.netloc:
                raw_url = path_str
            else:
                raw_url = f"{api_base.rstrip('/')}/files/download/?path={quote(path_str)}"

    if raw_url is None:
        raise ResourceResolutionError("Selected resource has no downloadable URL or path")
    url = _absolute_url(raw_url)
    if not allow_http and urlparse(url).scheme != "https":
        raise ResourceResolutionError("Resource resolution requires HTTPS unless HTTP is explicitly allowed")

    raw_id = _first_value(resource, _ID_FIELDS)
    raw_title = _first_value(resource, _TITLE_FIELDS)
    identifier = str(raw_id if raw_id is not None else raw_title or "").strip()
    title = str(raw_title if raw_title is not None else identifier).strip()
    if not identifier:
        raise ResourceResolutionError("Selected resource has no identifier")
    if not title:
        raise ResourceResolutionError("Selected resource has no title")

    raw_filename = _first_value(resource, _FILENAME_FIELDS)
    filename = _clean_filename(str(raw_filename)) if raw_filename is not None else _filename_from_url(url)
    if filename is None:
        raise ResourceResolutionError("Could not determine a safe filename from the selected resource")

    destination_dir = Path(destination_dir)
    destination = destination_dir / filename
    expected_size = _coerce_size(_first_value(resource, _SIZE_FIELDS))
    expected_sha256 = _coerce_sha256(_first_value(resource, _SHA_FIELDS))

    metadata: dict[str, str] = {}
    for key in ("category", "era", "album", "artist", "version", "original_key"):
        value = resource.get(key)
        if value not in (None, ""):
            if isinstance(value, dict) and "name" in value:
                metadata[key] = str(value["name"])
            else:
                metadata[key] = str(value)

    return AcquisitionItem(
        identifier=identifier,
        title=title,
        url=url,
        destination=destination,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
        metadata=metadata,
    )
